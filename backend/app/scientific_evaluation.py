"""Synthetic evaluation fixtures and local-only acceptance preparation. No gateway calls."""
import argparse
import json
import os
from pathlib import Path
from uuid import uuid4

CASES = [
    {'id':'economics','title':'Экономическая теория','question':'Как соотносятся спрос и издержки в объяснении изменения цены?',
     'claim':'Изменение цены может иметь несколько объяснений.',
     'evidence': [('ru','supports','В синтетическом случае A цена выросла одновременно со спросом.'),
                  ('en','contradicts','Synthetic case B attributes the price increase to higher costs, with unchanged demand.'),
                  ('ru','limits','Синтетические наблюдения не позволяют отделить причинность от совпадения.')],
     'expert_checks':['Сопоставлены спрос и издержки','Нет универсальной причинности']},
    {'id':'management','title':'Менеджмент','question':'Каковы границы централизованного и автономного управления?',
     'claim':'Пригодность управления зависит от условий организации.',
     'evidence':[('ru','supports','В синтетическом случае централизованное решение улучшило согласование действий.'),
                 ('en','contradicts','In a synthetic comparison, team autonomy supported adaptation; central approval delayed decisions.'),
                 ('ru','limits','Синтетические организации различаются по размеру; перенос вывода не обоснован.')],
     'expert_checks':['Сравнены оба подхода','Названы условия применимости']},
    {'id':'fintech','title':'Финансовые технологии','question':'Какие преимущества и риски имеет цифровой расчётный механизм?',
     'claim':'Преимущества технологии следует оценивать вместе с рисками.',
     'evidence':[('ru','supports','В синтетической системе цифровые расчёты уменьшили число ручных операций.'),
                 ('en','contradicts','The synthetic deployment introduced operational outages and privacy risks.'),
                 ('ru','limits','Синтетический пример не содержит оценки затрат или репрезентативной выборки.')],
     'expert_checks':['Сопоставлены выгоды и риски','Не выдуманы денежные эффекты']},
]


def create_case(client, case):
    def post(path, body):
        r=client.post(path,json=body)
        if r.status_code not in (200,201): raise RuntimeError('synthetic_fixture_creation_failed')
        return r.json()
    project=post('/api/projects', {'title':'SYNTHETIC — '+case['title'],
        'research_question':case['question'],'requirements':'Писать по-русски. Только синтетические Evidence. Сравнить позиции, факты и интерпретации, ограничения и пробелы; ничего не выдумывать.'})
    path='/api/projects/'+project['id']
    heading=str(uuid4())
    manuscript=post(path+'/manuscript/revisions', {'request_id':str(uuid4()),'base_revision_id':None,
        'document':{'schema_version':'1','blocks':[{'id':heading,'type':'heading','level':1,'text':case['title']}]}})
    links=[]
    for index,(language,relation,text) in enumerate(case['evidence']):
        source=post(path+'/sources',{'request_id':str(uuid4()),'metadata':{
            'title':f'SYNTHETIC {case["id"]} fixture {index+1}', 'kind':'report','language':language}})
        evidence=post(path+'/evidence',{'request_id':str(uuid4()),'source_version_id':source['latest_version']['id'],
            'excerpt':text,'original_language':language,
            'selection':{'start':0,'end':len(text.encode('utf-16-le'))//2,'quote':text},
            'locator':{'kind':'section','label':f'Synthetic fixture {index+1}'},
            'material':'full_text_excerpt','rights_confirmed':True})
        links.append({'evidence_id':evidence['id'],'relation':relation,'rationale':'Синтетическое оценочное свидетельство'})
    claim=str(uuid4())
    plan=post(path+'/research-plan/revisions', {'request_id':str(uuid4()),'base_revision_id':None,
        'manuscript_revision_id':manuscript['id'],'document':{'schema_version':'1','claims':[
            {'id':claim,'statement':case['claim'],'section_id':heading,'evidence':links}],'citations':[]}})
    task={'request_id':str(uuid4()),'brief_revision_id':project['latest_brief']['id'],
        'manuscript_revision_id':manuscript['id'],'plan_revision_id':plan['id'],
        'claim_ids':[claim],'title':case['title'],'instruction':'Написать по-русски сопоставление позиций и ограничений.',
        'provider':'mock','model':'mock-grounded-v1','max_output_tokens':8000}
    return path,task


def rubric(case):
    return {'case':case['id'],'structural_validity':'not_run',
            'scientific_adequacy':{'status':'requires_expert_review','checks':case['expert_checks']+[
                'Каждое внешнее утверждение опирается на Evidence','Нет вымышленных фактов',
                'Цитаты точны по смыслу и контексту','Противоречия сохранены']},
            'writing_quality':{'status':'requires_expert_review','checks':[
                'Академический стиль','Сопоставление позиций вместо коллажа','Полезность для дальнейшего исследования']}}


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output',type=Path,required=True)
    parser.add_argument('--prepare',action='store_true',help='Explicitly create synthetic records in a disposable DATABASE_URL')
    args=parser.parse_args()
    report={'model':'gpt-6.1-sol','live_status':'blocked','provider_calls':0,
            'estimated_cost_units':None,'maximum_reservation_units':None,'actual_cost_units':None,
            'blockers':['adapter_and_billing_review','owner_approval','account_and_network_access'],
            'cases':[rubric(case) for case in CASES]}
    if args.prepare:
        if not os.environ.get('DATABASE_URL'): parser.error('--prepare needs a disposable migrated DATABASE_URL')
        from fastapi.testclient import TestClient
        from app.main import app
        with TestClient(app) as client:
            for case,result in zip(CASES,report['cases']):
                path,task=create_case(client,case)
                result.update(project_path=path,prepared_mock_task=task,
                              desired_model='gpt-6.1-sol')
        # Never enqueue/count/send even when flags or keys happen to exist.
    args.output.write_text(json.dumps(report,ensure_ascii=False,indent=2)+'\n')

if __name__=='__main__': main()
