import pathlib, sys, unittest

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1] / "app"))
import documents, account_profile


class Documents(unittest.TestCase):
    def test_home_only_guide_uses_current_allocation_and_roles(self):
        lab=dict(id='test',home_only=True,account_backend='native_etc',allocated_gb=5000,storage_gb=4959.4,users=[dict(name='person',port=2208)])
        accounts=[dict(name='person',permissions=dict(status='configured',container_sudo=False)),dict(name='manager',permissions=dict(status='configured',container_sudo=True))]
        for lang in ['ko','en']:
            d=documents.compose({'access_host':'server.test'},{},lab,accounts,lang)
            resources={r['id']:r['value'] for r in d['resources']}
            self.assertIn('5 TB',resources['storage'])
            self.assertIn('/home/',resources['home'])
            self.assertIn('manager',resources['permissions'])
            self.assertIn('passwd',resources['password_change'])
            self.assertNotIn('/shared',str(d))
            self.assertIn('2208',d['accounts'][0]['command'])

    def test_legacy_guide_does_not_gain_home_only_instructions(self):
        d=documents.compose({}, {}, dict(id='other',storage_gb=983.2), [])
        self.assertEqual(next(r['value'] for r in d['resources'] if r['id']=='storage'),'983.2 GB')
        self.assertNotIn('home',{r['id'] for r in d['resources']})

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

class AccountSelection(unittest.TestCase):
    def test_excludes_account_from_rows_and_resource_details(self):
        lab=dict(id='lab',home_only=True,users=[dict(name='student',port=2208),dict(name='admin',port=2208)])
        accounts=[dict(name='student',cpu=2,permissions=dict(container_sudo=False)),dict(name='admin',cpu=8,permissions=dict(container_sudo=True))]
        for lang in ['ko','en']:
            d=documents.compose({}, {}, lab, accounts,lang,selected_accounts=['student'])
            self.assertEqual([u['id'] for u in d['accounts']],['student'])
            self.assertNotIn('admin',str(d))
            self.assertEqual(next(r['value'] for r in d['resources'] if r['id']=='cpu'),'2 cores')
        self.assertEqual(len(lab['users']),2)
        self.assertEqual(len(accounts),2)
    def test_empty_and_foreign_selection_rejected(self):
        for selection in [[],['foreign']]:
            with self.assertRaises(ValueError): documents.compose({}, {}, dict(id='lab',users=[dict(name='student')]),[],selected_accounts=selection)
