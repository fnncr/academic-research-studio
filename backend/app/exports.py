"""Preflight and scoped immutable export inputs; no network or persistent artifacts."""
from pathlib import Path
from typing import Annotated
from uuid import UUID
import json
import threading

from fastapi import APIRouter, Depends, HTTPException, Request, Response
from pydantic import ValidationError
from sqlalchemy import select

from app.evidence import read_payload, validate_plan
from app.evidence_schema import PlanDocument, SavePlan, WriteEvidence
from app.export_schema import ExportProfile, ExportRequest
from app.manuscript_schema import ManuscriptDocument
from app.manuscripts import digest, scoped_revision
from app.models import Evidence, ResearchPlanRevision, Source, SourceVersion
from app.projects import DB, get_project, problem
from app.source_schema import SourceMetadata

router = APIRouter(prefix='/api/projects/{project_id}/exports', tags=['exports'])
GENERATOR_VERSION = 'docx-1'
slots = threading.BoundedSemaphore(2)


async def export_payload(request: Request):
    try:
        return await read_payload(request, ExportRequest)
    except HTTPException as error:
        if error.status_code == 422:
            raise problem(422, 'invalid_export_settings', 'Проверьте версии, стиль и допустимые значения параметров оформления.') from None
        raise
ExportInput = Annotated[ExportRequest, Depends(export_payload)]


@router.get('/options')
def export_options(project_id: UUID, db: DB):
    get_project(db, project_id)
    profiles = json.loads((Path(__file__).parent / 'data/export-profiles.v1.json').read_text())
    for item in profiles:
        item['profile'] = ExportProfile.model_validate(item['profile']).model_dump()
    return {'profiles': profiles, 'citation_styles': [{'id': 'numeric-v1', 'label': 'Числовой, порядок первого цитирования (не ГОСТ)'}]}


def preflight(db, project_id, body):
    get_project(db, project_id)
    revision = scoped_revision(db, project_id, body.manuscript_revision_id)
    report = {'errors': [], 'warnings': [], 'info': []}
    def add(level, code, message, **location):
        report[level].append({'code': code, 'message': message, **location})
    source_map = {}; evidence_map = {}; plan = None; plan_document = None
    try:
        document = ManuscriptDocument.model_validate(revision.document).model_dump(mode='json')
        if digest(revision.document) != revision.content_hash:
            add('errors', 'manuscript_hash_mismatch', 'Хеш сохранённой рукописи не совпадает.')
    except (ValidationError, ValueError):
        document = {'schema_version': '1', 'blocks': []}
        add('errors', 'invalid_manuscript', 'Неподдерживаемая или повреждённая структура рукописи.')
    if not document['blocks']:
        add('errors', 'empty_manuscript', 'Рукопись пуста.')
    if body.title_page.enabled:
        for key, value in body.title_page.model_dump(exclude={'enabled'}).items():
            if value is None or isinstance(value, str) and not value.strip():
                add('errors', 'missing_title_field', 'Заполните поле титульного листа.', field=key)
    if body.plan_revision_id is not None:
        plan = db.scalar(select(ResearchPlanRevision).where(ResearchPlanRevision.id == body.plan_revision_id,
            ResearchPlanRevision.project_id == project_id))
        if plan is None:
            # Same 404 for foreign and unknown IDs; never return foreign metadata.
            raise problem(404, 'plan_not_found', 'Версия научного плана не найдена в проекте.')
        if body.without_plan:
            add('errors', 'plan_choice_conflict', 'Выберите план или экспорт без плана, а не оба варианта.')
        if plan.manuscript_revision_id != revision.id:
            add('errors', 'stale_plan', 'Научный план относится к другой версии рукописи. Перепроверьте привязки в P4.')
        try:
            plan_document = PlanDocument.model_validate(plan.document)
            validate_plan(db, project_id, SavePlan(request_id=plan.request_id, base_revision_id=None,
                manuscript_revision_id=plan.manuscript_revision_id, document=plan_document))
            if digest({'manuscript_revision_id': str(plan.manuscript_revision_id), 'document': plan.document}) != plan.content_hash:
                add('errors', 'plan_hash_mismatch', 'Хеш научного плана не совпадает.')
            for claim in plan_document.claims:
                if not claim.evidence:
                    add('warnings', 'unsupported_claim', 'У тезиса нет связанных доказательств.', claim_id=str(claim.id))
            ids = {citation.evidence_id for citation in plan_document.citations}
            for identifier in sorted(ids, key=str):
                evidence = db.scalar(select(Evidence).where(Evidence.id == identifier, Evidence.project_id == project_id))
                if evidence is None:
                    add('errors', 'missing_evidence', 'Доказательство не найдено в проекте.'); continue
                WriteEvidence.model_validate({**evidence.content, 'request_id': evidence.request_id,
                    'source_version_id': evidence.source_version_id})
                if digest(evidence.content) != evidence.content_hash:
                    add('errors', 'evidence_hash_mismatch', 'Хеш доказательства не совпадает.')
                evidence_map[str(identifier)] = evidence
                version = db.scalar(select(SourceVersion).join(Source).where(SourceVersion.id == evidence.source_version_id,
                    Source.project_id == project_id))
                if version is None:
                    add('errors', 'missing_source', 'Точная версия источника не найдена в проекте.'); continue
                source_map[str(version.id)] = version
            for identifier, version in source_map.items():
                metadata = SourceMetadata.model_validate(version.metadata_json)
                for key in ('title', 'authors', 'year'):
                    if not getattr(metadata, key):
                        add('errors', 'incomplete_bibliography', 'Недостаточно данных для библиографии.', source_version_id=identifier, source_title=metadata.title, field=key)
                for key in ('container',) if metadata.kind == 'article' else ('publisher',):
                    if not getattr(metadata, key):
                        add('warnings', 'incomplete_publication', 'Уточните библиографическое поле.', source_version_id=identifier, source_title=metadata.title, field=key)
                if not metadata.doi and not metadata.isbn and not metadata.url:
                    add('info', 'no_identifier', 'У записи нет DOI, ISBN или URL.', source_version_id=identifier, source_title=metadata.title)
            if plan_document.citations:
                add('warnings', 'unverified_sources', 'Метаданные, локаторы и научное соответствие цитат требуют проверки автора; экспорт их не подтверждает.')
            if plan_document.claims and not plan_document.citations:
                add('warnings', 'no_citations', 'В плане есть тезисы, но нет цитатных связей с рукописью.')
        except (ValidationError, ValueError, HTTPException):
            add('errors', 'invalid_scientific_links', 'Повреждённые, отсутствующие или неточные связи Evidence/Claim/Citation. Перепроверьте их в P4.')
    elif not body.without_plan:
        add('errors', 'plan_not_selected', 'Выберите версию научного плана или явно подтвердите экспорт без него.')
    else:
        add('warnings', 'without_plan', 'Экспорт без научного плана: ссылки в обычном тексте не распознаются автоматически.')
    cited_nodes = {str(c.block_id) for c in plan_document.citations} if plan_document else set()
    previous_level = 0
    for block in document['blocks']:
        if block['type'] == 'citation_placeholder':
            add('errors', 'unresolved_citation', 'Незаполненная заготовка ссылки. Замените её проверенной citation-связью в P4.', block_id=block['id'])
        elif block['type'] == 'heading':
            if not block['text'].strip(): add('errors', 'empty_heading', 'Пустой заголовок.', block_id=block['id'])
            if block['level'] > previous_level + 1:
                add('warnings', 'heading_level_jump', 'Пропущен уровень заголовка.', block_id=block['id'])
            previous_level = block['level']
        elif block['type'] == 'quote' and block['id'] not in cited_nodes:
            add('warnings', 'unlinked_quote', 'Цитатный блок не имеет связи с Evidence. Укажите источник или проверьте назначение блока.', block_id=block['id'])
        elif block['type'] == 'table':
            if len(block['rows'][0]['cells']) > 6:
                add('warnings', 'wide_table', 'Широкая таблица может потребовать ручного уменьшения шрифта или ширины.', block_id=block['id'])
    if body.profile.font_size >= 18 or body.profile.margin_left_cm + body.profile.margin_right_cm >= 8:
        add('warnings', 'tight_layout', 'Крупный шрифт или узкая полоса текста могут ухудшить переносы и таблицы.')
    if body.profile.toc:
        add('info', 'toc_update', 'В Word обновите оглавление и поля (Ctrl+A, F9). Номера страниц вычисляет офисный редактор.')
    add('info', 'unsupported_objects', 'Модель P2 не содержит рисунков, подписей, формул, сносок и объединённых ячеек. Эти объекты не создаются.')
    add('info', 'format_scope', 'Числовой стиль numeric-v1 и пользовательский профиль не заявляют соответствия ГОСТ или стандарту университета. Для точного титула нужен образец.')
    add('info', 'manual_reference_scope', 'Проверяются структурированные citations P4. Вручную набранные ссылки и библиографические строки не распознаются автоматически.')
    add('info', 'font_availability', 'Для одинаковой вёрстки в Word должен быть установлен выбранный шрифт.')
    def invalid_xml(value):
        if isinstance(value, str):
            return any(ord(c) < 32 and c not in '\t\n\r' or ord(c) in (0xFFFE, 0xFFFF) for c in value)
        if isinstance(value, dict): return any(invalid_xml(v) for v in value.values())
        if isinstance(value, list): return any(invalid_xml(v) for v in value)
        return False
    if invalid_xml([document, body.model_dump(mode='json'), [v.metadata_json for v in source_map.values()], [e.content for e in evidence_map.values()]]):
        add('errors', 'invalid_xml_text', 'Текст содержит неподдерживаемые XML-символы. Исправьте сохранённую версию.')
    settings = body.model_dump(mode='json', exclude={'preflight_token'})
    if not body.title_page.enabled:
        # Disabled title fields must not leak into the embedded audit metadata.
        settings['title_page'] = {'enabled': False}
    manifest = {'generator_version': GENERATOR_VERSION, 'project_id': str(project_id),
        'manuscript_revision_id': str(revision.id), 'manuscript_content_hash': revision.content_hash,
        'plan_revision_id': str(plan.id) if plan else None, 'plan_content_hash': plan.content_hash if plan else None,
        'evidence': {key: {'content_hash': item.content_hash, 'source_version_id': str(item.source_version_id)} for key, item in evidence_map.items()},
        'sources': {key: {'source_id': str(value.source_id), 'number': value.number, 'metadata': value.metadata_json} for key, value in source_map.items()},
        'settings': settings}
    report.update(can_export=not report['errors'], preflight_token=digest(manifest), manifest=manifest)
    return report, document, plan.document if plan else None, evidence_map, source_map


@router.post('/preflight')
def check_export(project_id: UUID, body: ExportInput, db: DB):
    return preflight(db, project_id, body)[0]


@router.post('/docx')
def download_export(project_id: UUID, body: ExportInput, db: DB):
    from app.docx_export import generate_docx
    if not slots.acquire(blocking=False):
        raise problem(503, 'export_busy', 'Экспорт занят. Повторите позже.')
    try:
        report, document, plan, evidence, sources = preflight(db, project_id, body)
        if not report['can_export']:
            raise HTTPException(422, detail={'code': 'export_blocked', 'message': 'Исправьте ошибки предварительной проверки.', 'report': report})
        if body.preflight_token != report['preflight_token']:
            raise problem(409, 'preflight_required', 'Параметры изменились. Повторите предварительную проверку.')
        output = generate_docx(document, plan, evidence, sources, body, report)
        return Response(output, media_type='application/vnd.openxmlformats-officedocument.wordprocessingml.document',
            headers={'Content-Disposition': f'attachment; filename="research-{body.manuscript_revision_id}.docx"',
                     'X-Export-Input-SHA256': report['preflight_token']})
    finally:
        slots.release()
