"""One mock-only worker iteration; supervisor/polling and real adapters deferred."""
from app.model_contracts import TaskSpec
from app.model_gateway import MockGateway


def run_once(queue, gateway=None):
    gateway = gateway or MockGateway()
    # Explicit allowlist; adding an external adapter is a reviewed follow-up.
    if not isinstance(gateway, MockGateway): raise ValueError('Only mock gateway is enabled')
    claim = queue.claim()
    if claim is None: return None
    project, job, token = claim['project_id'], claim['id'], claim['lease_token']
    dispatched = queue.dispatch(project, job, token)
    try:
        reply = gateway.generate(dispatched['input']['context'],
            TaskSpec.model_validate(dispatched['input']['task']), dispatched['dispatch_id'])
        return queue.finish(project, job, token, dispatched['dispatch_id'], reply)
    except Exception:
        # Includes network timeout, decode/validation bugs and persistence failure.
        # A second DB failure leaves durable dispatching for the recovery sweep.
        return queue.ambiguous(project, job, token, dispatched['dispatch_id'])
