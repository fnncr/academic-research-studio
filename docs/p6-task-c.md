# P6 Task C — AI Research Assistant UI

Prerequisite PRs #15–18 were checked (successful CI); their nested branch merges
were brought into main by integration PR #19. This feature starts from main
f086666. It does not merge itself, enable external models or implement P7–P9.

Open a project, its manual manuscript editor, then “Открыть AI Research Assistant”.
Manual editing and DOCX export remain independent of assistant configuration.
The assistant explicitly calls its backend local template composition via mock,
not an actual language model or proof of scientific truth. A running model_worker
is needed to process queued work; the UI never dispatches work itself.

Enter the configured MODEL_OWNER_TOKEN in the password field. This is the personal
owner API credential, not a model provider key. It is held in component memory
only, never in sessionStorage/localStorage. Re-enter it after refresh. The existing
Task A single-owner/loopback or authenticated proxy deployment boundary applies.
No token is sent to metadata URLs or other origins. External-enabled capabilities
fail closed in this UI until a provider-specific consent flow is approved.

Choose a saved manuscript revision, a compatible saved plan, section and up to 20
claims, new section title and output cap. View original Evidence, relation,
language, precise SourceVersion metadata and locator status. Older versions are
loaded in pages. Sources are neither translated nor fetched from external URLs.
Preview shows the complete server context (including omissions), provider/model,
input/output bound and synthetic maximum mock cost. Budget display distinguishes
spent and reserved values; the owner may explicitly set a limit through the audited
budget API. No sources/DOI/page fields are invented or automatically corrected.

Consent is specific to the preview fingerprint and is cleared by saved-head,
unsaved-state or settings changes. Once a task envelope is pinned, changing it
requires the explicit “Новое отдельное задание” confirmation: the previous request
may have committed or still hold budget. No timeout/refresh/poll creates a new
request UUID automatically. UI mutation handlers have a synchronous lock to prevent
double clicks; retries use the same persisted request/body. Network timeouts do
not imply cancellation, free usage or permission to regenerate.

The task envelope (version/claim UUIDs, title, fixed instruction and limits), job
ID and cancellation/acceptance request identities are stored per project in this
tab's sessionStorage. This includes the entered section title, but excludes owner
credentials, source excerpts and full manuscript/context. Storage write failure
blocks the initial request rather than generating without a recoverable identity.
Closing the tab clears session storage; server history remains. The history panel
can reopen saved jobs. Additive scoped GET /model-jobs/by-request/{request_id}
recovers jobs after an enqueue response is lost. Job reads expose the saved task
and immutable acceptance receipt; worker fences remain private. No DB schema
change was needed for these read-only projections.

Polling performs reads only, with bounded backoff and effect cleanup. Ambiguous
jobs show held funds/unknown actual cost and require owner reconciliation through
Task A; cancellation records intent and does not promise a refund. A saved
cancellation decision UUID survives a lost response. Errors leave task identities
intact; reconnect/re-read does not repeat generation. The UI supports the existing
latest-20 server history window; recorded job IDs remain directly recoverable.

Results render as text, including hostile HTML-looking source strings. The panel
shows the unchanged input manuscript alongside the appended proposal, citation
links/report, scientific gaps, warnings and semantic uncertainty. Structured
review jobs can be inspected without being accepted as manuscript text. Acceptance
requires explicit review and saved-head/result hashes. A precheck compares both
server heads; the existing backend remains the transactional authority if a race
occurs after that check. No automatic rebase or range migration is attempted.

The exact acceptance UUID/body survives a lost response, and repeated submission
returns the existing receipt. A recovered accepted job shows its receipt and an
explicit action to refresh the editor. Refresh does not overwrite unsaved manual
work: the parent retains the draft and offers version comparison instead. Manual
editor controls are locked during assistant mutations; manuscript/plan dirty state
blocks sending and accepting. Existing block IDs, formula/table objects and P4
citations are preserved by server append-only acceptance; P5.1 objects absent from
main remain a dependency limitation, not a claimed passing integration check.

Accessibility: labelled controls, fieldsets/legends, native checkbox/select/button
keyboard behavior, live status/error regions, visible focus and responsive diff
columns. React escapes source/result text; no model HTML is executed. Automated
DOM/accessibility-role tests do not replace a screen-reader or real-browser audit.
No new office-rendering or full manual assistive-technology review is claimed.

Validation: full PostgreSQL backend suite, frontend suite and TypeScript/Vite build
are required. Tests include exact consent, unsaved blocking, stale heads, request
recovery, cancellation, uncertain state, missing configuration, safe rendering,
acceptance replay, read-only recovery scoping and immutable receipts. The backend
suite retains P2/P4/P5 regressions and migration checks. A P5.1-dependent case is
skipped until PRs #12–14 are present. Real model quality, paid calls and semantic
truth verification remain outside this delivery.

Observed validation: 280 PostgreSQL backend tests passed with one P5.1-dependent
skip; 46 frontend tests passed; TypeScript/Vite build passed. Backend checks include
migration drift and scoped UUID/receipt recovery. Existing Starlette/httpx
TestClient deprecation warning remains. Acceptance hashing requires a secure browser
context (HTTPS or localhost). No new dependencies or migrations were added.
