import json, os, pathlib, sys, tempfile, unittest
from unittest.mock import patch

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1] / "app"))
import storage_usage, telemetry, hotops


class StorageTests(unittest.TestCase):
    def test_hidden_cache_and_hardlink_accounting(self):
        with tempfile.TemporaryDirectory() as folder:
            root = pathlib.Path(folder)
            (root / "student" / ".cache").mkdir(parents=True)
            f = root / "student" / ".cache" / "weights"
            f.write_bytes(b"x" * 8192)
            os.link(f, root / "student" / "linked")
            (root / ".admin").mkdir()
            (root / ".admin" / "secret").write_bytes(b"x" * 100000)
            (root / "external").symlink_to("/etc", target_is_directory=True)
            result = storage_usage.scan(str(root))
            self.assertFalse(result["partial"])
            self.assertNotIn("external", result["nodes"])
            self.assertNotIn(".admin", result["nodes"])
            self.assertIn("student/.cache", result["nodes"])
            leaf_total = sum(
                v["bytes"] for p, v in result["nodes"].items() if not v["directory"]
            )
            self.assertEqual(leaf_total, f.stat().st_blocks * 512)

    def test_sparse_file_uses_allocated_blocks(self):
        with tempfile.TemporaryDirectory() as folder:
            f = pathlib.Path(folder) / "sparse"
            with f.open("wb") as stream:
                stream.truncate(1024**3)
            result = storage_usage.scan(folder)
            self.assertEqual(
                result["nodes"]["sparse"]["bytes"], f.stat().st_blocks * 512
            )

    def test_budget_marks_partial(self):
        with tempfile.TemporaryDirectory() as folder:
            (pathlib.Path(folder) / "file").touch()
            self.assertTrue(storage_usage.scan(folder, max_entries=0)["partial"])


class TelemetryTests(unittest.TestCase):
    def test_network_totals_exclude_restarts_gaps_and_resets(self):
        def point(ts, count, started="one", lab="lab"):
            return dict(
                ts=ts,
                accounts=[
                    dict(
                        lab=lab,
                        user="u",
                        identity="id",
                        started=started,
                        network=dict(
                            rx=count,
                            tx=count * 2,
                            rx_packets=count,
                            tx_packets=count,
                            errors=0,
                            drops=0,
                        ),
                    )
                ],
            )

        records = [
            point(0, 0),
            point(60, 100),
            point(120, 10, "two"),
            point(180, 20, "two"),
            point(600, 100, "two"),
            point(660, 5, "two"),
            point(720, 15, "two"),
        ]
        r = telemetry.network_summary(records)[0]
        self.assertEqual((r["rx"], r["tx"], r["seconds"]), (120, 240, 180))
        self.assertEqual(r["peak"], 5)
        self.assertEqual(r["peak_ts"], 60)

    def test_network_history_keeps_error_deltas_and_lab_identity(self):
        def point(ts, errors):
            return dict(
                ts=ts,
                accounts=[
                    dict(
                        lab=lab,
                        user="same",
                        identity=lab,
                        started="one",
                        network=dict(
                            rx=ts,
                            tx=ts,
                            rx_packets=0,
                            tx_packets=0,
                            errors=errors,
                            drops=0,
                        ),
                    )
                    for lab in ("a", "b")
                ],
            )

        result = telemetry.network_summary([point(0, 10), point(60, 12)])
        self.assertEqual(len(result), 2)
        self.assertEqual(result[0]["errors"], 2)
        self.assertEqual(result[0]["incidents"], [dict(ts=60, errors=2, drops=0)])

    def test_network_counters_ignore_loopback(self):
        raw = "header\nheader\nlo: 99 9 0 0 0 0 0 0 99 9 0 0 0 0 0 0\neth0: 100 2 1 3 0 0 0 0 200 4 5 6 0 0 0 0"
        with patch.object(pathlib.Path, "read_text", return_value=raw):
            result = telemetry.network(1)
        self.assertEqual(
            result, dict(rx=100, tx=200, rx_packets=2, tx_packets=4, drops=9, errors=6)
        )

    def test_changes_are_edge_triggered(self):
        old = dict(
            accounts=[
                dict(container="a", user="u", lab="lab", running=True, started="one")
            ],
            disks=[dict(lab="lab", title="Lab", mounted=True, capacity=100, used=80)],
        )
        new = json.loads(json.dumps(old))
        new["accounts"][0]["running"] = False
        new["disks"][0]["used"] = 95
        self.assertEqual(
            [e[1] for e in telemetry.changes(old, new)], ["stopped", "storage_high"]
        )
        self.assertEqual(telemetry.changes(new, new), [])

    def test_history_no_samples(self):
        with (
            tempfile.TemporaryDirectory() as folder,
            patch.object(hotops, "STATE", pathlib.Path(folder)),
        ):
            data = telemetry.read()
            self.assertIsNone(data["latest"])
            self.assertEqual(data["history"], [])
