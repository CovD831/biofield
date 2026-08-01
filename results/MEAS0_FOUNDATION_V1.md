# MEAS0 foundation engineering reviewed result v1

Date: 2026-07-30

## Verdict

**Engineering support only. Gate M remains failed.**

The v10 run shell can prepare a write-once lock, materialize 36 paired
foundation cases, evaluate the same sealed episode through five fixed arm
views, preserve case-indexed task/episode/arm artifacts and CostVectors, seal
all output, and deterministically replay all 180 arm-case results.

This is not a formal MEAS0 Pilot. It does not establish measurement validity,
arm superiority, Judge qualification, human-gold quality, process isolation,
or any §13 adoption threshold.

## Canonical foundation evidence

| Item | Value |
|---|---|
| Run | `runs/meas0/pilot/meas0-foundation-20260730-v12` |
| Lock | `runs/meas0/locks/meas0-foundation-lock-20260730-v12/preregistration.lock.json` |
| Run shell | `meas0.pilot-run-shell.v10` |
| Foundation runner | `meas0.pilot-foundation.v9` |
| Claim limit | `pilot_foundation_only_not_a_formal_meas0_pilot_result` |
| Lock SHA-256 | `f6c5ad741a3ec5d555fd227c0f9210de71d27145697a3be8c8963b18e7584947` |
| Seal file SHA-256 | `6d1cc1ccb3619bf46da232928f5a8e304e5d8d5c878907c611a69b2333c5eb10` |
| Artifact bundle SHA-256 | `99ba36632d15d320ffb0c2ed9419c13432652adf2132c912244cab33dbe8d700` |
| Case manifest SHA-256 | `a6557169be54390bb3e63a28249a32cc2d47dc65e5488a952c627d2479e05cf8` |
| Replay SHA-256 | `4a80af2a834428428f57cecaae370f3b31bcba5b24d9408bb4fb9edf8a8bd2a4` |
| Cases / arms / results | `36 / 5 / 180` |
| Replayed results | `180`, verified |
| Sealed files | `1,280` |
| Task-native cases | `36/36` |
| Judge / human review | unavailable / unavailable |
| Formal Pilot flag | `false` |

The fixed arm order is produced once from seed `260722` with
`meas0.sha256-sort.v1`:

```text
rules_state → state_only → self_eval → judge_only → evaluation_plane
```

Its order hash is
`49e156fa28359716890841f4de7eda8de5e838abc37b316f30fdf8113c73b3b0`.
The frozen budget policy hash is
`3d315cb54fc825d96f785e22c639439cf6ad702d231ceacfafd7a6656b48d40a`.

## What is supported

- `prepare`, `run`, `replay`, and `summarize` CLI paths exist; the original
  no-subcommand S0 decision-table smoke remains compatible.
- The lock binds the design document, fixtures, evaluators, case descriptors,
  task bundles, native measurement plans, arm order, budget policy, and the
  complete local foundation execution source closure.
- Every case has case-indexed task bundle, episode, state-before/state-after,
  evidence artifact, and per-arm observation/result/cost/stderr/budget output.
- Arm order is checked against the frozen manifest before a run directory is
  created.
- Per-task/per-arm and stage-level budget accounting is deterministic.
  Exhaustion becomes `unknown` or `invalid` according to the frozen rule,
  retains the case in the denominator, and writes a hash-bound failure record.
- Run IDs, locks, and files are write-once; completed output is sealed and
  extra-file or content tampering fails closed.
- A serialized `FormalReadinessBundle` is fully reconstructed and revalidated;
  typed in-memory inputs cannot bypass the formal entry point.
- F06/F07 retain task-specific semantic evidence but correctly remain
  `unknown/unavailable` without a real Judge; R1 F12 is closed from two sealed
  submissions and the record-state transition rather than a generic label.
- Formal execution refusal occurs before run-directory creation.

The arm summaries in this run are engineering observations only. In
particular, the high self-evaluation pass count and the unavailable Judge arm
are expected synthetic/foundation behavior and must not be interpreted as
comparative performance.

## Formal-readiness contracts now implemented

The offline contract layer includes:

- typed `task × F01–F18` case scope and 36/36-native requirement;
- per-case and per-requirement gold scope plus raw blinded reviews and
  adjudication records from which agreement, Cohen's kappa, requirement gold,
  case gold, and role separation are derived;
- `JudgeCard`, 96 raw J-CAL normal/reversed invocation-response records,
  response-byte hashes, qualification/Wilson intervals, quarantine, and
  double-presentation fusion;
- raw preflight command/output records, environment/dependency/ACL hashes,
  read-only mount and process/network policy derivation;
- formal `comparison_block` and hidden-gold mount manifests;
- strict 36-case × five-arm contract-only orchestration, formal metrics,
  attack manifests, budget, price, approval, seed, and formal-lock bindings;
- stable blocker codes and a hash-bound readiness report;
- fail-closed `DESIGN_COMPLETE_NOT_RUNNABLE` when any required binding is
  absent or inconsistent.

Fake providers, reviewers, and executors are explicitly `test_only`; production
validators reject them. These are contracts, not evidence that the external
activities occurred.

## Why Gate M remains failed

The current repository cannot produce a formal-ready run for the following
reasons:

1. no real Judge provider/model digest, J-CAL responses, or J-AUDIT responses
   have been supplied;
2. no two human reviewers, adjudicator, operational escalator, and approved
   gold package have been executed;
3. no trusted OS-level ACL/read-only mount/process/network isolation proof has
   been executed;
4. no externally approved lock, price/FX manifest, or direct monetary cap has
   been supplied;
5. the production Judge/human/isolation backend is not connected to
   `execute/replay/summarize`; the current deterministic formal runner remains
   `contract_only` and always has `formal_result=false`;
6. the formal Pilot and N=144 confirmatory runs and §13 performance thresholds
   have not run;
7. provider/reviewer/preflight/approval attestations still require an external
   trust root and sealed presentation resolver;
8. the confirmatory paired-cluster bootstrap freezes seeds, strata, pairing,
   and replicate count, but not the within-stratum resampling unit or interval
   extraction rule. The implementation therefore raises `ProtocolGap` rather
   than inventing a confidence interval.

## Independent review

An independent agent ran 37 readiness/run/budget/CLI/foundation tests, replayed
the v8 predecessor, and exercised bundle-hash, extra-file, CostVector, and
31/36-native refusal probes. It found no blocker for a foundation-engineering
report and explicit blockers for formal MEAS0.

The review found that v8's source manifest omitted five transitive local
dependencies and that the duplicated `arms` field was checked too late. Both
were corrected with failing tests before the v9 run-shell evidence:

- the v9 run-shell lock hashes 12 local source files, including `meas0.py`,
  `resources.py`, `evidence_task.py`, `contracts.py`, and package initialization;
- the `arms` alias must exactly equal the frozen order manifest before the run
  store is created.

Subsequent TDD hardening brought every case to a task-native plan, added
derived Judge/human/preflight evidence, formal artifact and metric contracts,
and a strict contract-only 180-cell formal runner. The v12 foundation lock
binds 15 local execution files, including the derived evidence modules used by
the formal guard. The complete MEAS0-focused suite passes 125 tests.

## Reproduction

```bash
python -m biofield.meas0 prepare \
  --design docs/experiments/MEAS0_DESIGN_V1.md \
  --phase pilot \
  --lock-directory runs/meas0/locks \
  --lock-id meas0-foundation-lock-20260730-v12

python -m biofield.meas0 run \
  --lock runs/meas0/locks/meas0-foundation-lock-20260730-v12/preregistration.lock.json \
  --output-directory runs \
  --run-id meas0-foundation-20260730-v12 \
  --execution-mode foundation

python -m biofield.meas0 replay \
  --run runs/meas0/pilot/meas0-foundation-20260730-v12

python -m biofield.meas0 summarize \
  --run runs/meas0/pilot/meas0-foundation-20260730-v12
```

Fresh lock/run IDs are required.

## Prohibited conclusions

This result must not be cited as evidence that:

- Gate M or §13.1/§13.2 passed;
- `evaluation_plane` is better than self-evaluation, Judge-only, or any other
  arm;
- a formal Pilot or confirmatory experiment ran;
- Judge or human gold quality was established;
- approval, prices, isolation, or ACL enforcement were externally verified;
- downstream D, O1, O2, or self-improvement claims are measurable yet.
