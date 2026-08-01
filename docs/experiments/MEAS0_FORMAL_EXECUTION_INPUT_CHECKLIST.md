# MEAS0 Formal Execution: Authorization and Input Checklist

Date: 2026-08-01  
Status: **DRAFT / NO FORMAL EXECUTION AUTHORIZED**

## Purpose and limits

This is the minimum intake checklist for a separately authorized formal MEAS0
execution. It turns the external prerequisites in the [V3 formal
amendment](./MEAS0_FORMAL_PROTOCOL_AMENDMENT_V3.md) and [formal decision
packet](./MEAS0_FORMAL_DECISION_PACKET_DRAFT.md) into concrete deliverables.

Completing a row means that the named evidence has been supplied, verified,
and bound into the execution ancestry. A checkbox, chat approval, test result,
or offline fixture is not a substitute for that evidence. This document does
not authorize provider calls, expenditure, protected-data access, a formal
lock, or a Gate M assessment.

## 1. Decision and accountability

| ID | Required authorization or input | Evidence that must be bound | Accountable role | State |
|---|---|---|---|---|
| A1 | Named decision owner and execution owner | Signed decision record with scope, date, comparison block, and revocation/contact path | Decision owner | `UNAVAILABLE` |
| A2 | Budget and provider-call authority | Approved spend ceiling, permitted providers/regions, billing owner, and stop conditions | Budget owner | `UNAVAILABLE` |
| A3 | Protected-data authority | Data classification, allowed purpose, retention/deletion policy, ACL approver, and access audit mechanism | Data steward | `UNAVAILABLE` |
| A4 | Independent review roles | Named Gold reviewer/adjudicator, Judge reviewer, and final Gate reviewer; separation constraints recorded | Governance owner | `UNAVAILABLE` |
| A5 | Trusted signing and time policy | Signer identities, public verification material, trusted-time source, revocation policy, and signature-verification procedure | Trust-root owner | `UNAVAILABLE` |

## 2. Production inputs

| ID | Required input | Minimum bound content | State |
|---|---|---|---|
| P1 | Authority-bound backend descriptor | Provider/model/version/region, request adapter hash, capability constraints, endpoint policy, and responsible owner | `UNAVAILABLE` |
| P2 | Production price and transport evidence | Provider quote or price source, FX basis where applicable, gateway/infrastructure charges, signed/verified transport receipts, and independent verifier identity | `UNAVAILABLE` |
| P3 | Protected J-CAL and J-AUDIT material | Corpus/version hashes, task membership, Judge specification, ACL/encryption references, retention policy, and approved access path | `UNAVAILABLE` |
| P4 | Gold authority package | Locked Gold scope, reviewed/adjudicated records, reviewer signatures, selected-record hashes, and acceptance/safety derivation inputs | `UNAVAILABLE` |
| P5 | F01–F18 typed sources | For every required measurand: protected getter/source, relation or trial definition, failure policy, provenance, approval, checker/tool, ACL, and ordered-progress authority | `UNAVAILABLE` |
| P6 | Formal detection oracle | Request/plan-bound approved oracle root, version, signer/review record, and independent reconstruction/check method | `UNAVAILABLE` |
| P7 | Source-restoration closure | **Selected:** exact source archive + wheel + source distribution + dependency lock/artifacts + environment/build metadata; immutable package and independent verification procedure still required | `SELECTED / ARTIFACTS UNAVAILABLE` |

## 3. Formal lock and execution sequence

The following steps are permitted only after sections 1 and 2 have been
verified by the designated owners. Each result must be sealed and append-only;
an unavailable prerequisite leaves the next state unavailable rather than
being replaced with a simulated value.

| Order | Required sealed artifact | Acceptance condition | State |
|---|---|---|---|
| E1 | Preflight and provider/price manifest | Verifies A1–A5 and P1–P7; records exact environment, source closure, budget, and stop policy | `NOT_STARTED` |
| E2 | Formal comparison lock and phase checkpoints | Binds the comparison block, task/input manifests, source closure, provider/price manifest, Gold and oracle ancestry, and trusted signatures/time | `NOT_STARTED` |
| E3 | Formal Pilot (36×5) and J-AUDIT evidence | Protected raw request/response or absent-response records, exact attempt membership including retries, qualified Judge evidence, and independently checked receipts | `NOT_STARTED` |
| E4 | Confirmatory run (144×5, 720 outcomes) | One sealed package with one comparison block and complete input, cost, transport, Gold, oracle, authorization, and source ancestry | `NOT_STARTED` |
| E5 | Fresh-process replay and independent review | Replays the sealed package with approved source restoration and protected verifiers; produces no upgrade if verification is incomplete | `NOT_STARTED` |
| E6 | Terminal Gate M assessment | Derives `PASS`, `FAIL`, or `NOT_EVALUATED` solely from complete sealed evidence and the approved hard-Gate rule | `NOT_STARTED` |

## 4. Authorization handoff

Before requesting execution, the decision owner should supply one signed
handoff containing:

1. the completed A1–A5 and P1–P7 evidence references;
2. the exact scope and comparison block to authorize;
3. explicit approval for protected-data handling, provider calls, and any
   external spending;
4. the names and public verification material for all signers and independent
   reviewers; and
5. the selected source-restoration closure from P7, including the sealed bytes
   and independent verification handoff.

Until that handoff is independently verified, MEAS0 remains `FAIL` and Gate M
remains `NOT_EVALUATED`. The [existing V3 approval checklist](./MEAS0_V3_APPROVAL_CHECKLIST.md)
continues to govern offline implementation decisions only.
