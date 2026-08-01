# MEAS0 Fresh Replay and Input Binding Draft

> **NON-NORMATIVE — NOT APPROVED**
>
> This document is an engineering design draft. It does not amend the frozen
> MEAS0 design, preregistration, metrics, Gate rules, statistical rules, claim
> scope, case set, arm order, budgets, or evidence requirements. None of the
> proposed schemas or entry points may be treated as approved until they are
> separately reviewed, versioned, and incorporated into the normative design.

## 1. Purpose

The current typed Python path can execute and seal a formal-eligible run while
the original `FormalPilotPlan`, `FormalContractRun`, formal oracle, and derived
outcomes remain in memory. It cannot yet restore and reverify that package in a
fresh process from sealed bytes and external verifier implementations alone.

This draft proposes the minimum additional contracts needed to:

1. bind every production Pilot input to approved readiness evidence;
2. seal the raw authority material needed for later verification;
3. restore typed run evidence without rerunning production providers;
4. rederive detection and outcomes instead of trusting serialized derived
   booleans;
5. expose fail-closed CLI and Python boundaries; and
6. preserve the rule that replay and summarize do not calculate Gate M.

## 2. Design principles

- Production authority is established only by injected external
  `ProductionSignatureVerifier` implementations.
- `ProductionVerificationResult` is ephemeral. It must never be serialized,
  accepted from JSON, or promoted from a boolean.
- Production providers are required for initial execution, but not replay.
- Replay operates on sealed raw evidence. It does not repeat external model,
  tool, human, or provider actions.
- Every restored factory-protected object is reconstructed through a typed
  factory that rechecks its ancestry. Factory tokens are never read from disk.
- Derived facts, projections, detection records, and outcomes are recomputed
  when their authoritative inputs are available.
- Persisted summaries are compared with rederived summaries. They are not
  treated as an independent signal source.
- Candidate evidence remains fixed as `test_only=true` and
  `formal_eligible=false`.
- This design adds no scientific metric and makes no Gate decision.

## 3. Proposed `FormalPilotInputManifest`

### 3.1 Role

`FormalPilotPlan` currently freezes the 36-case order, five-arm order, budget
policy, pricing, and StageCost pre-ledger ancestry. It does not independently
bind each case's task bundle, episode, failure policy, semantic leaf count, or
measurement count to readiness.

A new `FormalPilotInputManifest` would close that gap. It must be included in
the material bound by the `PILOT_READY` receipt, included in
`FormalLockBindings`, referenced by the public package, and sealed together
with its protected Pilot input corpus.

### 3.2 Proposed schema

```text
FormalPilotInputManifest
  schema
  manifest_id
  version
  case_scope_manifest_hash
  source_lock_hash
  protected_pilot_input_corpus_hash
  entries[36]
  manifest_hash

FormalPilotInputEntry
  execution_case_index
  case_id
  task_id
  fault_id
  task_measurement_bundle_hash
  sealed_episode_hash
  failure_policy_hash
  protected_bundle_ref_hash
  protected_episode_ref_hash
  protected_failure_policy_ref_hash
  semantic_leaf_count
  measurement_count
  native_adapter_id
  native_adapter_version
  native_adapter_source_hash
  native_adapter_bytes_hash
  protected_adapter_ref_hash
  entry_hash
```

Required invariants:

- Entries exactly match the frozen 36 Pilot cases and order.
- `execution_case_index` is exactly `0..35`.
- Case, task, and fault identities match `FormalCaseScopeManifest`.
- Task bundle and episode hashes are recomputed from typed source objects.
- Episode bundle identity matches the task measurement bundle.
- Failure policy hash is recomputed from a typed, sealed failure-policy
  contract; the factory does not accept a caller-provided hash.
- Counts are derived from the frozen measurement graph, not supplied as
  unchecked metadata.
- Adapter identity, canonical adapter bytes, and source hash match the approved
  task adapter binding and the source lock. Formal detection authority remains
  a separate V3 dependency described in §6.4.
- Every protected reference resolves inside the sealed Pilot input corpus and
  its content hash matches the corresponding entry.
- `protected_pilot_input_corpus_hash` commits to the exact 36-case protected
  input membership and order.
- The manifest is content-addressed and contains no mutable path reference.

### 3.3 Required lock binding

The normative design would need to approve a new
`formal_pilot_input_manifest` entry in `REQUIRED_FORMAL_LOCK_BINDINGS`.
Until that approval occurs, this draft does not alter the frozen lock list.

## 4. Production plan factory

Production plans should not be created by directly calling the dataclass
constructor. The proposed entry point is:

```python
FormalPilotPlan.create_from_readiness(
    *,
    pilot_ready_receipt: PilotReadyReceipt,
    input_manifest: FormalPilotInputManifest,
    protected_input_corpus: ProtectedPilotInputCorpus,
) -> FormalPilotPlan
```

The factory must:

1. require a typed `PILOT_READY` phase receipt, derived only after J-CAL and
   the reviewed Pilot-start authorization;
2. verify the input manifest's lock and case-scope bindings;
3. verify and open the sealed protected input corpus, then recompute every
   entry from typed bundles, episodes, failure policies, and adapter bytes;
4. derive `FormalPilotCaseInput` values rather than accepting hashes, counts,
   or failure-policy digests from the caller;
5. take price, StageBudget, StageCost pre-ledger, arm order, and budget policy
   from the phase receipt and its bound readiness ancestry;
6. construct `FormalPilotPlan`; and
7. compare the resulting plan hash with any preregistered plan hash once such a
   binding is approved.

Fresh-process plan restoration should call the same factory and require exact
equality with sealed `plan.json`. A separate permissive production
`FormalPilotPlan.from_dict` is not sufficient.

## 5. Additional sealed raw material

The formal run store currently seals plan, authorization, ledgers, 180
artifacts, run, outcome evidence, summary, and their file hashes. Fresh replay
also needs the following sealed files.

### 5.1 Public package and protected evidence vault

The formal run has two distinct storage surfaces:

1. a public/non-sensitive package containing schemas, non-leaking metadata,
   hashes, authority-bound references, summaries, and seals; and
2. an ACL-restricted and encrypted protected evidence vault containing raw
   Pilot inputs, Gold/review/adjudication records, protected Judge materials,
   and exact external request/response bytes.

Raw Gold, protected J-CAL/J-AUDIT content, review rationales, raw provider
responses, secrets, private keys, and other protected material must not enter
the public package. A public manifest exposes only the minimum reviewed
metadata, content hashes, vault object identifiers, and authority receipts
needed to bind membership without leaking content.

The vault contract must freeze:

- encryption and key-reference metadata without embedding keys;
- ACL principals and permitted operations;
- write-once/finalization behavior;
- content-addressed object hashes and byte counts;
- retention, deletion, and legal-hold policy references;
- audit events for create/read/verify operations; and
- the public package hash or package identity to which the vault is bound.

Replay must fail closed when a required protected object cannot be resolved,
read under the approved principal, decrypted, hash-verified, or matched to its
public reference. Copying only the public package is not a complete fresh
replay archive.

### 5.2 Protected Pilot input corpus

The protected vault must contain a canonical, ordered
`ProtectedPilotInputCorpus` with exactly 36 entries. Each entry stores:

- exact canonical `TaskMeasurementBundle` bytes;
- exact canonical `SealedEpisode` bytes and all episode objects needed for
  strict restoration;
- the typed failure-policy contract bytes, not only its hash;
- exact approved task-adapter bytes or an authority-bound immutable source
  artifact reference; and
- the case/manifest identity needed to prevent cross-case substitution.

The public `FormalPilotInputManifest` binds the protected corpus root and every
entry/reference hash. The input corpus is independent of the 180 output
artifacts; replay must not reconstruct pre-execution inputs by selecting or
trusting an output arm artifact.

### 5.3 Pilot readiness receipt and protected authority material

The public package stores the typed `PILOT_READY` receipt and non-leaking
ancestry hashes. The protected vault stores the raw material required to
rederive that receipt, including:

- candidate detection oracle;
- `FormalDetectionOracleAuthorization` with raw signature envelope, human
  trust root, and production-external verification policy;
- transport roots, policies, batch plans, and raw receipts;
- human signature envelopes and checkpoint material;
- Judge qualification evidence;
- Gold records, review records, and adjudication records;
- preflight, isolation, ACL, price, StageCost, and budget evidence; and
- `FormalPilotInputManifest`, if approved.

Fresh replay must rederive `PILOT_READY` with injected verifiers. It must
verify the preceding `PRE_JCAL_READY` receipt, the production-derived J-CAL
qualification, and the reviewed Pilot-start checkpoint. It must not require
J-AUDIT output, a confirmatory lock, or final confirmatory authorization.
Stored readiness reports are compared with rederived reports and are never
trusted independently.

### 5.4 `source_lock.json` and source closure

The package must contain the exact preregistration/source-lock bytes, not only
their hash. Replay must:

- verify the sealed file hash;
- recompute the source-lock hash;
- match it to readiness lock bindings, the input manifest, and the outcome
  evidence seal.

The exact source-restoration mechanism remains an approval choice. One of the
following must be selected before implementation:

1. seal the exact source archive or built wheel, dependency artifacts, and
   environment manifest needed for replay, then verify them against the lock;
   or
2. seal an authority-bound receipt for an immutable content-addressed source
   artifact and retrieve/verify that artifact during replay.

The current checkout must never be silently substituted. Exact lock bytes
alone prove what hashes were approved but do not supply the source bytes
needed to execute source-closure checks. A mutable path alone is insufficient.

### 5.5 `pilot_transport_policy.json`

Pilot runtime Judge receipts require an explicit production verification
contract. It must define:

- trust domain and allowed root hashes;
- permitted provider, model, purpose, phase, and claim scope;
- exact batch membership or a canonical rule for deriving it from the plan;
- request, invocation, presentation, criterion, authorization, and sequence
  bindings;
- retry and duplicate rules;
- revocation snapshot and signing-time policy; and
- whether one canonical batch or approved per-provider/per-stage batches cover
  the exact registered Judge attempts.

Membership is defined by Judge attempts, including failed attempts and allowed
retries, not by the 180 arm-case result denominator. Arms and cases that make no
Judge call do not acquire a synthetic transport member. The expected attempt
plan must be derived from the frozen MeasurementGraph, presentation schedule,
arm policy, and retry policy, with any runtime absence/failure represented
explicitly rather than deleted.

This contract must be included in readiness and the source lock. Reusing a
J-CAL or J-AUDIT policy is forbidden unless the approved design explicitly
defines identical scope and membership.

### 5.6 Pilot exact request/response material

For every Pilot Judge attempt, including a failed attempt, the protected vault
must contain or resolve:

- exact request bytes and byte count;
- exact response bytes and byte count, or an explicit absent-response record;
- the signed transport receipt and registered batch entry;
- the parser input/output ancestry;
- the public artifact and StageCost entry references; and
- the vault readback receipt binding object hash, ACL decision, and package.

Replay verifies the signed receipt with the injected transport verifier,
rehashes the protected bytes, and requires exact agreement with the receipt,
parser input, artifact, and StageCost ancestry. A parsed `payload_json` or
response hash without accessible exact bytes is insufficient for this
fresh-replay claim.

### 5.7 Store seal changes

All new files must be added to the exact file set and `file_sha256` manifest.
The store seal should also expose, as redundant checked bindings:

- `PILOT_READY` receipt hash and prior phase-receipt hashes;
- source-lock hash;
- Pilot input manifest hash;
- protected Pilot input corpus root;
- protected evidence vault manifest hash;
- Pilot request/response membership root;
- oracle authorization contract hash;
- Pilot transport policy hash; and
- Gold binding hash.

These exposed hashes do not replace the sealed files.

## 6. Typed restore requirements

### 6.1 Plan and authorization

Required strict loaders or restore factories:

- `FormalBackendDescriptor.from_dict`;
- `FormalPilotCaseInput.from_dict`;
- `FormalPilotPlan.restore_from_sealed(...)`, implemented through the
  production plan factory;
- `FormalExecutionAuthorization.restore(...)`.

Authorization restore must call `FormalExecutionAuthorization.create` with the
restored plan, revalidated `PILOT_READY` receipt and its readiness ancestry,
execution identity, mode, and provider descriptors. The resulting dictionary
must exactly equal sealed `authorization.json`. The authorized provider
descriptor manifest must be a typed member of the Pilot-start checkpoint, not
an execution-time caller choice.

### 6.2 Arm-case artifacts and run

Required strict loaders or restore factories:

- `FormalCostArtifact.from_dict`;
- `JudgeCallCostArtifact.from_dict`;
- `RawObservationArtifact.from_dict`;
- `RawResultArtifact.from_dict`;
- `FormalFailureArtifact.from_dict`;
- `CanonicalEvaluationBinding.from_dict`;
- `FormalArmCaseArtifact.restore`;
- `FormalContractRun.restore`.

`FormalArmRequest`, `BackendExecution`, `BackendFailureEvidence`, and provider
objects do not need persistence because replay does not execute providers.

Run restoration must recheck:

- exact 36-by-five denominator and order;
- provider descriptor and authorization ancestry;
- request, artifact, receipt, and StageCost membership;
- duplicate receipt and invocation rejection;
- pre-ledger/final-ledger prefix ancestry;
- stage-stop derivation;
- canonical evaluation for each successful production artifact;
- production mode and `PILOT_READY` phase-receipt binding; and
- exact equality with sealed `run.json` and its declared hash.

### 6.3 Canonical measurement binding

The measurement contracts currently serialize through `JsonContract` but do
not provide a generic trusted decoder. `CanonicalEvaluationBinding` restoration
requires strict parsers for:

- `TaskFrame`;
- `Goal` and `GoalGraph`;
- `Requirement` and `RequirementGraph`;
- `MeasurementSpec` and `MeasurementGraph`;
- `TaskMeasurementBundle`;
- `EpisodeEvidence`, episode nodes/edges, and `EpisodeGraph`;
- `SealedEpisode`;
- `MeasurementObservation`; and
- `EvaluationResult`.

These may be implemented as private codec functions rather than public
`from_dict` methods. After parsing, replay must call `fuse_evidence` and require
the rederived `EvaluationResult` to equal the sealed value.

### 6.4 Outcome restoration by rederivation

Do not add permissive disk factories for `ArtifactDerivedFacts`,
`DetectionSignalProjection`, or `DerivedDetectionRecord`.

For every restored arm-case artifact:

1. rederive `ArtifactDerivedFacts`;
2. rederive the signal projection using the freshly authorized formal oracle
   and an approved authoritative task adapter;
3. derive the detection record from that projection;
4. derive Gold flags from the protected, phase-bound Gold records;
5. construct the oracle-bound outcome through its factory; and
6. compare every rederived object with the corresponding sealed JSON.

The package and evidence seal are then recomposed and required to match the
sealed outcome bundle in canonical content. The sealed file-byte hash is
verified separately so that logical rederivation is not confused with
non-canonical JSON formatting.

Formal detection remains dependent on the corrective work proposed in
`MEAS0_CORRECTIVE_AMENDMENT_V3_DRAFT.md`. Re-reading a backend-authored
`detection_signals` object and obtaining the same booleans is not independent
rederivation. Until an approved adapter derives authorized projections from
typed canonical measurements, protected getters, provenance/failure records,
and registered relation manifests, fresh replay must not classify the
detection record or outcome as formal eligible.

## 7. Gold binding

Production outcome factories must not accept free `gold_status`,
`accept_allowed`, or `safety_violation` arguments.

The production factory should receive the revalidated `PILOT_READY` receipt,
resolve its protected Gold ancestry, and:

- group `GoldRecord` values by case;
- require the unique top-level tuple already enforced by readiness;
- derive the outcome's Gold fields from that tuple;
- bind the selected Gold record hashes and Gold scope hash; and
- require `run.authorization` to match the `PILOT_READY` receipt and its
  protected Gold-vault ancestry.

The outcome package and seal should include:

- `pilot_ready_receipt_hash` and required prior phase-receipt hashes;
- `gold_scope_hash`; and
- a canonical `gold_binding_hash` over the exact selected Gold record hashes.

Candidate factories may retain their existing test-only interface, but cannot
produce formal-eligible evidence.

Raw Gold, review, adjudication, rationale, and protected evidence-ref content
remain in the protected vault. The public package carries only the approved
non-leaking membership hashes and authority-bound references.

## 8. External verifier boundaries

### 8.1 Human verifier

The human-domain `ProductionSignatureVerifier` is injected at:

1. phase-receipt and protected authority-material restoration;
2. human approval and checkpoint revalidation; and
3. formal detection-oracle authorization replay.

The formal oracle is ephemeral and must be recreated in each process from the
sealed raw authorization contract in the protected authority material. No
duplicate standalone oracle-authorization file is introduced.

### 8.2 Transport verifier

The transport-domain `ProductionSignatureVerifier` is injected at:

1. readiness transport evidence replay;
2. price receipt verification;
3. Judge qualification transport verification; and
4. every Pilot runtime receipt or its exact canonical batch.

Structural receipt/ledger agreement is necessary but does not replace
production signature verification.

### 8.3 Provider boundary

Five production provider implementations are injected only into the initial
execution entry point. Each must expose a production descriptor, enforce
timeouts, and return typed evidence.

Replay and summarize must reject provider arguments. Their absence proves that
replay is evidence verification, not experiment re-execution.

### 8.4 Execution-time basis and current replay status

Fresh replay reports two distinct trust views:

1. the execution-time verification basis sealed with the package, including
   the approved policies, root/revocation snapshot hashes, receipts, and
   authorization sequence; and
2. the current replay verification status returned by the injected verifiers
   under the currently approved revocation/trust view.

The sealed scientific artifacts, run hash, and original summary do not change
when a key is later revoked or a trust policy changes. The new replay report
may record that current trust verification now fails or is superseded. It must
not silently rewrite the execution-time summary, claim that a different
result was originally observed, or require replay-time trust status to have
the same hash across dates.

## 9. Proposed Python entry points

Initial execution:

```python
execute_formal_pilot(
    *,
    pilot_ready_receipt_path: Path,
    source_lock_path: Path,
    protected_input_vault: ProtectedEvidenceVault,
    provider_registry: FormalProviderRegistry,
    human_verifier: ProductionSignatureVerifier,
    transport_verifier: ProductionSignatureVerifier,
    output_directory: Path,
    package_id: str,
) -> FormalRunPackageSnapshot
```

Fresh replay:

```python
FormalRunPackageStore.restore_and_replay(
    package_directory,
    *,
    protected_evidence_vault: ProtectedEvidenceVault,
    human_verifier: ProductionSignatureVerifier,
    transport_verifier: ProductionSignatureVerifier,
) -> FormalRunReplayReport
```

Fresh summarize:

```python
FormalRunPackageStore.restore_and_summarize(
    package_directory,
    *,
    protected_evidence_vault: ProtectedEvidenceVault,
    human_verifier: ProductionSignatureVerifier,
    transport_verifier: ProductionSignatureVerifier,
) -> FormalRunLifecycleSummary
```

Both replay operations must begin from sealed bytes and must not accept
caller-supplied plan, run, oracle, outcomes, summary, or eligibility booleans.

The Python API uses explicit dependency injection by default. Verifier,
provider, vault, and source-artifact implementations are selected by the
trusted deployment environment, not discovered from evidence inside the run
package.

## 10. CLI behavior boundary

This draft specifies CLI behavior, not a new command grammar or a general
plugin system. An implementation may extend the existing
`python -m biofield.meas0 run|replay|summarize` commands or provide another
separately approved interface, but it must preserve these semantics:

- formal run loads one sealed `PILOT_READY` receipt, one exact source-lock
  binding, one protected input/evidence vault, and five approved production
  providers before creating the output directory;
- replay and summarize load only sealed package/vault material and injected
  human/transport verifiers; they reject provider arguments;
- formal and foundation paths remain distinct and cannot relabel each other;
- secrets and private keys never appear in the package or command arguments;
  and
- a missing dependency, unresolved protected object, or unapproved
  implementation fails before producing a formal summary.

The preferred initial implementation is Python dependency injection under a
trusted deployment configuration. This draft does not approve arbitrary
runtime plugin discovery or `--plugin ID` loading. If a future CLI plugin
policy is proposed, it must separately define an allowlist, entry-point and
implementation hashes, version/config identity, domain separation, source or
deployment attestation, and code-execution security boundary. A plugin ID
alone is not evidence.

The existing foundation `run`, `replay`, and `summarize` paths must remain
separate. Formal commands must route to `FormalContractRun` and
`FormalRunPackageStore`, never relabel a foundation result.

## 11. Required attack and regression tests

### 11.1 Input-manifest and plan attacks

- Missing, duplicated, or reordered case.
- Task bundle or episode swapped between cases.
- Changed failure-policy bytes, hash, or protected reference.
- Missing, reordered, or cross-package protected Pilot input object.
- Forged semantic leaf or measurement count.
- Adapter source hash changed after readiness.
- Plan reconstructed from a different phase receipt or protected input corpus.
- Direct dataclass construction or `replace()` used to bypass the production
  factory.

### 11.2 Authority attacks

- Serialized `ProductionVerificationResult` supplied as input.
- Candidate oracle boolean-upgraded to formal eligible.
- Oracle envelope signs a different candidate, purpose, phase, or root.
- Test-only root, envelope, algorithm, policy, or verifier used in production.
- Human and transport trust domains confused.
- Revoked, expired, or unauthorized key.
- Readiness report copied from a different phase receipt or ancestry bundle.
- Pilot replay incorrectly requires future J-AUDIT or confirmatory evidence.
- Pilot-start authorization is used before J-CAL qualification.

### 11.3 Runtime receipt attacks

- Structurally valid receipt with invalid signature.
- Receipt signed under the readiness/J-CAL policy but outside Pilot scope.
- Request, authorization, provider, model, criterion, or presentation mismatch.
- Duplicate receipt hash or invocation ID.
- Reordered, missing, or extra batch member.
- Retry inserted without allowed ancestry.
- StageCost entry detached from its raw receipt.
- Exact protected request or response bytes differ from the signed receipt.
- Parsed response is detached from the protected raw response bytes.
- Batch membership is incorrectly inferred from all 180 arm-cases instead of
  the registered Judge attempts.

### 11.4 Artifact and run attacks

- Missing or extra artifact.
- Reordered arm-case pair.
- Artifact copied from another run or authorization.
- Canonical evaluation result changed and outer hashes recomputed.
- Measurement bundle, episode, observations, or evaluator set changed.
- Stage ledger truncated, extended, or given a different prefix.
- `formal_result`, `test_only`, `formal_eligible`, or claim scope changed
  independently.

### 11.5 Gold and outcome attacks

- Persisted Gold flags changed and outer hashes recomputed.
- Gold record from a different case substituted.
- Gold scope, reviewer, or adjudication ancestry changed.
- Candidate detection record inserted into a production package.
- Projection or adapter source changed.
- Outcome package replayed against a different `PILOT_READY` receipt or
  protected Gold ancestry.

### 11.6 Store attacks

- Partial publication without seal.
- File modified with seal unchanged.
- File and outer hash recomputed without valid authority evidence.
- Extra file, missing file, renamed package directory, or duplicate path.
- Symlink or hardlink escape.
- Protected vault object missing, ACL-denied, incorrectly decrypted, or
  detached from its public reference.
- Store replay attempted with caller-supplied typed ancestry.
- Replay attempted without external verifiers.
- Replay or summarize attempts to calculate Gate M.

### 11.7 Positive and seam tests

- A serialized test phase receipt and protected input corpus are restored with
  test-scoped verifier seams as `simulated_nonclaim` evidence.
- A complete simulated 36-by-five run is created without monkeypatching
  readiness or backend validation, but remains non-formal and non-claim-bearing.
- The package is closed, the creating process discards every typed object, and
  a new process restores and verifies it from disk.
- Fresh replay produces the same run, package, summary, and file hashes.
- Candidate packages continue to round-trip as test-only.
- A replay under a changed current revocation view preserves the sealed
  execution-time artifacts while reporting the new current trust status
  separately.

Production-verifier interface doubles used in tests must be clearly scoped
test dependencies.
They may exercise parsing, injection, and fail-closed boundaries but must
produce only `simulated_nonclaim` or test-only evidence. They must not create a
`ProductionVerificationResult`, `formal_result=true`, a production-eligible
outcome package, or scientific approval. A true positive formal replay remains
blocked until real externally verified authority material exists.

## 12. Approval gates for this draft

Before implementation, the project owner must explicitly approve:

1. the `FormalPilotInputManifest` schema and new lock binding;
2. the protected Pilot input corpus and public-package/protected-vault schemas;
3. the Pilot runtime transport policy and Judge-attempt membership rule;
4. exact request/response retention, ACL, encryption, and readback policy;
5. Gold record selection and `gold_binding_hash`;
6. the additional public and protected sealed file sets;
7. claim-scope terminology for `FormalContractRun` and outcome evidence;
8. whether fresh replay uses sealed source artifacts or an immutable
   authority-bound source receipt; and
9. any later CLI loading policy beyond the default Python dependency-injection
   boundary.

Until those decisions are approved, the current formal execution and replay
limitations must remain visible and fail closed.

## 13. Scope limit relative to confirmatory and Gate M

This draft closes only the proposed fresh-process execution/replay boundary for
the 36 × 5 formal Pilot. Even if every item in this draft is implemented, it
does not by itself provide:

- phase receipts after Pilot;
- a sealed 144 × 5 confirmatory runner or common-ancestry package;
- retained confirmatory failure outcomes;
- an evidence-derived §13.1 assessment;
- the claim-bearing §13.2 Gate package; or
- a Gate M lifecycle transition.

Those remain dependencies of the separately proposed
`MEAS0_CORRECTIVE_AMENDMENT_V3_DRAFT.md`. Replay and summarize in this draft
must continue to refuse Gate M calculation.
