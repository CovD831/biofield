# MEAS0 V3 offline implementation progress V1

Date: 2026-07-31  
Authority: engineering progress record only  
Protocol: `docs/experiments/MEAS0_FORMAL_PROTOCOL_AMENDMENT_V3.md`

## Status

D1–D12 have been approved only as an offline implementation specification.
This record reports deterministic contract engineering. It is not a formal
Pilot, confirmatory result, Gate M assessment, production trust receipt, or
scientific claim. No real provider, protected production data, external cost,
or production authority was used.

## Implemented offline contracts

- B1 typed V3 checkpoint targets with exact phase evidence membership and
  append-only target ancestry.
- B2 `PRE_JCAL_READY → PILOT_READY → JAUDIT_READY →
  CONFIRMATORY_READY` simulated readiness receipts, including failed and
  quarantined parent rejection.
- B2a exact-36 Pilot protected corpus/input manifest. The public manifest binds
  the typed case scope, PRE-J-CAL parent, comparison block, source-lock hash,
  common ancestry, native adapter digest, task bundle, episode, failure policy,
  and derived counts. The Pilot target reverse-binds the manifest hash.
- A factory-only, `simulated_nonclaim` Pilot plan candidate whose 36 case inputs
  are derived from the input manifest and whose price, budget, StageCost,
  readiness, and source-lock ancestry are checked. Pilot and confirmatory plans
  now bind one frozen V3 budget policy and its offline validation receipt;
  attempted calls and retries count against the limit, while J-CAL/J-AUDIT are
  explicitly excluded from per-arm equality. This validates configured ceilings
  only and does not verify provider usage, time, tokens, prices, or paid cost.
- A simulated protected-evidence vault contract with location-free public
  references, exact-byte hashes/counts, ordered membership, write-once sealing,
  and no production encryption or ACL claim.
- An exact-byte carrier for the existing schema-v2 Pilot source lock. It does
  not read the current checkout and explicitly does not authorize source
  restoration.
- B3 reviewed-Gold case facts and a tagged nonclaim Gold-bound arm-case outcome.
  Caller-provided `gold_status`, `accept_allowed`, and `safety_violation` are
  absent from the V3 factory surface. A typed Gold order-lock receipt now binds
  the PRE-J-CAL/Pilot readiness ancestry and exact review/adjudication
  membership. It proves deterministic append-only structural order only, not
  trustworthy wall-clock time or signature authority.
- B4 D8 retained-failure projection. Typed evidence now distinguishes timeout,
  provider error, response-bound malformed parsing, total/stage budget stops,
  and request-bound protocol ancestry violations. Malformed parsing requires a
  signed response-bearing successful transport attempt whose byte hash/count
  exactly match the parser input. Protocol expectations are derived from the
  typed request, not caller hashes. Backend-invalid remains explicitly
  unconstructable because the current request/plan schema has no authoritative
  backend-descriptor ancestry.
- Strict typed-source restore paths for the Measurement Plane, Pilot candidate,
  Gold facts/outcome, and retained-failure objects. Persisted hashes and outcomes
  are comparison targets; bundle/episode seals and measurement fusion are
  recomputed.
- A B5 confirmatory structural-commitment slice: exact 144-case manifest,
  frozen five-arm order, exact 720 case-arm commitments, typed authorization,
  common ancestry, StageCost-ledger linkage, and typed-source restoration.
  Exact-prefix checkpoints can resume only to the authorized 720-member
  package. The offline commitment store uses a pinned real-directory root,
  descriptor-relative no-follow I/O, content objects, and an atomic persistent
  package-ID reservation, so concurrent replacement, root swapping, symlink or
  hard-link substitution, and content-object delete-then-reuse fail closed
  while the untrusted local store remains intact.
  The commitment package now also has a strict canonical-bytes restore
  boundary; bytes alone cannot reconstruct it without typed authorization,
  commitment membership, and StageCost ancestry.
  This layer deliberately contains no verified execution, cost, Gold/oracle
  outcome, accepted/detected value, or formal result; it is not a confirmatory
  outcome package.
- B6/B7 Gate coverage diagnostics whose criterion facts and hard-gate status
  are always `UNKNOWN`, whose Gate M state is always `NOT_EVALUATED`, and whose
  formal hard-gate and terminal factories fail closed.
- A partial B8a typed seven-file public Pilot slice. It is derived only from
  typed sources, reverse-binds the protected-vault membership commitments, and
  does not expose protected object IDs as plaintext. It explicitly remains
  `raw_package_closed=false`, `fresh_replay_ready=false`, and
  `source_restoration_authorized=false`. Deterministic commitments do not prove
  hiding of low-entropy object IDs; dictionary confirmation remains an explicit
  gap. The nonclaim public-slice carrier now has a strict canonical-bytes
  round-trip that still requires independently typed Pilot/protected sources,
  expected package identity, and an external closure hash; it does not upgrade
  raw-closure or replay authority.
- B8a now also has a protected-only raw payload bundle candidate. The bundle
  binds exact test payload bytes, typed vault membership, vault-manifest hash,
  ordered reference-index hash, and common ancestry. Its typed and strict
  canonical-bytes restore paths rederive payload hashes/counts and reject
  membership, metadata, duplicate-field, and authority-flag substitution.
  Protected object IDs and bytes remain outside the public projection; this is
  still `simulated_nonclaim/test_only`, with `fresh_replay_ready=false` and no
  source-restoration, transport, signature, or authority-bound package seal.
- A partial B9 test-only transport-membership verifier with policy, batch,
  receipt-chain, nonce/retry, request/response, and StageCost-hash linkage.
  It does not independently verify usage, price, wall time, token count,
  monetary cost, arm, or cost class, so every result remains
  `cost_verified=false`. The typed transport reverification result now also
  supports canonical-bytes restore that reruns the complete typed derivation;
  the legacy cross-batch ancestry and production cost-authority gaps remain
  explicit.
- A first D11 authority-inventory slice that keeps independently derived typed
  structure/failure facts separate from backend `detection_signals`. Raw
  signals are captured only in an audit record fixed to
  `authoritative=false`, `detection_eligible=false`, and
  `formal_eligible=false`. Missing authority is explicit `UNAVAILABLE`; among
  current oracle signal names, only F18 `budget_exhausted` is derived from typed
  failure disposition/evidence. The structure inventory now also names
  `judge_transport_membership_authority_valid` explicitly as `UNAVAILABLE`:
  typed Judge receipt membership is present only as a test-only artifact
  surface, without an injected independent production transport verifier or
  trust root. It likewise names
  `legacy_formal_detection_authority_valid` as `UNAVAILABLE`: the legacy
  formal detector still consumes backend `detection_signals`, and no typed
  source replacement has been integrated into that claim-bearing path. The
  offline oracle binding freezes one projection input but is not a
  request/plan/production-authorized trust root.
  The formal-bound detection projection now rejects before this legacy adapter
  with an explicit typed-source-authority error; this is isolation only, not a
  typed formal replacement, so the legacy authority fact remains
  `UNAVAILABLE`.
- A separate V3 nonclaim outcome package that closes exactly 36×5 case-arm
  membership and can carry Gold-bound leaves or typed retained-failure leaves.
  It is strictly source-replayed, keeps retained failures in the denominator,
  and is intentionally not accepted by the legacy claim-bearing
  `FormalOutcomePackage` or any metric/Gate entry point.
- A D12 self-contained source-closure candidate carrier that binds exact
  source-lock, wheel, sdist, dependency-lock, environment, and build-metadata
  bytes plus a typed dependency-artifact manifest. Its restore path rederives
  every byte hash and candidate hash, rejects unknown fields/path-like IDs and
  authority-flag forgery, and remains explicitly
  `simulated_nonclaim/test_only` with source restoration, fresh replay,
  formal, and production authorization disabled. This implements a candidate
  artifact family only; it now also has a strict canonical JSON-bytes restore
  boundary, but it does not choose the normative source-restoration mechanism
  or create a replay/evidence seal. The opaque artifact/metadata bytes are
  commitments only; they are not semantic source-closure or secret-sanitization
  verification.
- The evidence-derived four-stage lifecycle now has a strict canonical-bytes
  replay boundary. A serialized lifecycle is accepted only when its bytes are
  canonical and every transition is recomputed from independently supplied
  typed checkpoint, ledger, authorization, and qualification sources. This is
  a fresh-process replay carrier for the offline contract only; it does not
  create production evidence or alter Gate M.
- D11 projection and audit objects now also support strict canonical-bytes
  round-trip. Projection restore reruns typed request/artifact/oracle/failure
  derivation; audit restore preserves `audit_only=true`,
  `authoritative=false`, and `detection_eligible=false`. This is a replay
  carrier only and does not replace the legacy formal detector.
- E0 and LA1 replay entry points now reject a symlinked run directory before
  resolving it, closing a path-alias replay ambiguity while preserving the
  existing sealed-file symlink checks. This is an integrity hardening only;
  it does not alter the E0/LA1 claim scope or reviewed canonical run hashes.

All new candidate objects remain `simulated_nonclaim`, `test_only`, and
`production_authorized=false`. They do not create
`ProductionVerificationResult`, `formal_result=true`, a production-eligible
package, or a Gate receipt.

## Independent review corrections

The implementation review caught and corrected the following before this
record:

- provider unavailable and malformed response were initially projected as
  invalid; D8 requires retained `VALID/UNKNOWN` unless a separate integrity
  defect exists;
- the first input manifest omitted case-scope, block, source-lock, and readiness
  ancestry;
- public adapter paths and vault package identifiers could have exposed mutable
  location syntax;
- Gold review membership allowed an extra cross-split reviewer record, and
  adjudication verdicts were not checked against their referenced reviews;
- retained-failure construction initially accepted caller-separated case/arm
  hashes, reused one transport reason across failure classes, omitted typed
  pre-ledger/price ancestry, and incorrectly rejected legitimate zero-valued
  failed cost entries;
- the first malformed-response variant accepted arbitrary bytes beside a
  response-absent failed receipt, and the first protocol/backend variants
  accepted caller-selected expected hashes; parser bytes now bind the successful
  transport receipt, protocol facts derive from typed requests, and backend
  invalidity remains a declared schema gap rather than a false closed loop;
- the measurement codec initially rejected legal integer-valued numeric fields.
- the first confirmatory authorization allowed its embedded plan to be replaced
  without changing its scalar ancestry or package hashes; authorization now
  reverse-validates every embedded-plan binding;
- the first B8a public projection serialized protected object IDs, and its first
  redaction label overstated hiding; plaintext IDs are now omitted while the
  deterministic-commitment dictionary-confirmation gap is explicit;
- the first B9 result overstated StageCost contract verification even though
  only transport membership and hash linkage were authoritative;
- the first B6/B7 DTOs could be locally rehashed after `dataclasses.replace`;
  object construction now fixes all facts to `UNKNOWN` and Gate M to
  `NOT_EVALUATED`.
- the first confirmatory commitment store used an existence check followed by
  ordinary rename, trusted the root path only at construction, and allowed a
  deleted content directory to leave the same package ID reusable; publication
  and restoration now operate through pinned directory descriptors and a
  persistent no-replace reservation. This is not an external immutable-storage
  or adversarial-deletion guarantee.
- the first frozen-budget integration invoked a validator without binding the
  policy and validation hashes into both plan families; Pilot and confirmatory
  objects now reverse-bind both hashes during strict restoration.
- D11 review found the legacy formal projection still reads backend
  `detection_signals`. The new authority slice therefore uses a separate API
  that has no `signals`, `detected`, or `terminal_reason` parameter, and its raw
  audit type cannot enter the authoritative projection.
- The V3 outcome package is intentionally separate from the legacy formal
  outcome DTO; an exact structural closure is available without silently
  migrating nonclaim leaves into formal outcome or metric semantics.
- The public seven-file slice and protected exact-payload bundle now also have
  a separate composite membership carrier. It binds package, common ancestry,
  and both carrier hashes, while remaining explicitly nonclaim: it cannot
  upgrade partial raw closure into source restoration, fresh replay, transport,
  or formal authority.

Each correction received a failing attack test before the implementation was
tightened.

## Verification

- Budget/Gold/commitment-store/failure/confirmatory combined regression:
  `141 passed in 29.49s`.
- Commitment store focused concurrency and integrity regression:
  `21 passed in 18.05s`; an independent final review found no remaining P1
  correctness issue within the cooperative-process/advisory-lock boundary.
- MEAS0 test suite after the D11 authority slice, protected raw bundle,
  confirmatory canonical-bytes
  restore, transport canonical-bytes restore, D12 candidate, and replay-integrity
  fixes:
  focused regressions passed; the current full-suite count is reported below.
- Full test suite, including the LA1 atomic multi-Commitment batch and new
  D11/protected-raw slices: `1104 passed in 194.71s`.
- Ruff check: all source and tests passed.
- All files introduced or edited by this V3 batch pass Ruff format check.
  Pre-existing repository files outside the batch are not globally formatted.
- `git diff --check`: passed.
- Source distribution and wheel: built successfully.
- Isolated wheel import smoke with project runtime dependencies: passed.
- Wheel import smoke test: passed.
- Wheel SHA-256:
  `00acf0f43aa979ab6db9bc44310d0408ac3964f3f22c34c6b755ea9d4578e734`.
- Source distribution SHA-256:
  `790cbc9ea32c1bbe589470c63f89d96e51425566711c51c831e5363609ba4a77`.

These hashes identify local build outputs only. They are not a new canonical
MEAS0 source closure or formal evidence seal.

Independent historical replay verification kept E0 canonical v3 and all three
LA1 canonical v8 terminal hashes unchanged. MEAS0 canonical v27 correctly
failed closed against the evolved checkout with `locked source hash mismatch`;
the only locked-source difference was `meas0_formal_lifecycle.py`. The v27
artifact was not bypassed or resealed, so the current checkout must not be
described as replaying that historical closure.

## Remaining blockers

- The Gold order lock proves structural ancestry only. Trusted time, signer
  identity, and production authorization remain unverified.
- The legacy `FormalOutcomePackage` remains a legacy claim-bearing leaf type;
  the new V3 package is a separate nonclaim closure and does not migrate or
  upgrade those leaves. A formally eligible migration still requires an
  explicit normative decision and production evidence.
- Backend-invalid evidence still needs an authority-bound backend descriptor in
  the request/plan ancestry. The implementation deliberately cannot construct
  that failure class from two caller-provided hashes.
- The first D11 slice is not integrated into the legacy formal detection
  projection, which still consumes backend raw signals. Most F01–F18
  measurands still lack protected getter, relation/trial, approval, checker,
  tool, ACL, or ordered-progress authority and remain `UNAVAILABLE`.
- The offline oracle binding is projection-local only; a request/plan-bound or
  production-authorized oracle root remains absent.
- Complete public/protected raw closure, authority-bound package seal,
  production transport and cost re-verification, confirmatory exact-144/720
  execution/outcomes, hard-Gate derivation, Gate M terminal transition, and
  fresh-process lifecycle replay remain open. The new slices are structural
  precursors only.
- The source-restoration mechanism is not frozen. The approved draft leaves a
  choice between sealing a self-contained archive/wheel/dependency closure and
  binding an immutable content-addressed artifact receipt. The current
  exact-byte source-lock carrier proves neither option.
- No formal lock, real providers, external spend, production roots/keys,
  protected production corpus, or formal approval receipt exists.

The project therefore remains `FAIL`; Gate M remains formally
`NOT_EVALUATED`, and no downstream scientific Gate changes state.
