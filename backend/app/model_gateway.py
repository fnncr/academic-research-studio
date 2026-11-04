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
    billing_details: dict | None = None


class Gateway(Protocol):
    def quote(self, packet: dict, spec) -> Quote: ...
    def generate(self, packet: dict, spec, dispatch_id: UUID) -> GatewayReply: ...


class AmbiguousOutcome(Exception):
    """Request may have been billed; never silently resend."""


class UnconfirmedBilling(AmbiguousOutcome):
    """A provider billing contract changed; freeze spending pending review."""


def messages(packet, spec):
    from app.grounded_writing import PROMPT, prompt_manifest
    require(packet.get('writing_contract') == prompt_manifest(), 'prompt_changed')
    prompt = PROMPT
    if spec.kind == 'semantic_review':
        from app.semantic_review import REVIEW_PROMPT, review_manifest
        require(packet.get('review_contract') == review_manifest(), 'prompt_changed')
        prompt = REVIEW_PROMPT
    return [{'role': 'system', 'content': SYSTEM_RULES+' '+prompt},
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
        if spec.kind == 'semantic_review':
            from app.semantic_review import local_review
            result = local_review(packet, spec)
        else:
            from app.grounded_writing import compose
            result = compose(packet, spec)
        return GatewayReply(result, 100, 50, 50)



class GatewayUnavailable(ValueError):
    """Safe startup/configuration error, contains no credential/provider body."""


def gateway_for(provider):
    if provider == 'mock': return MockGateway()
    if provider == 'openai':
        from app.model_adapters.openai_chat import OpenAIChat
        return OpenAIChat()
    raise GatewayUnavailable('provider_not_approved')


def configured_gateway():
    import os
    return gateway_for(os.environ.get('MODEL_PROVIDER','mock'))


def check_ready(gateway):
    if isinstance(gateway,MockGateway): return
    from app.model_adapters.openai_chat import OpenAIChat
    if isinstance(gateway,OpenAIChat): gateway.ready(); return
    from app.model_adapters.openai_responses import SolResponses
    if isinstance(gateway,SolResponses): gateway.ready(); return
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
