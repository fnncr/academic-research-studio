"""Deterministic OOXML generation from checked, immutable inputs (no I/O/network)."""
from datetime import datetime, timezone
from io import BytesIO
import json
from zipfile import ZipFile, ZipInfo, ZIP_DEFLATED

from docx import Document
from docx.enum.table import WD_TABLE_ALIGNMENT, WD_CELL_VERTICAL_ALIGNMENT
from docx.enum.text import WD_ALIGN_PARAGRAPH
from docx.oxml import OxmlElement
from docx.oxml.ns import qn
from docx.shared import Cm, Pt, RGBColor
from lxml import etree

from app.evidence import text_nodes


def element(tag, **attributes):
    node = OxmlElement(tag)
    for key, value in attributes.items(): node.set(qn('w:' + key), str(value))
    return node


def field(paragraph, instruction, fallback=''):
    paragraph.add_run()._r.append(element('w:fldChar', fldCharType='begin', dirty='true'))
    code = element('w:instrText'); code.text = instruction
    code.set(qn('xml:space'), 'preserve')
    paragraph.add_run()._r.append(code)
    paragraph.add_run()._r.append(element('w:fldChar', fldCharType='separate'))
    # python-docx emits real w:br elements for multi-line cached TOC text.
    paragraph.add_run(fallback)
    paragraph.add_run()._r.append(element('w:fldChar', fldCharType='end'))


def font_style(style, profile):
    style.font.name = profile.font
    style.font.size = Pt(profile.font_size)
    style.font.color.rgb = RGBColor(0, 0, 0)
    rfonts = style.element.get_or_add_rPr().rFonts
    for attr in ('ascii', 'hAnsi', 'eastAsia', 'cs'):
        rfonts.set(qn('w:' + attr), profile.font)
    for attr in ('asciiTheme', 'hAnsiTheme', 'eastAsiaTheme', 'cstheme'):
        rfonts.attrib.pop(qn('w:' + attr), None)


def bibliography(metadata):
    # Deliberately small, documented numeric style. No fabricated missing fields.
    parts = [', '.join(metadata['authors']), metadata['title'], str(metadata['year'])]
    parts.extend(metadata[key] for key in ('container', 'publisher') if metadata.get(key))
    if metadata.get('doi'): parts.append('DOI: ' + metadata['doi'])
    if metadata.get('isbn'): parts.append('ISBN: ' + metadata['isbn'])
    if metadata.get('url'): parts.append(metadata['url'])
    return '. '.join(parts) + '.'


class ObjectCounter:
    """Independent counters ready for future typed table/figure captions."""
    def __init__(self): self.counts = {}
    def next(self, kind):
        self.counts[kind] = self.counts.get(kind, 0) + 1
        return self.counts[kind]


def citation_data(document, plan, evidence):
    order = {identifier: index for index, identifier in enumerate(text_nodes(document))}
    citations = sorted((plan or {}).get('citations', []), key=lambda c: (order.get(c['block_id'], -1), c['selection']['end'], c['id']))
    bibliography_ids = []
    by_node = {}
    for citation in citations:
        version_id = str(evidence[citation['evidence_id']].source_version_id)
        if version_id not in bibliography_ids: bibliography_ids.append(version_id)
        number = bibliography_ids.index(version_id) + 1
        locator = evidence[citation['evidence_id']].content['locator']
        label = {'page': 'с.', 'section': 'разд.', 'paragraph': 'абз.'}[locator['kind']]
        marker = f'[{number}, {label} {locator["label"]}]'
        by_node.setdefault(citation['block_id'], []).append((citation['selection']['end'], number, marker))
    return bibliography_ids, by_node


def add_text(paragraph, node, citations, math=False):
    text = node['text']; marks = node.get('marks', [])
    def run(value):
        if math:
            formula = OxmlElement('m:oMath'); r = OxmlElement('m:r'); text_node = OxmlElement('m:t'); text_node.text = value
            text_node.set(qn('xml:space'), 'preserve'); r.append(text_node); formula.append(r); paragraph._p.append(formula)
            return
        item = paragraph.add_run(value)
        item.bold = 'bold' in marks if marks else None
        item.italic = 'italic' in marks if marks else None
    previous = 0
    encoded = text.encode('utf-16-le')
    for end, number, label in citations.get(node['id'], []):
        index = len(encoded[:end * 2].decode('utf-16-le'))
        run(text[previous:index]); previous = index
        link = element('w:hyperlink', anchor=f'source_{number}')
        r = element('w:r'); t = element('w:t'); t.text = label; r.append(t); link.append(r)
        paragraph._p.append(link)
    run(text[previous:])


def numbering(document, ordered):
    root = document.part.numbering_part.element
    abstract_id = max([int(n.get(qn('w:abstractNumId'))) for n in root.findall(qn('w:abstractNum'))] + [-1]) + 1
    num_id = max([int(n.get(qn('w:numId'))) for n in root.findall(qn('w:num'))] + [0]) + 1
    abstract = element('w:abstractNum', abstractNumId=abstract_id)
    abstract.append(element('w:multiLevelType', val='singleLevel'))
    level = element('w:lvl', ilvl=0)
    for tag, value in [('w:start', 1), ('w:numFmt', 'decimal' if ordered else 'bullet'), ('w:lvlText', '%1.' if ordered else '•'), ('w:lvlJc', 'left')]:
        level.append(element(tag, val=value))
    abstract.append(level)
    first_num = root.find(qn('w:num'))
    if first_num is not None:
        root.insert(root.index(first_num), abstract)
    else:
        root.append(abstract)
    num = element('w:num', numId=num_id); num.append(element('w:abstractNumId', val=abstract_id))
    override = element('w:lvlOverride', ilvl=0); override.append(element('w:startOverride', val=1)); num.append(override); root.append(num)
    return num_id


def add_manifest(parts, manifest):
    ns = 'http://schemas.openxmlformats.org/officeDocument/2006/custom-properties'
    vt = 'http://schemas.openxmlformats.org/officeDocument/2006/docPropsVTypes'
    root = etree.Element('{'+ns+'}Properties', nsmap={None: ns, 'vt': vt})
    prop = etree.SubElement(root, '{'+ns+'}property', fmtid='{D5CDD505-2E9C-101B-9397-08002B2CF9AE}', pid='2', name='ResearchExportManifest')
    etree.SubElement(prop, '{'+vt+'}lpwstr').text = json.dumps(manifest, ensure_ascii=False, sort_keys=True, separators=(',', ':'))
    parts['docProps/custom.xml'] = etree.tostring(root, xml_declaration=True, encoding='UTF-8', standalone=True)
    content = etree.fromstring(parts['[Content_Types].xml'])
    etree.SubElement(content, '{http://schemas.openxmlformats.org/package/2006/content-types}Override', PartName='/docProps/custom.xml', ContentType='application/vnd.openxmlformats-officedocument.custom-properties+xml')
    parts['[Content_Types].xml'] = etree.tostring(content, xml_declaration=True, encoding='UTF-8', standalone=True)
    rels = etree.fromstring(parts['_rels/.rels'])
    etree.SubElement(rels, '{http://schemas.openxmlformats.org/package/2006/relationships}Relationship', Id='researchManifest', Type='http://schemas.openxmlformats.org/officeDocument/2006/relationships/custom-properties', Target='docProps/custom.xml')
    parts['_rels/.rels'] = etree.tostring(rels, xml_declaration=True, encoding='UTF-8', standalone=True)


def generate_docx(document, plan, evidence, sources, request, report):
    doc = Document(); profile = request.profile
    section = doc.sections[0]; section.page_width = Cm(21); section.page_height = Cm(29.7)
    for name in ('top', 'bottom', 'left', 'right'):
        setattr(section, name + '_margin', Cm(getattr(profile, 'margin_' + name + '_cm')))
    section.header_distance = Cm(0.75); section.footer_distance = Cm(0.75)
    normal = doc.styles['Normal']; font_style(normal, profile)
    normal.paragraph_format.line_spacing = profile.line_spacing
    normal.paragraph_format.first_line_indent = Cm(profile.first_line_cm)
    normal.paragraph_format.space_after = Pt(profile.paragraph_after_pt)
    normal.paragraph_format.space_before = Pt(0)
    normal.paragraph_format.widow_control = True
    normal.paragraph_format.alignment = WD_ALIGN_PARAGRAPH.JUSTIFY if profile.alignment == 'justify' else WD_ALIGN_PARAGRAPH.LEFT
    for level in range(1, 7):
        style = doc.styles[f'Heading {level}']; font_style(style, profile); style.font.bold = True
        style.paragraph_format.first_line_indent = Cm(0); style.paragraph_format.keep_with_next = True
        style.paragraph_format.alignment = WD_ALIGN_PARAGRAPH.LEFT; style.paragraph_format.space_before = Pt(12); style.paragraph_format.space_after = Pt(6)
    for name in ('Quote', 'Header', 'Footer', 'Title'):
        font_style(doc.styles[name], profile)
        doc.styles[name].paragraph_format.first_line_indent = Cm(0)
    if profile.header:
        header = section.header.paragraphs[0]; header.text = profile.header; header.alignment = WD_ALIGN_PARAGRAPH.CENTER
    footer = section.footer.paragraphs[0]; footer.alignment = WD_ALIGN_PARAGRAPH.CENTER
    if profile.footer: footer.add_run(profile.footer + ('\n' if profile.page_numbers else ''))
    if profile.page_numbers: field(footer, ' PAGE ', '1')
    if request.title_page.enabled:
        title = request.title_page
        for value in (title.university, title.department, title.discipline, '', title.topic, '',
                      'Автор: ' + title.author, 'Группа: ' + title.group, 'Преподаватель: ' + title.teacher, '',
                      title.city + ' — ' + str(title.year)):
            p = doc.add_paragraph(value); p.alignment = WD_ALIGN_PARAGRAPH.CENTER; p.paragraph_format.first_line_indent = Cm(0)
        doc.add_page_break()
    if profile.toc:
        doc.add_paragraph('Оглавление', style='Title')
        p = doc.add_paragraph(); p.paragraph_format.first_line_indent = Cm(0)
        headings = '\n'.join(b['text'] for b in document['blocks'] if b['type'] == 'heading')
        field(p, ' TOC \\o "1-6" \\h \\z \\u ', headings or 'Обновите поле оглавления в Word.')
        doc.add_page_break()
    bibliography_ids, citations = citation_data(document, plan, evidence)
    counter = ObjectCounter()
    for block in document['blocks']:
        kind = block['type']
        if kind in ('heading', 'paragraph', 'quote'):
            p = doc.add_paragraph(style=f'Heading {block["level"]}' if kind == 'heading' else 'Quote' if kind == 'quote' else 'Normal')
            if kind == 'quote':
                p.paragraph_format.left_indent = Cm(1); p.paragraph_format.right_indent = Cm(1)
            add_text(p, block, citations)
        elif kind == 'formula':
            p = doc.add_paragraph(); p.alignment = WD_ALIGN_PARAGRAPH.CENTER; p.paragraph_format.first_line_indent = Cm(0)
            add_text(p, block, citations, math=True)
        elif kind == 'list':
            num_id = numbering(doc, block['ordered'])
            for item in block['items']:
                p = doc.add_paragraph(); p.paragraph_format.first_line_indent = Cm(-0.5); p.paragraph_format.left_indent = Cm(0.75)
                num = element('w:numPr'); num.append(element('w:ilvl', val=0)); num.append(element('w:numId', val=num_id)); p._p.get_or_add_pPr().append(num)
                add_text(p, item, citations)
        elif kind == 'table':
            number = counter.next('table')
            if profile.number_tables:
                p = doc.add_paragraph(f'Таблица {number}'); p.paragraph_format.first_line_indent = Cm(0); p.paragraph_format.keep_with_next = True
            rows = block['rows']; columns = len(rows[0]['cells'])
            table = doc.add_table(rows=len(rows), cols=columns); table.style = 'Table Grid'; table.alignment = WD_TABLE_ALIGNMENT.CENTER; table.autofit = False
            width = Cm((21 - profile.margin_left_cm - profile.margin_right_cm) / columns)
            for column in table.columns: column.width = width
            for row_index, row in enumerate(rows):
                for col_index, cell in enumerate(row['cells']):
                    target = table.cell(row_index, col_index); target.width = width; target.vertical_alignment = WD_CELL_VERTICAL_ALIGNMENT.CENTER
                    p = target.paragraphs[0]; p.paragraph_format.first_line_indent = Cm(0); p.alignment = WD_ALIGN_PARAGRAPH.LEFT
                    add_text(p, cell, citations)
            # No guessed header row or caption text. Table Grid supplies all borders.
    if bibliography_ids:
        doc.add_heading('Список использованных источников', level=1)
        for index, identifier in enumerate(bibliography_ids, 1):
            p = doc.add_paragraph(); p.paragraph_format.first_line_indent = Cm(0)
            p._p.append(element('w:bookmarkStart', id=index, name=f'source_{index}'))
            p.add_run(f'{index}. ' + bibliography(sources[identifier].metadata_json))
            p._p.append(element('w:bookmarkEnd', id=index))
    core = doc.core_properties; core.author = ''; core.last_modified_by = ''; core.title = request.title_page.topic if request.title_page.enabled else ''
    core.subject = ''; core.comments = ''; core.keywords = ''; core.revision = 1
    core.created = core.modified = datetime(2000, 1, 1, tzinfo=timezone.utc)
    core.identifier = report['preflight_token']
    settings = doc.settings.element; settings.append(element('w:updateFields', val='true'))
    buf = BytesIO(); doc.save(buf)
    with ZipFile(BytesIO(buf.getvalue())) as archive:
        parts = {name: archive.read(name) for name in archive.namelist()}
    add_manifest(parts, {**report['manifest'], 'preflight_token': report['preflight_token'],
                         'diagnostics': {key: report[key] for key in ('errors', 'warnings', 'info')}})
    result = BytesIO()
    with ZipFile(result, 'w', compression=ZIP_DEFLATED, compresslevel=9) as archive:
        for name in sorted(parts):
            info = ZipInfo(name, date_time=(2000, 1, 1, 0, 0, 0)); info.compress_type = ZIP_DEFLATED; info.external_attr = 0o600 << 16
            archive.writestr(info, parts[name], compresslevel=9)
    return result.getvalue()
