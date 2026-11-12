import pathlib
import sys
import unittest
from unittest.mock import patch

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1] / "app"))
import hotops


class RestartBoundaryTests(unittest.TestCase):
    def setUp(self):
        self.obj = dict(
            Id="a" * 64,
            State=dict(StartedAt="old", Running=True),
            Mounts=[{"Source": "/data/lab/user"}],
        )
        self.authorized = ({}, {"prefix": "test-"}, {"name": "student"}, self.obj)
        self.req = dict(
            action="maintenance_restart",
            ack_downtime="yes",
            expected_id="a" * 12,
            expected_started="old",
        )

    def test_restart_requires_explicit_acknowledgement(self):
        self.req["ack_downtime"] = None
        with (
            patch.object(hotops, "authorize", return_value=self.authorized),
            patch.object(hotops, "run") as run,
        ):
            with self.assertRaises(ValueError):
                hotops.dispatch(self.req)
            run.assert_not_called()

    def test_stale_environment_rejected(self):
        self.req["expected_started"] = "different"
        with (
            patch.object(hotops, "authorize", return_value=self.authorized),
            patch.object(hotops, "run") as run,
        ):
            with self.assertRaises(ValueError):
                hotops.dispatch(self.req)
            run.assert_not_called()

    def test_only_selected_container_restarted(self):
        with (
            patch.object(hotops, "authorize", return_value=self.authorized),
            patch.object(hotops, "run") as run,
            patch.object(hotops, "obj", return_value=self.obj),
        ):
            hotops.dispatch(self.req)
            run.assert_called_once_with(
                "docker", "restart", "--time", "15", "test-student", timeout=90
            )
            self.assertFalse(hotops.JOB_LOCK.locked())

    def test_protection_gate_runs_before_restart(self):
        with (
            patch.object(hotops, "authorize", side_effect=PermissionError),
            patch.object(hotops, "run") as run,
        ):
            with self.assertRaises(PermissionError):
                hotops.dispatch(self.req)
            run.assert_not_called()

    def test_changed_mounts_report_failure(self):
        after = dict(self.obj, Mounts=[])
        with (
            patch.object(hotops, "authorize", return_value=self.authorized),
            patch.object(hotops, "run"),
            patch.object(hotops, "obj", return_value=after),
        ):
            with self.assertRaises(ValueError):
                hotops.dispatch(self.req)
            self.assertFalse(hotops.JOB_LOCK.locked())
