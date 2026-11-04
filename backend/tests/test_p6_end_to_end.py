"""Complete saved-source -> rich manuscript -> P6 -> DOCX -> v1 restore.

All scientific material is synthetic. Only local mock generation is executed.
"""
from copy import deepcopy
from io import BytesIO
from pathlib import Path
from uuid import UUID, uuid4
from zipfile import ZipFile
import base64
import os

from fastapi.testclient import TestClient
from app.main import app
from app.database import project_engine
from app.manuscripts import digest
from app.model_jobs import ModelJobs
from app.model_worker import run_once
from app.model_gateway import MockGateway
from test_projects import storage
from test_exports import export_work, download, xml
from test_manuscripts import save
from test_rich_objects import node, png
from test_sources import write
from test_model_api import TOKEN, decision


def test_complete_p6_api_rich_docx_reopen_restore(export_work, storage, monkeypatch):
    client,path,export_body,old,source,old_plan=export_work
    monkeypatch.setenv('MODEL_OWNER_TOKEN',TOKEN)
    for name in ('ARS_OPENAI_API_KEY','ARS_OPENAI_APPROVAL','ARS_OPENAI_PRICE_CONFIRMED'):
        monkeypatch.delenv(name,raising=False)
    client.headers['Authorization']='Bearer '+TOKEN
    project=path.rsplit('/',1)[1]; route=path+'/model-jobs'
    document=deepcopy(old['document']);document['schema_version']='2'
    image=node('image',png_base64=png(),text='А🧪Б — рисунок',alt='Синтетический рисунок',width_cm=4)
    note=node('footnote',text='А🧪Б — примечание',anchor={'block_id':image['id'],'start':1,'end':3,'quote':'🧪'})
    origin={'id':str(uuid4()),'text':'А🧪Б','row_span':2,'col_span':2,'covered_by':None}
    covered=lambda:{'id':str(uuid4()),'text':'','row_span':1,'col_span':1,'covered_by':origin['id']}
    table=node('merged_table',rows=[{'id':str(uuid4()),'cells':[origin,covered()]},{'id':str(uuid4()),'cells':[covered(),covered()]}])
    formula=node('formula',text='α + β = γ; 🧪')
    document['blocks'] += [image,note,table,formula]
    rich=save(client,project,document,old['id']);assert rich.status_code==201,rich.text
    rich=rich.json(); plan=deepcopy(old_plan['document'])
    for target in (image,note,origin):
        plan['citations'].append({**plan['citations'][0],'id':str(uuid4()),'block_id':target['id'],
            'selection':{'start':1,'end':3,'quote':'🧪'}})
    response=client.post(path+'/research-plan/revisions',json={'request_id':str(uuid4()),'base_revision_id':old_plan['id'],
        'manuscript_revision_id':rich['id'],'document':plan})
    assert response.status_code==201,response.text
    saved_plan=response.json()
    spec={'request_id':str(uuid4()),'brief_revision_id':client.get(path).json()['latest_brief']['id'],
        'manuscript_revision_id':rich['id'],'plan_revision_id':saved_plan['id'],
        'claim_ids':[plan['claims'][0]['id']],'title':'Синтетический научный раздел',
        'instruction':'Сохранить доказательства и противоречия.','provider':'mock','model':'mock-grounded-v1','max_output_tokens':8000}
    assert client.put(route+'/budget',json=decision(limit_units=100000)).status_code==200
    preview=client.post(route+'/preview',json=spec);assert preview.status_code==200
    assert 'png_base64' not in str(preview.json()['input']['context'])
    body={'task':spec,'consent':{'fingerprint':preview.json()['fingerprint'],'approved':True}}
    job=client.post(route,json=body);assert job.status_code==202
    job=job.json()
    class MetadataChangesDuringCall(MockGateway):
        updated = None
        def generate(self, packet, task, dispatch_id):
            # Dispatch has committed; this independent API transaction must not
            # deadlock and must not retarget the consented source version.
            self.updated = write(client,path+'/sources/'+source['id']+'/versions',
                {**source['latest_version']['metadata'],'title':'Более новая версия — не цитировать автоматически'},base=source['latest_version']['id'])
            assert self.updated.status_code==201,self.updated.text
            return super().generate(packet,task,dispatch_id)
    gateway=MetadataChangesDuringCall()
    engine=project_engine(storage[1]);queue=ModelJobs(engine)
    try:
        # Simulated lost enqueue response: reopen client and recover via UUID, no second job.
        with TestClient(app) as reopened:
            reopened.headers['Authorization']='Bearer '+TOKEN
            assert reopened.get(route+'/by-request/'+spec['request_id']).json()['id']==job['id']
            replay=reopened.post(route,json=body);assert replay.status_code==200 and replay.json()['id']==job['id']
            generated=run_once(queue,gateway);assert generated['state']=='succeeded'
            updated=gateway.updated; assert updated is not None
            assert generated['result']['verification']=='unverified'
            review_spec={**spec,'request_id':str(uuid4()),'kind':'semantic_review','review_job_id':job['id'],
                'review_result_hash':digest(generated['result'])}
            reviewed_preview=reopened.post(route+'/preview',json=review_spec);assert reviewed_preview.status_code==200
            review_job=reopened.post(route,json={'task':review_spec,'consent':{'fingerprint':reviewed_preview.json()['fingerprint'],'approved':True}})
            assert review_job.status_code==202
            reviewed=run_once(queue);assert reviewed['state']=='succeeded' and reviewed['result']['status']=='uncertain'
            assert reopened.get(route+'/budget').json()['spent_units']==200
            accept={'request_id':str(uuid4()),'manuscript_revision_id':rich['id'],'plan_revision_id':saved_plan['id'],
                'result_hash':digest(generated['result']),'review_acknowledged':True}
            accepted=reopened.post(route+'/'+job['id']+'/accept',json=accept);assert accepted.status_code==200,accepted.text
            receipt=accepted.json()
            result=reopened.get(path+'/manuscript').json()
            assert result['document']['blocks'][:len(rich['document']['blocks'])]==rich['document']['blocks']
            new_plan=reopened.get(path+'/research-plan').json()
            assert new_plan['document']['citations'][:len(plan['citations'])]==plan['citations']
            later=save(reopened,project,result['document'],result['id']).json()
            assert reopened.post(route+'/'+job['id']+'/accept',json=accept).json()==receipt
            assert reopened.get(path+'/manuscript').json()['id']==later['id']
            # Export exact accepted historical versions, independent of current heads.
            settings={**export_body,'manuscript_revision_id':receipt['manuscript_revision_id'],'plan_revision_id':receipt['plan_revision_id']}
            first,report=download(reopened,path,settings);second,_=download(reopened,path,settings)
            assert first.content==second.content
            root=xml(first.content)
            from test_exports import NS
            assert root.xpath('//w:p[w:r/w:instrText[contains(., "TOC")]]/w:pPr/w:jc/@w:val',namespaces=NS)==['left']
            for tag in ('drawing','oMath','gridSpan','vMerge','footnoteReference'):
                assert root.xpath(f'//*[local-name()="{tag}"]')
            assert xml(first.content,'word/footnotes.xml').xpath('//*[local-name()="hyperlink"]')
            assert 'PAGE' in ''.join(xml(first.content,'word/footer1.xml').itertext())
            assert source['latest_version']['metadata']['title'] in ''.join(root.itertext())
            assert updated.json()['metadata']['title'] not in ''.join(root.itertext())
            with ZipFile(BytesIO(first.content)) as archive:
                assert base64.b64decode(image['png_base64']) in [archive.read(n) for n in archive.namelist() if n.startswith('word/media/')]
            artifact=os.environ.get('P6_VALIDATION_ARTIFACT_DIR')
            if artifact:
                directory=Path(artifact);directory.mkdir(parents=True,exist_ok=True)
                (directory/'p6-acceptance.docx').write_bytes(first.content)
            restored=save(reopened,project,old['document'],later['id'],restored=old['id'])
            assert restored.status_code==201 and restored.json()['document']==old['document']
            assert reopened.get(path+'/manuscript/revisions/'+result['id']).json()==result
            again,_=download(reopened,path,settings);assert again.content==first.content
    finally:engine.dispose()
