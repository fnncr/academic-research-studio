# P6 foundation validation — 2026-11-04

Baseline: `origin/main` at `aa0a541` (PR #11 merged). Foundation implementation
`b8affbe`, stacked on architecture `4c9bc20`. No external paid API was called.
All model responses, publications and failure scenarios in these tests are
synthetic. Tests do not establish real model quality or injection immunity.

| Check | Observed result |
| --- | --- |
| Entire backend, PostgreSQL | 240 passed, 1 conditional P5.1 test skipped |
| P6 invariants within that suite | 36 passed; 1 P5.1-dependent test skipped |
| Entire frontend | 37 passed |
| TypeScript + Vite production build | passed |
| Alembic upgrade/downgrade/re-upgrade/check | passed against disposable schemas; no ORM drift |
| Foundation + pending P5.1 PRs #12–14 | 249 backend passed, no skips |
| P6 invariants on combined P5.1 tree | all 37 executed, including mixed rich-object acceptance/export/restore |
| Formatting check | git diff --check passed |

Commands (from backend, with installed repository requirements):

```sh
TEST_DATABASE_URL=postgresql+psycopg://studio@127.0.0.1:55432/studio_test ../.venv/bin/python -m pytest -q
```

Frontend: `npm --prefix frontend test` and `npm --prefix frontend run build`.
The local database is an existing PostgreSQL container, loopback-only. Test
fixtures create and remove separate temporary schemas; no production data used.
The sandbox needed its supported network permission to reach that local DB.
Dependencies were already installed; none added. Existing Starlette/TestClient
httpx deprecation warning remains unrelated to P6.

The combined compatibility run used a detached worktree at `b8affbe`, applying
only the `backend/app` and `backend/tests` diff from `aa0a541` to the pending
`feat/p2-png-images` tip `5ac7a1d`. It did not merge those PRs or change main.
`test_all_rich_objects_citations_survive_model_acceptance` verifies old cell,
footnote and caption citations, unchanged PNG bytes/UUIDs, formula, merged grid,
new plan/manuscript pairing, repeatable DOCX and restoring the prior v1 snapshot.
The conditional skip on main is a known unmerged dependency, not a passed check.

## Fault/race coverage

Actual separate PostgreSQL connections exercise competing last-budget
reservations, duplicate UUID submission, two worker claims, duplicate completion,
concurrent acceptance and cancellation/acceptance. Lease expiry/fencing, a timeout
that may have been billed, crash after dispatch, late reply, database failure
after model response and receipt-insert failure are injected. Assertions check
held reservations, no resend, one debit/receipt, no partial revision and stable
replay even after subsequent manual edits.

Billing beyond the reservation freezes further project spending; no invoice is
silently clipped. Unknown usage remains null in reconciliation receipts. Consent
hash changes and changed system policy block dispatch. Missing API keys do not
block the mock or manual app. P4 project scoping/UTF-16 surrogate boundaries,
unknown and foreign Evidence/SourceVersion, missing contradictions, invented
locator/author fields and forbidden `verified` status are rejected.

## Not validated / not delivered

- No actual paid provider integration or real billing/timeout/idempotency behavior.
- No operational semantic review, scientific truth proof or evaluation of LLM
  resistance to injection. Tests cover data/capability boundaries and strict output.
- No P6 HTTP routes, authentication rollout, background daemon or assistant UI.
- No new visual office rendering run for P6; DOCX structure and repeatability were
  checked automatically. Previous P5/P5.1 visual tests do not replace acceptance
  of future generated content in Microsoft Word.
- Production reconciliation, provider policy changes, billing-overrun investigation
  and audited unfreeze are follow-up operations; the internal foundation stays
  mock-only. See the four tasks in `docs/p6-implementation-handoff.md`.
