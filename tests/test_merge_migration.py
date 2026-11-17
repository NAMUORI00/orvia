import copy
import pathlib
import sys
import unittest
from unittest.mock import patch
sys.path.insert(0,str(pathlib.Path(__file__).resolve().parents[1]/'app'))
import merge_migration as migration
import hotops


class MergeMigrationTests(unittest.TestCase):
    def fixture(self):
        users=[dict(name='alpha',uid=12001),dict(name='beta',uid=12002)]
        sources={}
        for u in users:
            n,uid=u['name'],u['uid']
            sources[n]={
                'passwd':f'root:x:0:0:root:/root:/bin/bash\n{n}:x:{uid}:{uid}::/home/{n}:/bin/bash\n',
                'shadow':f'root:LOCK:0::::::\n{n}:HASH-{n}:20:0:99999:7:::\n',
                'group':f'root:x:0:\n{n}:x:{uid}:\norvia-research:x:60001:{n}\n',
                'gshadow':f'root:*::\n{n}:!::\norvia-research:!::{n}\n'}
        return users,sources

    def test_preserves_both_passwords_uids_and_shared_membership(self):
        users,sources=self.fixture()
        result=migration.merge_databases(sources,users,60001)
        for u in users:
            self.assertIn(f"{u['name']}:HASH-{u['name']}:",result['shadow'])
            self.assertIn(f"{u['name']}:x:{u['uid']}:",result['passwd'])
        self.assertIn('orvia-research:x:60001:alpha,beta',result['group'])
        self.assertIn('root:!:',result['shadow'])

    def test_conflicting_system_accounts_rejected(self):
        users,sources=self.fixture()
        sources['beta']['passwd']=sources['beta']['passwd'].replace('root:x:0:0:root','root:x:0:0:changed')
        with self.assertRaises(ValueError):migration.merge_databases(sources,users,60001)

    def test_duplicate_uid_rejected(self):
        users,sources=self.fixture()
        users[1]['uid']=12001
        sources['beta']['passwd']=sources['beta']['passwd'].replace('12002','12001')
        with self.assertRaises(ValueError):migration.merge_databases(sources,users,60001)

    def test_missing_password_rejected(self):
        users,sources=self.fixture()
        sources['beta']['shadow']='root:LOCK:0::::::\n'
        with self.assertRaises(ValueError):migration.merge_databases(sources,users,60001)

    def test_shared_action_uses_guarded_merge(self):
        with patch.object(migration,'submit',return_value={'ok':True}) as submit:
            self.assertEqual(hotops.dispatch({'action':'lab_share'}),{'ok':True})
            submit.assert_called_once()
