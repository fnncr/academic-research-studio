import os
from concurrent.futures import ThreadPoolExecutor
from uuid import uuid4

import pytest
from alembic import command
from alembic.config import Config
from fastapi.testclient import TestClient
from sqlalchemy import text
from sqlalchemy.engine import make_url
from sqlalchemy.exc import DBAPIError

from app.database import project_engine
from app.main import app


@pytest.fixture
def storage(monkeypatch):
    url = os.environ.get('TEST_DATABASE_URL')
    if not url:
        if os.environ.get('CI'):
            pytest.fail('CI must provide TEST_DATABASE_URL')
        pytest.skip('TEST_DATABASE_URL required for real PostgreSQL integration tests')
    admin = project_engine(url)
    schema = 'test_' + uuid4().hex
    with admin.begin() as connection:
        connection.execute(text(f'CREATE SCHEMA "{schema}"'))
    isolated = make_url(url).update_query_dict({'options': f'-csearch_path={schema}'}).render_as_string(hide_password=False)
    monkeypatch.setenv('DATABASE_URL', isolated)
    config = Config('alembic.ini')
    try:
        command.upgrade(config, 'head')
        yield config, isolated
    finally:
        with admin.begin() as connection:
            connection.execute(text(f'DROP SCHEMA "{schema}" CASCADE'))
        admin.dispose()


@pytest.fixture
def client(storage):
    with TestClient(app) as client:
        yield client


def create(client):
    response = client.post('/api/projects', json={'title': 'Курсовая', 'research_question': 'Как меняется результат?', 'requirements': 'Объём 20 страниц. Источники обязательны.'})
    assert response.status_code == 201, response.text
    return response.json()


def test_create_read_list_and_persist_after_restart(storage):
    with TestClient(app) as client:
        project = create(client)
        assert project['latest_brief']['number'] == 1
        assert client.get('/api/projects').json()[0]['id'] == project['id']
        assert client.get('/api/projects?limit=1&offset=1').json() == []
    with TestClient(app) as restarted:
        assert restarted.get('/api/projects/' + project['id']).json() == project


def test_append_history_and_stale_write_conflict(client):
    project = create(client)
    path = f"/api/projects/{project['id']}/brief-revisions"
    payload = {'base_revision_id': project['latest_brief']['id'], 'requirements': 'Теперь 25 страниц.'}
    response = client.post(path, json=payload)
    assert response.status_code == 201
    assert response.json()['number'] == 2
    assert client.post(path, json=payload).status_code == 409
    assert [b['number'] for b in client.get(path).json()] == [2, 1]
    assert client.get(path).json()[1]['requirements'] == project['latest_brief']['requirements']
    assert client.get(path + '?limit=1&offset=1').json()[0]['number'] == 1
    assert client.put(path, json=payload).status_code == 405


def test_concurrent_revision_writers(client):
    project = create(client)
    path = f"/api/projects/{project['id']}/brief-revisions"
    payload = {'base_revision_id': project['latest_brief']['id'], 'requirements': 'Изменённые требования'}
    with ThreadPoolExecutor(2) as pool:
        results = list(pool.map(lambda _: client.post(path, json=payload).status_code, range(2)))
    assert sorted(results) == [201, 409]
    assert len(client.get(path).json()) == 2


def test_invalid_unknown_and_cross_project_ids(client):
    assert client.get('/api/projects/not-a-uuid').status_code == 422
    assert client.get(f'/api/projects/{uuid4()}').status_code == 404
    project, other = create(client), create(client)
    response = client.post(f"/api/projects/{project['id']}/brief-revisions", json={
        'base_revision_id': other['latest_brief']['id'], 'requirements': 'Чужая версия'})
    assert response.status_code == 409


@pytest.mark.parametrize('field,value', [('title', '   '), ('title', 'x' * 201), ('research_question', ''), ('requirements', ''), ('requirements', 'x' * 20001), ('title', 123)])
def test_input_validation_has_no_partial_project(client, field, value):
    payload = {'title': 'Тема', 'research_question': 'Вопрос', 'requirements': 'Требования'}
    payload[field] = value
    assert client.post('/api/projects', json=payload).status_code == 422
    assert client.get('/api/projects').json() == []


def test_migrations_and_database_immutability(storage):
    config, url = storage
    command.upgrade(config, 'head')  # Repeatable.
    command.check(config)  # No ORM/migration drift.
    with TestClient(app) as client:
        project = create(client)
    engine = project_engine(url)
    try:
        with pytest.raises(DBAPIError):
            with engine.begin() as connection:
                connection.execute(text('UPDATE brief_revisions SET requirements = :text WHERE id = :id'), {'text': 'overwrite', 'id': project['latest_brief']['id']})
    finally:
        engine.dispose()
    command.downgrade(config, 'base')
    command.upgrade(config, 'head')
    with TestClient(app) as client:
        assert client.get('/api/projects').json() == []


@pytest.mark.parametrize('url', [None, 'bad-url', 'postgresql+psycopg://127.0.0.1:1/unavailable'])
def test_optional_storage_failure_does_not_break_extraction(monkeypatch, url):
    if url is None:
        monkeypatch.delenv('DATABASE_URL', raising=False)
    else:
        monkeypatch.setenv('DATABASE_URL', url)
    from io import BytesIO
    from docx import Document
    document = Document(); document.add_paragraph('Работает без БД')
    output = BytesIO(); document.save(output)
    with TestClient(app) as client:
        response = client.get('/api/projects')
        assert response.status_code == 503
        assert 'postgresql' not in response.text
        assert client.get('/api/health').status_code == 200
        response = client.post('/api/documents/extract?filename=test.docx', content=output.getvalue())
        assert response.status_code == 200
        assert response.json()['text'] == 'Работает без БД'


def test_first_revision_failure_rolls_back_project(storage):
    _, url = storage
    engine = project_engine(url)
    try:
        with engine.begin() as connection:
            connection.execute(text("""CREATE FUNCTION fail_test_insert() RETURNS trigger LANGUAGE plpgsql AS $$
                BEGIN RAISE EXCEPTION 'test insert failure'; END; $$"""))
            connection.execute(text('CREATE TRIGGER fail_test_insert BEFORE INSERT ON brief_revisions FOR EACH ROW EXECUTE FUNCTION fail_test_insert()'))
        with TestClient(app) as client:
            response = client.post('/api/projects', json={'title': 'Тема', 'research_question': 'Вопрос', 'requirements': 'Требования'})
            assert response.status_code == 503
            assert 'test insert failure' not in response.text
            assert client.get('/api/projects').json() == []
    finally:
        engine.dispose()


def test_missing_migrations_returns_safe_error(storage):
    config, _ = storage
    command.downgrade(config, 'base')
    with TestClient(app) as client:
        response = client.get('/api/projects')
        assert response.status_code == 503
        assert 'SELECT' not in response.text
        assert client.get('/api/health').status_code == 200
