"""No network: exact identification and ranked discovery have distinct contracts."""
from scripts.check_live_sources import WORKS, assess, required_check_passed


def test_ranked_miss_is_not_missing_publication_or_lookup_failure():
    result = {'status': 'completed', 'code': 'ok', 'hits': []}
    checks = assess(result, WORKS[2])
    assert checks == {'expected_doi_found': False}
    assert required_check_passed(result, checks, 'search') is True
    assert required_check_passed(result, checks, 'doi') is False


def test_unavailable_ranked_search_still_fails():
    for code in ['network_unavailable', 'access_denied', 'timeout']:
        assert required_check_passed({'status': 'unavailable', 'code': code}, {}, 'search') is False


def test_exact_metadata_failure_is_required_but_ranked_metadata_is_diagnostic():
    result = {'status': 'completed', 'code': 'ok'}
    assert required_check_passed(result, {'expected_doi_found': True, 'year': False}, 'doi') is False
    assert required_check_passed(result, {'expected_doi_found': True, 'year': False}, 'search') is True
    assert required_check_passed(result, {'expected_doi_found': True, 'year': True}, 'doi') is True
