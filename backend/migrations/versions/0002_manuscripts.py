"""Immutable structural manuscript revisions; existing projects are untouched."""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = '0002_manuscripts'
down_revision = '0001_projects'
branch_labels = None
depends_on = None


def upgrade():
    op.create_table('manuscript_revisions',
        sa.Column('id', sa.Uuid(), primary_key=True),
        sa.Column('project_id', sa.Uuid(), sa.ForeignKey('projects.id'), nullable=False),
        sa.Column('number', sa.Integer(), nullable=False),
        sa.Column('parent_id', sa.Uuid(), sa.ForeignKey('manuscript_revisions.id')),
        sa.Column('restored_from_id', sa.Uuid(), sa.ForeignKey('manuscript_revisions.id')),
        sa.Column('request_id', sa.Uuid(), nullable=False),
        sa.Column('request_hash', sa.String(64), nullable=False),
        sa.Column('content_hash', sa.String(64), nullable=False),
        sa.Column('document', postgresql.JSONB(), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.UniqueConstraint('project_id', 'number', name='uq_manuscript_project_number'),
        sa.UniqueConstraint('project_id', 'request_id', name='uq_manuscript_request'),
        sa.CheckConstraint('number > 0', name='ck_manuscript_number_positive'))
    op.create_index('ix_manuscript_revisions_project_id', 'manuscript_revisions', ['project_id'])
    op.execute("""CREATE FUNCTION reject_manuscript_mutation() RETURNS trigger LANGUAGE plpgsql AS $$
    BEGIN RAISE EXCEPTION 'Manuscript revisions are immutable'; END; $$""")
    op.execute('CREATE TRIGGER immutable_manuscript BEFORE UPDATE OR DELETE ON manuscript_revisions '
               'FOR EACH ROW EXECUTE FUNCTION reject_manuscript_mutation()')


def downgrade():
    # Destructive for manuscript history. Only on a disposable DB or after backup.
    op.drop_table('manuscript_revisions')
    op.execute('DROP FUNCTION reject_manuscript_mutation()')
