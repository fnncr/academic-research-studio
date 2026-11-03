"""Synthetic excerpts only; real PostgreSQL verifies history and foreign keys."""
from concurrent.futures import ThreadPoolExecutor
from copy import deepcopy
from uuid import uuid4

import pytest
from alembic import command
from fastapi.testclient import TestClient
from sqlalchemy import text
from sqlalchemy.exc import DBAPIError

from app.database import project_engine
from app.main import app
from test_projects import storage, create
from test_sources import write
from test_manuscripts import save, document


@pytest.fixture
def workspace(storage):
    with TestClient(app) as client:
        project = create(client)['id']; path = f'/api/projects/{project}'
        source = write(client, path + '/sources').json()
        manuscript = save(client, project, document()).json()
        yield client, path, source, manuscript


def excerpt(version):
    return {'request_id': str(uuid4()), 'source_version_id': version,
        'excerpt': 'А🧪Б — синтетический пример.',
        'selection': {'start': 1, 'end': 3, 'quote': '🧪'},
        'locator': {'kind': 'page', 'label': '12'}, 'material': 'full_text_excerpt',
        'rights_confirmed': True, 'note': 'Тестовый фрагмент'}


def plan(manuscript, evidence):
    claim = str(uuid4())
    block = manuscript['document']['blocks'][1]
    return {'request_id': str(uuid4()), 'base_revision_id': None,
        'manuscript_revision_id': manuscript['id'], 'document': {'schema_version': '1',
        'claims': [{'id': claim, 'statement': 'Тестовый тезис',
            'section_id': manuscript['document']['blocks'][0]['id'],
            'evidence': [{'evidence_id': evidence, 'relation': 'contradicts', 'rationale': 'Ограничение'}]}],
        'citations': [{'id': str(uuid4()), 'claim_id': claim, 'evidence_id': evidence,
            'block_id': block['id'], 'selection': {'start': 0, 'end': 5, 'quote': 'Смысл'}, 'kind': 'paraphrase'}]}}


def test_excerpt_exact_version_retry_and_restart(workspace):
    client, path, source, _ = workspace
    version = source['latest_version']; body = excerpt(version['id'])
    response = client.post(path + '/evidence', json=body)
    assert response.status_code == 201, response.text
    evidence = response.json()
    assert evidence['full_text_verified'] is False
    assert evidence['locator_verification'] == 'unverified'
    assert client.post(path + '/evidence', json=body).json() == evidence
    revised = {**version['metadata'], 'title': 'Новая редакция'}
    assert write(client, path + '/sources/' + source['id'] + '/versions', revised, base=version['id']).status_code == 201
    with TestClient(app) as restarted:
        detail = restarted.get(path + '/evidence/' + evidence['id'])
        assert detail.headers['cache-control'] == 'no-store'
        assert detail.json()['source_version']['id'] == version['id']
        assert detail.json()['content']['selection']['quote'] == '🧪'
    body['note'] = 'Другая запись'
    assert client.post(path + '/evidence', json=body).status_code == 409
    assert len(client.get(path + '/evidence').json()) == 1


@pytest.mark.parametrize('mutation', ['split', 'mismatch', 'end', 'rights', 'bool', 'private', 'null'])
def test_reject_invalid_quote_without_echo(workspace, mutation):
    client, path, source, _ = workspace
    body = excerpt(source['latest_version']['id'])
    if mutation == 'split': body['selection']['end'] = 2
    elif mutation == 'mismatch': body['selection']['quote'] = 'private excerpt'
    elif mutation == 'end': body['selection']['end'] = 40000
    elif mutation == 'rights': body['rights_confirmed'] = False
    elif mutation == 'bool': body['selection']['start'] = True
    elif mutation == 'private': body['unknown'] = 'private excerpt'
    elif mutation == 'null': body['note'] = '\0private excerpt'
    response = client.post(path + '/evidence', json=body)
    assert response.status_code == 422
    assert 'private excerpt' not in response.text
    assert client.get(path + '/evidence').json() == []


def test_plan_history_concurrency_and_immutable_manuscript_anchor(workspace):
    client, path, source, manuscript = workspace
    evidence = client.post(path + '/evidence', json=excerpt(source['latest_version']['id'])).json()
    body = plan(manuscript, evidence['id']); route = path + '/research-plan'
    with ThreadPoolExecutor(2) as pool:
        responses = list(pool.map(lambda _: client.post(route + '/revisions', json=body), range(2)))
    assert all(r.status_code == 201 for r in responses)
    first = responses[0].json(); assert responses[1].json() == first
    next_body = deepcopy(body); next_body.update(request_id=str(uuid4()), base_revision_id=first['id'])
    next_body['document']['claims'][0]['statement'] = 'Уточнённый тезис'
    competing = deepcopy(next_body); competing['request_id'] = str(uuid4())
    with ThreadPoolExecutor(2) as pool:
        responses = list(pool.map(lambda b: client.post(route + '/revisions', json=b), [next_body, competing]))
    assert sorted(r.status_code for r in responses) == [201, 409]
    assert client.post(route + '/revisions', json=body).json() == first
    save(client, path.rsplit('/', 1)[1], document(), manuscript['id'])
    assert client.get(route).json()['manuscript_revision_id'] == manuscript['id']
    assert client.get(route + '/revisions/' + first['id']).json() == first
    assert [p['number'] for p in client.get(route + '/revisions?before=2').json()] == [1]
    body['document']['claims'][0]['statement'] = 'Новый текст с прежним ключом'
    assert client.post(route + '/revisions', json=body).status_code == 409


@pytest.mark.parametrize('mutation', ['section', 'range', 'quote', 'missing_evidence', 'claim', 'duplicate', 'quotation'])
def test_invalid_plan_rolls_back(workspace, mutation):
    client, path, source, manuscript = workspace
    evidence = client.post(path + '/evidence', json=excerpt(source['latest_version']['id'])).json()
    body = plan(manuscript, evidence['id']); doc = body['document']
    if mutation == 'section': doc['claims'][0]['section_id'] = manuscript['document']['blocks'][1]['id']
    elif mutation == 'range': doc['citations'][0]['selection']['end'] = 10000
    elif mutation == 'quote': doc['citations'][0]['selection']['quote'] = 'private quote'
    elif mutation == 'missing_evidence': doc['claims'][0]['evidence'].append({'evidence_id': str(uuid4()), 'relation': 'supports'})
    elif mutation == 'claim': doc['citations'][0]['claim_id'] = str(uuid4())
    elif mutation == 'duplicate': doc['claims'].append(deepcopy(doc['claims'][0]))
    elif mutation == 'quotation': doc['citations'][0]['kind'] = 'quotation'
    response = client.post(path + '/research-plan/revisions', json=body)
    assert response.status_code == (404 if mutation == 'missing_evidence' else 422), response.text
    assert 'private quote' not in response.text
    assert client.get(path + '/research-plan').json() is None


def test_cross_project_links_rejected(workspace):
    client, path, source, manuscript = workspace
    other = '/api/projects/' + create(client)['id']
    body = excerpt(source['latest_version']['id'])
    assert client.post(other + '/evidence', json=body).status_code == 404
    evidence = client.post(path + '/evidence', json=body).json()
    assert client.get(other + '/evidence/' + evidence['id']).status_code == 404
    request = plan(manuscript, evidence['id'])
    assert client.post(other + '/research-plan/revisions', json=request).status_code == 404
    other_manuscript = save(client, other.rsplit('/', 1)[1], document()).json()
    request['manuscript_revision_id'] = other_manuscript['id']
    assert client.post(other + '/research-plan/revisions', json=request).status_code == 404
    request['manuscript_revision_id'] = manuscript['id']
    saved = client.post(path + '/research-plan/revisions', json=request).json()
    assert client.get(other + '/research-plan/revisions/' + saved['id']).status_code == 404


def test_exact_quotation_in_table_and_unresolved_claim(workspace):
    client, path, source, manuscript = workspace
    evidence = client.post(path + '/evidence', json=excerpt(source['latest_version']['id'])).json()
    doc = deepcopy(manuscript['document'])
    cell = doc['blocks'][4]['rows'][0]['cells'][0]
    cell['text'] = '🧪'
    revised = save(client, path.rsplit('/', 1)[1], doc, manuscript['id']).json()
    body = plan(revised, evidence['id'])
    body['document']['citations'][0].update(block_id=cell['id'], kind='quotation',
        selection={'start': 0, 'end': 2, 'quote': '🧪'})
    body['document']['claims'].append({'id': str(uuid4()), 'statement': 'Нужны дополнительные данные', 'evidence': []})
    response = client.post(path + '/research-plan/revisions', json=body)
    assert response.status_code == 201, response.text
    assert response.json()['document']['citations'][0]['selection']['quote'] == '🧪'
    assert response.json()['document']['claims'][1]['evidence'] == []


def test_migration_immutability_and_foreign_keys(workspace, storage):
    client, path, source, manuscript = workspace
    config, url = storage
    evidence = client.post(path + '/evidence', json=excerpt(source['latest_version']['id'])).json()
    saved = client.post(path + '/research-plan/revisions', json=plan(manuscript, evidence['id'])).json()
    command.check(config)
    engine = project_engine(url)
    try:
        statements = [
            ('UPDATE evidence SET content = :value WHERE id = :id', evidence['id']),
            ('DELETE FROM evidence WHERE id = :id', evidence['id']),
            ('DELETE FROM research_plan_revisions WHERE id = :id', saved['id']),
            ('DELETE FROM plan_evidence_references WHERE plan_revision_id = :id', saved['id']),
            ('DELETE FROM source_versions WHERE id = :id', source['latest_version']['id']),
            ('DELETE FROM sources WHERE id = :id', source['id']),
        ]
        for statement, identifier in statements:
            with pytest.raises(DBAPIError):
                with engine.begin() as connection:
                    connection.execute(text(statement), {'id': identifier, 'value': '{}'})
    finally: engine.dispose()
    command.downgrade(config, '0003_sources'); command.upgrade(config, 'head'); command.check(config)
    assert client.get(path + '/sources/' + source['id']).status_code == 200
    assert client.get(path + '/manuscript').json()['id'] == manuscript['id']


def test_payload_limits_and_optional_storage(workspace, monkeypatch):
    client, path, _, _ = workspace
    assert client.post(path + '/evidence', content=b'x' * (256 * 1024 + 1), headers={'content-type': 'application/json'}).status_code == 413
    assert client.post(path + '/evidence', content='{}', headers={'content-type': 'text/plain'}).status_code == 415
    monkeypatch.delenv('DATABASE_URL', raising=False)
    with TestClient(app) as offline:
        assert offline.get(path + '/evidence').status_code == 503
        assert offline.get('/api/health').status_code == 200


def test_original_language_is_separate_from_source_metadata(workspace):
    client, path, source, _ = workspace
    body = {**excerpt(source['latest_version']['id']), 'original_language': 'en'}
    response = client.post(path + '/evidence', json=body)
    assert response.status_code == 201, response.text
    assert response.json()['content']['original_language'] == 'en'
    assert response.json()['content']['excerpt'] == body['excerpt']
    assert client.post(path + '/evidence', json=body).json() == response.json()
    body['original_language'] = 'ru'
    assert client.post(path + '/evidence', json=body).status_code == 409
    body['request_id'] = str(uuid4()); body['original_language'] = 'invalid language'
    assert client.post(path + '/evidence', json=body).status_code == 422


def test_user_roundtrip_source_evidence_claim_citation_reload_restore(workspace):
    client, path, source, manuscript = workspace
    original = excerpt(source['latest_version']['id'])
    original['original_language'] = 'en'
    saved_evidence = client.post(path + '/evidence', json=original).json()
    body = plan(manuscript, saved_evidence['id'])
    route = path + '/research-plan'
    first = client.post(route + '/revisions', json=body)
    assert first.status_code == 201, first.text
    first = first.json()
    changed = deepcopy(body)
    changed.update(request_id=str(uuid4()), base_revision_id=first['id'])
    changed['document']['claims'][0]['statement'] = 'Уточнённая формулировка'
    second = client.post(route + '/revisions', json=changed).json()
    with TestClient(app) as restarted:
        assert restarted.get(route).json() == second
        assert restarted.get(path + '/evidence/' + saved_evidence['id']).json()['content']['original_language'] == 'en'
        archived = restarted.get(route + '/revisions/' + first['id']).json()
        restored = restarted.post(route + '/revisions', json={
            'request_id': str(uuid4()), 'base_revision_id': second['id'],
            'manuscript_revision_id': archived['manuscript_revision_id'], 'document': archived['document']})
        assert restored.status_code == 201, restored.text
        assert restored.json()['number'] == 3
        assert restored.json()['document'] == first['document']
        assert restarted.get(route + '/revisions/' + first['id']).json() == first


def test_p4a_request_can_be_retried_after_language_extension(workspace, storage):
    from sqlalchemy.orm import Session
    from app.models import Evidence
    from app.manuscripts import digest
    client, path, source, _ = workspace
    body = excerpt(source['latest_version']['id'])
    # Seed exactly the request and content shape written by the P4a release.
    legacy_content = {key: value for key, value in body.items() if key not in {'request_id', 'source_version_id'}}
    engine = project_engine(storage[1])
    try:
        with Session(engine) as db:
            record = Evidence(project_id=path.rsplit('/', 1)[1], source_version_id=body['source_version_id'],
                request_id=body['request_id'], request_hash=digest(body), content_hash=digest(legacy_content), content=legacy_content)
            db.add(record); db.commit(); identifier = str(record.id)
        retried = client.post(path + '/evidence', json=body)
        assert retried.status_code == 201, retried.text
        assert retried.json()['id'] == identifier
        assert 'original_language' not in retried.json()['content']
    finally: engine.dispose()
