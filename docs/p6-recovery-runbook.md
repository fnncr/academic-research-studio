# P6 deployment and recovery runbook

Use the existing personal owner boundary (loopback or authenticated TLS proxy).
Never publish owner/application keys in shell history examples, logs or reports.
Deploy the same code/configuration to API and workers. Back up the database,
apply `alembic upgrade head`, check schema drift, then start API/worker. Manual
P2/P4/P5 remains usable with external provider approval/key absent. UI session
storage contains request parameters/UUIDs, never provider credentials.

## Unknown result or worker crash

1. Stop additional worker processes if investigating billing/model drift. Do not
   set dispatching/ambiguous rows back to queued or replace a dispatch UUID.
2. Read the scoped job/status and project budget via the owner API. A lost browser
   response is not proof of no commit: recover by request UUID; repeated enqueue
   or acceptance must use the same UUID/body. Do not create a new paid task merely
   because a network response was lost.
3. Restarting a worker sweeps expired leases using PostgreSQL time. Work that was
   never dispatched can requeue with a new fence. Dispatched work becomes ambiguous
   and retains reservation; it never automatically sends again. A matching late
   reply may settle a still-unresolved job once.
4. Cancellation after dispatch is intent, not guaranteed cancellation/refund at
   the provider. The response may still incur cost; the proposal is discarded when
   cancellation wins. Cancel cannot undo a committed manuscript acceptance.

## Billing drift / ambiguous reservation

A different returned model/tier, unsupported billed categories or bound violation
requires operator investigation. Budget `blocked=true` prevents new reservations
and dispatches, including previously queued tasks. Keep external approval disabled
until provider/model/price/data policy are revalidated. No automated billing probe
or paid retry is part of recovery.

The owner reviews billing evidence out of band, then records a traceable evidence
reference and explicit acknowledgement through the existing reconcile API. Use
provider_receipt only for an actually reviewed amount; zero requires evidence,
not a timeout assumption. owner_full_reserve is a conservative closure at the
quoted reserve and is explicitly not a claim of a known invoice. Usage stays
unknown where not reported. Amounts beyond the reserved bound cannot be clipped
into a false receipt: stop and investigate/fund liability before continuing.

Reconciliation does not regenerate missing text and does not automatically clear
blocked. The separate owner-reviewed budget/unblock action refuses unresolved
active/ambiguous jobs. Clear the block only after all relevant uncertainties,
actual invoices and provider configuration are reviewed. Audit/settlement rows
are immutable. A desired new generation requires a new task UUID, preview,
explicit context consent and sufficient newly approved budget.

## Acceptance conflict or lost acceptance response

Keep unsaved manuscript/plan drafts. A changed saved head causes conflict; do not
shift UTF-16 citation ranges or rebase automatically. Compare versions and create
an explicitly reviewed new proposal/manual edit. If acceptance may have committed,
read the receipt or repeat the exact acceptance request: it returns the original
revision IDs even if later manual versions exist. A refreshed editor must not
overwrite a dirty draft. Exports can target the accepted historical manuscript/
plan pair independently of the current head. Restoring v1/v2 creates another
version; old P4 anchors remain pinned and need review before reuse.

## Repeatable offline validation

Run the full PostgreSQL suite and frontend tests/build. Regular tests block real
OpenAI HTTP transports and use synthetic MockTransport fixtures. To archive the
synthetic accepted DOCX, set P6_VALIDATION_ARTIFACT_DIR for the end-to-end test.
Office inspection can convert that artifact using a writable LibreOffice user
profile. Source excerpts/PNG bytes must stay intact; verify package hashes/OOXML
and inspect the render. Font substitution/field updating are separate limitations.
See validation/p6-final-integration.md for evidence and exact acceptance limits.

No downgrade of populated production history/audit tables is authorized by this
runbook. Test downgrade/upgrade only on disposable schemas; restore a reviewed
backup or follow a separately approved incident procedure in production.
