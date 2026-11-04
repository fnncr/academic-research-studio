"""Regular test runs must never reach the real paid model endpoint."""
import httpx
import pytest


@pytest.fixture(autouse=True)
def no_paid_model_network(monkeypatch):
    original = httpx.HTTPTransport.handle_request
    def guarded(transport, request):
        if request.url.host == 'api.openai.com':
            pytest.fail('Real paid model transport is forbidden in regular tests; use MockTransport')
        return original(transport, request)
    monkeypatch.setattr(httpx.HTTPTransport, 'handle_request', guarded)
    original_async = httpx.AsyncHTTPTransport.handle_async_request
    async def guarded_async(transport, request):
        if request.url.host == 'api.openai.com':
            pytest.fail('Real paid model transport is forbidden in regular tests; use MockTransport')
        return await original_async(transport, request)
    monkeypatch.setattr(httpx.AsyncHTTPTransport, 'handle_async_request', guarded_async)
