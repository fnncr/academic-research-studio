from datetime import datetime
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from pydantic import BaseModel, ConfigDict, StringConstraints
from sqlalchemy import select
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from app.models import BriefRevision, Project

router = APIRouter(prefix='/api/projects', tags=['projects'])
Title = Annotated[str, StringConstraints(strict=True, strip_whitespace=True, min_length=1, max_length=200)]
Question = Annotated[str, StringConstraints(strict=True, strip_whitespace=True, min_length=1, max_length=4000)]
Requirements = Annotated[str, StringConstraints(strict=True, strip_whitespace=True, min_length=1, max_length=20000)]


def problem(status: int, code: str, message: str):
    return HTTPException(status, detail={'code': code, 'message': message, 'retryable': status == 503})


class CreateProject(BaseModel):
    model_config = ConfigDict(extra='forbid')
    title: Title
    research_question: Question
    requirements: Requirements


class CreateBrief(BaseModel):
    model_config = ConfigDict(extra='forbid')
    base_revision_id: UUID
    requirements: Requirements


class ProjectSummary(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: UUID
    title: str
    research_question: str
    created_at: datetime


class BriefResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: UUID
    project_id: UUID
    number: int
    requirements: str
    created_at: datetime


class ProjectResponse(ProjectSummary):
    latest_brief: BriefResponse


def session(request: Request):
    engine = getattr(request.app.state, 'project_engine', None)
    if engine is None:
        raise problem(503, 'storage_unavailable', 'Хранилище проектов недоступно. Извлечение текста работает отдельно.')
    try:
        with Session(engine) as db:
            yield db
    except SQLAlchemyError:
        # Do not expose connection strings, SQL parameters or document content.
        raise problem(503, 'storage_unavailable', 'Не удалось сохранить или прочитать проект. Повторите попытку.') from None


DB = Annotated[Session, Depends(session)]


def get_project(db: Session, project_id: UUID, lock=False):
    statement = select(Project).where(Project.id == project_id)
    if lock:
        statement = statement.with_for_update()
    project = db.scalar(statement)
    if project is None:
        raise problem(404, 'project_not_found', 'Проект не найден.')
    return project


def latest(db: Session, project_id: UUID):
    return db.scalar(select(BriefRevision).where(BriefRevision.project_id == project_id)
                     .order_by(BriefRevision.number.desc()).limit(1))


def detail(project: Project, brief: BriefRevision):
    return ProjectResponse(**ProjectSummary.model_validate(project).model_dump(),
                           latest_brief=BriefResponse.model_validate(brief))


@router.post('', response_model=ProjectResponse, status_code=201)
def create_project(payload: CreateProject, db: DB):
    project = Project(title=payload.title, research_question=payload.research_question)
    db.add(project)
    db.flush()
    brief = BriefRevision(project_id=project.id, number=1, requirements=payload.requirements)
    db.add(brief)
    db.flush()
    result = detail(project, brief)
    db.commit()  # Project and first requirements revision commit atomically.
    return result


@router.get('', response_model=list[ProjectSummary])
def list_projects(db: DB, limit: int = Query(20, ge=1, le=100), offset: int = Query(0, ge=0)):
    return list(db.scalars(select(Project).order_by(Project.created_at.desc(), Project.id)
                          .limit(limit).offset(offset)))


@router.get('/{project_id}', response_model=ProjectResponse)
def read_project(project_id: UUID, db: DB):
    project = get_project(db, project_id)
    return detail(project, latest(db, project.id))


@router.get('/{project_id}/brief-revisions', response_model=list[BriefResponse])
def list_briefs(project_id: UUID, db: DB, limit: int = Query(20, ge=1, le=100), offset: int = Query(0, ge=0)):
    get_project(db, project_id)
    return list(db.scalars(select(BriefRevision).where(BriefRevision.project_id == project_id)
                          .order_by(BriefRevision.number.desc()).limit(limit).offset(offset)))


@router.post('/{project_id}/brief-revisions', response_model=BriefResponse, status_code=201)
def create_brief(project_id: UUID, payload: CreateBrief, db: DB):
    project = get_project(db, project_id, lock=True)
    current = latest(db, project.id)
    if current.id != payload.base_revision_id:
        raise problem(409, 'revision_conflict', 'Требования изменились в другой вкладке. Откройте актуальную версию и сравните текст.')
    brief = BriefRevision(project_id=project.id, number=current.number + 1, requirements=payload.requirements)
    db.add(brief)
    db.flush()
    result = BriefResponse.model_validate(brief)
    db.commit()
    return result
