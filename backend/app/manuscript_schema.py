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


class CitationPlaceholder(Node):
    type: Literal['citation_placeholder']
    label: Label
    locator: Label = ''


Block = Annotated[Paragraph | Heading | Quote | ListBlock | Table | CitationPlaceholder,
                  Field(discriminator='type')]


class ManuscriptDocument(StrictModel):
    schema_version: Literal['1']
    blocks: list[Block] = Field(max_length=1000)

    @model_validator(mode='after')
    def safe_tree(self):
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
                    if key in {'text', 'label', 'locator'}:
                        characters += len(item)
                        if '\0' in item or any(0xD800 <= ord(char) <= 0xDFFF for char in item):
                            raise ValueError('Invalid Unicode text')
                    if isinstance(item, (dict, list)):
                        visit(item)
            elif isinstance(value, list):
                for item in value:
                    visit(item)

        visit(self.model_dump())
        if len(ids) > 2000 or characters > 250000:
            raise ValueError('Document exceeds node or text limit')
        return self


class SaveManuscript(StrictModel):
    base_revision_id: UUID | None
    request_id: UUID
    document: ManuscriptDocument
    restored_from_id: UUID | None = None
