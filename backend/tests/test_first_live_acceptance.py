from copy import deepcopy
from uuid import UUID
import json,os
from pathlib import Path
import pytest
from app.first_live_acceptance import prepare,verify,TOPIC
from app.database import project_engine
from app.model_jobs import ModelJobs
from test_projects import storage,client

def test_exact_manifest_is_local_reviewable_and_not_enqueued(client,storage):
    engine=project_engine(storage[1])
    try:
        manifest=prepare(client,engine);verify(manifest)
        assert manifest['payload']['reasoning']['effort']=='high'
        assert manifest['payload']['max_output_tokens']==8000
        assert manifest['budget']['maximum_reserve_units']==10540000
        assert manifest['budget']['regional_alternative_reserve_units']==11594000
        assert manifest['budget']['project_snapshot']['reserved_units']==0
        assert manifest['budget']['project_snapshot']['spent_units']==0
        assert len(manifest['preview']['input']['context']['source_versions'])==4
        assert len(manifest['preview']['input']['context']['plan']['claims'])==2
        assert {v['content']['original_language'] for v in manifest['preview']['input']['context']['evidence'].values()}=={'ru','en'}
        assert ModelJobs(engine).claim() is None
        changed=deepcopy(manifest);changed['payload']['reasoning']['effort']='max'
        with pytest.raises(ValueError,match='manifest_changed'):verify(changed)
    finally:engine.dispose()

from test_evidence import workspace
from test_model_jobs import setup,enqueue,dispatched,budget
from test_sol_activation import activated
from app.model_contracts import TaskSpec
from app.model_context import ModelProblem

def test_fifty_dollar_limit_counts_unknown_obligations(setup,activated,monkeypatch):
    q,p,s,client,path,manuscript,*_=setup
    monkeypatch.setenv('ARS_SOL_MAX_UNITS','15000000')
    s=TaskSpec.model_validate(s.model_dump(mode='json')|{'provider':'openai','model':'gpt-6.1-sol',
        'section_id':manuscript['document']['blocks'][0]['id'],'reasoning_effort':'high','max_output_tokens':8000})
    q.configure_budget(p,50000000)
    jobs=[enqueue(q,p,s.model_copy(update={'request_id':__import__('uuid').uuid4()})) for _ in range(4)]
    d=dispatched(q);q.ambiguous(p,d['id'],d['lease_token'],d['dispatch_id'])
    assert budget(q,p)==(50000000,42160000,0)
    with pytest.raises(ModelProblem,match='budget_exhausted'):enqueue(q,p,s)
    for job in jobs:
        if job['id']!=d['id']:q.cancel(p,job['id'])
    assert budget(q,p)[1:]==(10540000,0)
    q.cancel(p,d['id']);assert budget(q,p)[1:]==(10540000,0)
    # No gateway or provider transport was called: this simulates ledger obligations only.
