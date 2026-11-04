"""Three local scientific scenarios. Mock success is not a quality measurement."""
import json
import os
from pathlib import Path
from uuid import UUID
import pytest
from app.scientific_evaluation import CASES,create_case,rubric,main
from app.model_contracts import TaskSpec,Consent
from app.model_jobs import ModelJobs
from app.model_worker import run_once
from app.database import project_engine
from test_projects import storage,client

@pytest.mark.parametrize('case',CASES,ids=lambda case:case['id'])
def test_scientific_scenario_exact_evidence_and_independent_rubric(client,storage,case):
    path,raw=create_case(client,case)
    engine=project_engine(storage[1])
    try:
        q=ModelJobs(engine);project=UUID(path.rsplit('/',1)[1]);task=TaskSpec.model_validate(raw)
        q.configure_budget(project,1000000)
        preview=q.preview(project,task)
        q.enqueue(project,task,Consent(approved=True,fingerprint=preview['fingerprint']))
        job=run_once(q)
        assert job['state']=='succeeded' and job['report']['semantic']=='uncertain'
        assert {e['relation'] for e in job['result']['claims'][0]['evidence']}=={'supports','contradicts','limits'}
        packet=preview['input']['context']
        assert len(job['result']['citations'])==3
        assert {e['content']['original_language'] for e in packet['evidence'].values()}=={'ru','en'}
        for citation in job['result']['citations']:
            evidence=packet['evidence'][citation['evidence_id']]
            assert citation['source_version_id']==evidence['source_version_id']
            assert citation['quote']==evidence['content']['selection']['quote']
        assert rubric(case)['scientific_adequacy']['status']=='requires_expert_review'
        assert rubric(case)['writing_quality']['status']=='requires_expert_review'
        if directory:=os.environ.get('P61_EVALUATION_ARTIFACT_DIR'):
            result=rubric(case)|{'structural_validity':'passed','execution':'local_mock_only',
                'model':'mock-grounded-v1','real_model_quality':'not_measured',
                'quote':preview['input']['quote'],'proposal':job['result'],
                'report':job['report']}
            target=Path(directory);target.mkdir(parents=True,exist_ok=True)
            (target/(case['id']+'.json')).write_text(json.dumps(result,ensure_ascii=False,indent=2)+'\n')
    finally: engine.dispose()

def test_live_preparation_is_blocked_without_side_effects(tmp_path,monkeypatch):
    import json
    target=tmp_path/'report.json'
    monkeypatch.setattr('sys.argv',['evaluation','--output',str(target)])
    monkeypatch.setenv('ARS_OPENAI_APPROVAL','gpt-6.1-sol')
    main();report=json.loads(target.read_text())
    assert report['live_status']=='blocked' and report['provider_calls']==0
    assert report['actual_cost_units'] is None and len(report['cases'])==3

def test_explicit_preparation_creates_only_synthetic_records(storage,monkeypatch,tmp_path):
    import json
    from fastapi.testclient import TestClient
    from app.main import app
    target=tmp_path/'prepared.json'
    monkeypatch.setattr('sys.argv',['evaluation','--prepare','--output',str(target)])
    main();result=json.loads(target.read_text())
    assert result['provider_calls']==0 and result['live_status']=='blocked'
    with TestClient(app) as client:
        assert len(client.get('/api/projects').json())==3
        for case in result['cases']:
            assert case['desired_model']=='gpt-6.1-sol'
            assert case['prepared_mock_task']['model']=='mock-grounded-v1'
            assert len(client.get(case['project_path']+'/evidence').json())==3
