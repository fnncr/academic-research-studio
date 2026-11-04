# P6 Task E — disabled real OpenAI adapter

The single adapter is OpenAI Chat Completions, fixed endpoint
`https://api.openai.com/v1/chat/completions`, snapshot
`gpt-4.1-mini-2025-04-14`. It is NOT enabled by default. No paid calls were made.
The official model page currently marks the snapshot deprecated. The [deprecation schedule](https://developers.openai.com/api/docs/deprecations)
announces shutdown on **2027-01-14**; readiness fails closed from that UTC date. Availability and
retirement must be checked by the owner before approval; no alias/fallback model
is substituted if it is unavailable. This is an offline-tested adapter, not a
claim that a deprecated snapshot is currently available to a particular account.

## Official reference review (2026-11-04)

- [Model](https://developers.openai.com/api/docs/models/gpt-4.1-mini): text input/output,
  no separate reasoning step, 1,047,576 context, 32,768 output maximum; structured
  output support. Displayed standard rates per million tokens: $0.40 input,
  $0.10 cached input, $1.60 output. Snapshot/deprecation/access need rechecking.
- [Authentication](https://developers.openai.com/api/reference/overview): server-side
  bearer application key. No ChatGPT/Codex credential is read or reused.
- [Chat API](https://developers.openai.com/api/reference/resources/chat/subresources/completions/methods/create):
  max_completion_tokens bounds generated tokens. This adapter sets n=1,
  service_tier=default, store=false and strict json_schema; no stream/tools/audio,
  predictions, batch, files, web search or premium tiers. Other billed categories
  are unsupported and cause an ambiguous outcome, not a guessed invoice.
- [Structured outputs](https://developers.openai.com/api/docs/guides/structured-outputs):
  all properties required, extra properties false; refusals/truncation are possible.
  Provider schema omits constraint keywords and defaults, but the original strict
  local Pydantic contracts, exact quotations and scientific allowlists still apply.
- [Rate limits](https://developers.openai.com/api/docs/guides/rate-limits): account,
  project and model-dependent RPM/TPM and other limits; inspect dashboard before
  enabling. Even 429/5xx is never automatically retried by this adapter.
- [Data controls](https://developers.openai.com/api/docs/guides/your-data): API data
  is not used for training by default; abuse-monitoring retention can be up to
  30 days. store=false does not mean Zero Data Retention; caching and contractual
  exceptions remain. Owner must review current terms, location and eligibility.

Documentation was read with the web tool. Shell access to the documentation host
was denied by the session proxy; that denial was not bypassed. The environment's
model API network permission must be configured separately before any approved
live check. A documentation read is not a paid model request.

## Cost bound and approval

No approximate tokenizer count is labelled exact. Reservation uses the entire
model context window minus the output cap as the input-token ceiling, at uncached
input price, plus the configured output cap. At 2000 output tokens it reserves
421431 micro-USD (ceiling-rounded). This is deliberately much larger than expected
usage. Quotes include a SHA-256 of the exact request payload (including server
prompt and schema); changes invalidate dispatch/consent. A real tokenizer can be
added later only with independently tested framing/schema bounds.

Actual reported prompt/completion/cached counts determine settlement at the
reviewed rates, rounded UP to integer micro-USD. This rounding is conservative
accounting, not an exact sub-micro-dollar invoice. Missing/malformed usage,
unknown nonzero categories, unexpected model/tier or usage outside bounds holds
the full reservation for reconciliation. Definitive usage with invalid/refused/
truncated content is charged, with invalid_result/schema or allowlist diagnostics.
No result is silently repaired or accepted into the manuscript.

There is no documented exactly-once billing guarantee relied on here.
X-Client-Request-Id is diagnostic identity, not proof of deduplication. HTTP timeout
is 10s connect / 45s phase inactivity, with a 60s elapsed check between chunks;
a stalled final read may extend past 60s by its read timeout. A forced worker kill
leaves durable dispatch markers. No SDK retries, redirects or direct proxy bypass.
Existing PostgreSQL leases, cancellation, reservations and atomic acceptance stay
in force. Cancellation after dispatch is intent and does not guarantee refund.

Only after the owner approves provider/snapshot availability, tariff, data transfer
and spending limit should a separate APPLICATION key/configuration be supplied:

```text
ARS_OPENAI_API_KEY=<separate owner application key; never a Codex/ChatGPT key>
ARS_OPENAI_APPROVAL=openai-gpt41mini-2026-11-04-v1
ARS_OPENAI_PRICE_CONFIRMED=openai-gpt41mini-2026-11-04-v1
ARS_OPENAI_MAX_UNITS=<approved per-call ceiling in micro-USD>
```

No default values authorize a call. A positive owner ceiling must cover the
conservative reservation; the project's DB budget must also suffice. Configure
API and worker consistently, with TLS trust and permitted proxy egress to
api.openai.com. Restart both after configuration changes. Readiness checks never
call the provider. Turning approval off prevents enqueue and dispatch; mock and
manual work remain usable without this key. Do not expose keys in frontend,
project drafts, logs or Git. The API owner token is a separate credential.

The assistant offers mock/OpenAI selection, actual snapshot and readiness,
external-data disclosure and monetary bound. Request-specific context consent is
still mandatory; configuration approval alone never authorizes a task. The
selected section can limit manuscript text; all selected claim relations and
original evidence remain intact. With no section selected the complete bounded
saved manuscript text is explicitly included in preview. No image pixels sent.

Generation prompts require synthesis, comparison of positions, facts versus
interpretations, cautious conclusions and explicit gaps. Only saved evidence and
source versions are allowed. Proposal remains unverified. Review uses a different
prompt and SemanticReview schema in a separate consented/budgeted job; its
assessment is not scientific proof. No automatic acceptance or version rebase.

## Tests and live acceptance plan

Regular tests use httpx.MockTransport and synthetic local fixtures only. They cover
bearer/request shape, strict schema, successful settlement, unknown identifiers,
nonexact quotes, refusal/length/invalid JSON, 401/403/429/5xx/redirect, timeout,
unknown billing, missing application key/approval, ceiling, configuration revocation
before dispatch and separately billed semantic review. Existing suites cover
cancellation, lost responses, races, conflicts, receipt replay and manual/export
compatibility. No new dependencies/migrations. No real-model quality claim.

After explicit owner approval, live acceptance should use a disposable project
with synthetic Research Question/claims and clearly labelled fictional excerpts,
no personal manuscript. Obtain quotes for ONE writing job and optionally ONE
independent review. Owner must approve the combined quote sum, provider data policy,
model and per-job limits before enqueue. Start one worker; do not automatically
repeat ambiguous/invalid results. Archive request IDs, hashes, usage/cost, validation
and human quality review without keys. Check cancellation and version conflicts
with fixtures, not extra paid calls. Missing support should remain a gap and
opposing evidence must remain visible. P6 remains incomplete until this separate
live/integration and human acceptance are actually performed.


Observed local validation: full PostgreSQL backend **298 passed, 1 P5.1-dependent
skip**, frontend **47 passed**, TypeScript/Vite build passed. A subsequent lifecycle
gate adds a targeted retirement test; final CI runs the full suite including it.
Migration upgrade/downgrade/check are exercised by existing integration tests;
there are no model/migration changes. Live provider, account authorization, real
model output quality and the owner's final synthetic live acceptance are untested.
