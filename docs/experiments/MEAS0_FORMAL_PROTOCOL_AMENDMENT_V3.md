# MEAS0 formal protocol amendment V3

Date: 2026-07-31

Status: **normative implementation amendment; offline implementation only;
formal execution not authorized**

Approval provenance: the user explicitly approved decisions D1–D12 in
[the V3 approval checklist](./MEAS0_V3_APPROVAL_CHECKLIST.md) and directed the
project to proceed with offline implementation. This records approval of the
implementation semantics in this amendment. The conversation record and this
document are not cryptographic approval evidence, do not provide a trust root,
and do not authorize provider calls, protected production-data access,
external cost, a formal comparison lock, production signatures, a formal
Pilot, J-AUDIT, confirmatory execution, Gate M evaluation, or any scientific
claim.

## 1. Authority, incorporated material, and precedence

This amendment is read together with:

- [MEAS0 Design V1](./MEAS0_DESIGN_V1.md);
- [MEAS0 formal protocol amendment V2](./MEAS0_FORMAL_PROTOCOL_AMENDMENT_V2.md);
- [the corrective V3 draft](./MEAS0_CORRECTIVE_AMENDMENT_V3_DRAFT.md);
- [the fresh replay and input-binding draft](./MEAS0_FRESH_REPLAY_AND_INPUT_BINDING_DRAFT.md).

V1 remains authoritative for the research question, tasks, F01–F18, five
arms, allowed arm signals, paired comparisons, case construction, sample
sizes, seeds, metrics, statistical procedures, confidence intervals, budget
maxima, thresholds, adoption rules, and stop/invalid rules. V2 remains
authoritative for trusted transport, Judge response and identity semantics,
instability probes, protected corpus and StageCost rules, detection-oracle
authority, human roles/signatures, and the required external execution order.

V3 adds only the approved implementation corrections needed to make the V1/V2
evidence lifecycle structurally reachable, common-ancestry-bound, and
fresh-process replayable. If an implementation of V3 would alter a frozen V1
or V2 scientific rule, the implementation must stop; a new design version is
required rather than interpreting V3 as authority for that change.

The substantive requirements in §§1–13 of the corrective V3 draft are
incorporated into this amendment, subject to the explicit D1–D12 decisions
restated below. Its draft title, status, approval-gate wording, and statements
that its decisions are unapproved are not incorporated. The incorporated
source bytes have SHA-256:

```text
fbdb98022ede0eb2bcfd0af5d3efa9cdb55e9e1e999a7c7411d79376c4eba528
```

The engineering schemas, invariants, attack requirements, and fresh-process
boundaries in §§1–11 of the fresh replay and input-binding draft are approved
for offline implementation as narrowed by D1–D12 and this amendment. Its
draft status and approval-gate wording are not incorporated. Its §13 statement
that it alone covers only the Pilot remains a scope description of that
document; the confirmatory and Gate requirements come from the corrective V3
material incorporated above. The referenced fresh-replay source bytes have
SHA-256:

```text
2bc04855b7ea3de8bf0ce1c4afd517fdb6069e40faf1a6864f89b055c9181787
```

The approval checklist remains a provenance and review aid rather than a
cryptographic approval artifact. D1–D12 are restated here so the normative
rules do not depend on the checklist retaining draft status.

## 2. Explicit non-changes

This amendment does not change:

- the two Pilot tasks or two confirmatory tasks;
- F01–F18 or their gold meanings;
- the five arms, their allowed signals, arm order, or paired comparison;
- Pilot `N=36`, confirmatory `N=144`, or the 180/720 arm-case denominators;
- Pilot mutation seed `1729`, confirmatory mutation seeds
  `[7301, 9151, 12289, 15401]`, arm-order seed `260722`, bootstrap seed `9511`,
  10,000 replicates, cluster definition, percentile convention, or confidence
  levels;
- FAR, unsafe success, detection, coverage, cost, or any other metric
  definition;
- §13.1 hard requirements, §13.2 performance thresholds, §13.3 adoption
  logic, or §13.4 stop/invalid conditions;
- Pilot Judge-call/escalation maxima `240/8`, confirmatory
  Judge-call/escalation maxima `800/22`, the confirmatory direct monetary cap
  of at most `100 USD`, or any per-arm-case V1 maximum;
- Judge qualification thresholds, gold precedence, the Evaluation Plane
  authority boundary, or the prohibition on using foundation, candidate,
  synthetic, or test-only evidence in a formal claim.

No existing foundation, candidate, Pilot, confirmatory, E0, LA0, or LA1
artifact is retroactively changed, migrated, reclassified, resealed, or
upgraded by this amendment.

The governing implementation rule is:

> No caller-supplied status, Boolean, case list, opaque hash, serialized
> verification result, or collection of individually valid objects may
> substitute for evidence-derived common ancestry at a formal boundary.

## 3. Approved decisions D1–D12

### D1 — Phase-specific readiness

Use the append-only sequence:

```text
PRE_JCAL_READY → PILOT_READY → JAUDIT_READY → CONFIRMATORY_READY
```

An earlier receipt must never require evidence that can only exist after its
authorized stage. Every receipt is factory-derived from typed raw evidence,
binds the preceding receipt where applicable, binds the current StageCost
ledger head and comparison block, and authorizes exactly one next action.
Future checkpoints cannot be predeclared as if their review and signature had
already occurred.

### D2 — Judge identity before and after J-CAL

The pre-J-CAL lock binds a Judge specification/identity object containing the
frozen provider/model identity, Prompt, rubric, parser, response schema,
sampling policy, price/budget surface, and trust policy. It contains no
calibration-derived rates, qualification status, or qualification time.

After J-CAL, a separate qualification card binds that unchanged specification
and records the evidence-derived qualification metrics and disposition. The
qualification card cannot rewrite the pre-J-CAL specification or identity.

### D3 — Typed checkpoint signature targets

Each of `pre_jcal`, `pilot_start`, `post_pilot_jaudit`, and
`confirmatory_start` signs a typed, canonical phase payload. The payload binds
the exact stage-available lock, qualification, input plan/provider manifest,
ledger pre-head, comparison block, previous checkpoint, and required evidence
ancestry. An opaque caller hash is insufficient.

Verification reconstructs the payload from typed sources and verifies the
detached signature with the phase-appropriate human trust verifier. A
signature over one payload cannot authorize another plan, provider, source
set, execution identity, phase, or comparison block.

### D4 — Exact execution inputs

Seal exact Pilot 36-case and confirmatory 144-case input manifests. Each entry
binds the protected canonical task bundle, EpisodeGraph, failure policy,
native adapter bytes/source, semantic-leaf and measurement derivation, case
identity, order, and approved source lock.

Production plans are factory-derived from these manifests. Callers cannot
provide unchecked case membership, counts, hashes, adapter selection, or
execution order. The Pilot and confirmatory manifests and packages use
distinct typed schemas; a Pilot package cannot be relabeled or expanded into
a confirmatory package.

### D5 — Public package and protected evidence vault

Use two jointly sealed evidence surfaces:

1. a public, non-leaking package containing typed manifests, hashes, ancestry,
   redacted summaries, and public receipts; and
2. an ACL-restricted and, where required by the approved lock, encrypted
   protected vault containing raw Gold, reviews/adjudication, protected
   J-CAL/J-AUDIT material, protected task/episode/failure-policy inputs, exact
   provider request/response bytes or absent-response evidence, and other
   protected sources required for replay.

Protected bytes and secrets never move into the public package. Public
references must resolve to exact protected-vault membership without exposing
mutable filesystem paths. Actual retention periods, encryption mechanisms,
custody, deletion/legal-hold policy, and production ACL identities remain
formal-lock inputs and are not invented by offline implementation.

### D6 — Exact Judge-attempt transport membership

For J-CAL, Pilot, J-AUDIT, and confirmatory, freeze phase-specific exact Judge
attempt membership, including failed attempts and retries. Bind each attempt
to canonical request bytes, response bytes or an explicit absent-response
record, invocation/presentation identity, provider/model/endpoint, transport
receipt, StageCost entry, phase plan, sequence, and previous receipt/batch
ancestry.

Execution and replay use an injected production transport verifier to
cryptographically reverify raw envelopes and approved out-of-band roots.
Structural validity, a local signer, metadata, or a key supplied only by the
package cannot satisfy production verification.

### D7 — Gold-derived outcome authority

Derive `gold_status`, `accept_allowed`, and `safety_violation` only from the
locked Gold scope/artifact membership, selected Gold records, blind reviews,
adjudication, protected source evidence, phase receipt, and signed lock
ancestry. `accept_allowed=true` only for a valid gold `pass`.

The selected record hashes and Gold binding hash enter the outcome package and
seal. Formal outcome factories do not accept replacement strings or Booleans.
Synthetic mathematical DTOs remain explicitly test-only.

### D8 — Retained-failure projection

Preserve V1 status and denominator semantics; do not add a new task status:

| Retained condition | Formal projection |
|---|---|
| canonical evaluation | valid; derive `pass/fail/unknown/disputed` through the frozen fusion rule |
| timeout or provider/transport unavailable after the frozen retry | affected measurement unavailable/`unknown`; derive the top level through frozen fusion unless a separate integrity defect makes the run invalid |
| parser error or malformed provider response | affected Judge measurement unavailable/`unknown`; only evaluator/schema contamination or incompatibility makes the run `invalid/null` |
| per-case or stage budget exhaustion | retain evidence and derive `unknown` or `fail`; never default to pass or grant an unfavorable arm more budget |
| bundle/hash/schema/evaluator contamination or incompatibility | `run_validity=invalid`, `automatic_status=null` |
| §13.4 immediate stop | seal the stage as `failed/aborted`, retain every existing result and cost, and do not fabricate work that was not authorized or run |

Internal reason codes such as `backend_invalid`, `protocol_violation`, or
`stage_budget_exhausted` may improve diagnosis but cannot create a fifth task
conclusion or silently change the V1 projection.

### D9 — Exact confirmatory common ancestry

A claim-bearing confirmatory path requires exactly 144 frozen cases and five
outcomes per case: one ordered, sealed 720-entry package. Every entry binds one
comparison block, confirmatory lock, execution authorization, case manifest,
formal oracle authority, Gold ancestry, source/evaluator manifest, budget,
provider manifest, StageCost ledger, run, and package ancestry.

The factory rejects missing, duplicate, reordered, cross-run, cross-lock,
cross-oracle, cross-Gold, cross-provider, cross-budget, or
cross-authorization entries. The five arms for a case share the same frozen
case, task/bundle, EpisodeGraph, mutation seed, failure policy, and budget
policy. Gate and bootstrap entry points consume this package rather than a
caller-created outcome mapping.

### D10 — Evidence-derived hard Gate and Gate M

Derive all ordered §13.1 criteria from the fresh-replayed, sealed
common-ancestry package, protected vault evidence, registered replay receipts,
production qualification receipts, and typed evidence membership. The public
factory accepts no caller-reported pass IDs, counts, hash Booleans, replay
Booleans, or qualification Booleans.

Gate state is determined by evidence completeness:

- structurally incomplete, mixed-ancestry, unsealed, test-only, or
  pre-assessment stopped/failed/quarantined evidence is `NOT_EVALUATED`;
- a complete sealed assessment missing any unchanged §13.1 or §13.2
  requirement is `FAIL`;
- only a complete sealed assessment satisfying all unchanged §13.1 and §13.2
  requirements is `PASS`.

A complete, deterministically assessable hard-stop remains `FAIL` even if the
lifecycle also records a stop/failure disposition. A stop before the required
assessment closure remains `NOT_EVALUATED`. The Gate transition is
append-only, write-once, and terminal for its comparison block. It computes no
new metric and changes no threshold.

### D11 — Detection authority

Formal detection measurands come only from independently governed typed
measurements, protected state/artifact getters, provenance parents, failure
evidence, and registered relation manifests named by the signed F01–F18
oracle. An independent verifier reconstructs or checks each measurand from its
protected source evidence.

Backend or raw-observation `detection_signals` fields are audit-only. They are
never a sole source, authoritative measurand, or substitute for independent
derivation and verification, even if named in an oracle manifest.

Retained terminals create no new detection denominator or fault population.
For the frozen eligible membership, detection is mechanically derived by the
signed fault-specific predicate and its predeclared missing/unavailable
behavior. A terminal reason cannot itself be converted into detection.

### D12 — Replay, source, CLI, and claim boundaries

Fresh replay receives:

- the sealed public package;
- its bound protected evidence vault;
- an approved sealed source/wheel artifact or an authority-bound source
  resolver;
- injected human-signature and transport verifiers.

A sealed source or wheel artifact is preferred to the current checkout.
Current-checkout source is never silently treated as historical authority.
Source/package-data bytes, versions, recursive local closure, and resolver
results are hash-bound and fail closed on drift.

Replay reconstructs typed sources from sealed bytes, reexecutes deterministic
measurement fusion and oracle predicates, rederives Gold facts, outcomes,
summaries, §13.1 inputs, and all relevant ancestry, and compares them with
persisted artifacts. It does not rerun providers, models, tools, or human
decisions and does not claim provider-side generation replay.

Initial integration uses explicit Python dependency injection. Arbitrary
runtime plugin loading is not approved. A later plugin/CLI loading policy
requires separate approval.

Execution-contract validity, oracle/outcome validity, and Gate claim state are
separate typed scopes:

- execute/replay/summarize may establish only the scope their complete
  evidence supports;
- replay and summarize do not calculate or upgrade Gate M;
- the Gate entry point must independently consume the fresh-replayed sealed
  evidence required by D10;
- a valid run contract is not automatically a valid outcome package or a Gate
  result.

## 4. Fresh-process archive and replay requirements

The offline implementation must provide strict, versioned codecs and
write-once stores for all raw authority material needed after the creating
process exits. At minimum, the sealed closure includes:

- design/source locks and exact source or wheel binding;
- phase readiness inputs and receipts;
- typed checkpoint targets and raw signature envelopes;
- public and protected input manifests;
- provider/backend descriptors and runtime transport policy;
- exact Judge-attempt plans, request/response or absent-response records,
  transport batches, roots/revocation snapshots, and StageCost entries;
- Gold scope/artifact/record/review/adjudication ancestry;
- task bundles, EpisodeGraphs, failure policies, native adapters, canonical
  observations, raw results, and failure records;
- Pilot and confirmatory plans, runs, outcomes, summaries, file indexes, and
  seals;
- oracle manifest/authorization and authorized typed measurands;
- lifecycle, hard-gate assessment inputs, bootstrap assessment, and Gate
  terminal receipt when those objects formally exist.

The public package uses an exact file set and non-leaking protected refs. The
protected vault uses an exact sealed membership manifest. Unknown files,
missing files, extra files, symlink ancestry, path traversal, non-canonical
serialization, partial publication, concurrent overwrite, content/hash drift,
or caller-supplied replacement ancestry fail closed.

Fresh replay begins after all creating-process typed objects have been
discarded. It must reconstruct factory-protected objects through typed
factories rather than deserializing factory tokens or verification Booleans.
Persisted derived facts and summaries are comparison targets, not independent
authority.

Execution-time verification evidence and current replay-time trust status are
reported separately. A later revocation or policy change does not rewrite the
sealed historical bytes, but current verification failure prevents a current
production-valid replay claim. The exact treatment of a later trust change in
any future scientific claim must be fixed by the applicable formal lock.

## 5. Roles, budget, and authority invariants

Formal readiness models the eight V2 role categories as nine distinct
operational identity slots because blind reviewers A and B are separate
identities. The strict V2 no-overlap policy applies across all nine slots.
Role, purpose, phase, key authorization, and root scope must agree.

Both Pilot and confirmatory budget validators enforce all frozen V1 limits:

- Pilot Judge calls `<=240` and operational human escalations `<=8`;
- confirmatory Judge calls `<=800`, operational human escalations `<=22`, and
  direct monetary cap `<=100 USD`;
- the complete per-arm-case R1/R2 deterministic-check, Judge-call, token,
  retry, escalation, deterministic-wall-time, and Judge-wall-time limits;
- separate preregistered J-CAL/J-AUDIT sub-budgets;
- J-CAL/J-AUDIT exclusion from per-arm equal-cost comparison while their calls
  remain separately identified in the applicable phase CostVector and total
  cap;
- failed calls, unavailable responses, retries, gateway/KMS, infrastructure,
  human work/payment, and the V1 direct/all-in reporting categories.

A generic caller-created phase budget cannot satisfy production readiness.
Actual prices, FX observations, provider quotes, gateway/infrastructure fees,
human payments, cap values stricter than the maxima, and retention policy are
formal-lock inputs.

## 6. Offline implementation and test-evidence rule

This amendment authorizes test-first offline implementation of D1–D12 and the
incorporated contracts. Each implementation batch must begin with failing
acceptance and attack tests, add the minimum production-shaped contract code,
and then run direct, MEAS0-wide, project-wide, fresh-process, wheel-install,
tamper, and historical replay regression appropriate to that batch.

Synthetic fixtures, fake providers, deterministic test backends, test roots,
test signatures, and test verifier seams may exercise shared parsing,
derivation, state-machine, store, and replay logic. Their outputs remain
`test_only` or `simulated_nonclaim`. They must not create or serialize a
`ProductionVerificationResult`, set `formal_result=true`, satisfy production
readiness, create a production-eligible package, or create a formal Gate
receipt.

The implementation must remain deny-all at the production boundary until
actual external roots, signatures, protected inputs, providers, reviews, and
locks are supplied. A positive production-authority unit-test seam is not
production evidence.

## 7. External inputs and actions not authorized

This amendment does not supply or authorize:

- real Subject or Judge provider execution;
- external network calls, paid APIs, or external spend;
- production transport/human trust roots, keys, operators, signatures,
  revocation state, or trusted time;
- protected J-CAL/J-AUDIT contents or production personal/sensitive data;
- actual Gold review, adjudication, preflight, isolation/ACL evidence, or role
  assignments;
- an approved and signed formal detection oracle;
- actual provider quotes, price/FX evidence, gateway/infrastructure charges,
  or human costs;
- a Pilot or confirmatory comparison lock;
- formal Pilot, J-AUDIT, confirmatory, bootstrap, Gate M, or scientific
  evidence.

Only a later, separately authorized execution using conforming implementation,
real external inputs, signed locks, protected evidence, and new sealed
artifacts may create formal evidence. Gate M remains unpassed until such
evidence is independently reviewed. LA1 formal Gate 1 remains inactive while
Gate M is unresolved.

## 8. Migration, replay, and claim preservation

- Existing artifacts are immutable and are never rewritten in place.
- Legacy readiness bundles, opaque checkpoints, Pilot-only packages, and
  historical schemas may remain explicit replay-only inputs.
- Legacy replay compatibility does not confer current production eligibility.
- New writers emit only the new versioned schemas.
- Readers use explicit version dispatch and never infer a version from missing
  fields or insert eligibility-producing defaults.
- Migration produces a new candidate with explicit source provenance; it
  cannot silently upgrade a historical artifact.
- Any source, schema, event, metric, replay, seal, failure, outcome, or Gate
  semantic change requires a new implementation version and source closure.
- E0 canonical v3, MEAS0 foundation v27, and LA1 canonical v8 remain regression
  anchors and are not resealed merely because this amendment is approved.

Completing the offline implementation proves only that the production-shaped
evidence path is structurally reachable and fails closed under test. It does
not prove provider execution, Judge validity, formal measurement quality,
arm superiority, Gate M, local-agent differentiation, Field value,
organization benefit, O1/O2, or self-improvement.
