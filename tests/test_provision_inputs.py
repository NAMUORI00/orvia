import pathlib, sys, unittest
from unittest.mock import patch

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1] / "app"))
import accounts, environments, lifecycle, json


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


class ImageSources(unittest.TestCase):
    def test_only_matching_official_bases_are_default_choices(self):
        lab = {"title": "Lab", "users": [{"image": "sha256:lab", "container": "lab-user"}]}
        images = [{"Id": "sha256:lab", "RepoTags": ["custom:1"], "RootFS": {"Layers": ["a", "b", "c"]}}]
        bases = [
            {"RepoTags": ["nvidia/cuda:12.4.1-base-ubuntu22.04"], "RootFS": {"Layers": ["a", "b"]}},
            {"RepoTags": ["nvidia/cuda:other"], "RootFS": {"Layers": ["x"]}},
        ]
        with patch.object(lifecycle.hotops, "catalog", return_value={"labs": [lab]}), patch.object(
            lifecycle, "run", side_effect=[json.dumps(images), "nvidia/cuda:12.4.1-base-ubuntu22.04\nnvidia/cuda:other\ncustom:1", json.dumps(bases)]
        ):
            result = lifecycle.sources()
        self.assertEqual(len(result["bases"]), 1)
        self.assertEqual(result["bases"][0]["provider"], "cuda")
        self.assertEqual(result["registered"][0]["source"], "lab-user")
        self.assertEqual(result["registered"][0]["label"], "custom:1")

    def test_empty_catalog_has_no_invented_base(self):
        with patch.object(lifecycle.hotops, "catalog", return_value={"labs": []}), patch.object(lifecycle, "run", return_value=""):
            self.assertEqual(lifecycle.sources(), {"registered": [], "bases": []})
