# MEAS0 formal protocol amendment V2

Date: 2026-07-31

Status: **normative implementation amendment; formal execution not authorized**

Approval provenance: the user instructed the project to continue after review
of [the D1-D4 decision packet](./MEAS0_FORMAL_DECISION_PACKET_DRAFT.md). This
records approval to implement and test the recommended protocol offline. The
conversation record and this document are not cryptographic approval evidence,
do not provide a trust root, and do not authorize provider calls, external
cost, a formal comparison lock, or a Gate M upgrade.

This amendment is read together with
[MEAS0 Design V1](./MEAS0_DESIGN_V1.md). V1 remains authoritative except for
the explicit clarifications below. This amendment does not change:

- the two tasks, F01-F18, five arms, or paired comparisons;
- primary metrics or Gate thresholds;
- gold precedence or the Evaluation Plane authority boundary;
- Pilot/confirmatory sample structure;
- the prohibition on using foundation or test-only evidence as formal evidence.

## 1. Trusted transport

Formal Judge evidence requires a per-call signed transport receipt for every
J-CAL, J-AUDIT, Pilot, and confirmatory attempt, including failed attempts.

The accepted minimum claim is:

> An independently administered gateway observed the exact request and response
> bytes over the approved, verified TLS endpoint and signed their ancestry.

It is not a provider attestation of internal model execution. The gateway must
be outside the Harness rewrite and administrative domain and use a separately
authorized workload identity and signing key. A Harness/local signer, username,
transport ID, approval metadata, or bundle-supplied unpinned public key remains
contract-only.

The canonical receipt payload binds:

- trust-root/key/algorithm/claim-scope identifiers;
- provider, endpoint, requested and observed model identity;
- TLS hostname/SNI, peer certificate/SPKI/chain hashes, verification result,
  trust-store hash, and verification-policy hash;
- exact request fingerprint and bytes hash;
- exact response hash and byte count, or an explicit absent-response failure;
- invocation, criterion, presentation, phase, comparison block, design, lock,
  and data-attestation hashes;
- status/failure, observed times, nonce, sequence, previous receipt or batch
  root, and revocation snapshot.

Transport and human-approval trust roots are separately scoped. Out-of-band
root manifests bind each key to its role, allowed purpose, and phase. Production
verification remains deny-all until actual roots, operators, keys, revocation
policy, and independent review are present in a signed lock.

Subject generation continues to use sealed black-box artifact provenance and
is not blocked on the Judge gateway receipt. Any later decision to require
Subject transport receipts needs a separate amendment.

## 2. Judge response and identity

The next response schema adds:

```text
p_pass_0_1: number in [0, 1]
```

`p_pass_0_1` is the Judge's raw probability of `pass` and is used only for
Brier/ECE reporting. It does not override `verdict`, create a verdict threshold,
or grant additional authority. `confidence_0_1` remains confidence in the
selected verdict. No implementation may infer `p_pass_0_1` from
selected-verdict confidence.

`judge_version` equals the versioned `JudgeCard.card_id`. Provider/model/system
identity is recorded separately. `model_digest` is the SHA-256 of a reviewed
black-box identity manifest, not a weight digest. The manifest binds provider,
endpoint contract, requested and observed model/system fingerprints, evidence
refs, observation date, and reviewer.

`qualification_time` is evaluator derivation time. Transport observation and
approval times remain distinct.

The values `8111/8117` are deterministic presentation-schedule identifiers,
not provider seeds. DeepSeek V4 Pro thinking continues to record
`effective_seed=unsupported`.

## 3. Independent instability probes

Order flip, style flip, and repeat disagreement must be derived from distinct,
registered presentation relations:

- order: normal versus a semantic-equivalent order reversal;
- style: normal versus a separately sealed semantic-equivalent style variant;
- repeat: two calls over the identical registered presentation.

The same call pair cannot populate more than one instability metric. Style flip
remains a qualification condition. Repeat disagreement remains report-only.

The protected calibration/audit probe manifest freezes exact presentation
bytes, relation IDs, schedule IDs, call count, and budget before execution.
Until such a manifest is present, J-CAL/J-AUDIT readiness fails closed. This
amendment does not invent live corpus bytes or a live-call budget.

## 4. Protected corpus and stage cost

J-CAL/J-AUDIT contents, gold, reviews, adjudications, and raw outputs are
protected, versioned, hash-bound artifacts in a separately authorized store.
Public/package manifests expose only non-leaking hashes and metadata. J-AUDIT
is disjoint from J-CAL by source case/template/entity and remains inaccessible
to Prompt/rubric/parser development roles until its approved stage.

An append-only, hash-chained stage ledger uses:

```text
jcal / pilot / jaudit / confirmatory
```

Every entry binds phase, request/call/receipt ancestry, provider and cost class,
tokens, time, bytes, retries, PriceManifest hash, and monetary microunits.
Failed calls remain in the ledger. J-CAL/J-AUDIT use separate preregistered
sub-budgets and do not enter per-arm equal-cost comparisons. Reports separately
show:

- automatic per-arm execution cost;
- Subject and Judge provider charges;
- gateway/KMS and infrastructure charges;
- human gold/review/adjudication/escalation time and direct payment;
- all-in total.

Existing Pilot/confirmatory caps are unchanged. Missing phase budgets,
PriceManifest ancestry, currency/FX as-of, token-class pricing, gateway charges,
or cap scope blocks readiness.

The pre-calibration lock also freezes exact Prompt, rubric, parser, schema,
JudgeCard, identity, corpus-manifest, price, budget, and modification authority.
After J-AUDIT exposure none may change within the design version.

## 5. Detection oracle

Formal metrics may not accept caller-supplied `detection_expected` or
`detected`. Both are produced by a versioned oracle from arm-authorized
artifacts. The oracle may not read hidden gold or use only the top-level verdict
as proof of detection.

The oracle manifest:

- covers exactly F01-F18 for both task adapters;
- binds design, fault, case, task-adapter, evaluator, and source hashes;
- freezes authorized and forbidden artifact fields;
- freezes exact predicate, reason code, stage, evidence refs, and
  paired/subepisode aggregation;
- is authored and independently reviewed;
- produces hash-bound derived detection records.

Gate 13.2.5 remains restricted to
F03/F04/F05/F07/F08/F09/F13/F17. The implementation may contain test-only
candidate predicates, but production readiness remains false until the exact
18-by-two-task oracle is independently reviewed, signed, and lock-bound.

## 6. Human roles and signatures

Formal execution adopts the stricter no-overlap role policy:

- fixture/gold author;
- blind reviewers A and B;
- adjudicator C;
- preflight executor;
- preflight reviewer D;
- user/comparison-lock authority E;
- independent lock reviewer F;
- operational escalator G.

F attests independent review and does not share or replace E's approval
authority. If required role separation cannot be satisfied, the run remains
exploratory and confirmatory cannot start.

Human approval uses domain-separated detached signatures. Envelopes bind
purpose, role, phase, comparison block, design/lock/evidence hashes, signer key
fingerprint, sequence/nonce, algorithm, signature, and observed signing time.
Time is non-authoritative unless a trusted time source is separately approved.
The root manifest binds key to role, purpose, and phase.

Actual role IDs, public-key fingerprints, custody, rotation/revocation, blind
package custody, review deadlines, correction policy, evidence allowlist, and
raw retention/deletion/legal-hold policy are formal-lock inputs. Test identities
or keys cannot satisfy production readiness.

## 7. Required order

1. Implement and validate the offline contracts in this amendment.
2. Prepare and independently review gold and the protected J-CAL corpus.
3. Freeze and sign a pre-calibration lock.
4. Run J-CAL and derive qualification or quarantine.
5. Only after J-CAL passes, review and sign the Pilot comparison lock, then run
   formal Pilot.
6. If the design is unchanged, review and sign the confirmatory lock binding
   the held-out J-AUDIT manifest hash.
7. Run J-AUDIT without exposing protected content to development roles.
8. If J-AUDIT passes, sign a final execution authorization binding the
   unchanged confirmatory lock and audit result, then run confirmatory.

No existing foundation result is retroactively reclassified. Contract tests,
synthetic keys, candidate oracles, and fake providers remain test-only.
