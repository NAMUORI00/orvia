import copy
import pathlib
import sys
import unittest
from unittest.mock import patch

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1] / "app"))
import maintenance
import hotops


class RecreateTests(unittest.TestCase):
    def test_payload_pins_image_and_preserves_environment_and_mount_config(self):
        original = dict(
            Id="a" * 64,
            Image="sha256:immutable",
            Config=dict(
                Image="moving:tag",
                Env=["EXAMPLE=one"],
                Entrypoint=["/entry"],
                Labels={"lab": "sample"},
            ),
            HostConfig=dict(
                Mounts=[dict(Type="bind", Source="/data", Target="/home/user")],
                DeviceRequests=[{"DeviceIDs": ["gpu0"]}],
            ),
            NetworkSettings=dict(
                Networks={"test-network": dict(Aliases=["a" * 12, "alias"])}
            ),
        )
        saved = copy.deepcopy(original)
        payload = maintenance.create_payload(original)
        self.assertEqual(payload["Image"], "sha256:immutable")
        self.assertEqual(payload["Env"], ["EXAMPLE=one"])
        self.assertEqual(payload["HostConfig"], original["HostConfig"])
        self.assertEqual(
            payload["NetworkingConfig"]["EndpointsConfig"]["test-network"]["Aliases"],
            ["alias"],
        )
        self.assertEqual(original, saved)

    def test_writable_environment_rejected(self):
        with self.assertRaises(ValueError):
            maintenance.validate(
                dict(managed=True), {}, dict(HostConfig=dict(ReadonlyRootfs=False))
            )

    def test_protected_lab_rejected_before_recreation(self):
        with (
            patch.object(hotops, "authorize", side_effect=PermissionError),
            patch.object(maintenance, "recreate") as recreate,
        ):
            with self.assertRaises(PermissionError):
                hotops.dispatch(dict(action="maintenance_recreate"))
            recreate.assert_not_called()

    def test_requires_both_confirmations(self):
        with patch.object(maintenance, "engine") as engine:
            with self.assertRaises(ValueError):
                maintenance.recreate(dict(ack_downtime="yes"), {}, {}, {}, {})
            engine.assert_not_called()
