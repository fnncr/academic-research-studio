"""Read-only P7 preview for an existing immutable manuscript revision.

Single-owner installation: uses the same owner boundary as P6.
No provider calls, no document mutations, no fake percent score.
"""
from uuid import UUID
from fastapi import APIRouter, Depends
from app.model_api import owner
from app.manuscripts import scoped_revision
from app.projects import DB, get_project
from app.editorial_review_v2 import inspect
from app.manuscript_schema import ManuscriptDocument

router = APIRouter(prefix="/api/projects/{project_id}/editorial",
                   tags=["editorial-review"], dependencies=[Depends(owner)])


@router.get("/revisions/{revision_id}/preview")
def preview(project_id: UUID, revision_id: UUID, db: DB):
    get_project(db, project_id)
    revision = scoped_revision(db, project_id, revision_id)
    document = ManuscriptDocument.model_validate(revision.document)
    return inspect(document, revision.id)
