"""Sol Responses codec/transport under contract test, NOT admitted to the registry.

Production ready() always fails closed. Only httpx.MockTransport can execute
this staged adapter; a separate reviewed activation patch is required for live.
"""
import os
import json
import time
from dataclasses import dataclass
import httpx
from app.manuscripts import digest
from app.model_context import require
from app.model_gateway import Quote, GatewayReply, GatewayUnavailable, AmbiguousOutcome, UnconfirmedBilling, _reject_constant
from app.model_adapters.openai_chat import OpenAIChat, unique_object

MODEL = 'gpt-6.1-sol'
ENDPOINT = 'https://api.openai.com/v1/responses'
POLICY = 'sol-activation-2026-11-04-v1'
CONTEXT = 1050000
LONG_CONTEXT = 272000
EFFORTS = {'low', 'medium', 'high', 'xhigh', 'max'}


def ceiling(numerator, denominator):
    return (numerator + denominator - 1) // denominator


@dataclass(frozen=True)
class BillingProfile:
    # An owner must eventually confirm region/account processing; not provider-authored.
    regional: bool = False

    def __post_init__(self):
        if type(self.regional) is not bool: raise ValueError('Invalid region profile')

    def units(self, numerator):
        # numerator is in tenths of micro-USD. No binary floating point money.
        return ceiling(numerator * (11 if self.regional else 10), 100)


def charge_usage(usage, quote, profile):
    def check(ok):
        if not ok: raise UnconfirmedBilling()
    def count(value):
        check(type(value) is int and value >= 0)
        return value
    check(isinstance(usage, dict) and set(usage) == {
        'input_tokens', 'output_tokens', 'total_tokens', 'input_tokens_details', 'output_tokens_details'})
    inp, out, total = [count(usage[k]) for k in ('input_tokens', 'output_tokens', 'total_tokens')]
    check(total == inp + out and total <= CONTEXT and inp <= quote.input_token_bound and out <= quote.output_token_cap)
    details, output = usage['input_tokens_details'], usage['output_tokens_details']
    check(isinstance(details, dict) and set(details) == {'cached_tokens','cache_write_tokens','cache_write_tokens_details'})
    check(isinstance(output, dict) and set(output) == {'reasoning_tokens'})
    cached, written = count(details['cached_tokens']), count(details['cache_write_tokens'])
    reasoning = count(output['reasoning_tokens'])
    writes = details['cache_write_tokens_details']
    check(isinstance(writes, dict) and set(writes) == {'ttl_30m_tokens','ttl_12h_tokens'})
    short, long = count(writes['ttl_30m_tokens']), count(writes['ttl_12h_tokens'])
    check(short + long == written and cached + written <= inp and reasoning <= out)
    multiplier = 2 if inp > LONG_CONTEXT else 1
    numerator = (20*(inp-cached-written) + cached + 25*short + 50*long)*multiplier
    # reasoning is a SUBSET of output_tokens, never charged twice.
    numerator += out * (150 if inp > LONG_CONTEXT else 100)
    units = profile.units(numerator)
    check(units <= quote.max_units)
    return units, {'input_tokens':inp, 'output_tokens':out, 'reasoning_tokens':reasoning,
        'cached_tokens':cached, 'cache_write_30m_tokens':short, 'cache_write_12h_tokens':long,
        'long_context':inp > LONG_CONTEXT, 'regional':profile.regional, 'pricing_policy':POLICY}


class SolResponses:
    def __init__(self, transport=None, *, effort='medium', profile=BillingProfile()):
        if effort not in EFFORTS: raise GatewayUnavailable('unsupported_reasoning_effort')
        if not isinstance(profile, BillingProfile): raise GatewayUnavailable('invalid_billing_profile')
        self.transport, self.effort, self.profile = transport, effort, profile

    def ready(self):
        for key in ('ARS_SOL_APPROVAL','ARS_SOL_DATA_POLICY','ARS_SOL_PRICE_CONFIRMED'):
            if os.environ.get(key) != POLICY: raise GatewayUnavailable('sol_approval_required')
        if os.environ.get('ARS_SOL_MODEL') != MODEL: raise GatewayUnavailable('sol_model_unconfirmed')
        if os.environ.get('ARS_SOL_REGION') not in ('global','regional'): raise GatewayUnavailable('sol_region_unconfirmed')
        if self.profile.regional != (os.environ['ARS_SOL_REGION']=='regional'): raise GatewayUnavailable('sol_region_changed')
        if not os.environ.get('ARS_SOL_API_KEY','').strip(): raise GatewayUnavailable('sol_key_missing')
        try: limit=int(os.environ.get('ARS_SOL_MAX_UNITS','0'))
        except ValueError: raise GatewayUnavailable('sol_limit_invalid') from None
        if not 0<limit<=10**12: raise GatewayUnavailable('sol_limit_invalid')
        return limit

    def body(self, packet, spec):
        require(spec.provider == 'openai' and spec.model == MODEL, 'provider_model_mismatch')
        require(type(spec.max_output_tokens) is int and 256 <= spec.max_output_tokens <= 8000, 'invalid_output_cap')
        if spec.kind == 'writing':
            require(spec.section_id is not None and packet['manuscript'].get('selected_section_id') == str(spec.section_id), 'section_required')
        chat = OpenAIChat().body(packet, spec)
        instructions = chat['messages'][0]['content'] + ' Write in Russian; preserve original-language quotations. Separate facts, interpretations and hypotheses. Do not invent statistical results.'
        return {'model':MODEL, 'instructions':instructions, 'input':[
            {'role':'user','content':[{'type':'input_text','text':chat['messages'][1]['content']}]}],
            'reasoning':{'effort':self.effort}, 'text':{'format':{
                'type':'json_schema', **chat['response_format']['json_schema']}},
            'max_output_tokens':spec.max_output_tokens, 'store':False, 'stream':False,
            'background':False, 'service_tier':'default', 'truncation':'disabled',
            'prompt_cache_options':{'mode':'implicit','ttl':'30m'}}

    def quote(self, packet, spec):
        body = self.body(packet, spec)
        require(len(json.dumps(body, ensure_ascii=False).encode()) <= 128000, 'context_too_large')
        bound = CONTEXT - spec.max_output_tokens
        # Full window at the most expensive write lifetime, long-context rates.
        reserve = self.profile.units(bound*100 + spec.max_output_tokens*150)
        return Quote(bound, spec.max_output_tokens, reserve, 'USD',
            POLICY+':'+digest({'body':body, 'regional':self.profile.regional}))

    def generate(self, packet, spec, dispatch_id):
        if not isinstance(self.transport, httpx.MockTransport): self.ready()
        quote = self.quote(packet, spec)
        if not isinstance(self.transport,httpx.MockTransport) and quote.max_units>self.ready(): raise GatewayUnavailable('sol_call_limit')
        payload=self.body(packet,spec)
        require(quote.pricing_version == POLICY+':'+digest({'body':payload,'regional':self.profile.regional}), 'payload_changed')
        started = time.monotonic()
        try:
            with httpx.Client(transport=self.transport, timeout=httpx.Timeout(45,connect=10), follow_redirects=False) as client:
                with client.stream('POST', ENDPOINT, json=payload, headers={
                    'Authorization':'Bearer '+('contract-fixture-only' if isinstance(self.transport,httpx.MockTransport) else os.environ['ARS_SOL_API_KEY']), 'X-Client-Request-Id':str(dispatch_id)}) as response:
                    if response.status_code != 200: raise AmbiguousOutcome()
                    data = bytearray()
                    for chunk in response.iter_bytes(chunk_size=16384):
                        if time.monotonic()-started > 60 or len(data)+len(chunk)>1024*1024: raise AmbiguousOutcome()
                        data.extend(chunk)
            raw = json.loads(data, parse_constant=_reject_constant, object_pairs_hook=unique_object)
            if not isinstance(raw,dict): raise UnconfirmedBilling()
            if raw.get('model') != MODEL or raw.get('service_tier') != 'default': raise UnconfirmedBilling()
            units, details = charge_usage(raw.get('usage'), quote, self.profile)
            # With definitive usage, invalid/refused/incomplete content is still charged.
            result = {}
            try:
                require(raw.get('object') == 'response' and raw.get('status') == 'completed' and raw.get('error') is None
                        and raw.get('incomplete_details') is None, 'invalid_response')
                output = raw['output']
                require(isinstance(output,list), 'invalid_response')
                messages = [item for item in output if item.get('type')=='message']
                require(all(item.get('type') in {'message','reasoning'} for item in output) and len(messages)==1, 'invalid_response')
                message = messages[0]
                require(message['role']=='assistant' and message['status']=='completed', 'invalid_response')
                content = message['content']
                require(len(content)==1 and content[0]['type']=='output_text', 'invalid_response')
                result = json.loads(content[0]['text'],parse_constant=_reject_constant,object_pairs_hook=unique_object)
                require(isinstance(result,dict), 'invalid_response')
            except (ValueError,KeyError,TypeError,AttributeError): result = {}
            return GatewayReply(result, units, details['input_tokens'], details['output_tokens'], details)
        except AmbiguousOutcome: raise
        except Exception: raise AmbiguousOutcome() from None


def sol_gateway(spec):
    return SolResponses(effort=spec.reasoning_effort or 'medium',
        profile=BillingProfile(os.environ.get('ARS_SOL_REGION')=='regional'))
