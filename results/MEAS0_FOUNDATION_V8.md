# MEAS0 Foundation Engineering V8

Date: 2026-07-31

Claim scope: **offline foundation engineering only**

Gate M: **FAIL**

Canonical v21 supersedes v20 as the current foundation package. It preserves
the frozen tasks, F01-F18 faults, five arms, comparisons, metrics, thresholds,
budgets, and foundation behavior. Its purpose is to source-bind the approved
D1-D4 offline protocol amendment and verify that the new contracts remain
deterministic and fail closed.

## Canonical package

| Item | Value |
|---|---|
| Run | `runs/meas0/pilot/meas0-foundation-20260731-v21` |
| Lock | `runs/meas0/locks/meas0-foundation-lock-20260731-v21/preregistration.lock.json` |
| Design SHA-256 | `138c9be3f7b32e510c8a8283d88ed896e6f5286ff447a2e001a83a1a594b51c2` |
| Lock file SHA-256 | `a33c3a38c767da7de5547330b3f25208927509f7ea7afba90b9e4ef0fea5443d` |
| Lock seal file SHA-256 | `afec96b76c33342f1f3b968d17ee1199f597e527f14912097c2a4efc8f0722bc` |
| Run seal file SHA-256 | `f1f9f972c9ea2bbadfee310123bb61f97c29de3f46abcc338315d85118ac2d2d` |
| Artifact bundle hash | `c865d53de95795591e1e07897f0e0da61c686f950db076f29209308d74b96d67` |
| Case manifest file SHA-256 | `a6557169be54390bb3e63a28249a32cc2d47dc65e5488a952c627d2479e05cf8` |
| Case manifest logical hash | `42b33e8f7cbcc41c350ca8d1afe2be8bf39c13547782a9d9d99de0f3e9996dab` |
| Run shell | `meas0.pilot-run-shell.v11` |
| Foundation runner | `meas0.pilot-foundation.v9` |
| Claim limit | `pilot_foundation_only_not_a_formal_meas0_pilot_result` |

The schema-v2 lock embeds the exact design bytes and binds 26 source files,
11 package fixtures, and 3 evaluators. The run seal covers 1,280 files.

## v21 additions

### Judge response and independent probes

- `p_pass_0_1` is a mandatory independent pass probability used for
  calibration reporting; it is not inferred from selected-verdict confidence.
- `judge_version` now identifies the versioned JudgeCard, while provider/model
  identity remains separate.
- The legacy two-presentation J-CAL runner derives only order instability.
  Missing style and repeat relations produce fail-closed rates and quarantine;
  the same call pair is no longer reused for three metrics.
- A separate test-only probe manifest registers 48 independent order, style,
  and repeat relations. It does not select protected corpus bytes or live
  budgets.

### Trust and cost contracts

- Transport and human roots are domain separated. Signed receipt payloads bind
  verified-TLS observations, exact request/response ancestry, phase, sequence,
  revocation snapshot, and batch linkage.
- Only a deterministic test verifier exists. All verification results remain
  `contract_only`; production policy is deny-all until real roots and keys are
  approved.
- The immutable StageCost ledger covers `jcal → pilot → jaudit →
  confirmatory`, preserves failed calls, binds PriceManifest ancestry, derives
  budget stops, and separates per-arm automatic cost from all-in costs.
- No production price or phase budget was invented.

### Detection oracle candidate

- The candidate oracle covers exactly F01-F18 for both frozen task adapters and
  derives detection from allow-listed artifact signals.
- Gold, `accept_allowed`, safety verdicts, and top-level automatic status are
  forbidden oracle inputs.
- Detection records cannot be caller-filled and are re-derived during strict
  round-trip validation.
- Every candidate manifest and record remains `test_only_candidate` and
  `formal_eligible=false`; exact production predicates and signatures remain
  formal-lock inputs.

## Verification

- 36 frozen cases and 180 arm-case results were retained.
- All 36 cases use task-native measurement plans.
- Three replay commands returned `verified=true` and the same replay hash:

```text
764f4de578dba38f24053cc92725e19f90f4fe63a0265e20c50b623a0017fc4a
```

- Full regression: `693 passed`.
- Ruff checks for the changed MEAS0 modules and tests passed.
- sdist and wheel built successfully without isolation.
- The wheel installed in an external virtual environment and imported the
  trust, stage-cost, detection-oracle, and Judge-probe modules.

## Remaining boundary

Production readiness still lacks:

- real independently administered transport and human trust roots/keys;
- signed per-call receipts integrated through provider, corpus, and run
  ancestry;
- protected production J-CAL/J-AUDIT corpora and independently registered
  probe bytes;
- approved J-CAL/J-AUDIT phase budgets, PriceManifest, and ledger integration
  in the formal runner;
- approved gold, blind review/adjudication, exact signed production detection
  oracle, OS isolation/preflight, and role assignments;
- signed comparison locks, production Subject/Judge backends, formal Pilot,
  and confirmatory execution.

Therefore v21 is stronger offline engineering evidence, not formal experiment
evidence. Gate M remains `FAIL`.

## Reproduction

```bash
export PYTHONPATH="$PWD/src"
python -m biofield.meas0 replay \
  --run runs/meas0/pilot/meas0-foundation-20260731-v21
python -m biofield.meas0 summarize \
  --run runs/meas0/pilot/meas0-foundation-20260731-v21
```

## Prohibited conclusions

This result must not be cited as evidence that Gate M passed, a formal Pilot or
confirmatory experiment ran, `evaluation_plane` outperformed another arm, or
D/O1/O2/Field/self-improvement claims are supported.
