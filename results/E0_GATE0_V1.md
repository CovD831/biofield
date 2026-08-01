# E0 deterministic public replay Gate 0 reviewed result v1

Date: 2026-07-30

## Verdict

**Support, with a deliberately narrow claim boundary.**

The canonical `f0.native.v2` evidence package replays all four required
terminal paths, independently re-evaluates Evidence → Feedback, reconstructs
the public Residual/Ledger terminal projection, and produces the same result
after checkpoint resume as after full replay. This is sufficient for E0 Gate 0.

It supports only the deterministic Harness causal substrate. It does not
support claims about real-model capability, local-agent differentiation,
Field value, O1/O2 organization, or self-improvement.

## Canonical evidence

| Item | Value |
|---|---|
| Run | `runs/e0/e0-20260730-v2` |
| Runner | `e0.artifact-runner.v1` |
| Stream | `f0.native.v2` |
| Lock SHA-256 | `c225b7436c3c85d5dfdfbab0a34baf785128a3a15e7cb9b007484e529896f86d` |
| Seal file SHA-256 | `5312510763b6f157de4cbcc782a9c0d907e142a28bf33e2b46eb1cec8a7c1b86` |
| Sealed artifact bundle SHA-256 | `50e2ac8c7dcf040de01d302ebc8777c856dd99818b7a6cfa38080dbb84e65225` |
| Replay SHA-256 | `01a190eb27c9ced5fdc07d70d821254de957aab0060878262689b2508b59fcfa` |
| Git commit recorded by run | `9dc412520387d0c9cda700f49744305ff9f99acd` |
| Repository state | dirty; exact dirty-state digest and local source hashes are sealed |
| Model/Judge/human calls | `0 / 0 / 0` |

The run contains 75 public events. All four cases report
`primitive_replay_verified=true`,
`evidence_feedback_verified=true`, and checkpoint/full equivalence.

| Terminal path | Events | Public event bundle SHA-256 | Source finalization SHA-256 | Public terminal projection SHA-256 |
|---|---:|---|---|---|
| `completed` | 27 | `83b576fa62b38da4eb82b2babcbc8b2c6cada23fd38e30da8f5f62026c7f635b` | `62edb17c1b5f593bbadfbbd5588567c9b22fd2d41f139a4452a206ad4ee385d3` | `c53cca0ae8a904a25983d3ca553b06f59bb2df07266a0ec4ce4d577e51b8227e` |
| `failed` | 18 | `f86a52e60225c8a9a985fe7f2e625341914edfc84503e370e47c51916fc9d547` | `31a77bc743a07def1dceafb6fe4baedb708adeff19b9b1b1dfedc0a758111102` | `d8be8eb257977534e4e76d14376ae6f2f16f97a95034347a6ea9ae5b8b6a3357` |
| `budget_exhausted` | 11 | `aec166515693dab9621bd22e1cd6ecd7a1a26edcacc39c2afa59c6b861a420c8` | `d074932b6277e57ad040804938a4126af96d7b9128d137131ee864f968c5ac39` | `63edf4db95cf89c6f79f11950dbde5d7120b59ce3b5138a0ccc372a043e6c718` |
| `max_cycles` | 19 | `c897030f68324b4125bf322238eb328773d7858404a6fb016370f55ca76926b1` | `b27aaa481c1e19182101729b0f7fae31ec2391787a8f00f611b4cbc0c4a628cc` | `141a0d351fb54a2ffe902f32aecdd2894bf1b81cc0543d021c7f3548bb8b5b93` |

## Gate criteria

| Criterion | Result |
|---|---|
| Same public stream produces the same terminal projection | pass |
| Evidence → Feedback is recomputed from the frozen verifier contract | pass |
| Residual and Ledger primitives replay without reading hidden gold | pass |
| `completed`, `failed`, `budget_exhausted`, and `max_cycles` are covered | pass |
| Midstream checkpoint resume equals full replay | pass, 4/4 |
| Lock, source, event, checkpoint, replay, metrics, summary, and terminal artifacts are sealed | pass |
| Existing lock/run IDs cannot be silently overwritten | pass |
| Finalized runs reject mutation | pass |
| Event, source, lock, checkpoint, and outer-seal tampering fail closed | pass |
| Execution failure is retained as a sealed machine-readable failed run | pass |

The completed run records a full public CostVector: 8 verifier calls,
8 deterministic checks, 48,720 transferred bytes, 103 ms wall time, and
72 ms CPU time; all model, Judge, human, communication, retry, and tool fields
are explicit zeroes. Failed E0 runs use the same 15-field CostVector schema.

## Review and hardening history

An independent agent reviewed the runner against protocol §5 and ran the E0
artifact/CLI tests. It found no Gate-blocking defect, but identified two
evidence-quality gaps: the initial source manifest covered only four direct
files, and failed-run metrics lacked the common CostVector.

Both were fixed before the canonical v2 run:

- the source manifest now hashes the ten-file local execution closure:
  `__init__`, artifacts, contracts, E0, E0 runner, evidence task, F0, Ledger,
  Residual, and package resources;
- failed runs now retain a complete CostVector and an explicit accounting
  statement.

The E0 replay/artifact slice passes 56 tests after hardening. The original v1
machine run is retained only as an audit predecessor; its source manifest no
longer matches the current runner and it is not the normative result.

## Reproduction

The machine-readable workflow is:

```bash
python -m biofield.e0_run sources \
  --output-directory runs/e0-sources \
  --source-set-id e0-canonical-20260730-v2

python -m biofield.e0_run prepare \
  --lock-directory runs/e0-locks \
  --lock-id e0-lock-20260730-v2 \
  --completed runs/e0-sources/f0-contract/e0-canonical-20260730-v2-completed \
  --failed runs/e0-sources/f0-contract/e0-canonical-20260730-v2-failed \
  --budget-exhausted runs/e0-sources/f0-contract/e0-canonical-20260730-v2-budget_exhausted \
  --max-cycles runs/e0-sources/f0-contract/e0-canonical-20260730-v2-max_cycles

python -m biofield.e0_run run \
  --lock runs/e0-locks/e0-lock-20260730-v2/e0.lock.json \
  --output-directory runs \
  --run-id e0-20260730-v2

python -m biofield.e0_run replay --run runs/e0/e0-20260730-v2
python -m biofield.e0_run summarize --run runs/e0/e0-20260730-v2
```

All run IDs and lock IDs are write-once; reproduction therefore requires fresh
IDs or a fresh output root.

## Limitations

- The seal proves content integrity within the artifact package; it is not an
  external cryptographic signature or transparency-log entry.
- The run was made from a dirty checkout. This is disclosed rather than hidden:
  the Git commit, dirty-state digest, dependency versions, platform, and exact
  execution-closure source hashes are sealed.
- Source-run paths in the lock are absolute provenance references. Replay of
  the completed E0 package consumes its sealed events and checkpoints and does
  not require those source directories.
- `native.v1` and legacy streams remain compatibility formats and do not inherit
  the verifier-bound `native.v2` conclusion.

