"""P6 wire contracts: data only, no model-authored document patches or tools."""
from typing import Annotated, Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, StringConstraints, field_validator, model_validator

Text = Annotated[str, StringConstraints(strict=True, min_length=1, max_length=12000)]
Short = Annotated[str, StringConstraints(strict=True, min_length=1, max_length=500)]
Hash = Annotated[str, StringConstraints(strict=True, pattern=r'^[0-9a-f]{64}$')]
Count = Annotated[int, Field(strict=True, ge=0, le=1000000)]
Units = Annotated[int, Field(strict=True, ge=0, le=10**12)]


class Contract(BaseModel):
    model_config = ConfigDict(extra='forbid', frozen=True)

    @model_validator(mode='after')
    def valid_unicode(self):
        def visit(value):
            if isinstance(value, str) and ('\0' in value or any(0xD800 <= ord(c) <= 0xDFFF for c in value)):
                raise ValueError('Invalid Unicode')
            if isinstance(value, dict):
                for child in value.values(): visit(child)
            if isinstance(value, list):
                for child in value: visit(child)
        visit(self.model_dump(mode='json'))
        return self


class TaskSpec(Contract):
    request_id: UUID
    brief_revision_id: UUID
    manuscript_revision_id: UUID
    plan_revision_id: UUID
    claim_ids: list[UUID] = Field(min_length=1, max_length=20)
    section_id: UUID | None = None
    title: Short
    instruction: Text
    provider: Literal['mock', 'openai'] = 'mock'
    model: Literal['mock-grounded-v1', 'gpt-4.1-mini-2025-04-14', 'gpt-6.1-sol'] = 'mock-grounded-v1'
    reasoning_effort: Literal['low','medium','high','xhigh','max'] | None = None
    kind: Literal['writing', 'semantic_review'] = 'writing'
    review_job_id: UUID | None = None
    review_result_hash: Hash | None = None
    max_output_tokens: Annotated[int, Field(strict=True, ge=256, le=8000)] = 2000

    @model_validator(mode='after')
    def distinct_claims(self):
        if (self.provider == 'mock') != (self.model == 'mock-grounded-v1'): raise ValueError('Provider/model mismatch')
        if self.model != 'gpt-6.1-sol' and self.reasoning_effort is not None: raise ValueError('Reasoning only supported by Sol')
        if self.model == 'gpt-6.1-sol' and self.section_id is None: raise ValueError('Sol requires a selected section')
        if self.kind == 'semantic_review':
            if self.review_job_id is None or self.review_result_hash is None: raise ValueError('Review subject required')
        elif self.review_job_id is not None or self.review_result_hash is not None:
            raise ValueError('Writing task cannot carry a review subject')
        if len(set(self.claim_ids)) != len(self.claim_ids): raise ValueError('Duplicate claim')
        return self


class Consent(Contract):
    fingerprint: Hash
    approved: Literal[True]

    @field_validator('approved', mode='before')
    @classmethod
    def explicit_boolean(cls, value):
        if value is not True: raise ValueError('Explicit approval required')
        return value


class ProposalCitation(Contract):
    paragraph: Annotated[int, Field(strict=True, ge=0, le=19)]
    claim_id: UUID
    evidence_id: UUID
    source_version_id: UUID
    start: Count
    end: Count
    quote: Text
    kind: Literal['quotation', 'paraphrase']


class EvidenceDisposition(Contract):
    evidence_id: UUID
    relation: Literal['supports', 'contradicts', 'limits']
    explanation: Short


class ClaimAssessment(Contract):
    claim_id: UUID
    status: Literal['needs_review', 'insufficient_evidence']
    evidence: list[EvidenceDisposition] = Field(max_length=30)
    explanation: Short


class ResearchGap(Contract):
    claim_id: UUID
    explanation: Short


class Proposal(Contract):
    schema_version: Literal['1']
    context_hash: Hash
    paragraphs: list[Text] = Field(min_length=1, max_length=20)
    claims: list[ClaimAssessment] = Field(min_length=1, max_length=20)
    citations: list[ProposalCitation] = Field(max_length=100)
    research_gaps: list[ResearchGap] = Field(max_length=20)
    warnings: list[Short] = Field(max_length=30)
    verification: Literal['unverified']


class SemanticFinding(Contract):
    claim_id: UUID
    evidence_id: UUID
    paragraph: Annotated[int, Field(strict=True, ge=0, le=19)]
    outcome: Literal['supports', 'contradicts', 'uncertain', 'insufficient_data']
    explanation: Text
    evidence_quote: Text
    limitations: list[Short] = Field(max_length=20)


class SemanticReview(Contract):
    result_hash: Hash
    context_hash: Hash
    reviewer_kind: Literal['human', 'model']
    reviewer_version: Short
    findings: list[SemanticFinding] = Field(max_length=100)
    # Never a universal "verified" flag.
    status: Literal['needs_review', 'uncertain', 'insufficient_data']


class AcceptanceSpec(Contract):
    request_id: UUID
    manuscript_revision_id: UUID
    plan_revision_id: UUID
    result_hash: Hash
    review_acknowledged: Literal[True]

    @field_validator('review_acknowledged', mode='before')
    @classmethod
    def explicit_boolean(cls, value):
        if value is not True: raise ValueError('Explicit approval required')
        return value


class HumanReviewSubmission(Contract):
    request_id: UUID
    review: SemanticReview
    acknowledged: Literal[True]

    @field_validator('acknowledged', mode='before')
    @classmethod
    def explicit_review(cls, value):
        if value is not True: raise ValueError('Explicit human review required')
        return value
