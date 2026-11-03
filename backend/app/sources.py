import asyncio
import threading
from datetime import datetime
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from pydantic import ValidationError
from sqlalchemy import delete, select
from starlette.requests import ClientDisconnect

from app import source_adapters
from app.manuscripts import digest
from app.models import SearchRun, Source, SourceIdentifier, SourceVersion
from app.projects import DB, get_project, problem
from app.source_schema import SearchRequest, WriteSource

router = APIRouter(prefix='/api/projects/{project_id}', tags=['sources'])
network_slots = threading.BoundedSemaphore(2)


async def payload(request: Request, schema):
    if request.headers.get('content-type', '').split(';')[0].strip() != 'application/json' or request.headers.get('content-encoding', 'identity') != 'identity':
        raise problem(415, 'unsupported_format', 'Ожидается несжатый JSON.')
    data = bytearray()
    try:
        async with asyncio.timeout(15):
            async for chunk in request.stream():
                if len(data) + len(chunk) > 128 * 1024:
                    raise problem(413, 'payload_too_large', 'Слишком большой запрос библиотеки.')
                data.extend(chunk)
        return schema.model_validate_json(data)
    except (ValidationError, ValueError):
        raise problem(422, 'invalid_source_request', 'Проверьте поля, формат DOI, контрольную сумму ISBN и диапазон лет.') from None
    except (ClientDisconnect, TimeoutError):
        raise problem(408, 'upload_interrupted', 'Передача запроса прервана.') from None


async def source_payload(request: Request): return await payload(request, WriteSource)
async def search_payload(request: Request): return await payload(request, SearchRequest)
SourceInput = Annotated[WriteSource, Depends(source_payload)]
SearchInput = Annotated[SearchRequest, Depends(search_payload)]


def source_record(db, project_id, source_id):
    record = db.scalar(select(Source).where(Source.id == source_id, Source.project_id == project_id))
    if record is None: raise problem(404, 'source_not_found', 'Источник не найден в проекте.')
    return record


def latest_version(db, source_id):
    return db.scalar(select(SourceVersion).where(SourceVersion.source_id == source_id).order_by(SourceVersion.number.desc()).limit(1))


def version_view(version):
    return {'id': version.id, 'source_id': version.source_id, 'number': version.number, 'metadata': version.metadata_json,
            'provenance': version.provenance, 'created_at': version.created_at, 'verification': 'unverified'}


def source_view(record, version):
    return {'id': record.id, 'project_id': record.project_id, 'created_at': record.created_at, 'latest_version': version_view(version)}


def check_identities(db, project_id, metadata, except_source=None):
    matches = {}
    for kind in ('doi', 'isbn'):
        if not metadata.get(kind): continue
        identifier = db.get(SourceIdentifier, (project_id, kind, metadata[kind]))
        if identifier and identifier.source_id != except_source:
            current = latest_version(db, identifier.source_id)
            matches[str(identifier.source_id)] = {'source_id': str(identifier.source_id), 'version_id': str(current.id),
                'metadata': current.metadata_json, 'differences': source_adapters.metadata_differences(current.metadata_json, metadata)}
    if matches:
        raise HTTPException(409, detail={'code': 'duplicate_source', 'message': 'Этот DOI или ISBN уже есть в проекте. Сравните метаданные перед изменением существующей карточки.', 'retryable': False, 'matches': list(matches.values())})


def set_identities(db, project_id, source_id, metadata):
    db.execute(delete(SourceIdentifier).where(SourceIdentifier.project_id == project_id, SourceIdentifier.source_id == source_id))
    for kind in ('doi', 'isbn'):
        if metadata.get(kind): db.add(SourceIdentifier(project_id=project_id, source_id=source_id, kind=kind, value=metadata[kind]))


def provenance(db, project_id, body):
    if body.origin is None: return {'kind': 'manual'}
    run = db.scalar(select(SearchRun).where(SearchRun.id == body.origin.search_run_id, SearchRun.project_id == project_id, SearchRun.status == 'completed'))
    if run:
        for result in run.results:
            for hit in result['hits']:
                if hit['id'] == body.origin.hit_id and hit['metadata'] == body.metadata.model_dump(mode='json'):
                    return {'kind': 'catalog_metadata', 'provider': result['provider'], 'search_run_id': str(run.id),
                            'hit_id': hit['id'], 'checked_at': result['checked_at'], 'adapter_version': result['adapter_version']}
    raise problem(422, 'origin_mismatch', 'Метаданные не совпадают с сохранённым результатом поиска этого проекта.')


@router.get('/sources')
def list_sources(project_id: UUID, db: DB, limit: int = Query(20, ge=1, le=100), offset: int = Query(0, ge=0)):
    get_project(db, project_id)
    records = db.scalars(select(Source).where(Source.project_id == project_id).order_by(Source.created_at.desc(), Source.id).limit(limit).offset(offset))
    return [source_view(record, latest_version(db, record.id)) for record in records]


@router.get('/sources/{source_id}')
def read_source(project_id: UUID, source_id: UUID, db: DB):
    record = source_record(db, project_id, source_id)
    return source_view(record, latest_version(db, source_id))


@router.post('/sources', status_code=201)
def create_source(project_id: UUID, body: SourceInput, db: DB):
    get_project(db, project_id, lock=True)
    if body.base_version_id is not None: raise problem(422, 'unexpected_base', 'У нового источника нет базовой версии.')
    fingerprint = digest(body.model_dump(mode='json'))
    previous = db.scalar(select(Source).where(Source.project_id == project_id, Source.request_id == body.request_id))
    if previous:
        if previous.request_hash != fingerprint: raise problem(409, 'request_conflict', 'Ключ запроса уже использован для других данных.')
        original = db.scalar(select(SourceVersion).where(SourceVersion.source_id == previous.id, SourceVersion.number == 1))
        return source_view(previous, original)
    metadata = body.metadata.model_dump(mode='json')
    check_identities(db, project_id, metadata)
    origin = provenance(db, project_id, body)
    record = Source(project_id=project_id, request_id=body.request_id, request_hash=fingerprint)
    db.add(record); db.flush()
    version = SourceVersion(source_id=record.id, number=1, request_id=body.request_id, request_hash=fingerprint, metadata_json=metadata, provenance=origin)
    db.add(version); db.flush(); set_identities(db, project_id, record.id, metadata)
    result = source_view(record, version); db.commit(); return result


@router.post('/sources/{source_id}/versions', status_code=201)
def update_source(project_id: UUID, source_id: UUID, body: SourceInput, db: DB):
    get_project(db, project_id, lock=True)
    source_record(db, project_id, source_id)
    fingerprint = digest(body.model_dump(mode='json'))
    previous = db.scalar(select(SourceVersion).where(SourceVersion.source_id == source_id, SourceVersion.request_id == body.request_id))
    if previous:
        if previous.request_hash != fingerprint: raise problem(409, 'request_conflict', 'Ключ запроса уже использован для других данных.')
        return version_view(previous)
    current = latest_version(db, source_id)
    if body.base_version_id != current.id: raise problem(409, 'version_conflict', 'Карточка изменилась. Загрузите актуальную версию и сравните поля.')
    metadata = body.metadata.model_dump(mode='json'); check_identities(db, project_id, metadata, source_id)
    version = SourceVersion(source_id=source_id, number=current.number + 1, request_id=body.request_id,
        request_hash=fingerprint, metadata_json=metadata, provenance=provenance(db, project_id, body))
    db.add(version); db.flush(); set_identities(db, project_id, source_id, metadata)
    result = version_view(version); db.commit(); return result


@router.get('/sources/{source_id}/versions')
def source_history(project_id: UUID, source_id: UUID, db: DB, before: int | None = Query(None, ge=1), limit: int = Query(20, ge=1, le=100)):
    source_record(db, project_id, source_id)
    query = select(SourceVersion).where(SourceVersion.source_id == source_id)
    if before: query = query.where(SourceVersion.number < before)
    return [version_view(v) for v in db.scalars(query.order_by(SourceVersion.number.desc()).limit(limit))]


@router.get('/sources/{source_id}/versions/{version_id}')
def read_source_version(project_id: UUID, source_id: UUID, version_id: UUID, db: DB):
    source_record(db, project_id, source_id)
    version = db.scalar(select(SourceVersion).where(SourceVersion.id == version_id, SourceVersion.source_id == source_id))
    if not version: raise problem(404, 'version_not_found', 'Версия источника не найдена.')
    return version_view(version)


def run_view(run):
    return {'id': run.id, 'project_id': run.project_id, 'request': run.request_json,
            'source_version_id': run.source_version_id, 'status': run.status, 'results': run.results, 'created_at': run.created_at}


@router.get('/search-runs')
def search_history(project_id: UUID, db: DB, limit: int = Query(10, ge=1, le=50), offset: int = Query(0, ge=0)):
    get_project(db, project_id)
    return [run_view(run) for run in db.scalars(select(SearchRun).where(SearchRun.project_id == project_id)
            .order_by(SearchRun.created_at.desc(), SearchRun.id).limit(limit).offset(offset))]


@router.post('/search-runs', status_code=201)
def search(project_id: UUID, body: SearchInput, db: DB):
    get_project(db, project_id, lock=True)
    fingerprint = digest(body.model_dump(mode='json'))
    previous = db.scalar(select(SearchRun).where(SearchRun.project_id == project_id, SearchRun.request_id == body.request_id))
    if previous:
        if previous.request_hash != fingerprint: raise problem(409, 'request_conflict', 'Ключ поиска уже использован для другого запроса.')
        return run_view(previous)
    target = None
    if body.source_version_id:
        target = db.scalar(select(SourceVersion).join(Source).where(Source.project_id == project_id, SourceVersion.id == body.source_version_id))
        if not target or target.metadata_json.get('doi') != body.query: raise problem(422, 'verification_mismatch', 'DOI не соответствует выбранной версии источника.')
    if not network_slots.acquire(blocking=False): raise problem(503, 'search_busy', 'Уже выполняются два поиска. Повторите позже.')
    try:
        run = SearchRun(project_id=project_id, request_id=body.request_id, request_hash=fingerprint,
            request_json=body.model_dump(mode='json', exclude={'request_id'}), source_version_id=body.source_version_id, status='pending', results=[])
        db.add(run); db.flush(); run_id = run.id
        target_metadata = target.metadata_json if target else None
        db.commit()  # Persist intent and release project lock before any network request.
        results = asyncio.run(source_adapters.fetch_all(body))
        all_hits = [hit for result in results for hit in result['hits']]
        for hit in all_hits:
            hit['related_hits'] = [{'id': other['id'], 'differences': source_adapters.metadata_differences(hit['metadata'], other['metadata'])}
                for other in all_hits if other['id'] != hit['id'] and any(hit['metadata'].get(key) and hit['metadata'][key] == other['metadata'].get(key) for key in ('doi', 'isbn'))]
        for result in results:
            for hit in result['hits']:
                if target_metadata:
                    differences = source_adapters.metadata_differences(target_metadata, hit['metadata'])
                    missing = [field for field in ('title', 'authors', 'year') if not target_metadata.get(field) or not hit['metadata'].get(field)]
                    hit['comparison'] = {'status': 'conflict' if differences else ('insufficient_metadata' if missing else 'metadata_match'), 'differences': differences, 'missing_fields': missing}
        run = db.get(SearchRun, run_id)
        run.status = 'completed'; run.results = results
        result = run_view(run); db.commit(); return result
    finally:
        network_slots.release()
