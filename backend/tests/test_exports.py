"""Synthetic publications only. Inspect actual OOXML and real PostgreSQL scoping."""
from copy import deepcopy
from io import BytesIO
import json
from pathlib import Path
from uuid import uuid4
from zipfile import ZipFile

from alembic import command
from docx import Document
from lxml import etree
import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from app.database import project_engine
from app.main import app
from app.models import ManuscriptRevision, ResearchPlanRevision
from app.manuscripts import digest
from test_projects import storage, create
from test_manuscripts import document, save
from test_sources import write, metadata
from test_evidence import excerpt, plan

NS = {'w': 'http://schemas.openxmlformats.org/wordprocessingml/2006/main'}


@pytest.fixture
def export_work(storage):
    with TestClient(app) as client:
        project = create(client)['id']; path = f'/api/projects/{project}'
        doc = document(); doc['blocks'] = [b for b in doc['blocks'] if b['type'] != 'citation_placeholder']
        doc['blocks'][1]['text'] = 'А🧪Б. Точная цитата.'
        doc['blocks'].append({'id': str(uuid4()), 'type': 'heading', 'level': 3, 'text': 'Границы применимости'})
        manuscript = save(client, project, doc).json()
        source = write(client, path + '/sources', {**metadata(), 'container': 'Тестовый журнал'}).json()
        evidence_body = excerpt(source['latest_version']['id'])
        evidence = client.post(path + '/evidence', json=evidence_body).json()
        plan_body = plan(manuscript, evidence['id'])
        plan_body['document']['citations'][0].update(kind='quotation', selection={'start': 1, 'end': 3, 'quote': '🧪'})
        saved_plan = client.post(path + '/research-plan/revisions', json=plan_body)
        assert saved_plan.status_code == 201, saved_plan.text
        profile = client.get(path + '/exports/options').json()['profiles'][0]['profile']
        body = {'manuscript_revision_id': manuscript['id'], 'plan_revision_id': saved_plan.json()['id'],
                'profile': profile, 'title_page': {'enabled': False}, 'citation_style': 'numeric-v1'}
        yield client, path, body, manuscript, source, saved_plan.json()


def checked(client, path, body):
    response = client.post(path + '/exports/preflight', json=body)
    assert response.status_code == 200, response.text
    return response.json()


def download(client, path, body):
    report = checked(client, path, body)
    assert report['can_export'], report
    response = client.post(path + '/exports/docx', json={**body, 'preflight_token': report['preflight_token']})
    assert response.status_code == 200, response.text
    return response, report


def xml(data, part='word/document.xml'):
    with ZipFile(BytesIO(data)) as archive: return etree.fromstring(archive.read(part))


def test_docx_structure_unicode_styles_citations_bibliography_and_manifest(export_work):
    client, path, body, manuscript, source, _ = export_work
    body['profile'].update(header='Исследование — верхний колонтитул', footer='Черновик')
    body['title_page'].update(author='Скрытое имя при отключённом титуле')
    response, report = download(client, path, body)
    assert response.headers['cache-control'] == 'no-store'
    assert response.headers['content-type'].startswith('application/vnd.openxmlformats')
    assert response.headers['x-export-input-sha256'] == report['preflight_token']
    doc = Document(BytesIO(response.content))
    assert doc.sections[0].page_width.cm == pytest.approx(21, abs=.01)
    assert doc.sections[0].page_height.cm == pytest.approx(29.7, abs=.01)
    assert doc.sections[0].left_margin.cm == pytest.approx(3, abs=.01)
    normal = doc.styles['Normal']; assert normal.font.name == 'Times New Roman'
    assert normal.font.size.pt == 14 and normal.paragraph_format.line_spacing == 1.5
    assert normal.paragraph_format.first_line_indent.cm == pytest.approx(1.25, abs=.01)
    assert doc.styles['Heading 2'].font.bold is True
    root = xml(response.content)
    text = ''.join(root.xpath('//w:t/text()', namespaces=NS))
    assert 'А🧪[1, с. 12]Б. Точная цитата.' in text
    assert source['latest_version']['metadata']['title'] in text
    assert source['latest_version']['metadata']['doi'] in text
    assert root.xpath('//w:hyperlink[@w:anchor="source_1"]', namespaces=NS)
    assert root.xpath('//w:bookmarkStart[@w:name="source_1"]', namespaces=NS)
    assert root.xpath('//w:pStyle[@w:val="Heading2"]', namespaces=NS)
    assert root.xpath('//w:pStyle[@w:val="Heading3"]', namespaces=NS)
    assert root.xpath('//w:p[w:r/w:instrText[contains(., "TOC")]]/w:r/w:br', namespaces=NS)
    assert len(doc.tables) == 1 and doc.tables[0].cell(1, 0).text == 'α\nβ'
    assert doc.tables[0].style.name == 'Table Grid' and not doc.tables[0].autofit
    assert root.xpath('//w:numPr/w:numId', namespaces=NS)
    numbering = xml(response.content, 'word/numbering.xml')
    tags = [etree.QName(child).localname for child in numbering]
    assert max(i for i, tag in enumerate(tags) if tag == 'abstractNum') < min(i for i, tag in enumerate(tags) if tag == 'num')
    styles = xml(response.content, 'word/styles.xml')
    assert len(styles.xpath('//w:style[@w:styleId="TableGrid"]/w:tblPr/w:tblBorders/*', namespaces=NS)) == 6
    assert 'Таблица 1' in text
    assert 'TOC' in ''.join(root.xpath('//w:instrText/text()', namespaces=NS))
    footer = xml(response.content, 'word/footer1.xml')
    assert 'PAGE' in ''.join(footer.xpath('//w:instrText/text()', namespaces=NS))
    assert footer.xpath('//w:jc[@w:val="center"]', namespaces=NS)
    assert 'Исследование' in ''.join(xml(response.content, 'word/header1.xml').xpath('//w:t/text()', namespaces=NS))
    with ZipFile(BytesIO(response.content)) as archive:
        custom = etree.fromstring(archive.read('docProps/custom.xml'))
        manifest = json.loads(custom.xpath('//*[local-name()="lpwstr"]/text()')[0])
        assert manifest['manuscript_revision_id'] == manuscript['id']
        assert str(source['latest_version']['id']) in manifest['sources']
        assert manifest['settings']['profile']['font'] == 'Times New Roman'
        assert manifest['settings']['title_page'] == {'enabled': False}
        assert 'Скрытое имя' not in json.dumps(report, ensure_ascii=False)
        assert 'Скрытое имя' not in archive.read('docProps/custom.xml').decode()
        assert not root.xpath('//w:drawing', namespaces=NS)


def test_repeat_export_is_byte_identical_even_after_new_source_version(export_work):
    client, path, body, _, source, _ = export_work
    first, report = download(client, path, body)
    second, _ = download(client, path, body)
    assert first.content == second.content
    revised = {**source['latest_version']['metadata'], 'title': 'Другие метаданные в новой версии'}
    assert write(client, path + '/sources/' + source['id'] + '/versions', revised, base=source['latest_version']['id']).status_code == 201
    third, report2 = download(client, path, body)
    assert third.content == first.content and report2['preflight_token'] == report['preflight_token']


def test_title_and_custom_profile_are_explicit_and_repeatable(export_work):
    client, path, body, *_ = export_work
    body['title_page'] = {'enabled': True}
    report = checked(client, path, body)
    assert len([e for e in report['errors'] if e['code'] == 'missing_title_field']) == 9
    assert client.post(path + '/exports/docx', json=body).status_code == 422
    body['title_page'] = {'enabled': True, 'university': 'Тестовый университет', 'department': 'Кафедра методов',
        'discipline': 'Методология', 'topic': 'Исследование данных', 'author': 'Тестовый Автор',
        'group': 'Группа А', 'teacher': 'Преподаватель — тестовое имя', 'city': 'Тестовый город', 'year': 2026}
    body['profile'].update(font='Arial', font_size=12, line_spacing=2, margin_left_cm=2, toc=False, page_numbers=False)
    response, _ = download(client, path, body)
    doc = Document(BytesIO(response.content)); text = '\n'.join(p.text for p in doc.paragraphs)
    assert 'Тестовый университет' in text and 'Тестовый город — 2026' in text
    assert doc.styles['Normal'].font.name == 'Arial' and doc.styles['Normal'].font.size.pt == 12
    assert not xml(response.content).xpath('//w:instrText', namespaces=NS)
    assert not xml(response.content, 'word/footer1.xml').xpath('//w:instrText', namespaces=NS)


def test_preflight_token_rejects_changes_and_missing_style(export_work):
    client, path, body, *_ = export_work
    assert client.post(path + '/exports/docx', json=body).status_code == 409
    report = checked(client, path, body)
    changed = deepcopy(body); changed['profile']['font_size'] = 12
    assert client.post(path + '/exports/docx', json={**changed, 'preflight_token': report['preflight_token']}).status_code == 409
    changed['citation_style'] = 'gost'
    assert client.post(path + '/exports/preflight', json=changed).status_code == 422
    changed = deepcopy(body); changed['profile']['font_size'] = 100
    assert client.post(path + '/exports/preflight', json=changed).status_code == 422
    changed = deepcopy(body); changed.pop('citation_style')
    assert client.post(path + '/exports/preflight', json=changed).status_code == 422


def test_stale_plan_placeholders_and_without_plan(export_work):
    client, path, body, manuscript, *_ = export_work
    revision = save(client, path.rsplit('/', 1)[1], document(), manuscript['id']).json()
    body['manuscript_revision_id'] = revision['id']
    report = checked(client, path, body)
    assert {'stale_plan', 'unresolved_citation'} <= {e['code'] for e in report['errors']}
    assert client.post(path + '/exports/docx', json=body).status_code == 422
    body['manuscript_revision_id'] = manuscript['id']; body['plan_revision_id'] = None
    assert 'plan_not_selected' in {e['code'] for e in checked(client, path, body)['errors']}
    body['without_plan'] = True
    response, report = download(client, path, body)
    assert 'without_plan' in {e['code'] for e in report['warnings']}
    assert 'Список использованных источников' not in ''.join(xml(response.content).xpath('//w:t/text()', namespaces=NS))


def test_incomplete_source_blocks_instead_of_inventing_fields(export_work):
    client, path, body, manuscript, _, _ = export_work
    record = {**metadata(), 'doi': None, 'authors': [], 'year': None, 'container': ''}
    source = write(client, path + '/sources', record).json()
    evidence = client.post(path + '/evidence', json=excerpt(source['latest_version']['id'])).json()
    request = plan(manuscript, evidence['id']); request['document']['citations'][0]['selection'] = {'start': 0, 'end': 1, 'quote': 'А'}
    request['base_revision_id'] = body['plan_revision_id']
    saved = client.post(path + '/research-plan/revisions', json=request)
    assert saved.status_code == 201, saved.text
    body['plan_revision_id'] = saved.json()['id']
    report = checked(client, path, body)
    assert {'authors', 'year'} == {e['field'] for e in report['errors'] if e['code'] == 'incomplete_bibliography'}
    assert not report['can_export']
    assert client.post(path + '/exports/docx', json=body).status_code == 422


def test_no_project_leaks_or_cross_project_versions(export_work):
    client, path, body, *_ = export_work
    other = '/api/projects/' + create(client)['id']
    assert client.post(other + '/exports/preflight', json=body).status_code == 404
    altered = deepcopy(body); altered['plan_revision_id'] = str(uuid4())
    assert client.post(path + '/exports/preflight', json=altered).status_code == 404
    doc = save(client, other.rsplit('/', 1)[1], {'schema_version': '1', 'blocks': [{'id': str(uuid4()), 'type': 'paragraph', 'text': 'Другая работа'}]}).json()
    altered['manuscript_revision_id'] = doc['id']; altered['plan_revision_id'] = body['plan_revision_id']
    assert client.post(other + '/exports/preflight', json=altered).status_code == 404
    assert client.get('/api/projects/' + str(uuid4()) + '/exports/options').status_code == 404


def test_corrupt_structure_and_citation_ranges_block_export(export_work, storage):
    client, path, body, manuscript, _, plan_record = export_work
    engine = project_engine(storage[1])
    try:
        # New immutable rows simulate legacy/corrupt imported data without mutating history.
        with Session(engine) as db:
            old = db.get(ManuscriptRevision, manuscript['id'])
            broken = ManuscriptRevision(project_id=old.project_id, number=2, parent_id=old.id, request_id=uuid4(),
                request_hash='0' * 64, content_hash='0' * 64, document={'schema_version': '1', 'blocks': [{'id': str(uuid4()), 'type': 'image', 'text': 'private'}]})
            db.add(broken); db.flush(); broken_id = str(broken.id)
            old_plan = db.get(ResearchPlanRevision, plan_record['id']); bad_doc = deepcopy(old_plan.document)
            bad_doc['citations'][0]['selection']['quote'] = 'private quote mismatch'
            bad_plan = ResearchPlanRevision(project_id=old_plan.project_id, manuscript_revision_id=old.id, number=2,
                parent_id=old_plan.id, request_id=uuid4(), request_hash='0' * 64,
                content_hash=digest({'manuscript_revision_id': str(old.id), 'document': bad_doc}), document=bad_doc)
            db.add(bad_plan); db.flush(); bad_id = str(bad_plan.id); db.commit()
        altered = {**body, 'manuscript_revision_id': broken_id, 'plan_revision_id': None, 'without_plan': True}
        report = checked(client, path, altered)
        assert 'invalid_manuscript' in {e['code'] for e in report['errors']}
        report = checked(client, path, {**body, 'plan_revision_id': bad_id})
        assert 'invalid_scientific_links' in {e['code'] for e in report['errors']}
        assert 'private quote mismatch' not in json.dumps(report)
    finally: engine.dispose()


def test_xml_control_character_blocked_and_migrations_unchanged(export_work, storage):
    client, path, body, *_ = export_work
    body['profile']['header'] = 'Bad\x01character'
    report = checked(client, path, body)
    assert 'invalid_xml_text' in {e['code'] for e in report['errors']}
    command.check(storage[0])
    command.upgrade(storage[0], 'head')


def test_output_fixture_for_office_renderer(export_work):
    client, path, body, *_ = export_work
    response, _ = download(client, path, body)
    # Optional explicit artifact destination; no user documents used.
    import os
    destination = os.environ.get('EXPORT_TEST_ARTIFACT')
    if destination: Path(destination).write_bytes(response.content)


def test_nested_citations_keep_first_use_order_and_distinct_source_versions(export_work):
    client, path, body, manuscript, source, first_plan = export_work
    updated = write(client, path + '/sources/' + source['id'] + '/versions',
        {**source['latest_version']['metadata'], 'title': 'Вторая версия библиографии'}, base=source['latest_version']['id']).json()
    new_evidence = client.post(path + '/evidence', json=excerpt(updated['id'])).json()
    original_evidence = first_plan['document']['claims'][0]['evidence'][0]['evidence_id']
    request = {'request_id': str(uuid4()), 'base_revision_id': first_plan['id'],
        'manuscript_revision_id': manuscript['id'], 'document': deepcopy(first_plan['document'])}
    claim = request['document']['claims'][0]
    claim['evidence'].append({'evidence_id': new_evidence['id'], 'relation': 'limits', 'rationale': 'Сопоставить редакции'})
    list_item = manuscript['document']['blocks'][3]['items'][0]
    table_cell = manuscript['document']['blocks'][4]['rows'][0]['cells'][0]
    # Deliberately reversed input order: numbering follows manuscript text order.
    for node, evidence_id in [(table_cell, original_evidence), (list_item, new_evidence['id'])]:
        request['document']['citations'].append({'id': str(uuid4()), 'claim_id': claim['id'], 'evidence_id': evidence_id,
            'block_id': node['id'], 'kind': 'paraphrase',
            'selection': {'start': 0, 'end': len(node['text']), 'quote': node['text']}})
    saved = client.post(path + '/research-plan/revisions', json=request)
    assert saved.status_code == 201, saved.text
    body['plan_revision_id'] = saved.json()['id']
    response, _ = download(client, path, body)
    text = ''.join(xml(response.content).xpath('//w:t/text()', namespaces=NS))
    assert 'Гипотеза[2, с. 12]' in text and 'Показатель[1, с. 12]' in text
    assert 'Вторая версия библиографии' in text
    assert len(xml(response.content).xpath('//w:bookmarkStart', namespaces=NS)) == 2


def test_bounded_input_optional_storage_and_generation_slots(export_work, monkeypatch):
    from app.exports import slots
    client, path, body, *_ = export_work
    assert client.post(path + '/exports/preflight', content=b'x' * (256 * 1024 + 1), headers={'content-type': 'application/json'}).status_code == 413
    assert client.post(path + '/exports/preflight', content='{}', headers={'content-type': 'text/plain'}).status_code == 415
    slots.acquire(); slots.acquire()
    try:
        assert client.post(path + '/exports/docx', json=body).status_code == 503
    finally:
        slots.release(); slots.release()
    monkeypatch.delenv('DATABASE_URL', raising=False)
    with TestClient(app) as offline:
        assert offline.post(path + '/exports/preflight', json=body).status_code == 503
        assert offline.get('/api/health').status_code == 200


def test_concurrent_project_exports_do_not_share_text_or_numbering(export_work):
    from concurrent.futures import ThreadPoolExecutor
    client, path, body, manuscript, *_ = export_work
    other = '/api/projects/' + create(client)['id']
    other_doc = save(client, other.rsplit('/', 1)[1], {'schema_version': '1', 'blocks': [
        {'id': str(uuid4()), 'type': 'paragraph', 'text': 'Приватный текст другого проекта'}]}).json()
    other_body = {**body, 'manuscript_revision_id': other_doc['id'], 'plan_revision_id': None, 'without_plan': True}
    pairs = [(path, body), (other, other_body)]
    with ThreadPoolExecutor(2) as pool:
        responses = list(pool.map(lambda pair: download(client, *pair)[0], pairs))
    texts = [''.join(xml(r.content).xpath('//w:t/text()', namespaces=NS)) for r in responses]
    assert 'Приватный текст другого проекта' not in texts[0]
    assert 'Приватный текст другого проекта' in texts[1]
    assert 'Тестовый Автор' not in texts[1]
    assert '[1, с. 12]' in texts[0] and '[1, с. 12]' not in texts[1]
