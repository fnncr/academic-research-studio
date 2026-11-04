"""Provider billing drift must not leave other queued paid jobs runnable."""
from copy import deepcopy
from uuid import uuid4
import httpx
import pytest
from app.model_adapters.openai_chat import OpenAIChat
from app.model_worker import run_once
from app.model_gateway import MockGateway
from app.model_context import ModelProblem
from test_projects import storage
from test_evidence import workspace
from test_model_jobs import setup,enqueue,budget
from test_openai_gateway import approved,external,api_reply


@pytest.mark.parametrize('failure',['model','tier','reasoning','audio','input_bound',
    'unknown_usage','wrong_total','missing_usage','malformed_details','misplaced_cached'])
def test_billing_drift_freezes_queued_spending_and_requires_resolution(setup,approved,failure):
    q,p,s,*_=setup;s=external(s)
    packet=q.preview(p,s)['input']['context'];payload=api_reply(MockGateway().generate(packet,s,uuid4()).result)
    first=enqueue(q,p,s)
    second=enqueue(q,p,s.model_copy(update={'request_id':uuid4()}))
    if failure=='model':payload['model']='unapproved-model'
    if failure=='tier':payload['service_tier']='priority'
    if failure=='reasoning':payload['usage']['completion_tokens_details']={'reasoning_tokens':1}
    if failure=='audio':payload['usage']['prompt_tokens_details']['audio_tokens']=1
    if failure=='input_bound':payload['usage']['prompt_tokens']=2_000_000
    if failure=='unknown_usage':payload['usage']['new_billable_tokens']=100
    if failure=='wrong_total':payload['usage']['total_tokens']=999
    if failure=='missing_usage':payload.pop('usage')
    if failure=='malformed_details':payload['usage']['prompt_tokens_details']=[]
    if failure=='misplaced_cached':payload['usage']['completion_tokens_details']={'cached_tokens':100}
    requests=[]
    def respond(request):requests.append(request);return httpx.Response(200,json=payload)
    gateway=OpenAIChat(httpx.MockTransport(respond))
    result=run_once(q,gateway)
    assert result['state']=='ambiguous' and result['report']['code']=='unconfirmed_billing'
    assert q.budget(p)['blocked'] and budget(q,p)[2]==0
    blocked=run_once(q,gateway)
    assert blocked['id']==second['id'] and blocked['state']=='failed' and len(requests)==1
    assert budget(q,p)[1]==first['reserved_units'] and run_once(q,gateway) is None
    q.cancel(p,first['id'])
    q.reconcile(p,first['id'],first['reserved_units'],'owner_full_reserve')
    assert q.budget(p)['blocked'] and budget(q,p)[1]==0
    with pytest.raises(ModelProblem):enqueue(q,p,s.model_copy(update={'request_id':uuid4()}))
