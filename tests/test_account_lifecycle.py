import pathlib
import sys
import tempfile
import unittest
from unittest.mock import patch
import subprocess
import tarfile

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1] / "app"))
import account_lifecycle
import hotops


class AccountLifecycleTests(unittest.TestCase):
    def test_shared_deletion_archives_home_and_preserves_peer(self):
        with tempfile.TemporaryDirectory() as directory:
            root=pathlib.Path(directory)
            admin=root/".admin/shared"
            admin.mkdir(parents=True)
            for name in ("student","peer"):
                (root/name).mkdir()
                (root/name/"research.txt").write_text(name+" data")
            records={"passwd":"student:x:12001:12001::/home/student:/bin/bash\npeer:x:12002:12002::/home/peer:/bin/bash\n", "shadow":"student:HASH:20000:0:99999:7:::\npeer:UNCHANGED:20000:0:99999:7:::\n", "group":"student:x:12001:\npeer:x:12002:\norvia-research:x:60001:student,peer\n", "gshadow":"student:!::\npeer:!::\norvia-research:!::student,peer\n"}
            for key,text in records.items():(admin/key).write_text(text)
            users=[dict(name=n,uid=12001+i,container="shared",port=2208) for i,n in enumerate(("student","peer"))]
            spec=dict(storage=str(root),account_layout="shared",prefix="x-",users=users)
            config=dict(labs={"lab":spec})
            obj=dict(Id="same",State={"Running":True},Mounts=[])
            req=dict(action="account_delete",lab="lab",user="student",confirm="lab",confirm_user="student",ack_delete="yes")
            job=dict(id="test",lab="lab",kind="account")
            state=root/"state";(state/"jobs").mkdir(parents=True)
            calls=[]
            def run(*args,**kwargs):
                calls.append(args)
                if args[:2]==("docker","top"):return "UID PID COMMAND\n12002 5 python"
                return subprocess.check_output(args,text=True).strip()
            with patch.object(hotops,"authorize",return_value=(config,spec,users[0],obj)),patch.object(hotops,"obj",return_value=obj),patch.object(hotops,"STATE",state),patch.object(hotops,"run",side_effect=run),patch.object(account_lifecycle.os.path,"ismount",return_value=True),patch.object(account_lifecycle,"validate_shared"),patch.object(account_lifecycle.recovery,"install",return_value={}),patch.object(hotops,"ETC",root):
                hotops.JOB_LOCK.acquire()
                account_lifecycle.worker(req,job)
            self.assertEqual(job["state"],"complete")
            self.assertFalse((root/"student").exists())
            self.assertEqual((root/"peer/research.txt").read_text(),"peer data")
            self.assertEqual([u["name"] for u in spec["users"]],["peer"])
            self.assertEqual((admin/"shadow").read_text(),"peer:UNCHANGED:20000:0:99999:7:::\n")
            with tarfile.open(pathlib.Path(job["backup"])/"home.tar") as archive:
                self.assertEqual(archive.extractfile("student/research.txt").read(),b"student data")
            self.assertFalse(any(args[:2] in (("docker","stop"),("docker","rm"),("docker","restart")) for args in calls))

    def test_last_account_cannot_be_deleted(self):
        with self.assertRaises(ValueError):
            account_lifecycle.validate(dict(action="account_delete", confirm_user="student", ack_delete="yes"), dict(users=[{}]), {"name":"student"}, {})

    def test_delete_needs_exact_account_confirmation(self):
        with self.assertRaises(ValueError):
            account_lifecycle.validate(dict(action="account_delete", confirm_user="other", ack_delete="yes"), dict(users=[{},{}]), {"name":"student"}, {})

    def test_running_user_blocks_backup_and_deletion(self):
        with tempfile.TemporaryDirectory() as directory:
            root=pathlib.Path(directory)
            (root/"student").mkdir()
            spec=dict(users=[{},{}],storage=str(root))
            obj=dict(Id="container",State={"Running":True},Mounts=[dict(Source=str(root/"student"),Destination="/home/student")])
            with patch.object(account_lifecycle.os.path,"ismount",return_value=True),patch.object(hotops,"run",return_value="UID PID COMMAND\n12001 101 python"):
                with self.assertRaises(ValueError):
                    account_lifecycle.validate(dict(action="account_backup"), spec, dict(name="student",uid=12001), obj)

    def test_idle_user_does_not_block_other_members(self):
        with tempfile.TemporaryDirectory() as directory:
            root=pathlib.Path(directory)
            (root/"student").mkdir()
            spec=dict(users=[{},{}],storage=str(root))
            obj=dict(Id="container",State={"Running":True},Mounts=[dict(Source=str(root/"student"),Destination="/home/student")])
            with patch.object(account_lifecycle.os.path,"ismount",return_value=True),patch.object(hotops,"run",return_value="UID PID COMMAND\n12002 101 python"):
                self.assertEqual(account_lifecycle.validate(dict(action="account_backup"),spec,dict(name="student",uid=12001),obj)[1],root/"student")

