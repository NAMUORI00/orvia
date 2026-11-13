import json
import pathlib
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1] / "app"))
import telemetry, history_store, hotops


def sample(ts, value):
    return dict(
        ts=ts,
        load=1,
        memory_used=100,
        memory_total=1000,
        cpu_util=value,
        gpus=[dict(util=value)],
        disks=[],
        accounts=[
            dict(
                lab="lab",
                user="u",
                container="c",
                identity="id",
                started="one",
                running=True,
                cpu=value,
                rates=dict(rx=1, tx=2),
                processes=[],
                network=dict(
                    rx=value,
                    tx=value * 2,
                    rx_packets=value,
                    tx_packets=value,
                    errors=0,
                    drops=0,
                ),
            )
        ],
    )


class HistoryTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.patch = patch.object(hotops, "STATE", pathlib.Path(self.tmp.name))
        self.patch.start()

    def tearDown(self):
        self.patch.stop()
        self.tmp.cleanup()

    def insert(self, c, ts, value):
        c.execute(
            "INSERT INTO samples VALUES(?,?)", (ts, json.dumps(sample(ts, value)))
        )

    def test_archive_preserves_totals_at_raw_boundary(self):
        with telemetry.database() as c:
            for ts in (0, 60, 840, 900, 960):
                self.insert(c, ts, ts)
            history_store.maintain(c, 1800, telemetry.network_summary)
            expected = telemetry.network_summary(
                [sample(ts, ts) for ts in (0, 60, 840, 900, 960)]
            )[0]
            c.execute("DELETE FROM samples WHERE ts<840")
            with patch.object(history_store.time, "time", return_value=1000000):
                result = history_store.query(c, 0, 1800, telemetry.network_summary)
            self.assertEqual(result["network_usage"][0]["rx"], expected["rx"])
            self.assertEqual(result["network_usage"][0]["seconds"], expected["seconds"])
            self.assertTrue(result["archive"])

    def test_bounded_rollup_and_retention(self):
        with telemetry.database() as c:
            for ts in range(0, 9000, 900):
                self.insert(c, ts, ts)
            history_store.maintain(c, 10000, telemetry.network_summary)
            self.assertEqual(c.execute("SELECT count(*) FROM rollups").fetchone()[0], 4)
            self.assertEqual(
                c.execute("SELECT count(*) FROM samples").fetchone()[0], 10
            )
            for _ in range(3):
                history_store.maintain(c, 10 * 86400, telemetry.network_summary)
            self.assertEqual(c.execute("SELECT count(*) FROM samples").fetchone()[0], 1)
            history_store.settings(c, dict(raw_days=1, archive_days=30))
            history_store.maintain(c, 40 * 86400, telemetry.network_summary)
            self.assertEqual(c.execute("SELECT count(*) FROM rollups").fetchone()[0], 0)

    def test_summary_average_max_and_event_date_bounds(self):
        with telemetry.database() as c:
            self.insert(c, 60, 10)
            self.insert(c, 120, 30)
            c.execute("INSERT INTO events VALUES(?,?,?,?)", (60, "u", "started", "lab"))
            c.execute(
                "INSERT INTO events VALUES(?,?,?,?)", (2000, "u", "stopped", "lab")
            )
            history_store.maintain(c, 900, telemetry.network_summary)
            payload = json.loads(c.execute("SELECT payload FROM rollups").fetchone()[0])
            self.assertEqual(payload["point"]["cpu_util"], 20)
            self.assertEqual(payload["point"]["peak"]["cpu_util"], 30)
            self.assertEqual(
                len(
                    history_store.query(c, 0, 900, telemetry.network_summary)["events"]
                ),
                1,
            )

    def test_settings_validation_and_empty_date(self):
        self.assertEqual(telemetry.retention(), dict(raw_days=7, archive_days=90))
        with self.assertRaises(ValueError):
            telemetry.retention(dict(raw_days=30, archive_days=999))
        with self.assertRaises(ValueError):
            telemetry.read(start=1, end=32 * 86400)
        self.assertIsNone(telemetry.read(start=1, end=100)["latest"])
