"""Task A: actual owner transport and PostgreSQL; no external model calls."""
import json
import threading
from uuid import uuid4
from dataclasses import replace

import pytest
from sqlalchemy import select, text
from sqlalchemy.orm import Session
from sqlalchemy.exc import DBAPIError
from alembic import command

from app.model_gateway import MockGateway, GatewayUnavailable, configured_gateway, decode_reply, AmbiguousOutcome
from app.model_worker import run_once, serve
from app.models import ModelAudit, ModelBudget
from test_projects import storage, create
from test_evidence import workspace
from test_model_jobs import setup, enqueue, dispatched, response, finish, acceptance, budget

TOKEN='test-owner-token-for-task-a-only-123456789'


@pytest.fixture
def api(setup,monkeypatch):
    q,p,s,client,path,*_=setup
    monkeypatch.setenv('MODEL_OWNER_TOKEN',TOKEN)
    client.headers['Authorization']='Bearer '+TOKEN
    return setup,path+'/model-jobs'


def decision(**kwargs):
    return {'request_id':str(uuid4()),'evidence_ref':'Owner reviewed synthetic receipt','acknowledged':True,**kwargs}


def post_job(client,path,spec):
    preview=client.post(path+'/preview',json=spec.model_dump(mode='json'))
    assert preview.status_code==200,preview.text
    assert 'no external' in preview.json()['input']['disclosure']
    return client.post(path,json={'task':spec.model_dump(mode='json'),
        'consent':{'fingerprint':preview.json()['fingerprint'],'approved':True}})


def test_owner_gating_safe_validation_and_limits(api,monkeypatch):
    (q,p,s,c,path,*_),route=api
    c.headers.pop('Authorization')
    assert c.get(route).status_code==401
    assert c.post(route+'/preview',json={'secret':'PRIVATE'}).status_code==401
    c.headers['Authorization']='Bearer '+TOKEN
    bad=c.post(route+'/preview',json={'instruction':'PRIVATE','unknown':'PRIVATE'})
    assert bad.status_code==422 and 'PRIVATE' not in bad.text
    assert c.post(route+'/preview',content=b'x'*(256*1024+1),headers={'Content-Type':'application/json'}).status_code==413
    assert c.post(route+'/preview',content='{}',headers={'Content-Type':'text/plain'}).status_code==415
    monkeypatch.delenv('MODEL_OWNER_TOKEN')
    assert c.get(route).status_code==503
    assert c.get('/api/health').status_code==200


def test_api_roundtrip_consent_budget_cost_acceptance_audit(api):
    (q,p,s,c,path,manuscript,plan),route=api
    change=decision(limit_units=500000)
    assert c.put(route+'/budget',json=change).status_code==200
    assert c.put(route+'/budget',json=change).status_code==200
    job=post_job(c,route,s); assert job.status_code==202,job.text
    assert 'lease_token' not in job.json() and 'dispatch_id' not in job.json()
    retry=post_job(c,route,s); assert retry.json()['id']==job.json()['id']
    assert c.get(route).json()[0]['id']==job.json()['id']
    run_once(q)
    read=c.get(route+'/'+job.json()['id']); assert read.headers['cache-control']=='no-store'
    assert read.json()['charged_units']==100 and read.json()['held_units']==0
    assert 'result' not in read.json() and 'lease_token' not in read.json()
    result=c.get(route+'/'+job.json()['id']+'/result').json()
    body=acceptance(s,result['result']).model_dump(mode='json')
    accepted=c.post(route+'/'+job.json()['id']+'/accept',json=body)
    assert accepted.status_code==200,accepted.text
    assert c.post(route+'/'+job.json()['id']+'/accept',json=body).json()==accepted.json()
    with Session(q.engine) as db:
        events=list(db.scalars(select(ModelAudit)))
        assert {e.action for e in events}=={'budget','consent','accept'}
        assert all(e.actor=='owner' for e in events)
        consent=next(e for e in events if e.action=='consent')
        assert consent.details['fingerprint']==job.json()['fingerprint']
        assert TOKEN not in str([e.details for e in events])
    with pytest.raises(DBAPIError),q.engine.begin() as connection:
        connection.execute(text('DELETE FROM model_audit'))


def test_scoping_cancel_reconcile_and_explicit_unfreeze(api):
    (q,p,s,c,path,*_),route=api
    job=post_job(c,route,s).json(); d=dispatched(q)
    # A larger-than-reserved charge blocks further project spending.
    finish(q,d,replace(response(d),charged_units=d['reserved_units']+1))
    other='/api/projects/'+create(c)['id']+'/model-jobs/'+job['id']
    assert c.get(other).status_code==404
    assert c.post(other+'/cancel',json=decision()).status_code==404
    assert c.post(other+'/reconcile',json=decision(charged_units=0,reason='provider_receipt')).status_code==404
    assert c.post(route+'/budget/unblock',json=decision()).status_code==409
    assert c.post(route+'/'+job['id']+'/reconcile',json={'charged_units':0,'reason':'provider_receipt'}).status_code==422
    resolve=decision(charged_units=d['reserved_units'],reason='owner_full_reserve')
    resolved=c.post(route+'/'+job['id']+'/reconcile',json=resolve)
    assert resolved.status_code==200,resolved.text
    assert c.post(route+'/'+job['id']+'/reconcile',json=resolve).status_code==200
    assert c.get(route+'/budget').json()['blocked']
    assert c.post(route+'/budget/unblock',json=decision()).status_code==200
    assert not c.get(route+'/budget').json()['blocked']
    next_spec=s.model_copy(update={'request_id':uuid4()}); next_job=post_job(c,route,next_spec).json()
    cancel=decision()
    assert c.post(route+'/'+next_job['id']+'/cancel',json=cancel).json()['state']=='cancelled'
    changed={**cancel,'evidence_ref':'different receipt'}
    assert c.post(route+'/'+next_job['id']+'/cancel',json=changed).status_code==409
    assert budget(q,p)[1]==0


def test_api_consent_changed_and_budget_exhaustion(api):
    (q,p,s,c,path,*_),route=api
    preview=c.post(route+'/preview',json=s.model_dump(mode='json')).json()
    bad={'task':s.model_dump(mode='json'),'consent':{'fingerprint':preview['fingerprint'],'approved':True}}
    bad['task']['title']='changed'
    assert c.post(route,json=bad).status_code==409
    assert c.put(route+'/budget',json=decision(limit_units=0)).status_code==200
    assert post_job(c,route,s).status_code==409


def test_worker_loop_restart_shutdown_and_preflight_failure(setup):
    q,p,s,*_=setup; job=enqueue(q,p,s)
    class BadPricing(MockGateway):
        def quote(self,*args): raise ValueError('sensitive config')
    assert run_once(q,BadPricing())['state']=='failed'
    assert budget(q,p)[1:]==(0,0)
    stop=threading.Event()
    class Loop:
        calls=0
        def recover(self): self.calls+=1; stop.set()
        def claim(self): return None
    loop=Loop(); serve(loop,stop); assert loop.calls==1
    # Existing recovery/fencing/late response tests exercise real PostgreSQL.


def test_gateway_disabled_without_keys_and_no_fallback(monkeypatch):
    monkeypatch.setenv('MODEL_PROVIDER','external')
    monkeypatch.delenv('OPENAI_API_KEY',raising=False)
    with pytest.raises(GatewayUnavailable,match='provider_not_approved'): configured_gateway()
    monkeypatch.setenv('MODEL_PROVIDER','mock')
    assert isinstance(configured_gateway(),MockGateway)


@pytest.mark.parametrize('data',[b'not JSON',b'[]',b'x'*(1024*1024+1),b'{"secret":NaN}'])
def test_decoder_invalid_or_oversize_response_does_not_retry(data):
    with pytest.raises(AmbiguousOutcome): decode_reply(data,100,1,1)


def test_migration_and_receipt_actor_isolation(api,storage):
    (q,p,s,c,path,*_),route=api
    post_job(c,route,s)
    c.headers['Authorization']='Bearer another-owner-token-that-is-not-authorized'
    assert c.get(route).status_code==401
    assert c.get(route+'/budget').status_code==401
    command.check(storage[0]); command.downgrade(storage[0],'0005_model_jobs')
    command.upgrade(storage[0],'head'); command.check(storage[0])


@pytest.mark.parametrize('status',[429,500,503])
def test_http_error_fixtures_never_resend_or_release_uncertain_cost(setup,status):
    import httpx
    q,p,s,*_=setup; job=enqueue(q,p,s)
    class FailedHTTP(MockGateway):
        def generate(self,*args):
            self.calls+=1
            r=httpx.Response(status,request=httpx.Request('POST','https://fixture.invalid'),content=b'PRIVATE')
            r.raise_for_status()
    gateway=FailedHTTP()
    assert run_once(q,gateway)['state']=='ambiguous'
    assert run_once(q,gateway) is None and gateway.calls==1
    assert budget(q,p)[1:]==(job['reserved_units'],0)


def test_worker_cli_processes_mock_job_and_stops_cleanly(setup):
    import os,subprocess,sys,time
    q,p,s,*_=setup; job=enqueue(q,p,s)
    process=subprocess.Popen([sys.executable,'-m','app.model_worker'],stdout=subprocess.PIPE,stderr=subprocess.PIPE,
        env={**os.environ,'MODEL_PROVIDER':'mock'})
    try:
        for _ in range(50):
            if q.read(p,job['id'])['state']=='succeeded': break
            if process.poll() is not None: pytest.fail('worker exited early')
            time.sleep(.1)
        assert q.read(p,job['id'])['state']=='succeeded'
        process.terminate(); _,err=process.communicate(timeout=5)
        assert process.returncode==0 and b'PRIVATE' not in err
    finally:
        if process.poll() is None: process.kill(); process.communicate()


def test_shutdown_after_claim_requeues_without_dispatch(setup):
    q,p,s,*_=setup; job=enqueue(q,p,s); stop=threading.Event()
    class StopGateway(MockGateway):
        def quote(self,*args): stop.set(); return super().quote(*args)
    result=run_once(q,StopGateway(),stop)
    assert result['state']=='queued' and result['dispatch_id'] is None
    assert budget(q,p)[1:]==(job['reserved_units'],0)


def test_capabilities_and_blank_evidence_are_scoped(api):
    (q,p,s,c,path,*_),route=api
    capabilities=c.get(route+'/capabilities')
    assert capabilities.status_code==200 and capabilities.json()['external_enabled'] is False
    assert c.get('/api/projects/'+str(uuid4())+'/model-jobs/capabilities').status_code==404
    assert c.put(route+'/budget',json=decision(limit_units=1,evidence_ref='   ')).status_code==422


def test_enqueue_replay_status(api):
    (q,p,s,c,path,*_),route=api
    assert post_job(c,route,s).status_code==202
    assert post_job(c,route,s).status_code==200
