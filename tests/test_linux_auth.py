import pathlib,sys,unittest,time
from unittest.mock import patch,MagicMock
sys.path.insert(0,str(pathlib.Path(__file__).resolve().parents[1]/'app'))
import linux_auth,pam_auth
class LinuxAuthTests(unittest.TestCase):
    def test_missing_session_rejected_before_dispatch(self):
        with patch.object(linux_auth,'allowed') as allowed:
            self.assertFalse(linux_auth.handle({'action':'stop','actor':'jnu'})['ok'])
            allowed.assert_not_called()
    def test_invalid_password_never_spawns_sudo(self):
        with patch.object(linux_auth.pam_auth,'authenticate',return_value=False), patch.object(linux_auth.subprocess,'Popen') as popen:
            self.assertFalse(linux_auth.handle({'action':'linux_login','username':'test-user','password':'incorrect'})['ok'])
            popen.assert_not_called()
    def test_expired_session_is_closed(self):
        p=MagicMock();linux_auth.SESSIONS['expired']={'expires':0,'process':p,'lock':__import__('threading').Lock(),'user':'alice'}
        self.assertFalse(linux_auth.handle({'action':'status','_session':'expired'})['ok'])
        p.stdin.close.assert_called_once()
    def test_restricted_sudo_rejected(self):
        user=MagicMock(pw_uid=1000,pw_shell='/bin/bash')
        with patch.object(linux_auth.pwd,'getpwnam',return_value=user),patch.object(linux_auth.spwd,'getspnam',return_value=MagicMock(sp_pwdp='hash')),patch.object(linux_auth.pam_auth,'authenticate',return_value=True),patch.object(linux_auth.subprocess,'run',return_value=MagicMock(returncode=1)):
            self.assertFalse(linux_auth.allowed('alice'))
    def test_locked_account_rejected(self):
        with patch.object(linux_auth.pwd,'getpwnam',return_value=MagicMock(pw_uid=1000,pw_shell='/bin/bash')),patch.object(linux_auth.spwd,'getspnam',return_value=MagicMock(sp_pwdp='!locked')):
            self.assertFalse(linux_auth.allowed('alice'))

    def test_account_and_actor_in_activity(self):
        import activity_view
        entry=activity_view.events({'events':[{'action':'identity_check','actor':'jnu','result':'ok'}]})[0]
        self.assertEqual(entry['actor'],'jnu')
    def test_navigation_uses_linux_session(self):
        base=(pathlib.Path(__file__).resolve().parents[1]/'app/templates/base.html').read_text(encoding='utf-8')
        self.assertNotIn('session.admin',base)
        self.assertIn('session.linux_token',base)

    def test_every_activity_action_renders(self):
        import activity_view
        for action in activity_view.ACTIONS:
            self.assertEqual(len(activity_view.events({'events':[{'action':action,'result':'ok'}]})),1)
