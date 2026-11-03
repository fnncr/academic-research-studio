import asyncio
from datetime import datetime
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, Query, Request
from pydantic import BaseModel, ConfigDict, ValidationError
from sqlalchemy import select
from starlette.requests import ClientDisconnect

from app.evidence_schema import PlanDocument, SavePlan, WriteEvidence, utf16_slice
from app.manuscripts import digest, scoped_revision
from app.models import Evidence, PlanEvidenceReference, ResearchPlanRevision, Source, SourceVersion
from app.projects import DB, get_project, problem
from app.sources import version_view

router = APIRouter(prefix='/api/projects/{project_id}', tags=['evidence'])
MAX_BODY = 256 * 1024


async def read_payload(request, schema):
    if request.headers.get('content-type', '').split(';')[0].strip() != 'application/json' or request.headers.get('content-encoding', 'identity') != 'identity':
        raise problem(415, 'unsupported_format', 'Ожидается несжатый JSON.')
    data = bytearray()
    try:
        async with asyncio.timeout(15):
            async for chunk in request.stream():
                if len(data) + len(chunk) > MAX_BODY:
                    raise problem(413, 'payload_too_large', 'План или фрагмент превышает лимит 256 КиБ.')
                data.extend(chunk)
        return schema.model_validate_json(data)
    except (ValidationError, ValueError):
        raise problem(422, 'invalid_evidence_plan', 'Проверьте поля, связи, согласие и точное совпадение цитаты с фрагментом.') from None
    except (ClientDisconnect, TimeoutError):
        raise problem(408, 'upload_interrupted', 'Передача запроса прервана.') from None


async def evidence_payload(request: Request): return await read_payload(request, WriteEvidence)
async def plan_payload(request: Request): return await read_payload(request, SavePlan)
EvidenceInput = Annotated[WriteEvidence, Depends(evidence_payload)]
PlanInput = Annotated[SavePlan, Depends(plan_payload)]


def source_version(db, project_id, version_id):
    version = db.scalar(select(SourceVersion).join(Source).where(
        Source.project_id == project_id, SourceVersion.id == version_id))
    if version is None:
        raise problem(404, 'source_version_not_found', 'Версия источника не найдена в проекте.')
    return version


def evidence_view(record):
    return {'id': record.id, 'project_id': record.project_id,
            'source_version_id': record.source_version_id, 'content': record.content,
            'content_hash': record.content_hash, 'created_at': record.created_at,
            'verification': 'user_supplied_excerpt', 'locator_verification': 'unverified',
            'full_text_verified': False}


@router.post('/evidence', status_code=201)
def create_evidence(project_id: UUID, body: EvidenceInput, db: DB):
    get_project(db, project_id, lock=True)
    fingerprint = digest(body.model_dump(mode='json'))
    previous = db.scalar(select(Evidence).where(Evidence.project_id == project_id, Evidence.request_id == body.request_id))
    if previous is not None:
        if previous.request_hash != fingerprint:
            raise problem(409, 'request_conflict', 'Ключ запроса уже использован для других данных.')
        return evidence_view(previous)
    source_version(db, project_id, body.source_version_id)
    content = body.model_dump(mode='json', exclude={'request_id', 'source_version_id'})
    record = Evidence(project_id=project_id, source_version_id=body.source_version_id,
        request_id=body.request_id, request_hash=fingerprint, content_hash=digest(content), content=content)
    db.add(record); db.flush()
    result = evidence_view(record)
    db.commit()
    return result


@router.get('/evidence')
def list_evidence(project_id: UUID, db: DB, limit: int = Query(20, ge=1, le=100), offset: int = Query(0, ge=0)):
    get_project(db, project_id)
    return [evidence_view(record) for record in db.scalars(select(Evidence).where(Evidence.project_id == project_id)
        .order_by(Evidence.created_at.desc(), Evidence.id).limit(limit).offset(offset))]


@router.get('/evidence/{evidence_id}')
def read_evidence(project_id: UUID, evidence_id: UUID, db: DB):
    record = db.scalar(select(Evidence).where(Evidence.project_id == project_id, Evidence.id == evidence_id))
    if record is None:
        raise problem(404, 'evidence_not_found', 'Фрагмент не найден в проекте.')
    return {**evidence_view(record), 'source_version': version_view(source_version(db, project_id, record.source_version_id))}


class PlanSummary(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: UUID
    project_id: UUID
    manuscript_revision_id: UUID
    number: int
    parent_id: UUID | None
    content_hash: str
    created_at: datetime


class PlanResponse(PlanSummary):
    document: PlanDocument


def latest_plan(db, project_id):
    return db.scalar(select(ResearchPlanRevision).where(ResearchPlanRevision.project_id == project_id)
        .order_by(ResearchPlanRevision.number.desc()).limit(1))


def text_nodes(document):
    """Stable text IDs include list items and table cells, never inferred text."""
    nodes = {}
    def visit(value):
        if isinstance(value, dict):
            if 'id' in value and 'text' in value:
                nodes[value['id']] = value
            for child in value.values():
                if isinstance(child, (dict, list)): visit(child)
        elif isinstance(value, list):
            for child in value: visit(child)
    visit(document)
    return nodes


def validate_plan(db, project_id, body):
    manuscript = scoped_revision(db, project_id, body.manuscript_revision_id)
    nodes = text_nodes(manuscript.document)
    evidence_ids = {link.evidence_id for claim in body.document.claims for link in claim.evidence}
    evidence = {item.id: item for item in db.scalars(select(Evidence).where(
        Evidence.project_id == project_id, Evidence.id.in_(evidence_ids)))} if evidence_ids else {}
    if evidence_ids != set(evidence):
        raise problem(404, 'evidence_not_found', 'Связанный фрагмент не найден в проекте.')
    for claim in body.document.claims:
        if claim.section_id is not None and nodes.get(str(claim.section_id), {}).get('type') != 'heading':
            raise problem(422, 'invalid_section', 'Раздел должен быть заголовком выбранной версии рукописи.')
    for citation in body.document.citations:
        node = nodes.get(str(citation.block_id))
        try:
            selected = utf16_slice(node['text'], citation.selection.start, citation.selection.end) if node else None
        except ValueError:
            selected = None
        if selected != citation.selection.quote:
            raise problem(422, 'citation_mismatch', 'Цитируемый диапазон не совпадает с выбранной версией рукописи.')
        if citation.kind == 'quotation' and selected != evidence[citation.evidence_id].content['selection']['quote']:
            raise problem(422, 'quotation_mismatch', 'Прямая цитата должна точно совпадать с сохранённой цитатой источника.')
    return evidence_ids


@router.get('/research-plan', response_model=PlanResponse | None)
def read_plan(project_id: UUID, db: DB):
    get_project(db, project_id)
    return latest_plan(db, project_id)


@router.get('/research-plan/revisions', response_model=list[PlanSummary])
def list_plans(project_id: UUID, db: DB, limit: int = Query(20, ge=1, le=100), before: int | None = Query(None, ge=1)):
    get_project(db, project_id)
    statement = select(ResearchPlanRevision).where(ResearchPlanRevision.project_id == project_id)
    if before is not None: statement = statement.where(ResearchPlanRevision.number < before)
    return list(db.scalars(statement.order_by(ResearchPlanRevision.number.desc()).limit(limit)))


@router.get('/research-plan/revisions/{revision_id}', response_model=PlanResponse)
def read_plan_revision(project_id: UUID, revision_id: UUID, db: DB):
    record = db.scalar(select(ResearchPlanRevision).where(
        ResearchPlanRevision.project_id == project_id, ResearchPlanRevision.id == revision_id))
    if record is None: raise problem(404, 'plan_not_found', 'Версия плана не найдена в проекте.')
    return record


@router.post('/research-plan/revisions', response_model=PlanResponse, status_code=201)
def save_plan(project_id: UUID, body: PlanInput, db: DB):
    get_project(db, project_id, lock=True)
    fingerprint = digest(body.model_dump(mode='json'))
    previous = db.scalar(select(ResearchPlanRevision).where(
        ResearchPlanRevision.project_id == project_id, ResearchPlanRevision.request_id == body.request_id))
    if previous is not None:
        if previous.request_hash != fingerprint:
            raise problem(409, 'request_conflict', 'Ключ запроса уже использован для других данных.')
        return PlanResponse.model_validate(previous)
    current = latest_plan(db, project_id)
    if body.base_revision_id != (current.id if current else None):
        raise problem(409, 'plan_conflict', 'План изменился в другой вкладке. Загрузите его для сравнения.')
    evidence_ids = validate_plan(db, project_id, body)
    document = body.document.model_dump(mode='json')
    record = ResearchPlanRevision(project_id=project_id, manuscript_revision_id=body.manuscript_revision_id,
        parent_id=current.id if current else None, number=current.number + 1 if current else 1,
        request_id=body.request_id, request_hash=fingerprint,
        content_hash=digest({'manuscript_revision_id': str(body.manuscript_revision_id), 'document': document}), document=document)
    db.add(record); db.flush()
    for evidence_id in evidence_ids:
        db.add(PlanEvidenceReference(plan_revision_id=record.id, evidence_id=evidence_id))
    result = PlanResponse.model_validate(record)
    db.commit()
    return result
