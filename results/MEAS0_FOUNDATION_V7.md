# MEAS0 Foundation Engineering V7

Date: 2026-07-31

Claim scope: **offline foundation engineering only**

Gate M: **FAIL**

Canonical v20 supersedes v19 as the current foundation package. It retains the
same frozen tasks, faults, five arms, thresholds, budgets, and foundation
behavior while closing source-closure, semantic-count, cost-accounting,
stage-stop, and production-authorization gaps found by independent v19 audits.

## Canonical package

| Item | Value |
|---|---|
| Run | `runs/meas0/pilot/meas0-foundation-20260731-v20` |
| Lock | `runs/meas0/locks/meas0-foundation-lock-20260731-v20/preregistration.lock.json` |
| Design SHA-256 | `138c9be3f7b32e510c8a8283d88ed896e6f5286ff447a2e001a83a1a594b51c2` |
| Lock file SHA-256 | `29d407c8c80917650b96ad44df27cc54cc336d6221ec2c1586b29bb1406028c8` |
| Lock seal file SHA-256 | `aea417eb08307e4647a0ff0f8b9054b51e08d0861bdb16724fcf15d15a634014` |
| Run seal file SHA-256 | `71fe3a72ae4a14e8f70ce1167d716836b876d1b44b1fbddface98c5976992aa6` |
| Artifact bundle hash | `73bc5dc974ac027875196f57befd6a5004c4df964f76759e31b8bbfaa92280bb` |
| Case manifest file SHA-256 | `a6557169be54390bb3e63a28249a32cc2d47dc65e5488a952c627d2479e05cf8` |
| Case manifest logical hash | `42b33e8f7cbcc41c350ca8d1afe2be8bf39c13547782a9d9d99de0f3e9996dab` |
| Run shell | `meas0.pilot-run-shell.v11` |
| Foundation runner | `meas0.pilot-foundation.v9` |
| Formal runner contract | `meas0.formal-runner-contract.v5` |
| Formal derivation contract | `meas0.formal-artifact-facts.v2` |
| Claim limit | `pilot_foundation_only_not_a_formal_meas0_pilot_result` |

The schema-v2 lock embeds the exact design bytes and binds 22 source files,
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

## v20 hardening

### Complete local source closure

The lock now includes `artifacts.py` and `meas0_fixtures.py`, the two local
modules directly imported by locked `meas0.py` but omitted from v19. An AST
regression check verifies that the declared manifest covers the recursive
local-import closure. The manifest therefore contains 22 source files.

### Canonical semantic-count derivation

For canonical evaluation, the runner counts `SEMANTIC` requirements directly
from the exact bound `TaskMeasurementBundle` and rejects a request whose
`semantic_leaf_count` differs. An evaluation-plane backend cannot invoke the
Judge without canonical evidence even in test-only mode, so a caller cannot
inflate its Judge budget by supplying an arbitrary count.

### Fail-closed accounting and stage state

Backend execution is malformed when cost accounting is incomplete, Judge call
count differs from raw call-cost records, or aggregate input/output tokens are
below the corresponding raw Judge-call totals. The malformed artifact remains
in the denominator and stops subsequent provider calls.

`FormalContractRun` derives `stage_stopped` from retained malformed/stage
failures and from aggregate artifact Judge/human costs against the frozen Pilot
caps. This also covers a cap crossing on the terminal artifact.

### Typed production authorization

`FormalExecutionAuthorization.create()` accepts production mode only with a
typed bundle whose revalidated report is `FORMAL_READY`; it obtains the bundle
hash internally. A private derivation token rejects ordinary direct dataclass
construction. The token is an API misuse guard, not a cryptographic trust root
or protection against hostile code in the same process.

## Replayed foundation observations

- 36 frozen cases and 180 arm-case results were retained.
- All 36 cases use task-native measurement plans.
- Three independent replay commands returned `verified=true`.
- All three returned:

```text
65f39eb015b9883b225a10eb3da91430651137e26399bec3fd532de7106b415e
```

The arm summaries are unchanged from v19 because v20 changes evidence
contracts and source closure, not foundation arm behavior.

## Remaining boundary

The following remain absent:

- a trusted transport root and signed transport receipts;
- protected production J-CAL and held-out J-AUDIT;
- approved case-level gold with blind review/adjudication;
- a frozen fault-specific detection oracle;
- integration of J-CAL/J-AUDIT call cost into the formal stage-cost ledger;
- a phase-generic verified confirmatory corpus and source-derived §13.1 inputs;
- post-run/postflight source, wheel, ACL, mount, network and gold-access
  closure;
- production Subject/Judge backends and a signed formal comparison lock;
- the N=36 formal Pilot and N=144 confirmatory comparison.

Therefore the local authorization hash, derivation tokens, provider-recorded
costs, and artifact-derived facts remain non-claim-bearing contract
primitives. Gate M remains `FAIL`.

## Reproduction

```bash
export PYTHONPATH="$PWD/src"
python -m biofield.meas0 replay \
  --run runs/meas0/pilot/meas0-foundation-20260731-v20
python -m biofield.meas0 summarize \
  --run runs/meas0/pilot/meas0-foundation-20260731-v20
```

## Prohibited conclusions

This result must not be cited as evidence that Gate M passed, a formal Pilot or
confirmatory experiment ran, `evaluation_plane` outperformed another arm, a
trusted Judge/human process exists, or D/O1/O2/Field/self-improvement claims
are supported.
