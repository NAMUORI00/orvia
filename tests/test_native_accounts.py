import pathlib
import sys
import tempfile
import unittest
from unittest.mock import patch
sys.path.insert(0,str(pathlib.Path(__file__).resolve().parents[1]/'app'))
import hotops
import native_accounts
import shared_accounts


class NativeAccountTests(unittest.TestCase):
    def test_password_uses_native_locking_without_secret_arguments(self):
        with patch.object(hotops,'run') as run:
            native_accounts.set_password('container','testuser','test-password')
        args=run.call_args.args
        self.assertEqual(args,('docker','exec','-i','container','chpasswd','-e'))
        self.assertNotIn('test-password',str(run.call_args))
        self.assertTrue(run.call_args.kwargs['input'].startswith('testuser:$6$'))

    def test_writable_etc_mount_validated(self):
        with tempfile.TemporaryDirectory() as d:
            root=pathlib.Path(d)
            spec=dict(storage=d,account_layout='shared',account_backend='native_etc')
            obj=dict(State={'Running':True},Mounts=[dict(Destination='/home',Source=d,RW=True),dict(Destination='/etc',Source=str(root/'.admin/shared/etc'),RW=True)])
            with patch.object(shared_accounts.os.path,'ismount',return_value=True):
                self.assertEqual(shared_accounts.validate_shared(spec,obj),root)
                obj['Mounts'][1]['RW']=False
                with self.assertRaises(ValueError):shared_accounts.validate_shared(spec,obj)

    def test_native_dispatch_does_not_write_stale_shadow(self):
        with patch.object(hotops,'authorize',return_value=({}, {'account_backend':'native_etc'}, {'name':'testuser'}, {'Id':'container'})),patch.object(shared_accounts,'validate_shared'),patch.object(native_accounts,'set_password') as native,patch.object(shared_accounts,'write_bound') as write:
            shared_accounts.password(dict(password='test-password',password_confirm='test-password'))
            native.assert_called_once_with('container','testuser','test-password')
            write.assert_not_called()
