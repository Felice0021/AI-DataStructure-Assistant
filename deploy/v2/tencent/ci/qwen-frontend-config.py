#!/usr/bin/python3
"""Root-only deployment preflight. Prints only the verified public course UUID."""
import http.cookiejar
import json
import os
from pathlib import Path
import stat
import sys
import urllib.request
from uuid import UUID

CONFIG = Path('/etc/ds-v2-qa/qwen-course-kb-id')
PRIVATE = Path('/var/lib/ds-v2-parser/qwen-demo')
ORIGIN = 'https://qwen.dsassistant.cn'


class InvalidConfig(Exception):
    pass


class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, *args, **kwargs):
        raise InvalidConfig('course API redirected')


def controlled_read(path, *, owners, private=False, limit=65536):
    fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
    try:
        info = os.fstat(fd)
        if (not stat.S_ISREG(info.st_mode) or info.st_uid not in owners
                or info.st_mode & (0o077 if private else 0o022) or info.st_size > limit):
            raise InvalidConfig('unsafe frontend configuration file')
        content = os.read(fd, limit + 1)
        if len(content) > limit:
            raise InvalidConfig('frontend configuration too large')
        return content.decode('utf-8')
    finally:
        os.close(fd)


def course_id(value):
    if not isinstance(value, str):
        raise InvalidConfig('course UUID missing or invalid')
    value = value.removesuffix('\n')
    try:
        canonical = str(UUID(value))
    except ValueError:
        raise InvalidConfig('course UUID missing or invalid') from None
    if value.lower() != canonical or UUID(canonical).int == 0:
        raise InvalidConfig('course UUID missing or invalid')
    return canonical


class HttpsApi:
    def __init__(self):
        self.opener = urllib.request.build_opener(urllib.request.ProxyHandler({}), NoRedirect(),
            urllib.request.HTTPCookieProcessor(http.cookiejar.CookieJar()))

    def request(self, method, path, data=None, csrf=None):
        headers = {'Origin': ORIGIN, 'Accept': 'application/json'}
        if csrf is not None:
            headers['X-CSRF-Token'] = csrf
        if data is not None:
            headers['Content-Type'] = 'application/json'
        request = urllib.request.Request(ORIGIN + '/api/v2' + path,
            data=None if data is None else json.dumps(data).encode(), headers=headers, method=method)
        with self.opener.open(request, timeout=15) as response:
            # Never accept a redirect to a different destination or a non-HTTPS response.
            if response.geturl() != request.full_url:
                raise InvalidConfig('course API redirected')
            raw = response.read(1048577)
            if len(raw) > 1048576:
                raise InvalidConfig('course API response too large')
            return json.loads(raw) if raw else {}


def verify_course(identifier, state, credentials, api):
    if course_id(state.get('kb')) != identifier:
        raise InvalidConfig('configured course differs from course import manifest')
    account = credentials['accounts'][0]
    login = {key: account[key] for key in ('email', 'password')}
    logged_in = False
    try:
        csrf = api.request('GET', '/auth/csrf')['csrf_token']
        api.request('POST', '/auth/login', login, csrf)
        logged_in = True
        user = api.request('GET', '/auth/me')['user']
        record = api.request('GET', '/knowledge-bases/' + identifier)['knowledge_base']
        if (record['id'] != identifier or record['visibility'] != 'private'
                or record['owner_id'] != user['id']):
            raise InvalidConfig('course not owned by the configured demo account')
    finally:
        if logged_in:
            csrf = api.request('GET', '/auth/csrf')['csrf_token']
            api.request('POST', '/auth/logout', csrf=csrf)


def main():
    try:
        identifier = course_id(controlled_read(CONFIG, owners={0}, limit=64))
        # Existing QA runtime UID; no production credentials enter the build environment.
        state = json.loads(controlled_read(PRIVATE / 'course-import-state.json', owners={0, 1002}, private=True))
        credentials = json.loads(controlled_read(PRIVATE / 'credentials.json', owners={0, 1002}, private=True))
        verify_course(identifier, state, credentials, HttpsApi())
    except Exception:
        print('course configuration preflight failed; check root-controlled config and authenticated API', file=sys.stderr)
        return 1
    print(identifier)
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
