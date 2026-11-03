from datetime import datetime
from uuid import UUID, uuid4

from sqlalchemy import DateTime, ForeignKey, Integer, String, Text, UniqueConstraint, CheckConstraint, func
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
