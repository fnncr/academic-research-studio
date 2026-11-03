"""Real Word footnote part, using the same citation renderer as body text."""
from docx.opc.part import Part
from docx.opc.packuri import PackURI
from docx.oxml import OxmlElement
from docx.oxml.ns import nsmap, qn
from lxml import etree


def add_footnotes(doc, document, citations, add_text):
    notes=[b for b in document['blocks'] if b['type']=='footnote']
    if not notes: return
    root=OxmlElement('w:footnotes')
    for identifier, kind in [(-1,'separator'),(0,'continuationSeparator')]:
        note=etree.SubElement(root,qn('w:footnote'),{qn('w:id'):str(identifier),qn('w:type'):kind})
        p=etree.SubElement(note,qn('w:p')); r=etree.SubElement(p,qn('w:r')); etree.SubElement(r,qn('w:'+kind))
    from docx.text.paragraph import Paragraph
    for identifier,note in enumerate(notes,1):
        anchor=note['anchor']; citations.setdefault(anchor['block_id'],[]).append((anchor['end'],0,identifier))
        item=etree.SubElement(root,qn('w:footnote'),{qn('w:id'):str(identifier)})
        p=Paragraph(OxmlElement('w:p'),doc._body); item.append(p._p)
        p.paragraph_format.first_line_indent=0
        r=p.add_run(); r.font.superscript=True; r._r.append(OxmlElement('w:footnoteRef')); p.add_run(' ')
        add_text(p,note,citations)
    part=Part(PackURI('/word/footnotes.xml'),'application/vnd.openxmlformats-officedocument.wordprocessingml.footnotes+xml',etree.tostring(root,xml_declaration=True,encoding='UTF-8',standalone=True),doc.part.package)
    doc.part.relate_to(part,'http://schemas.openxmlformats.org/officeDocument/2006/relationships/footnotes')
