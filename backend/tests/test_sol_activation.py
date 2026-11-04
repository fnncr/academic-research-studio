from uuid import UUID,uuid4
import json
import httpx
import pytest
from app.model_adapters.openai_responses import SolResponses,POLICY,MODEL
from app.model_worker import run_once
from app.model_contracts import TaskSpec,Consent
from app.model_context import ModelProblem
from app.model_gateway import MockGateway,GatewayUnavailable
from app.manuscripts import digest
from test_projects import storage
from test_evidence import workspace
from test_model_jobs import setup,enqueue,budget
from test_sol_responses import envelope

@pytest.fixture
def activated(monkeypatch):
    for name in ('ARS_SOL_APPROVAL','ARS_SOL_DATA_POLICY','ARS_SOL_PRICE_CONFIRMED'):monkeypatch.setenv(name,POLICY)
    monkeypatch.setenv('ARS_SOL_MODEL',MODEL);monkeypatch.setenv('ARS_SOL_REGION','global')
    monkeypatch.setenv('ARS_SOL_API_KEY','fixture-only');monkeypatch.setenv('ARS_SOL_MAX_UNITS','20000000')

@pytest.mark.parametrize('missing',['ARS_SOL_APPROVAL','ARS_SOL_DATA_POLICY','ARS_SOL_PRICE_CONFIRMED','ARS_SOL_MODEL','ARS_SOL_REGION','ARS_SOL_API_KEY','ARS_SOL_MAX_UNITS'])
def test_each_gate_required(activated,monkeypatch,missing):
    monkeypatch.delenv(missing)
    with pytest.raises(GatewayUnavailable):SolResponses().ready()

def test_real_registry_queue_with_fixture_transport(setup,activated,monkeypatch):
    q,p,s,client,path,manuscript,plan=setup
    s=TaskSpec.model_validate(s.model_dump(mode='json')|{'provider':'openai','model':MODEL,'section_id':manuscript['document']['blocks'][0]['id'],'reasoning_effort':'high'})
    q.configure_budget(p,50000000)
    preview=q.preview(p,s);est=preview['input']['budget_estimate']
    assert est['reserved_cost']==preview['input']['quote']['max_units'] and est['reserve_reduction_units']==0
    assert est['estimated_cost'] is None and est['context_hash']==digest(preview['input']['context'])
    with pytest.raises(ModelProblem,match='consent_mismatch'):q.enqueue(p,s.model_copy(update={'reasoning_effort':'max'}),Consent(approved=True,fingerprint=preview['fingerprint']))
    job=enqueue(q,p,s)
    calls=[]
    def respond(r):
        calls.append(r);body=json.loads(r.content);assert body['reasoning']['effort']=='high'
        packet=json.loads(body['input'][0]['content'][0]['text'])['research_data']
        return httpx.Response(200,json=envelope(MockGateway().generate(packet,s,uuid4()).result))
    # Replace only httpx transport; registry/service/worker stay real.
    original=SolResponses.__init__
    def fixture(self,*args,**kwargs):original(self,httpx.MockTransport(respond),**kwargs)
    monkeypatch.setattr(SolResponses,'__init__',fixture)
    result=run_once(q)
    assert result['state']=='succeeded' and len(calls)==1 and budget(q,p)[2]==3810
    assert run_once(q) is None
    assert q.enqueue(p,s,Consent(approved=True,fingerprint=q.preview(p,s)['fingerprint']))['id']==job['id']

def test_disabled_enqueue_never_reserves(setup,monkeypatch):
    q,p,s,client,path,manuscript,*_=setup
    monkeypatch.delenv('ARS_SOL_APPROVAL',raising=False)
    s=TaskSpec.model_validate(s.model_dump(mode='json')|{'provider':'openai','model':MODEL,'section_id':manuscript['document']['blocks'][0]['id']})
    with pytest.raises(ModelProblem,match='provider_configuration_unavailable'):enqueue(q,p,s)
    assert budget(q,p)[1:]==(0,0)

def test_configuration_revocation_stops_queued_sol(setup,activated,monkeypatch):
    q,p,s,client,path,manuscript,*_=setup
    s=TaskSpec.model_validate(s.model_dump(mode='json')|{'provider':'openai','model':MODEL,'section_id':manuscript['document']['blocks'][0]['id']})
    q.configure_budget(p,20000000);job=enqueue(q,p,s)
    monkeypatch.delenv('ARS_SOL_DATA_POLICY')
    assert run_once(q)['state']=='failed' and budget(q,p)[1:]==(0,0)
    assert q.read(p,job['id'])['held_units']==0

def test_payload_change_after_consent_cannot_dispatch(setup,activated,monkeypatch):
    q,p,s,client,path,manuscript,*_=setup
    s=TaskSpec.model_validate(s.model_dump(mode='json')|{'provider':'openai','model':MODEL,'section_id':manuscript['document']['blocks'][0]['id']})
    q.configure_budget(p,20000000);enqueue(q,p,s)
    original=SolResponses.body
    def changed(self,*args):return original(self,*args)|{'instructions':'different policy'}
    monkeypatch.setattr(SolResponses,'body',changed)
    assert run_once(q)['state']=='failed' and budget(q,p)[1:]==(0,0)

def test_live_cli_defaults_to_no_action(tmp_path,monkeypatch,capsys):
    from app.sol_live_acceptance import main
    target=tmp_path/'manifest.json'
    monkeypatch.setattr('sys.argv',['live','--manifest',str(target)])
    main()
    assert 'blocked' in capsys.readouterr().out and not target.exists()
