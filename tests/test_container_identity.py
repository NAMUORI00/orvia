import json
import pathlib
import sys
import tempfile
import unittest
from unittest.mock import patch
sys.path.insert(0,str(pathlib.Path(__file__).resolve().parents[1]/"app"))
import container_identity as ci
import hotops

class RenameTests(unittest.TestCase):
    def test_invalid_name_never_authorizes(self):
        with patch.object(hotops,'authorize') as auth:
            with self.assertRaises(ValueError): ci.rename({'container_name':'../bad'})
            auth.assert_not_called()

    def test_exact_values_only(self):
        self.assertEqual(ci.replace_name({'container':'old','path':'/raid/old'},'old','new'),{'container':'new','path':'/raid/old'})

    def test_shared_users_and_recovery_updated_without_restart(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=pathlib.Path(tmp); rec=root/'recovery.json'
            rec.write_text(json.dumps({'containers':[{'name':'old'}]}))
            spec={'prefix':'lh-', 'users':[{'name':'a','container':'old'},{'name':'b','container':'old'}]}
            c={'labs':{'lab':spec}}
            obj={'Id':'a'*64,'State':{'StartedAt':'t'}}
            req={'lab':'lab','container_name':'new','expected_id':'a'*12,'expected_started':'t'}
            with patch.object(hotops,'ETC',root), patch.object(hotops,'authorize',return_value=(c,spec,spec['users'][0],obj)), patch.object(hotops,'obj',return_value=obj), patch.object(hotops,'run',return_value='old') as run, patch.object(ci.recovery,'recovery_path',return_value=rec), patch.object(ci.recovery,'pause',return_value=True), patch.object(ci.recovery,'resume'):
                ci.rename(req)
                self.assertEqual([u['container'] for u in json.loads((root/'policy.json').read_text())['labs']['lab']['users']],['new','new'])
                self.assertEqual(json.loads(rec.read_text())['containers'][0]['name'],'new')
                self.assertFalse(any('restart' in call.args or 'stop' in call.args for call in run.call_args_list))

    def test_stale_request_rejected(self):
        with patch.object(hotops,'authorize',return_value=({}, {}, {}, {'Id':'a'*64,'State':{'StartedAt':'new'}})), patch.object(hotops,'run') as run:
            with self.assertRaises(ValueError): ci.rename({'container_name':'new','expected_id':'a'*12,'expected_started':'old'})
            run.assert_not_called()
