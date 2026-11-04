"""Prepare the exact first-live case locally. This module never enqueues or calls a model."""
from copy import deepcopy
from uuid import UUID,uuid4
from app.model_contracts import TaskSpec
from app.model_api import BudgetDecision
from app.model_jobs import ModelJobs
from app.model_adapters.openai_responses import sol_gateway,ENDPOINT,BillingProfile,SolResponses
from app.manuscripts import digest

TOPIC='Влияние цифровых финансовых технологий на эффективность денежного обращения'
QUESTION='При каких условиях цифровые финансовые технологии могут повышать эффективность денежного обращения и какие риски ограничивают этот вывод?'
REQUIREMENTS='Синтетический тест по экономической теории. Русский академический раздел объёмом 700–1000 слов: сопоставить позиции, различать факты, интерпретации и гипотезы, сохранить противоречия и ограничения. Использовать только предоставленные SYNTHETIC Evidence, не добавлять авторов, DOI, страницы, статистику или реальные публикации.'
SOURCES=[
 ('ru','supports','В синтетической модели цифровые расчёты сократили число ручных этапов обработки платежа. Это характеристика тестовой модели, а не измеренный результат реального рынка.'),
 ('en','contradicts','In the synthetic counter-scenario, digital payment outages delayed settlement and increased precautionary liquidity demand. Faster normal processing did not guarantee greater system-wide efficiency.'),
 ('ru','limits','Синтетическая схема не учитывает стоимость внедрения, киберриски, неодинаковый доступ участников и поведение банков. Устойчивый причинный эффект и общеэкономическая эффективность на этих данных не установлены.'),
 ('en','limits','The synthetic comparison contains no representative sample, monetary cost estimates, or causal identification. Changes in payment speed cannot be treated as evidence of lower inflation or higher welfare.'),
]
INSTRUCTION='Написать содержательный научный раздел на русском, ориентировочно 700–1000 слов, по теме «'+TOPIC+'». Структура: понятие эффективности денежного обращения; механизм потенциальных преимуществ; сопоставление с рисками и противоположной позицией; ограничения и осторожный вывод; исследовательские пробелы. Не выдавать синтетические источники за реальные публикации. Подкреплять внешние утверждения сохранёнными Evidence и не выдумывать численные эффекты. Оригинальные RU/EN цитаты сохранять без перевода. Данные не доказывают влияние на инфляцию или благосостояние.'

def prepare(client,engine):
    def post(path,body):
        response=client.post(path,json=body)
        if response.status_code!=201:raise RuntimeError('first_live_preparation_failed')
        return response.json()
    project=post('/api/projects',{'title':'SYNTHETIC FIRST LIVE — '+TOPIC,'research_question':QUESTION,'requirements':REQUIREMENTS})
    path='/api/projects/'+project['id'];heading=str(uuid4())
    manuscript=post(path+'/manuscript/revisions',{'request_id':str(uuid4()),'base_revision_id':None,
        'document':{'schema_version':'1','blocks':[{'id':heading,'type':'heading','level':1,'text':TOPIC},
        {'id':str(uuid4()),'type':'paragraph','text':'План тестового раздела: эффективность и механизм → сравнение преимуществ и рисков → ограничения → осторожный вывод и пробелы. Все материалы ниже синтетические.'}]}})
    evidence=[]
    for index,(language,relation,text) in enumerate(SOURCES,1):
        source=post(path+'/sources',{'request_id':str(uuid4()),'metadata':{'title':f'SYNTHETIC FIRST LIVE fixture {index} — NOT A PUBLICATION','kind':'report','language':language}})
        item=post(path+'/evidence',{'request_id':str(uuid4()),'source_version_id':source['latest_version']['id'],
            'excerpt':text,'original_language':language,'selection':{'start':0,'end':len(text.encode('utf-16-le'))//2,'quote':text},
            'locator':{'kind':'section','label':f'Synthetic fixture {index}'},'material':'full_text_excerpt','rights_confirmed':True})
        evidence.append(item)
    statements=['Цифровые расчёты могут повышать операционную эффективность при определённых условиях.',
                'Скорость обработки сама по себе не устанавливает общеэкономическую эффективность денежного обращения.']
    claims=[{'id':str(uuid4()),'statement':statement,'section_id':heading,
        'evidence':[{'evidence_id':e['id'],'relation':(SOURCES[i][1] if statement==statements[0] else ['limits','supports','supports','limits'][i]),'rationale':'Синтетическое свидетельство; научная истинность не установлена.'} for i,e in enumerate(evidence)]} for statement in statements]
    plan=post(path+'/research-plan/revisions',{'request_id':str(uuid4()),'base_revision_id':None,'manuscript_revision_id':manuscript['id'],
        'document':{'schema_version':'1','claims':claims,'citations':[]}})
    task=TaskSpec(request_id=uuid4(),brief_revision_id=project['latest_brief']['id'],manuscript_revision_id=manuscript['id'],
        plan_revision_id=plan['id'],section_id=heading,claim_ids=[c['id'] for c in claims],title=TOPIC,instruction=INSTRUCTION,
        provider='openai',model='gpt-6.1-sol',reasoning_effort='high',max_output_tokens=8000)
    q=ModelJobs(engine);pid=UUID(project['id'])
    q.administer_budget(pid,BudgetDecision(request_id=uuid4(),acknowledged=True,
        evidence_ref='Owner first-live request: planned aggregate budget <= USD 50; final transmission consent pending',limit_units=50000000),'owner')
    preview=q.preview(pid,task);gateway=sol_gateway(task)
    payload=gateway.body(preview['input']['context'],task)
    alternate=SolResponses(profile=BillingProfile(True),effort='high').quote(preview['input']['context'],task)
    manifest={'schema_version':'first-live-v1','status':'blocked_awaiting_final_manifest_approval',
        'topic':TOPIC,'project_id':str(pid),'request_id':str(task.request_id),'model':task.model,'endpoint':ENDPOINT,
        'allowed_calls':{'writing':1,'semantic_review':0,'token_counting':0,'automatic_retries':0},
        'region':{'proposed':'global','account_region_confirmed':False},
        'data_policy':{'owner_approval':False,'store':False,'training_by_default':False,
            'notice':'OpenAI API defaults: no training; abuse retention up to 30 days and caching exceptions. store=false is not ZDR; account/region terms require confirmation.'},
        'budget':{'aggregate_limit_units':50000000,'writing_limit_units':15000000,'future_review_limit_units':15000000,
            'project_snapshot':q.budget(pid),'maximum_reserve_units':preview['input']['quote']['max_units'],
            'regional_alternative_reserve_units':alternate.max_units,'currency':'USD-micro',
            'provider_hard_cap_verified':False,'global_account_liabilities_verified':False},
        'preview':preview,'payload':payload,
        'context_hash':digest(preview['input']['context']),'payload_hash':digest(payload),
        'observed':{'provider_calls':0,'returned_model':None,'input_tokens':None,'output_tokens':None,
            'reasoning_tokens':None,'actual_cost_units':None,'uncertain_cost_units':None,'generated_text':None},
        'evaluations':{k:'not_run' for k in ('structural_validity','scientific_adequacy','writing_quality','billing_correctness')},
        'blockers':['final_owner_manifest_and_transmission_approval','application_key','network_access',
                    'account_entitlement','account_region_and_data_policy','provider_hard_spend_limit_and_existing_liabilities']}
    manifest['manifest_hash']=digest(manifest)
    return manifest

def verify(manifest):
    body=deepcopy(manifest);expected=body.pop('manifest_hash')
    if digest(body)!=expected:raise ValueError('manifest_changed')
    if digest(manifest['payload'])!=manifest['payload_hash']:raise ValueError('payload_changed')
    if manifest['allowed_calls']!={'writing':1,'semantic_review':0,'token_counting':0,'automatic_retries':0}:raise ValueError('call_count_changed')
