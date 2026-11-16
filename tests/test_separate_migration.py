import pathlib
import sys
import unittest
from unittest.mock import patch
sys.path.insert(0,str(pathlib.Path(__file__).resolve().parents[1]/"app"))
import separate_migration as migration
import hotops
import reconfigure


class SeparateMigrationTests(unittest.TestCase):
    def test_shadow_keeps_only_target_credential(self):
        result=migration.account_database("root:ROOT:1:0:9:7:::\namin:KEEP:1:0:9:7:::\npeer:SECRET:1:0:9:7:::\n", "shadow", "amin", {"amin","peer"})
        self.assertIn("amin:KEEP:",result)
        self.assertIn("root:!:",result)
        self.assertNotIn("SECRET",result)
        self.assertNotIn("peer:",result)

    def test_common_group_contains_only_this_user(self):
        result=migration.account_database("orvia-research:x:60001:amin,peer\namin:x:12001:\npeer:x:12002:\n","group","amin",{"amin","peer"})
        self.assertEqual(result,"orvia-research:x:60001:amin\namin:x:12001:\n")

    def test_cpu_or_ssh_process_blocks_conversion(self):
        spec=dict(prefix="x-",users=[dict(name="amin",uid=12001,container="shared")])
        obj=dict(Id="x",State={"StartedAt":"now"},HostConfig={"ReadonlyRootfs":True})
        req=dict(ack_downtime="yes",ack_recreate="yes",expected_fingerprint=reconfigure.fingerprint([obj]))
        with patch.object(hotops,"authorize",return_value=({},spec,{},obj)),patch.object(migration,"validate_shared"),patch.object(migration,"require_idle"),patch.object(hotops,"run",return_value="UID PID COMMAND\n12001 123 python"):
            with self.assertRaises(ValueError):migration.validate(req)


    def test_layout_dispatch_keeps_legacy_shared_labs_supported(self):
        import accounts, shared_accounts
        for layout, expected in [("separate", accounts), ("shared", shared_accounts)]:
            with patch.object(hotops, "cfg", return_value={"labs":{"lab":{"account_layout":layout}}}), patch.object(expected, "submit", return_value={"ok":True}) as submit:
                result=hotops.dispatch({"action":"account_create", "lab":"lab"})
                self.assertEqual(result,{"ok":True})
                submit.assert_called_once()

    def test_writable_system_prevents_loss_of_os_changes(self):
        obj={"Id":"x", "State":{"StartedAt":"now"}, "HostConfig":{"ReadonlyRootfs":False}}
        spec={"prefix":"x-", "users":[{"name":"amin", "container":"shared"}]}
        req={"ack_downtime":"yes", "ack_recreate":"yes", "expected_fingerprint":reconfigure.fingerprint([obj])}
        with patch.object(hotops,"authorize",return_value=({},spec,{},obj)), patch.object(migration,"validate_shared"):
            with self.assertRaises(ValueError): migration.validate(req)
