from __future__ import annotations

import json

import pytest

from biofield.meas0_composite_closure_v3 import (
    CompositeClosureError,
    SimulatedCompositeClosureV3,
)
from biofield.meas0_protected_raw_bundle_v3 import SimulatedProtectedRawBundleV3
from biofield.meas0_raw_package_closure_v3 import SimulatedPublicPackageClosure
from test_meas0_raw_package_closure_v3 import _sources


def _carriers() -> tuple[SimulatedPublicPackageClosure, SimulatedProtectedRawBundleV3]:
    candidate, manifest, references = _sources()
    public = SimulatedPublicPackageClosure.create_from_typed_sources(
        expected_package_id=manifest.package_id,
        pilot_candidate=candidate,
        protected_vault_manifest=manifest,
        protected_references=references,
    )
    protected = SimulatedProtectedRawBundleV3.create_from_typed_sources(
        expected_package_id=manifest.package_id,
        common_ancestry_hash=candidate.common_ancestry_hash,
        protected_vault_manifest=manifest,
        protected_references=references,
        payloads={
            references[0].object_id: b"exact protected test task bytes",
            references[1].object_id: b"exact protected test judge bytes",
        },
    )
    return public, protected


def test_composite_binds_two_carriers_but_stays_nonclaim() -> None:
    public, protected = _carriers()
    composite = SimulatedCompositeClosureV3.create_from_typed_sources(
        public_closure=public, protected_bundle=protected
    )
    assert composite.package_id == public.package_id
    assert composite.public_closure_hash == public.closure_hash
    assert composite.protected_bundle_hash == protected.bundle_hash
    assert composite.raw_package_closed is False
    assert composite.source_restoration_authorized is False
    assert composite.fresh_replay_ready is False
    assert composite.test_only is True


def test_composite_canonical_restore_rederives_membership() -> None:
    public, protected = _carriers()
    composite = SimulatedCompositeClosureV3.create_from_typed_sources(
        public_closure=public, protected_bundle=protected
    )
    restored = SimulatedCompositeClosureV3.restore_from_canonical_bytes(
        composite.to_canonical_bytes(),
        public_closure=public,
        protected_bundle=protected,
    )
    assert restored == composite
    assert restored.to_canonical_bytes() == composite.to_canonical_bytes()


def test_composite_rejects_substitution_and_forged_upgrade() -> None:
    public, protected = _carriers()
    composite = SimulatedCompositeClosureV3.create_from_typed_sources(
        public_closure=public, protected_bundle=protected
    )
    forged = json.loads(composite.to_canonical_bytes())
    forged["fresh_replay_ready"] = True
    forged_raw = json.dumps(forged, sort_keys=True, separators=(",", ":")).encode()
    with pytest.raises(CompositeClosureError, match="source-derived"):
        SimulatedCompositeClosureV3.restore_from_canonical_bytes(
            forged_raw, public_closure=public, protected_bundle=protected
        )

    with pytest.raises(CompositeClosureError, match="typed public closure"):
        SimulatedCompositeClosureV3.create_from_typed_sources(
            public_closure=object(), protected_bundle=protected
        )
