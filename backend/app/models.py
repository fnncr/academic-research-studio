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
