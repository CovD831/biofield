# MEAS0 V3 approval checklist

Date: 2026-07-31

Status: **NON-NORMATIVE / NOT APPROVED**

This checklist is a compact decision surface for the proposed corrective
amendment. It does not amend MEAS0 V1/V2, authorize external execution, create
a trust root, or change any task, fault, arm, comparison, sample size,
statistic, budget maximum, threshold, or Gate rule.

The detailed proposals are:

- [Corrective amendment V3 draft](./MEAS0_CORRECTIVE_AMENDMENT_V3_DRAFT.md)
- [Fresh replay and input binding draft](./MEAS0_FRESH_REPLAY_AND_INPUT_BINDING_DRAFT.md)
- [Implementation TDD plan](./MEAS0_IMPLEMENTATION_TDD_PLAN_V1.md)
- [Completion audit](../../results/MEAS0_COMPLETION_AUDIT_V1.md)

## Decision set

| ID | Decision requiring owner approval | Recommended choice |
|---|---|---|
| D1 | Readiness sequence | Use append-only `PRE_JCAL_READY → PILOT_READY → JAUDIT_READY → CONFIRMATORY_READY`; an earlier receipt never requires future evidence. |
| D2 | Judge identity before/after J-CAL | Freeze a pre-J-CAL Judge specification/identity object; create a separate post-J-CAL qualification card with derived metrics. |
| D3 | Checkpoint signature target | Sign a typed phase payload binding the exact lock, qualification, plan/provider manifest, ledger head, comparison block, and previous checkpoint—not an opaque caller hash. |
| D4 | Execution inputs | Seal exact Pilot 36-case and confirmatory 144-case input manifests plus protected canonical bundle, episode, failure-policy, and adapter bytes; production plans are factory-derived only. |
| D5 | Protected evidence boundary | Keep a public non-leaking package plus an ACL-restricted/encrypted protected evidence vault. Raw Gold, reviews, protected corpora, raw provider bytes, and keys never enter the public package. |
| D6 | Judge transport evidence | Freeze phase-specific exact Judge-attempt membership, including failed attempts/retries; retain exact request/response bytes or absent-response records in the protected vault and cryptographically reverify them. |
| D7 | Gold authority | Derive `gold_status`, `accept_allowed`, and `safety_violation` only from locked Gold scope/artifact/review/adjudication ancestry; bind selected record hashes into package/seal. |
| D8 | Retained failure projection | Preserve V1 semantics: unavailable/timeout/parser failures produce unavailable measurement evidence and normally `unknown` through fusion; integrity contamination is `invalid/null`; budget exhaustion retains evidence and derives `unknown` or `fail`; no new task status. |
| D9 | Confirmatory package | Require one exact 144×5/720-entry sealed package with a single comparison-block, lock, authorization, oracle, Gold, source, budget, provider, and run ancestry. |
| D10 | Hard Gate and Gate M | Derive §13.1 only from the fresh-replayed sealed package. Incomplete evidence is `NOT_EVALUATED`; a complete assessment missing any §13.1/§13.2 requirement is `FAIL`; only a complete passing assessment is `PASS`. |
| D11 | Detection authority | Formal detection measurands come from independently governed typed measurements/protected getters/provenance/failure evidence and are independently reconstructed or checked. Backend `detection_signals` remain audit-only. |
| D12 | Replay/source/CLI/claim boundary | Fresh replay receives public package + protected vault + approved source artifact/resolver + human/transport verifiers. Prefer sealed source/wheel artifacts over the current checkout; use Python dependency injection initially; do not approve arbitrary plugin loading. Keep execution-contract, oracle-outcome, and Gate claim scopes explicit and separate. |

## Test-evidence rule

Synthetic fixtures and test verifiers remain `test_only` or
`simulated_nonclaim`. They may exercise shared deterministic validation logic,
but they must not create `ProductionVerificationResult`,
`formal_result=true`, a production-eligible package, or a formal Gate receipt.
A true production-authority positive path therefore remains blocked until real
external roots, signatures, providers, protected inputs, and approvals exist.

## Approval effect

Approving D1–D12 would authorize only the offline TDD implementation described
in the implementation plan. It would not authorize:

- real provider/Judge calls or external spend;
- use of protected production corpora or personal data;
- creation of a formal comparison lock or production signatures;
- a formal Pilot, J-AUDIT, confirmatory run, or Gate M decision.

Any requested change to D1–D12 should be incorporated into a revised draft
before a normative amendment is published.

