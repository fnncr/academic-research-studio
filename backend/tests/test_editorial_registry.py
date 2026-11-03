"""Check data against the human specification, not generated expected fixtures."""
import hashlib
import json
import re
from pathlib import Path

import pytest
from pydantic import ValidationError

from app.editorial_registry import EditorialRegistry, REGISTRY_PATH, load_registry

ROOT = Path(__file__).resolve().parents[2]


@pytest.fixture
def raw():
    return json.loads(REGISTRY_PATH.read_text(encoding='utf-8'))


def test_registry_matches_entire_specification():
    source = (ROOT / 'docs/editorial-criteria.md').read_text(encoding='utf-8')
    registry = load_registry()
    assert registry.source_sha256 == hashlib.sha256(
        (ROOT / registry.source).read_bytes()).hexdigest()
    assert registry.evaluation_rules == source.split('\n\n')[1]
    assert registry.priorities == re.findall(r'^ [1-5]\. (.+)$', source, re.M)
    # Include every numbered heading; the former stray '33.' must fail here.
    headings = list(re.finditer(r'^(\d+)\. (.+)$', source, re.M))
    assert [m[1] for m in headings] == [f'{i:02}' for i in range(1, 35)]
    assert len(registry.criteria) == len(headings) == 34
    for i, (heading, criterion) in enumerate(zip(headings, registry.criteria)):
        end = headings[i + 1].start() if i < 33 else source.index('Приоритеты системы')
        body = source[heading.end():end]
        # Ignore section headings; all remaining content must be represented.
        body = re.sub(r'^[A-G]\. .+$', '', body, flags=re.M).strip()
        expected = '\n'.join([
            f'● Сигналы: {criterion.signals}',
            f'● Редактура: {criterion.review_action}',
            f'● Исключения: {criterion.exceptions}',
        ])
        assert '\n'.join(line.strip() for line in body.splitlines()) == expected
        assert (criterion.id, criterion.name) == heading.groups()
        assert criterion.description is None
        assert criterion.description_status == 'missing_in_source'


@pytest.mark.parametrize('change', ['missing', 'extra', 'duplicate', 'reordered'])
def test_reject_incomplete_or_unordered_registry(raw, change):
    if change == 'missing':
        raw['criteria'].pop()
    elif change == 'extra':
        raw['criteria'].append(raw['criteria'][0].copy())
    elif change == 'duplicate':
        raw['criteria'][1]['id'] = '01'
    else:
        raw['criteria'][0], raw['criteria'][1] = raw['criteria'][1], raw['criteria'][0]
    with pytest.raises(ValidationError):
        EditorialRegistry.model_validate(raw)


@pytest.mark.parametrize('id', [1, True, '1', '00', '35', '001', '01\n'])
def test_reject_invalid_ids(raw, id):
    raw['criteria'][0]['id'] = id
    with pytest.raises(ValidationError):
        EditorialRegistry.model_validate(raw)


@pytest.mark.parametrize('field', ['id', 'name', 'description', 'description_status', 'signals', 'review_action', 'exceptions'])
def test_all_criterion_fields_are_required(raw, field):
    del raw['criteria'][0][field]
    with pytest.raises(ValidationError):
        EditorialRegistry.model_validate(raw)


@pytest.mark.parametrize('field', ['name', 'signals', 'review_action', 'exceptions'])
@pytest.mark.parametrize('value', ['', ' \n\t', None, 123, [], {}])
def test_text_is_nonempty_and_strict(raw, field, value):
    raw['criteria'][0][field] = value
    with pytest.raises(ValidationError):
        EditorialRegistry.model_validate(raw)


@pytest.mark.parametrize('description,status', [(None, 'provided'), ('Text', 'missing_in_source'), ('', 'provided'), ('  ', 'provided')])
def test_reject_misleading_description_provenance(raw, description, status):
    raw['criteria'][0].update(description=description, description_status=status)
    with pytest.raises(ValidationError):
        EditorialRegistry.model_validate(raw)


def test_schema_can_preserve_future_source_description(raw):
    raw['criteria'][0].update(description='Описание из будущей спецификации.', description_status='provided')
    assert EditorialRegistry.model_validate(raw).criteria[0].description == raw['criteria'][0]['description']


@pytest.mark.parametrize('field', ['schema_version', 'registry_version', 'source', 'source_sha256', 'evaluation_rules', 'priorities', 'criteria'])
def test_registry_fields_required(raw, field):
    del raw[field]
    with pytest.raises(ValidationError):
        EditorialRegistry.model_validate(raw)


@pytest.mark.parametrize('field,value', [('schema_version', '2'), ('schema_version', 1), ('registry_version', 'latest'), ('registry_version', '01.0.0'), ('source_sha256', 'invalid'), ('evaluation_rules', ''), ('priorities', []), ('priorities', [''] * 5)])
def test_registry_metadata_validation(raw, field, value):
    raw[field] = value
    with pytest.raises(ValidationError):
        EditorialRegistry.model_validate(raw)


@pytest.mark.parametrize('nested', [False, True])
def test_unknown_fields_forbidden(raw, nested):
    target = raw['criteria'][0] if nested else raw
    target['invented_threshold'] = 3
    with pytest.raises(ValidationError):
        EditorialRegistry.model_validate(raw)


@pytest.mark.parametrize('text', ['{"schema_version":"1","schema_version":"2"}', '{"criteria":[{"id":"01","id":"02"}]}', '{"x":NaN}', '{"x":Infinity}', '{broken'])
def test_loader_rejects_ambiguous_or_invalid_json(tmp_path, text):
    path = tmp_path / 'bad.json'
    path.write_text(text)
    with pytest.raises(ValueError):
        load_registry(path)


def test_default_path_independent_of_working_directory(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    assert load_registry().registry_version == '1.0.0'


def test_version_one_baseline():
    assert load_registry().registry_version == '1.0.0'
