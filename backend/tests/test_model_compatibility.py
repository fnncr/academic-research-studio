"""A documented model must not acquire billing authority through configuration."""
import pytest
from pydantic import ValidationError
from app.model_catalog import unavailable_models
from app.model_contracts import TaskSpec
from app.model_gateway import gateway_for, GatewayUnavailable
from test_projects import storage
from test_evidence import workspace
from test_model_jobs import setup, budget
from test_model_api import api

def test_candidate_never_becomes_an_executable_quote(monkeypatch):
    monkeypatch.setenv('ARS_OPENAI_APPROVAL','gpt-6.1-sol')
    candidate=unavailable_models()[0]
    assert candidate['model']=='gpt-6.1-sol' and not candidate['executable']
    assert candidate['maximum_reservation_units'] is None
    candidate['modes'][0]['enabled']=True
    assert not unavailable_models()[0]['modes'][0]['enabled']
    with pytest.raises(GatewayUnavailable): gateway_for('gpt-6.1-sol')

def test_candidate_cannot_enqueue_via_raw_http(api):
    (q,p,s,c,path,*_),route=api
    before=budget(q,p)
    task=s.model_dump(mode='json')|{'model':'gpt-6.1-sol'}
    caps=c.get(route+'/capabilities').json()
    assert next(v for v in caps['providers'] if v['model']=='gpt-6.1-sol')['ready'] is False
    for suffix,body in [('/preview',task),('',{'task':task,'consent':{'approved':True,'fingerprint':'0'*64}})]:
        assert c.post(route+suffix,json=body).status_code==422
    assert budget(q,p)==before and q.claim() is None
    with pytest.raises(ValidationError): TaskSpec.model_validate(task)
