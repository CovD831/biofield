# MEAS0 Foundation Engineering V10

Date: 2026-07-31

Claim scope: **offline foundation and formal-contract integration only**

Gate M: **FAIL**

Canonical v25 supersedes v23 as the current foundation package. The frozen
tasks, F01-F18 faults, five arms, comparisons, metrics, budgets, thresholds,
and Gate M criteria are unchanged. This version source-binds the end-to-end
trust, price, StageCost, authorization-checkpoint, receipt, and
artifact-derived outcome contracts implemented after v23.

## Canonical package

| Item | Value |
|---|---|
| Run | `runs/meas0/pilot/meas0-foundation-20260731-v25` |
| Lock | `runs/meas0/locks/meas0-foundation-lock-20260731-v25/preregistration.lock.json` |
| Design SHA-256 | `138c9be3f7b32e510c8a8283d88ed896e6f5286ff447a2e001a83a1a594b51c2` |
| Lock file SHA-256 | `083889f710497d5705bcb6a9007e346a111570053d9e1e21d6517b012e861639` |
| Lock seal file SHA-256 | `773217f36ae45f2e6e0843bf5080f8bcf85d3c7d064b0c11999d4b8e87d37f17` |
| Run seal file SHA-256 | `0d9bbe7055e125b266549816d30075dad9c698e23beeb28652b79926dd786a11` |
| Artifact bundle hash | `4dcb76f20c105d771a1e4a0477a705bad5cd00445b096dbd795c20036e979d30` |
| Case manifest file SHA-256 | `a6557169be54390bb3e63a28249a32cc2d47dc65e5488a952c627d2479e05cf8` |
| Case manifest logical hash | `42b33e8f7cbcc41c350ca8d1afe2be8bf39c13547782a9d9d99de0f3e9996dab` |
| Run shell | `meas0.pilot-run-shell.v11` |
| Foundation runner | `meas0.pilot-foundation.v9` |
| Formal runner source-bound version | `meas0.formal-runner.v6` |
| Claim limit | `pilot_foundation_only_not_a_formal_meas0_pilot_result` |

The schema-v2 lock embeds the exact design bytes and binds 27 source files,
11 package fixtures, and 3 evaluators. The added source is
`meas0_formal_outcomes.py`. The run directory contains 1,281 files including
its seal.

## v25 integration

### StageCost is the formal runner's only stop authority

- Formal plan, authorization, and request bind typed `PriceManifest`,
  `StageBudgetManifest`, and the StageCost pre-ledger.
- Artifacts bind their request and exact Judge-attempt → StageCost entry
  ancestry. The run seals typed pre/final ledgers and the final ledger hash.
- Timeout, provider error, malformed response, and post-call budget crossing
  retain every actual attempt and its cost. An uncalled denominator placeholder
  does not create a cost entry.
- Once a budget triggers, no new request may begin. Remaining attempts already
  incurred by the same executed request may be appended consecutively; retry,
  new request, provider/model/category/arm drift, and non-contiguous additions
  are rejected.

This is an implementation of the approved V2 append-only stage-ledger rule.
It does not change any cap or experimental threshold.

### Receipt and cost ancestry

- Signed transport receipt, transport batch entry, invocation, request,
  authorization, provider/model, artifact, and StageCost entry are
  cross-checked.
- Missing, duplicate, reordered, truncated, tampered, or misbound evidence
  fails closed across the complete formal run.
- The implemented deterministic verifier remains test-only. Production
  authorization cannot be obtained by changing a serialized Boolean.

### Production-capable interfaces remain unavailable

- A typed verifier authority and sealed result factory allow a future
  independently registered transport/human verification backend.
- Readiness re-verifies raw evidence through the injected verifier. With no
  approved production backend/root/key, it returns a production-unavailable
  blocker.
- `PriceQuote`, `PriceQuoteReceipt`, and their receipt contract re-derive the
  `PriceManifest`; candidate quote evidence remains non-production.
- A four-stage authorization-checkpoint manifest freezes exact
  pre-J-CAL, Pilot-start, post-Pilot/J-AUDIT, and confirmatory memberships,
  including phase, purpose, role, payload, and ledger pre-head. No real
  signers or signatures were invented.

### Exact outcome package and sidecar seal

- The post-run composition requires exact 36×5/180 coverage and binds the
  formal run, authorization, every artifact, derived facts, signal projection,
  oracle entry, adapter source, detection record, and oracle-bound outcome.
- A separate evidence seal avoids a run-hash cycle while binding the run hash,
  package hash, oracle, source lock, authorization, and ordered 180 artifact
  references.
- Its store is atomic and write-once and re-verifies typed ancestry on read.
  Overwrite, interrupted publication, missing files, symlinks, tampering, and
  self-rehashed source-lock substitution are rejected.
- The available oracle is still a candidate. Every resulting package and seal
  has `test_only=true` and `formal_eligible=false`.

## Verification

- 36 frozen cases and 180 arm-case results were retained.
- All 36 cases use task-native measurement plans.
- Three replay commands returned `verified=true` with the same hash:

```text
c377a5149325014ea331fc462644dee6452823550a38452f1ce0e295bd58da23
```

- Full offline regression before documentation-only updates: `756 passed`.
- Ruff lint, changed-file formatting, and diff checks passed.
- sdist and wheel built successfully. The wheel installed in a repository-
  external virtual environment; formal runner v6, verifier/checkpoint/price
  contracts, outcome evidence store, LA1 runner v5, and packaged fixtures
  imported successfully.
- No production provider, human reviewer, signing service, or paid endpoint was
  called.

## Remaining boundary

The code now exposes production-capable interfaces, but production authority
and evidence do not exist. Gate M still requires:

- independently administered transport and human roots, real keys, registered
  verifier backends, and checkpoint signatures;
- protected J-CAL/J-AUDIT corpus and probe bytes;
- approved price/FX receipts and phase/category caps;
- approved and signed production detection oracle;
- production Subject/Judge backend, real Judge calls, human gold/adjudication,
  OS isolation/preflight, and role assignments;
- signed pre-calibration/Pilot/confirmatory locks and formal execution;
- completed formal Pilot and confirmatory evidence.

Therefore v25 is stronger offline engineering evidence, not a formal Pilot.
Gate M remains `FAIL`.

## Reproduction

```bash
export PYTHONPATH="$PWD/src"
python -m biofield.meas0 replay \
  --run runs/meas0/pilot/meas0-foundation-20260731-v25
python -m biofield.meas0 summarize \
  --run runs/meas0/pilot/meas0-foundation-20260731-v25
```

## Prohibited conclusions

This package does not show that Gate M passed, a production verifier exists,
real API costs were observed, a formal Pilot or confirmatory run occurred,
`evaluation_plane` outperformed another arm, or D/O1/O2/Field/self-improvement
claims are supported.
