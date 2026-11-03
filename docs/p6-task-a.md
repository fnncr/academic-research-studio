# Sol Task A — owner API and supervised mock worker

Implemented on `main` 57eb774 with foundation PR #16 as an explicit dependency.
Architecture and paid-call recovery policy are unchanged. PR #16 must be merged
before this dependent PR; this branch does not merge anything on GitHub.

## Runtime and ownership boundary

The app is a personal installation with **one owner of all projects**, not a
multi-user system. Bind API/frontend to loopback or put the entire application
behind authenticated TLS reverse proxy/VPN. Existing P2–P5 endpoints retain their
personal-deployment contract; the new model endpoints independently require
`Authorization: Bearer <MODEL_OWNER_TOKEN>` on every request, including reads.
Configure a private random token of at least 32 characters in the API environment.
Unset/short token disables model API (503); missing/incorrect token is 401. No
browser storage or UI token handling is added in Task A. Do not expose the older
personal endpoints unauthenticated on the Internet. A multi-user deployment needs
real project ownership/membership and is not supported by this token scheme.

Use existing PostgreSQL configuration. From backend:

```sh
alembic upgrade head
uvicorn app.main:app --host 127.0.0.1
python -m app.model_worker
```

Apply migration 0006_model_audit before starting either API or worker. It adds
immutable, timestamped owner decisions: exact consent fingerprint and disclosure,
budget changes, cancellation, acceptance, reconciliation and explicit unfreeze.
The audit write shares the operation's database transaction. Request UUID/hash
conflicts fail with 409; replays do not duplicate billing or revisions. Token
values and provider keys are never recorded. Downgrade is for backed-up disposable
or explicitly approved databases only; it drops new audit data.

The optional Compose profile `models` adds a supervised worker; migrate the shared
DB first, then `docker compose --profile models up -d model-worker`. The image runs
as an unprivileged user with read-only root filesystem. In managed environments,
package installation must use the inherited proxy and a mounted trusted CA (the
Dockerfile supports BuildKit secret `proxy_ca`); never disable TLS. The existing
PostgreSQL service stays loopback-bound. The worker service does not need the API
owner token. Test startup locally with `python -m app.model_worker` before enabling
restart policies. An unconfigured provider causes safe nonzero startup exit.

## API

Prefix `/api/projects/{project_id}/model-jobs`. Every operation checks the project
scope; job UUIDs from another project return 404. The owner can access every
project in this single-owner installation.

| Method/path | Body/result |
| --- | --- |
| GET /capabilities | mock capability disclosure; no credentials |
| POST /preview | TaskSpec -> fingerprint and exact task/context/quote/disclosure |
| POST / | `{task: TaskSpec, consent: {fingerprint, approved:true}}` -> 202 job; same UUID replays same job with 200 |
| GET / | latest 20 jobs, configurable limit 1–50; no result text or worker fences |
| GET /{id} | state, original reserve, currently held units, actual known charge/token usage, warnings |
| GET /{id}/result | same status plus stored proposal; unverified is never scientific proof |
| POST /{id}/cancel | Decision -> cancellation intent/state; no automatic refund after dispatch |
| POST /{id}/accept | AcceptanceSpec -> stable manuscript/plan receipt; saved-head conflicts remain 409 |
| POST /{id}/reconcile | Decision + charged_units + reason -> settle ambiguity without regeneration |
| GET /budget | USD micro-unit cap, reserved, spent, blocked; null if not configured |
| PUT /budget | Decision + limit_units -> atomic owner budget update |
| POST /budget/unblock | Decision -> explicit reviewed unfreeze; refuses unresolved dispatching/ambiguous jobs |

Decision = `{request_id: UUID, evidence_ref: nonblank string, acknowledged:true}`.
Reconcile reason is `provider_receipt` (owner reviewed actual billing evidence,
including confirmed zero) or `owner_full_reserve` (explicit conservative closure,
charge must equal reserve). An evidence reference is an owner attestation and
traceable receipt identifier, not automatic verification of an invoice. Unknown
usage stays null. Billing above reserve freezes future spending; resolving one
job does not unfreeze the budget. After investigating actual invoices and funding
any liability, record a separate reviewed unfreeze decision. There is no timeout
refund or public worker completion endpoint.

Bodies are bounded to 256 KiB, identity JSON, 15-second upload window; responses
are bounded to 1 MiB. Invalid body errors do not echo user text. State/conflict
errors are 409, unknown scoped IDs 404, invalid fields/charges 422, media 415,
size 413, database unavailability 503. Retry mutations using the exact UUID/body;
a database/network failure is not permission to start a new paid task. Responses
are no-store. Internal lease/dispatch tokens are filtered from every public route.
The preview includes text authorized for this task and a mock-local retention
policy; changing task/context/quote/disclosure changes its fingerprint.

## Worker and gateway capabilities

| Capability | Delivered behavior |
| --- | --- |
| Provider/model | mock / mock-grounded-v1; deterministic synthetic fixture |
| External API / retention | none; no source documents sent outside process |
| Pricing | mock-microunits-v1, not a real provider price |
| Input bound | UTF-8 serialized bytes plus 1024 framing allowance |
| Output / context cap | TaskSpec 256–8000 output tokens; total mock bound 128000 |
| Credentials | no model key required; external provider config rejected before claim |
| External deduplication / TTL | not applicable; one durable dispatch per job |
| Cancellation | intent recorded; completion may still settle cost; proposal not accepted automatically |
| Recovery | expired pre-dispatch lease can requeue; dispatched work becomes ambiguous |

Gateway protocol and configured factory form the replacement seam. No provider
has been approved, so the registry remains mock-only. Arbitrary URLs, SDK retry
policies, paid adapters and silent mock fallback for unknown providers are
rejected. Bounded fixture decoding rejects non-JSON/non-object/nonfinite/oversize
responses. HTTP 429/5xx/timeout fixtures yield ambiguous state without resend.
An actual provider needs owner selection/approval, fixed endpoint, documented
retention, exact tested tokenizer/framing and price bounds, reasoning/output caps,
credential checks before dispatch, TLS/proxy/no redirects and fixture tests before
its TaskSpec literal and registry entry can be enabled. Real billing or provider
idempotency is not claimed by these mock tests.

The worker polls PostgreSQL with bounded backoff (1–5 seconds), sweeps stale leases
and heartbeats active work every 15 seconds. Repricing/configuration failure before
dispatch releases reserve with known zero cost. Failures after durable dispatch
hold budget and never resend. SIGINT/SIGTERM stop new work; a claim stopped before
dispatch requeues with reserve retained. Active mock work finishes before shutdown;
a forced kill leaves durable markers for recovery. A future real adapter needs
bounded HTTP deadlines within the supervisor grace period. Logs contain fixed
error codes, no exception bodies/documents/headers.

## Verification and remaining scope

Run real PostgreSQL tests: `TEST_DATABASE_URL=… python -m pytest -q` from backend;
frontend: `npm --prefix frontend test` and `npm --prefix frontend run build`.
Task A tests cover owner denial, privacy/body bounds, scoped API round trip,
consent/audit immutability, reconciliation/unfreeze, cost/usage, pricing failure,
429/5xx, decoder bounds, actual worker subprocess + SIGTERM and migration drift.
Foundation tests retain races, ambiguity, acceptance conflicts and version tests.
The conditional rich-object test requires PRs #12–14; it is not a pass on main.

No paid calls or live-provider tests were performed. Task B semantic/generation
work and Task C interface remain separate. The Docker image was built with the supported proxy/trusted-CA secret, and a
network-disabled runtime smoke check confirmed nonroot mock startup; this change does not claim a
new office-rendering validation or multi-user authentication deployment.
