"""HTTP fixtures only. No environment credentials or paid requests."""
import json
from dataclasses import replace
from uuid import uuid4
import httpx
import pytest
from app.model_adapters.openai_chat import OpenAIChat, MODEL, POLICY, CONTEXT, strict_schema
from app.model_gateway import GatewayUnavailable, AmbiguousOutcome, MockGateway
from app.model_contracts import Proposal
from app.model_worker import run_once
from test_projects import storage
from test_evidence import workspace
from test_model_jobs import setup, enqueue, budget, acceptance

@pytest.fixture
def approved(monkeypatch):
    from datetime import date
    monkeypatch.setattr('app.model_adapters.openai_chat.utc_today',lambda:date(2026,11,4))
    monkeypatch.setenv('ARS_OPENAI_API_KEY','fixture-application-key')
    monkeypatch.setenv('ARS_OPENAI_APPROVAL',POLICY)
    monkeypatch.setenv('ARS_OPENAI_PRICE_CONFIRMED',POLICY)
    monkeypatch.setenv('ARS_OPENAI_MAX_UNITS','500000')

def external(s): return s.model_copy(update={'provider':'openai','model':MODEL})

def api_reply(result):
    return {'model':MODEL,'service_tier':'default','usage':{'prompt_tokens':100,'completion_tokens':50,'total_tokens':150,'prompt_tokens_details':{'cached_tokens':20}},
            'choices':[{'finish_reason':'stop','message':{'content':json.dumps(result)}}]}

def test_schema_required_and_no_extra():
    schema=strict_schema(Proposal)
    assert set(schema['required'])==set(schema['properties']) and schema['additionalProperties'] is False
    assert 'format' not in json.dumps(schema)

@pytest.mark.parametrize('status',[401,403,429,500,503,302])
def test_http_errors_are_single_attempt_ambiguous(setup,approved,status):
    q,p,s,*_=setup;s=external(s);packet=q.preview(p,s)['input']['context']; calls=[]
    g=OpenAIChat(httpx.MockTransport(lambda r:(calls.append(r),httpx.Response(status,json={'private':'never expose'}))[1]))
    with pytest.raises(AmbiguousOutcome):g.generate(packet,s,uuid4())
    assert len(calls)==1 and str(calls[0].url)=='https://api.openai.com/v1/chat/completions'
    body=json.loads(calls[0].content);assert not body['store'] and body['n']==1 and body['service_tier']=='default'
    assert 'tools' not in body and body['response_format']['json_schema']['strict']

def test_success_queue_exact_validation_and_duplicate_settlement(setup,approved):
    q,p,s,*_=setup;s=external(s);packet=q.preview(p,s)['input']['context']
    raw=MockGateway().generate(packet,s,uuid4()).result
    g=OpenAIChat(httpx.MockTransport(lambda r:httpx.Response(200,json=api_reply(raw))))
    enqueue(q,p,s);result=run_once(q,g)
    assert result['state']=='succeeded' and budget(q,p)[1:]==(0,114)
    assert result['report']['scientific_verification']=='unverified'
    assert run_once(q,g) is None
    q.accept(p,result['id'],acceptance(s,result['result']))

@pytest.mark.parametrize('mutation',['json','quote','source','refusal','length'])
def test_invalid_outputs_are_charged_not_repaired(setup,approved,mutation):
    q,p,s,*_=setup;s=external(s);packet=q.preview(p,s)['input']['context'];raw=MockGateway().generate(packet,s,uuid4()).result
    if mutation=='quote':raw['citations'][0]['quote']='invented'
    if mutation=='source':raw['citations'][0]['source_version_id']=str(uuid4())
    reply=api_reply(raw)
    if mutation=='json':reply['choices'][0]['message']['content']='{bad'
    if mutation=='refusal':reply['choices'][0]['message']['refusal']='no'
    if mutation=='length':reply['choices'][0]['finish_reason']='length'
    enqueue(q,p,s);result=run_once(q,OpenAIChat(httpx.MockTransport(lambda r:httpx.Response(200,json=reply))))
    assert result['state']=='invalid' and result['result'] is None and budget(q,p)[2]==114

def test_timeout_no_resend_no_refund(setup,approved):
    q,p,s,*_=setup;s=external(s);job=enqueue(q,p,s);calls=[]
    def timeout(r):calls.append(r);raise httpx.ReadTimeout('private')
    g=OpenAIChat(httpx.MockTransport(timeout));assert run_once(q,g)['state']=='ambiguous'
    q.cancel(p,job['id']);assert budget(q,p)[1]==job['reserved_units'] and run_once(q,g) is None and len(calls)==1

def test_disabled_missing_application_key_and_budget(setup,approved,monkeypatch):
    q,p,s,*_=setup;s=external(s)
    monkeypatch.delenv('ARS_OPENAI_API_KEY')
    with pytest.raises(GatewayUnavailable):OpenAIChat().ready()
    with pytest.raises(ValueError):enqueue(q,p,s)
    assert budget(q,p)[1:]==(0,0)
    monkeypatch.setenv('ARS_OPENAI_API_KEY','fixture')
    monkeypatch.setenv('ARS_OPENAI_MAX_UNITS','1')
    with pytest.raises(ValueError):enqueue(q,p,s)
    assert budget(q,p)[1:]==(0,0)

def test_unknown_billing_holds_full_reserve(setup,approved):
    q,p,s,*_=setup;s=external(s);job=enqueue(q,p,s)
    reply=api_reply({});reply['usage']['completion_tokens_details']={'audio_tokens':5}
    result=run_once(q,OpenAIChat(httpx.MockTransport(lambda r:httpx.Response(200,json=reply))))
    assert result['state']=='ambiguous' and budget(q,p)[1]==job['reserved_units']


def test_review_is_separate_external_job_and_requires_fresh_consent(setup,approved):
    from app.semantic_review import local_review
    from app.manuscripts import digest
    q,p,s,*_=setup;s=external(s);packet=q.preview(p,s)['input']['context'];raw=MockGateway().generate(packet,s,uuid4()).result
    enqueue(q,p,s);source=run_once(q,OpenAIChat(httpx.MockTransport(lambda r:httpx.Response(200,json=api_reply(raw)))))
    review=s.model_copy(update={'request_id':uuid4(),'kind':'semantic_review','review_job_id':source['id'],'review_result_hash':digest(source['result'])})
    packet=q.preview(p,review)['input']['context'];result=local_review(packet,review)
    enqueue(q,p,review);job=run_once(q,OpenAIChat(httpx.MockTransport(lambda r:httpx.Response(200,json=api_reply(result)))))
    assert job['state']=='succeeded' and job['result']['status']=='uncertain' and budget(q,p)[2]==228


def test_configuration_revoked_before_dispatch_never_sends(setup,approved,monkeypatch):
    q,p,s,*_=setup;s=external(s);enqueue(q,p,s);monkeypatch.delenv('ARS_OPENAI_APPROVAL')
    calls=[];g=OpenAIChat(httpx.MockTransport(lambda r:calls.append(r)))
    # A worker without a forced fixture gateway claims then fails preflight safely.
    result=run_once(q)
    assert result['state']=='failed' and result['dispatch_id'] is None and budget(q,p)[1:]==(0,0) and not calls


def test_snapshot_shutdown_fails_closed(approved,monkeypatch):
    from datetime import date
    monkeypatch.setattr('app.model_adapters.openai_chat.utc_today',lambda:date(2027,1,14))
    with pytest.raises(GatewayUnavailable,match='snapshot_retired'):OpenAIChat().ready()
