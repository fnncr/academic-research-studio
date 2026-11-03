"""Immutable excerpts and atomic claim/citation plan snapshots."""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB

revision = '0004_evidence_plan'
down_revision = '0003_sources'
branch_labels = None
depends_on = None


def upgrade():
    op.create_table('evidence',
        sa.Column('id', sa.Uuid(), primary_key=True),
        sa.Column('project_id', sa.Uuid(), sa.ForeignKey('projects.id'), nullable=False),
        sa.Column('source_version_id', sa.Uuid(), sa.ForeignKey('source_versions.id'), nullable=False),
        sa.Column('request_id', sa.Uuid(), nullable=False),
        sa.Column('request_hash', sa.String(64), nullable=False),
        sa.Column('content_hash', sa.String(64), nullable=False),
        sa.Column('content', JSONB(), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.UniqueConstraint('project_id', 'request_id', name='uq_evidence_request'))
    op.create_index('ix_evidence_project_id', 'evidence', ['project_id'])
    op.create_table('research_plan_revisions',
        sa.Column('id', sa.Uuid(), primary_key=True),
        sa.Column('project_id', sa.Uuid(), sa.ForeignKey('projects.id'), nullable=False),
        sa.Column('manuscript_revision_id', sa.Uuid(), sa.ForeignKey('manuscript_revisions.id'), nullable=False),
        sa.Column('parent_id', sa.Uuid(), sa.ForeignKey('research_plan_revisions.id')),
        sa.Column('number', sa.Integer(), nullable=False),
        sa.Column('request_id', sa.Uuid(), nullable=False),
        sa.Column('request_hash', sa.String(64), nullable=False),
        sa.Column('content_hash', sa.String(64), nullable=False),
        sa.Column('document', JSONB(), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.UniqueConstraint('project_id', 'number', name='uq_plan_number'),
        sa.UniqueConstraint('project_id', 'request_id', name='uq_plan_request'),
        sa.CheckConstraint('number > 0', name='ck_plan_number'))
    op.create_index('ix_research_plan_revisions_project_id', 'research_plan_revisions', ['project_id'])
    op.create_table('plan_evidence_references',
        sa.Column('plan_revision_id', sa.Uuid(), sa.ForeignKey('research_plan_revisions.id'), primary_key=True),
        sa.Column('evidence_id', sa.Uuid(), sa.ForeignKey('evidence.id'), primary_key=True))
    op.execute("""CREATE FUNCTION reject_evidence_plan_mutation() RETURNS trigger LANGUAGE plpgsql AS $$
        BEGIN RAISE EXCEPTION 'Evidence and plan history are immutable'; END; $$""")
    for table in ('evidence', 'research_plan_revisions', 'plan_evidence_references'):
        op.execute(f'CREATE TRIGGER immutable_{table} BEFORE UPDATE OR DELETE ON {table} '
                   'FOR EACH ROW EXECUTE FUNCTION reject_evidence_plan_mutation()')


def downgrade():
    for table in ('plan_evidence_references', 'research_plan_revisions', 'evidence'):
        op.drop_table(table)
    op.execute('DROP FUNCTION reject_evidence_plan_mutation()')
