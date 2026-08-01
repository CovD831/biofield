# MEAS0 D12 source-restoration selection — 2026-08-01

Status: **SELECTED POLICY / ARTIFACTS NOT YET PROVIDED / NO FORMAL EXECUTION AUTHORIZED**

## Decision

The project owner selected the D12 self-contained restoration mechanism:

> Seal the exact source archive, built wheel and source distribution,
> dependency-lock bytes and dependency artifacts, environment manifest, and
> build metadata required for independent replay.

An authority-bound content-addressed artifact receipt is not the selected
primary restoration mechanism. A mutable checkout, local path, or a hash-only
reference is never an acceptable substitute.

## Required sealed closure

For a future separately authorized formal execution, the closure must contain
the exact bytes and SHA-256 digest of each of the following:

1. source archive with a canonical inventory of project source and package
   data;
2. built wheel and source distribution;
3. dependency lock and each resolved wheel or source-distribution artifact;
4. environment manifest and build metadata;
5. source-lock bytes and their bindings to the package, plan, readiness lock,
   and outcome evidence; and
6. an immutable sealed artifact package from which a fresh process can restore
   the selected bytes without consulting the current checkout.

The fresh verifier must recompute every digest, verify exact source-lock
membership, install only the sealed dependency artifacts in an isolated
environment, and fail closed on a missing, extra, substituted, or drifted
artifact.

## Current boundary

The existing D12 candidate codec binds the relevant bytes deterministically,
but it remains `simulated_nonclaim/test_only`. No real archive, dependency
artifact set, independent storage seal, signer, or formal source-restoration
approval has been supplied. Consequently:

- `source_restoration_authorized` remains `false`;
- fresh replay and formal execution remain unauthorized;
- no historical run is resealed or upgraded; and
- Gate M remains `FAIL / NOT_EVALUATED`.

This selection narrows the required future handoff; it does not create the
external evidence or authority needed to complete that handoff.
