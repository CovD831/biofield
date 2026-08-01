# AGENTS.md

## Purpose

This file defines the development rules for the standalone Biofield research project.

## Development principles

- Diagnose the concrete experimental or contract gap before changing behavior.
- Prefer the smallest change that preserves explicit contracts and reproducibility.
- Keep engineering viability separate from scientific evidence and architecture claims.
- Do not introduce OpenPilot runtime dependencies into this repository.

## Boundaries

- `src/biofield/contracts.py`, `residual.py`, and `ledger.py` own deterministic state contracts.
- `allocator.py`, `dynamics.py`, `metrics.py`, and `synthetic.py` own offline allocation experiments.
- `a0_*`, `model_probe.py`, `probe_assets.py`, and `ollama_adapter.py` own model probes.
- `f0.py` and `f0_model.py` own the bounded action-to-evidence feedback loop.
- `src/biofield/fixtures/` contains versioned package data; access it through `biofield.resources`.
- `results/` contains reviewed conclusions. Raw machine output stays under ignored `runs/`.

## Tool and network policy

- Unit tests must be deterministic, offline, and repeatable.
- Tests must not require Ollama, a live model, or public network access.
- Live model probes are explicit manual validation and must record model identity, seed, request fingerprint, and source hashes.
- Never silently overwrite an existing run directory or weaken artifact sealing.

## Testing and change discipline

- Follow test-driven development: add or update a failing test before changing behavior.
- Every contract, resource-loading, lifecycle, or CLI change needs matching tests.
- Keep changes localized; do not combine unrelated architecture refactors.
- Before committing, run the full test suite and build both wheel and source distribution.
- Any package-data change must be verified from a wheel installed outside the checkout.

## Documentation sync

Review and update the relevant current documents when behavior changes:

- `README.md`
- `docs/README.md`
- `docs/architecture/ARCHITECTURE_EXPLORATION_FINAL.md`
- `docs/experiments/EXPERIMENT_PROTOCOL.md`
- `docs/experiments/EXPERIMENT_ROADMAP_REVIEW_V1.md`

Historical architecture versions under `docs/architecture/history/` and completed result reports under `results/` are audit records. Do not rewrite them merely to modernize current wording; add a dated correction or provenance note when necessary.
