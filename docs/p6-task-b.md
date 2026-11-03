# Sol Task B — Evidence-grounded sections and independent review

Task B branches from Task A (#17), which depends on foundation #16. Main still
contains architecture #15 only. Neither dependency is silently merged on GitHub.
The agreed PostgreSQL queue, budget/consent/fencing and append-only acceptance
remain in force; no new tables or dependencies are introduced.

## Delivered generation

Writing TaskSpec defaults to `kind: writing`; existing clients may omit this
field. MockGateway now uses the bounded local composer in grounded_writing.py.
It produces Proposal v1: explicitly attributed/unconfirmed claim text, labelled
supports/contradicts/limits, exact original quotations, citations and research
gaps. It is deterministic template composition, **not LLM synthesis or evidence
of real-model quality**. It does not translate, infer new results, resolve
contradictions, invent a bibliography or execute instructions in source/task text.
Real model/provider approval and tokenizer/billing validation remain prerequisites
for external LLM execution. No paid API was called for this work.

The selected claim closure remains complete. RU/EN originals stay separate from
labels and are never rewritten. Lack of support yields insufficient_evidence plus
a gap; a support relation yields only needs_review, never verified. Contradictions
are displayed next to support. Existing claims and evidence links are preserved
when a new section is accepted. Citation ranges count UTF-16 units, including
surrogate pairs, and point to exact SourceVersion through the stored Evidence.

Context includes saved research question/brief, manuscript and plan IDs/hashes,
all selected claim relations, original excerpts/languages and source metadata.
Image bytes are excluded; captions and formula text are uninterpreted. P3 metadata
schema and saved Evidence selection/permission/hash are independently checked.
Missing authors/year remain missing and appear in bibliography_diagnostics;
metadata existence/valid DOI syntax does not establish full-text or semantic truth.
Locators stay user supplied/unverified; source text cannot supply a new locator.

Prompt, schema and policy hashes are included in the consented snapshot. Server
messages use distinct writing/review prompts; excerpts remain data with no tools.
A changed prompt invalidates dispatch before transmission, including changes of
identical string length. Source/evidence hashes, exact input versions, provider,
model, price quote and reported usage are attached by the server to the immutable
job report, not trusted from model output. Updated contracts require a new preview
and consent; old snapshots are not rewritten. Old-policy jobs can fail closed
and require explicit new preview rather than using a changed prompt silently.

The local composer checks paragraph/citation limits and a conservative UTF-8 text
output bound before reservation. A task too large to include all evidence returns
output_capacity_exceeded; shorten the explicitly selected context, select fewer
claims, choose smaller saved excerpts or increase the allowed output cap. Nothing
is silently trimmed. This conservative bound is not a real provider tokenizer.
The existing 128000 context bound, saved-document/plan limits and P5 preflight
still apply. Acceptance may conflict with either current saved head.

## Separate semantic-review jobs

Use the same owner-only Task A API and saved TaskSpec IDs/claims:

```json
{
  "kind": "semantic_review",
  "review_job_id": "<completed-writing-job-uuid>",
  "review_result_hash": "<sha256-of-stored-Proposal>",
  "request_id": "<new-uuid>"
}
```

The omitted TaskSpec fields (brief/manuscript/plan/claim_ids/title/instruction,
provider/model/output cap) must also be supplied. Preview returns the exact
review_subject, including immutable Proposal and result hash. The source must be
a succeeded writing job in the same project; the pinned research context must
match. Review-of-review is rejected. Enqueue requires fresh exact-context consent
and reserves its own budget. Writing consent never authorizes a second call.

SemanticReview v1 is validated separately from Proposal: result/context hashes,
claim/evidence/paragraph allowlist, exact original evidence quotation, distinct
and complete target coverage, explanations and limitations. Targets include every
selected relation on each paragraph attributed to its claim by citations. With
no attribution, all paragraphs must be considered for that claim's evidence.
Over 100 pairs or the output bound fails admission; opposition is not dropped.
No evidence produces insufficient_data. Unknown IDs, omitted/duplicate targets,
wrong paragraph, altered quote, or a verified status are rejected.

The local reviewer emits only uncertain findings with explicit limitations; it
cannot assess entailment, methodology, causality or literature completeness.
Its `reviewer_kind=model` identifies the automated mock path, not real-model
analysis. Model jobs cannot impersonate a human reviewer. Human review can record
supports/contradicts/uncertain/insufficient_data with explanation and provenance,
but no review status certifies scientific truth. Reports remain independently
stored; reviews do not overwrite the generator's immutable result/report or
make a manuscript change automatically. A review job cannot be accepted as text.

## Human review without model execution

An authenticated owner may POST
`/api/projects/{project_id}/model-jobs/{writing_job_id}/human-review`:

```json
{
  "request_id": "<new-stable-uuid>",
  "acknowledged": true,
  "review": {
    "result_hash": "<stored-Proposal-hash>",
    "context_hash": "<hash-of-review-preview-context>",
    "reviewer_kind": "human",
    "reviewer_version": "<human-review-protocol/version>",
    "findings": [],
    "status": "uncertain"
  }
}
```

Use the semantic-task preview context to identify targets and original quotations.
The empty findings example is schematic: actual findings must cover all targets;
when there are no evidence targets, status must be insufficient_data. Preview
requires no model consent or reserve. Human submission creates a separate immutable
completed review job, a zero-cost/zero-token settlement and owner audit atomically;
it never calls a gateway or needs a model key/budget. Repeating the exact UUID/body
returns the same review, even after later cancellation of the writing job. Changed
content under that UUID conflicts. The returned human job can be read with the
existing owner/scoped status/result routes. Source manuscripts and plans remain
unchanged; text acceptance still requires its own saved-head/result acknowledgement.
The deployment remains personal/single-owner, as described in Task A.

## Verification / limits

Tests cover multilingual originals, incomplete bibliography, contradiction/limit
retention, no-support gaps, independent review linkage/coverage/quote failures,
foreign projects, mismatched hashes, separate costs, human zero-cost replay and
HTTP authorization, reviewer impersonation, prompt changes and capacity failures.
Existing tests retain injection fixtures, unknown SourceVersion/Evidence, UTF-16
surrogate boundaries, atomic acceptance conflicts and P2–P5 compatibility.

No real LLM quality/entailment evaluation or new office-rendering validation was
performed. The React assistant is Task C. A real independently consented reviewer,
expert evaluation and SQ01–SQ10 are future work. The local composer/reviewer do
not make P6 scientifically or operationally complete.
