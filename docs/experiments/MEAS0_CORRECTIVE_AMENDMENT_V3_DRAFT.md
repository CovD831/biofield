# MEAS0 corrective amendment V3 — DRAFT

Status: **NON-NORMATIVE / NOT APPROVED**

Date: 2026-07-31

This document is a corrective implementation proposal produced from a
protocol-to-code coverage audit. It is not a preregistration, approval,
comparison lock, execution authorization, trust root, or Gate decision. It
does not authorize provider calls, external cost, access to protected
materials, Pilot execution, confirmatory execution, or any scientific claim.

[MEAS0 Design V1](./MEAS0_DESIGN_V1.md) and
[MEAS0 formal protocol amendment V2](./MEAS0_FORMAL_PROTOCOL_AMENDMENT_V2.md)
remain unchanged and authoritative. Nothing in this draft retroactively
changes or reclassifies an existing foundation, candidate, Pilot, or
confirmatory artifact. If this proposal is approved, the approved text must be
published separately and bound by a new lock before it has normative effect.

## 1. Purpose and non-changes

The proposed correction closes implementation reachability and evidence
ancestry gaps between the V1/V2 protocol and a future Gate M decision. It does
not change:

- the two Pilot tasks or two confirmatory tasks;
- F01–F18 or their gold meanings;
- the five arms, their allowed signals, or their paired comparison;
- Pilot `N=36`, confirmatory `N=144`, or the five-arm denominators;
- mutation seeds, arm-order seed, bootstrap seed, replicate count, cluster
  definition, percentile convention, or confidence levels;
- FAR, unsafe success, detection, coverage, cost, or other metric definitions;
- §13.1 hard requirements, §13.2 performance thresholds, §13.3 adoption logic,
  or §13.4 stop/invalid conditions;
- Judge qualification thresholds, gold precedence, or the prohibition on
  foundation/test-only evidence entering a formal claim.

The proposed implementation rule is:

> No caller-supplied status, boolean, case list, opaque hash, or collection of
> individually valid objects may substitute for evidence-derived common
> ancestry at a formal boundary.

## 2. Phase-specific readiness

The current idea of one final, cumulative readiness bundle should be split
into phase-specific, append-only readiness receipts. A later receipt may bind
earlier receipts, but an earlier stage must not require evidence that can only
exist after that stage has run.

If approved, the minimum phase sequence would be:

1. `PRE_JCAL_READY`
   - binds the reviewed protected J-CAL corpus manifest;
   - binds the pre-J-CAL Judge specification and identity manifest, including
     Prompt, rubric, parser, response schema, sampling policy, provider/model
     identity, price inputs, the J-CAL sub-budget, trust policies, and the
     pre-calibration lock;
   - does not contain calibration-derived rates, qualification status, or
     qualification time; those fields belong to the post-J-CAL qualification
     card described below;
   - requires the typed `pre_jcal` authorization checkpoint;
   - must not require J-CAL output, Pilot output, J-AUDIT output, or a
     confirmatory authorization.
2. `PILOT_READY`
   - binds the unchanged pre-calibration surface;
   - binds a production-derived J-CAL qualification and its exact transport,
     invocation, protected-corpus, and StageCost ancestry;
   - binds a post-J-CAL qualification card that references the frozen
     pre-J-CAL Judge specification and contains the derived qualification
     metrics; it must not rewrite the specification or identity surface;
   - binds the reviewed Pilot comparison lock, Pilot case manifest, five
     approved backend descriptors, formal oracle authority, gold ancestry,
     isolation/preflight evidence, and the typed `pilot_start` authorization;
   - must not require J-AUDIT output or final confirmatory authorization.
3. `JAUDIT_READY`
   - binds the sealed Pilot result and the unchanged design surface;
   - binds the held-out J-AUDIT manifest without exposing its protected
     content to development roles;
   - binds the reviewed confirmatory lock and the typed
     `post_pilot_jaudit` authorization;
   - must not require J-AUDIT output.
4. `CONFIRMATORY_READY`
   - binds the unchanged confirmatory lock;
   - binds a production-derived J-AUDIT qualification and its exact transport,
     invocation, protected-corpus, and StageCost ancestry;
   - binds the typed final `confirmatory_start` authorization;
   - is the only readiness class that may authorize confirmatory execution.

Each receipt must have a factory-only derivation path, an exact schema, a
canonical hash, the preceding receipt hash where applicable, the current
StageCost ledger head, comparison-block identity, design/lock hashes, and an
explicit authorized next action. Serializing a future checkpoint in an
initial manifest is not evidence that the later review and authorization
occurred in the required order.

Test-only phase receipts may exercise this state machine but must remain
non-upgradable. A production receipt must be reconstructed from typed raw
evidence and production verification results; it cannot be created by changing
`test_only`, `formal_eligible`, `ready`, or an equivalent flag.

In this proposal, the pre-J-CAL Judge specification/identity object and the
post-J-CAL qualification card are distinct typed objects. The former freezes
what will be evaluated; the latter records the resulting qualification. The
term `JudgeCard` in V1/V2 must not be implemented as one object that requires
future calibration output while authorizing J-CAL.

## 3. Typed authorization checkpoint targets

An authorization checkpoint target should be a typed, canonical payload, not
an uninterpreted caller-provided digest. The four checkpoint payloads should
bind the evidence that exists at their respective stages:

- `pre_jcal`: pre-calibration lock, protected J-CAL manifest, approved
  pre-J-CAL Judge specification/identity surface, price/budget inputs, and
  ledger pre-head;
- `pilot_start`: unchanged pre-calibration lock, derived J-CAL qualification,
  post-J-CAL qualification card, reviewed Pilot lock, Pilot cases,
  gold/oracle/isolation ancestry, approved provider descriptors, and ledger
  pre-head;
- `post_pilot_jaudit`: sealed Pilot package, unchanged design surface, reviewed
  confirmatory lock, held-out J-AUDIT manifest hash, and ledger pre-head;
- `confirmatory_start`: unchanged confirmatory lock, derived J-AUDIT
  qualification, exact confirmatory execution plan/provider manifest, and
  ledger pre-head.

Verification must recompute the target payload from the supplied typed
objects, verify its detached signature under the phase-appropriate human
trust policy, and compare all embedded hashes. A signature over payload A
must not authorize execution plan B, a different provider descriptor, a
different comparison block, or a newly chosen execution identity.

The checkpoint sequence is append-only. Later checkpoint requirements and
signatures are added only after their prerequisite evidence exists. Replacing
or rewriting an earlier checkpoint requires a new comparison block.

## 4. Confirmatory 144 × 5 common ancestry

A claim-bearing confirmatory path should accept exactly:

- the frozen confirmatory manifest of 144 cases;
- five outcomes for every case, for exactly 720 ordered arm-case outcomes;
- one confirmatory execution authorization;
- one unchanged confirmatory comparison lock;
- one approved formal detection-oracle authority;
- one common gold manifest and review ancestry;
- one append-only StageCost ledger ancestry;
- one sealed outcome package and one write-once package seal.

Every outcome must bind the same:

- design and comparison-block identifiers;
- confirmatory lock hash;
- execution authorization hash;
- case-manifest hash;
- oracle manifest/authorization hash;
- gold manifest hash;
- source/evaluator manifest hash;
- run and package ancestry.

The five arms for a case must share the same frozen case, task/bundle,
EpisodeGraph, mutation seed, failure policy, and budget policy. The package
factory must reject missing, duplicate, reordered, cross-run, cross-lock,
cross-oracle, cross-gold, or cross-authorization entries.

The formal Gate entry point should consume this sealed 720-entry package,
not a caller-created mapping of otherwise valid outcomes. The paired
bootstrap remains exactly the V1 rule: within each `task_id × fault_id`
stratum, resample four complete mutation-seed clusters with replacement while
preserving all five arms.

Pilot and confirmatory packages must be distinct typed schemas. A valid
36 × 5 Pilot package cannot be relabeled or expanded into a confirmatory
package.

## 5. Gold-derived outcome fields

Claim-bearing `gold_status`, `accept_allowed`, and `safety_violation` must not
be parameters supplied to the outcome factory.

The proposed formal outcome factory should instead accept:

- the typed case identity;
- the complete reviewed `GoldRecord` membership for that case;
- the `GoldScopeManifest`;
- the `GoldArtifactManifest`;
- blind-review and adjudication records;
- the phase readiness receipt and signed lock ancestry that bind those
  records.

It should independently derive the case-level:

- gold run validity;
- top-level gold status;
- `accept_allowed`, using the frozen rule that acceptance is allowed only for
  a valid gold `pass`;
- safety-violation flag.

All requirement-level records for a case must agree on these case-level
fields. Review hashes, adjudication hashes, evidence refs, gold source refs,
author/reviewer/adjudicator roles, scope membership, and the gold artifact
manifest must be verified before an outcome becomes formal eligible.

The metric layer may project these derived values but must not accept
replacement booleans or strings. Synthetic DTOs may remain for pure
mathematical tests, with an explicit test-only claim scope.

## 6. Evidence-derived §13.1 hard requirements

The eight ordered §13.1 criteria remain unchanged, but their evidence should
be produced by a typed assessment factory over sealed sources:

1. traceable pass membership derived from the exact evaluation artifacts,
   frozen MeasurementSpecs, EpisodeGraphs, and evidence parents;
2. F04/F09/F17 block/invalid membership derived from the confirmatory case
   manifest and retained outcome records;
3. deterministic hard/critical override count derived from canonical
   measurement leaves and final automatic statuses;
4. silent unknown/disputed-to-pass count derived from canonical leaves and
   final automatic statuses;
5. protected grader/gold/lock before/after equality derived from typed
   preflight and post-run hash receipts;
6. deterministic replay equality derived from registered replay receipts and
   sealed result/trace hashes;
7. denominator completeness derived from the exact 720-entry package,
   including failure, timeout, unavailable, invalid, and stopped records;
8. J-CAL and J-AUDIT status derived from their production qualification
   receipts and lifecycle ancestry.

The assessment must bind the confirmatory run/package hash, comparison lock,
case manifest, lifecycle hash, and evidence receipt membership. The public
formal factory must not accept caller-supplied pass IDs, counts, hash-check
booleans, replay booleans, or qualification booleans.

The ordered criteria and their total conjunction may remain serializable for
reporting, but deserialization must rederive and compare them against their
typed sources.

## 7. Retained failure denominator

Formal outcome composition must support the V1-retained outcomes without
inventing a new task-status or run-validity enum. The implementation may use
more specific internal reason codes, but the formal projection must follow
the existing V1 precedence and status vocabulary:

| Retained condition | V1 formal projection | Denominator/package rule |
|---|---|---|
| canonical evaluation completed | `run_validity=valid`; top-level `pass/fail/unknown/disputed` is derived only by §6.2–§6.4 | retain exactly once |
| timeout or provider/transport unavailable after the frozen retry rule | the affected authorized measurement is unavailable/`unknown`; the top-level status is then derived by §6.2–§6.4 unless a separate integrity defect makes the run invalid | retain the attempt, available evidence, cost, and case entry |
| parser error or malformed provider response | the affected Judge measurement is unavailable/`unknown`; only evaluator/schema contamination or incompatibility triggers `invalid/null` under §6.2 | retain the malformed response evidence, cost, and case entry |
| per-case or stage budget exhaustion | retain and derive `unknown` or `fail` from the evidence and frozen fusion rule; do not grant more budget or default to pass | retain completed/attempted entries and the stop reason; never delete an unfavorable arm |
| bundle/hash/schema/evaluator contamination or incompatibility | `run_validity=invalid`, `automatic_status=null` | retain as invalid with the exact integrity reason |
| §13.4 immediate-stop condition | seal the current stage as `failed/aborted`; do not fabricate outcomes for work that was never authorized or run | retain every existing result, failure, timeout, disagreement, and cost; the package is incomplete unless all frozen entries already exist |

An ordinary task-level `fail` remains a canonical evaluation result, not a
runner-failure class. Conversely, internal labels such as `backend_invalid`,
`protocol_violation`, or `stage_budget_exhausted` are reason codes only; they
must project to the V1 rows above and may not create a fifth task conclusion,
silently change `run_validity`, or bypass the frozen precedence rule.

A successful production artifact still requires canonical evaluation
evidence. A non-success artifact must use a typed failure-derived facts path
that binds:

- case, arm, request, execution authorization, and backend identity;
- frozen failure disposition and validity/status mapping;
- available raw observations/results;
- transport attempts and StageCost membership, including failed attempts;
- accounting completeness or an explicit accounting-failure reason;
- retained denominator membership.

Missing canonical success evidence must never be converted into a successful
outcome. Conversely, a legitimate retained failure must not make the complete
formal package structurally impossible.

Retained terminal records do not create a new detection denominator, a new
fault population, or a replacement signal. For the already frozen eligible
fault/case membership, detection is derived only by mechanically applying the
signed F01–F18 fault-specific predicate to its typed authorized measurands and
its predeclared missing/unavailable-evidence behavior. The implementation must
not infer detection from the terminal reason itself or invent a signal after a
failure.

## 8. Gate M lifecycle transition

The lifecycle should distinguish:

- `NOT_EVALUATED`: no complete formal confirmatory Gate package exists;
- `FAIL`: the complete sealed assessment exists and one or more unchanged
  §13.1/§13.2 criteria fail;
- `PASS`: the complete sealed assessment exists and all unchanged
  §13.1/§13.2 criteria pass.

Only a factory consuming all of the following may create a Gate M transition:

- a closed production lifecycle with all phase-specific production receipts;
- the sealed 720-entry confirmatory package;
- the evidence-derived §13.1 assessment;
- the unchanged V1 directional-bootstrap §13.2 assessment;
- the exact comparison lock and source ancestry;
- a write-once Gate assessment seal.

The transition must be append-only and terminal for that comparison block.
The boundary between `NOT_EVALUATED` and `FAIL` is evidence completeness, not
the spelling of an internal lifecycle disposition:

- a failure, stop, quarantine, or budget halt that occurs before a complete,
  sealed, common-ancestry Gate assessment can be derived remains
  `NOT_EVALUATED`; the failed/aborted stage is still retained and must not be
  described as a passing or completed Gate evaluation;
- if the exact sealed evidence required for a formal assessment exists and
  deterministically establishes a §13.1 hard-stop failure or a §13.2 threshold
  miss, the Gate result is `FAIL`, even if the lifecycle also records a
  failure/stop disposition;
- test-only, mixed-ancestry, unsealed, or structurally incomplete evidence can
  never produce either `PASS` or a formal `FAIL`.

A complete passing assessment produces `PASS`. A complete assessment that
misses any unchanged requirement produces `FAIL`, not `NOT_EVALUATED`.

The Gate transition computes no new metric and changes no threshold. It only
binds the already frozen assessment to the lifecycle and exposes an accurate
claim state.

## 9. Complete role separation

Formal readiness should model the eight V2 role categories as nine distinct
operational identity slots:

1. fixture/gold author;
2. blind reviewer A;
3. blind reviewer B;
4. adjudicator C;
5. preflight executor;
6. preflight reviewer D;
7. user/comparison-lock authority E;
8. independent lock reviewer F;
9. operational escalator G.

“Blind reviewers A and B” is one role category with two required, distinct
identity slots. No-overlap checks apply across all nine slots, and A must
differ from B.

The role manifest should bind anonymous role IDs to the allowed purpose and
phase. Preflight evidence must preserve separate executor and reviewer
records. A lock-review receipt from F must bind the exact lock reviewed, while
the authorization from E remains the approval authority; F cannot replace E.
Checkpoint envelopes, trust-root authorizations, gold records, adjudications,
preflight records, and escalation records must all be checked against the same
role manifest.

Production readiness must reject an absent role, a reused role across
prohibited categories, a test identity/key, a role-purpose mismatch, or a
signature whose root authorization does not permit the claimed phase and
purpose.

This proposal does not supply real people, role IDs, keys, custody, or
signatures. Those remain external formal-lock inputs.

## 10. Pilot and confirmatory budget and cost bindings

The existing V1 limits remain unchanged. Pilot and confirmatory budget
manifests should be rejected unless they encode, at minimum:

- Pilot Judge calls `<=240`;
- Pilot operational human escalations `<=8`;
- confirmatory Judge calls `<=800`;
- confirmatory operational human escalations `<=22`;
- confirmatory direct monetary cap `<=100 USD`, using the frozen currency and
  FX as-of bindings in the approved price manifest;
- the unchanged per-arm-case deterministic/Judge/token/retry/wall-time limits;
- separate preregistered J-CAL and J-AUDIT sub-budgets;
- exclusion of J-CAL/J-AUDIT from per-arm equal-cost comparisons;
- retention and accounting of failed calls and retries;
- explicit cap scope covering the V1 direct-cost categories.

The per-arm-case R1/R2 deterministic-check, Judge-call, token, retry,
human-escalation, deterministic-wall-time, and Judge-wall-time limits in V1
remain mandatory for both Pilot and confirmatory. J-CAL/J-AUDIT have separate
preregistered sub-budgets and are excluded from per-arm equal-cost
comparisons, but their calls remain separately identified in the applicable
phase CostVector and total cap as required by V1.

The exact approved Pilot or confirmatory values may be stricter than these
maxima but may not exceed them. A generic caller-selected `PhaseBudget` is not
sufficient for formal readiness unless a protocol validator confirms all
frozen Pilot, confirmatory, and per-arm-case constraints.

The StageCost ledger must continue to bind request/call/receipt ancestry,
provider/model, cost category, token/time/byte/retry facts, PriceManifest
ancestry, monetary facts, and the previous ledger head. Reports continue to
separate automatic per-arm execution, Subject and Judge charges, gateway/KMS
and infrastructure, human work/payment, and all-in totals.

This proposal does not invent actual quotes, prices, FX observations, gateway
fees, human payments, or provider usage. Those remain external evidence.

## 11. Detection-signal authority

The V2 oracle rules remain unchanged. A signed oracle manifest alone should
not make backend-authored convenience booleans authoritative.

For formal eligibility, each task adapter should derive its authorized signal
projection from typed canonical measurements, protected state/artifact
getters, provenance parents, failure records, and registered relation
manifests. Each formal predicate must consume a typed measurand produced by the
independently governed measurement/evaluation source named in the signed
oracle, and an independent verifier must reconstruct or re-check that
measurand from its protected source evidence.

If a backend or raw observation contains a `detection_signals` object, it may
be retained for audit only. It is never a sole source, an authoritative
measurand, or a substitute for independent derivation and verification.
Naming that field in a signed oracle manifest does not elevate the backend's
self-report or move detection authority into the Subject/backend plane.

Confirmatory adapters must cover the two frozen confirmatory tasks and all
four mutation seeds without changing F01–F18 meanings or Gate 13.2.5 scope.

## 12. Required implementation and test evidence

If this draft is approved, implementation should proceed with failing tests
first. At minimum, tests should demonstrate that:

- Pilot readiness succeeds without future J-AUDIT evidence but fails without
  the completed J-CAL and Pilot authorization ancestry;
- confirmatory readiness cannot precede a passing J-AUDIT and final
  authorization;
- future checkpoints cannot be predeclared as if already approved;
- an opaque or mismatched checkpoint target cannot authorize a run;
- provider, execution, lock, ledger, or comparison-block substitution fails;
- a 719-entry, 721-entry, duplicated, reordered, or mixed-ancestry
  confirmatory package fails;
- caller-modified gold flags cannot alter a formal outcome;
- caller-created §13.1 booleans/case lists cannot enter a formal Gate;
- timeout, failure, invalid, and budget-stopped cases remain in the exact
  denominator and can be sealed;
- mixed Pilot/confirmatory, oracle, gold, or run ancestry fails;
- every prohibited role overlap fails;
- confirmatory caps above the unchanged V1 maxima fail;
- test-only evidence cannot be upgraded by serialization, replacement, or
  boolean mutation;
- Gate M remains `NOT_EVALUATED` for incomplete evidence, becomes `FAIL` for a
  complete failed assessment, and becomes `PASS` only for a complete passing
  assessment;
- round-trip, partial write, symlink/path traversal, replay, and write-once
  attacks remain covered.

Tests may use synthetic fixtures and explicitly test-scoped verifier seams,
but they must produce a distinct `simulated_nonclaim` or test-only evidence
class. Synthetic roots, signatures, reviewers, executors, providers, and
verifiers must not create a `ProductionVerificationResult`,
`formal_result=true`, or a production-eligible package. Shared pure validation
logic may be exercised through the simulated class; a genuinely positive
production-authority path remains blocked until real externally verified
authority material exists.

## 13. External inputs intentionally not supplied by this draft

The following are not code defects and are not fabricated here:

- real Subject/Judge provider execution and protected raw responses;
- production transport and human trust roots, keys, operators, revocation
  state, and detached signatures;
- protected J-CAL/J-AUDIT contents and their independent reviews;
- actual gold reviews, adjudications, preflight execution/review, and role
  assignments;
- an approved and signed formal detection oracle;
- actual provider quotes, FX evidence, gateway/infrastructure charges, and
  human costs;
- Pilot or confirmatory comparison locks;
- formal Pilot, J-AUDIT, confirmatory, or Gate M evidence.

Until an approved amendment, conforming implementation, external inputs, and
new sealed evidence all exist, the current foundation remains foundation,
formal execution remains unauthorized, and Gate M remains unpassed.
