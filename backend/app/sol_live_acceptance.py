"""Owner-operated single synthetic request. Never run --execute without new permission."""
import argparse,json,os
from pathlib import Path
from uuid import UUID
from fastapi.testclient import TestClient
from app.main import app
from app.scientific_evaluation import CASES,create_case,rubric
from app.model_jobs import ModelJobs
from app.database import project_engine
from app.model_contracts import TaskSpec,Consent
from app.manuscripts import digest

def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--manifest',type=Path,required=True)
    p.add_argument('--prepare',action='store_true')
    p.add_argument('--execute',action='store_true')
    p.add_argument('--collect',action='store_true')
    p.add_argument('--owner-approval',default='')
    a=p.parse_args()
    if sum((a.prepare,a.execute,a.collect))>1:p.error('Separate preparation, execution and collection')
    if not a.prepare and not a.execute and not a.collect:
        print('blocked: explicit preparation or separately authorized execution required');return
    if not os.environ.get('DATABASE_URL'):p.error('Use a disposable migrated DATABASE_URL')
    engine=project_engine(os.environ['DATABASE_URL']);q=ModelJobs(engine)
    try:
        if a.prepare:
            with TestClient(app) as client:
                path,raw=create_case(client,CASES[0]);manuscript=client.get(path+'/manuscript').json()
            task=TaskSpec.model_validate(raw|{'model':'gpt-6.1-sol','provider':'openai','max_output_tokens':2000,
                'section_id':manuscript['document']['blocks'][0]['id'],'reasoning_effort':'medium'})
            project=UUID(path.rsplit('/',1)[1]);preview=q.preview(project,task)
            a.manifest.write_text(json.dumps({'project_id':str(project),'preview':preview,'quality':rubric(CASES[0])},ensure_ascii=False,indent=2))
            print('Prepared only. Inspect complete manifest and configure project budget through owner API. No call made.')
        elif a.collect:
            record=json.loads(a.manifest.read_text());project=UUID(record['project_id'])
            task=TaskSpec.model_validate(record['preview']['input']['task'])
            result=q.by_request(project,task.request_id)
            record['job_result']={k:v for k,v in result.items() if k not in {'lease_token','dispatch_id'}}
            a.manifest.write_text(json.dumps(record,ensure_ascii=False,indent=2,default=str))
            print('Read-only result collected; quality rubric remains for expert review.')
        else:
            record=json.loads(a.manifest.read_text());preview=record['preview'];project=UUID(record['project_id'])
            if a.owner_approval!='SEND ONE SYNTHETIC WRITING REQUEST':p.error('Separate explicit owner approval required')
            task=TaskSpec.model_validate(preview['input']['task']);packet=preview['input']['context']
            expected={e[2] for e in CASES[0]['evidence']}
            if task.instruction!='Написать по-русски сопоставление позиций и ограничений.' or task.title!=CASES[0]['title']:p.error('Synthetic task required')
            if any(not v['metadata']['title'].startswith('SYNTHETIC economics fixture ') or any(v['metadata'].get(k) for k in ('authors','doi','isbn','url','publisher','container','year')) for v in packet['source_versions'].values()):p.error('Synthetic source metadata required')
            if task.kind!='writing' or packet['research_question']!=CASES[0]['question'] or \
                {e['content']['excerpt'] for e in packet['evidence'].values()}!=expected or \
                set(packet['manuscript']['texts'].values())!={CASES[0]['title']}:
                p.error('Only the exact synthetic case is allowed')
            if q.preview(project,task)!=preview:p.error('Context/configuration changed; prepare and approve again')
            # Persistent request UUID makes repeated CLI invocations enqueue replays.
            # This does not call worker or provider; the normally gated worker is authoritative.
            job=q.enqueue(project,task,Consent(approved=True,fingerprint=preview['fingerprint']),actor='owner')
            print('Enqueued once/recovered '+str(job['id'])+'. Read result via owner API; never retry under a new UUID.')
    finally:engine.dispose()

if __name__=='__main__':main()
