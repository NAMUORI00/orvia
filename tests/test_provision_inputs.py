import pathlib, sys, unittest
from unittest.mock import patch

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1] / "app"))
import accounts, environments


class ProvisionInputs(unittest.TestCase):
    def test_official_image_only(self):
        self.assertEqual(
            environments.reference("cuda", "12.4.1-base-ubuntu22.04"),
            "nvidia/cuda:12.4.1-base-ubuntu22.04",
        )
        for p, t in [("other", "tag"), ("cuda", "tag;command"), ("cuda", "centos7")]:
            with self.assertRaises(ValueError):
                environments.reference(p, t)

    def test_duplicate_account_rejected(self):
        with self.assertRaises(ValueError):
            accounts.validate(
                {"new_user": "student", "password": "test-value-only"},
                {"labs": {"a": {"users": [{"name": "student"}]}}},
                {"storage": "/data"},
            )

    def test_missing_mount_rejected(self):
        with patch.object(accounts.os.path, "ismount", return_value=False):
            with self.assertRaises(ValueError):
                accounts.validate(
                    {"new_user": "student", "password": "test-value-only"},
                    {"labs": {}},
                    {"storage": "/data"},
                )
