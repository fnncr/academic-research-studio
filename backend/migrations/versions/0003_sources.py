"""Source versions, current identifier ownership and persisted search results."""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB

revision = '0003_sources'
down_revision = '0002_manuscripts'
branch_labels = None
depends_on = None


def upgrade():
    op.create_table('sources',
        sa.Column('id', sa.Uuid(), primary_key=True),
        sa.Column('project_id', sa.Uuid(), sa.ForeignKey('projects.id'), nullable=False),
        sa.Column('request_id', sa.Uuid(), nullable=False),
        sa.Column('request_hash', sa.String(64), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.UniqueConstraint('project_id', 'request_id', name='uq_source_request'))
    op.create_index('ix_sources_project_id', 'sources', ['project_id'])
    op.create_table('source_versions',
        sa.Column('id', sa.Uuid(), primary_key=True),
        sa.Column('source_id', sa.Uuid(), sa.ForeignKey('sources.id'), nullable=False),
        sa.Column('number', sa.Integer(), nullable=False),
        sa.Column('request_id', sa.Uuid(), nullable=False),
        sa.Column('request_hash', sa.String(64), nullable=False),
        sa.Column('metadata_json', JSONB(), nullable=False),
        sa.Column('provenance', JSONB(), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.UniqueConstraint('source_id', 'number', name='uq_source_version_number'),
        sa.UniqueConstraint('source_id', 'request_id', name='uq_source_version_request'),
        sa.CheckConstraint('number > 0', name='ck_source_version_number'))
    op.create_index('ix_source_versions_source_id', 'source_versions', ['source_id'])
    op.create_table('source_identifiers',
        sa.Column('project_id', sa.Uuid(), sa.ForeignKey('projects.id'), primary_key=True),
        sa.Column('kind', sa.String(4), primary_key=True),
        sa.Column('value', sa.String(255), primary_key=True),
        sa.Column('source_id', sa.Uuid(), sa.ForeignKey('sources.id'), nullable=False))
    op.create_index('ix_source_identifiers_source_id', 'source_identifiers', ['source_id'])
    op.create_table('search_runs',
        sa.Column('id', sa.Uuid(), primary_key=True),
        sa.Column('project_id', sa.Uuid(), sa.ForeignKey('projects.id'), nullable=False),
        sa.Column('request_id', sa.Uuid(), nullable=False),
        sa.Column('request_hash', sa.String(64), nullable=False),
        sa.Column('request_json', JSONB(), nullable=False),
        sa.Column('source_version_id', sa.Uuid(), sa.ForeignKey('source_versions.id')),
        sa.Column('status', sa.String(20), nullable=False),
        sa.Column('results', JSONB(), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.UniqueConstraint('project_id', 'request_id', name='uq_search_request'))
    op.create_index('ix_search_runs_project_id', 'search_runs', ['project_id'])
    op.execute("""CREATE FUNCTION reject_source_version_mutation() RETURNS trigger LANGUAGE plpgsql AS $$
    BEGIN RAISE EXCEPTION 'Source versions are immutable'; END; $$""")
    op.execute('CREATE TRIGGER immutable_source_version BEFORE UPDATE OR DELETE ON source_versions '
               'FOR EACH ROW EXECUTE FUNCTION reject_source_version_mutation()')


def downgrade():
    op.drop_table('search_runs')
    op.drop_table('source_identifiers')
    op.drop_table('source_versions')
    op.execute('DROP FUNCTION reject_source_version_mutation()')
    op.drop_table('sources')
