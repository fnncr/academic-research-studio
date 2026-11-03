"""Bounded metadata-only adapters. No user-provided URL is ever fetched."""
import asyncio
from datetime import datetime, timezone
import json
import os
from urllib.parse import quote

import httpx
from pydantic import ValidationError

from app.source_schema import SearchRequest, SourceMetadata

ENDPOINTS = {'crossref': 'https://api.crossref.org/works', 'openalex': 'https://api.openalex.org/works'}
MAX_RESPONSE = 1024 * 1024
TOTAL_TIMEOUT = 12
ADAPTER_VERSION = '1'


class ProviderFailure(Exception):
    def __init__(self, code):
        self.code = code


async def fetch_metadata(provider: str, request: SearchRequest, transport=None):
    """Fixed HTTPS origins, encoded params/DOIs, TLS on, redirects always rejected.

    This deliberately does not implement a general URL fetcher. Landing pages,
    full texts, links in API responses and DOI redirects are never followed.
    """
    url = ENDPOINTS[provider]
    params = {}
    if provider == 'crossref':
        if request.mode == 'doi':
            url += '/' + quote(request.query, safe='')
        else:
            params = {'query.bibliographic': request.query, 'rows': str(request.limit)}
            filters = []
            if request.year_from: filters.append(f'from-pub-date:{request.year_from}-01-01')
            if request.year_to: filters.append(f'until-pub-date:{request.year_to}-12-31')
            if filters: params['filter'] = ','.join(filters)
    else:
        params = {'per-page': str(request.limit)}
        if request.mode == 'doi':
            params['filter'] = 'doi:https://doi.org/' + request.query
        else:
            params['search'] = request.query
            filters = []
            if request.year_from: filters.append(f'from_publication_date:{request.year_from}-01-01')
            if request.year_to: filters.append(f'to_publication_date:{request.year_to}-12-31')
            if filters: params['filter'] = ','.join(filters)
        if os.environ.get('OPENALEX_API_KEY'):
            params['api_key'] = os.environ['OPENALEX_API_KEY']
    contact = os.environ.get('SOURCE_API_CONTACT')
    if contact:
        params['mailto'] = contact
    try:
        async with asyncio.timeout(TOTAL_TIMEOUT):
            async with httpx.AsyncClient(transport=transport, timeout=httpx.Timeout(5, connect=3),
                follow_redirects=False, headers={'Accept': 'application/json', 'Accept-Encoding': 'identity', 'User-Agent': 'AcademicResearchStudio/0.1 (metadata only)'}) as client:
                async with client.stream('GET', url, params=params) as response:
                    if 300 <= response.status_code < 400: raise ProviderFailure('redirect_blocked')
                    if response.status_code in (401, 403): raise ProviderFailure('access_denied')
                    if response.status_code == 429: raise ProviderFailure('rate_limited')
                    if response.status_code == 404: raise ProviderFailure('record_not_found')
                    if response.status_code != 200: raise ProviderFailure('provider_unavailable')
                    if response.headers.get('content-encoding', 'identity') != 'identity': raise ProviderFailure('unsupported_encoding')
                    data = bytearray()
                    async for chunk in response.aiter_bytes(chunk_size=16384):
                        if len(data) + len(chunk) > MAX_RESPONSE: raise ProviderFailure('response_too_large')
                        data.extend(chunk)
                    try:
                        result = json.loads(data)
                    except (ValueError, UnicodeError, RecursionError):
                        raise ProviderFailure('invalid_response') from None
                    if not isinstance(result, dict): raise ProviderFailure('invalid_response')
                    return result
    except (httpx.TimeoutException, TimeoutError):
        raise ProviderFailure('timeout') from None
    except httpx.HTTPError:
        # Request URLs may include provider API keys: never persist/log exceptions.
        raise ProviderFailure('network_unavailable') from None


def first(value, fallback=''):
    return value[0] if isinstance(value, list) and value else fallback


def crossref_record(item):
    dates = item.get('published') or item.get('issued') or {}
    parts = first(dates.get('date-parts'), [])
    authors = [' '.join(filter(None, [author.get('given'), author.get('family')])) or author.get('name', '') for author in item.get('author', [])]
    return SourceMetadata(title=first(item.get('title')), authors=authors,
        year=first(parts, None), kind={'journal-article': 'article', 'proceedings-article': 'article', 'book': 'monograph', 'monograph': 'monograph', 'dissertation': 'dissertation', 'report': 'report', 'dataset': 'dataset'}.get(item.get('type'), 'other'),
        language=item.get('language') or 'und', container=first(item.get('container-title')),
        publisher=item.get('publisher') or '', doi=item.get('DOI'), isbn=first(item.get('ISBN'), None), url=item.get('URL'))


def openalex_record(item):
    location = item.get('primary_location') or {}
    source = location.get('source') or {}
    return SourceMetadata(title=item.get('title') or item.get('display_name'),
        authors=[(a.get('author') or {}).get('display_name', '') for a in item.get('authorships', [])],
        year=item.get('publication_year'), kind={'article': 'article', 'book': 'monograph', 'dissertation': 'dissertation', 'report': 'report', 'dataset': 'dataset'}.get(item.get('type'), 'other'),
        language=item.get('language') or 'und', container=source.get('display_name') or '',
        publisher=source.get('host_organization_name') or '', doi=item.get('doi'), url=location.get('landing_page_url') or item.get('id'))


async def one_provider(provider, request, transport=None):
    result = {'provider': provider, 'adapter_version': ADAPTER_VERSION, 'checked_at': datetime.now(timezone.utc).isoformat(),
              'status': 'unavailable', 'code': None, 'hits': [], 'skipped_records': 0}
    try:
        raw = await fetch_metadata(provider, request, transport)
        if provider == 'crossref':
            message = raw.get('message')
            if not isinstance(message, dict): raise ProviderFailure('invalid_response')
            records = [message] if request.mode == 'doi' else message.get('items')
            parser = crossref_record
        else:
            records = raw.get('results'); parser = openalex_record
        if not isinstance(records, list): raise ProviderFailure('invalid_response')
        for rank, item in enumerate(records[:request.limit], 1):
            try:
                metadata = parser(item).model_dump(mode='json')
                if request.mode == 'doi' and metadata['doi'] != request.query:
                    result['skipped_records'] += 1
                    continue
                result['hits'].append({'id': f'{provider}:{rank}', 'rank': rank, 'metadata': metadata})
            except (ValidationError, TypeError, AttributeError, ValueError, KeyError):
                result['skipped_records'] += 1
        result['status'] = 'completed'
        result['code'] = 'partial_metadata' if result['skipped_records'] else ('ok' if result['hits'] else 'no_results')
    except ProviderFailure as error:
        result['code'] = error.code
    return result


async def fetch_all(request):
    return list(await asyncio.gather(*(one_provider(provider, request) for provider in request.providers)))


def metadata_differences(before, after):
    """Conservative differences for review, not automatic corrections or truth claims."""
    def normalize(value):
        if isinstance(value, list): return [normalize(v) for v in value]
        return ' '.join(value.casefold().split()) if isinstance(value, str) else value
    return [field for field in ('title', 'authors', 'year', 'doi', 'isbn', 'container', 'publisher', 'language', 'kind')
            if before.get(field) not in (None, '', [], 'und', 'other') and after.get(field) not in (None, '', [], 'und', 'other')
            and normalize(before[field]) != normalize(after[field])]
