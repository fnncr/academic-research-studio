# P6 offline integration acceptance — 2026-11-04

Baseline main: `1d50462` (PR #21). This delivery integrates the already-reviewed
P5.1 work from PRs #12–14, previously merged into nested branches rather than
main. Integration commit `4a4400a` keeps the Task C editor/assistant integration;
README conflict resolution retains both P6 and rich-object documentation.
No P7/P8/P9 work, production migrations or paid model calls were performed.

## Observed checks

| Check | Result |
| --- | --- |
| Entire backend, real PostgreSQL | **314 passed, zero skips**, 54.42s |
| Entire frontend | **52 passed**, 15.73s |
| TypeScript / Vite production build | passed |
| Alembic upgrade/downgrade/re-upgrade/check | passed inside disposable test schemas |
| Previously skipped mixed P5.1/P6 regression | executes and passes; missing Image support now fails instead of skipping |
| Full saved-source -> DOCX -> v1 restore API scenario | passed |
| Five additional provider-billing drift scenarios | passed |
| Paid network prevention | autouse test guard blocks actual api.openai.com HTTP transports; MockTransport fixtures only |
| Office conversion / inspection | LibreOfficeDev 26.8 opened DOCX, exported three A4 PDF pages; visually inspected |
| git diff --check | passed |

Backend command from backend directory:

```sh
P6_VALIDATION_ARTIFACT_DIR=/workspace/work/p6-final-artifacts \
TEST_DATABASE_URL=postgresql+psycopg://studio@127.0.0.1:55432/studio_test \
../.venv/bin/python -m pytest -q
```

Frontend: `npm --prefix frontend test` and `npm --prefix frontend run build`.
PostgreSQL tests allocate isolated schemas and remove them afterward. CI supplies
its own disposable PostgreSQL; no production database was used. Existing
Starlette/TestClient httpx deprecation warning is unrelated to these changes.
No requirements or migrations were added. Owner application keys/approval flags
are removed in the end-to-end mock scenario. Synthetic key strings are used only
with in-process HTTP fixture transports in adapter tests.

## End-to-end coverage

`test_p6_end_to_end.py` starts with the existing source/evidence/claim/citation
fixture, saves a v2 document with an embedded PNG, native footnote, rectangular
merged cells, table, formula, Cyrillic text and UTF-16 emoji citations. It:

1. Pins a saved manuscript and plan, previews all allowed context, checks that PNG
   bytes are excluded and explicitly consents/enqueues through the owner API.
2. Adds a newer SourceVersion during generation: output and bibliography continue
   to use the original exact version, not its latest replacement.
3. Reopens an API client and recovers the task via request UUID. Same request
   returns the same job without another reservation.
4. Runs mock writing and a separate consented/budgeted review. Reports stay
   unverified/uncertain; no evidence relation is promoted to scientific truth.
5. Accepts atomically into new manuscript/plan versions. Original rich blocks,
   UUIDs and citation ranges remain byte-for-byte JSON-equal.
6. Loses/repeats acceptance after a subsequent manual save: receipt IDs replay,
   and the newer manual head is not replaced by a second application.
7. Exports the exact accepted historical versions twice with identical DOCX
   bytes; checks bibliography version, embedded original PNG bytes, OMML,
   gridSpan/vMerge, footnotes with citation hyperlinks and PAGE footer.
8. Restores the original v1 as a new version, rereads the accepted v2 archive and
   reexports the earlier accepted snapshot with the same DOCX bytes.

Existing suites additionally test budget/worker/acceptance races, expired lease
fencing, death before/after dispatch, provider timeout, cancellation during calls,
DB failure after reply, receipt insertion rollback, stale manuscript and plan
heads, project isolation, hostile source instructions, unknown source IDs and
exact quote/surrogate validation. Frontend tests cover UUID/consent recovery,
cancellation, lost acceptance, unsaved work, API errors, escaped hostile result
text, missing configuration, rich-object controls and manual/export regressions.
These are HTTP/DOM/in-process-worker integration tests, not a claim of a manual
real-browser/screen-reader audit.

## Defects corrected

- P5.1 was missing from main, not intrinsically failing. Integrating its actual
  backend/frontend functionality makes its required test executable; skip removal
  alone would have hidden the missing user functionality.
- The real adapter used to hold one ambiguous reservation for an unexpected
  model/tier, nonzero reasoning/audio tokens or usage outside bounds, while other
  queued tasks could still spend. `UnconfirmedBilling` now freezes the project
  budget atomically with its ambiguous marker. Five fault tests ensure another
  queued task cannot send, existing reserve stays held, no debit/retry occurs,
  and reconciliation alone does not silently unfreeze the account. The UI gives
  an explicit billing-drift warning. No actual provider request was needed.
- Cached TOC text inherited justified Normal alignment; line breaks stretched
  short headings across the page. The TOC paragraph is now explicitly left
  aligned, protected by the end-to-end OOXML assertion and visually rechecked.

## Office artifacts and visual scope

Synthetic example files: [DOCX](artifacts/p6-acceptance.docx),
[LibreOffice PDF preview](artifacts/p6-acceptance.pdf).
The file contains deliberately synthetic publications/data, not real research.

DOCX SHA-256:
`ba092a3f7cd9fff503b381ed5912edc66c86e5dc907b18d7cb21186b893e3e11`

PDF SHA-256:
`8bcd627fff016f8a722d63f50d27a436766ee6dd2682c1b135371d8fc577a988`

The three-page render shows the corrected TOC preview, original text/table/PNG/
merged table/formula, accepted section, cited footnote at the page bottom,
bibliography and centered page numbers without observed clipping/overlap.
Times New Roman is absent here: Liberation Serif substitutes it; Noto Color Emoji
renders the synthetic emoji. Microsoft Word, exact institutional typography and
full screen-reader acceptance still require owner review. TOC is a real updateable
field, but cached headings have no invented page numbers: update the field in
Word/office editor for final pagination. PDF conversion is a validation artifact,
not a new application PDF-export feature. PDF timestamps are not claimed to be
repeatable; DOCX repeatability is verified for the identical saved inputs.

## Completion matrix

| P6 area | Offline status | Remaining acceptance |
| --- | --- | --- |
| Immutable writing/review contracts, scopes and exact citations | passes | expert review of generated factual content |
| Queue, lease fencing, budgets, cancellation/replay/recovery | passes fault/race tests | deployment recovery exercise in owner's environment |
| Mock grounded sections / gaps / opposition | passes | author reviews research quality |
| Owner API / assistant / request-specific consent | passes automated API/DOM tests | real-browser and assistive-technology acceptance |
| Real OpenAI adapter | fixture contract/failure tests pass, default OFF | owner-approved account/config/data/budget and bounded synthetic live test |
| P2/P4/P5.1 preservation and deterministic DOCX | passes without skips | Microsoft Word/font/template acceptance |
| Offline migration checks | passes on disposable schemas | backed-up deployment procedure |

This completes the offline integration validation, not all live/scientific
acceptance of P6. The model snapshot remains deprecated and has the lifecycle
gate described in p6-task-e.md. No provider was enabled, no invoices were fetched
and no actual model quality or remote billing behavior was measured.
