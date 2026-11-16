import pathlib
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1] / "app"))
import hotops
import shared_accounts
import reconfigure
import shared_migration


class SharedAccountTests(unittest.TestCase):
    def test_password_changes_only_target_without_restart(self):
        import crypt
        with tempfile.TemporaryDirectory() as directory:
            root = pathlib.Path(directory)
            admin = root / ".admin/shared"
            admin.mkdir(parents=True)
            path = admin / "shadow"
            other = "hasnain:UNCHANGED:20000:0:99999:7:::\n"
            path.write_text(other + "amin:OLD:20000:0:99999:7:::\n")
            inode = path.stat().st_ino
            spec = dict(storage=str(root), account_layout="shared")
            obj = dict(Mounts=[dict(Destination="/etc/shadow", Source=str(path))])
            with patch.object(hotops, "authorize", return_value=({}, spec, {"name":"amin"}, obj)), patch.object(shared_accounts.os.path, "ismount", return_value=True), patch.object(hotops, "run") as run:
                shared_accounts.password(dict(password="test-new-password", password_confirm="test-new-password"))
            rows = path.read_text().splitlines()
            self.assertEqual(rows[0] + "\n", other)
            hashed = rows[1].split(":")[1]
            self.assertEqual(crypt.crypt("test-new-password", hashed), hashed)
            self.assertEqual(path.stat().st_ino, inode)
            run.assert_not_called()

    def test_mismatched_password_confirmation_rejected(self):
        with patch.object(hotops, "authorize") as auth:
            with self.assertRaises(ValueError):
                shared_accounts.password(dict(password="test-password", password_confirm="different"))
            auth.assert_not_called()

    def test_idle_gpu_with_live_process_is_blocked(self):
        with patch.object(hotops, "run", return_value="gpu3, 123"):
            with self.assertRaises(ValueError):
                shared_migration.require_idle({"gpu": "gpu3"})

    def test_unknown_gpu_state_is_blocked(self):
        with patch.object(hotops, "run", side_effect=["", "gpu3, N/A, 1"]):
            with self.assertRaises(ValueError):
                shared_migration.require_idle({"gpu": "gpu3"})

    def test_idle_selected_gpu_ignores_other_labs(self):
        with patch.object(hotops, "run", side_effect=["gpu7, 123", "gpu3, 0, 1\ngpu7, 100, 90000"]):
            shared_migration.require_idle({"gpu": "gpu3"})

    def test_bound_file_inode_and_existing_accounts_are_preserved(self):
        with tempfile.TemporaryDirectory() as directory:
            path = pathlib.Path(directory) / "passwd"
            original = "hasnain:x:12000:12000::/home/hasnain:/bin/bash\n"
            path.write_text(original)
            inode = path.stat().st_ino
            shared_accounts.write_bound(path, original + "amin:x:12001:12001::/home/amin:/bin/bash\n")
            self.assertEqual(path.stat().st_ino, inode)
            self.assertTrue(path.read_text().startswith(original))

    def test_legacy_layout_is_not_silently_recreated(self):
        with patch.object(hotops, "run") as run:
            with self.assertRaises(ValueError):
                shared_accounts.validate_shared({"storage": "/unused"}, {})
            run.assert_not_called()

    def test_shared_container_fingerprint_not_multiplied_by_users(self):
        obj = {"Id": "same", "State": {"StartedAt": "same"}}
        self.assertEqual(reconfigure.fingerprint([obj]), reconfigure.fingerprint([obj, obj]))

    def test_add_account_keeps_container_and_port_and_existing_shadow(self):
        with tempfile.TemporaryDirectory() as directory:
            root = pathlib.Path(directory)
            admin = root / ".admin/shared"
            admin.mkdir(parents=True)
            content = {
                "passwd": "hasnain:x:12000:12000::/home/hasnain:/bin/bash\n",
                "shadow": "hasnain:EXISTING_HASH:20000:0:99999:7:::\n",
                "group": "hasnain:x:12000:\norvia-research:x:60001:hasnain\n",
                "gshadow": "hasnain:!::\norvia-research:!::hasnain\n",
            }
            for key, value in content.items():
                (admin / key).write_text(value)
            user = dict(name="hasnain", uid=12000, port=2208, container="existing")
            spec = dict(storage=str(root), prefix="lh-", account_layout="shared", users=[user])
            cfg = dict(labs={"byun": spec})
            obj = {"State": {"Running": True}, "Mounts": [dict(Destination="/home", Source=str(root), RW=True)] + [dict(Destination="/etc/" + k, Source=str(admin / k), RW=False) for k in content]}
            with patch.object(hotops, "authorize", return_value=(cfg, spec, user, obj)), patch.object(shared_accounts.os.path, "ismount", return_value=True), patch.object(shared_accounts.os, "chown"), patch.object(hotops, "run", return_value="12001") as run, patch.object(hotops, "save"):
                shared_accounts.submit(dict(new_user="amin", password="test-only-password"))
            self.assertEqual(spec["users"][-1]["container"], "existing")
            self.assertEqual(spec["users"][-1]["port"], 2208)
            self.assertTrue((admin / "shadow").read_text().startswith(content["shadow"]))
            self.assertEqual((root / "amin").stat().st_mode & 0o777, 0o700)
            run.assert_called_once_with("docker", "exec", "existing", "id", "-u", "amin")


if __name__ == "__main__":
    unittest.main()
