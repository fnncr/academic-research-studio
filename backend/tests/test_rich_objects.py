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


def test_merged_grid_preserves_ids_and_exports_spans():
    cells=[[{'id':str(uuid4()),'text':'Начало' if r==c==0 else '', 'row_span':2 if r==c==0 else 1,'col_span':2 if r==c==0 else 1,'covered_by':None} for c in range(2)] for r in range(2)]
    for r in range(2):
        for c in range(2):
            if r or c: cells[r][c]['covered_by']=cells[0][0]['id']
    table=node('merged_table',rows=[{'id':str(uuid4()),'cells':row} for row in cells])
    doc={'schema_version':'2','blocks':[table]}
    ManuscriptDocument.model_validate(doc)
    root=part(render(doc))
    assert root.xpath('//*[local-name()="gridSpan"]') and root.xpath('//*[local-name()="vMerge"]')
    cells[1][1]['text']='Не терять'
    with pytest.raises(ValidationError): ManuscriptDocument.model_validate(doc)


def png():
    import base64,struct,zlib
    def chunk(kind,data): return struct.pack('>I',len(data))+kind+data+struct.pack('>I',zlib.crc32(kind+data)&0xffffffff)
    return base64.b64encode(b'\x89PNG\r\n\x1a\n'+chunk(b'IHDR',struct.pack('>IIBBBBB',2,2,8,2,0,0,0))+chunk(b'IDAT',zlib.compress(b'\0'+b'\xff\0\0'*2+b'\0'+b'\0\xff\0'*2))+chunk(b'IEND',b'')).decode()


def test_embedded_png_and_rejection_of_bad_data():
    doc={'schema_version':'2','blocks':[node('image',png_base64=png(),text='Синтетический рисунок',alt='Красный и зелёный',width_cm=4)]}
    ManuscriptDocument.model_validate(doc)
    output=render(doc)
    assert part(output).xpath('//*[local-name()="drawing"]')
    with ZipFile(BytesIO(output)) as archive: assert any(n.startswith('word/media/') for n in archive.namelist())
    doc['blocks'][0]['png_base64']='https://example.com/x.svg'
    with pytest.raises(ValidationError): ManuscriptDocument.model_validate(doc)


@pytest.mark.parametrize('damage',['crc','trailing','oversized','bad_zlib'])
def test_png_rejects_corruption_and_bombs(damage):
    import base64,struct,zlib
    from app.png_images import read_png
    data=base64.b64decode(png())
    if damage=='crc': data=data[:-1]+bytes([data[-1]^1])
    elif damage=='trailing': data+=b'extra'
    elif damage=='oversized': data=b'x'*(512*1024+1)
    else:
        def chunk(kind,payload):return struct.pack('>I',len(payload))+kind+payload+struct.pack('>I',zlib.crc32(kind+payload)&0xffffffff)
        data=data[:33]+chunk(b'IDAT',zlib.compress(b'x'*100000))+chunk(b'IEND',b'')
    with pytest.raises(ValueError):read_png(base64.b64encode(data).decode())


def test_mixed_v2_history_restore_and_caption_citation(export_work):
    client,path,body,old,_,old_plan=export_work
    doc=deepcopy(old['document']);doc['schema_version']='2'
    image=node('image',png_base64=png(),text='А🧪Б. Точная цитата.',alt='Синтетическая иллюстрация',width_cm=4)
    note=node('footnote',text='Пояснение автора',anchor={'block_id':image['id'],'start':1,'end':3,'quote':'🧪'})
    doc['blocks'] += [node('formula',text='α + β = γ'),image,note]
    saved=save(client,path.rsplit('/',1)[1],doc,old['id'])
    assert saved.status_code==201,saved.text
    saved=saved.json()
    request={'request_id':str(uuid4()),'base_revision_id':old_plan['id'],'manuscript_revision_id':saved['id'],'document':deepcopy(old_plan['document'])}
    request['document']['citations'][0]['block_id']=image['id']
    request['document']['citations'].append({'id':str(uuid4()),'claim_id':request['document']['claims'][0]['id'],'evidence_id':request['document']['citations'][0]['evidence_id'],'block_id':note['id'],'kind':'paraphrase','selection':{'start':0,'end':5,'quote':note['text'][:5]}})
    new_plan=client.post(path+'/research-plan/revisions',json=request).json()
    result,_=download(client,path,{**body,'manuscript_revision_id':saved['id'],'plan_revision_id':new_plan['id']})
    assert part(result.content).xpath('//*[local-name()="drawing"]')
    assert part(result.content).xpath('//*[local-name()="footnoteReference"]')
    assert part(result.content,'word/footnotes.xml').xpath('//*[local-name()="hyperlink"]')
    result2,_=download(client,path,{**body,'manuscript_revision_id':saved['id'],'plan_revision_id':new_plan['id']})
    assert result.content==result2.content
    restored=save(client,path.rsplit('/',1)[1],old['document'],saved['id'],restored=old['id'])
    assert restored.status_code==201 and restored.json()['document']==old['document']
    assert client.get(path+'/manuscript/revisions/'+saved['id']).json()['document']==saved['document']
