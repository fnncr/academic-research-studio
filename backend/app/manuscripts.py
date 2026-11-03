import asyncio
import hashlib
import json
from datetime import datetime
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, Query, Request
from pydantic import BaseModel, ConfigDict, ValidationError
from sqlalchemy import select
from starlette.requests import ClientDisconnect

from app.manuscript_schema import ManuscriptDocument, SaveManuscript
from app.models import ManuscriptRevision
from app.projects import DB, get_project, problem

router = APIRouter(prefix='/api/projects/{project_id}/manuscript', tags=['manuscripts'])
MAX_BODY = 2 * 1024 * 1024


class RevisionSummary(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: UUID
    project_id: UUID
    number: int
    parent_id: UUID | None
    restored_from_id: UUID | None
    content_hash: str
    created_at: datetime


class RevisionResponse(RevisionSummary):
    document: ManuscriptDocument


async def bounded_payload(request: Request) -> SaveManuscript:
    if request.headers.get('content-encoding', 'identity') != 'identity':
        raise problem(415, 'unsupported_encoding', 'Сжатие запроса не поддерживается.')
    if request.headers.get('content-type', '').split(';')[0].strip() != 'application/json':
        raise problem(415, 'unsupported_media_type', 'Ожидается JSON-документ.')
    data = bytearray()
    try:
        async with asyncio.timeout(15):
            async for chunk in request.stream():
                if len(data) + len(chunk) > MAX_BODY:
                    raise problem(413, 'manuscript_too_large', 'Рукопись превышает лимит 2 МиБ на запрос.')
                data.extend(chunk)
        return SaveManuscript.model_validate_json(data)
    except (ValidationError, ValueError):
        # Pydantic input/context may contain the entire manuscript. Do not echo it.
        raise problem(422, 'invalid_manuscript', 'Неподдерживаемая структура, повтор ID или превышение лимитов рукописи.') from None
    except (TimeoutError, ClientDisconnect):
        raise problem(408, 'upload_interrupted', 'Передача рукописи прервана. Черновик можно отправить повторно.') from None


def digest(value):
    return hashlib.sha256(json.dumps(value, ensure_ascii=False, sort_keys=True,
                                     separators=(',', ':')).encode('utf-8')).hexdigest()


def current_revision(db, project_id):
    return db.scalar(select(ManuscriptRevision).where(ManuscriptRevision.project_id == project_id)
                     .order_by(ManuscriptRevision.number.desc()).limit(1))


def scoped_revision(db, project_id, revision_id):
    revision = db.scalar(select(ManuscriptRevision).where(
        ManuscriptRevision.project_id == project_id, ManuscriptRevision.id == revision_id))
    if revision is None:
        raise problem(404, 'revision_not_found', 'Версия рукописи не найдена в этом проекте.')
    return revision


@router.get('', response_model=RevisionResponse | None)
def read_manuscript(project_id: UUID, db: DB):
    get_project(db, project_id)
    return current_revision(db, project_id)


@router.get('/revisions', response_model=list[RevisionSummary])
def list_revisions(project_id: UUID, db: DB, limit: int = Query(20, ge=1, le=100),
                   before: int | None = Query(None, ge=1)):
    get_project(db, project_id)
    statement = select(ManuscriptRevision).where(ManuscriptRevision.project_id == project_id)
    if before is not None:
        statement = statement.where(ManuscriptRevision.number < before)
    return list(db.scalars(statement.order_by(ManuscriptRevision.number.desc()).limit(limit)))


@router.get('/revisions/{revision_id}', response_model=RevisionResponse)
def read_revision(project_id: UUID, revision_id: UUID, db: DB):
    get_project(db, project_id)
    return scoped_revision(db, project_id, revision_id)


@router.post('/revisions', response_model=RevisionResponse, status_code=201)
def save_manuscript(project_id: UUID, payload: Annotated[SaveManuscript, Depends(bounded_payload)], db: DB):
    get_project(db, project_id, lock=True)  # Serializes even the first save from two tabs.
    request_hash = digest(payload.model_dump(mode='json'))
    previous = db.scalar(select(ManuscriptRevision).where(
        ManuscriptRevision.project_id == project_id, ManuscriptRevision.request_id == payload.request_id))
    if previous is not None:
        if previous.request_hash != request_hash:
            raise problem(409, 'request_conflict', 'Этот идентификатор сохранения уже использован для другого текста.')
        return RevisionResponse.model_validate(previous)
    current = current_revision(db, project_id)
    if (current.id if current else None) != payload.base_revision_id:
        raise problem(409, 'revision_conflict', 'Рукопись изменилась в другой вкладке. Сравните версии перед сохранением.')
    document = payload.document.model_dump(mode='json')
    if payload.restored_from_id:
        restored = scoped_revision(db, project_id, payload.restored_from_id)
        if restored.document != document:
            raise problem(422, 'restore_mismatch', 'Для восстановления нужен точный текст выбранной версии.')
    revision = ManuscriptRevision(project_id=project_id, number=current.number + 1 if current else 1,
        parent_id=current.id if current else None, restored_from_id=payload.restored_from_id,
        request_id=payload.request_id, request_hash=request_hash, content_hash=digest(document), document=document)
    db.add(revision)
    db.flush()
    result = RevisionResponse.model_validate(revision)
    db.commit()
    return result
