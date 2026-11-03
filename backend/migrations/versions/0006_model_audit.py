"""Immutable owner decisions, consent and administrative recovery audit."""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB
revision = '0006_model_audit'
down_revision = '0005_model_jobs'
branch_labels = depends_on = None


def upgrade():
    op.create_table('model_audit',
        sa.Column('id',sa.Uuid(),primary_key=True),
        sa.Column('project_id',sa.Uuid(),sa.ForeignKey('projects.id'),nullable=False),
        sa.Column('job_id',sa.Uuid(),sa.ForeignKey('model_jobs.id')),
        sa.Column('action',sa.String(30),nullable=False),
        sa.Column('request_id',sa.Uuid(),nullable=False),
        sa.Column('actor',sa.String(100),nullable=False),
        sa.Column('request_hash',sa.String(64),nullable=False),
        sa.Column('details',JSONB(),nullable=False),
        sa.Column('created_at',sa.DateTime(timezone=True),server_default=sa.func.now(),nullable=False),
        sa.UniqueConstraint('project_id','action','request_id',name='uq_model_audit_request'))
    op.execute('CREATE TRIGGER immutable_model_audit BEFORE UPDATE OR DELETE ON model_audit '
               'FOR EACH ROW EXECUTE FUNCTION reject_evidence_plan_mutation()')


def downgrade():
    op.drop_table('model_audit')
