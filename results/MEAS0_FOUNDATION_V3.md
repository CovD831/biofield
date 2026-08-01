# MEAS0 foundation engineering reviewed result v3

Date: 2026-07-31

## Verdict

**Engineering support only. Gate M remains failed.**

The canonical v16 foundation package binds the current MEAS0 design and
19-file source closure, materializes 36 paired cases, evaluates five fixed arm
views over the same sealed episodes, preserves 180 arm-case results, seals
1,280 files, and reproduces the same replay hash three times.

This revision makes the lock self-contained and relocatable by embedding the
exact design bytes in lock schema v2. It also binds the protected raw Judge
artifact implementation. Neither change is formal experimental evidence:
there was no real Subject, Judge, human review, trusted preflight, formal
Pilot, or confirmatory run.

## Canonical foundation evidence

| Item | Value |
|---|---|
| Run | `runs/meas0/pilot/meas0-foundation-20260731-v16` |
| Lock | `runs/meas0/locks/meas0-foundation-lock-20260731-v16/preregistration.lock.json` |
| Lock schema / design binding | `2 / embedded_bytes_base64` |
| Run shell | `meas0.pilot-run-shell.v11` |
| Foundation runner | `meas0.pilot-foundation.v9` |
| Claim limit | `pilot_foundation_only_not_a_formal_meas0_pilot_result` |
| Design document SHA-256 | `49928ab7fb12755af89bd45d928a5beae7b8455d88b19b501e9465a8ad89a154` |
| Lock SHA-256 | `7409313ec8f07cea1d80a833571cb8bb3c00cfa8df6e91c650f75592e765f70f` |
| Seal file SHA-256 | `f009b8b67869066d104132a30c906d9acb56a0096ebc20e817f899bc07290a25` |
| Artifact bundle SHA-256 | `7b632cb615ed9275ab9965d00c25dfa307be85bebdd38a354e57767f540a9e46` |
| Case manifest file SHA-256 | `a6557169be54390bb3e63a28249a32cc2d47dc65e5488a952c627d2479e05cf8` |
| Replay SHA-256 | `0a7f561a29f6721948d7feacaedb5e287954b0f154559c803cc16547252a200b` |
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

## New engineering evidence

### Relocatable lock and replay

- lock schema v2 stores the exact design bytes as canonical Base64 and checks
  their byte count and SHA-256;
- the lock is verified from one byte snapshot, and the run copies that same
  verified snapshot;
- the original design file may be moved or deleted after preparation without
  invalidating v2 execution or replay;
- legacy schema v1 remains supported only with a strict absolute-path binding;
- replay requires the complete source, fixture, evaluator, mutation, and
  design projection in `source_manifest.json` to equal the lock.

Tests cover moved lock/run directories, deleted source design documents,
non-canonical Base64, mixed v1/v2 fields, changed legacy design files,
single-read lock verification, and re-sealed source-manifest drift.

### Protected raw Judge artifact boundary

The new `meas0_protected_artifacts.py` source implements a local write-once
store with a path-free public receipt. It requires a `0700` root and `0600`
regular file, rejects unsafe IDs, symlinks, hard links and overwrite, uses
directory-relative open plus `O_EXCL`/`O_NOFOLLOW`, fsyncs writes, and verifies
inode, size, mode and SHA-256 during readback.

DeepSeek public evidence contains no raw response, reasoning bytes, Base64
payload, or resolved protected path. Verification reads the protected bytes
and re-derives response identity, model, output, usage, and reasoning metadata.
It also rechecks the fixed external Evaluation Plane authority and claim scope.

This is only a local storage-integrity boundary. The receipt is not signed and
is not a trusted transport receipt. Raw-inaccessible metadata such as request
provenance, transport identity, timestamps and data-handling attestation still
requires a future locked request plus externally verifiable transport
envelope. Production readiness therefore remains fail-closed.

The legacy inline raw-Base64 J-CAL corpus is explicitly test-only. It cannot be
used as production qualification evidence.

## Foundation observations

These values describe synthetic foundation behavior only:

| Arm | Automatic coverage | Pass | Fail | Unknown | Disputed | Invalid | Unavailable |
|---|---:|---:|---:|---:|---:|---:|---:|
| `self_eval` | 0.9444 | 34 | 0 | 2 | 0 | 0 | 0 |
| `judge_only` | 0.0000 | 0 | 0 | 36 | 0 | 0 | 36 |
| `state_only` | 0.7778 | 16 | 12 | 8 | 0 | 0 | 0 |
| `rules_state` | 0.7222 | 8 | 18 | 8 | 2 | 0 | 0 |
| `evaluation_plane` | 0.5556 | 2 | 18 | 8 | 2 | 6 | 4 |

They must not be interpreted as arm performance, measurement validity, or an
adoption result.

## Why Gate M remains failed

1. No production Codex Subject block or provider-side generation receipt has
   been sealed.
2. No trusted DeepSeek transport receipt, 96-call protected J-CAL bundle, or
   typed protected J-AUDIT evidence exists.
3. The production fusion path does not yet derive every non-compensatory result
   and hard-gate boolean directly from sealed observations.
4. No two-reviewer blind gold/adjudication or operational escalation evidence
   exists.
5. No trusted OS ACL, read-only mount, isolation, signed preflight, or
   independently reviewed presentation provenance exists.
6. No signed and independently reviewed formal comparison lock, price/FX
   manifest, or direct monetary cap exists.
7. Production Subject/Judge/human/isolation backends are not connected to the
   formal lifecycle.
8. Neither the N=36 formal Pilot nor N=144 confirmatory comparison has run.

Consequently no §13 hard/performance Gate, paired interval, or confirmatory
claim can be evaluated.

## Reproduction

Audit the write-once canonical package:

```bash
export PYTHONPATH="$PWD/src"
python -m biofield.meas0 replay \
  --run runs/meas0/pilot/meas0-foundation-20260731-v16
python -m biofield.meas0 summarize \
  --run runs/meas0/pilot/meas0-foundation-20260731-v16
```

Run replay three times and require:

```text
verified=true
replayed_result_count=180
replay_hash=0a7f561a29f6721948d7feacaedb5e287954b0f154559c803cc16547252a200b
```

For an independent reproduction, use fresh lock and run IDs. The exact replay
hash will differ because it binds the fresh artifact bundle; all three hashes
must still match one another.

## Unsealed engineering verification

The final full-suite, package-build, and installed-wheel checks are session
verification outside the 1,280-file run seal. Their exact counts are recorded
in the project status after completion. No live GPT, DeepSeek, Ollama,
public-network model, or paid provider call was made.

## Prohibited conclusions

This result must not be cited as evidence that:

- Gate M or §13.1/§13.2 passed;
- `evaluation_plane` is better than any simpler arm;
- a formal Pilot or confirmatory experiment ran;
- Judge, human gold, approval, pricing, isolation, or ACL quality was
  established;
- downstream D, O1, O2, Field, organization, or self-improvement claims are
  measurable or supported.
