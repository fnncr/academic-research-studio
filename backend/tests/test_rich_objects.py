from copy import deepcopy
from io import BytesIO
from uuid import uuid4
from zipfile import ZipFile
from lxml import etree
import pytest
from pydantic import ValidationError
from app.manuscript_schema import ManuscriptDocument
from app.docx_export import generate_docx
from app.export_schema import ExportRequest
from test_projects import storage
from test_exports import export_work, download, checked
from test_manuscripts import save


def node(kind, **fields): return {'id': str(uuid4()), 'type': kind, **fields}


def render(doc):
    request = ExportRequest(manuscript_revision_id=uuid4(), plan_revision_id=None, without_plan=True,
        profile={'name':'Test','toc':False}, title_page={'enabled':False}, citation_style='numeric-v1')
    return generate_docx(doc, None, {}, {}, request, {'manifest':{},'preflight_token':'a'*64,'errors':[],'warnings':[],'info':[]})


def part(output, name='word/document.xml'):
    with ZipFile(BytesIO(output)) as archive: return etree.fromstring(archive.read(name))


def test_formula_schema_and_office_math():
    doc={'schema_version':'2','blocks':[node('formula',text='E = mc²; α + β')]}
    ManuscriptDocument.model_validate(doc)
    root=part(render(doc))
    assert root.xpath('//*[local-name()="oMath"]')
    assert root.xpath('//*[local-name()="oMath"]//*[local-name()="t"]/text()') == ['E = mc²; α + β']
    with pytest.raises(ValidationError): ManuscriptDocument.model_validate({**doc,'schema_version':'1'})


def test_formula_history_and_citation(export_work):
    client,path,body,old,source,plan=export_work
    doc=deepcopy(old['document']); doc['schema_version']='2'; doc['blocks'][1]=node('formula',text='А🧪Б. Точная цитата.')
    saved=save(client,path.rsplit('/',1)[1],doc,old['id']).json()
    request={'request_id':str(uuid4()),'base_revision_id':plan['id'],'manuscript_revision_id':saved['id'],'document':deepcopy(plan['document'])}
    request['document']['citations'][0]['block_id']=doc['blocks'][1]['id']
    new_plan=client.post(path+'/research-plan/revisions',json=request)
    assert new_plan.status_code==201,new_plan.text
    response,_=download(client,path,{**body,'manuscript_revision_id':saved['id'],'plan_revision_id':new_plan.json()['id']})
    assert part(response.content).xpath('//*[local-name()="oMath"]')
    assert client.get(path+'/manuscript/revisions/'+old['id']).json()['document']==old['document']


def test_native_footnote_and_stale_anchor():
    p=node('paragraph',text='А🧪Б')
    note=node('footnote',text='Примечание автора',anchor={'block_id':p['id'],'start':1,'end':3,'quote':'🧪'})
    doc={'schema_version':'2','blocks':[p,note]}
    ManuscriptDocument.model_validate(doc)
    output=render(doc)
    assert part(output).xpath('//*[local-name()="footnoteReference"]')
    assert 'Примечание автора' in ''.join(part(output,'word/footnotes.xml').itertext())
    p['text']='Изменённый текст'
    with pytest.raises(ValidationError): ManuscriptDocument.model_validate(doc)
