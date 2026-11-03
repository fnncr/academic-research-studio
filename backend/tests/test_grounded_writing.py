"""Synthetic multilingual evidence and separately persisted review jobs."""
from copy import deepcopy
from uuid import UUID, uuid4

import pytest
from pydantic import ValidationError
from sqlalchemy.orm import Session
from sqlalchemy import select

from app.manuscripts import digest
from app.model_context import ModelProblem, validate_proposal
from app.model_contracts import TaskSpec, HumanReviewSubmission
from app.model_worker import run_once
from app.model_gateway import messages
from app.semantic_review import local_review, validate_review, targets
from app.models import ModelJob, ModelSettlement, ModelAudit
from test_projects import storage, create
from test_evidence import workspace, excerpt
from test_model_jobs import setup, enqueue, acceptance, budget
from test_sources import write, metadata


def review_spec(spec, source):
    return spec.model_copy(update={'request_id':uuid4(),'kind':'semantic_review',
        'review_job_id':source['id'],'review_result_hash':digest(source['result'])})


def revised(q,p,s,c,path,manuscript,old,links,extra=None):
    doc=deepcopy(old['document']); doc['claims'][0]['evidence']=links
    doc['citations']=[]
    if extra: doc['claims'].append(extra)
    result=c.post(path+'/research-plan/revisions',json={'request_id':str(uuid4()),'base_revision_id':old['id'],
        'manuscript_revision_id':manuscript['id'],'document':doc})
    assert result.status_code==201,result.text
    ids=[UUID(claim['id']) for claim in doc['claims']]
    return s.model_copy(update={'plan_revision_id':UUID(result.json()['id']),'claim_ids':ids})


def test_mixed_languages_contradictions_limits_and_provenance(setup):
    q,p,s,c,path,manuscript,old=setup
    links=deepcopy(old['document']['claims'][0]['evidence'])
    original={}
    for language,relation,quote in [('ru','supports','Синтетическое наблюдение.'),('en','limits','Synthetic limitation.')]:
        source=write(c,path+'/sources',{**metadata(),'doi':None,'title':'Fixture '+language,'authors':[],'year':None}).json()
        body=excerpt(source['latest_version']['id']); body.update(excerpt=quote,original_language=language,
            selection={'start':0,'end':len(quote.encode('utf-16-le'))//2,'quote':quote})
        evidence=c.post(path+'/evidence',json=body).json(); original[evidence['id']]=quote
        links.append({'evidence_id':evidence['id'],'relation':relation,'rationale':'Synthetic'})
    s=revised(*setup,links)
    enqueue(q,p,s); job=run_once(q)
    assert job['state']=='succeeded'
    assert len(job['result']['citations'])==3
    for citation in job['result']['citations']:
        if citation['evidence_id'] in original: assert citation['quote']==original[citation['evidence_id']]
    text='\n'.join(job['result']['paragraphs'])
    assert 'Противоречащий' in text and 'Ограничивающий' in text and 'ru' in text and 'en' in text
    assert job['result']['claims'][0]['status']=='needs_review'
    assert job['result']['verification']=='unverified'
    report=job['report']; assert report['provenance']['prompt_version']=='evidence-sections-v1'
    assert len(report['provenance']['source_hashes'])==3
    assert any('authors' in d['missing_fields'] for d in report['bibliography_diagnostics'].values())
    assert report['execution']['quote']['pricing_version']=='mock-microunits-v1'
    accepted=q.accept(p,job['id'],acceptance(s,job['result']))
    assert accepted['manuscript_revision_id']!=s.manuscript_revision_id
    assert c.get(path+'/research-plan').json()['document']['claims']==c.get(path+'/research-plan/revisions/'+str(s.plan_revision_id)).json()['document']['claims']


def test_no_evidence_is_a_gap_not_a_fact_and_empty_review(setup):
    q,p,s,c,path,manuscript,old=setup
    s=revised(*setup,[])
    enqueue(q,p,s); source=run_once(q)
    assert source['result']['claims'][0]['status']=='insufficient_evidence'
    assert source['result']['research_gaps'] and not source['result']['citations']
    task=review_spec(s,source); enqueue(q,p,task); result=run_once(q)
    assert result['state']=='succeeded' and result['result']['status']=='insufficient_data'
    assert result['result']['findings']==[]


def test_semantic_review_is_separate_costed_immutable_and_not_acceptable_as_text(setup):
    q,p,s,*_=setup; enqueue(q,p,s); source=run_once(q)
    task=review_spec(s,source); preview=q.preview(p,task)
    assert preview['input']['context']['review_subject']['result_hash']==digest(source['result'])
    enqueue(q,p,task); review=run_once(q)
    assert review['state']=='succeeded' and review['result']['status']=='uncertain'
    assert review['result']['result_hash']==digest(source['result'])
    assert review['report']['reviewed_job_id']==str(source['id'])
    assert review['report']['provenance']['plan']==str(s.plan_revision_id)
    assert all(f['outcome']=='uncertain' and f['limitations'] for f in review['result']['findings'])
    assert budget(q,p)[2]==200
    assert q.read(p,source['id'])['report']['semantic']=='uncertain'
    with pytest.raises(ModelProblem,match='review_not_acceptable_as_text'):
        q.accept(p,review['id'],acceptance(task,review['result']))


@pytest.mark.parametrize('mutation,code',[('hash','review_result_mismatch'),('quote','quotation_mismatch'),
    ('evidence','review_coverage_mismatch'),('claim','review_coverage_mismatch'),('paragraph','review_coverage_mismatch'),
    ('omit','review_coverage_mismatch'),('duplicate','review_coverage_mismatch'),('limits','review_limitations_required')])
def test_semantic_review_independent_exact_checks(setup,mutation,code):
    q,p,s,*_=setup; enqueue(q,p,s); source=run_once(q); task=review_spec(s,source)
    packet=q.preview(p,task)['input']['context']; raw=local_review(packet,task)
    if mutation=='hash': raw['result_hash']='0'*64
    if mutation=='quote': raw['findings'][0]['evidence_quote']='Not the quote'
    if mutation=='evidence': raw['findings'][0]['evidence_id']=str(uuid4())
    if mutation=='claim': raw['findings'][0]['claim_id']=str(uuid4())
    if mutation=='paragraph': raw['findings'][0]['paragraph']=19
    if mutation=='omit': raw['findings']=[]
    if mutation=='duplicate': raw['findings'].append(deepcopy(raw['findings'][0]))
    if mutation=='limits': raw['findings'][0]['limitations']=[]
    with pytest.raises(ModelProblem,match=code): validate_review(packet,raw)


def test_human_review_zero_cost_without_model_or_budget_and_replay(setup):
    q,p,s,*_=setup; enqueue(q,p,s); source=run_once(q); task=review_spec(s,source)
    packet=q.preview(p,task)['input']['context']; raw=local_review(packet,task)
    raw.update(reviewer_kind='human',reviewer_version='Owner review fixture v1')
    submission=HumanReviewSubmission(request_id=uuid4(),review=raw,acknowledged=True)
    before=budget(q,p)
    first=q.human_review(p,source['id'],submission,'owner')
    assert q.human_review(p,source['id'],submission,'owner')['id']==first['id']
    assert budget(q,p)==before
    with Session(q.engine) as db:
        settlement=db.get(ModelSettlement,first['id'])
        assert settlement.charged_units==0 and settlement.reason=='human_review_no_model'
        assert db.scalar(select(ModelAudit).where(ModelAudit.job_id==first['id'])).action=='human_review'
    q.cancel(p,source['id'])
    assert q.human_review(p,source['id'],submission,'owner')['id']==first['id']
    with pytest.raises(ModelProblem,match='request_conflict'):
        altered=submission.model_copy(update={'review':submission.review.model_copy(update={'reviewer_version':'changed'})})
        q.human_review(p,source['id'],altered,'owner')


def test_review_foreign_job_changed_hash_and_subject_schema_rejected(setup):
    q,p,s,c,*_=setup; enqueue(q,p,s); source=run_once(q)
    other=UUID(create(c)['id'])
    task=review_spec(s,source)
    from fastapi import HTTPException
    with pytest.raises((HTTPException,ModelProblem)): q.preview(other,task)
    with pytest.raises(ModelProblem,match='review_result_mismatch'):
        q.preview(p,task.model_copy(update={'review_result_hash':'0'*64}))
    with pytest.raises(ValidationError): TaskSpec.model_validate({**s.model_dump(),'kind':'semantic_review'})
    enqueue(q,p,task); review=run_once(q)
    with pytest.raises(ModelProblem,match='invalid_review_subject'): q.preview(p,review_spec(s,review))


def test_local_output_capacity_does_not_silently_trim_evidence(setup):
    q,p,s,*_=setup
    small=s.model_copy(update={'max_output_tokens':256})
    with pytest.raises(ModelProblem,match='output_capacity_exceeded'): q.preview(p,small)
    assert budget(q,p)[1:]==(0,0)


def test_prompt_change_before_dispatch_does_not_send_old_consent(setup,monkeypatch):
    q,p,s,*_=setup; enqueue(q,p,s)
    monkeypatch.setattr('app.grounded_writing.PROMPT','changed same authority rules')
    result=run_once(q)
    assert result['state']=='failed' and result['dispatch_id'] is None and budget(q,p)[1:]==(0,0)


def test_model_injection_extra_fields_and_false_verification_rejected(setup):
    q,p,s,*_=setup; enqueue(q,p,s); source=run_once(q)
    for field in ('doi','authors','tools','locator','configuration'):
        raw=deepcopy(source['result']); raw[field]='Injected'
        with Session(q.engine) as db,pytest.raises(ValidationError):
            validate_proposal(db,p,s,q.preview(p,s)['input']['context'],raw)
    task=review_spec(s,source); packet=q.preview(p,task)['input']['context']; raw=local_review(packet,task)
    raw['status']='verified'
    with pytest.raises(ValidationError): validate_review(packet,raw)


def test_http_review_and_zero_cost_human_route(setup,monkeypatch):
    from test_model_api import TOKEN, post_job
    q,p,s,c,path,*_=setup
    monkeypatch.setenv('MODEL_OWNER_TOKEN',TOKEN); c.headers['Authorization']='Bearer '+TOKEN
    route=path+'/model-jobs'
    assert post_job(c,route,s).status_code==202
    source=run_once(q); task=review_spec(s,source)
    assert post_job(c,route,task).status_code==202
    result=run_once(q)
    assert c.get(route+'/'+str(result['id'])+'/result').json()['result']['status']=='uncertain'
    raw=deepcopy(result['result']); raw.update(reviewer_kind='human',reviewer_version='Owner fixture')
    submission={'request_id':str(uuid4()),'review':raw,'acknowledged':True}
    human=c.post(route+'/'+str(source['id'])+'/human-review',json=submission)
    assert human.status_code==200,human.text
    assert human.json()['result']['reviewer_kind']=='human'
    assert 'lease_token' not in human.json()
    assert c.post(route+'/'+str(source['id'])+'/human-review',json=submission).json()['id']==human.json()['id']
    c.headers.pop('Authorization')
    assert c.post(route+'/'+str(source['id'])+'/human-review',json=submission).status_code==401


def test_reviewer_cannot_impersonate_human_or_omit_explanation(setup):
    from test_model_jobs import dispatched, finish, response
    from dataclasses import replace
    q,p,s,*_=setup; enqueue(q,p,s); source=run_once(q); task=review_spec(s,source)
    enqueue(q,p,task); d=dispatched(q); reply=response(d)
    raw=deepcopy(reply.result); raw['reviewer_kind']='human'
    assert finish(q,d,replace(reply,result=raw))['state']=='invalid'
    packet=q.preview(p,task)['input']['context']; raw=local_review(packet,task)
    raw['findings'][0]['explanation']=' '
    with pytest.raises(ModelProblem,match='review_explanation_required'): validate_review(packet,raw)


def test_review_target_overflow_never_drops_opposition(setup):
    q,p,s,*_=setup; enqueue(q,p,s); source=run_once(q); task=review_spec(s,source)
    packet=q.preview(p,task)['input']['context']
    claim=packet['plan']['claims'][0]; link=claim['evidence'][0]
    # Pure target admission: One claim x 6 evidence links x 20 paragraphs > 100.
    claim['evidence']=[{**link,'evidence_id':str(uuid4()),'relation':'contradicts'} for _ in range(6)]
    packet['review_subject']['result']['citations']=[]
    packet['review_subject']['result']['paragraphs']=['Synthetic']*20
    with pytest.raises(ModelProblem,match='review_capacity_exceeded'): targets(packet)
