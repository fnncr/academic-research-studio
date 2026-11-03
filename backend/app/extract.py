"""Document parsing; run only inside the resource-limited worker."""
from io import BytesIO
from pathlib import PurePosixPath
from zipfile import ZipFile

from defusedxml.ElementTree import fromstring
from docx import Document
from docx.table import Table
from pypdf import PdfReader

MAX_TEXT = 1_000_000
MAX_PAGES = 200
MAX_EXPANDED = 40 * 1024 * 1024


def extract(data: bytes, kind: str) -> dict:
    chunks = []
    total = 0

    def append(text: str, page: int | None = None):
        nonlocal total
        text = text.strip()
        total += len(text)
        if total > MAX_TEXT:
            raise ValueError('Извлечённый текст превышает лимит 1 000 000 символов.')
        if text:
            chunks.append({'text': text, 'page': page})

    if kind == 'docx':
        if not data.startswith(b'PK\x03\x04'):
            raise ValueError('Файл не является DOCX.')
        with ZipFile(BytesIO(data)) as archive:
            entries = archive.infolist()
            names = [entry.filename for entry in entries]
            if len(entries) > 2000 or len(names) != len(set(names)):
                raise ValueError('Недопустимая структура DOCX.')
            if sum(e.file_size for e in entries) > MAX_EXPANDED:
                raise ValueError('Распакованный DOCX слишком большой.')
            if not {'[Content_Types].xml', 'word/document.xml'} <= set(names):
                raise ValueError('В DOCX отсутствуют обязательные части.')
            for entry in entries:
                path = PurePosixPath(entry.filename)
                if path.is_absolute() or '..' in path.parts or '\\' in entry.filename:
                    raise ValueError('Недопустимый путь внутри DOCX.')
                if entry.flag_bits & 1 or 'vbaproject' in entry.filename.lower():
                    raise ValueError('Зашифрованные документы и макросы не поддерживаются.')
                if entry.file_size > 10 * 1024 * 1024 or entry.file_size > max(entry.compress_size, 1) * 200:
                    raise ValueError('Недопустимое сжатие DOCX.')
                if entry.filename.endswith(('.xml', '.rels')):
                    fromstring(archive.read(entry), forbid_dtd=True)
        document = Document(BytesIO(data))
        for block in document.iter_inner_content():
            if isinstance(block, Table):
                for row in block.rows:
                    append('\t'.join(cell.text for cell in row.cells))
            else:
                append(block.text)
        pages = None
    else:
        if not data.startswith(b'%PDF-'):
            raise ValueError('Файл не является PDF.')
        reader = PdfReader(BytesIO(data), strict=True)
        if reader.is_encrypted:
            raise ValueError('PDF с паролем не поддерживается.')
        pages = len(reader.pages)
        if pages > MAX_PAGES:
            raise ValueError('PDF содержит больше 200 страниц.')
        for number, page in enumerate(reader.pages, 1):
            append(page.extract_text() or '', number)
    if not chunks:
        raise ValueError('Текст не найден. Для сканов требуется OCR, который пока не поддерживается.')
    return {'format': kind, 'text': '\n\n'.join(c['text'] for c in chunks), 'chunks': chunks, 'pages': pages}
