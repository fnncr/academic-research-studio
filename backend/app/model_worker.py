"""Supervised PostgreSQL worker. python -m app.model_worker; mock-only registry."""
import logging
import os
import signal
import threading
from dataclasses import asdict

from app.model_contracts import TaskSpec
from app.model_context import ModelProblem, require
from app.model_gateway import configured_gateway, check_ready

log = logging.getLogger(__name__)


def run_once(queue, gateway=None, stop=None):
    gateway = gateway or configured_gateway()
    check_ready(gateway)  # Fail before claiming work if runtime configuration is invalid.
    if stop is not None and stop.is_set(): return None
    claim = queue.claim()
    if claim is None: return None
    project, job, token = claim['project_id'], claim['id'], claim['lease_token']
    stopped = threading.Event()
    def heartbeat():
        while not stopped.wait(15):
            try: queue.heartbeat(project, job, token)
            except Exception:
                log.warning('model_worker_heartbeat_failed')
                return  # Fencing and durable recovery remain authoritative.
    thread = threading.Thread(target=heartbeat, daemon=True)
    thread.start()
    try:
        try:
            data = queue.worker_input(project, job, token)
            spec = TaskSpec.model_validate(data['task'])
            require(asdict(gateway.quote(data['context'], spec)) == data['quote'], 'pricing_changed')
            check_ready(gateway)
        except Exception:
            return queue.predispatch_failure(project, job, token)
        if stop is not None and stop.is_set():
            return queue.release_claim(project, job, token)
        try: dispatched = queue.dispatch(project, job, token)
        except ModelProblem as exc:
            if str(exc) in {'policy_changed', 'budget_blocked'}:
                return queue.predispatch_failure(project, job, token)
            # Cancellation or lease replacement: never send with a stale fence.
            return queue.read(project, job)
        try:
            reply = gateway.generate(data['context'], spec, dispatched['dispatch_id'])
            return queue.finish(project, job, token, dispatched['dispatch_id'], reply)
        except Exception:
            return queue.ambiguous(project, job, token, dispatched['dispatch_id'])
    finally:
        stopped.set(); thread.join(timeout=1)


def serve(queue, stop, gateway=None):
    gateway = gateway or configured_gateway()
    check_ready(gateway)
    delay = 1
    while not stop.is_set():
        try:
            queue.recover()
            if stop.is_set(): break
            result = run_once(queue, gateway, stop)
            delay = 1
            if result is None: stop.wait(1)
        except Exception:
            # No exception text: it may contain document/provider/SQL parameters.
            log.warning('model_worker_iteration_failed')
            stop.wait(delay); delay = min(delay*2, 5)


def main():
    from app.database import project_engine
    from app.model_jobs import ModelJobs
    stop = threading.Event()
    for name in (signal.SIGINT, signal.SIGTERM): signal.signal(name, lambda *_: stop.set())
    engine = None
    try:
        gateway = configured_gateway()
        engine = project_engine(os.environ['DATABASE_URL'])
        serve(ModelJobs(engine), stop, gateway)
    except Exception:
        log.error('model_worker_startup_failed')
        return 1
    finally:
        if engine is not None: engine.dispose()
    return 0


if __name__ == '__main__': raise SystemExit(main())
