# MEAS0 Foundation Engineering V5

Date: 2026-07-31

Claim scope: **offline foundation engineering only**

Gate M: **FAIL**

The canonical v18 foundation package binds the current MEAS0 design and
implementation after adding execution-authorization ancestry, artifact-derived
non-gold facts, and a derived-only §13.1 assessment constructor. It does not
contain a real Subject/Judge run, human gold, a formal Pilot, a confirmatory
comparison, or evidence that any arm is superior.

## Canonical package

| Item | Value |
|---|---|
| Run | `runs/meas0/pilot/meas0-foundation-20260731-v18` |
| Lock | `runs/meas0/locks/meas0-foundation-lock-20260731-v18/preregistration.lock.json` |
| Design SHA-256 | `da3c3e6f39f643a0cb768d06f38d20eae790123a99e9d4ca81fd37d8b5cf1af2` |
| Lock file SHA-256 | `1fda0a1d3445460275eeb9276c976c56609b721413d7372213b2c9771150f92d` |
| Lock seal file SHA-256 | `591f421d1d50e2722cdde2870826ff5fc5e194fe1a47fd68f00834381f41fa47` |
| Run seal file SHA-256 | `34208b12dbdcf0312dbf2c80de7a9dec798342f0d14fe035f2eaa1e61fb02167` |
| Artifact bundle hash | `d5884b3f41366876493dc4dc8d9c26a658d128f4f426370e612e65dd74b3e01b` |
| Case manifest file SHA-256 | `a6557169be54390bb3e63a28249a32cc2d47dc65e5488a952c627d2479e05cf8` |
| Case manifest logical hash | `42b33e8f7cbcc41c350ca8d1afe2be8bf39c13547782a9d9d99de0f3e9996dab` |
| Run shell | `meas0.pilot-run-shell.v11` |
| Foundation runner | `meas0.pilot-foundation.v9` |
| Formal runner contract | `meas0.formal-runner-contract.v3` |
| Formal derivation contract | `meas0.formal-artifact-facts.v1` |
| Claim limit | `pilot_foundation_only_not_a_formal_meas0_pilot_result` |

The schema-v2 lock embeds the exact design bytes. It binds 20 source files,
11 package fixtures, and 3 evaluators. The run seal covers 1,280 files. The
fixed arm order remains:

```text
rules_state → state_only → self_eval → judge_only → evaluation_plane
```

The arm-order manifest `contract_hash` is
`cf3dce44c90827e96e9fbe0d48dc9db50e69f5bfce0d4eb6d52d911949dad685`;
its `order_hash` is
`49e156fa28359716890841f4de7eda8de5e838abc37b316f30fdf8113c73b3b0`.
The budget policy hash remains
`3d315cb54fc825d96f785e22c639439cf6ad702d231ceacfafd7a6656b48d40a`.

## New contract evidence

### Execution authorization ancestry

`FormalExecutionAuthorization` is created before any provider call and binds:

- an explicit execution identity;
- the complete Pilot plan hash;
- the production readiness bundle hash when production mode is used;
- the ordered five-arm provider descriptor manifest and mode.

Its authorization hash is carried by every `FormalArmRequest`, echoed by every
`BackendExecution`, retained by every `FormalArmCaseArtifact`, and bound into
the final `FormalContractRun`. A response from another authorization, an
artifact with changed ancestry, or a run whose artifacts and authorization
disagree now fails closed.

This is local hash ancestry, not an external signature or an independently
trusted transport receipt.

### Artifact-derived facts

For artifacts that retain a valid `CanonicalEvaluationBinding`,
`derive_artifact_facts()` now projects:

- automatic status;
- budget-exhaustion disposition;
- recorded human escalations;
- all formal leaf count;
- deterministic-eligible and deterministically resolved leaf counts;
- artifact, authorization, bundle and episode hashes.

The projection is versioned and hash-bound. It recomputes deterministic
eligibility from the frozen requirement/measurement graphs and resolution from
typed canonical observations. It deliberately does not accept or synthesize
gold or fault-detection labels.

### Artifact and hard-gate construction

Successful arm-case artifacts now cross-check case/task/fault identity,
raw observation/result identity, canonical task identity, and authoritative
status. The final run checks that all 180 artifacts share its authorization
ancestry.

`ContractHardGateAssessment` can no longer be directly constructed with eight
caller-supplied `true` criteria. It must be returned by the §13.1 evaluator.
This closes direct assessment injection, but the evaluator's evidence leaves
remain contract-only until they are derived from a verified sealed corpus and
trusted receipts.

## Replayed foundation observations

- 36 frozen cases and 180 arm-case results were retained.
- All 36 cases use task-native measurement plans.
- Three independent replay commands returned `verified=true`.
- All three returned:

```text
f39775e16fb52a8e96f6f14220a2c3ca52c156d70551db1dda7c04e0d6254166
```

The arm summaries are unchanged from the prior foundation because this
increment changes evidence ancestry and derivation contracts, not the frozen
tasks, faults, arm behavior, thresholds, or foundation evaluator.

## Remaining boundary

The following are still absent:

- an approved trusted transport root and signed transport receipts;
- protected production J-CAL and held-out J-AUDIT;
- approved case-level gold and its blind review/adjudication;
- a frozen fault-specific detection oracle for
  `detection_expected/detected`;
- source-derived §13.1 protected integrity, replay, denominator and Judge
  evidence;
- post-run/postflight closure for source, wheel, ACL, mount, network and gold
  access state;
- a signed formal comparison lock and production five-arm backends;
- the N=36 formal Pilot and N=144 confirmatory comparison.

Consequently, manually constructed `ArmCaseOutcome` and
`ContractHardGateEvidence` remain test/contract primitives and cannot be used
as claim-bearing evidence.

## Reproduction

```bash
export PYTHONPATH="$PWD/src"
python -m biofield.meas0 replay \
  --run runs/meas0/pilot/meas0-foundation-20260731-v18
python -m biofield.meas0 summarize \
  --run runs/meas0/pilot/meas0-foundation-20260731-v18
```

## Prohibited conclusions

This result must not be cited as evidence that Gate M passed, a formal Pilot or
confirmatory experiment ran, `evaluation_plane` outperformed another arm, a
trusted Judge/human process exists, or D/O1/O2/Field/self-improvement claims
are supported.
