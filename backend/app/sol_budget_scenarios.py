"""Local synthetic 30 logical-page payload matrix; no tokenizer/API usage claims."""
from uuid import uuid4
from app.model_contracts import TaskSpec
from app.model_adapters.openai_responses import SolResponses
from app.grounded_writing import prompt_manifest
from app.model_context import SYSTEM_RULES
from app.manuscripts import digest
from app.budget_estimator import estimate

def matrix():
    heading=str(uuid4())
    task=TaskSpec(request_id=uuid4(),brief_revision_id=uuid4(),manuscript_revision_id=uuid4(),plan_revision_id=uuid4(),
        claim_ids=[uuid4()],section_id=heading,provider='openai',model='gpt-6.1-sol',title='Синтетический анализ',instruction='Сравнить RU/EN позиции.')
    # Thirty explicitly synthetic logical pages, not a promise about Word pagination.
    pages={str(uuid4()):('Синтетическая русская страница: анализ ограничений. '*20) for _ in range(30)}
    base={'writing_contract':prompt_manifest(),'system_hash':digest(SYSTEM_RULES),
          'manuscript':{'selected_section_id':heading,'texts':pages},
          'evidence':{'ru':{'original':'Синтетическое наблюдение'},'en':{'original':'Synthetic opposing observation'}}}
    result=[]
    for name,amount in [('full_document',30),('selected_section',5),('writing',5),('independent_review',5),('disputed_claim',1)]:
        packet={**base,'manuscript':{**base['manuscript'],'texts':dict(list(pages.items())[:amount])}}
        gateway=SolResponses();body=gateway.body(packet,task);quote=gateway.quote(packet,task)
        result.append({'scenario':name,'logical_pages':amount,'synthetic_only':True,**estimate(body,packet,quote)})
    return result

if __name__=='__main__':
    import json
    print(json.dumps(matrix(),ensure_ascii=False,indent=2))
