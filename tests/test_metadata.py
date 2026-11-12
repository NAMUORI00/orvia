import copy
import pathlib
import sys
import unittest
from unittest.mock import patch

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1] / "app"))
import hotops


class MetadataTests(unittest.TestCase):
    def setUp(self):
        self.c = dict(
            labs={
                "sample": dict(
                    title="Original",
                    gpu="g4",
                    users=[dict(name="user")],
                    storage="/data/sample",
                )
            },
            write_labs=["sample"],
            write_gpus=["g4"],
        )

    def test_name_edit_preserves_resources_without_docker_calls(self):
        original = copy.deepcopy(self.c)
        with (
            patch.object(hotops, "cfg", return_value=self.c),
            patch.object(hotops, "save") as save,
            patch.object(hotops, "run") as run,
        ):
            hotops.dispatch(
                dict(action="metadata", lab="sample", confirm="sample", title="Updated")
            )
            run.assert_not_called()
            self.assertEqual(
                save.call_args.args[1]["labs"]["sample"]["title"], "Updated"
            )
            self.c["labs"]["sample"]["title"] = "Original"
            self.assertEqual(self.c, original)

    def test_protected_lab_rejected_before_write(self):
        self.c["write_labs"] = []
        with (
            patch.object(hotops, "cfg", return_value=self.c),
            patch.object(hotops, "save") as save,
        ):
            with self.assertRaises(PermissionError):
                hotops.dispatch(
                    dict(
                        action="metadata",
                        lab="sample",
                        confirm="sample",
                        title="Updated",
                    )
                )
            save.assert_not_called()

    def test_wrong_confirmation_rejected(self):
        with (
            patch.object(hotops, "cfg", return_value=self.c),
            patch.object(hotops, "save") as save,
        ):
            with self.assertRaises(ValueError):
                hotops.dispatch(
                    dict(
                        action="metadata",
                        lab="sample",
                        confirm="other",
                        title="Updated",
                    )
                )
            save.assert_not_called()
