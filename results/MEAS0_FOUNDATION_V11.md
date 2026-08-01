# MEAS0 Foundation Engineering V11

Date: 2026-07-31

Claim scope: **offline foundation and formal-contract integration only**

Gate M: **FAIL**

Canonical v27 supersedes v25 as the current foundation package. The frozen
tasks, F01-F18 faults, five arms, comparisons, metrics, budgets, thresholds,
and Gate M criteria are unchanged. This version adds exact J-CAL/J-AUDIT
invocation membership, an evidence-derived formal lifecycle, and a sealed
formal-run package store to the source closure.

## Canonical package

| Item | Value |
|---|---|
| Run | `runs/meas0/pilot/meas0-foundation-20260731-v27` |
| Lock | `runs/meas0/locks/meas0-foundation-lock-20260731-v27/preregistration.lock.json` |
| Design SHA-256 | `138c9be3f7b32e510c8a8283d88ed896e6f5286ff447a2e001a83a1a594b51c2` |
| Lock file SHA-256 | `18eb2be2d314d65e5da20c16482d141da05f85bcce43a6cadba7a3d14b7bb20e` |
| Lock seal file SHA-256 | `00895d46208778bf3a496e4d9fed377e0a85f9fdee796675716280469eda25a3` |
| Run seal file SHA-256 | `ec58d57674fb75895dc5b569e97d64da1b9200e52ff1aa239e49db3713cd7ae5` |
| Artifact bundle hash | `f1a5b83ec6cdfeab89d85e068e35e69b9fb43e384400528d0eb34acf7e3c7c64` |
| Case manifest file SHA-256 | `a6557169be54390bb3e63a28249a32cc2d47dc65e5488a952c627d2479e05cf8` |
| Case manifest logical hash | `42b33e8f7cbcc41c350ca8d1afe2be8bf39c13547782a9d9d99de0f3e9996dab` |
| Run shell | `meas0.pilot-run-shell.v11` |
| Foundation runner | `meas0.pilot-foundation.v9` |
| Formal runner source-bound version | `meas0.formal-runner-contract.v6` |
| Claim limit | `pilot_foundation_only_not_a_formal_meas0_pilot_result` |

The schema-v2 lock embeds the exact design bytes and binds 29 source files,
11 package fixtures, and 3 evaluators. The two newly bound sources are
`meas0_formal_lifecycle.py` and `meas0_formal_run_store.py`. The run directory
contains 1,281 files including its seal.

## v27 integration

### Exact J-CAL/J-AUDIT invocation membership

- `ExactInvocationManifest` binds, in one exact order, every registered probe
  call, Judge call record, transport batch entry, receipt, and StageCost entry.
- Missing, duplicate, extra, reordered, truncated, or cross-bound entries fail
  closed. Item, criterion, presentation, request, receipt, and cost ancestry
  are checked rather than inferred from aggregate counts.
- J-AUDIT now has independent manifest, probe, qualification, transport,
  ledger, and invocation-readiness inputs. It cannot reuse J-CAL qualification,
  source corpus, transport batch, or receipt.
- J-CAL and J-AUDIT protected corpora must be disjoint by protected corpus,
  source, template, and entity provenance.
- `ProbeJudgeCorpus` now carries the amended 48×6/288-call
  order/style/repeat contract. Schema/evidence validity use 288 calls,
  false-accept/false-reject use their 96 applicable calls, and each
  instability measure uses its own 48 relations.
- The legacy `JudgeCorpus` path remains a 48×2/96-call offline fixture and
  cannot be presented as production evidence.

### Evidence-derived formal lifecycle

- The fixed lifecycle is
  pre-J-CAL → J-CAL → Pilot → J-AUDIT → confirmatory → closed.
- Transitions are derived only from typed StageCost ledger decisions,
  authorization-checkpoint verification, and J-CAL/J-AUDIT qualification.
  There is no caller-supplied success Boolean.
- STOPPED, FAILED, and QUARANTINED are terminal. Hash-bound replay rejects
  tampering, skipped or reordered phases, broken ledger ancestry, and reopen.
- Qualification and authorization receipts retain their evidence class.
  A closed lifecycle becomes formal only when all four checkpoints and both
  qualifications are production-derived. Test-only or mixed chains remain
  contract-only.
- Gate M is never inferred by this lifecycle; it remains a separate,
  not-evaluated decision.

### Formal-run package store and injectable boundary

- `FormalRunPackageStore` atomically publishes a write-once package containing
  config, plan, authorization, pre/final ledgers, artifact index, 180 artifact
  leaves, run, outcome evidence, summary, and a final seal.
- Read, replay, and summarize first verify the exact file set and every file
  hash, then compare sealed bytes with typed plan/auth/ledger/artifact/run and
  outcome ancestry. Missing seals/files, symlinks, overwrite, interrupted
  publication, rename, tampering, and self-rehashed substitution fail closed.
- `FormalShellBackend` is a Python-only injectable protocol. It adds no CLI
  fake flag, readiness bypass, network call, Gate calculation, or run-hash
  cycle.
- Candidate packages remain `test_only=true` and `formal_eligible=false`.
  A production path is structurally available only from a production-mode run,
  a `FORMAL_READY` binding, artifact-derived records, and a formal oracle
  authorized by a `ProductionVerificationResult`.

### Production primitives are locally reachable but the serialized lifecycle is incomplete

- `PRODUCTION_EXTERNAL` policy preserves raw candidate oracle, signature
  envelope, human trust root, and verification policy. Serialized readiness
  replay injects an external verifier and re-verifies that raw evidence; an
  ephemeral production result is never trusted from JSON.
- Formal detection forbids legacy synthetic signals. Detection records,
  outcome package/seal, and store config/summary inherit eligibility from the
  verified run and oracle instead of accepting a caller Boolean.
- `FormalContractRun.formal_result` is derived only from production backend
  mode, a `FORMAL_READY` readiness hash, and the complete canonical
  artifact/receipt/ledger chain.
- This repository intentionally provides no production verifier
  implementation, credentials, signatures, protected corpus, or provider
  backend. A single-process Python contract path can accept injected typed
  objects, but the formal CLI and fresh-process store replay are not yet a
  complete production lifecycle. The completion gaps are recorded in
  [`MEAS0_COMPLETION_AUDIT_V1.md`](./MEAS0_COMPLETION_AUDIT_V1.md).

### Previously integrated boundaries retained

- Formal plan, authorization, request, artifact, and run retain their
  Price/StageBudget/pre-final StageCost and receipt ancestry.
- StageCost remains the only formal stop authority; failed attempts retain
  their incurred cost, while uncalled denominator placeholders create no cost.
- Readiness re-verifies raw trust and price receipts through injected
  verifier interfaces. No serialized Boolean can manufacture production
  authority.
- Four signed checkpoint positions remain frozen: pre-J-CAL, Pilot-start,
  post-Pilot/J-AUDIT, and confirmatory-start.
- The exact-180 outcome sidecar remains one-way sealed and cannot enter formal
  metrics while its oracle is candidate-only.

## Verification

- 36 frozen cases and 180 arm-case results were retained.
- All 36 cases use task-native measurement plans.
- Three replay commands returned `verified=true` with the same hash:

```text
4d4e62bf78494b96c70152b6716ef0c0cf6ccddebdbce34668aec9181a7f247d
```

- Full offline regression: `781 passed`.
- Ruff lint and formatting plus `git diff --check` passed.
- sdist and wheel built successfully. The wheel installed in a
  repository-external virtual environment and the newly source-bound
  lifecycle/store contracts imported successfully.
- No production provider, human reviewer, signing service, or paid endpoint
  was called.

## Remaining boundary

The offline foundation is complete, but the formal experiment implementation
is not complete through the production lifecycle. In addition to the external
authority and evidence below, the phase-order, confirmatory, gold/hard-gate,
retained-failure, checkpoint-target, Gate transition, and fresh-process replay
gaps in [`MEAS0_COMPLETION_AUDIT_V1.md`](./MEAS0_COMPLETION_AUDIT_V1.md) must be
resolved. Gate M still requires:

- independently administered transport and human roots, real keys, registered
  verifier backends, and checkpoint signatures;
- protected 288-call J-CAL and independent 288-call J-AUDIT corpora and probe
  bytes;
- approved price/FX receipts and phase/category caps;
- approved and signed production detection oracle;
- production Subject/Judge backend, real Judge calls, human gold/adjudication,
  OS isolation/preflight, and role assignments;
- signed pre-calibration/Pilot/confirmatory locks and formal execution;
- completed formal Pilot and confirmatory evidence.

Therefore v27 is stronger offline engineering evidence, not a formal Pilot.
Gate M remains `FAIL`.

## Reproduction

```bash
export PYTHONPATH="$PWD/src"
python -m biofield.meas0 replay \
  --run runs/meas0/pilot/meas0-foundation-20260731-v27
python -m biofield.meas0 summarize \
  --run runs/meas0/pilot/meas0-foundation-20260731-v27
```

## Prohibited conclusions

This package does not show that Gate M passed, a production verifier exists,
real API costs were observed, a formal Pilot or confirmatory run occurred,
`evaluation_plane` outperformed another arm, or D/O1/O2/Field/self-improvement
claims are supported.
