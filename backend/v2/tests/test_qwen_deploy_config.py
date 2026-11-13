"""Deployment-only tests: no database, model, production credentials or server access."""
import importlib.util
import json
import os
from pathlib import Path
import re
import subprocess

import pytest

ROOT = Path(__file__).resolve().parents[3]
SCRIPT = ROOT / 'deploy/v2/tencent/ci/qwen-deploy.sh'
spec = importlib.util.spec_from_file_location('qwen_frontend_config', SCRIPT.with_name('qwen-frontend-config.py'))
config = importlib.util.module_from_spec(spec)
spec.loader.exec_module(config)
COURSE = '11111111-1111-4111-8111-111111111111'
OTHER = '22222222-2222-4222-8222-222222222222'
FAKE_ACCOUNT = {'email': 'fixture@example.com', 'password': 'mock-only-not-a-credential'}


class Api:
    def __init__(self, record=None):
        self.calls = []
        self.record = record or {'id': COURSE, 'owner_id': 'owner', 'visibility': 'private'}

    def request(self, method, path, data=None, csrf=None):
        self.calls.append((method, path, data, csrf))
        if path == '/auth/csrf':
            return {'csrf_token': 'mock-only'}
        if path == '/auth/me':
            return {'user': {'id': 'owner'}}
        if path.startswith('/knowledge-bases/'):
            return {'knowledge_base': self.record}
        return {}


@pytest.mark.parametrize('value', ['', 'invalid', COURSE.replace('-', ''), COURSE + '\n' + OTHER,
                                  ' ' + COURSE, '00000000-0000-0000-0000-000000000000', None])
def test_reject_invalid_course_uuid(value):
    with pytest.raises(config.InvalidConfig):
        config.course_id(value)


def test_controlled_file_read_and_missing_config(tmp_path):
    path = tmp_path / 'course'
    with pytest.raises(FileNotFoundError):
        config.controlled_read(path, owners={os.getuid()})
    path.write_text(COURSE + '\n'); path.chmod(0o644)
    assert config.course_id(config.controlled_read(path, owners={os.getuid()})) == COURSE
    path.chmod(0o666)
    with pytest.raises(config.InvalidConfig):
        config.controlled_read(path, owners={os.getuid()})
    path.chmod(0o600)
    with pytest.raises(config.InvalidConfig):
        config.controlled_read(path, owners={os.getuid() + 10000})
    link = tmp_path / 'link'; link.symlink_to(path)
    with pytest.raises(OSError):
        config.controlled_read(link, owners={os.getuid()})


def test_private_and_oversized_files_rejected(tmp_path):
    path = tmp_path / 'private'; path.write_text(COURSE); path.chmod(0o644)
    with pytest.raises(config.InvalidConfig):
        config.controlled_read(path, owners={os.getuid()}, private=True)
    path.chmod(0o600)
    with pytest.raises(config.InvalidConfig):
        config.controlled_read(path, owners={os.getuid()}, limit=10)


def test_verified_course_uses_existing_api_and_revokes_only_its_login():
    api = Api()
    config.verify_course(COURSE, {'kb': COURSE}, {'accounts': [FAKE_ACCOUNT]}, api)
    assert [x[:2] for x in api.calls] == [('GET', '/auth/csrf'), ('POST', '/auth/login'),
        ('GET', '/auth/me'), ('GET', '/knowledge-bases/' + COURSE), ('GET', '/auth/csrf'), ('POST', '/auth/logout')]
    assert api.calls[1][2] == FAKE_ACCOUNT
    assert api.calls[1][3] == api.calls[-1][3] == 'mock-only'


def test_never_falls_back_to_synthetic_or_logs_in_for_wrong_config():
    api = Api()
    with pytest.raises(config.InvalidConfig):
        config.verify_course(OTHER, {'kb': COURSE}, {'accounts': [FAKE_ACCOUNT]}, api)
    assert api.calls == []


@pytest.mark.parametrize('changed', [{'id': OTHER}, {'owner_id': 'another-user'}, {'visibility': 'public'}])
def test_wrong_or_unauthorized_api_course_fails_and_logs_out(changed):
    record = {'id': COURSE, 'owner_id': 'owner', 'visibility': 'private'} | changed
    api = Api(record)
    with pytest.raises(config.InvalidConfig):
        config.verify_course(COURSE, {'kb': COURSE}, {'accounts': [FAKE_ACCOUNT]}, api)
    assert api.calls[-1][:2] == ('POST', '/auth/logout')


def test_http_404_is_failure_and_the_test_session_is_revoked():
    class Missing(Api):
        def request(self, method, path, data=None, csrf=None):
            if path.startswith('/knowledge-bases/'):
                raise RuntimeError('simulated 404')
            return super().request(method, path, data, csrf)
    api = Missing()
    with pytest.raises(RuntimeError):
        config.verify_course(COURSE, {'kb': COURSE}, {'accounts': [FAKE_ACCOUNT]}, api)
    assert api.calls[-1][:2] == ('POST', '/auth/logout')


def test_cli_emits_only_uuid_and_never_underlying_error_or_credentials(monkeypatch, capsys):
    def read(path, **kwargs):
        if path == config.CONFIG:
            assert kwargs['owners'] == {0}
            return COURSE + '\n'
        return json.dumps({'kb': COURSE} if path.name == 'course-import-state.json' else {'accounts': [FAKE_ACCOUNT]})
    monkeypatch.setattr(config, 'controlled_read', read)
    monkeypatch.setattr(config, 'HttpsApi', Api)
    assert config.main() == 0
    captured = capsys.readouterr(); assert captured.out == COURSE + '\n'; assert captured.err == ''
    def broken(*args, **kwargs):
        raise RuntimeError(FAKE_ACCOUNT['password'])
    monkeypatch.setattr(config, 'controlled_read', broken)
    assert config.main() == 1
    captured = capsys.readouterr(); assert captured.out == ''
    assert FAKE_ACCOUNT['password'] not in captured.err
    assert 'preflight failed' in captured.err


def test_https_transport_pins_origin_and_refuses_redirects():
    with pytest.raises(config.InvalidConfig):
        config.NoRedirect().redirect_request(None, None, 307, None, None, 'http://invalid.example')
    api = config.HttpsApi()
    class Opener:
        def open(self, request, timeout):
            assert request.full_url == 'https://qwen.dsassistant.cn/api/v2/auth/login'
            assert request.get_header('Origin') == config.ORIGIN
            assert request.get_header('X-csrf-token') == 'mock-only'
            assert timeout == 15
            raise RuntimeError('inspection complete, no network call')
    api.opener = Opener()
    with pytest.raises(RuntimeError):
        api.request('POST', '/auth/login', FAKE_ACCOUNT, 'mock-only')


def test_actual_build_command_explicitly_passes_course_in_clean_environment(tmp_path):
    source = SCRIPT.read_text()
    commands = re.findall(r'^"\$\{build\[@\]\}".*?(?=\n[^ ])', source, re.M | re.S)
    command = next(x for x in commands if 'run build' in x)
    node = tmp_path / 'bin'; node.mkdir()
    npm = node / 'npm'
    npm.write_text('#!/usr/bin/python3\nimport json,os\nprint(json.dumps(dict(os.environ)))\n'); npm.chmod(0o755)
    run = subprocess.run(['bash', '-c', 'build=(); node_bin="$1"; release="$2"; course_id="$3"; ' + command,
                          'test', str(node), str(tmp_path), COURSE], capture_output=True, text=True,
                         env=dict(os.environ, PRIVATE_SHOULD_NOT_REACH_BUILD='test-only', VITE_COURSE_KB_ID=OTHER), check=True)
    env = json.loads(run.stdout)
    assert env['VITE_COURSE_KB_ID'] == COURSE
    assert env['VITE_USE_MOCK'] == env['VITE_REGISTRATION_ENABLED'] == 'false'
    assert env['VITE_API_BASE'] == ''
    assert 'PRIVATE_SHOULD_NOT_REACH_BUILD' not in env
    assert source.index('course_id=$(') < source.index('scratch=$(mktemp') < source.index('mv -Tf "$base/.qwen-ci-next-$$"')
