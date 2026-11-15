import os
from uuid import UUID, uuid4

import pytest
from sqlalchemy import select
from sqlalchemy.orm import Session

from backend.v2.core.errors import AuthError
from backend.v2.models import Conversation, Message, ProjectMemory, User
from backend.v2.services import project_service as projects
from backend.v2.tests.test_conversations import (database, local_settings, client_for,
                                                   register, login, csrf_headers)

pytestmark = [pytest.mark.integration, pytest.mark.skipif(
    os.environ.get('DS_V2_RUN_DB_TESTS') != '1', reason='Opt in to isolated PostgreSQL tests',
)]


def make_project(client, name):
    result = client.post('/api/v2/projects', json={'title': name}, headers=csrf_headers(client))
    assert result.status_code == 201, result.text
    return result.json()['id']


def test_projects_crud_user_isolation_and_conversation_retention(database):
    settings = local_settings(database[1])
    with client_for(settings) as a, client_for(settings) as b:
        ca, cb = register(a), register(b)
        login(a, ca); login(b, cb)
        p1 = make_project(a, '二叉树')
        p2 = make_project(a, '复杂度')
        other = make_project(b, '隐私项目')
        assert a.patch(f'/api/v2/projects/{p1}', json={'memory_source_ids': [other]},
                       headers=csrf_headers(a)).status_code == 404
        assert a.patch(f'/api/v2/projects/{p1}', json={'memory_source_ids': [p1]},
                       headers=csrf_headers(a)).status_code == 422
        assert a.patch(f'/api/v2/projects/{p1}', json={'memory_source_ids': [p2, p2]},
                       headers=csrf_headers(a)).status_code == 422
        assert b.patch(f'/api/v2/projects/{p1}', json={'title': '越权'},
                       headers=csrf_headers(b)).status_code == 404
        saved = a.patch(f'/api/v2/projects/{p1}', json={'description': '研究树结构', 'memory_source_ids': [p2]},
                        headers=csrf_headers(a))
        assert saved.status_code == 200
        assert saved.json()['memory_source_ids'] == [p2]
        created = a.post('/api/v2/conversations', json={'title': '树的遍历', 'project_id': p1},
                         headers=csrf_headers(a))
        assert created.status_code == 201
        conv = created.json()['conversation']['id']
        assert created.json()['conversation']['project_id'] == p1
        assert b.post('/api/v2/conversations', json={'title': '越权', 'project_id': p1},
                      headers=csrf_headers(b)).status_code == 404
        assert a.patch(f'/api/v2/conversations/{conv}', json={'project_id': other},
                       headers=csrf_headers(a)).status_code == 404
        assert a.delete(f'/api/v2/projects/{p1}', headers=csrf_headers(a)).status_code == 204
        assert a.get(f'/api/v2/conversations/{conv}').json()['conversation']['project_id'] is None
        assert a.get(f'/api/v2/projects/{p1}/memories').status_code == 404
        assert a.get('/api/v2/projects').json()['items'][0]['id'] == p2


def test_memory_requires_explicit_import_and_revalidates_scope(database):
    settings = local_settings(database[1])
    with client_for(settings) as client:
        credentials = register(client); login(client, credentials)
        target = make_project(client, '复杂度')
        source = make_project(client, '二叉树')
        def create(project):
            response = client.post('/api/v2/conversations', json={'title': '课程讨论', 'project_id': project},
                                   headers=csrf_headers(client))
            assert response.status_code == 201
            return UUID(response.json()['conversation']['id'])
        source_conv, target_conv = create(source), create(target)
        scope = [uuid4()]
        with Session(database[0]) as session:
            user = session.scalar(select(User).where(User.email == credentials['email']))
            question = Message(conversation_id=source_conv, seq=1, role='user', content='二叉树的性质？',
                               metadata_json={'request_id': str(uuid4())})
            answer = Message(conversation_id=source_conv, seq=2, role='assistant', content='二叉树是一种树结构 [S1]。',
                             metadata_json={'result': {'status': 'answered', 'sources': [{}]},
                                            'knowledge_base_ids': [str(scope[0])]})
            session.add_all([question, answer]); session.flush()
            projects.remember(session, session.get(Conversation, source_conv), question.content, answer)
            session.commit()
        stub_check = lambda *args: None  # Focused sharing test; source-citation verification has its own tests.
        verify = lambda session: session.scalar(select(User).where(User.email == credentials['email']))
        with Session(database[0]) as session:
            user = verify(session)
            assert projects.load_notes(session, user, target_conv, scope, settings, verify, stub_check) == ()
        assert client.patch(f'/api/v2/projects/{target}', json={'memory_source_ids': [source]},
                            headers=csrf_headers(client)).status_code == 200
        with Session(database[0]) as session:
            user = verify(session)
            notes = projects.load_notes(session, user, target_conv, scope, settings, verify, stub_check)
            assert len(notes) == 1 and notes[0]['topic'] == '二叉树'
            assert '二叉树是一种树结构' in notes[0]['summary']
            assert projects.load_notes(session, user, target_conv, [uuid4()], settings, verify, stub_check) == ()
        # Fake evidence cannot be exposed via the actual HTTP memory endpoint.
        assert client.get(f'/api/v2/projects/{source}/memories').json()['items'] == []
        with Session(database[0]) as session:
            memory_id = session.scalar(select(ProjectMemory).where(ProjectMemory.project_id == UUID(source))).id
        assert client.delete(f'/api/v2/projects/{source}/memories/{memory_id}',
                             headers=csrf_headers(client)).status_code == 204
        with Session(database[0]) as session:
            user = verify(session)
            with pytest.raises(AuthError) as exc:
                projects.revalidate_notes(session, user, target_conv, notes, scope, settings, verify, stub_check)
            assert exc.value.code == 'project_memory_changed'
