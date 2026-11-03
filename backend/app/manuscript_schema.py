"""Version 1 of the bounded manuscript tree. No HTML or inferred formatting."""
from typing import Annotated, Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, StringConstraints, model_validator

Text = Annotated[str, StringConstraints(strict=True, max_length=20000)]
Label = Annotated[str, StringConstraints(strict=True, max_length=500)]


class StrictModel(BaseModel):
    model_config = ConfigDict(extra='forbid')


class Node(StrictModel):
    id: UUID


class Paragraph(Node):
    type: Literal['paragraph']
    text: Text
    marks: list[Literal['bold', 'italic']] = Field(default_factory=list, max_length=2)
    origin: Literal['manual', 'docx_plain_text', 'pdf_plain_text'] = 'manual'
    page: Annotated[int, Field(strict=True, ge=1, le=200)] | None = None


class Heading(Node):
    type: Literal['heading']
    text: Text
    level: Annotated[int, Field(strict=True, ge=1, le=6)]


class Quote(Node):
    type: Literal['quote']
    text: Text


class ListBlock(Node):
    type: Literal['list']
    ordered: Annotated[bool, Field(strict=True)] = False
    items: list[Paragraph] = Field(min_length=1, max_length=200)


class Cell(Node):
    text: Text


class Row(Node):
    cells: list[Cell] = Field(min_length=1, max_length=20)


class Table(Node):
    type: Literal['table']
    rows: list[Row] = Field(min_length=1, max_length=100)

    @model_validator(mode='after')
    def rectangular(self):
        if len({len(row.cells) for row in self.rows}) != 1:
            raise ValueError('Table rows must have equal cell counts')
        return self


class Image(Node):
    type: Literal['image']
    png_base64: Annotated[str, StringConstraints(strict=True, max_length=700000)]
    text: Label = ''  # Caption is a normal, P4-addressable text node.
    alt: Label = ''
    width_cm: Annotated[float, Field(strict=True, ge=1, le=18)] = 12

    @model_validator(mode='after')
    def valid_png(self):
        from app.png_images import read_png
        read_png(self.png_base64)
        return self


class MergeCell(Cell):
    row_span: Annotated[int, Field(strict=True, ge=1, le=100)] = 1
    col_span: Annotated[int, Field(strict=True, ge=1, le=20)] = 1
    covered_by: UUID | None = None


class MergeRow(Node):
    cells: list[MergeCell] = Field(min_length=1, max_length=20)


class MergedTable(Node):
    type: Literal['merged_table']
    rows: list[MergeRow] = Field(min_length=1, max_length=100)

    @model_validator(mode='after')
    def topology(self):
        height = len(self.rows); width = len(self.rows[0].cells)
        if any(len(row.cells) != width for row in self.rows): raise ValueError('Ragged grid')
        owners = {}
        for r, row in enumerate(self.rows):
            for c, cell in enumerate(row.cells):
                if cell.covered_by is not None: continue
                if r + cell.row_span > height or c + cell.col_span > width: raise ValueError('Span outside grid')
                for rr in range(r, r + cell.row_span):
                    for cc in range(c, c + cell.col_span):
                        if (rr, cc) in owners: raise ValueError('Overlapping spans')
                        owners[(rr, cc)] = cell.id
        for r, row in enumerate(self.rows):
            for c, cell in enumerate(row.cells):
                if owners.get((r,c)) != (cell.covered_by or cell.id): raise ValueError('Invalid covered cell')
                if cell.covered_by and (cell.text or cell.row_span != 1 or cell.col_span != 1): raise ValueError('Covered content would be lost')
        return self


class FootnoteAnchor(StrictModel):
    block_id: UUID
    start: Annotated[int, Field(strict=True, ge=0, le=40000)]
    end: Annotated[int, Field(strict=True, ge=1, le=40000)]
    quote: Text


class Footnote(Node):
    type: Literal['footnote']
    text: Text
    anchor: FootnoteAnchor


class Formula(Node):
    type: Literal['formula']
    text: Text


class CitationPlaceholder(Node):
    type: Literal['citation_placeholder']
    label: Label
    locator: Label = ''


Block = Annotated[Paragraph | Heading | Quote | ListBlock | Table | CitationPlaceholder | Formula | Footnote | MergedTable | Image,
                  Field(discriminator='type')]


class ManuscriptDocument(StrictModel):
    schema_version: Literal['1', '2']
    blocks: list[Block] = Field(max_length=1000)

    @model_validator(mode='after')
    def safe_tree(self):
        if self.schema_version == '1' and any(b.type in ('formula', 'footnote', 'merged_table', 'image') for b in self.blocks):
            raise ValueError('New objects require schema 2')
        ids = set()
        characters = 0

        def visit(value):
            nonlocal characters
            if isinstance(value, dict):
                if 'id' in value:
                    if value['id'] in ids:
                        raise ValueError('Every node ID must be unique')
                    ids.add(value['id'])
                for key, item in value.items():
                    if key in {'text', 'label', 'locator', 'alt'}:
                        characters += len(item)
                        if '\0' in item or any(0xD800 <= ord(char) <= 0xDFFF for char in item):
                            raise ValueError('Invalid Unicode text')
                    if isinstance(item, (dict, list)):
                        visit(item)
            elif isinstance(value, list):
                for item in value:
                    visit(item)

        snapshot = self.model_dump(mode='json')
        visit(snapshot)
        from app.evidence_schema import utf16_slice
        targets = {}
        def collect(value):
            if isinstance(value, dict):
                if 'id' in value and 'text' in value: targets[value['id']] = value
                for child in value.values(): collect(child)
            elif isinstance(value, list):
                for child in value: collect(child)
        collect(snapshot)
        for block in self.blocks:
            if block.type == 'footnote':
                anchor = block.anchor
                target = targets.get(str(anchor.block_id))
                if not target or target.get('type') == 'footnote' or utf16_slice(target['text'], anchor.start, anchor.end) != anchor.quote:
                    raise ValueError('Footnote anchor is stale or invalid')
        if sum(len(b.png_base64) for b in self.blocks if b.type == 'image') > 1500000:
            raise ValueError('Total image payload exceeds manuscript budget')
        if len(ids) > 2000 or characters > 250000:
            raise ValueError('Document exceeds node or text limit')
        return self


class SaveManuscript(StrictModel):
    base_revision_id: UUID | None
    request_id: UUID
    document: ManuscriptDocument
    restored_from_id: UUID | None = None
