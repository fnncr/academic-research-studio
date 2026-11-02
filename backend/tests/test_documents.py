from io import BytesIO
from zipfile import ZipFile, ZIP_DEFLATED

import pytest
from docx import Document
from fastapi.testclient import TestClient
from pypdf import PdfWriter
from pypdf.generic import DictionaryObject, NameObject, DecodedStreamObject

from app import main


@pytest.fixture
def client():
    with TestClient(main.app) as client:
        yield client


def docx_bytes(text='Исследование и результаты'):
    doc = Document()
    doc.add_paragraph(text)
    table = doc.add_table(rows=1, cols=2)
    table.cell(0, 0).text = 'Показатель'
    table.cell(0, 1).text = '42'
    doc.add_paragraph('Вывод')
    output = BytesIO()
    doc.save(output)
    return output.getvalue()


def pdf_bytes(text=True, encrypted=False, pages=1):
    writer = PdfWriter()
    for _ in range(pages):
        page = writer.add_blank_page(600, 800)
        if text:
            font = DictionaryObject({NameObject('/Type'): NameObject('/Font'), NameObject('/Subtype'): NameObject('/Type1'), NameObject('/BaseFont'): NameObject('/Helvetica')})
            page[NameObject('/Resources')] = DictionaryObject({NameObject('/Font'): DictionaryObject({NameObject('/F1'): writer._add_object(font)})})
            stream = DecodedStreamObject()
            stream.set_data(b'BT /F1 12 Tf 50 750 Td (Research results) Tj ET')
            page[NameObject('/Contents')] = writer._add_object(stream)
    if encrypted:
        writer.encrypt('password')
    output = BytesIO()
    writer.write(output)
    return output.getvalue()


def upload(client, data, filename='research.docx'):
    return client.post('/api/documents/extract', params={'filename': filename}, content=data)


def test_docx_order_tables_unicode_and_privacy(client):
    response = upload(client, docx_bytes(), '../../research.docx')
    assert response.status_code == 200
    result = response.json()
    assert result['text'] == 'Исследование и результаты\n\nПоказатель\t42\n\nВывод'
    assert result['pages'] is None
    assert response.headers['cache-control'] == 'no-store'


def test_pdf_text_and_page_numbers(client):
    response = upload(client, pdf_bytes(pages=2), 'file.PDF')
    assert response.status_code == 200
    assert response.json()['chunks'] == [{'text': 'Research results', 'page': 1}, {'text': 'Research results', 'page': 2}]


@pytest.mark.parametrize('data,name,status', [
    (b'', 'a.docx', 400), (b'abc', 'a.exe', 415),
    (b'%PDF-broken', 'a.docx', 422), (b'not pdf', 'a.pdf', 422),
    (b'PK\x03\x04broken', 'a.docx', 422), (b'%PDF-1.7 broken', 'a.pdf', 422),
])
def test_invalid_uploads(client, data, name, status):
    assert upload(client, data, name).status_code == status


@pytest.mark.parametrize('options,message', [({'text': False}, 'Текст не найден'), ({'encrypted': True}, 'паролем'), ({'pages': 201, 'text': False}, '200 страниц')])
def test_unsupported_pdf(client, options, message):
    response = upload(client, pdf_bytes(**options), 'file.pdf')
    assert response.status_code == 422
    assert message in response.json()['detail']


def test_empty_docx(client):
    output = BytesIO()
    Document().save(output)
    assert upload(client, output.getvalue()).status_code == 422


@pytest.mark.parametrize('name,content', [
    ('../escape', b'x'), ('word/vbaProject.bin', b'x'),
    ('evil.xml', b'<!DOCTYPE a [<!ENTITY x SYSTEM "file:///etc/passwd">]><a>&x;</a>'),
    ('bomb.txt', b'x' * 1_000_000),
])
def test_dangerous_docx(client, name, content):
    output = BytesIO()
    with ZipFile(BytesIO(docx_bytes())) as source, ZipFile(output, 'w', ZIP_DEFLATED) as target:
        for item in source.infolist():
            target.writestr(item, source.read(item))
        target.writestr(name, content)
    assert upload(client, output.getvalue()).status_code == 422


def test_size_limit_with_and_without_content_length(client, monkeypatch):
    monkeypatch.setattr(main, 'MAX_UPLOAD', 8)
    assert upload(client, b'x' * 9).status_code == 413
    response = client.post('/api/documents/extract?filename=a.pdf', content=iter([b'12345', b'67890']))
    assert response.status_code == 413


def test_worker_timeout_and_slot_recovery(client, monkeypatch):
    monkeypatch.setattr(main, 'TIMEOUT', 0.000001)
    assert upload(client, docx_bytes()).status_code == 422
    monkeypatch.setattr(main, 'TIMEOUT', 15)
    assert upload(client, docx_bytes()).status_code == 200


def test_health(client):
    assert client.get('/api/health').json() == {'status': 'ok'}
