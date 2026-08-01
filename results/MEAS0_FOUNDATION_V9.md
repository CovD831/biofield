# MEAS0 Foundation Engineering V9

Date: 2026-07-31

Claim scope: **offline foundation engineering only**

Gate M: **FAIL**

Canonical v23 supersedes v21 as the current foundation package. It preserves
the frozen tasks, F01-F18 faults, five arms, comparisons, metrics, thresholds,
budgets, and foundation behavior. Its purpose is to bind the approved D1-D4
contracts through readiness, provider, Judge corpus, StageCost, detection, and
formal metric boundaries while keeping every unavailable production authority
fail closed.

## Canonical package

| Item | Value |
|---|---|
| Run | `runs/meas0/pilot/meas0-foundation-20260731-v23` |
| Lock | `runs/meas0/locks/meas0-foundation-lock-20260731-v23/preregistration.lock.json` |
| Design SHA-256 | `138c9be3f7b32e510c8a8283d88ed896e6f5286ff447a2e001a83a1a594b51c2` |
| Lock file SHA-256 | `e091429943bec40cd83c0e7a0c5fa0cbb6bde0e5b7bbea2cb9bf16adf6dae67f` |
| Lock seal file SHA-256 | `9a9008ff49ae599a459dca4526ff9f2f1795f64ee6b09fef42d4bdbee7ee79a9` |
| Run seal file SHA-256 | `6db91eb8238a5337d9ee67c618f3da0e4143238a0ab1775940db5ba887e23f7c` |
| Artifact bundle hash | `9cd99543c1beabb23f654852f4ab06c5b698e162571dff05d570151c34b2b59a` |
| Case manifest file SHA-256 | `a6557169be54390bb3e63a28249a32cc2d47dc65e5488a952c627d2479e05cf8` |
| Case manifest logical hash | `42b33e8f7cbcc41c350ca8d1afe2be8bf39c13547782a9d9d99de0f3e9996dab` |
| Run shell | `meas0.pilot-run-shell.v11` |
| Foundation runner | `meas0.pilot-foundation.v9` |
| Claim limit | `pilot_foundation_only_not_a_formal_meas0_pilot_result` |

The schema-v2 lock embeds the exact design bytes and binds 26 source files,
11 package fixtures, and 3 evaluators. The run directory contains 1,281 files,
including its seal.

## v23 additions

### Trust evidence is reverified, not caller asserted

- Formal readiness now binds separate transport and human trust roots,
  policies, a receipt batch plan, raw receipt batch, and raw human signature
  envelopes.
- Readiness re-runs verification from those raw typed artifacts. It does not
  accept a caller-supplied verification result.
- Receipt batches enforce exact membership, order, sequence, hash-chain,
  request/response ancestry, model identity, authorization, and lock binding.
- The provider adapter preserves and revalidates typed per-call receipts
  against canonical request and response bytes.
- The only implemented cryptographic verifier is deterministic and test-only.
  A valid contract-only receipt or signature therefore receives a dedicated
  production-trust-unavailable blocker rather than formal authorization.

### J-CAL/J-AUDIT cost ancestry

- Every actual Judge attempt, including schema errors, timeouts, provider
  errors, and post-call budget crossings, maps one-to-one to a StageCost entry.
- A stopped, uncalled `BUDGET_EXHAUSTED` placeholder has no cost entry.
- Judge corpora seal typed pre/final ledgers and validate ledger prefix,
  phase, provider, model, request, and attempt ancestry.
- Retry attempts are separate immutable entries linked to their predecessor.
- Current price and budget objects are explicit test-only projections;
  `production_ready` is derived false and cannot be forged.

### Artifact-derived detection

- Candidate detection now starts from a typed formal artifact and
  `ArtifactDerivedFacts`, not an arbitrary mapping plus a caller-selected
  artifact hash.
- A factory-token, hash-bound `DetectionSignalProjection` records exact case,
  task, fault, arm, authorization, artifact/facts, adapter, and oracle ancestry.
- Only registered task adapters can extract the unique allow-listed
  `detection_signals` object. Field drift, duplicate/missing signals, wrong
  phase/seed, ancestry mismatch, and projection tampering fail closed.
- The legacy mapping path must be explicitly marked synthetic and cannot enter
  an oracle-bound formal outcome.
- The current oracle remains a `test_only_candidate` with
  `formal_eligible=false`; no production predicate was invented.

### Formal claim boundary

- Formal metric and confirmatory-gate entry points accept only typed
  oracle-bound outcomes.
- Formal readiness now requires the new trust, receipt, probe, stage-budget,
  StageCost, and oracle bindings.
- Contract-valid but non-production artifacts remain insufficient. This is an
  intentional representation of missing authority, not a partially passed
  Gate M.

## Verification

- 36 frozen cases and 180 arm-case results were retained.
- All 36 cases use task-native measurement plans.
- Three replay commands returned `verified=true` and the same replay hash:

```text
3bf819757e7f143c8eef74e461d9b53d26d48e7f3c6b18501fe34bac6280279d
```

- Full regression: `735 passed`.
- Ruff lint passed for the full source/test tree; Ruff format passed for all
  files changed in this integration round. The repository-wide format check
  still reports 92 pre-existing files outside this change set.
- sdist and wheel built successfully without isolation.
- The wheel installed in an external virtual environment; the trust,
  StageCost, provider, readiness, Judge corpus, and detection modules imported,
  and the packaged mutation fixture was present.
- No production provider was called.

## Remaining boundary

Production readiness still lacks:

- independently administered transport and human trust roots and real keys;
- a production receipt verifier and aggregate batch authorization;
- protected production J-CAL/J-AUDIT corpus and independently registered probe
  bytes;
- approved production PriceManifest and phase/category budgets;
- an approved, signed, fault-specific production detection oracle;
- production Subject/Judge backend, real Judge calls, human gold/adjudication,
  OS isolation/preflight, role assignments, and a signed comparison lock;
- formal Pilot and confirmatory execution.

Therefore v23 is stronger offline integration evidence, not formal experiment
evidence. Gate M remains `FAIL`.

## Reproduction

```bash
export PYTHONPATH="$PWD/src"
python -m biofield.meas0 replay \
  --run runs/meas0/pilot/meas0-foundation-20260731-v23
python -m biofield.meas0 summarize \
  --run runs/meas0/pilot/meas0-foundation-20260731-v23
```

## Prohibited conclusions

This result must not be cited as evidence that Gate M passed, a formal Pilot or
confirmatory experiment ran, `evaluation_plane` outperformed another arm, or
D/O1/O2/Field/self-improvement claims are supported.
