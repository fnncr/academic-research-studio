# Sol Task A validation — 2026-11-04

Baseline main: 57eb774; explicit dependency: foundation PR #16 (d35dae0).
Implementation: a34af32. No remote merges and no paid/live model calls.

- Full backend on real PostgreSQL: **260 passed, 1 skipped** (36.19 seconds).
- The 18 Task A cases include API privacy/owner/scoping, consent/audit, budgets,
  reconciliation/unfreeze, replay, HTTP 429/500/503 fixtures, bounded decoder,
  preflight failure, actual worker subprocess/SIGTERM and migration drift.
- The one skip requires independent P5.1 PRs #12–14, absent from current main;
  it is not reported as a successful compatibility check for this change.
- Full frontend: **37 passed**; TypeScript + Vite production build passed.
- Alembic upgrade/downgrade/re-upgrade/check: passed in disposable test schemas.
- Docker image built from Dockerfile.model-worker using inherited proxy and a
  BuildKit secret containing the host trusted CA bundle. No TLS bypass.
- Network-disabled/read-only container smoke: nonroot UID 65532 and mock gateway
  initialization passed. Host worker subprocess processed a saved job and exited
  cleanly on SIGTERM. Full Compose deployment/real provider is not a tested claim.
- git diff --check: passed. Existing Starlette/httpx deprecation warning remains.

Commands: backend `TEST_DATABASE_URL=… python -m pytest -q`; frontend `npm test`
and `npm run build`. Docker build used `--secret id=proxy_ca,src=…` with public
CA roots; no secrets were copied into the image. Managed read-only home required
moving Buildx state via BUILDX_CONFIG into the workspace, without changing Docker
credentials/configuration. Source-copy permissions were corrected before the
successful nonroot runtime check.

The provider registry deliberately rejects external providers before work is
claimed. These fixture tests do not validate real provider tokenizer/pricing,
billing receipts, retention, idempotency or semantic quality. Owner approval of a
specific provider/configuration and adapter fixture review are still required
before enabling a paid provider. API authorization is for one owner of all
projects; it does not implement multi-user project memberships. See p6-task-a.md
for the authenticated personal-deployment boundary and runbook.
