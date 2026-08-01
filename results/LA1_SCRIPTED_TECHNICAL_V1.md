# LA1 scripted local-agency technical result v1

Date: 2026-07-30

## Verdict

**LA1 §7.3/§7.5 scripted technical criteria achieved. Formal claim-bearing
Gate 1 activation remains pending MEAS0 Gate M.**

Three canonical `la1-artifact-runner-v2` runs jointly cover the ten required
scripted scenarios, the frozen §7.4 metrics, checkpoint/full replay, failure
retention, configuration locking, and terminal sealing.

This is an engineering result for scripted agents. It is not evidence that a
real model differentiates, that local organization has net benefit, that Field
adds value, or that O1/O2/self-evolution exists.

## Dependency status

| Dependency | Status |
|---|---|
| E0 | Gate 0 supported by `results/E0_GATE0_V1.md` |
| LA0 | contract-layer criteria pass offline tests |
| MEAS0 / Gate M | **not passed**; only foundation engineering is supported |
| LA1 §7 technical package | supported by the three runs below |
| Formal Gate 1 activation | **pending Gate M** under the frozen DAG |

This wording preserves the protocol dependency instead of silently treating
LA1's internal technical success as an activated downstream Gate.

## Canonical evidence

| Scenario | Run | Events | Config lock SHA-256 | Config seal SHA-256 | Finalization SHA-256 | Public terminal projection SHA-256 |
|---|---|---:|---|---|---|---|
| success | `runs/la1-scripted/la1-success-20260730-v5` | 46 | `94639405879f1f0b72922d1183dbbc617a919cfc768dd8903e946e201e2f1f93` | `1d9c3eccbf2c5ed5c1f08a7e6b294d3f200731cb8ed97c612402448e1da8c6be` | `e8f37f5e078a2c251e008df40afea5928b4575d4a85bf738c00311cd6634eb63` | `658925cf8afe2c7572de4396ecd1ba49aed2dbbd4d3a5b66d479256a09aa7bbd` |
| failure recovery | `runs/la1-scripted/la1-failure-recovery-20260730-v5` | 20 | `46e8e907e2614b60aed5285a0a4ad09b3303c72ece0e6976ceac9ec9f79a85be` | `57b67bc5bd4d9947e7c5d60aa2e67579d6353e1dc5fc2197e9019f5790470b32` | `6e99f1540d7378480458b37211601b5bdb298884067c466f4c2542c3275df0a9` | `7ef2d8357c2d7f27d73513100525daf6bf9aa3eb19e5b7fe98ada59eddf25073` |
| governance paths | `runs/la1-scripted/la1-governance-paths-20260730-v5` | 6 wrapper events plus sealed native traces | `f6773f974b7ec4e763ebfbbd60637279c751ba13c99b4e5ed4b3268668fdc33e` | `443e834608d1385153b9b16ff8f54db81ba59e6ec55c23e19d2bb432c94e681c` | `a84414afed9eba9aecc434921b49f8ef229adb696faaf380d417c402f6c031ac` | `df82869394c0abb50ab2d2a46315d5bad4ee5e12f3cd8dbf12e3a3ad368c7659` |

All three runs are `completed`, replay successfully from sealed artifacts, use
no model/Judge/human calls, and record exact source hashes for the transitive
LA runtime closure. The checkout commit is
`9dc412520387d0c9cda700f49744305ff9f99acd`; the dirty file list is sealed in
each config.

## §7.3 scenario coverage

| Required scenario | Canonical evidence | Result |
|---|---|---|
| Same Field, different private states produce different Intent | success | pass |
| Concurrent Bids are resolved from public rules | success | pass |
| Refusal is followed by a different Agent takeover | success; ordering-aware `refusal_recovery=1/1` | pass |
| Communication delivers structured Evidence and changes later legal behavior | success; 1 message, 104 bytes, 3 communication tokens | pass |
| Accepted Feedback updates Residual and local state | success | pass |
| Rejected Feedback creates neither completion nor positive credit | governance paths; lifecycle `CANCELLED`, Residual `UNMET`, contribution `0` | pass |
| Disputed Feedback enters quarantine and independent revalidation | governance paths | pass |
| Insufficient resources reject/degrade a Bid | governance paths; `budget_limit` | pass |
| Agent failure causes a new Commitment | failure recovery; one reorganization | pass |
| Checkpoint resume equals full replay | failure recovery | pass |

The governance run's `canonical_path_coverage` has four true fields:

- `rejected_feedback_no_positive_credit`;
- `disputed_quarantine_revalidation`;
- `resource_insufficient_rejected`;
- `illegal_proposal_zero_side_effects`.

The wrapper events do not replace native evidence. The complete native rejected
and dispute streams plus admission results are sealed in
`artifacts/governance_paths.json`; replay re-executes the real governance
functions and verifies the wrapper, artifact, and terminal hashes.

## §7.4 metrics

The success run records:

- contract validity `46/46`;
- refusal recovery `1/1`;
- one communication message, 104 bytes, and 3 actual communication tokens;
- state-update provenance `1/1`;
- Ledger conservation for the frozen 100-token budget;
- one accepted and one failed/cancelled Commitment cycle;
- a complete 15-field CostVector.

The failure-recovery run records:

- contract validity `20/20`;
- one failed/cancelled and one completed Commitment;
- one reorganization/retry;
- checkpoint/full replay equivalence;
- Ledger conservation.

The governance run records:

- contract validity `6/6` for the top-level wrapper stream;
- admission rejection reasons `action_not_allowed=1` and `budget_limit=1`;
- illegal rejection `1/1`, with zero admitted Bids and zero side effects;
- all four canonical governance coverage flags;
- a complete CostVector including two native state updates, three verifier
  calls, four deterministic checks, and one revalidation retry.

Metric denominators, zero-denominator `not_applicable`, organization snapshot
statistics, public terminal hashes, residual cycles, and CostVector fields are
machine-readable and replayed.

## §7.5 criteria

| Criterion | Result |
|---|---|
| Every executed Action references a valid Commitment | pass |
| Public-state changes trace to committed events | pass |
| LocalStateUpdate versions and sources are complete | pass |
| Illegal proposals have no side effects | pass |
| Refusal and communication alter later legal behavior | pass |
| accepted / rejected / disputed paths are correct | pass |
| Full replay and checkpoint resume agree | pass |
| Ledger conservation and terminal sealing pass | pass |

## Evidence-governance hardening

Independent review initially found three classes of defect. They were fixed
before the canonical runs:

1. **Prepare was not a real preregistration freeze.**  
   Every run now writes independent, write-once `config_lock.json` and
   `config_seal.json`; execution and replay verify the complete config bytes,
   including environment and exclusion policy.

2. **Mid/late failures were not uniformly replayable.**  
   Early, post-event, post-artifact, post-metrics, summary, and finalization
   failures now retain a sealed failed run. If normal `metrics.json` already
   exists, it is preserved as a hash-bound non-authoritative partial artifact;
   write-once `failure_metrics.json` becomes authoritative, reports
   `invalid-run`, includes failure and all CostVector fields, and omits the
   successful public terminal hash.

3. **The two original scenarios did not seal all §7.3 paths.**  
   `governance_paths` adds real rejected, disputed/revalidated,
   resource-insufficient, and illegal-proposal executions.

The review also exposed a direct runtime bug: Action success plus rejected
Feedback incorrectly completed a Commitment. The runtime now completes only
when Action status is `SUCCEEDED` **and** Feedback is `ACCEPTED`; rejected and
other non-accepted outcomes cancel the Commitment without positive credit.

Other hardening includes complete transitive source hashes, nested artifact
file-set sealing, symlink rejection, ordering-aware refusal recovery, actual
communication-token accounting, and JSON CLI error contracts.

Post-hardening validation includes 22 artifact tests and a 137-test LA broad
slice. Independent replay of the three predecessor v2 scenarios passed; the
v5 runs above were regenerated with the final, wheel-portable source closure
after the runner version was advanced to `la1-artifact-runner-v2`.

## Reproduction

For each scenario, first prepare and then execute:

```bash
python -m biofield.la1_artifacts prepare \
  --output-directory runs \
  --run-id <fresh-run-id> \
  --scenario <success|failure_recovery|governance_paths>

python -m biofield.la1_artifacts run \
  --run-directory runs/la1-scripted/<fresh-run-id>

python -m biofield.la1_artifacts replay \
  --run-directory runs/la1-scripted/<fresh-run-id>

python -m biofield.la1_artifacts summarize \
  --run-directory runs/la1-scripted/<fresh-run-id>
```

Existing IDs are never overwritten.

## Limitations

- These are deterministic scripted fixtures, not real-model trials.
- The governance metric aggregator uses six top-level wrapper events; native
  state updates are sealed and replayed and counted in CostVector, but the
  top-level `state_update_provenance` denominator is `not_applicable`. This is a
  reporting-clarity limitation, not missing native evidence.
- The result does not compare Single, Fixed, Central, Local-no-field, or
  Local-field arms under equal cost.
- It does not demonstrate emergent topology, net organization benefit,
  cross-task selection, O2 memory, longitudinal improvement, or Harness
  self-modification.
- Under the frozen experiment DAG, formal Gate 1 remains inactive until Gate M
  is satisfied by a real formal MEAS0 evidence package.
