import copy, pathlib, sys, unittest
from unittest.mock import patch

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1] / "app"))
import reconfigure, recovery


class Reconfiguration(unittest.TestCase):
    def test_gpu_payload_preserves_data_and_image(self):
        original = dict(
            Id="a" * 64,
            Image="sha256:old",
            Config=dict(
                Image="tag", Env=["HOME=/home/research", "NVIDIA_VISIBLE_DEVICES=old"]
            ),
            HostConfig=dict(
                Devices=[
                    dict(
                        PathOnHost="/dev/nvidia7",
                        PathInContainer="/dev/nvidia7",
                        CgroupPermissions="rw",
                    ),
                    dict(
                        PathOnHost="/dev/nvidiactl",
                        PathInContainer="/dev/nvidiactl",
                        CgroupPermissions="rw",
                    ),
                ],
                DeviceRequests=[],
                Binds=["/data:/home/research"],
                PortBindings={"2222/tcp": [{"HostPort": "2200"}]},
                Memory=5000,
            ),
            NetworkSettings=dict(Networks={}),
        )
        before = copy.deepcopy(original)
        p = reconfigure.payload(original, [0, 1], ["g0", "g1"])
        self.assertEqual(original, before)
        self.assertEqual(p["HostConfig"]["Binds"], original["HostConfig"]["Binds"])
        self.assertEqual(p["Image"], "sha256:old")
        self.assertEqual(p["HostConfig"]["Memory"], 5000)
        self.assertEqual(
            p["HostConfig"]["DeviceRequests"][0]["DeviceIDs"], ["g0", "g1"]
        )
        self.assertEqual(
            p["Env"], ["HOME=/home/research", "NVIDIA_VISIBLE_DEVICES=g0,g1"]
        )

    def test_legacy_recovery_does_not_stop_lab_service(self):
        with (
            patch.object(recovery.subprocess, "run") as sub,
            patch.object(recovery.hotops, "run") as run,
        ):
            sub.return_value.returncode = 0
            recovery.pause({"service": "h200-research.service"})
            self.assertEqual(
                run.call_args.args,
                (
                    "systemctl",
                    "stop",
                    "h200-research-recover.timer",
                    "h200-research-recover.service",
                ),
            )

    def test_acknowledgement_before_inventory(self):
        with (
            patch.object(
                reconfigure.hotops,
                "cfg",
                return_value={"labs": {"test": {"gpu": "g0"}}, "write_labs": ["test"]},
            ),
            patch.object(reconfigure, "inventory") as inv,
        ):
            with self.assertRaises(ValueError):
                reconfigure.apply({"lab": "test", "confirm": "test"})
            inv.assert_not_called()

    def test_fingerprint_changes_when_restarted(self):
        a = [{"Id": "a", "State": {"StartedAt": "one"}}]
        b = [{"Id": "a", "State": {"StartedAt": "two"}}]
        self.assertNotEqual(reconfigure.fingerprint(a), reconfigure.fingerprint(b))
