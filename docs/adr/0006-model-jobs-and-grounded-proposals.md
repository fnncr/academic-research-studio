# ADR 0006: PostgreSQL reservations, one dispatch, append-only proposals

Status: proposed for owner review; implemented by the P6 foundation PR.

Context: external LLM calls are paid, nondeterministic and not transactional with
PostgreSQL. P2/P4 already serialize project writes and protect immutable history.

Decision:
1. Use the existing PostgreSQL and synchronous SQLAlchemy transactions; poll a
   SKIP LOCKED queue. No new broker or universal orchestration framework.
2. Reserve bounded integer cost before work. Separate uncertain execution from
   definitive failure. One potentially paid dispatch per job; preserve ambiguity
   and reservation across crashes. No exactly-once promise. Provider idempotency
   may be added only with tested scope/TTL/billing guarantees.
3. Persist task-specific exact-context consent. No broad project-level permission
   implies permission for arbitrary future document transmission.
4. Strict allowlisted structured proposals plus deterministic validation and a
   separate, explicitly fallible semantic review. Valid UUIDs are not truth.
5. Append new sections atomically with plan/citation updates and replay receipts.
   Reject stale heads. Defer replacements/rebasing and rich-object generation.

Alternatives rejected: automatic timeout retries risk duplicate charges; release
on cancellation can overspend; “JSON mode means safe” confuses syntax with truth;
model-authored document patches can destroy anchors; Redis adds another durable
system without need; automatic citation rebase can attach evidence to new text.

Consequences: uncertain requests may hold budget until human reconciliation;
conservative token bounds reject some feasible contexts; initial generation is
less flexible than an editor agent. These are deliberate reliability tradeoffs.
The personal app still needs an authenticated deployment boundary before remote
multi-user use. See ../p6-architecture.md for contracts, invariants and failure table.
