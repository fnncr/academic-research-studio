"""Opt-in live metadata check; no database, documents, API keys or raw URLs in output.

Run from backend: PYTHONPATH=. ../.venv/bin/python scripts/check_live_sources.py
Writes JSON to stdout; exits 1 if a required check fails or cannot be completed.
Text-search rank is diagnostic and does not prove publication absence.
Makes at most 16 sequential requests, with no retries or full-text downloads.
"""
import asyncio
from datetime import datetime, timezone
import json
import re
from uuid import uuid4

import httpx

from app.source_adapters import ENDPOINTS, metadata_differences, one_provider
from app.source_schema import SearchRequest


# Bibliographic expectations, not claims about current catalogue responses.
WORKS = [
    {'doi': '10.1038/171737a0', 'year': 1953,
     'title': 'Molecular Structure of Nucleic Acids: A Structure for Deoxyribose Nucleic Acid',
     'authors': ['watson', 'crick'], 'container': 'Nature'},
    {'doi': '10.1371/journal.pmed.0020124', 'year': 2005,
     'title': 'Why Most Published Research Findings Are False',
     'authors': ['ioannidis'], 'container': 'PLoS Medicine'},
    {'doi': '10.1038/sdata.2016.18', 'year': 2016,
     'title': 'The FAIR Guiding Principles for scientific data management and stewardship',
     'authors': ['wilkinson'], 'container': 'Scientific Data'},
]


def normalized(text):
    return re.sub(r'\W+', '', text.casefold())


async def query(provider, text, mode):
    request = SearchRequest(request_id=uuid4(), query=text, providers=[provider],
        mode=mode, source_version_id=uuid4() if mode == 'doi' else None,
        limit=5, consent=True)
    result = await one_provider(provider, request)
    await asyncio.sleep(.15)
    return result


def assess(result, expected):
    hit = next((h for h in result['hits'] if h['metadata']['doi'] == expected['doi']), None)
    if hit is None:
        return {'expected_doi_found': False}
    metadata = hit['metadata']
    return {
        'expected_doi_found': True,
        'title': normalized(metadata['title']) == normalized(expected['title']),
        'year': metadata['year'] == expected['year'],
        # Surnames only: initial expansion and diacritics may differ by provider.
        # This is not a complete audit of every author of the FAIR paper.
        'expected_author_surnames': all(any(name in author.casefold()
            for author in metadata['authors']) for name in expected['authors']),
        'container': normalized(metadata['container']) == normalized(expected['container']),
    }


def required_check_passed(result, checks, mode):
    if result['status'] != 'completed':
        return False
    # Ranked discovery is not an exact lookup contract. Keep metadata comparisons
    # and rank in the report, but never require one known work in the first page.
    return all(checks.values()) if mode == 'doi' else result['code'] in ('ok', 'no_results')


async def main():
    report = {'report_format_version': 2, 'complete_scope': 'required_metadata_and_error_contracts', 'checked_at': datetime.now(timezone.utc).isoformat(),
        'checks': [], 'provider_differences': [], 'errors': [], 'complete': True}
    snapshots = {}
    for provider in ENDPOINTS:
        reachable = True
        for work in WORKS:
            for mode in ('doi', 'search'):
                result = await query(provider, work['doi'] if mode == 'doi' else work['title'], mode)
                checks = assess(result, work)
                report['checks'].append({'expected': work, 'mode': mode, 'result': result, 'checks': checks})
                rank = next((hit['rank'] for hit in result['hits'] if hit['metadata']['doi'] == work['doi']), None)
                report['checks'][-1]['assessment_kind'] = 'exact_doi' if mode == 'doi' else 'ranked_search'
                report['checks'][-1]['expected_doi_rank'] = rank
                report['checks'][-1]['passed'] = required_check_passed(result, checks, mode)
                if not report['checks'][-1]['passed']:
                    report['complete'] = False
                if result['status'] != 'completed':
                    reachable = False
                    break
                match = next((h['metadata'] for h in result['hits'] if h['metadata']['doi'] == work['doi']), None)
                if mode == 'doi' and match:
                    snapshots[(provider, work['doi'])] = match
            if not reachable:
                break  # Do not repeat requests when network/access is unavailable.
        if not reachable:
            continue
        # Explicitly synthetic, deliberately nonexistent-looking identifier.
        missing = await query(provider, '10.5555/ars-live-check-nonexistent-' + uuid4().hex, 'doi')
        passed = missing['code'] in ('record_not_found', 'no_results') and not missing['hits']
        report['errors'].append({'case': 'synthetic_missing_doi', 'result': missing, 'passed': passed})
        report['complete'] &= passed
        # Direct invalid-filter response: separate from production adapter checks.
        try:
            async with httpx.AsyncClient(timeout=5, follow_redirects=False) as client:
                async with client.stream('GET', ENDPOINTS[provider],
                        params={'filter': 'ars_nonexistent_field:true'}) as response:
                    status = response.status_code
            passed = status == 400
            report['errors'].append({'case': 'invalid_filter', 'provider': provider,
                'http_status': status, 'passed': passed})
        except httpx.HTTPError as error:
            passed = False
            report['errors'].append({'case': 'invalid_filter', 'provider': provider,
                'error_type': type(error).__name__, 'passed': False})
        report['complete'] &= passed
    for work in WORKS:
        records = [snapshots.get((provider, work['doi'])) for provider in ENDPOINTS]
        if all(records):
            report['provider_differences'].append({'doi': work['doi'],
                'fields': metadata_differences(*records)})
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0 if report['complete'] else 1


if __name__ == '__main__':
    raise SystemExit(asyncio.run(main()))
