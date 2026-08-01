# MEAS0 Foundation Engineering V6

Date: 2026-07-31

Claim scope: **offline foundation engineering only**

Gate M: **FAIL**

Canonical v19 supersedes v18 as the current foundation package. It retains the
same frozen tasks, faults, five arms, thresholds, budgets, and foundation
behavior while closing artifact-state and direct production-run construction
gaps found by the independent v18 attack audit.

## Canonical package

| Item | Value |
|---|---|
| Run | `runs/meas0/pilot/meas0-foundation-20260731-v19` |
| Lock | `runs/meas0/locks/meas0-foundation-lock-20260731-v19/preregistration.lock.json` |
| Design SHA-256 | `2a339f6dd41bd1d1b30232ac49d6db080b94e765f1e77fb00ff4cb48c11c66e3` |
| Lock file SHA-256 | `24da91d62c12187240e8f202e14b1254877f296c8599aff7503a9aa25d24d8f9` |
| Lock seal file SHA-256 | `b9c1da1035f0f58d0b0713205fc8b4de79c8853cddb046785d900b7d35b339b4` |
| Run seal file SHA-256 | `daec0eda024e6a51000a6a23bb54b6ac13cd864475b72256e33113f098962705` |
| Artifact bundle hash | `74b0ad4b6e2072726993d89eae7d831a793782708a6673a62b732e2a411852f4` |
| Case manifest file SHA-256 | `a6557169be54390bb3e63a28249a32cc2d47dc65e5488a952c627d2479e05cf8` |
| Case manifest logical hash | `42b33e8f7cbcc41c350ca8d1afe2be8bf39c13547782a9d9d99de0f3e9996dab` |
| Run shell | `meas0.pilot-run-shell.v11` |
| Foundation runner | `meas0.pilot-foundation.v9` |
| Formal runner contract | `meas0.formal-runner-contract.v4` |
| Formal derivation contract | `meas0.formal-artifact-facts.v2` |
| Claim limit | `pilot_foundation_only_not_a_formal_meas0_pilot_result` |

The schema-v2 lock embeds the exact design bytes and binds 20 source files,
11 package fixtures, and 3 evaluators. The run seal covers 1,280 files.

The fixed arm order remains:

```text
rules_state → state_only → self_eval → judge_only → evaluation_plane
```

The arm-order manifest `contract_hash` remains
`cf3dce44c90827e96e9fbe0d48dc9db50e69f5bfce0d4eb6d52d911949dad685`;
its `order_hash` remains
`49e156fa28359716890841f4de7eda8de5e838abc37b316f30fdf8113c73b3b0`.
The budget policy hash remains
`3d315cb54fc825d96f785e22c639439cf6ad702d231ceacfafd7a6656b48d40a`.

## v19 hardening

### Frozen failure disposition

Every `FormalFailureArtifact` now has a fixed
`FailureCode → (ResultValidity, EvaluationStatus)` disposition. A caller cannot
attach a timeout or budget failure to a canonical `FAIL` artifact and relabel
the final status as `PASS`. `ArtifactDerivedFacts` v2 therefore cannot project
the v18 failure-status injection found by audit.

Successful artifacts additionally require:

- complete cost accounting;
- a non-timeout raw result;
- Judge call count consistent with raw Judge cost entries;
- raw result/observation and canonical task/status identity.

### Run construction and ancestry

The authorization hash commits the execution identity, mode, plan hash,
production readiness bundle hash, and ordered provider descriptor manifest.
Request, response and artifact objects carry that ancestry; the final run hash
then commits the artifacts.

`FormalContractRun` is factory-derived and also verifies:

- each artifact backend ID against its arm descriptor;
- every successful production artifact has canonical evaluation evidence;
- `stage_stopped` is derived from retained stage-budget failure artifacts;
- all 180 artifacts have the frozen case/arm order and authorization ancestry.

Production authorization also requires timeout-enforcing backend descriptors.
This remains local hash ancestry, not a signature or trusted transport proof.

### Exact canonical bundle binding

`FormalArmRequest` now validates all typed identity, count and hash fields.
When canonical evaluation is present, its exact
`TaskMeasurementBundle.bundle_hash`, task identity, sealed episode hash and
measurement count must match the request. Matching only task ID and count is no
longer sufficient.

## Replayed foundation observations

- 36 frozen cases and 180 arm-case results were retained.
- All 36 cases use task-native measurement plans.
- Three independent replay commands returned `verified=true`.
- All three returned:

```text
d84325c9e548b646ac55a05d6af930a04e2c49e78f5834ba668eb950abaeb85c
```

The arm summaries are unchanged from v17 and v18. This is expected because v19
changes evidence contracts, not foundation arm behavior.

## Remaining boundary

The following remain absent:

- a trusted transport root and signed transport receipts;
- protected production J-CAL and held-out J-AUDIT;
- approved case-level gold with blind review/adjudication;
- a frozen fault-specific detection oracle;
- a phase-generic verified confirmatory corpus and source-derived §13.1
  integrity/replay/Judge inputs;
- post-run/postflight source, wheel, ACL, mount, network and gold-access
  closure;
- production Subject/Judge backends and a signed formal comparison lock;
- the N=36 formal Pilot and N=144 confirmatory comparison.

Private in-process derivation tokens prevent ordinary public-constructor misuse;
they are not a cryptographic trust root. Likewise, provider-recorded cost is
not independent metering until a trusted execution closure exists.

Therefore manually constructed `ArmCaseOutcome`,
`ContractHardGateEvidence`, local authorization hashes, and artifact-derived
facts remain non-claim-bearing contract primitives.

## Reproduction

```bash
export PYTHONPATH="$PWD/src"
python -m biofield.meas0 replay \
  --run runs/meas0/pilot/meas0-foundation-20260731-v19
python -m biofield.meas0 summarize \
  --run runs/meas0/pilot/meas0-foundation-20260731-v19
```

## Prohibited conclusions

This result must not be cited as evidence that Gate M passed, a formal Pilot or
confirmatory experiment ran, `evaluation_plane` outperformed another arm, a
trusted Judge/human process exists, or D/O1/O2/Field/self-improvement claims
are supported.
