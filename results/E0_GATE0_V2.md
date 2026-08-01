# E0 deterministic public replay Gate 0 reviewed result v2

Date: 2026-07-31

## Verdict

**Gate 0 remains supported for `f0.native.v2`.**

Canonical v3 supersedes canonical v2 as the current E0 evidence package. It
does not change the Gate 0 claim, public event semantics, four terminal paths,
or pass criteria. It adds exact raw-byte binding for the two package fixtures
used by Evidence → Feedback replay and an explicit legacy replay dispatcher.

This remains evidence only for the deterministic Harness causal substrate. It
does not support real-model, differentiation, Field, organization, O1/O2, or
self-improvement claims.

## Canonical evidence

| Item | Value |
|---|---|
| Run | `runs/e0/e0-20260731-v3` |
| Lock | `runs/e0-locks/e0-lock-20260731-v3/e0.lock.json` |
| Runner | `e0.artifact-runner.v2` |
| Lock schema | `2` |
| Stream | `f0.native.v2` |
| Lock SHA-256 | `a32da59e8118d59838a5073ed0d571cd3ac39f2e0f25970bac400bd2192e833f` |
| Lock seal SHA-256 | `a386f634a3cc85fcc20d41ed0a930e304599db66f0a6d61d50e2c9666aebc00c` |
| Run seal SHA-256 | `38964e29098a3c61e6dab7486708fd9f61953d76c2f44c6977d26b202c500955` |
| Artifact bundle SHA-256 | `aa9d3f26d1665ff16fa27d87cdc8fcaf9970fe1e86a43a63045de502400b807a` |
| Replay SHA-256 | `e57c82c65e124cefd9885b8b30922f8e8a481baf16c89bb9a8302d629a6418ff` |
| Model/Judge/human calls | `0 / 0 / 0` |

The run contains 75 public events. All four terminal cases report
`primitive_replay_verified=true`, `evidence_feedback_verified=true`, and
checkpoint/full replay equivalence:

- `completed`;
- `failed`;
- `budget_exhausted`;
- `max_cycles`.

Three independent replay invocations returned the same replay hash above.

## v3 evidence hardening

### Exact package-data closure

The schema-v2 lock binds ten Python source files and these exact raw package
resources:

| Fixture | SHA-256 |
|---|---|
| `r1/cold_chain_readiness/task.v1.json` | `dbd38a6d77583d6ced24349f53df9672efc34a45571c21084fb12981a1fb1be9` |
| `r1/cold_chain_readiness/answer_key.v1.json` | `a22fa9b63e016e7a9b658a0a0ff7692ede9484bcee45a6e5702d9396b31e74ae` |

The fixture manifest is copied into `source_manifest.json` and checked during
prepare, execute, and replay. A raw-byte-only JSON drift now fails closed even
when its parsed semantic object is unchanged. The existing task, answer-key,
and verifier semantic hashes remain independently checked.

### Source closure and legacy replay

An AST regression test verifies the transitive local Python import closure.
Schema-1 / runner-v1 packages are accepted only by an explicit replay-only
dispatcher using the frozen ten-file legacy manifest; they cannot start new
executions. Canonical v2 therefore remains historically replayable with its
original replay hash, while new packages must use schema 2 and runner v2.

## Gate criteria

All Gate 0 criteria remain satisfied:

- empty-state replay matches the sealed terminal projection;
- checkpoint resume equals full replay for all four paths;
- duplicate events are idempotent;
- conflicting duplicates, missing parents, version/order drift, terminal
  writes, settlement omission, and artifact tampering fail closed;
- Evidence → Feedback is recomputed from the frozen verifier contract;
- Residual and Ledger primitives replay without exposing hidden gold;
- failed runs retain machine-readable failure and complete CostVector data;
- IDs are write-once and finalized artifacts reject mutation.

The E0 replay/artifact slice passes 60 tests.

## Historical evidence

Canonical v2 and [E0 Gate 0 V1](./E0_GATE0_V1.md) remain immutable historical
audit records. V2 is the current reviewed conclusion because it adds exact
package-data byte closure without changing the Gate claim.

## Prohibited conclusions

This result must not be used as evidence for real-model capability, local
agent differentiation, Field value, organization benefit, O1/O2, or
self-improvement.
