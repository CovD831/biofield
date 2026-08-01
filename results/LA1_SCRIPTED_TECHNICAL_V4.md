# LA1 scripted local-agency technical result v4

Date: 2026-07-31

## Verdict

**LA1 §7.3/§7.5 scripted technical criteria remain achieved. Formal
claim-bearing Gate 1 activation remains pending MEAS0 Gate M.**

Three fresh `la1-artifact-runner-v5` / `la1.metrics.v2` runs supersede the v7
package. The frozen scenarios, controls, and passing criteria are unchanged.
Runner v5 adds a separately scoped machine-readable provenance metric for
native state updates inside the governance artifact.

## Canonical evidence

| Scenario | Run | Events | Config lock SHA-256 | Config seal SHA-256 | Finalization SHA-256 | Public terminal projection SHA-256 |
|---|---|---:|---|---|---|---|
| success | `runs/la1-scripted/la1-success-20260731-v8` | 46 | `beed12df20795ea96b10ca46ed12b00cfd91a06264309564f5f8a191f34fa1d5` | `87eaca7691f4c1aeff148bdf81f16a05f05ccb51fe75e95591d78c214cd30476` | `04dee479073e620fce96cbb35b0179c6858efe1d9bd3308b536213016adcdc8a` | `d789c66b05c40facc3379bf3400f22bb5940958aabcdded7afc0162d7b8a99d5` |
| action failure recovery | `runs/la1-scripted/la1-failure-recovery-20260731-v8` | 20 | `61f5f514f3f95ddc809c5b090a4fd6d0b417e6dfd5d63c1aabe86be82f2cc6d3` | `aabb7cbe51c68fd834081d08cbdb07a1a56354080d8198e4e0c4326830b37b5c` | `5175f1bdff6385e9190965c2483aba316814a4fa08febf26cf6c5fdf280270c3` | `4f028c4b91c50e7dfbfbcbbc2289b696c9bcb6d7910ef55f0c8118b0c0f88777` |
| governance paths | `runs/la1-scripted/la1-governance-paths-20260731-v8` | 6 wrapper events plus sealed native traces | `6140caf536f7954e082c98e48c50e365970f2f850b842ae9f0f6c8c43c5ba92b` | `e0d58665a2ff863ad9861b9f7327f8a7700851a5c5c3f1915fe9d4d7b030dd54` | `4aced4b0d3fb74b71c3773b58604c0032d71070af3b7d1465dafd10380539231` | `a3a842e69890027049ba761ac1d7e1572bbd1c0f5906f83814f8348a605c6fd9` |

Each run binds the exact 19-source local runtime closure. Each was replayed
three times after sealing; all nine invocations reproduced the terminal hash.

## Native state provenance

The wrapper-level `state_update_provenance` metric remains
`not_applicable` for governance paths, preserving its original scope and
denominator.

Runner v5 adds `native_state_update_provenance` only to the governance
scenario. It inspects both sealed native traces and requires every
`local_state_update` to have:

- integer `previous_state_version → next_state_version` continuity;
- non-identical 64-character before/after state hashes;
- a non-empty source event window;
- every source-window ID included in causal parents;
- per-agent continuity for multiple updates in one native trace.

The canonical governance run reports:

```json
{
  "denominator": 2,
  "numerator": 2,
  "rate": 1.0,
  "status": "measured",
  "trace_count": 2
}
```

Replay independently recomputes the metric. Source-parent drift is covered by
a fail-closed test.

## Verification

- LA1 artifact tests: `31 passed`.
- The broader/full regression is reported in the current project status.
- All existing §7.3 ten-scenario and §7.5 eight-criterion coverage remains.
- No model, Judge, human, network, or paid call was made.

## Limitations

- These remain deterministic scripted fixtures, not real-model trials.
- There is no equal-cost Single/Fixed/Central/Local-no-field/Local-field
  comparison.
- Source hashes detect drift but do not restore an uncommitted historical
  source tree; formal evidence still requires a clean source bundle or other
  approved provenance.
- Formal Gate 1 activation remains pending Gate M.

## Historical evidence

[V3](./LA1_SCRIPTED_TECHNICAL_V3.md), [V2](./LA1_SCRIPTED_TECHNICAL_V2.md),
and [V1](./LA1_SCRIPTED_TECHNICAL_V1.md) remain immutable historical records.

## Prohibited conclusions

This result does not prove real-model differentiation, Field increment,
emergent topology, organization net benefit, O1/O2, longitudinal improvement,
or Harness self-modification.
