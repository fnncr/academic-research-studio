"""Transactional P6 kernel. Every public method owns a short transaction.

The owner-only HTTP layer delegates to this service. Only MockGateway is
enabled; external adapters require separate provider approval. Never call a provider while holding a database lock.
"""
import json
from copy import deepcopy
from dataclasses import asdict
from datetime import timedelta
from uuid import UUID, uuid4, uuid5

from pydantic import ValidationError
from sqlalchemy import select, func
from sqlalchemy.orm import Session

from app.evidence import MAX_BODY as PLAN_MAX_BODY, latest_plan, validate_plan
from app.evidence_schema import SavePlan
from app.manuscript_schema import ManuscriptDocument
from app.manuscripts import MAX_BODY, current_revision, digest
from app.model_context import ModelProblem, SYSTEM_RULES, assemble_context, require, validate_proposal
from app.model_contracts import AcceptanceSpec, Consent, TaskSpec
from app.model_gateway import MockGateway, gateway_for, check_ready, GatewayUnavailable
from app.models import (ModelAudit, ModelAcceptance, ModelBudget, ModelJob, ModelSettlement,
                        ManuscriptRevision, ResearchPlanRevision, PlanEvidenceReference)
from app.projects import get_project

TERMINAL = {'succeeded', 'invalid', 'cancelled', 'failed'}


def view(job):
    return {'id': job.id, 'project_id': job.project_id, 'state': job.state,
            'fingerprint': job.fingerprint, 'reserved_units': job.reserved_units,
            'lease_token': job.lease_token, 'dispatch_id': job.dispatch_id,
            'cancel_requested': job.cancel_requested, 'result': deepcopy(job.result),
            'report': deepcopy(job.report)}


def receipt_view(receipt):
    return {'job_id': receipt.job_id, 'manuscript_revision_id': receipt.manuscript_revision_id,
            'plan_revision_id': receipt.plan_revision_id}


class ModelJobs:
    def __init__(self, engine):
        self.engine = engine

    def _lock(self, db, project_id, job_id):
        get_project(db, project_id, lock=True)
        job = db.scalar(select(ModelJob).where(ModelJob.project_id == project_id,
                                               ModelJob.id == job_id).with_for_update())
        require(job is not None, 'not_found')
        return job

    def _preview(self, db, project_id, spec):
        packet = assemble_context(db, project_id, spec)
        if spec.provider == 'openai':
            pass  # Real generation has no template-composition admission requirement.
        elif spec.kind == 'writing':
            from app.grounded_writing import compose
            compose(packet, spec)  # Output capacity fails before reserving a budget.
        else:
            from app.semantic_review import local_review
            local_review(packet, spec)
        quote = asdict(gateway_for(spec.provider).quote(packet, spec))
        from app.model_adapters.openai_chat import DISCLOSURE
        data = {'task': spec.model_dump(mode='json'), 'context': packet, 'quote': quote,
                'disclosure': DISCLOSURE if spec.provider == 'openai' else 'mock-local-v1: no external transmission or provider retention'}
        return {'fingerprint': digest(data), 'input': data}

    def preview(self, project_id: UUID, spec: TaskSpec):
        with Session(self.engine) as db:
            return self._preview(db, project_id, spec)

    def configure_budget(self, project_id: UUID, limit_units: int):
        require(type(limit_units) is int and 0 <= limit_units <= 10**12, 'invalid_budget')
        with Session(self.engine) as db, db.begin():
            get_project(db, project_id, lock=True)
            budget = db.get(ModelBudget, project_id)
            if budget:
                require(limit_units >= budget.spent_units + budget.reserved_units, 'budget_exhausted')
                budget.limit_units = limit_units
            else:
                db.add(ModelBudget(project_id=project_id, currency='USD', limit_units=limit_units,
                                   spent_units=0, reserved_units=0))

    def enqueue(self, project_id: UUID, spec: TaskSpec, consent: Consent, actor=None, with_creation=False):
        with Session(self.engine) as db, db.begin():
            get_project(db, project_id, lock=True)
            preview = self._preview(db, project_id, spec)
            require(consent.approved and consent.fingerprint == preview['fingerprint'], 'consent_mismatch')
            previous = db.scalar(select(ModelJob).where(ModelJob.project_id == project_id,
                                                        ModelJob.request_id == spec.request_id))
            if previous:
                require(previous.fingerprint == preview['fingerprint'], 'request_conflict')
                if actor: self._audit(db, project_id, previous.id, 'consent', spec.request_id, actor,
                    {'fingerprint': preview['fingerprint'], 'disclosure': preview['input']['disclosure']})
                return dict(view(previous), created=False) if with_creation else view(previous)
            if spec.provider == 'openai':
                try:
                    gateway=gateway_for(spec.provider); check_ready(gateway)
                    require(preview['input']['quote']['max_units'] <= gateway.ready(), 'call_budget_exceeded')
                except GatewayUnavailable: raise ModelProblem('provider_configuration_unavailable') from None
            budget = db.scalar(select(ModelBudget).where(ModelBudget.project_id == project_id).with_for_update())
            units = preview['input']['quote']['max_units']
            require(budget is not None and budget.currency == preview['input']['quote']['currency'] and
                    not budget.blocked and budget.limit_units - budget.spent_units - budget.reserved_units >= units, 'budget_exhausted')
            budget.reserved_units += units
            job = ModelJob(project_id=project_id, request_id=spec.request_id,
                fingerprint=preview['fingerprint'], brief_revision_id=spec.brief_revision_id,
                manuscript_revision_id=spec.manuscript_revision_id, plan_revision_id=spec.plan_revision_id,
                input_json=preview['input'], reserved_units=units, state='queued', cancel_requested=False)
            db.add(job); db.flush()
            if actor: self._audit(db, project_id, job.id, 'consent', spec.request_id, actor,
                {'fingerprint': preview['fingerprint'], 'disclosure': preview['input']['disclosure']})
            return dict(view(job), created=True) if with_creation else view(job)

    def read(self, project_id: UUID, job_id: UUID):
        with Session(self.engine) as db:
            job = db.scalar(select(ModelJob).where(ModelJob.project_id == project_id, ModelJob.id == job_id))
            require(job is not None, 'not_found')
            result = view(job)
            result['task'] = job.input_json['task']
            receipt = db.get(ModelAcceptance, job.id)
            result['acceptance'] = receipt_view(receipt) if receipt else None
            settled = db.get(ModelSettlement, job.id)
            result['charged_units'] = settled.charged_units if settled else None
            result['held_units'] = 0 if settled else job.reserved_units
            result['usage'] = {'input_tokens': settled.input_tokens, 'output_tokens': settled.output_tokens} if settled else None
            return result

    def claim(self):
        with Session(self.engine) as db, db.begin():
            job = db.scalar(select(ModelJob).where(ModelJob.state == 'queued')
                            .order_by(ModelJob.created_at, ModelJob.id).with_for_update(skip_locked=True).limit(1))
            if not job: return None
            job.state = 'leased'; job.lease_token = uuid4()
            job.lease_until = db.scalar(select(func.clock_timestamp())) + timedelta(seconds=60)
            return view(job)

    def heartbeat(self, project_id, job_id, token):
        with Session(self.engine) as db, db.begin():
            job = self._lock(db, project_id, job_id)
            now = db.scalar(select(func.clock_timestamp()))
            require(job.state in {'leased', 'dispatching'} and job.lease_token == token and job.lease_until > now, 'stale_lease')
            job.lease_until = now + timedelta(seconds=60)

    def dispatch(self, project_id, job_id, token):
        with Session(self.engine) as db, db.begin():
            job = self._lock(db, project_id, job_id)
            require(job.state == 'leased' and job.lease_token == token and
                    job.lease_until > db.scalar(select(func.clock_timestamp())) and not job.cancel_requested, 'stale_lease')
            require(job.input_json['context']['system_hash'] == digest(SYSTEM_RULES), 'policy_changed')
            budget = db.get(ModelBudget, project_id)
            require(not budget.blocked, 'budget_blocked')
            job.state = 'dispatching'; job.dispatch_id = uuid4()
            # This transaction MUST commit before handing a payload to a provider.
            return {**view(job), 'input': deepcopy(job.input_json)}

    def ambiguous(self, project_id, job_id, token, dispatch_id):
        with Session(self.engine) as db, db.begin():
            job = self._lock(db, project_id, job_id)
            require(job.lease_token == token and job.dispatch_id == dispatch_id, 'stale_lease')
            if job.state == 'dispatching': job.state = 'ambiguous'
            return view(job)

    def recover(self):
        # Candidate discovery holds no locks; recheck each candidate under the
        # normal lock order. Multiple sweepers are safe.
        with Session(self.engine) as db:
            candidates = list(db.execute(select(ModelJob.project_id, ModelJob.id).where(
                ModelJob.state.in_(['leased', 'dispatching']), ModelJob.lease_until <= func.clock_timestamp()).limit(100)))
        for project_id, job_id in candidates:
            with Session(self.engine) as db, db.begin():
                job = self._lock(db, project_id, job_id)
                if job.state not in {'leased', 'dispatching'} or job.lease_until > db.scalar(select(func.clock_timestamp())): continue
                if job.state == 'leased':
                    job.state = 'queued'; job.lease_token = None; job.lease_until = None
                else: job.state = 'ambiguous'

    def _settle(self, db, job, units, reason, input_tokens=None, output_tokens=None):
        require(type(units) is int and 0 <= units <= job.reserved_units, 'invalid_charge')
        require((input_tokens is None and output_tokens is None) or
                (type(input_tokens) is int and type(output_tokens) is int and
                 0 <= input_tokens <= 1000000 and 0 <= output_tokens <= 1000000), 'invalid_usage')
        require(db.get(ModelSettlement, job.id) is None, 'already_settled')
        budget = db.scalar(select(ModelBudget).where(ModelBudget.project_id == job.project_id).with_for_update())
        budget.reserved_units -= job.reserved_units; budget.spent_units += units
        db.add(ModelSettlement(job_id=job.id, project_id=job.project_id, charged_units=units,
            input_tokens=input_tokens, output_tokens=output_tokens, reason=reason))

    def finish(self, project_id, job_id, token, dispatch_id, reply):
        with Session(self.engine) as db, db.begin():
            job = self._lock(db, project_id, job_id)
            require(job.lease_token == token and job.dispatch_id == dispatch_id, 'stale_lease')
            if job.state in TERMINAL: return view(job)  # Duplicate delivery cannot debit twice.
            require(job.state in {'dispatching', 'ambiguous'}, 'invalid_transition')
            if type(reply.charged_units) is not int or not 0 <= reply.charged_units <= job.reserved_units:
                job.state = 'ambiguous'; job.report = {'code': 'billing_bound_violation'}
                db.get(ModelBudget, project_id).blocked = True
                return view(job)
            spec = TaskSpec.model_validate(job.input_json['task'])
            if job.cancel_requested:
                job.state = 'cancelled'
                job.report = {'code': 'cancelled_after_dispatch'}
            else:
                try:
                    if spec.kind == 'semantic_review':
                        from app.semantic_review import validate_review
                        require(assemble_context(db, project_id, spec) == job.input_json['context'], 'context_changed')
                        proposal, report = validate_review(job.input_json['context'], reply.result)
                        require(proposal.reviewer_kind == 'model', 'model_reviewer_required')
                    else:
                        proposal, report = validate_proposal(db, project_id, spec, job.input_json['context'], reply.result)
                    require(reply.input_tokens <= job.input_json['quote']['input_token_bound'] and
                            reply.output_tokens <= spec.max_output_tokens, 'usage_limit_exceeded')
                    report['execution'] = {'quote': job.input_json['quote'],
                        'input_tokens': reply.input_tokens, 'output_tokens': reply.output_tokens}
                    job.result = proposal.model_dump(mode='json'); job.report = report; job.state = 'succeeded'
                except (ValueError, ValidationError) as exc:
                    job.state = 'invalid'; job.report = {'code': 'invalid_result', 'semantic': 'uncertain',
                        'validation_code': str(exc) if isinstance(exc, ModelProblem) else 'schema_mismatch'}
            self._settle(db, job, reply.charged_units, 'provider_response', reply.input_tokens, reply.output_tokens)
            return view(job)

    def cancel(self, project_id, job_id, actor=None, decision=None):
        with Session(self.engine) as db, db.begin():
            job = self._lock(db, project_id, job_id)
            if actor: self._audit(db, project_id, job.id, 'cancel', decision.request_id, actor, decision.model_dump(mode='json'))
            require(db.get(ModelAcceptance, job.id) is None, 'already_accepted')
            job.cancel_requested = True
            if job.state in {'queued', 'leased'}:
                self._settle(db, job, 0, 'cancelled_before_dispatch', 0, 0); job.state = 'cancelled'
            elif job.state == 'succeeded': job.state = 'cancelled'
            return view(job)

    def reconcile(self, project_id, job_id, charged_units, reason, actor=None, decision=None):
        """Administrative boundary: requires owner decision/evidence, never resend.

        Only two bounded resolution codes; HTTP actor/audit integration is deferred.
        Full-reserve closure is allowed without claiming a known provider invoice.
        """
        require(reason in {'provider_receipt', 'owner_full_reserve'}, 'invalid_resolution')
        with Session(self.engine) as db, db.begin():
            job = self._lock(db, project_id, job_id)
            if actor: self._audit(db, project_id, job.id, 'reconcile', decision.request_id, actor, decision.model_dump(mode='json'))
            existing = db.get(ModelSettlement, job.id)
            if existing:
                require(existing.charged_units == charged_units and existing.reason == reason, 'request_conflict')
                return view(job)
            require(job.state == 'ambiguous', 'invalid_transition')
            require(reason != 'owner_full_reserve' or charged_units == job.reserved_units, 'invalid_charge')
            self._settle(db, job, charged_units, reason)
            job.state = 'cancelled' if job.cancel_requested else 'failed'
            job.report = {'code': 'resolved_without_result', 'resolution': reason}
            return view(job)

    def accept(self, project_id, job_id, request: AcceptanceSpec, actor=None):
        with Session(self.engine) as db, db.begin():
            job = self._lock(db, project_id, job_id)
            if actor: self._audit(db, project_id, job.id, 'accept', request.request_id, actor, request.model_dump(mode='json'))
            fingerprint = digest(request.model_dump(mode='json'))
            previous = db.get(ModelAcceptance, job_id)
            if previous:
                require(previous.request_hash == fingerprint, 'request_conflict')
                return receipt_view(previous)
            used = db.scalar(select(ModelAcceptance).where(ModelAcceptance.project_id == project_id,
                                                           ModelAcceptance.request_id == request.request_id))
            require(used is None, 'request_conflict')
            require(job.state == 'succeeded' and not job.cancel_requested and job.result is not None, 'invalid_transition')
            require(request.review_acknowledged and request.result_hash == digest(job.result), 'review_required')
            current = current_revision(db, project_id); plan = latest_plan(db, project_id)
            require(current is not None and plan is not None and
                request.manuscript_revision_id == current.id == job.manuscript_revision_id and
                request.plan_revision_id == plan.id == job.plan_revision_id, 'revision_conflict')
            spec = TaskSpec.model_validate(job.input_json['task'])
            require(spec.kind == 'writing', 'review_not_acceptable_as_text')
            proposal, _ = validate_proposal(db, project_id, spec, job.input_json['context'], job.result)
            document = deepcopy(current.document)
            document['blocks'].append({'id': str(uuid5(job.id, 'heading')), 'type': 'heading', 'text': spec.title, 'level': 1})
            for i, paragraph in enumerate(proposal.paragraphs):
                document['blocks'].append({'id': str(uuid5(job.id, f'paragraph:{i}')), 'type': 'paragraph',
                                           'text': paragraph, 'marks': [], 'origin': 'manual', 'page': None})
            # Validate without reserializing old nodes/defaults. AI origin is recorded
            # in the immutable acceptance receipt, not a new P2 enum value.
            ManuscriptDocument.model_validate(document)
            restore_envelope = {'document': document, 'request_id': str(uuid4()),
                'base_revision_id': str(current.id), 'restored_from_id': str(current.id)}
            require(len(json.dumps(restore_envelope, ensure_ascii=False).encode('utf-8')) <= MAX_BODY, 'manuscript_too_large')
            revision = ManuscriptRevision(project_id=project_id, number=current.number + 1, parent_id=current.id,
                request_id=uuid5(job.id, 'manuscript-save'), request_hash=fingerprint,
                content_hash=digest(document), document=document)
            db.add(revision); db.flush()
            plan_doc = deepcopy(plan.document)
            for i, citation in enumerate(proposal.citations):
                plan_doc['citations'].append({'id': str(uuid5(job.id, f'citation:{i}')),
                    'claim_id': str(citation.claim_id), 'evidence_id': str(citation.evidence_id),
                    'block_id': str(uuid5(job.id, f'paragraph:{citation.paragraph}')),
                    'selection': {'start': citation.start, 'end': citation.end, 'quote': citation.quote}, 'kind': citation.kind})
            plan_request = SavePlan(request_id=uuid5(job.id, 'plan-save'), base_revision_id=plan.id,
                                   manuscript_revision_id=revision.id, document=plan_doc)
            require(len(plan_request.model_dump_json().encode('utf-8')) <= PLAN_MAX_BODY, 'plan_too_large')
            evidence_ids = validate_plan(db, project_id, plan_request)
            new_plan = ResearchPlanRevision(project_id=project_id, number=plan.number + 1, parent_id=plan.id,
                manuscript_revision_id=revision.id, request_id=plan_request.request_id, request_hash=fingerprint,
                content_hash=digest({'manuscript_revision_id': str(revision.id), 'document': plan_doc}), document=plan_doc)
            db.add(new_plan); db.flush()
            for evidence_id in evidence_ids:
                db.add(PlanEvidenceReference(plan_revision_id=new_plan.id, evidence_id=evidence_id))
            receipt = ModelAcceptance(job_id=job.id, project_id=project_id, request_id=request.request_id,
                request_hash=fingerprint, manuscript_revision_id=revision.id, plan_revision_id=new_plan.id)
            db.add(receipt); db.flush()
            return receipt_view(receipt)


    def _audit(self, db, project_id, job_id, action, request_id, actor, details):
        fingerprint = digest({'actor': actor, 'job_id': str(job_id), 'details': details})
        old = db.scalar(select(ModelAudit).where(ModelAudit.project_id == project_id,
            ModelAudit.action == action, ModelAudit.request_id == request_id))
        if old:
            require(old.request_hash == fingerprint, 'request_conflict')
            return True
        db.add(ModelAudit(project_id=project_id, job_id=job_id, action=action,
            request_id=request_id, actor=actor, request_hash=fingerprint, details=details))
        return False

    def budget(self, project_id):
        with Session(self.engine) as db:
            get_project(db, project_id)
            b = db.get(ModelBudget, project_id)
            return {'currency': b.currency, 'limit_units': b.limit_units, 'reserved_units': b.reserved_units,
                    'spent_units': b.spent_units, 'blocked': b.blocked} if b else None

    def administer_budget(self, project_id, decision, actor, unblock=False):
        with Session(self.engine) as db, db.begin():
            get_project(db, project_id, lock=True)
            action = 'unblock' if unblock else 'budget'
            if self._audit(db, project_id, None, action, decision.request_id, actor, decision.model_dump(mode='json')):
                return
            b = db.get(ModelBudget, project_id)
            if unblock:
                require(b is not None, 'not_found')
                unresolved = db.scalar(select(ModelJob.id).where(ModelJob.project_id == project_id,
                    ModelJob.state.in_(['dispatching', 'ambiguous'])).limit(1))
                require(unresolved is None, 'ambiguous_outcome')
                b.blocked = False
            elif b:
                require(decision.limit_units >= b.spent_units + b.reserved_units, 'budget_exhausted')
                b.limit_units = decision.limit_units
            else:
                db.add(ModelBudget(project_id=project_id, currency='USD', limit_units=decision.limit_units,
                                   reserved_units=0, spent_units=0, blocked=False))

    def list_jobs(self, project_id, limit=20):
        with Session(self.engine) as db:
            get_project(db, project_id)
            return [view(j) for j in db.scalars(select(ModelJob).where(ModelJob.project_id == project_id)
                    .order_by(ModelJob.created_at.desc(), ModelJob.id).limit(limit))]

    def predispatch_failure(self, project_id, job_id, token):
        with Session(self.engine) as db, db.begin():
            job = self._lock(db, project_id, job_id)
            require(job.state == 'leased' and job.lease_token == token and job.dispatch_id is None, 'stale_lease')
            self._settle(db, job, 0, 'configuration_failure', 0, 0)
            job.state = 'failed'; job.report = {'code': 'gateway_unavailable_before_dispatch'}
            return view(job)

    def worker_input(self, project_id, job_id, token):
        with Session(self.engine) as db:
            job = db.scalar(select(ModelJob).where(ModelJob.project_id == project_id, ModelJob.id == job_id))
            require(job is not None and job.state == 'leased' and job.lease_token == token, 'stale_lease')
            return deepcopy(job.input_json)


    def release_claim(self, project_id, job_id, token):
        with Session(self.engine) as db, db.begin():
            job = self._lock(db, project_id, job_id)
            require(job.state == 'leased' and job.lease_token == token and job.dispatch_id is None, 'stale_lease')
            job.state = 'queued'; job.lease_token = None; job.lease_until = None
            return view(job)


    def human_review(self, project_id, source_job_id, submission, actor):
        from app.semantic_review import validate_review
        with Session(self.engine) as db, db.begin():
            source = self._lock(db, project_id, source_job_id)
            fingerprint = digest({'subject_job_id': str(source_job_id), 'actor': actor,
                                  'submission': submission.model_dump(mode='json')})
            old = db.scalar(select(ModelJob).where(ModelJob.project_id==project_id, ModelJob.request_id==submission.request_id))
            if old:
                require(old.fingerprint==fingerprint, 'request_conflict')
                return view(old)
            task = dict(source.input_json['task'], request_id=str(submission.request_id),
                kind='semantic_review', review_job_id=str(source.id), review_result_hash=digest(source.result))
            spec = TaskSpec.model_validate(task)
            packet = assemble_context(db, project_id, spec)
            require(submission.review.reviewer_kind == 'human', 'human_reviewer_required')
            review, report = validate_review(packet, submission.review.model_dump(mode='json'))
            record = ModelJob(project_id=project_id, request_id=submission.request_id, fingerprint=fingerprint,
                brief_revision_id=spec.brief_revision_id, manuscript_revision_id=spec.manuscript_revision_id,
                plan_revision_id=spec.plan_revision_id, input_json={'task':spec.model_dump(mode='json'),
                    'context':packet, 'disclosure':'human-local-v1: no model invocation'},
                reserved_units=0, state='succeeded', cancel_requested=False,
                result=review.model_dump(mode='json'), report=report)
            db.add(record); db.flush()
            db.add(ModelSettlement(job_id=record.id, project_id=project_id, charged_units=0,
                input_tokens=0, output_tokens=0, reason='human_review_no_model'))
            self._audit(db, project_id, record.id, 'human_review', submission.request_id, actor,
                {'subject_job_id':str(source.id), 'result_hash':review.result_hash, 'review_hash':digest(record.result)})
            return view(record)


    def by_request(self, project_id, request_id):
        with Session(self.engine) as db:
            job = db.scalar(select(ModelJob).where(ModelJob.project_id==project_id, ModelJob.request_id==request_id))
            require(job is not None, 'not_found')
            return self.read(project_id, job.id)
