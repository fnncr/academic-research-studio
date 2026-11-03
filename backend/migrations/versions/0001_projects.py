"""Projects and append-only teacher requirement revisions."""
from alembic import op
import sqlalchemy as sa

revision = '0001_projects'
down_revision = None
branch_labels = None
depends_on = None


def upgrade():
    op.create_table('projects',
        sa.Column('id', sa.Uuid(), primary_key=True),
        sa.Column('title', sa.String(200), nullable=False),
        sa.Column('research_question', sa.Text(), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False))
    op.create_table('brief_revisions',
        sa.Column('id', sa.Uuid(), primary_key=True),
        sa.Column('project_id', sa.Uuid(), sa.ForeignKey('projects.id'), nullable=False),
        sa.Column('number', sa.Integer(), nullable=False),
        sa.Column('requirements', sa.Text(), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.UniqueConstraint('project_id', 'number', name='uq_brief_project_number'),
        sa.CheckConstraint('number > 0', name='ck_brief_number_positive'))
    op.create_index('ix_brief_revisions_project_id', 'brief_revisions', ['project_id'])
    op.execute("""CREATE FUNCTION reject_brief_update() RETURNS trigger LANGUAGE plpgsql AS $$
    BEGIN RAISE EXCEPTION 'Brief revisions are immutable'; END; $$""")
    op.execute('CREATE TRIGGER immutable_brief BEFORE UPDATE ON brief_revisions FOR EACH ROW EXECUTE FUNCTION reject_brief_update()')


def downgrade():
    op.drop_table('brief_revisions')
    op.execute('DROP FUNCTION reject_brief_update()')
    op.drop_table('projects')
