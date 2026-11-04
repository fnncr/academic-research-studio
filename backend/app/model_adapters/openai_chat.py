"""Disabled-by-default, fixed text-only OpenAI Chat Completions adapter."""
import json
import os
import time
from datetime import datetime, timezone, date
from copy import deepcopy
import httpx
from app.model_gateway import Quote, GatewayReply, GatewayUnavailable, AmbiguousOutcome, messages, _reject_constant
from app.model_contracts import Proposal, SemanticReview
from app.model_context import require
from app.manuscripts import digest

MODEL = 'gpt-4.1-mini-2025-04-14'
POLICY = 'openai-gpt41mini-2026-11-04-v1'
ENDPOINT = 'https://api.openai.com/v1/chat/completions'
CONTEXT = 1047576
DISCLOSURE = ('OpenAI US/default API endpoint; text context and originals leave this installation. '
              'store=false; API data not used for training by default. Abuse monitoring may retain '
              'content up to 30 days; caching/contract exceptions apply. No Zero Data Retention promise. '+POLICY)

def utc_today(): return datetime.now(timezone.utc).date()

def unique_object(pairs):
    value={}
    for key,item in pairs:
        if key in value: raise ValueError('Duplicate JSON key')
        value[key]=item
    return value

def strict_schema(contract):
    schema = deepcopy(contract.model_json_schema())
    def visit(value):
        if isinstance(value, dict):
            for key in list(value):
                if key in {'default','title','format','minLength','maxLength','pattern','minimum','maximum','minItems','maxItems'}: value.pop(key)
            if 'const' in value: value['enum']=[value.pop('const')]
            if value.get('type')=='object':
                value['additionalProperties']=False; value['required']=list(value.get('properties',{}))
            for child in value.values(): visit(child)
        elif isinstance(value,list):
            for child in value: visit(child)
    visit(schema); return schema

class OpenAIChat:
    def __init__(self, transport=None): self.transport=transport

    def ready(self):
        if utc_today() >= date(2027,1,14): raise GatewayUnavailable('openai_snapshot_retired')
        if os.environ.get('ARS_OPENAI_APPROVAL') != POLICY or os.environ.get('ARS_OPENAI_PRICE_CONFIRMED') != POLICY:
            raise GatewayUnavailable('openai_owner_approval_required')
        if not os.environ.get('ARS_OPENAI_API_KEY','').strip(): raise GatewayUnavailable('openai_application_key_missing')
        try: limit=int(os.environ.get('ARS_OPENAI_MAX_UNITS','0'))
        except ValueError: raise GatewayUnavailable('openai_budget_invalid') from None
        if not 0 < limit <= 10**12: raise GatewayUnavailable('openai_budget_invalid')
        return limit

    def quote(self, packet, spec):
        require(spec.model==MODEL and spec.provider=='openai', 'provider_model_mismatch')
        # Reserve the entire documented model window, not a guessed tokenizer count.
        payload=self.body(packet,spec)
        require(len(json.dumps(payload,ensure_ascii=False).encode())<=128000, 'context_too_large')
        maximum=((CONTEXT-spec.max_output_tokens)*4+spec.max_output_tokens*16+9)//10
        return Quote(CONTEXT-spec.max_output_tokens,spec.max_output_tokens,maximum,'USD',POLICY+':'+digest(payload))

    def body(self,packet,spec):
        contract=SemanticReview if spec.kind=='semantic_review' else Proposal
        system=('Independently assess claim/passage/evidence correspondence. Return uncertain or insufficient_data when needed. '
                if spec.kind=='semantic_review' else
                'Write a coherent academic section, not an excerpt collage. Compare positions, distinguish facts from interpretations, '
                'use cautious conclusions and correct terminology; identify research gaps. ')
        system+=('Only the consented research data may support factual statements. Unknown authors/DOI/locators are forbidden. '
                 'Keep contradictions and limitations. Never claim verified truth. Return exact UTF-16 citation spans. ')
        msgs=messages(packet,spec)
        msgs[0]['content']=msgs[0]['content'].replace('Return only the proposal schema;', 'Return only the requested structured result schema;')+' '+system
        data=json.loads(msgs[1]['content']); data['expected_context_hash']=digest(packet)
        msgs[1]['content']=json.dumps(data,ensure_ascii=False,sort_keys=True)
        return {'model':MODEL,'messages':msgs,'store':False,'service_tier':'default','stream':False,'n':1,'max_completion_tokens':spec.max_output_tokens,
                'response_format':{'type':'json_schema','json_schema':{'name':'research_result','strict':True,'schema':strict_schema(contract)}}}

    def generate(self,packet,spec,dispatch_id):
        limit=self.ready(); quote=self.quote(packet,spec)
        if quote.max_units>limit: raise GatewayUnavailable('openai_call_budget_exceeded')
        started=time.monotonic()
        try:
            with httpx.Client(transport=self.transport,timeout=httpx.Timeout(45,connect=10),follow_redirects=False) as client:
                with client.stream('POST',ENDPOINT,json=self.body(packet,spec),headers={
                    'Authorization':'Bearer '+os.environ['ARS_OPENAI_API_KEY'], 'X-Client-Request-Id':str(dispatch_id)}) as response:
                    if response.status_code!=200: raise AmbiguousOutcome() # includes 401/429/5xx, never retry
                    data=bytearray()
                    for chunk in response.iter_bytes(chunk_size=16384):
                        if time.monotonic()-started>60: raise AmbiguousOutcome()
                        if len(data)+len(chunk)>1024*1024: raise AmbiguousOutcome()
                        data.extend(chunk)
            raw=json.loads(data,parse_constant=_reject_constant,object_pairs_hook=unique_object)
            require(raw['model']==MODEL and raw.get('service_tier')=='default', 'unexpected_model_or_tier')
            usage=raw['usage']; inp=usage['prompt_tokens']; out=usage['completion_tokens']
            cached=usage.get('prompt_tokens_details',{}).get('cached_tokens',0)
            reasoning=usage.get('completion_tokens_details',{}).get('reasoning_tokens',0)
            if any(type(v)is not int or v<0 for v in (inp,out,cached,reasoning)) or cached>inp: raise AmbiguousOutcome()
            if inp>quote.input_token_bound or out>spec.max_output_tokens or reasoning: raise AmbiguousOutcome()
            # No audio/tools/prediction accepted. Unknown billed token categories require investigation.
            for details in (usage.get('prompt_tokens_details',{}),usage.get('completion_tokens_details',{})):
                if any(v for k,v in details.items() if k not in {'cached_tokens','reasoning_tokens'}): raise AmbiguousOutcome()
            charge=((inp-cached)*4+cached+out*16+9)//10
            choice=raw['choices'][0]; message=choice['message']; result={}
            if choice.get('finish_reason')=='stop' and not message.get('refusal') and not message.get('tool_calls'):
                try: result=json.loads(message['content'],parse_constant=_reject_constant,object_pairs_hook=unique_object)
                except (ValueError,TypeError): pass # definitive usage: invalid output is still charged
            return GatewayReply(result,charge,inp,out)
        except AmbiguousOutcome: raise
        except Exception: raise AmbiguousOutcome() from None
