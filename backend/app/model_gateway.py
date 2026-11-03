"""Minimal mock adapter. No SDK, environment keys, network or executable tools."""
import json
from dataclasses import dataclass
from typing import Protocol
from uuid import UUID

from app.manuscripts import digest
from app.model_context import SYSTEM_RULES, require


@dataclass(frozen=True)
class Quote:
    input_token_bound: int
    output_token_cap: int
    max_units: int
    currency: str = 'USD'
    pricing_version: str = 'mock-microunits-v1'


@dataclass(frozen=True)
class GatewayReply:
    result: dict
    charged_units: int
    input_tokens: int
    output_tokens: int


class Gateway(Protocol):
    def quote(self, packet: dict, spec) -> Quote: ...
    def generate(self, packet: dict, spec, dispatch_id: UUID) -> GatewayReply: ...


class AmbiguousOutcome(Exception):
    """Request may have been billed; never silently resend."""


def messages(packet, spec):
    return [{'role': 'system', 'content': SYSTEM_RULES},
            {'role': 'user', 'content': json.dumps({'task': spec.model_dump(mode='json'),
                                                  'research_data': packet}, ensure_ascii=False, sort_keys=True)}]


class MockGateway:
    """Deterministic fixture generator, not a simulation of semantic reliability."""
    def __init__(self, mode='success'):
        self.mode = mode
        self.calls = 0

    def quote(self, packet, spec):
        bound = len(json.dumps(messages(packet, spec), ensure_ascii=False).encode('utf-8')) + 1024
        require(bound + spec.max_output_tokens <= 128000, 'context_too_large')
        return Quote(bound, spec.max_output_tokens, bound + spec.max_output_tokens)

    def generate(self, packet, spec, dispatch_id):
        self.calls += 1
        if self.mode == 'timeout': raise AmbiguousOutcome()
        assessments = []
        gaps = []
        for claim in packet['plan']['claims']:
            supported = any(e['relation'] == 'supports' for e in claim['evidence'])
            assessments.append({'claim_id': claim['id'], 'status': 'needs_review' if supported else 'insufficient_evidence',
                'explanation': 'Mock: требуется проверка автором.', 'evidence': [
                    {'evidence_id': e['evidence_id'], 'relation': e['relation'], 'explanation': 'Связь сохранена без вывода о достоверности.'}
                    for e in claim['evidence']]})
            if not supported: gaps.append({'claim_id': claim['id'], 'explanation': 'Недостаточно подтверждающих доказательств.'})
        result = {'schema_version': '1', 'context_hash': digest(packet),
                  'paragraphs': ['Тестовое предложение: требуется анализ доказательств автором.'],
                  'claims': assessments, 'citations': [], 'research_gaps': gaps,
                  'warnings': ['Mock не выполняет научную генерацию.'], 'verification': 'unverified'}
        return GatewayReply(result, 100, 50, 50)


class GatewayUnavailable(ValueError):
    """Safe startup/configuration error, contains no credential/provider body."""


def configured_gateway():
    import os
    if os.environ.get('MODEL_PROVIDER','mock') != 'mock':
        raise GatewayUnavailable('provider_not_approved')
    return MockGateway()


def check_ready(gateway):
    if not isinstance(gateway, MockGateway):
        raise GatewayUnavailable('provider_not_approved')


def _reject_constant(value):
    raise ValueError('Non-finite JSON number')


def decode_reply(data, charged_units, input_tokens, output_tokens):
    """Bounded transport decoder for fixture adapters; never prints response data."""
    if len(data)>1024*1024: raise AmbiguousOutcome()
    try:
        result=json.loads(data, parse_constant=_reject_constant)
        if not isinstance(result,dict): raise ValueError()
        if any(type(v) is not int or v<0 for v in (charged_units,input_tokens,output_tokens)): raise ValueError()
        return GatewayReply(result,charged_units,input_tokens,output_tokens)
    except (ValueError,UnicodeError): raise AmbiguousOutcome() from None
