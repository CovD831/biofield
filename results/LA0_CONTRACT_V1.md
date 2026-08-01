# LA0 local-agency contract-layer reviewed result v1

Date: 2026-07-31

> **2026-07-31 provenance note:** the LA0 conclusion is unchanged. The
> current downstream LA1 package is canonical v7 / runner v4; the v6 reference
> in the original verification text below records the package reviewed with
> this LA0 result.

## Verdict

**LA0 contract-layer criteria pass for deterministic offline engineering.**

LA0 is not an independent scientific Gate. It provides the contract and
authority substrate consumed by LA1. Formal Gate 1 activation still depends
on E0, LA0, LA1, and MEAS0 Gate M.

This result does not prove real-model differentiation, hostile-process
isolation, Field value, emergent organization, or organization net benefit.

## Requirement coverage

The implementation and offline tests cover:

- `LocalFieldObservation`, `AgentIntent`, `AgentBid`, `AgentCommitment`, and
  `AgentRefusal`;
- `CommunicationOffer` / `CommunicationRequest`, permit, delivery, receipt,
  quota, and single-consume governance;
- `LocalStateUpdate`, `UpdateSurfaceManifest`, and
  `ExperienceUpdateRecord`;
- `OrganizationSnapshot`;
- deterministic single- and multi-Bid Admission;
- Action authorization and Commitment lifecycle;
- public-state redaction of private values.

All public contracts in the LA0 surface now support deterministic canonical
round-trip serialization. In particular, `AdmissionDecision` now reconstructs
both admitted and rejected results and cross-checks its decision ID and policy
version against the nested Harness-issued Commitment.

## Protocol §6.2 failure coverage

The current tests reject:

- stale or wrong-audience observations and intents;
- missing Bid target/cost bounds, invalid parents, and budget excess;
- invalid grant/Commitment ancestry and Action bypass;
- malformed Refusal retry conditions;
- unauthorized, over-quota, or wrong-schema communication;
- state version jumps, empty source windows, forbidden fields, and writes
  after finalization;
- experience compiler/validation/rollback defects, unapproved destination
  surfaces, and consumption of rejected/quarantined experience;
- private-state publication and permission/resource escalation;
- nondeterministic Admission input ordering and post-finalization admission.

## Verification

The focused LA0 contract slice contains 63 tests and passes offline:

```text
63 passed
```

The broader LA runtime slice contains 137 passing tests. The three current LA1
v6 sealed runs also exercise the LA0 contracts through success, action-failure
recovery, and governance paths.

## Boundaries

- The deterministic resolver and scripted runtime are in-process engineering
  evidence, not a hostile-code security boundary.
- Multiple Commitment atomic materialization is a later organization/concurrency
  enhancement, not a missing LA0 criterion.
- Formal Gate 1 remains pending MEAS0 Gate M.
