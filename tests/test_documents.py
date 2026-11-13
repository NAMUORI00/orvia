import pathlib, sys, unittest

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1] / "app"))
import documents, account_profile


class Documents(unittest.TestCase):
    def test_missing_fields(self):
        d = documents.compose({}, {}, {"id": "test"}, [])
        self.assertEqual(d["host"], "N/A")
        self.assertTrue(all(r["value"] == "N/A" for r in d["resources"]))
        self.assertEqual(d["accounts"], [])

    def test_config_not_request_and_no_passwords(self):
        d = documents.compose(
            {
                "access_host": "server.test",
                "document_labs": {
                    "test": {
                        "extra_fields": [
                            {
                                "id": "x",
                                "label_en": "Support",
                                "value_en": "Contact office",
                            }
                        ]
                    }
                },
            },
            {},
            {
                "id": "test",
                "users": [
                    {
                        "name": "tester",
                        "port": 2200,
                        "password": "SECRET",
                        "profile": {"display_name": "Name"},
                    }
                ],
            },
            [],
            lang="en",
        )
        self.assertEqual(d["accounts"][0]["command"], "ssh -p 2200 tester@server.test")
        self.assertNotIn("SECRET", str(d))
        self.assertEqual(d["resources"][-1]["value"], "Contact office")

    def test_version_and_input_boundaries(self):
        with self.assertRaises(ValueError):
            documents.compose(
                {"document_defaults": {"schema_version": 99}}, {}, {"id": "test"}, []
            )
        with self.assertRaises(ValueError):
            documents.compose({"access_host": "host; bad"}, {}, {"id": "test"}, [])

    def test_profile_no_invented_values(self):
        d = account_profile.clean({"password": "SECRET", "role": "root"})
        self.assertIsNone(d["joined_on"])
        self.assertNotIn("password", d)
        self.assertNotIn("role", d)

    def test_profile_dates(self):
        with self.assertRaises(ValueError):
            account_profile.clean(
                {"joined_on": "2026-11-13", "expires_on": "2025-01-01"}
            )
