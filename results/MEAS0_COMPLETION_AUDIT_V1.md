# MEAS0 Formal Completion Audit V1

Date: 2026-07-31

Claim scope: **read-only implementation/protocol coverage audit**

Gate M: **NOT FORMALLY EVALUATED; project status remains FAIL**

This audit does not change the frozen tasks, faults, arms, comparisons,
statistics, thresholds, or Gate M criteria. It corrects the earlier conclusion
that the offline implementation was complete through the formal shell and that
only external production inputs remained.

## What remains valid

- Canonical MEAS0 foundation v27 remains a sealed, deterministic 36-case /
  180-result offline foundation run with 36/36 task-native cases and three
  identical replay hashes.
- The trust, StageCost, exact J-CAL/J-AUDIT invocation, candidate-oracle,
  lifecycle, formal-runner, and write-once-store primitives remain useful
  contract-tested components.
- Candidate/test-only evidence still cannot be upgraded to production evidence
  by a Boolean or serialized `ProductionVerificationResult`.
- No production provider, reviewer, verifier, signing service, or paid endpoint
  was called.

## Current P0 gaps

1. **Protocol order and readiness conflict.** The frozen amendment requires
   staged authorization: pre-J-CAL, J-CAL, Pilot, J-AUDIT, then confirmatory.
   The current production runner requires one final `FORMAL_READY` bundle that
   already contains J-AUDIT and later checkpoint evidence before Pilot can
   start. An honest Pilot is therefore not reachable through the current
   readiness contract.
2. **No sealed confirmatory execution path.** The typed runner, oracle-bound
   outcomes, and store cover 36×5 Pilot artifacts. Gate M requires a
   confirmatory 144×5 corpus, but the current Gate function accepts a loose
   outcome mapping rather than one sealed, common-ancestry confirmatory run.
3. **Gold outcome ancestry is caller-controlled.** Formal outcome derivation
   accepts `gold_status`, `accept_allowed`, and `safety_violation` as arguments
   instead of deriving them from the reviewed, locked Gold records in
   readiness evidence.
4. **Hard-gate evidence is caller-reported.** The §13.1 hard-gate assessment
   consumes IDs, counts, and Booleans rather than deriving them from sealed
   run/store/replay/trust/lifecycle evidence.
5. **Retained failures cannot always enter the outcome package.** The runner
   correctly retains timeout/provider-failure denominator entries, but outcome
   derivation currently requires canonical evaluation evidence for all 180
   artifacts. A legitimate retained failure can therefore make the formal
   package uncomposable.
6. **Checkpoint targets are opaque hashes.** Signature verification binds an
   envelope to a hash, but does not yet prove that each target is the required
   phase-specific lock, qualification, run, audit, or provider manifest.
7. **Gate M lifecycle transition is absent.** The lifecycle deliberately
   returns only `NOT_EVALUATED`; no factory consumes one sealed confirmatory
   package plus derived §13.1/§13.2 assessments to produce a formal PASS/FAIL.
8. **Fresh-process replay is incomplete.** The store requires original
   in-memory typed objects. It does not persist and reverify the raw readiness
   authority, source lock, Pilot input manifest, or runtime transport policy,
   and it does not reconstruct canonical measurement leaves and outcomes from
   sealed bytes.
9. **The legacy formal CLI is a deliberate dead end.** It cannot inject
   production verifiers or a backend, rejects formal execution, and rejects
   formal replay/summarize. A separate Python-only contract path exists, but it
   is not yet a complete serialized production lifecycle.
10. **Runtime transport receipts are structurally checked, not
    cryptographically reverified.** Production replay still needs an injected
    transport verifier over the Pilot runtime receipt batch.
11. **The production plan is not bound to a sealed input corpus.** Per-case
    task-bundle, episode, failure-policy, measurement-count, semantic-leaf, and
    adapter values can be supplied as valid-looking hashes/counts. Readiness
    does not yet contain a canonical 36-case input manifest plus the exact
    protected bytes needed to reconstruct those values.
12. **Raw protected evidence is not a complete replay archive.** A public run
    package cannot safely contain hidden Gold, protected Judge corpora, review
    material, or raw provider content, while hashes alone cannot reproduce
    them. A separately protected, access-controlled evidence vault and
    authority-bound public references are not yet specified or implemented.
13. **Pilot request/response byte ancestry is incomplete.** Runtime receipts
    bind request/response hashes, but the store does not preserve or resolve
    every exact protected request/response byte sequence and prove that parser,
    artifact, receipt, and StageCost ancestry used those same bytes.
14. **Formal detection can still inherit backend-authored convenience
    signals.** Re-reading an observation's `detection_signals` and applying a
    signed predicate is not independent derivation. A formal adapter must
    derive its measurands from typed canonical measurements, protected getters,
    provenance/failure records, or an independently governed producer.

## Required design decisions before implementation

The gaps that define phase authority, claim-bearing outcomes, protected
evidence, detection authority, and Gate semantics cannot be chosen by
implementation alone. Before further MEAS0 production work, approve:

- phase-specific readiness/authorization objects rather than one all-at-once
  `FORMAL_READY` bundle;
- a typed 144×5 confirmatory run/package/store sharing one comparison-block,
  run, authorization, oracle, and source-lock ancestry;
- derivation of gold and hard-gate facts exclusively from reviewed and sealed
  evidence;
- an explicit retained-failure outcome rule;
- typed checkpoint target payloads for each phase;
- a final lifecycle transition that derives Gate M PASS/FAIL from the sealed
  confirmatory and hard-gate evidence;
- a production input manifest and protected 36-case input corpus;
- the public-package/protected-vault boundary, raw request/response retention,
  and authoritative formal-detection measurands.

Fresh-process codecs, raw-authority persistence, strict re-derivation, and
external verifier injection are engineering follow-ons once those choices are
fixed.

## Other tracks

- E0 canonical v3 was independently replayed in this audit and remains Gate 0
  support.
- LA0 remains complete as the deterministic local-agency contract layer.
- LA1 canonical v8 success, failure-recovery, and governance runs replay
  correctly and continue to satisfy the scripted §7.3/§7.5 technical criteria.
  Formal Gate 1 remains inactive while Gate M is unresolved.
