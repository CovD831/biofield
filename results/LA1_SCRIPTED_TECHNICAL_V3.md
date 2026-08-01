# LA1 scripted local-agency technical result v3

Date: 2026-07-31

## Verdict

**LA1 §7.3/§7.5 scripted technical criteria remain achieved. Formal
claim-bearing Gate 1 activation remains pending MEAS0 Gate M.**

Three fresh `la1-artifact-runner-v4` runs supersede the v6 package. The
scientific design, scenarios, metrics, controls, and passing criteria are
unchanged. Runner v4 closes a failed-run reporting ambiguity: when a
post-metrics finalization failure leaves an immutable successful `summary.md`,
that file is now explicitly hash-bound as a non-authoritative partial summary,
while a separate write-once `artifacts/failure_summary.json` is the sole
authoritative failed-run summary.

All three canonical runs are completed scripted scenarios. Deterministic
runner-terminal failure retention is supported separately by attack and
failure-injection tests; it is not misrepresented as one of the three
completed canonical scenarios.

## Dependency status

| Dependency | Status |
|---|---|
| E0 | Gate 0 supported by [E0 Gate 0 V2](./E0_GATE0_V2.md) |
| LA0 | contract layer supported by [LA0 Contract V1](./LA0_CONTRACT_V1.md) |
| MEAS0 / Gate M | **FAIL**; only foundation engineering is supported |
| LA1 §7 technical package | supported by the three v7 runs |
| Formal Gate 1 activation | **pending Gate M** |

## Canonical evidence

| Scenario | Run | Events | Config lock SHA-256 | Config seal SHA-256 | Finalization SHA-256 | Public terminal projection SHA-256 |
|---|---|---:|---|---|---|---|
| success | `runs/la1-scripted/la1-success-20260731-v7` | 46 | `3efd81de40db05e92ebe874111b28586b6e65956f7a033fb6c0a05b9a9212a0a` | `4e44773f37cf575b78f9fc7ab0f809f2bbfcad160531d90412f35603d4a29305` | `71564e75e667d333b9f2be86d1edc1c64124c6be04a737297a75d6612385fea9` | `feee80de2a49293e16de26e16335269789d667a8768656c9991c91c734f3702a` |
| action failure recovery | `runs/la1-scripted/la1-failure-recovery-20260731-v7` | 20 | `c31a6cbee5b1d80982e9c0591c274ee0de8428f23bbcc22b0053f9b2bd632fca` | `f999937ed6af1cf78e7a71110096daf3674580d69c93247e09c6270593c2d774` | `ec5318093219a471f6a251fdc817593380dc2d5fa2c2946f21a250638d64dd43` | `ce796bfe3591bac07e37858ef941e2fa2789b67380a68da674e73987a2f2a1c7` |
| governance paths | `runs/la1-scripted/la1-governance-paths-20260731-v7` | 6 wrapper events plus sealed native traces | `611821456602620b850a57169f28e2cd7936103f8fec8ef0767b3a3e39807f5c` | `a572aad6fc7ba6ffc4ad5f130702a53c0a9f8e2013e0ad95c095baff60c0e583` | `0c4062c97bca97e4b0c9a6b7fe815e74d132b68eeec8cf267ab58c86a7bbb3b4` | `227109ed69c73221b19242ea6961b34409ed9b6c4991a79e3f8e09f8ce00783f` |

Each run independently replayed three times and binds the exact 19-source
local runtime closure, including `src/biofield/__init__.py`.

## §7.3 and §7.5 coverage

The v7 runs retain all ten required scenarios: private-state-dependent Intent
differentiation, concurrent Bid resolution, Refusal/takeover, behavior-changing
communication, accepted Feedback state change, rejected Feedback without
positive credit, disputed quarantine/revalidation, resource rejection, action
failure recovery, and checkpoint/full replay equivalence.

All eight §7.5 criteria remain satisfied: Action/Commitment ancestry,
public-event provenance, LocalState version/source continuity, illegal
proposal zero-side-effects, Refusal/communication behavioral effect,
accepted/rejected/disputed correctness, replay/checkpoint equivalence, and
Ledger conservation/terminal sealing.

## v3 hardening

- Post-metrics failures always create a write-once authoritative
  `artifacts/failure_summary.json`.
- An earlier successful `summary.md` is retained only as a hash-bound
  `partial_summary` with `authoritative=false`.
- Authoritative failure metrics and the final-state hash bind the authoritative
  and optional partial summary references.
- Replay reconstructs the failure summary, verifies exact keys and hashes, and
  rejects an unlabelled valid summary in a failed run.
- The completed-run scenarios, metrics, governance paths, outer run identity,
  and 19-source closure are unchanged.

The LA1 artifact test file passes 30 tests. The broad LA slice passes 138
tests.

## Limitations

- These are deterministic scripted fixtures, not real-model trials.
- The governance wrapper-level state-provenance denominator remains
  `not_applicable`; its two native state updates are sealed and replayed.
- There is no equal-cost Single/Fixed/Central/Local-no-field/Local-field
  comparison.
- Source hashes detect drift but do not restore an uncommitted historical
  source tree. A clean commit, wheel, or source bundle is required before
  upgrading this package to formal evidence.
- A machine-readable aggregate Gate 1 activation object remains deferred until
  typed E0/LA0/Gate M receipts are frozen.

## Historical evidence

[LA1 Scripted Technical V2](./LA1_SCRIPTED_TECHNICAL_V2.md),
[V1](./LA1_SCRIPTED_TECHNICAL_V1.md), and their canonical runs remain
immutable historical audit records. They must not be presented as current
runner-v4 evidence.

## Prohibited conclusions

This result does not prove real-model differentiation, Field increment,
emergent topology, organization net benefit, O1/O2, longitudinal improvement,
or Harness self-modification.
