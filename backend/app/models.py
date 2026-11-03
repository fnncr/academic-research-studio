from datetime import datetime
from uuid import UUID, uuid4

from sqlalchemy import BigInteger, DateTime, ForeignKey, Integer, String, Text, UniqueConstraint, CheckConstraint, func
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column
from sqlalchemy.dialects.postgresql import JSONB


class Base(DeclarativeBase):
    pass


class Project(Base):
    __tablename__ = 'projects'
    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    title: Mapped[str] = mapped_column(String(200))
    research_question: Mapped[str] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class BriefRevision(Base):
    __tablename__ = 'brief_revisions'
    __table_args__ = (UniqueConstraint('project_id', 'number', name='uq_brief_project_number'),
                     CheckConstraint('number > 0', name='ck_brief_number_positive'))
    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    project_id: Mapped[UUID] = mapped_column(ForeignKey('projects.id'), index=True)
    number: Mapped[int] = mapped_column(Integer)
    requirements: Mapped[str] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class ManuscriptRevision(Base):
    __tablename__ = 'manuscript_revisions'
    __table_args__ = (
        UniqueConstraint('project_id', 'number', name='uq_manuscript_project_number'),
        UniqueConstraint('project_id', 'request_id', name='uq_manuscript_request'),
        CheckConstraint('number > 0', name='ck_manuscript_number_positive'),
    )
    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    project_id: Mapped[UUID] = mapped_column(ForeignKey('projects.id'), index=True)
    number: Mapped[int] = mapped_column(Integer)
    parent_id: Mapped[UUID | None] = mapped_column(ForeignKey('manuscript_revisions.id'))
    restored_from_id: Mapped[UUID | None] = mapped_column(ForeignKey('manuscript_revisions.id'))
    request_id: Mapped[UUID] = mapped_column()
    request_hash: Mapped[str] = mapped_column(String(64))
    content_hash: Mapped[str] = mapped_column(String(64))
    document: Mapped[dict] = mapped_column(JSONB)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class Source(Base):
    __tablename__ = 'sources'
    __table_args__ = (UniqueConstraint('project_id', 'request_id', name='uq_source_request'),)
    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    project_id: Mapped[UUID] = mapped_column(ForeignKey('projects.id'), index=True)
    request_id: Mapped[UUID] = mapped_column()
    request_hash: Mapped[str] = mapped_column(String(64))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class SourceVersion(Base):
    __tablename__ = 'source_versions'
    __table_args__ = (UniqueConstraint('source_id', 'number', name='uq_source_version_number'),
                     UniqueConstraint('source_id', 'request_id', name='uq_source_version_request'),
                     CheckConstraint('number > 0', name='ck_source_version_number'))
    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    source_id: Mapped[UUID] = mapped_column(ForeignKey('sources.id'), index=True)
    number: Mapped[int] = mapped_column(Integer)
    request_id: Mapped[UUID] = mapped_column()
    request_hash: Mapped[str] = mapped_column(String(64))
    metadata_json: Mapped[dict] = mapped_column(JSONB)
    provenance: Mapped[dict] = mapped_column(JSONB)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class SourceIdentifier(Base):
    __tablename__ = 'source_identifiers'
    project_id: Mapped[UUID] = mapped_column(ForeignKey('projects.id'), primary_key=True)
    kind: Mapped[str] = mapped_column(String(4), primary_key=True)
    value: Mapped[str] = mapped_column(String(255), primary_key=True)
    source_id: Mapped[UUID] = mapped_column(ForeignKey('sources.id'), index=True)


class SearchRun(Base):
    __tablename__ = 'search_runs'
    __table_args__ = (UniqueConstraint('project_id', 'request_id', name='uq_search_request'),)
    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    project_id: Mapped[UUID] = mapped_column(ForeignKey('projects.id'), index=True)
    request_id: Mapped[UUID] = mapped_column()
    request_hash: Mapped[str] = mapped_column(String(64))
    request_json: Mapped[dict] = mapped_column(JSONB)
    source_version_id: Mapped[UUID | None] = mapped_column(ForeignKey('source_versions.id'))
    status: Mapped[str] = mapped_column(String(20))
    results: Mapped[list] = mapped_column(JSONB)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class Evidence(Base):
    __tablename__ = 'evidence'
    __table_args__ = (UniqueConstraint('project_id', 'request_id', name='uq_evidence_request'),)
    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    project_id: Mapped[UUID] = mapped_column(ForeignKey('projects.id'), index=True)
    source_version_id: Mapped[UUID] = mapped_column(ForeignKey('source_versions.id'))
    request_id: Mapped[UUID] = mapped_column()
    request_hash: Mapped[str] = mapped_column(String(64))
    content_hash: Mapped[str] = mapped_column(String(64))
    content: Mapped[dict] = mapped_column(JSONB)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class ResearchPlanRevision(Base):
    __tablename__ = 'research_plan_revisions'
    __table_args__ = (
        UniqueConstraint('project_id', 'number', name='uq_plan_number'),
        UniqueConstraint('project_id', 'request_id', name='uq_plan_request'),
        CheckConstraint('number > 0', name='ck_plan_number'),
    )
    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    project_id: Mapped[UUID] = mapped_column(ForeignKey('projects.id'), index=True)
    manuscript_revision_id: Mapped[UUID] = mapped_column(ForeignKey('manuscript_revisions.id'))
    parent_id: Mapped[UUID | None] = mapped_column(ForeignKey('research_plan_revisions.id'))
    number: Mapped[int] = mapped_column(Integer)
    request_id: Mapped[UUID] = mapped_column()
    request_hash: Mapped[str] = mapped_column(String(64))
    content_hash: Mapped[str] = mapped_column(String(64))
    document: Mapped[dict] = mapped_column(JSONB)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class PlanEvidenceReference(Base):
    __tablename__ = 'plan_evidence_references'
    plan_revision_id: Mapped[UUID] = mapped_column(ForeignKey('research_plan_revisions.id'), primary_key=True)
    evidence_id: Mapped[UUID] = mapped_column(ForeignKey('evidence.id'), primary_key=True)


# P6 is deliberately additive: existing revision rows/schemas remain untouched.
class ModelBudget(Base):
    __tablename__ = 'model_budgets'
    __table_args__ = (CheckConstraint('limit_units >= 0 AND spent_units >= 0 AND reserved_units >= 0 AND spent_units + reserved_units <= limit_units', name='ck_model_budget'),)
    project_id: Mapped[UUID] = mapped_column(ForeignKey('projects.id'), primary_key=True)
    currency: Mapped[str] = mapped_column(String(3))
    blocked: Mapped[bool] = mapped_column(default=False)
    limit_units: Mapped[int] = mapped_column(BigInteger)
    spent_units: Mapped[int] = mapped_column(BigInteger)
    reserved_units: Mapped[int] = mapped_column(BigInteger)


class ModelJob(Base):
    __tablename__ = 'model_jobs'
    __table_args__ = (
        UniqueConstraint('project_id', 'request_id', name='uq_model_job_request'),
        CheckConstraint("state IN ('queued','leased','dispatching','ambiguous','succeeded','invalid','cancelled','failed')", name='ck_model_job_state'),
        CheckConstraint('reserved_units >= 0', name='ck_model_job_reserve'),
    )
    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    project_id: Mapped[UUID] = mapped_column(ForeignKey('projects.id'), index=True)
    request_id: Mapped[UUID] = mapped_column()
    fingerprint: Mapped[str] = mapped_column(String(64))
    brief_revision_id: Mapped[UUID] = mapped_column(ForeignKey('brief_revisions.id'))
    manuscript_revision_id: Mapped[UUID] = mapped_column(ForeignKey('manuscript_revisions.id'))
    plan_revision_id: Mapped[UUID] = mapped_column(ForeignKey('research_plan_revisions.id'))
    input_json: Mapped[dict] = mapped_column(JSONB)
    reserved_units: Mapped[int] = mapped_column(BigInteger)
    state: Mapped[str] = mapped_column(String(20), index=True)
    lease_token: Mapped[UUID | None] = mapped_column()
    lease_until: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    dispatch_id: Mapped[UUID | None] = mapped_column()
    cancel_requested: Mapped[bool] = mapped_column(default=False)
    result: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    report: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class ModelSettlement(Base):
    __tablename__ = 'model_settlements'
    __table_args__ = (CheckConstraint('charged_units >= 0 AND input_tokens >= 0 AND output_tokens >= 0', name='ck_model_settlement'),)
    job_id: Mapped[UUID] = mapped_column(ForeignKey('model_jobs.id'), primary_key=True)
    project_id: Mapped[UUID] = mapped_column(ForeignKey('projects.id'))
    charged_units: Mapped[int] = mapped_column(BigInteger)
    input_tokens: Mapped[int | None] = mapped_column(Integer)
    output_tokens: Mapped[int | None] = mapped_column(Integer)
    reason: Mapped[str] = mapped_column(String(100))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class ModelAcceptance(Base):
    __tablename__ = 'model_acceptances'
    __table_args__ = (UniqueConstraint('project_id', 'request_id', name='uq_model_accept_request'),)
    job_id: Mapped[UUID] = mapped_column(ForeignKey('model_jobs.id'), primary_key=True)
    project_id: Mapped[UUID] = mapped_column(ForeignKey('projects.id'))
    request_id: Mapped[UUID] = mapped_column()
    request_hash: Mapped[str] = mapped_column(String(64))
    manuscript_revision_id: Mapped[UUID] = mapped_column(ForeignKey('manuscript_revisions.id'))
    plan_revision_id: Mapped[UUID] = mapped_column(ForeignKey('research_plan_revisions.id'))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class ModelAudit(Base):
    __tablename__ = 'model_audit'
    __table_args__ = (UniqueConstraint('project_id', 'action', 'request_id', name='uq_model_audit_request'),)
    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    project_id: Mapped[UUID] = mapped_column(ForeignKey('projects.id'))
    job_id: Mapped[UUID | None] = mapped_column(ForeignKey('model_jobs.id'))
    action: Mapped[str] = mapped_column(String(30))
    request_id: Mapped[UUID] = mapped_column()
    actor: Mapped[str] = mapped_column(String(100))
    request_hash: Mapped[str] = mapped_column(String(64))
    details: Mapped[dict] = mapped_column(JSONB)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
