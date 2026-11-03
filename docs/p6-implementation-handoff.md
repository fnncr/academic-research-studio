# P6 implementation handoff for GPT-6.1 Sol

Read AGENTS.md, [P6 specification](p6-architecture.md),
[ADR 0006](adr/0006-model-jobs-and-grounded-proposals.md), and the files/tests named
below before changing code. Do not redesign these decisions or replace P2–P5.
They are the implemented contract submitted for owner review, not a claim of
owner approval or complete P6. Use one task branch/PR at a time; never merge
without owner permission. No paid calls without explicit authorization.

## Foundation delivered / boundaries

- `model_contracts.py`: TaskSpec, Consent, Proposal, SemanticReview, AcceptanceSpec.
- `model_context.py`: scoped complete selected-claim closure; snapshots, exact
  source/version/UTF-16 checks; report keeps semantic status uncertain.
- `model_gateway.py`: Gateway protocol and bounded deterministic mock; system/data
  messages; mock quote in integer USD micro-units. No real network adapters.
- `model_jobs.py`: transaction-owning service, budget reservation, SKIP LOCKED
  leases/fences, ambiguity/recovery/cancel, settlement, atomic append acceptance.
- `model_worker.py`: one mock iteration. No production daemon/supervisor yet.
- Migration `0005_model_jobs`: four tables, checks, immutable input/result and
  settlement/acceptance receipts. No change to P2–P4 models or schema versions.
- `test_model_jobs.py`: actual PostgreSQL races, faults and compatibility tests.

The architecture PR is `feat/p6-architecture` (#15). The implementation branch is
`feat/p6-critical-foundation`, based on that PR. Start dependent work from the
foundation HEAD until both are merged; afterward rebase onto current main.
Pending rich-object PRs #12–14 are independent compatibility dependencies. Do not
cherry-pick them silently into a P6 feature PR. A conditional integration test
runs when they are present. Never interpret skipped compatibility as passed.

Internal ModelJobs methods assume a trusted application caller and are NOT a
public authorization boundary. No AI endpoints are registered yet. ModelGateway
is mock-only; TaskSpec intentionally rejects unknown provider/model names.
SemanticReview is a contract, not an implemented model reviewer. All existing
P2–P5 manual workflows remain available without model keys.

## Sol Task A — Model Gateway and infrastructure API

**Dependency / branch:** after foundation, branch `feat/p6-gateway-api`.
Read model_jobs/contracts/gateway/worker and p6-architecture.md end to end.

**Allowed files:** `model_jobs.py`, `model_contracts.py`, `model_gateway.py`,
`model_worker.py`, additive audit tables in `models.py`; new `app/model_api.py`,
`app/model_adapters/` (one explicitly approved provider), `main.py` router wiring;
additive migrations after 0005 if required for actor/consent/reconciliation audit;
new tests, runtime configuration example, compose worker service and docs.
Do not edit parser `worker.py`, manuscript/evidence schemas or source adapters.
Changing a locked contract requires a documented compatibility change, not a
replacement schema. No new queue framework or broker.

**Work:** expose the planned project-scoped preview/enqueue/read/cancel/result/
accept/reconcile API. Authenticate the owner at the deployment boundary; retain
project predicates for every read/write. Bound request/response bytes and time,
map domain errors to safe codes, no-store, no raw Pydantic input echoes. Internal lease/fencing tokens must not be exposed
in public job responses. Record
consent actor/time, exact preview hash and provider retention disclosure. Current
service accepts explicit Consent but has no actor identity; do not expose it as
sufficient for a multi-user deployment. Reconciliation must require owner decision
and recorded billing evidence, not an untrusted request claiming zero charge.
Do not allow automatic clearing of the budget `blocked` flag after a billing
bound violation; add an audited operator resolution for that exceptional case.

Implement fixed-endpoint adapter, startup capability/credential checks, no tools,
redirects or SDK retries, tested tokenizer/framing/pricing bounds and explicit
reasoning/output caps. Credentials never enter rows/logs/prompts. Permit an
external provider in TaskSpec only when its cost bounds are supported. A failed
key/configuration check occurs BEFORE dispatch and consumes no external call.
Any uncertainty after durable dispatch stays ambiguous. The existing generic
Gateway protocol is a replaceability seam, not permission to enable arbitrary
endpoints. Add supervised poll loop with bounded backoff, heartbeat and recovery;
DB time and token fencing stay authoritative. Crash after dispatch stays ambiguous.

**Required tests:** all foundation tests; API project/actor scoping (including
receipts), safe errors/body bounds, consent mutation/retry, exhausted/frozen budget,
missing key, canceled and stale worker, timeout after charge, non-JSON/oversize
response, HTTP 429/5xx without implicit resend, startup/restart recovery, graceful
shutdown, usage/billing limits. Adapter tests use local fixtures, not paid APIs.

**Acceptance / outputs:** documented executable worker + polling API + mock path;
real adapter remains disabled unless owner approves provider/configuration and
live tests. Acceptance/reconciliation authorization audited. CLI/API runbook and
provider capability matrix (token upper bound, rate version, idempotency TTL,
retention, cancellation semantics). No claim of external exactly-once calls.

**Remaining risks:** provider billing changes/hidden tokens, uncertain calls holding
budget, absent multi-user auth in existing application, cost overruns needing
invoice investigation. Do not hide these with automatic retries or refunds.

## Sol Task B — Grounded section generation

**Dependency / branch:** foundation plus Task A's reviewed adapter contract;
branch `feat/p6-grounded-sections`. Can develop deterministic mock cases on the
foundation first; external execution depends on A and owner consent.

**Allowed files:** `model_context.py`, `model_contracts.py` only additive compatible
changes, prompt-versioned new `app/grounded_writing.py`, semantic-review adapter
module, tests/fixtures and documentation. `model_jobs.py` only integration of
validated immutable results. Do not change existing version/locator/UTF-16 rules.

**Work:** assemble task-scoped context preview from saved brief/research question,
manuscript, plan, selected claims and full evidence closure. Keep original RU/EN
excerpts separate; no automatic translation. Current selector includes all text
nodes and rejects >128000 mock bound; optional improved selection must display
complete omissions and require renewed consent. Never trim contradictions or
limits to fit a budget. Include source hashes, stored metadata/locator statuses,
model/token/rate/prompt/policy versions in result provenance.

Implement generation into Proposal only; no document patch language. Resolve
bibliography from library; reject arbitrary DOI/authors/locators in structured
fields. Free prose still needs semantic review. Add a distinct SemanticReview
job over immutable result/context hashes: claim-passage-evidence references,
exact evidence quote, relation verdict, explanation, limitations, uncertain or
insufficient_data permitted. Validate its allowlist/ranges independently too.
Do not turn model confidence, source existence or structural_valid into verified.
No evidence support -> insufficient_evidence + gap; retain conflicting evidence.
Human review is allowed when no semantic model consent is given. This is not a
proof engine or a replacement for Scientific Quality Review SQ01–SQ10.

**Required tests:** multilingual mixed sources, missing support and incomplete
metadata, contradictions and limits retained, exact/nonexact quotations and
surrogate boundaries, unknown/cross-project IDs, stale versions, context limits,
malicious instructions in excerpts/metadata/task text, structured tool injection,
uncertain semantic findings, unauthorized DOI/author fields. Genuine model output
quality must be evaluated separately with permission; mock does not measure it.

**Acceptance / outputs:** bounded grounded proposals with explainable checks;
versioned prompts, stable output schema, fixtures for error cases, visible research
gaps, explicit semantic limitations. Existing claims/links never overwritten.

**Remaining risks:** unsourced claims in free prose, plausible but wrong entailment,
missing contradictory literature, misleading quotations out of context. Keep
user review and SQ follow-up visible, not a green “scientifically verified” badge.

## Sol Task C — React AI Research Assistant

**Dependency / branch:** Tasks A and B's stable reviewed API; branch
`feat/p6-assistant-ui`. Develop against fixtures until APIs are merged.

**Allowed files:** new `frontend/src/ModelAssistant*.tsx`, client/types modules,
UI tests/styles, minimal mounting in ManuscriptEditor/EvidenceWorkspace, docs.
No backend schema changes or rewrites of the manual editor/export panel.

**Work:** choose saved manuscript/plan/brief, selected claims and user section title;
preview exactly what goes to which provider, omissions, token/cost cap and
retention disclosure. Explicit task-specific consent; changed data clears consent.
Show queued/leased/dispatching/ambiguous/cancelled/invalid/succeeded states and
reserved vs charged/unknown accounting. Poll with backoff, preserve request UUID
across retry/navigation; no automatic new paid job on timeout. Cancellation does
not imply refunded money. No secret fields in project drafts/localStorage.

Render plain text proposals and explanations; no model HTML/scripts/links-as-actions.
Show side-by-side append diff, original evidence/versions and contradictions,
scientific unverified status, semantic uncertainty and gaps. Acceptance requires
explicit review and saved-head/result hashes; reuse acceptance UUID after lost
response. Unsaved manual edits block acceptance until saved/discarded; stale
head conflict offers comparison/new preview, not auto rebase. Keep manual P2–P5
working when no model/key/network is available. Image bytes are not transmitted;
formula text remains uninterpreted, footnote/cell/caption anchors stay unchanged.

**Required tests:** explicit consent reset, concurrent edit conflict, refresh and
request UUID restoration, canceled/uncertain jobs, repeated acceptance after lost
response, no accidental unsaved export, keyboard/accessibility labels, no HTML
execution, missing key fallback and RU/EN evidence display.

**Acceptance / outputs:** usable bounded section workflow with transparent costs
and review, frontend tests/build passing, manual mode regression coverage.

**Remaining risks:** user mistaking syntax checks for semantic proof, polling
staleness, accidental repeat generation. Make ambiguous state and explicit new
request/cost decision understandable; do not surface implementation jargon alone.

## Sol Task D — Integration, failure handling and documentation

**Dependency / branch:** reviewed A+B+C plus merged P5.1 PRs #12–14;
branch `test/p6-end-to-end`. No redesign of foundations.

**Allowed files:** backend/frontend integration tests, fixture adapters, CI,
docs/runbooks, minimal bug fixes in A–C modules with a focused regression test.
Do not disable migrations/immutability checks or weaken scoping to pass tests.

**Work:** full saved source -> evidence -> plan -> preview -> consent -> job ->
proposal -> review -> atomic acceptance -> reload -> deterministic DOCX -> restore
old version. Include old v1 and mixed v2 tables/merged cells, formula, footnotes,
image captions and bytes. Test source/version metadata changes during generation,
plan-only conflict, competing workers/budgets, worker death before and after
send, provider timeout+charge, cancel during call, DB failure after response,
acceptance commit followed by connection loss and repeated request.

Run migrations upgrade, downgrade on disposable DB, upgrade, alembic check;
never downgrade populated production audit without backup/owner decision. Run
entire backend suite with real PostgreSQL (no silent skips), frontend suite/build,
CI, and office rendering if available. Mark rich-object skips explicitly until
those PRs are present. Report fixture tests separately from owner-authorized
live paid tests. No API key -> manual and mock workflows must still pass.

**Acceptance / outputs:** reproducible commands/results, live-test authorization
record if performed, deployment/recovery/budget-reconciliation runbook, accurate
P6 completion matrix and remaining risks, no regressions P2–P5.1. Visual Word
acceptance cannot be inferred solely from OOXML tests.

**Remaining risks:** real provider behavior, availability/cost/retention policy,
semantic evaluation quality and human acceptance. P6 is incomplete until its UI,
real approved gateway, explicit consent UX, independent review and operational
recovery have been accepted. Corpus Engine and SQ01–SQ10 remain separate phases.

## Provenance display compatibility note

P2's existing paragraph `origin` distinguishes manual/document import formats;
this foundation preserves that enum and records AI proposal provenance in the
immutable ModelAcceptance -> job -> paragraph UUID derivation instead. Task C
must show that provenance on accepted sections, rather than interpreting
`origin=manual` as proof that a human originally wrote every word. If the owner
prefers an explicit new origin enum, introduce it as a coordinated, additive
backend/frontend compatibility change with old-version tests. Do not mutate old
snapshots to relabel their authorship.
