import pathlib
import sys
import unittest
from unittest.mock import patch

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1] / "app"))
import broker
import hotops
import maintenance


class OperatingScopeTests(unittest.TestCase):
    def test_registered_labs_are_operable_without_sandbox_flag(self):
        spec = {"gpu": "gpu-a", "users": [{"name": "researcher"}]}
        config = {
            "labs": {"research": spec},
            "write_labs": ["research"],
            "write_gpus": ["gpu-a"],
        }
        for action in ["start", "stop", "password", "gpu_test", "grow"]:
            self.assertIs(broker.authorize(config, action, "research"), spec)

    def test_removing_limits_requires_explicit_restart_confirmation(self):
        original = {"HostConfig": {"Memory": 1073741824, "NanoCpus": 1000000000}}
        with (
            patch.object(hotops, "authorize", return_value=({}, {}, {}, original)),
            patch.object(maintenance, "recreate") as recreate,
        ):
            with self.assertRaises(ValueError):
                hotops.dispatch({"action": "resources", "cpu": "0", "ram": "0"})
            recreate.assert_not_called()

    def test_removing_limits_uses_preserving_recreation(self):
        original = {
            "Id": "a" * 64,
            "State": {"StartedAt": "start"},
            "HostConfig": {"Memory": 1073741824, "NanoCpus": 1000000000},
        }
        with (
            patch.object(hotops, "authorize", return_value=({}, {}, {}, original)),
            patch.object(maintenance, "recreate") as recreate,
        ):
            hotops.dispatch(
                {"action": "resources", "cpu": "0", "ram": "0", "ack_downtime": "yes"}
            )
            self.assertEqual(recreate.call_args.kwargs["resource_limits"]["Memory"], 0)
            self.assertEqual(recreate.call_args.args[0]["ack_recreate"], "yes")
