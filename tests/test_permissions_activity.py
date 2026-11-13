import pathlib, sys, unittest

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1] / "app"))
import permissions, documents, activity_view


class PermissionTests(unittest.TestCase):
    def test_new_account_inherits_container_sudo_policy(self):
        self.assertEqual(permissions.account_sudo_rule("student", False), "")
        self.assertIn(
            "student ALL=(ALL)", permissions.account_sudo_rule("student", True)
        )
        with self.assertRaises(ValueError):
            permissions.account_sudo_rule("bad;name", True)

    def test_writable_root_does_not_imply_sudo(self):
        p = permissions.describe({}, {}, {"HostConfig": {"ReadonlyRootfs": False}})
        self.assertFalse(p["container_sudo"])

    def test_mismatch_and_host_socket_are_flagged(self):
        p = permissions.describe(
            {"root_access": True}, {}, {"HostConfig": {"ReadonlyRootfs": True}}
        )
        self.assertEqual(p["status"], "review")
        p = permissions.describe(
            {},
            {},
            {"HostConfig": {}, "Mounts": [{"Destination": "/var/run/docker.sock"}]},
        )
        self.assertEqual(p["status"], "review")

    def test_profile_validation_and_legacy_input(self):
        self.assertTrue(
            permissions.requested({"root_access": "yes"})[1]["container_sudo"]
        )
        self.assertFalse(
            permissions.requested(
                {"permission_profile": "standard", "root_access": "yes"}
            )[1]["container_sudo"]
        )
        with self.assertRaises(ValueError):
            permissions.requested({"permission_profile": "host_admin"})

    def test_document_uses_policy_not_saved_text(self):
        policy = permissions.describe(
            {"root_access": True}, {}, {"HostConfig": {"ReadonlyRootfs": False}}
        )
        d = documents.compose(
            {"document_defaults": {"permissions_en": "OUTDATED"}},
            {},
            {"id": "lab"},
            [{"name": "a", "permissions": policy}],
            lang="en",
        )
        text = next(r["value"] for r in d["resources"] if r["id"] == "permissions")
        self.assertIn("Container sudo permitted", text)
        self.assertNotIn("OUTDATED", text)

    def test_activity_distinguishes_acceptance_and_result(self):
        records = activity_view.events(
            {
                "labs": [{"id": "x", "title": "Lab X"}],
                "events": [
                    {"lab": "x", "action": "backup", "result": "ok", "time": "new"},
                    {"action": "unrecognized", "result": "denied", "time": "old"},
                ],
            }
        )
        self.assertEqual(records[0]["label_result"], "요청 접수")
        self.assertEqual(records[0]["lab"], "Lab X")
        self.assertEqual(records[1]["code"], "unrecognized")
        self.assertEqual(records[1]["label_result"], "권한 거부")


class TemplateTests(unittest.TestCase):
    def test_templates_parse(self):
        import jinja2

        env = jinja2.Environment()
        root = pathlib.Path(__file__).resolve().parents[1] / "app/templates"
        for path in root.glob("*.html"):
            with self.subTest(template=path.name):
                env.parse(path.read_text(encoding="utf-8"))
