import importlib.util
import json
import os
import sys
import pathlib
import tempfile
import unittest
from unittest.mock import patch

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'app'))


class NavigationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        with tempfile.TemporaryDirectory() as folder:
            config = pathlib.Path(folder) / 'web.json'
            config.write_text(json.dumps({'secret': 'test-navigation-only'}))
            with patch.dict(os.environ, {'H200_WEB_CONFIG': str(config)}):
                spec = importlib.util.spec_from_file_location('navigation_web', ROOT / 'app/web.py')
                cls.web = importlib.util.module_from_spec(spec)
                spec.loader.exec_module(cls.web)
        cls.web.app.testing = True
        # The isolated module name has no package root; bind its real templates.
        cls.web.app.jinja_loader.searchpath = [str(ROOT / 'app/templates')]

    def setUp(self):
        users = [dict(name=n, container='shared-box', status='running', port=2208) for n in ['alice', 'bob']]
        self.data = dict(labs=[dict(id='alpha', title='Alpha', writable=True, users=users, root_access=False, gpu=0, gpu_indices=[0])], gpus=[])
        self.catalog = dict(labs=[dict(id='alpha', title='Alpha', account_layout='shared',
            fingerprint='fingerprint', users=[dict(name=n, container='shared-box', hostname='shared-box', id='abc123', started='time', image='image:test') for n in ['alice', 'bob']])],
            available=[], maintenance=[], jobs=[], storage_limit=100)
        self.calls = []
        self.stub = patch.object(self.web, 'call', side_effect=self.call)
        self.stub.start()
        self.addCleanup(self.stub.stop)
        self.client = self.web.app.test_client()
        with self.client.session_transaction() as session:
            session.update(linux_token='test-token', username='review', csrf='test-csrf', language='ko')

    def call(self, request):
        self.calls.append(request)
        action = request['action']
        if action == 'linux_session': return {'username': 'review'}
        if action == 'status': return self.data
        if action == 'catalog': return self.catalog
        if action == 'provision_plans': return dict(storage_max_gb=100, plans=[], jobs=[])
        if action == 'provision_sources': return dict(bases=[], registered=[])
        if action in {'register', 'container_rename', 'provision_submit'}: return {'message': 'test only'}
        raise AssertionError('Unexpected action: ' + action)

    def test_get_pages_are_read_only_and_shared_container_listed_once(self):
        for route in ['/labs/add', '/labs/add/new', '/labs/add/existing', '/containers', '/containers/alpha', '/containers/alpha/images']:
            response = self.client.get(route)
            self.assertEqual(response.status_code, 200, route)
        self.assertTrue(all(c['action'] in {'linux_session', 'status', 'catalog', 'provision_plans', 'provision_sources'} for c in self.calls))
        rows = self.web.container_rows(self.data, self.catalog)
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]['accounts'], ['alice', 'bob'])
        html = self.client.get('/containers/alpha').get_data(as_text=True)
        self.assertIn('alice, bob', html)
        self.assertIn('공용 컨테이너 작업은 연결된 모든 계정에 함께 영향을 줍니다.', html)
        self.assertIn('name="expected_fingerprint"', html)
        self.assertIn('name="ack_downtime"', html)
        self.assertIn('data-affected-accounts="alice, bob"', html)
        self.assertIn('href="/containers" class="active"', html)
        self.assertNotIn('href="/labs" class="active"', html)

    def test_existing_environment_empty_state_and_mode_links(self):
        html = self.client.get('/labs/add/existing').get_data(as_text=True)
        self.assertIn('연결 가능한 기존 환경이 없습니다.', html)
        self.assertIn('href="/labs/add/new"', html)
        self.assertIn('href="/labs/add/existing" class="active"', html)
        self.assertNotIn('<form method="post"><input', html)

    def test_old_links_redirect_with_gpu_selection_preserved(self):
        for old, new in [('/provision?gpu=3','/labs/add/new?gpu=3'),('/register','/labs/add/existing'),('/labs/alpha/maintenance','/containers/alpha/maintenance'),('/labs/alpha/images','/containers/alpha/images')]:
            response = self.client.get(old)
            self.assertEqual(response.status_code, 302)
            self.assertEqual(response.headers['Location'], new)

    def test_existing_post_handlers_keep_csrf_and_return_to_new_sections(self):
        response = self.client.post('/labs/add/existing', data={'csrf':'test-csrf', 'id':'new', 'container':'existing'})
        self.assertEqual(response.headers['Location'], '/labs')
        self.assertTrue(any(c['action']=='register' and c['container']=='existing' for c in self.calls))
        response = self.client.post('/hot-action', data={'csrf':'test-csrf','action':'container_rename','lab':'alpha','container_name':'renamed'})
        self.assertEqual(response.headers['Location'], '/containers/alpha/maintenance')
        before = len(self.calls)
        self.assertEqual(self.client.post('/labs/add/new', data={'plan':'alpha'}).status_code, 403)
        self.assertEqual(len(self.calls), before)

    def test_unknown_lab_and_section_not_found(self):
        for route in ['/containers/unknown','/containers/alpha/delete']:
            self.assertEqual(self.client.get(route).status_code, 404)

    def test_english_navigation(self):
        with self.client.session_transaction() as session: session['language']='en'
        html=self.client.get('/labs/add').get_data(as_text=True)
        self.assertIn('Add laboratory', html)
        self.assertIn('Connect existing environment', html)
        self.assertIn('Container management', html)
