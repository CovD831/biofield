# MEAS0 foundation engineering reviewed result v4

Date: 2026-07-31

## Verdict

**Engineering support only. Gate M remains failed.**

The canonical v17 foundation package binds the current MEAS0 design and
19-file source closure, materializes 36 paired cases, evaluates five fixed arm
views over the same sealed episodes, preserves 180 arm-case results, seals
1,280 files, and reproduces the same replay hash three times.

This revision closes three offline contract gaps:

1. a production backend must provide a typed canonical evaluation that is
   rederived by the frozen `fuse_evidence()` path;
2. a §13.1 hard-gate assessment cannot be forged as an empty criteria list with
   `passed=true`;
3. the protected raw store pins the initialized root identity and opens its
   ancestry component by component without following symlinks.

No real Subject, Judge, human review, trusted preflight, formal Pilot, or
confirmatory run occurred.

## Canonical foundation evidence

| Item | Value |
|---|---|
| Run | `runs/meas0/pilot/meas0-foundation-20260731-v17` |
| Lock | `runs/meas0/locks/meas0-foundation-lock-20260731-v17/preregistration.lock.json` |
| Lock schema / design binding | `2 / embedded_bytes_base64` |
| Run shell | `meas0.pilot-run-shell.v11` |
| Foundation runner | `meas0.pilot-foundation.v9` |
| Formal runner contract | `meas0.formal-runner-contract.v2` |
| Claim limit | `pilot_foundation_only_not_a_formal_meas0_pilot_result` |
| Design document SHA-256 | `108a874e3c574fb44bb25764afcc80b59734cecde2f0ab99b5703ed8d8253883` |
| Lock SHA-256 | `0a5638ec069f834e6a889d3800fa26b58e002b6d8dd3c3715e300cec8330aa3b` |
| Seal file SHA-256 | `cf8440166116357d9722dbe88aa7105f0869c5f5008fa4f6df613484264ffa4f` |
| Artifact bundle SHA-256 | `f559d44ef91018b802f0831a00533eedb327f78cb11ed8d6270abdba24041a90` |
| Case manifest file SHA-256 | `a6557169be54390bb3e63a28249a32cc2d47dc65e5488a952c627d2479e05cf8` |
| Replay SHA-256 | `4a6402b3fd5cb22f6b6150809aca7303c637c3d3031a1f93dc5d411b6476b313` |
| Cases / arms / results | `36 / 5 / 180` |
| Reviewer replay checks, unsealed | `3/3`, each verified with 180 results |
| Sealed files | `1,280` |
| Task-native cases | `36/36` |
| Source / fixture / evaluator closure | `19 / 11 / 3` files |
| Judge / human review | unavailable / unavailable |
| Formal Pilot flag | `false` |

The fixed arm order remains:

```text
rules_state → state_only → self_eval → judge_only → evaluation_plane
```

Its order hash is
`cf3dce44c90827e96e9fbe0d48dc9db50e69f5bfce0d4eb6d52d911949dad685`.
The budget policy hash remains
`3d315cb54fc825d96f785e22c639439cf6ad702d231ceacfafd7a6656b48d40a`.

> **2026-07-31 audit correction:** the preceding
> `cf3dce44c90827e96e9fbe0d48dc9db50e69f5bfce0d4eb6d52d911949dad685`
> value is the arm-order manifest `contract_hash`, not its `order_hash`.
> The verified `order_hash` is
> `49e156fa28359716890841f4de7eda8de5e838abc37b316f30fdf8113c73b3b0`.
> The resolved arm order itself is unchanged.

## New contract evidence

### Canonical production evaluation

`CanonicalEvaluationBinding` contains the complete frozen
`TaskMeasurementBundle`, `SealedEpisode`, typed `MeasurementObservation`
leaves, and `EvaluationResult`. Construction reruns `fuse_evidence()` and
requires exact equality with the supplied result. A backend-reported status
that differs from the canonical outcome is rejected.

The formal runner requires this binding for every production backend result.
Test-only providers may continue exercising denominator, timeout and budget
contracts without pretending to be production evidence. Successful formal
artifacts retain the canonical binding rather than only a backend status enum.

This closes the direct status-enum substitution path. It does not yet derive
confirmatory `ArmCaseOutcome` or every §13.1 evidence field from the sealed run;
those remain explicit production evidence work.

### Hard-gate assessment invariant

`ContractHardGateAssessment` now requires exactly the ordered criteria
`13.1.1` through `13.1.8`, boolean criterion values, confirmatory phase, and a
top-level `passed` value equal to the conjunction of those criteria. Empty,
reordered or contradictory assessments fail construction.

This prevents the previous direct `criteria=(), passed=true` bypass. The
underlying hard-gate inputs still need to be derived from sealed evaluation,
protected-file verification, replay comparison and trusted J-CAL/J-AUDIT
evidence before they can carry a formal claim.

### Protected-store root identity

The protected raw store now:

- opens the absolute path from the filesystem root one directory component at
  a time using directory-relative `O_DIRECTORY | O_NOFOLLOW`;
- creates only the final missing store directory and fsyncs its pinned parent;
- checks `0700` and effective-user ownership;
- records the initialized root device/inode and requires every later operation
  to reach the same directory;
- rejects a renamed parent followed by a replacement same-name `0700` root.

Artifact-level write-once, `0600`, no-symlink/no-hardlink, inode, size, hash and
readback protections from v16 remain in force.

## Remaining protocol decisions

The following cannot be selected by implementation without user/design
approval:

1. the trusted transport root and its exact claim: provider signature,
   independently operated gateway/HSM signature, or another proof;
2. the actual 48-item J-CAL and 48-item held-out J-AUDIT presentation/gold
   packages;
3. whether style-flip and repeat-disagreement remain proxies derived from the
   existing 96 normal/reversed calls or require additional calls;
4. how Brier/ECE obtains a raw pass probability when the frozen schema only
   contains confidence in the selected verdict;
5. calibration/audit token, timeout and stage-budget allocation;
6. resolution of `judge_version` (`deepseek-v4-pro` versus JudgeCard identity),
   black-box `model_digest`, and qualification timestamp semantics;
7. comparison-lock → J-AUDIT → final execution authorization signing order;
8. protected raw retention and deletion policy.

Until these decisions are frozen, production Judge readiness correctly remains
fail-closed. A local protected receipt is not a trusted transport receipt.

## Foundation observations

The synthetic foundation summary is unchanged:

| Arm | Automatic coverage | Pass | Fail | Unknown | Disputed | Invalid | Unavailable |
|---|---:|---:|---:|---:|---:|---:|---:|
| `self_eval` | 0.9444 | 34 | 0 | 2 | 0 | 0 | 0 |
| `judge_only` | 0.0000 | 0 | 0 | 36 | 0 | 0 | 36 |
| `state_only` | 0.7778 | 16 | 12 | 8 | 0 | 0 | 0 |
| `rules_state` | 0.7222 | 8 | 18 | 8 | 2 | 0 | 0 |
| `evaluation_plane` | 0.5556 | 2 | 18 | 8 | 2 | 6 | 4 |

These values are not arm-performance or measurement-validity evidence.

## Why Gate M remains failed

- No production Subject block or provider-side generation receipt is sealed.
- No approved trusted transport root, protected 96-call J-CAL bundle, or typed
  protected J-AUDIT evidence exists.
- Formal metrics and all §13.1 inputs are not yet fully derived from sealed
  production artifacts.
- No blind human gold/adjudication, operational escalation, trusted isolation,
  signed preflight or independently reviewed presentation provenance exists.
- No signed formal comparison lock, price/FX manifest or direct monetary cap
  exists.
- Production Subject/Judge/human/isolation backends are not connected.
- Neither the N=36 formal Pilot nor N=144 confirmatory comparison has run.

## Reproduction

```bash
export PYTHONPATH="$PWD/src"
python -m biofield.meas0 replay \
  --run runs/meas0/pilot/meas0-foundation-20260731-v17
python -m biofield.meas0 summarize \
  --run runs/meas0/pilot/meas0-foundation-20260731-v17
```

Run replay three times and require:

```text
verified=true
replayed_result_count=180
replay_hash=4a6402b3fd5cb22f6b6150809aca7303c637c3d3031a1f93dc5d411b6476b313
```

## Prohibited conclusions

This result must not be cited as evidence that Gate M passed, a formal Pilot or
confirmatory experiment ran, `evaluation_plane` outperformed another arm, a
trusted Judge or human process exists, or D/O1/O2/Field/self-improvement claims
are supported.
