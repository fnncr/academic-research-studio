from concurrent.futures import ThreadPoolExecutor
from copy import deepcopy
from uuid import uuid4

import pytest
from alembic import command
from fastapi.testclient import TestClient
from pydantic import ValidationError
from sqlalchemy import text
from sqlalchemy.exc import DBAPIError

from app.database import project_engine
from app.main import app
from app.manuscript_schema import ManuscriptDocument
from app.manuscripts import MAX_BODY, digest
from test_projects import storage, create  # Real PostgreSQL, a disposable schema per test.


def paragraph(value='Смысл: ё, Й, e\u0301, 𐍈, 🧪. Число −1,25; ссылка [1].'):
    return {'id': str(uuid4()), 'type': 'paragraph', 'text': value,
            'marks': ['bold'], 'origin': 'manual', 'page': None}


def document():
    return {'schema_version': '1', 'blocks': [
        {'id': str(uuid4()), 'type': 'heading', 'text': 'Исследовательский план', 'level': 2},
        paragraph(),
        {'id': str(uuid4()), 'type': 'quote', 'text': 'Точная цитата — проверить источник.'},
        {'id': str(uuid4()), 'type': 'list', 'ordered': True, 'items': [paragraph('Гипотеза'), paragraph('Метод')]},
        {'id': str(uuid4()), 'type': 'table', 'rows': [
            {'id': str(uuid4()), 'cells': [{'id': str(uuid4()), 'text': 'Показатель'}, {'id': str(uuid4()), 'text': 'Год'}]},
            {'id': str(uuid4()), 'cells': [{'id': str(uuid4()), 'text': 'α\nβ'}, {'id': str(uuid4()), 'text': '2026'}]},
        ]},
        {'id': str(uuid4()), 'type': 'citation_placeholder', 'label': 'Найти первичный источник', 'locator': 'с. 12'},
    ]}


def save(client, project_id, doc, base=None, request_id=None, restored=None):
    return client.post(f'/api/projects/{project_id}/manuscript/revisions', json={
        'base_revision_id': base, 'request_id': request_id or str(uuid4()),
        'document': doc, 'restored_from_id': restored})


@pytest.fixture
def manuscript(storage):
    with TestClient(app) as client:
        project = create(client)
        yield client, project['id'], f"/api/projects/{project['id']}/manuscript"


def test_unicode_tree_survives_storage_and_application_restart(manuscript):
    client, project_id, path = manuscript
    assert client.get(path).json() is None
    doc = document()
    saved = save(client, project_id, doc)
    assert saved.status_code == 201, saved.text
    revision = saved.json()
    assert revision['document'] == doc
    assert revision['content_hash'] == digest(doc)
    assert revision['number'] == 1 and revision['parent_id'] is None
    assert client.get(path).headers['cache-control'] == 'no-store'
    with TestClient(app) as restarted:
        assert restarted.get(path).json() == revision
        assert restarted.get(path + '/revisions/' + revision['id']).json() == revision
    summary = client.get(path + '/revisions').json()
    assert summary[0]['id'] == revision['id'] and 'document' not in summary[0]


@pytest.mark.parametrize('initial', [True, False])
def test_two_tabs_cannot_overwrite_including_first_save(manuscript, initial):
    client, project_id, path = manuscript
    first = None if initial else save(client, project_id, document()).json()['id']
    with ThreadPoolExecutor(max_workers=2) as executor:
        responses = list(executor.map(lambda _: save(client, project_id, document(), first), range(2)))
    assert sorted(response.status_code for response in responses) == [201, 409]
    assert client.get(path).json()['number'] == (1 if initial else 2)
    assert next(r for r in responses if r.status_code == 409).json()['detail']['code'] == 'revision_conflict'


def test_idempotent_retry_after_lost_response_and_later_revision(manuscript):
    client, project_id, path = manuscript
    doc = document(); key = str(uuid4())
    with ThreadPoolExecutor(max_workers=2) as executor:
        responses = list(executor.map(lambda _: save(client, project_id, doc, request_id=key), range(2)))
    first = responses[0].json()
    assert all(r.status_code == 201 and r.json() == first for r in responses)
    second = save(client, project_id, document(), first['id']).json()
    assert save(client, project_id, doc, request_id=key).json() == first
    assert client.get(path).json()['id'] == second['id']
    assert save(client, project_id, document(), request_id=key).status_code == 409
    assert len(client.get(path + '/revisions').json()) == 2


def test_restore_appends_and_never_rewrites_history(manuscript):
    client, project_id, path = manuscript
    original = save(client, project_id, document()).json()
    altered = deepcopy(original['document']); altered['blocks'].reverse()
    second = save(client, project_id, altered, original['id']).json()
    assert save(client, project_id, altered, second['id'], restored=original['id']).status_code == 422
    restored = save(client, project_id, original['document'], second['id'], restored=original['id']).json()
    assert restored['number'] == 3 and restored['parent_id'] == second['id']
    assert restored['restored_from_id'] == original['id']
    assert restored['content_hash'] == original['content_hash']
    assert client.get(path + '/revisions/' + original['id']).json() == original
    assert save(client, project_id, altered, second['id'], restored=second['id']).status_code == 409
    history = client.get(path + '/revisions?limit=1').json()
    save(client, project_id, altered, restored['id'])
    older = client.get(path + f"/revisions?before={history[-1]['number']}&limit=2").json()
    assert [r['number'] for r in older] == [2, 1]


def test_project_scoping_and_unknown_ids(manuscript):
    client, project_id, path = manuscript
    first = save(client, project_id, document()).json()
    other = create(client)['id']
    assert client.get(f"/api/projects/{other}/manuscript/revisions/{first['id']}").status_code == 404
    assert save(client, other, first['document'], restored=first['id']).status_code == 404
    assert save(client, other, first['document'], base=first['id']).status_code == 409
    assert client.get(f'/api/projects/{other}/manuscript').json() is None
    assert client.get(path + f'/revisions/{uuid4()}').status_code == 404
    assert save(client, str(uuid4()), document()).status_code == 404


@pytest.mark.parametrize('mutation', ['type', 'version', 'duplicate', 'nested_duplicate', 'extra', 'ragged', 'level', 'null', 'surrogate', 'nodes', 'characters', 'marks', 'bool'])
def test_reject_invalid_tree(mutation):
    doc = document()
    if mutation == 'type': doc['blocks'][0]['type'] = 'html'
    elif mutation == 'version': doc['schema_version'] = 'future'
    elif mutation == 'duplicate': doc['blocks'][1]['id'] = doc['blocks'][0]['id']
    elif mutation == 'nested_duplicate': doc['blocks'][4]['rows'][0]['cells'][0]['id'] = doc['blocks'][0]['id']
    elif mutation == 'extra': doc['blocks'][1]['html'] = '<script>private</script>'
    elif mutation == 'ragged': doc['blocks'][4]['rows'][0]['cells'].pop()
    elif mutation == 'level': doc['blocks'][0]['level'] = 7
    elif mutation == 'null': doc['blocks'][1]['text'] = 'secret\0text'
    elif mutation == 'surrogate': doc['blocks'][1]['text'] = '\ud800'
    elif mutation == 'nodes': doc['blocks'] = [paragraph() for _ in range(1001)]
    elif mutation == 'characters': doc['blocks'] = [paragraph('x' * 20000) for _ in range(13)]
    elif mutation == 'marks': doc['blocks'][1]['marks'] = ['underline']
    elif mutation == 'bool': doc['blocks'][0]['level'] = True
    with pytest.raises(ValidationError): ManuscriptDocument.model_validate(doc)


def test_bad_request_is_bounded_and_does_not_echo_manuscript(manuscript):
    client, project_id, path = manuscript
    doc = document(); doc['blocks'][0]['type'] = 'secret-manuscript-content'
    response = save(client, project_id, doc)
    assert response.status_code == 422 and 'secret-manuscript-content' not in response.text
    route = path + '/revisions'
    assert client.post(route, content=b'x' * (MAX_BODY + 1), headers={'content-type': 'application/json'}).status_code == 413
    assert client.post(route, content=b'{broken', headers={'content-type': 'application/json'}).status_code == 422
    assert client.post(route, content=b'{}', headers={'content-type': 'text/plain'}).status_code == 415
    assert client.post(route, json={}, headers={'content-encoding': 'gzip'}).status_code == 415
    assert client.get(path).json() is None


def test_migration_keeps_p1_data_and_prevents_revision_mutation(storage):
    config, url = storage
    command.downgrade(config, '0001_projects')
    with TestClient(app) as client:
        project = create(client)
        assert save(client, project['id'], document()).status_code == 503
        command.upgrade(config, 'head'); command.upgrade(config, 'head'); command.check(config)
        assert client.get('/api/projects/' + project['id']).json() == project
        saved = save(client, project['id'], document()).json()
    engine = project_engine(url)
    try:
        for statement in ['UPDATE manuscript_revisions SET number = 8 WHERE id = :id', 'DELETE FROM manuscript_revisions WHERE id = :id']:
            with pytest.raises(DBAPIError):
                with engine.begin() as connection: connection.execute(text(statement), {'id': saved['id']})
        with engine.begin() as connection:
            connection.execute(text("""CREATE FUNCTION reject_test_manuscript() RETURNS trigger LANGUAGE plpgsql AS $$
                BEGIN RAISE EXCEPTION 'private SQL failure'; END; $$"""))
            connection.execute(text('CREATE TRIGGER test_failure BEFORE INSERT ON manuscript_revisions FOR EACH ROW EXECUTE FUNCTION reject_test_manuscript()'))
        with TestClient(app) as client:
            response = save(client, project['id'], document(), saved['id'])
            assert response.status_code == 503 and 'private SQL failure' not in response.text
            assert client.get(f"/api/projects/{project['id']}/manuscript").json() == saved
    finally: engine.dispose()


@pytest.mark.parametrize('url', [None, 'bad-url', 'postgresql+psycopg://127.0.0.1:1/unavailable'])
def test_unavailable_storage_safe_error(monkeypatch, url):
    if url: monkeypatch.setenv('DATABASE_URL', url)
    else: monkeypatch.delenv('DATABASE_URL', raising=False)
    with TestClient(app) as client:
        response = client.get(f'/api/projects/{uuid4()}/manuscript')
        assert response.status_code == 503 and 'postgresql' not in response.text
        assert client.get('/api/health').json() == {'status': 'ok'}
