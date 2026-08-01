# MEAS0 foundation engineering reviewed result v2

Date: 2026-07-31

## Verdict

**Engineering support only. Gate M remains failed.**

The v14 canonical foundation package binds the current MEAS0 design and 18-file
source closure, materializes 36 paired cases, evaluates five fixed arm views
over the same sealed episodes, preserves 180 arm-case results, seals 1,280
files, and reproduces the same replay hash three times.

The newly bound source includes the external-provider contracts, formal metric
and runner contracts, the complete-five-arm bootstrap corpus contract, and the
directional bootstrap Gate implementation. The foundation run does not execute
a real Subject, Judge, human review, trusted preflight, formal Pilot, or
confirmatory experiment. Source binding and contract tests are not evidence
that those external activities occurred or that one arm is superior.

## Canonical foundation evidence

| Item | Value |
|---|---|
| Run | `runs/meas0/pilot/meas0-foundation-20260731-v14` |
| Lock | `runs/meas0/locks/meas0-foundation-lock-20260731-v14/preregistration.lock.json` |
| Run shell | `meas0.pilot-run-shell.v10` |
| Foundation runner | `meas0.pilot-foundation.v9` |
| Claim limit | `pilot_foundation_only_not_a_formal_meas0_pilot_result` |
| Design document SHA-256 | `67cf06b3e248ee0eca83a3e8f8458c4a4254d7188a5988f44bab0d5bf63e8e8a` |
| Lock SHA-256 | `5021efcdfd00911a4f12c2b6d7c596c1a84277fa85ed2d0c0c3474e0b2c0b946` |
| Seal file SHA-256 | `89029262cdeaadbfcb59d99fdcec718289b8303a744bf9843e6fe023e93e0885` |
| Artifact bundle SHA-256 | `fdcd419abdf557fa2695a972e606d38deb811c7184a282dc0d6bb8c563d390a5` |
| Case manifest file SHA-256 | `a6557169be54390bb3e63a28249a32cc2d47dc65e5488a952c627d2479e05cf8` |
| Replay SHA-256 | `53ee029cd408aad12bc5e17aa9eb3045bfb41241de1bf55150ba3664880ee0cf` |
| Cases / arms / results | `36 / 5 / 180` |
| Reviewer replay checks, unsealed | `3/3`, each verified with 180 results |
| Sealed files | `1,280` |
| Task-native cases | `36/36` |
| Source closure | `18` files |
| Judge / human review | unavailable / unavailable |
| Formal Pilot flag | `false` |

The fixed arm order remains:

```text
rules_state → state_only → self_eval → judge_only → evaluation_plane
```

Its order hash is
`49e156fa28359716890841f4de7eda8de5e838abc37b316f30fdf8113c73b3b0`.
The frozen budget policy hash is
`3d315cb54fc825d96f785e22c639439cf6ad702d231ceacfafd7a6656b48d40a`.

## Newly bound contract layer

The v14 lock adds these files to the source closure:

| Source | SHA-256 |
|---|---|
| `meas0_formal_metrics.py` | `8b25be2af068be6a93ccbda1a328eade775e31d455923b38a9d49fd1fe9526d2` |
| `meas0_formal_runner.py` | `7c9361a4479a42727306045b2358dd9b23877e9abf0281e50f6d2f27ab0179d6` |
| `meas0_providers.py` | `fbecff0ba434adfa3b0b56e7fb018c9e3366607672b57824967247afd9c85084` |

The bound provider contracts:

- construct a strict, build-only Codex Subject command intended for a
  subscription-authenticated environment, with normalized workspace-contained
  paths and explicit black-box replay limits; the code does not verify active
  authentication or subscription;
- construct and revalidate canonical DeepSeek V4 Pro request bytes in an
  external Evaluation Plane;
- require a hash-bound declaration that Judge inputs are deidentified and
  non-sensitive, without claiming the code itself classifies content;
- keep raw Judge responses out of public evidence and expose only their hashes;
  a persistent protected artifact store, ACL, and retention policy are not yet
  implemented;
- reject all production upgrades until a verifiable trusted transport receipt
  and external trust root exist.

The bound confirmatory statistic contracts:

- require one complete `FORMAL_ARMS × 144` corpus with common case ordering;
- resample four mutation-seed clusters with replacement inside each of 36
  `task_id × fault_id` strata;
- use seed `9511`, 10,000 replicates, and one arm-independent SHA-256 draw
  schedule;
- use nearest-rank percentile endpoints without interpolation or BCa;
- report two-sided 95% intervals and use the adverse one-sided 95% bound for
  paired Gate criteria;
- compute the §13.2.5 detection lower bound separately for each preregistered
  blind-spot fault.

None of these items turns the N=36 foundation outputs into confirmatory
bootstrap results. The formal statistic entry point requires a complete
five-arm confirmatory corpus, which this run does not contain.

## Unsealed engineering verification

The following checks are reviewer/operator assertions from this work session.
Their logs, tool versions, and receipts are not entries in the 1,280-file
canonical run seal, so they are supporting engineering verification rather
than sealed run evidence:

- Full deterministic test suite: `552 passed`.
- MEAS0 formal-metric/bootstrap/provider/pilot focused suite after formatting:
  `44 passed`.
- Ruff checks and formatting checks passed for all modified Python files.
- `git diff --check` passed.
- Wheel and source distribution built successfully in a fresh temporary
  output directory.
- The wheel was installed in a virtual environment outside the checkout.
  Package fixtures, the mutation manifest, the provider module, and the
  confirmatory metric module loaded successfully from that installation.
- No live GPT, DeepSeek, Ollama, public-network model, or paid provider call was
  made.

## Foundation observations

The sealed summary remains engineering-only:

| Arm | Automatic coverage | Pass | Fail | Unknown | Disputed | Invalid | Unavailable |
|---|---:|---:|---:|---:|---:|---:|---:|
| `self_eval` | 0.9444 | 34 | 0 | 2 | 0 | 0 | 0 |
| `judge_only` | 0.0000 | 0 | 0 | 36 | 0 | 0 | 36 |
| `state_only` | 0.7778 | 16 | 12 | 8 | 0 | 0 | 0 |
| `rules_state` | 0.7222 | 8 | 18 | 8 | 2 | 0 | 0 |
| `evaluation_plane` | 0.5556 | 2 | 18 | 8 | 2 | 6 | 4 |

The high self-evaluation pass count and unavailable Judge arm are expected
synthetic/foundation behavior. They must not be interpreted as comparative
performance, measurement validity, or an adoption result.

## Why Gate M remains failed

1. No production Codex Subject block has been sealed; the build-only adapter
   does not verify the active subscription/authentication, schema bytes, or
   inherited process environment.
2. No DeepSeek V4 Pro Judge calls, trusted transport receipts, persistent
   protected raw-response store, J-CAL corpus, or J-AUDIT corpus exist.
3. No two-reviewer blind gold process, independent adjudication, or operational
   escalation evidence exists.
4. No trusted OS ACL, read-only mount, process/network isolation, or signed
   preflight evidence exists.
5. No externally signed and independently reviewed formal lock, price/FX
   manifest, or direct monetary cap exists.
6. The production Subject/Judge/human/isolation backends are not connected to
   the formal `execute/replay/summarize` lifecycle.
7. Neither the N=36 formal Pilot nor the N=144 confirmatory comparison has run;
   therefore no §13 hard/performance Gate or confirmatory interval can be
   evaluated.
8. The foundation lock's absolute design path is not yet a relocatable,
   self-contained evidence binding.
9. The deidentification/non-sensitive declaration has not been independently
   reviewed or rooted in a trusted data-handling attestation.

## Reproduction

From a source checkout, either install the package first or export its source
directory:

```bash
export PYTHONPATH="$PWD/src"
```

The existing canonical package is write-once. In this workspace, audit it
without modifying it:

```bash
python -m biofield.meas0 replay \
  --run runs/meas0/pilot/meas0-foundation-20260731-v14

python -m biofield.meas0 summarize \
  --run runs/meas0/pilot/meas0-foundation-20260731-v14
```

For an independent reproduction, substitute fresh lock and run IDs:

```bash
python -m biofield.meas0 prepare \
  --design docs/experiments/MEAS0_DESIGN_V1.md \
  --phase pilot \
  --lock-directory runs/meas0/locks \
  --lock-id <fresh-lock-id>

python -m biofield.meas0 run \
  --lock runs/meas0/locks/<fresh-lock-id>/preregistration.lock.json \
  --output-directory runs \
  --run-id <fresh-run-id> \
  --execution-mode foundation

python -m biofield.meas0 replay \
  --run runs/meas0/pilot/<fresh-run-id>

python -m biofield.meas0 summarize \
  --run runs/meas0/pilot/<fresh-run-id>
```

For the canonical v14 audit, run the replay command three times and require:

```text
verified=true
replayed_result_count=180
replay_hash=53ee029cd408aad12bc5e17aa9eb3045bfb41241de1bf55150ba3664880ee0cf
```

That exact hash applies only to the canonical v14 audit. A fresh reproduction
has a different lock/config and therefore a different artifact-bundle and
replay hash. For a fresh run, require all three replays to report
`verified=true`, 180 results, and the same hash as each other; do not require
the v14 hash.

The v14 lock records the design document as an absolute local path. Canonical
replay therefore works at the locked workspace path but is not relocatable to
an arbitrary checkout. A future formal lock must seal the design bytes or use a
validated relocatable reference. The canonical v14 directories must never be
reused as reproduction targets.

## Prohibited conclusions

This result must not be cited as evidence that:

- Gate M or §13.1/§13.2 passed;
- `evaluation_plane` is better than any simpler arm;
- a formal Pilot or confirmatory experiment ran;
- Judge, human gold, approval, pricing, isolation, or ACL quality was
  established;
- the bootstrap interval or directional Gate passed on real data;
- downstream D, O1, O2, or self-improvement claims are measurable yet.
