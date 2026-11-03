"""Bibliographic metadata; identifier syntax never proves a publication exists."""
import re
from typing import Annotated, Literal
from urllib.parse import unquote, urlsplit
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, StringConstraints, field_validator, model_validator

ShortText = Annotated[str, StringConstraints(strict=True, strip_whitespace=True, max_length=500)]
Title = Annotated[str, StringConstraints(strict=True, strip_whitespace=True, min_length=1, max_length=1000)]


def normalize_doi(value: str) -> str:
    value = value.strip()
    if value.lower().startswith(('https://doi.org/', 'http://doi.org/', 'https://dx.doi.org/', 'http://dx.doi.org/')):
        parsed = urlsplit(value)
        if parsed.query or parsed.fragment:
            raise ValueError('DOI URL must not have query or fragment')
        value = unquote(parsed.path[1:])
    elif value.lower().startswith('doi:'):
        value = value[4:].strip()
    value = value.lower()
    if not re.fullmatch(r'10\.\d{4,9}/[^\s<>"#]+', value) or len(value) > 255:
        raise ValueError('Invalid DOI syntax')
    return value


def normalize_isbn(value: str) -> str:
    value = re.sub(r'[\s-]', '', value).upper()
    if re.fullmatch(r'[0-9]{9}[0-9X]', value):
        if sum((10 - index) * (10 if digit == 'X' else int(digit)) for index, digit in enumerate(value)) % 11:
            raise ValueError('Invalid ISBN-10 checksum')
        prefix = '978' + value[:9]
        return prefix + str((-sum(int(digit) * (1 if index % 2 == 0 else 3) for index, digit in enumerate(prefix))) % 10)
    if re.fullmatch(r'97[89][0-9]{10}', value):
        if sum(int(digit) * (1 if index % 2 == 0 else 3) for index, digit in enumerate(value)) % 10:
            raise ValueError('Invalid ISBN-13 checksum')
        return value
    raise ValueError('Invalid ISBN')


class Strict(BaseModel):
    model_config = ConfigDict(extra='forbid')

    @field_validator('*', mode='after')
    @classmethod
    def unicode_text(cls, value):
        values = value if isinstance(value, list) else [value]
        for item in values:
            if isinstance(item, str) and ('\0' in item or any(0xD800 <= ord(c) <= 0xDFFF for c in item)):
                raise ValueError('Invalid Unicode')
        return value


class SourceMetadata(Strict):
    title: Title
    authors: list[Annotated[str, StringConstraints(strict=True, strip_whitespace=True, min_length=1, max_length=300)]] = Field(default_factory=list, max_length=100)
    year: Annotated[int, Field(strict=True, ge=1000, le=2200)] | None = None
    kind: Literal['article', 'monograph', 'dissertation', 'report', 'dataset', 'other'] = 'other'
    language: Annotated[str, StringConstraints(pattern=r'^(?:[a-z]{2,3})(?:-[A-Z]{2})?$', strict=True)] = 'und'
    container: ShortText = ''
    publisher: ShortText = ''
    doi: Annotated[str, StringConstraints(strict=True, max_length=400)] | None = None
    isbn: Annotated[str, StringConstraints(strict=True, max_length=32)] | None = None
    url: Annotated[str, StringConstraints(strict=True, max_length=2048)] | None = None

    @field_validator('doi')
    @classmethod
    def doi_syntax(cls, value):
        return normalize_doi(value) if value else None

    @field_validator('isbn')
    @classmethod
    def isbn_syntax(cls, value):
        return normalize_isbn(value) if value else None

    @field_validator('url')
    @classmethod
    def url_syntax(cls, value):
        if not value:
            return None
        parsed = urlsplit(value)
        if parsed.scheme not in {'http', 'https'} or not parsed.hostname or parsed.username is not None or parsed.password is not None or any(ord(c) < 33 for c in value):
            raise ValueError('Only HTTP(S) URLs without credentials are accepted')
        return value


class HitOrigin(Strict):
    search_run_id: UUID
    hit_id: str = Field(min_length=1, max_length=40)


class WriteSource(Strict):
    request_id: UUID
    base_version_id: UUID | None = None
    metadata: SourceMetadata
    origin: HitOrigin | None = None


class SearchRequest(Strict):
    request_id: UUID
    query: Annotated[str, StringConstraints(strict=True, strip_whitespace=True, min_length=2, max_length=300)]
    providers: list[Literal['crossref', 'openalex']] = Field(min_length=1, max_length=2)
    limit: Annotated[int, Field(strict=True, ge=1, le=10)] = 5
    year_from: Annotated[int, Field(strict=True, ge=1000, le=2200)] | None = None
    year_to: Annotated[int, Field(strict=True, ge=1000, le=2200)] | None = None
    mode: Literal['search', 'doi'] = 'search'
    source_version_id: UUID | None = None
    consent: Annotated[bool, Field(strict=True)]

    @model_validator(mode='after')
    def consistent(self):
        if not self.consent:
            raise ValueError('Explicit permission is required')
        if len(set(self.providers)) != len(self.providers):
            raise ValueError('Duplicate provider')
        if self.year_from and self.year_to and self.year_from > self.year_to:
            raise ValueError('Invalid date range')
        if self.mode == 'doi':
            self.query = normalize_doi(self.query)
            if not self.source_version_id or self.year_from or self.year_to:
                raise ValueError('DOI verification needs a source version and no filters')
        elif self.source_version_id:
            raise ValueError('Search cannot claim to verify a source version')
        return self
