"""Manual evidence and versioned claims; no inferred scientific verification."""
from typing import Annotated, Literal
from uuid import UUID

from pydantic import Field, StringConstraints, model_validator

from app.source_schema import Strict

Text = Annotated[str, StringConstraints(strict=True, min_length=1, max_length=12000)]
Note = Annotated[str, StringConstraints(strict=True, max_length=2000)]
Label = Annotated[str, StringConstraints(strict=True, strip_whitespace=True, min_length=1, max_length=500)]
Offset = Annotated[int, Field(strict=True, ge=0, le=40000)]


def utf16_slice(text: str, start: int, end: int) -> str:
    encoded = text.encode('utf-16-le')
    if start >= end or end * 2 > len(encoded):
        raise ValueError('Invalid range')
    # Strict decoding also rejects boundaries inside a surrogate pair.
    return encoded[start * 2:end * 2].decode('utf-16-le')


class TextRange(Strict):
    start: Offset
    end: Offset
    quote: Text


class Locator(Strict):
    kind: Literal['page', 'section', 'paragraph']
    label: Label


class WriteEvidence(Strict):
    request_id: UUID
    source_version_id: UUID
    excerpt: Text
    original_language: Annotated[str, StringConstraints(strict=True, pattern=r'^(?:[a-z]{2,3})(?:-[A-Z]{2})?$')] = 'und'
    selection: TextRange
    locator: Locator
    material: Literal['abstract', 'full_text_excerpt']
    note: Note = ''
    rights_confirmed: Annotated[bool, Field(strict=True)]

    @model_validator(mode='after')
    def exact_quote(self):
        if not self.rights_confirmed:
            raise ValueError('Permission to store the excerpt is required')
        if utf16_slice(self.excerpt, self.selection.start, self.selection.end) != self.selection.quote:
            raise ValueError('Quote does not match the supplied excerpt')
        if not self.selection.quote.strip():
            raise ValueError('Empty quote')
        return self


class ClaimEvidence(Strict):
    evidence_id: UUID
    relation: Literal['supports', 'contradicts', 'limits']
    rationale: Note = ''


class Claim(Strict):
    id: UUID
    statement: Label
    section_id: UUID | None = None
    evidence: list[ClaimEvidence] = Field(default_factory=list, max_length=30)

    @model_validator(mode='after')
    def unique_evidence(self):
        if len({item.evidence_id for item in self.evidence}) != len(self.evidence):
            raise ValueError('Duplicate evidence in a claim')
        return self


class Citation(Strict):
    id: UUID
    claim_id: UUID
    evidence_id: UUID
    block_id: UUID
    selection: TextRange
    kind: Literal['quotation', 'paraphrase']


class PlanDocument(Strict):
    schema_version: Literal['1']
    claims: list[Claim] = Field(default_factory=list, max_length=100)
    citations: list[Citation] = Field(default_factory=list, max_length=200)

    @model_validator(mode='after')
    def links(self):
        ids = [item.id for item in [*self.claims, *self.citations]]
        if len(set(ids)) != len(ids):
            raise ValueError('Duplicate IDs')
        claims = {claim.id: claim for claim in self.claims}
        for citation in self.citations:
            claim = claims.get(citation.claim_id)
            if claim is None or citation.evidence_id not in {link.evidence_id for link in claim.evidence}:
                raise ValueError('Citation must reference evidence linked to its claim')
        return self


class SavePlan(Strict):
    request_id: UUID
    base_revision_id: UUID | None
    manuscript_revision_id: UUID
    document: PlanDocument
