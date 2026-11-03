"""All records in these tests are synthetic fixtures, not real publications."""
import asyncio
from concurrent.futures import ThreadPoolExecutor
from copy import deepcopy
from uuid import uuid4

import httpx
import pytest
from alembic import command
from fastapi.testclient import TestClient
from pydantic import ValidationError
from sqlalchemy import text
from sqlalchemy.exc import DBAPIError

from app import source_adapters
from app.database import project_engine
from app.main import app
from app.source_schema import SearchRequest, SourceMetadata, normalize_doi, normalize_isbn
from test_projects import storage, create


def metadata(**overrides):
    return SourceMetadata(title='СИНТЕТИЧЕСКАЯ запись для теста', authors=['Тестовый Автор'], year=2020,
        kind='article', language='ru', doi='10.5555/synthetic-fixture', **overrides).model_dump(mode='json')


@pytest.fixture
def library(storage):
    with TestClient(app) as client:
        project_id = create(client)['id']
        yield client, project_id, f'/api/projects/{project_id}'


def write(client, path, record=None, key=None, base=None, origin=None):
    return client.post(path, json={'request_id': key or str(uuid4()), 'metadata': record or metadata(), 'base_version_id': base, 'origin': origin})


def search_body(**overrides):
    return {'request_id': str(uuid4()), 'query': 'synthetic fixture', 'providers': ['crossref', 'openalex'],
            'limit': 5, 'mode': 'search', 'source_version_id': None, 'consent': True, 'year_from': None, 'year_to': None, **overrides}


def results():
    other = {**metadata(), 'title': 'Другая синтетическая формулировка'}
    return [{'provider': provider, 'adapter_version': '1', 'checked_at': '2026-11-03T10:00:00+00:00',
             'status': 'completed', 'code': 'ok', 'skipped_records': 0,
             'hits': [{'id': provider + ':1', 'rank': 1, 'metadata': value}]}
            for provider, value in [('crossref', metadata()), ('openalex', other)]]


def test_source_create_retry_version_history_and_restart(library):
    client, _, path = library
    key = str(uuid4())
    first = write(client, path + '/sources', key=key)
    assert first.status_code == 201, first.text
    source = first.json(); version = source['latest_version']; route = path + '/sources/' + source['id']
    assert version['verification'] == 'unverified' and version['provenance'] == {'kind': 'manual'}
    assert write(client, path + '/sources', key=key).json() == source
    revised = {**metadata(), 'title': 'Исправленная синтетическая запись'}
    second = write(client, route + '/versions', revised, base=version['id'])
    assert second.status_code == 201 and second.json()['number'] == 2
    assert client.get(route + '/versions/' + version['id']).json() == version
    assert write(client, path + '/sources', key=key).json() == source
    with TestClient(app) as restarted:
        assert restarted.get(route).json()['latest_version'] == second.json()
        assert [v['number'] for v in restarted.get(route + '/versions?before=2').json()] == [1]
    assert write(client, route + '/versions', base=version['id']).status_code == 409
    assert write(client, path + '/sources', revised, key=key).status_code == 409


def test_duplicate_doi_conflict_visible_and_concurrent_creation(library):
    client, _, path = library
    with ThreadPoolExecutor(max_workers=2) as executor:
        saved = list(executor.map(lambda _: write(client, path + '/sources'), range(2)))
    assert sorted(r.status_code for r in saved) == [201, 409]
    doc = {**metadata(), 'doi': 'https://doi.org/10.5555/SYNTHETIC-FIXTURE', 'year': 2021}
    duplicate = write(client, path + '/sources', doc)
    assert duplicate.status_code == 409
    match = duplicate.json()['detail']['matches'][0]
    assert match['differences'] == ['year'] and match['metadata']['year'] == 2020
    assert len(client.get(path + '/sources').json()) == 1
    assert write(client, path + '/sources/' + match['source_id'] + '/versions', doc, base=match['version_id']).status_code == 201


def test_isbn_equivalence_and_atomic_identity_change(library):
    client, _, path = library
    book = {**metadata(), 'doi': None, 'isbn': '0000000000', 'kind': 'monograph'}
    source = write(client, path + '/sources', book).json()
    assert source['latest_version']['metadata']['isbn'] == '9780000000002'
    assert write(client, path + '/sources', {**book, 'isbn': '978-0-00-000000-2'}).status_code == 409
    first_doi = write(client, path + '/sources').json()
    conflict = write(client, path + '/sources/' + source['id'] + '/versions', {**book, 'doi': metadata()['doi']}, base=source['latest_version']['id'])
    assert conflict.status_code == 409
    assert client.get(path + '/sources/' + source['id']).json() == source
    assert client.get(path + '/sources/' + first_doi['id']).status_code == 200


def test_project_scoping_and_concurrent_updates(library):
    client, _, path = library
    source = write(client, path + '/sources').json(); old = source['latest_version']
    other = '/api/projects/' + create(client)['id']
    assert client.get(other + '/sources/' + source['id']).status_code == 404
    assert client.get(other + '/sources/' + source['id'] + '/versions/' + old['id']).status_code == 404
    assert write(client, other + '/sources').status_code == 201
    with ThreadPoolExecutor(max_workers=2) as executor:
        updates = list(executor.map(lambda n: write(client, path + '/sources/' + source['id'] + '/versions', {**metadata(), 'year': 2021 + n}, base=old['id']), range(2)))
    assert sorted(r.status_code for r in updates) == [201, 409]


def test_search_journal_import_provenance_and_metadata_conflicts(library, monkeypatch):
    client, _, path = library
    calls = []
    async def fetch(request): calls.append(request); return results()
    monkeypatch.setattr(source_adapters, 'fetch_all', fetch)
    body = search_body(year_from=2018, year_to=2022)
    response = client.post(path + '/search-runs', json=body)
    assert response.status_code == 201, response.text
    run = response.json(); hit = run['results'][0]['hits'][0]
    assert hit['related_hits'][0]['differences'] == ['title']
    assert run['request']['year_from'] == 2018 and run['request']['consent'] is True
    assert client.post(path + '/search-runs', json=body).json() == run and len(calls) == 1
    origin = {'search_run_id': run['id'], 'hit_id': hit['id']}
    source = write(client, path + '/sources', hit['metadata'], origin=origin)
    assert source.status_code == 201, source.text
    version = source.json()['latest_version']
    assert version['provenance']['search_run_id'] == run['id']
    assert version['verification'] == 'unverified'
    assert write(client, path + '/sources', {**hit['metadata'], 'doi': '10.5555/other-synthetic'}, origin=origin).status_code == 422
    check = client.post(path + '/search-runs', json=search_body(mode='doi', query=metadata()['doi'], source_version_id=version['id']))
    assert check.status_code == 201, check.text
    comparisons = [r['hits'][0]['comparison']['status'] for r in check.json()['results']]
    assert comparisons == ['metadata_match', 'conflict']
    assert client.get(path + '/sources/' + source.json()['id']).json()['latest_version']['id'] == version['id']
    with TestClient(app) as restarted:
        assert len(restarted.get(path + '/search-runs').json()) == 2
    other = '/api/projects/' + create(client)['id']
    assert write(client, other + '/sources', hit['metadata'], origin=origin).status_code == 422
    assert client.post(other + '/search-runs', json=search_body(mode='doi', query=metadata()['doi'], source_version_id=version['id'])).status_code == 422


def test_interrupted_search_is_journaled_and_not_automatically_repeated(library, monkeypatch):
    client, _, path = library
    async def interrupted(request): raise RuntimeError('synthetic process interruption')
    monkeypatch.setattr(source_adapters, 'fetch_all', interrupted)
    body = search_body()
    with pytest.raises(RuntimeError): client.post(path + '/search-runs', json=body)
    assert client.get(path + '/search-runs').json()[0]['status'] == 'pending'
    assert client.post(path + '/search-runs', json=body).json()['status'] == 'pending'


def test_validation_no_consent_no_network_and_no_content_echo(library, monkeypatch):
    client, _, path = library
    async def forbidden(_): pytest.fail('No external request permitted')
    monkeypatch.setattr(source_adapters, 'fetch_all', forbidden)
    for body in [search_body(consent=False), search_body(consent=1), search_body(providers=['http://127.0.0.1']), search_body(year_from=2025, year_to=2020), search_body(query='private', unknown='private')]:
        response = client.post(path + '/search-runs', json=body)
        assert response.status_code == 422 and 'private' not in response.text
    assert client.get(path + '/search-runs').json() == []
    assert write(client, path + '/sources', {**metadata(), 'doi': 'invalid-private-doi'}).status_code == 422
    assert client.post(path + '/sources', content=b'x' * (128 * 1024 + 1), headers={'content-type': 'application/json'}).status_code == 413


def test_migration_and_database_immutability(storage):
    config, url = storage
    command.check(config); command.upgrade(config, 'head')
    with TestClient(app) as client:
        path = '/api/projects/' + create(client)['id']
        version = write(client, path + '/sources').json()['latest_version']
    engine = project_engine(url)
    try:
        for sql in ['UPDATE source_versions SET number = 9 WHERE id = :id', 'DELETE FROM source_versions WHERE id = :id']:
            with pytest.raises(DBAPIError):
                with engine.begin() as connection: connection.execute(text(sql), {'id': version['id']})
    finally: engine.dispose()
    command.downgrade(config, '0002_manuscripts'); command.upgrade(config, 'head'); command.check(config)
    with TestClient(app) as client:
        assert client.get(path).status_code == 200
        assert client.get(path + '/sources').json() == []


@pytest.mark.parametrize('value', ['10.5555/SYNTHETIC-FIXTURE', 'doi:10.5555/synthetic-fixture', 'https://doi.org/10.5555%2Fsynthetic-fixture'])
def test_doi_normalization(value): assert normalize_doi(value) == '10.5555/synthetic-fixture'


@pytest.mark.parametrize('value', ['0000000001', '9780000000003', 'X000000000', '123', '978000000000X'])
def test_invalid_isbn(value):
    with pytest.raises(ValueError): normalize_isbn(value)


def test_invalid_metadata_url_and_types():
    for field, value in [('url', 'file:///etc/passwd'), ('url', 'javascript:alert(1)'), ('url', 'https://user:secret@example.org'), ('year', True), ('title', '\ud800'), ('title', '\0')]:
        with pytest.raises(ValidationError): SourceMetadata.model_validate({**metadata(), field: value})


def crossref_fixture():
    return {'message': {'items': [{'title': ['SYNTHETIC fixture'], 'author': [{'given': 'Test', 'family': 'Author'}],
        'published': {'date-parts': [[2020, 1]]}, 'DOI': '10.5555/synthetic-fixture', 'type': 'journal-article', 'language': 'en'}]}}


def test_crossref_adapter_contract_and_query_injection_is_data():
    seen = []
    def handler(request):
        seen.append(request)
        return httpx.Response(200, json=crossref_fixture())
    request = SearchRequest.model_validate(search_body(query='http://127.0.0.1:1/private?secret=test', providers=['crossref'], year_from=2010, year_to=2020))
    result = asyncio.run(source_adapters.one_provider('crossref', request, httpx.MockTransport(handler)))
    assert result['code'] == 'ok' and result['hits'][0]['metadata']['year'] == 2020
    assert len(seen) == 1 and seen[0].url.host == 'api.crossref.org' and seen[0].url.path == '/works'
    assert seen[0].url.params['query.bibliographic'] == request.query
    assert seen[0].url.params['filter'] == 'from-pub-date:2010-01-01,until-pub-date:2020-12-31'


def test_openalex_contract_secrets_not_in_results(monkeypatch):
    monkeypatch.setenv('OPENALEX_API_KEY', 'synthetic-secret-key')
    def handler(request):
        assert request.url.host == 'api.openalex.org' and request.url.params['api_key'] == 'synthetic-secret-key'
        return httpx.Response(200, json={'results': [{'id': 'https://openalex.org/W999999999999999', 'title': 'SYNTHETIC fixture', 'doi': 'https://doi.org/10.5555/synthetic-fixture', 'authorships': [{'author': {'display_name': 'Test Author'}}], 'publication_year': 2020, 'type': 'article', 'language': 'en'}]})
    result = asyncio.run(source_adapters.one_provider('openalex', SearchRequest.model_validate(search_body()), httpx.MockTransport(handler)))
    assert result['hits'][0]['metadata']['doi'] == '10.5555/synthetic-fixture'
    assert 'synthetic-secret-key' not in str(result)


@pytest.mark.parametrize('status,code', [(302, 'redirect_blocked'), (401, 'access_denied'), (403, 'access_denied'), (404, 'record_not_found'), (429, 'rate_limited'), (500, 'provider_unavailable')])
def test_provider_failures_and_private_redirects_are_never_followed(status, code):
    seen = []
    def handler(request):
        seen.append(str(request.url)); return httpx.Response(status, headers={'location': 'http://169.254.169.254/latest/meta-data/'})
    result = asyncio.run(source_adapters.one_provider('crossref', SearchRequest.model_validate(search_body()), httpx.MockTransport(handler)))
    assert result['status'] == 'unavailable' and result['code'] == code and len(seen) == 1
    assert result['hits'] == []


@pytest.mark.parametrize('mode', ['timeout', 'network', 'invalid', 'too_large', 'wrong_schema', 'bad_metadata'])
def test_bounded_adapter_errors(mode):
    def handler(request):
        if mode == 'timeout': raise httpx.ReadTimeout('private detail')
        if mode == 'network': raise httpx.ConnectError('private detail')
        if mode == 'invalid': return httpx.Response(200, content=b'not json')
        if mode == 'too_large': return httpx.Response(200, content=b'x' * (source_adapters.MAX_RESPONSE + 1))
        if mode == 'wrong_schema': return httpx.Response(200, json={'message': {}})
        return httpx.Response(200, json={'message': {'items': [{'title': ['fixture'], 'DOI': 'malformed'}]}})
    result = asyncio.run(source_adapters.one_provider('crossref', SearchRequest.model_validate(search_body()), httpx.MockTransport(handler)))
    assert result['code'] == {'timeout': 'timeout', 'network': 'network_unavailable', 'invalid': 'invalid_response', 'too_large': 'response_too_large', 'wrong_schema': 'invalid_response', 'bad_metadata': 'partial_metadata'}[mode]
    assert 'private detail' not in str(result) and result['hits'] == []


def test_total_deadline(monkeypatch):
    monkeypatch.setattr(source_adapters, 'TOTAL_TIMEOUT', .01)
    async def slow(request):
        await asyncio.sleep(.1); return httpx.Response(200, json=crossref_fixture())
    result = asyncio.run(source_adapters.one_provider('crossref', SearchRequest.model_validate(search_body()), httpx.MockTransport(slow)))
    assert result['code'] == 'timeout'
