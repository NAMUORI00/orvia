import copy
import pathlib
import sys
import unittest
import tempfile

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1] / "app"))
import lifecycle


class ProvisionBoundary(unittest.TestCase):
    def test_storage_name_is_independent_of_lab_id(self):
        with tempfile.TemporaryDirectory() as folder:
            root = pathlib.Path(folder)
            base, disk = lifecycle.storage_paths(
                root, dict(id="sample", storage_name="another-lab")
            )
            self.assertEqual(base, root / "another-lab")
            self.assertEqual(disk, root / "another-lab.ext4")

    def test_storage_name_defaults_for_older_plans(self):
        self.assertEqual(lifecycle.storage_name(dict(id="sample")), "sample")

    def test_storage_path_injection_rejected(self):
        for name in [
            "../other",
            "/etc",
            "a/b",
            "a\\b",
            ".",
            "name.ext4",
            "a\n",
            "-bad",
        ]:
            with self.subTest(name=name), self.assertRaises(ValueError):
                lifecycle.storage_name(dict(id="sample", storage_name=name))

    def test_existing_folder_or_disk_rejected(self):
        with tempfile.TemporaryDirectory() as folder:
            root = pathlib.Path(folder)
            (root / "sample").mkdir()
            with self.assertRaises(ValueError):
                lifecycle.storage_paths(root, dict(id="sample"))
            (root / "sample").rmdir()
            (root / "sample.ext4").touch()
            with self.assertRaises(ValueError):
                lifecycle.storage_paths(root, dict(id="sample"))

    @unittest.skipIf(sys.platform == "win32", "Linux deployment boundary")
    def test_broken_symlink_rejected(self):
        with tempfile.TemporaryDirectory() as folder:
            root = pathlib.Path(folder)
            (root / "sample").symlink_to(root / "missing")
            with self.assertRaises(ValueError):
                lifecycle.storage_paths(root, dict(id="sample"))

    def setUp(self):
        self.p = dict(
            id="sample",
            user="student",
            gpu="gpu-test",
            storage_gb=5000,
            port=2220,
            uid=12001,
            replace="sandbox",
            replace_users=["testuser"],
        )
        self.c = dict(
            write_gpus=["gpu-test"],
            write_labs=["sandbox"],
            provision_max_gb=5000,
            labs={
                "sandbox": dict(
                    sandbox=True, gpu="gpu-test", users=[{"name": "testuser"}]
                )
            },
        )

    def test_approved_replacement(self):
        lifecycle.validate(self.p, self.c)

    def test_protected_gpu(self):
        self.p["gpu"] = "gpu-production"
        with self.assertRaises(PermissionError):
            lifecycle.validate(self.p, self.c)

    def test_production_cannot_be_replaced(self):
        self.c["labs"]["sandbox"]["sandbox"] = False
        with self.assertRaises(PermissionError):
            lifecycle.validate(self.p, self.c)

    def test_membership_drift(self):
        self.c["labs"]["sandbox"]["users"].append({"name": "new-researcher"})
        with self.assertRaises(ValueError):
            lifecycle.validate(self.p, self.c)

    def test_over_allocation(self):
        self.p["storage_gb"] = 5001
        with self.assertRaises(ValueError):
            lifecycle.validate(self.p, self.c)

    def test_plan_traversal(self):
        with self.assertRaises(ValueError):
            lifecycle.read_plan("../../policy")

    def test_duplicate_lab(self):
        self.c["labs"]["sample"] = copy.deepcopy(self.c["labs"]["sandbox"])
        with self.assertRaises(ValueError):
            lifecycle.validate(self.p, self.c)
