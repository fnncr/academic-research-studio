"""Responses fixtures only; no Sol admission or live model calls."""
from copy import deepcopy
from random import Random
from uuid import UUID,uuid4
import json
import httpx
import pytest
from app.model_adapters.openai_responses import SolResponses,BillingProfile,charge_usage,MODEL,CONTEXT
from app.model_gateway import MockGateway,GatewayUnavailable,AmbiguousOutcome,UnconfirmedBilling
from sqlalchemy.orm import Session
from app.model_context import ModelProblem
from test_projects import storage
from test_evidence import workspace
from test_model_jobs import setup
from test_openai_gateway import external

@pytest.fixture
def case(setup):
    q,p,s,c,path,manuscript,plan=setup
    original=external(s).model_copy(update={'section_id':UUID(manuscript['document']['blocks'][0]['id'])})
    packet=q.preview(p,original)['input']['context']
    task=original.model_copy(update={'model':MODEL})  # codec fixture; public TaskSpec still rejects Sol
    result=MockGateway().generate(packet,original,uuid4()).result
    return q,p,original,task,packet,result

def usage(inp=1000,out=100,cached=100,short=200,long=300,reasoning=40):
    return {'input_tokens':inp,'output_tokens':out,'total_tokens':inp+out,
        'input_tokens_details':{'cached_tokens':cached,'cache_write_tokens':short+long,
            'cache_write_tokens_details':{'ttl_30m_tokens':short,'ttl_12h_tokens':long}},
        'output_tokens_details':{'reasoning_tokens':reasoning}}

def envelope(result):
    return {'object':'response','model':MODEL,'service_tier':'default','status':'completed',
        'usage':usage(),'error':None,'incomplete_details':None,
        'output':[{'type':'reasoning','summary':[]},{'type':'message','role':'assistant','status':'completed',
        'content':[{'type':'output_text','text':json.dumps(result),'annotations':[]}]}]}

def adapter(payload,**kwargs):
    return SolResponses(httpx.MockTransport(lambda _:httpx.Response(200,json=payload)),**kwargs)

def test_production_gate(case,monkeypatch):
    _,_,_,task,packet,_=case
    for key in ('ARS_OPENAI_APPROVAL','ARS_OPENAI_API_KEY','ARS_OPENAI_PRICE_CONFIRMED'):monkeypatch.setenv(key,MODEL)
    with pytest.raises(GatewayUnavailable,match='sol_not_admitted'):SolResponses().generate(packet,task,uuid4())

@pytest.mark.parametrize('effort',['low','medium','high','xhigh','max'])
def test_request_and_quote_bind_configuration(case,effort):
    _,_,_,task,packet,result=case;requests=[]
    g=SolResponses(httpx.MockTransport(lambda r:(requests.append(r),httpx.Response(200,json=envelope(result)))[1]),effort=effort)
    reply=g.generate(packet,task,uuid4());body=json.loads(requests[0].content)
    assert reply.result==result and reply.charged_units==3810
    assert str(requests[0].url)=='https://api.openai.com/v1/responses'
    assert body['reasoning']=={'effort':effort} and body['text']['format']['strict']
    assert not body['store'] and not body['background'] and body['truncation']=='disabled'
    assert 'tools' not in body and 'previous_response_id' not in body
    assert g.quote(packet,task).max_units>=reply.charged_units
    assert SolResponses(effort='high').quote(packet,task).pricing_version!=SolResponses(effort='low').quote(packet,task).pricing_version
    assert SolResponses(profile=BillingProfile(True)).quote(packet,task).pricing_version!=SolResponses().quote(packet,task).pricing_version

@pytest.mark.parametrize('status',[401,403,429,500,503,302])
def test_http_errors_never_retry(case,status):
    _,_,_,task,packet,_=case;calls=[]
    g=SolResponses(httpx.MockTransport(lambda r:(calls.append(r),httpx.Response(status))[1]))
    with pytest.raises(AmbiguousOutcome):g.generate(packet,task,uuid4())
    assert len(calls)==1

@pytest.mark.parametrize('mutation',['model','tier','missing','total','unknown','missing_detail','negative','bool','writes','overlap','reasoning','input_cap','output_cap','unknown_details','unknown_output','missing_lifetime'])
def test_uncertain_billing(case,mutation):
    _,_,_,task,packet,result=case;raw=envelope(result);u=raw['usage'];d=u['input_tokens_details']
    if mutation=='model':raw['model']='unapproved'
    if mutation=='tier':raw['service_tier']='priority'
    if mutation=='missing':raw.pop('usage')
    if mutation=='total':u['total_tokens']+=1
    if mutation=='unknown':u['new_billed_tokens']=0
    if mutation=='missing_detail':u['input_tokens_details']=None
    if mutation=='negative':d['cached_tokens']=-1
    if mutation=='bool':u['input_tokens']=True
    if mutation=='writes':d['cache_write_tokens']+=1
    if mutation=='overlap':d['cached_tokens']=1001
    if mutation=='reasoning':u['output_tokens_details']['reasoning_tokens']=101
    if mutation=='input_cap':u['input_tokens']=CONTEXT;u['total_tokens']=CONTEXT+100
    if mutation=='output_cap':u['output_tokens']=8001;u['total_tokens']=9001
    if mutation=='unknown_details':d['audio_tokens']=1
    if mutation=='unknown_output':u['output_tokens_details']['audio_tokens']=0
    if mutation=='missing_lifetime':d['cache_write_tokens_details'].pop('ttl_12h_tokens')
    with pytest.raises(UnconfirmedBilling):adapter(raw).generate(packet,task,uuid4())

@pytest.mark.parametrize('mutation',['json','refusal','incomplete','failed','tool','multiple','array','duplicate'])
def test_invalid_content_is_still_charged(case,mutation):
    _,_,_,task,packet,result=case;raw=envelope(result);content=raw['output'][1]['content']
    if mutation=='json':content[0]['text']='{invalid'
    if mutation=='refusal':content[:]=[{'type':'refusal','refusal':'No'}]
    if mutation=='incomplete':raw['status']='incomplete';raw['incomplete_details']={'reason':'max_output_tokens'}
    if mutation=='failed':raw['status']='failed'
    if mutation=='tool':raw['output'].append({'type':'function_call'})
    if mutation=='multiple':raw['output'].append(deepcopy(raw['output'][1]))
    if mutation=='array':content[0]['text']='[]'
    if mutation=='duplicate':content[0]['text']='{"key":1,"key":2}'
    reply=adapter(raw).generate(packet,task,uuid4())
    assert reply.result=={} and reply.charged_units==3810 and reply.billing_details['reasoning_tokens']==40

@pytest.mark.parametrize('failure',['timeout','oversize','json','duplicate'])
def test_unreadable_response(case,failure):
    _,_,_,task,packet,_=case;calls=[]
    def respond(r):
        calls.append(r)
        if failure=='timeout':raise httpx.ReadTimeout('private')
        return httpx.Response(200,content={'oversize':b'x'*(1024*1024+1),'json':b'{broken','duplicate':b'{"usage":1,"usage":2}'}[failure])
    with pytest.raises(AmbiguousOutcome):SolResponses(httpx.MockTransport(respond)).generate(packet,task,uuid4())
    assert len(calls)==1

def test_thresholds_and_reserve_properties(case):
    _,_,_,task,packet,_=case;rng=Random(17)
    for region in (False,True):
        g=SolResponses(profile=BillingProfile(region));quote=g.quote(packet,task)
        for inp in [272000,272001,quote.input_token_bound]+[rng.randrange(quote.input_token_bound+1) for _ in range(100)]:
            cached=rng.randrange(inp+1);short=rng.randrange(inp-cached+1);long=rng.randrange(inp-cached-short+1);out=rng.randrange(task.max_output_tokens+1)
            cost,details=charge_usage(usage(inp,out,cached,short,long,out),quote,g.profile)
            assert 0<=cost<=quote.max_units and details['long_context']==(inp>272000)
        assert charge_usage(usage(),quote,g.profile)[0]==charge_usage(usage(reasoning=0),quote,g.profile)[0]
    quote=SolResponses().quote(packet,task)
    assert charge_usage(usage(272000,100,0,0,0),quote,BillingProfile())[0]==545000
    assert charge_usage(usage(272001,100,0,0,0),quote,BillingProfile())[0]==1089504

def test_section_and_effort_fail_before_send(case):
    _,_,_,task,packet,_=case
    with pytest.raises(ModelProblem,match='section_required'):SolResponses().quote(packet,task.model_copy(update={'section_id':None}))
    with pytest.raises(GatewayUnavailable):SolResponses(effort='ultra')

# Bridge exists only inside this test: real public TaskSpec/gateway admission stays closed.
from app.model_worker import run_once
from test_model_jobs import enqueue,budget,acceptance
from app.model_contracts import Consent
from app.semantic_review import local_review
from app.manuscripts import digest

class QueueFixture(MockGateway):
    def __init__(self,mutate=None):super().__init__();self.mutate=mutate
    def ready(self):return 100000000
    def quote(self,packet,spec):return SolResponses().quote(packet,spec.model_copy(update={'model':MODEL}))
    def generate(self,packet,spec,dispatch):
        self.calls+=1
        raw=envelope(MockGateway().generate(packet,spec,dispatch).result)
        if self.mutate:self.mutate(raw)
        return adapter(raw).generate(packet,spec.model_copy(update={'model':MODEL}),dispatch)

def install_bridge(case,monkeypatch,bridge):
    q,p,original,*_=case
    monkeypatch.setattr('app.model_jobs.gateway_for',lambda _:bridge)
    q.configure_budget(p,100000000)
    return q,p,original

@pytest.mark.parametrize('failure',['none','source','quote','billing','timeout','cancel','lost_db','conflict'])
def test_responses_worker_financial_and_acceptance_invariants(case,monkeypatch,failure):
    bridge=QueueFixture();q,p,s=install_bridge(case,monkeypatch,bridge)
    job=enqueue(q,p,s)
    def mutate(raw):
        if failure in {'source','quote'}:
            result=json.loads(raw['output'][1]['content'][0]['text'])
            result['citations'][0]['source_version_id' if failure=='source' else 'quote']=str(uuid4())
            raw['output'][1]['content'][0]['text']=json.dumps(result)
        if failure=='billing':raw['usage']['input_tokens_details']['cache_write_tokens']+=1
        if failure=='timeout':raise httpx.ReadTimeout('private')
        if failure=='cancel':q.cancel(p,job['id'])
    bridge.mutate=mutate
    if failure=='lost_db':monkeypatch.setattr(q,'_settle',lambda *a,**kw:(_ for _ in ()).throw(RuntimeError('DB unavailable')))
    result=run_once(q,bridge)
    assert bridge.calls==1 and run_once(q,bridge) is None
    if failure in {'timeout','billing','lost_db'}:
        assert result['state']=='ambiguous' and budget(q,p)[1:]==(job['reserved_units'],0)
        if failure=='billing':assert q.budget(p)['blocked']
    else:
        assert budget(q,p)[1:]==(0,3810)
        assert result['report']['billing']['reasoning_tokens']==40
        if failure in {'source','quote'}:assert result['state']=='invalid' and result['result'] is None
        elif failure=='cancel':assert result['state']=='cancelled' and result['result'] is None
        else:
            assert result['state']=='succeeded'
            if failure=='conflict':
                # A competing plan-only revision must block append acceptance.
                with q.engine.begin() as connection:
                    from sqlalchemy import text
                    connection.execute(text("INSERT INTO research_plan_revisions (id,project_id,number,parent_id,manuscript_revision_id,request_id,request_hash,content_hash,document) SELECT :id,project_id,number+1,id,manuscript_revision_id,:request,request_hash,content_hash,document FROM research_plan_revisions WHERE id=:old"),{'id':uuid4(),'request':uuid4(),'old':s.plan_revision_id})
                with pytest.raises(ModelProblem,match='revision_conflict'):q.accept(p,job['id'],acceptance(s,result['result']))
            else:
                request=acceptance(s,result['result']);receipt=q.accept(p,job['id'],request)
                assert q.accept(p,job['id'],request)==receipt

def test_independent_review_fixture_has_separate_cost_and_consent(case,monkeypatch):
    bridge=QueueFixture();q,p,s=install_bridge(case,monkeypatch,bridge)
    enqueue(q,p,s);source=run_once(q,bridge)
    review=s.model_copy(update={'request_id':uuid4(),'kind':'semantic_review','review_job_id':source['id'],'review_result_hash':digest(source['result'])})
    with pytest.raises(ModelProblem,match='consent_mismatch'):
        q.enqueue(p,review,Consent(approved=True,fingerprint='0'*64))
    enqueue(q,p,review);result=run_once(q,bridge)
    assert result['state']=='succeeded' and result['result']['status']=='uncertain'
    assert budget(q,p)[2]==7620 and bridge.calls==2

@pytest.mark.parametrize('cached,short,long,expected',[(0,0,0,3000),(1000,0,0,1100),(0,1000,0,3500),(0,0,1000,6000)])
def test_known_cache_costs_and_regional_premium(case,cached,short,long,expected):
    _,_,_,task,packet,_=case;raw=usage(1000,100,cached,short,long)
    assert charge_usage(raw,SolResponses().quote(packet,task),BillingProfile())[0]==expected
    assert charge_usage(raw,SolResponses(profile=BillingProfile(True)).quote(packet,task),BillingProfile(True))[0]==(expected*11+9)//10

def test_budget_before_dispatch_and_freeze_stops_next_job(case,monkeypatch):
    bridge=QueueFixture();q,p,s=install_bridge(case,monkeypatch,bridge)
    amount=q.preview(p,s)['input']['quote']['max_units'];q.configure_budget(p,amount-1)
    with pytest.raises(ModelProblem,match='budget_exhausted'):enqueue(q,p,s)
    assert q.claim() is None and bridge.calls==0
    q.configure_budget(p,amount*2)
    first=enqueue(q,p,s);second=enqueue(q,p,s.model_copy(update={'request_id':uuid4()}))
    bridge.mutate=lambda raw:raw['usage'].update(unknown_category=1)
    assert run_once(q,bridge)['state']=='ambiguous'
    blocked=run_once(q,bridge)
    assert blocked['id']==second['id'] and blocked['state']=='failed'
    assert bridge.calls==1 and budget(q,p)[1:]==(first['reserved_units'],0)

from app.scientific_evaluation import CASES,create_case
from app.model_contracts import TaskSpec
from app.model_jobs import ModelJobs
from app.database import project_engine
from test_projects import client

@pytest.mark.parametrize('scenario',CASES,ids=lambda item:item['id'])
def test_three_scientific_scenarios_through_responses_fixture(client,storage,scenario,monkeypatch):
    path,raw=create_case(client,scenario)
    manuscript=client.get(path+'/manuscript').json()
    s=external(TaskSpec.model_validate(raw)).model_copy(update={'section_id':UUID(manuscript['document']['blocks'][0]['id'])})
    engine=project_engine(storage[1])
    try:
        q=ModelJobs(engine);p=UUID(path.rsplit('/',1)[1]);bridge=QueueFixture()
        monkeypatch.setattr('app.model_jobs.gateway_for',lambda _:bridge)
        q.configure_budget(p,100000000);enqueue(q,p,s);job=run_once(q,bridge)
        assert job['state']=='succeeded' and job['report']['scientific_verification']=='unverified'
        assert len(job['result']['citations'])==3
        assert {item['relation'] for item in job['result']['claims'][0]['evidence']}=={'supports','contradicts','limits'}
    finally:engine.dispose()
