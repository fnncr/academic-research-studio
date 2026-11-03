"""Bounded P6 queue, accounting and acceptance receipts (no external adapter)."""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB

revision = '0005_model_jobs'
down_revision = '0004_evidence_plan'
branch_labels = None
depends_on = None


def ref(name, table, primary=False):
    return sa.Column(name, sa.Uuid(), sa.ForeignKey(table + '.id'), primary_key=primary, nullable=False)


def timestamp():
    return sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False)


def upgrade():
    op.create_table('model_budgets', ref('project_id', 'projects', True),
        sa.Column('currency', sa.String(3), nullable=False),
        sa.Column('blocked', sa.Boolean(), nullable=False),
        sa.Column('limit_units', sa.BigInteger(), nullable=False),
        sa.Column('spent_units', sa.BigInteger(), nullable=False),
        sa.Column('reserved_units', sa.BigInteger(), nullable=False),
        sa.CheckConstraint('limit_units >= 0 AND spent_units >= 0 AND reserved_units >= 0 AND spent_units + reserved_units <= limit_units', name='ck_model_budget'))
    op.create_table('model_jobs', sa.Column('id', sa.Uuid(), primary_key=True),
        ref('project_id', 'projects'), sa.Column('request_id', sa.Uuid(), nullable=False),
        sa.Column('fingerprint', sa.String(64), nullable=False),
        ref('brief_revision_id', 'brief_revisions'), ref('manuscript_revision_id', 'manuscript_revisions'),
        ref('plan_revision_id', 'research_plan_revisions'), sa.Column('input_json', JSONB(), nullable=False),
        sa.Column('reserved_units', sa.BigInteger(), nullable=False),
        sa.Column('state', sa.String(20), nullable=False),
        sa.Column('lease_token', sa.Uuid()), sa.Column('lease_until', sa.DateTime(timezone=True)),
        sa.Column('dispatch_id', sa.Uuid()), sa.Column('cancel_requested', sa.Boolean(), nullable=False),
        sa.Column('result', JSONB()), sa.Column('report', JSONB()), timestamp(),
        sa.UniqueConstraint('project_id', 'request_id', name='uq_model_job_request'),
        sa.CheckConstraint("state IN ('queued','leased','dispatching','ambiguous','succeeded','invalid','cancelled','failed')", name='ck_model_job_state'),
        sa.CheckConstraint('reserved_units >= 0', name='ck_model_job_reserve'))
    op.create_index('ix_model_jobs_project_id', 'model_jobs', ['project_id'])
    op.create_index('ix_model_jobs_state', 'model_jobs', ['state'])
    op.create_table('model_settlements', ref('job_id', 'model_jobs', True), ref('project_id', 'projects'),
        sa.Column('charged_units', sa.BigInteger(), nullable=False),
        sa.Column('input_tokens', sa.Integer()), sa.Column('output_tokens', sa.Integer()),
        sa.Column('reason', sa.String(100), nullable=False), timestamp(),
        sa.CheckConstraint('charged_units >= 0 AND input_tokens >= 0 AND output_tokens >= 0', name='ck_model_settlement'))
    op.create_table('model_acceptances', ref('job_id', 'model_jobs', True), ref('project_id', 'projects'),
        sa.Column('request_id', sa.Uuid(), nullable=False), sa.Column('request_hash', sa.String(64), nullable=False),
        ref('manuscript_revision_id', 'manuscript_revisions'), ref('plan_revision_id', 'research_plan_revisions'),
        timestamp(), sa.UniqueConstraint('project_id', 'request_id', name='uq_model_accept_request'))
    for table in ('model_settlements', 'model_acceptances'):
        op.execute(f'CREATE TRIGGER immutable_{table} BEFORE UPDATE OR DELETE ON {table} '
                   'FOR EACH ROW EXECUTE FUNCTION reject_evidence_plan_mutation()')
    op.execute("""CREATE FUNCTION protect_model_job_input() RETURNS trigger LANGUAGE plpgsql AS $$
        BEGIN
          IF TG_OP = 'DELETE' THEN RAISE EXCEPTION 'Model job audit is retained'; END IF;
          IF ROW(NEW.id,NEW.project_id,NEW.request_id,NEW.fingerprint,NEW.input_json,NEW.reserved_units,
                 NEW.brief_revision_id,NEW.manuscript_revision_id,NEW.plan_revision_id,NEW.created_at)
             IS DISTINCT FROM ROW(OLD.id,OLD.project_id,OLD.request_id,OLD.fingerprint,OLD.input_json,OLD.reserved_units,
                 OLD.brief_revision_id,OLD.manuscript_revision_id,OLD.plan_revision_id,OLD.created_at)
          THEN RAISE EXCEPTION 'Model input is immutable'; END IF;
          IF OLD.dispatch_id IS NOT NULL AND NEW.dispatch_id IS DISTINCT FROM OLD.dispatch_id
          THEN RAISE EXCEPTION 'Dispatch identity is immutable'; END IF;
          IF OLD.result IS NOT NULL AND OLD.result <> 'null'::jsonb AND NEW.result IS DISTINCT FROM OLD.result
          THEN RAISE EXCEPTION 'Model result is immutable'; END IF;
          RETURN NEW;
        END; $$""")
    op.execute('CREATE TRIGGER immutable_model_input BEFORE UPDATE OR DELETE ON model_jobs '
               'FOR EACH ROW EXECUTE FUNCTION protect_model_job_input()')


def downgrade():
    # Operator must back up P6 audit/billing rows before deliberately downgrading.
    for table in ('model_acceptances', 'model_settlements', 'model_jobs', 'model_budgets'):
        op.drop_table(table)
    op.execute('DROP FUNCTION protect_model_job_input()')
