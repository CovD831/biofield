# LA1 scripted local-agency technical result v2

Date: 2026-07-31

> **2026-07-31 provenance correction:** runner v3 correctly retained
> post-metrics finalization failures and authoritative failure metrics, but an
> already-written successful `summary.md` was not explicitly labelled as a
> non-authoritative partial summary. Runner v4 closes that reporting ambiguity;
> the current reviewed result is
> [LA1 Scripted Technical V3](./LA1_SCRIPTED_TECHNICAL_V3.md). The three
> completed v6 scenario results below are unchanged historical evidence.

## Verdict

**LA1 §7.3/§7.5 scripted technical criteria remain achieved. Formal
claim-bearing Gate 1 activation remains pending MEAS0 Gate M.**

Three fresh `la1-artifact-runner-v3` runs supersede the v5 package. They add
the package bootstrap to the 19-source closure, bind governance evidence to
the outer run identity, and make finalization, summaries, and failed-run
metrics semantically replayable rather than accepting self-consistent
rehashing.

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
| LA1 §7 technical package | supported by the three v6 runs |
| Formal Gate 1 activation | **pending Gate M** |

## Canonical evidence

| Scenario | Run | Events | Config lock SHA-256 | Config seal SHA-256 | Finalization SHA-256 | Public terminal projection SHA-256 |
|---|---|---:|---|---|---|---|
| success | `runs/la1-scripted/la1-success-20260731-v6` | 46 | `2a650da1623d3c22455aafc5bc05a53aa8078c457d781fde91cf659919907b87` | `3b163cd54763f9e729f3d1c20d61a8d03d36101d2491d1271d97219f3c43ea63` | `6c2d2d4dd09f2cc563c6193eb59c95b17cd7133cc4f9ebbb37f650426106ff07` | `0d5b4136f88fdfde6705883a8ab890d74a38f592e64ef22723df0777a08ab76c` |
| action failure recovery | `runs/la1-scripted/la1-failure-recovery-20260731-v6` | 20 | `48163f185a675ced6c4457d0c0b8c4130bc18f4918b898a8542e76656733b335` | `8d8a0d6e9176d4cc0596aeab01cdf2b4ead990e508e77e2b800d43e274766716` | `3c9dd5c5c05d95176c6b47beb14bb0d0563498c0584154ca602cf0990f541cce` | `d1c3b44f775fc181e0dc994111a4c664c7ddaf9b60674617523a47618564a162` |
| governance paths | `runs/la1-scripted/la1-governance-paths-20260731-v6` | 6 wrapper events plus sealed native traces | `dd1f4248a7238eb7211e450dca993bcd3bb7948909801fb4f210a5ac0ce953e1` | `be593ff592b2fe3fc2f7e06c9aa2f035dd1f85bd24229d78821d696e599de2b2` | `0316373ddc7ffa7f1663ed53dd247089f2bccc904b1d7d9539af694051bedf9c` | `c9ce79800f0a04c28d5c8bd805c23c960e140b2e3704276920215db9eff06304` |

Each run independently replays and binds 19 source files. The manifest now
includes `src/biofield/__init__.py`; an AST regression check confirms there
are no missing or extra local transitive imports.

## §7.3 and §7.5 coverage

The current runs retain all ten required scenarios:

1. private-state-dependent Intent differentiation;
2. concurrent Bid resolution;
3. Refusal followed by another Agent takeover;
4. structured communication that changes later legal behavior;
5. accepted Feedback updating Residual and local state;
6. rejected Feedback producing no completion or positive credit;
7. disputed Feedback entering quarantine and revalidation;
8. insufficient resources rejecting the Bid;
9. Agent action failure producing a new Commitment;
10. checkpoint resume equalling full replay.

All eight §7.5 criteria remain satisfied: Action/Commitment ancestry,
public-event provenance, LocalState version/source continuity, illegal
proposal zero-side-effects, Refusal/communication behavioral effect,
accepted/rejected/disputed correctness, replay/checkpoint equivalence, and
Ledger conservation/terminal sealing.

The governance scenario retains six top-level wrapper events. Its complete
rejected and disputed native traces remain sealed in
`artifacts/governance_paths.json` and are semantically re-executed on replay.
The outer run ID is now carried by the native manifest, OrganizationSnapshot,
and governance artifact.

## v2 hardening

- `AdmissionDecision` has canonical round-trip reconstruction and verifies
  outer decision/policy ancestry against its Commitment.
- Finalization requires the exact schema, experiment ID, run ID, terminal
  status, and frozen status-specific reason.
- Completed and failed summaries are regenerated during replay.
- Early and post-metrics failure artifacts use exact key sets, complete
  nonnegative finite CostVector data, failure-event identity, and
  authoritative/partial reference checks.
- Injecting a `gate1_passed` field or forged summary and updating all locally
  recomputable hashes is rejected.
- Governance evidence is generated from the outer run ID.
- Runner-terminal failure retention remains covered by deterministic
  early/late/post-metrics failure-injection tests.

The broad LA slice passes 137 tests.

## Limitations

- These are deterministic scripted fixtures, not real-model trials.
- The governance wrapper-level state-provenance denominator remains
  `not_applicable`; its two native state updates are sealed and replayed.
- There is no equal-cost Single/Fixed/Central/Local-no-field/Local-field
  comparison.
- Source hashes detect drift but do not by themselves restore an uncommitted
  historical source tree. A clean commit, wheel, or source bundle is required
  before upgrading this package to formal evidence.
- A machine-readable aggregate Gate 1 activation object should be added before
  formal activation, after typed E0/LA0/GateM receipts are frozen. It is not a
  current §7.3/§7.5 criterion and must not invent a Gate M receipt.

## Historical evidence

[LA1 Scripted Technical V1](./LA1_SCRIPTED_TECHNICAL_V1.md) and the v5 runs
remain immutable historical audit records. They should not be claimed as
replayable by the current runner-v3 source tree.

## Prohibited conclusions

This result does not prove real-model differentiation, Field increment,
emergent topology, organization net benefit, O1/O2, longitudinal improvement,
or Harness self-modification.
