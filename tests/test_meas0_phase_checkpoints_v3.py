from __future__ import annotations

from dataclasses import replace

import pytest

from biofield.meas0_formal_lifecycle import (
    FormalLifecycleError,
    PhaseCheckpointTarget,
    SimulatedPhaseCheckpointAuthorization,
    authorize_simulated_phase_checkpoint,
    validate_v3_phase_checkpoint_chain,
)
from biofield.meas0_trust import (
    AuthorizationCheckpoint,
    AuthorizationCheckpointRequirement,
    TrustDomain,
    TrustVerificationMode,
    VerificationResult,
)


def _hash(character: str) -> str:
    return character * 64


def _bindings(
    checkpoint: AuthorizationCheckpoint,
) -> dict[str, str]:
    names = {
        AuthorizationCheckpoint.PRE_JCAL: (
            "human_trust_policy",
            "jcal_manifest",
            "judge_identity_manifest",
            "judge_specification",
            "precalibration_lock",
            "price_manifest",
            "stage_budget_manifest",
            "transport_trust_policy",
        ),
        AuthorizationCheckpoint.PILOT_START: (
            "formal_oracle_authority",
            "gold_binding",
            "isolation_preflight",
            "jcal_invocation",
            "jcal_qualification",
            "jcal_stage_cost",
            "jcal_transport",
            "pilot_input_manifest",
            "pilot_lock",
            "precalibration_lock",
            "provider_manifest",
        ),
        AuthorizationCheckpoint.POST_PILOT_JAUDIT: (
            "confirmatory_lock",
            "jaudit_manifest",
            "pilot_package",
            "unchanged_design_surface",
        ),
        AuthorizationCheckpoint.CONFIRMATORY_START: (
            "confirmatory_lock",
            "confirmatory_input_manifest",
            "confirmatory_plan",
            "jaudit_invocation",
            "jaudit_qualification",
            "jaudit_stage_cost",
            "jaudit_transport",
            "provider_manifest",
        ),
    }[checkpoint]
    return {name: "123456789abcdef"[index] * 64 for index, name in enumerate(names)}


def _targets() -> tuple[PhaseCheckpointTarget, ...]:
    values: list[PhaseCheckpointTarget] = []
    for index, checkpoint in enumerate(AuthorizationCheckpoint):
        values.append(
            PhaseCheckpointTarget.create(
                checkpoint=checkpoint,
                lifecycle_id="pytest.phase-checkpoints.v3",
                comparison_block_id="pytest.meas0.block.v3",
                authority_role_id="human-approval-authority",
                design_hash=_hash("a"),
                source_lock_hash=_hash("b"),
                common_ancestry_hash=_hash("c"),
                ledger_pre_head_hash=("d", "e", "f", "0")[index] * 64,
                evidence_bindings=_bindings(checkpoint),
                previous_target=(values[-1] if values else None),
            )
        )
    return tuple(values)


def _verification(target: PhaseCheckpointTarget) -> VerificationResult:
    return VerificationResult(
        schema_version=1,
        verified=True,
        production_authorized=False,
        claim_scope="contract_only",
        mode=TrustVerificationMode.TEST_ONLY_CONTRACT,
        trust_domain=TrustDomain.HUMAN_APPROVAL,
        policy_hash=_hash("8"),
        root_manifest_hash=_hash("9"),
        payload_hash=target.target_hash,
        envelope_hash=_hash("7"),
        blockers=(),
    )


def test_v3_targets_round_trip_with_canonical_phase_chain() -> None:
    targets = _targets()

    assert tuple(item.checkpoint for item in targets) == tuple(AuthorizationCheckpoint)
    assert targets[0].previous_target_hash is None
    assert tuple(item.previous_target_hash for item in targets[1:]) == tuple(
        item.target_hash for item in targets[:-1]
    )
    assert len({item.common_ancestry_hash for item in targets}) == 1
    assert (
        tuple(PhaseCheckpointTarget.from_dict(item.to_dict()) for item in targets)
        == targets
    )


def test_v3_target_rejects_phase_purpose_previous_and_ancestry_tamper() -> None:
    targets = _targets()

    with pytest.raises(FormalLifecycleError, match="phase/purpose"):
        replace(targets[1], purpose="pre_jcal")
    with pytest.raises(FormalLifecycleError, match="previous"):
        replace(targets[2], previous_target_hash=_hash("f"))
    with pytest.raises(FormalLifecycleError, match="common ancestry"):
        PhaseCheckpointTarget.create(
            checkpoint=AuthorizationCheckpoint.POST_PILOT_JAUDIT,
            lifecycle_id=targets[1].lifecycle_id,
            comparison_block_id=targets[1].comparison_block_id,
            authority_role_id=targets[1].authority_role_id,
            design_hash=targets[1].design_hash,
            source_lock_hash=targets[1].source_lock_hash,
            common_ancestry_hash=_hash("f"),
            ledger_pre_head_hash=_hash("e"),
            evidence_bindings=_bindings(AuthorizationCheckpoint.POST_PILOT_JAUDIT),
            previous_target=targets[1],
        )
    with pytest.raises(FormalLifecycleError, match="evidence bindings"):
        PhaseCheckpointTarget.create(
            checkpoint=AuthorizationCheckpoint.PRE_JCAL,
            lifecycle_id="pytest.phase-checkpoints.v3",
            comparison_block_id="pytest.meas0.block.v3",
            authority_role_id="human-approval-authority",
            design_hash=_hash("a"),
            source_lock_hash=_hash("b"),
            common_ancestry_hash=_hash("c"),
            ledger_pre_head_hash=_hash("d"),
            evidence_bindings={"jcal_manifest": _hash("1")},
            previous_target=None,
        )


@pytest.mark.parametrize("checkpoint", tuple(AuthorizationCheckpoint))
def test_v3_each_phase_rejects_a_missing_explicit_binding(
    checkpoint: AuthorizationCheckpoint,
) -> None:
    targets = _targets()
    index = tuple(AuthorizationCheckpoint).index(checkpoint)
    bindings = _bindings(checkpoint)
    bindings.pop(next(iter(bindings)))

    with pytest.raises(FormalLifecycleError, match="evidence bindings"):
        PhaseCheckpointTarget.create(
            checkpoint=checkpoint,
            lifecycle_id=targets[index].lifecycle_id,
            comparison_block_id=targets[index].comparison_block_id,
            authority_role_id=targets[index].authority_role_id,
            design_hash=targets[index].design_hash,
            source_lock_hash=targets[index].source_lock_hash,
            common_ancestry_hash=targets[index].common_ancestry_hash,
            ledger_pre_head_hash=targets[index].ledger_pre_head_hash,
            evidence_bindings=bindings,
            previous_target=(targets[index - 1] if index else None),
        )


def test_simulated_authorization_is_factory_derived_and_never_production() -> None:
    target = _targets()[0]
    authorization = authorize_simulated_phase_checkpoint(
        target=target,
        verification=_verification(target),
    )

    assert isinstance(authorization, SimulatedPhaseCheckpointAuthorization)
    assert authorization.claim_scope == "simulated_nonclaim"
    assert authorization.production_authorized is False
    assert authorization.test_only is True
    with pytest.raises(FormalLifecycleError, match="factory"):
        SimulatedPhaseCheckpointAuthorization(
            target=target,
            verification=_verification(target),
        )
    with pytest.raises(FormalLifecycleError, match="payload"):
        authorize_simulated_phase_checkpoint(
            target=target,
            verification=replace(
                _verification(target),
                payload_hash=_hash("f"),
            ),
        )


def test_legacy_opaque_requirement_cannot_satisfy_v3_checkpoint() -> None:
    targets = _targets()
    authorizations = tuple(
        authorize_simulated_phase_checkpoint(
            target=target,
            verification=_verification(target),
        )
        for target in targets
    )
    assert (
        validate_v3_phase_checkpoint_chain(
            targets,
            authorizations,
        )
        == authorizations
    )

    legacy = AuthorizationCheckpointRequirement(
        checkpoint=AuthorizationCheckpoint.PRE_JCAL,
        phase="jcal",
        purpose="pre_jcal",
        role_id="legacy-authority",
        authorization_target_hash=targets[0].target_hash,
        ledger_pre_head_hash=targets[0].ledger_pre_head_hash,
    )
    with pytest.raises(FormalLifecycleError, match="typed V3"):
        validate_v3_phase_checkpoint_chain(
            (legacy, *targets[1:]),
            authorizations,
        )


def test_v3_chain_rejects_reorder_cross_chain_and_authorization_substitution() -> None:
    targets = _targets()
    authorizations = tuple(
        authorize_simulated_phase_checkpoint(
            target=target,
            verification=_verification(target),
        )
        for target in targets
    )

    with pytest.raises(FormalLifecycleError, match="ordered"):
        validate_v3_phase_checkpoint_chain(
            (targets[1], targets[0], *targets[2:]),
            authorizations,
        )
    other_first = PhaseCheckpointTarget.create(
        checkpoint=AuthorizationCheckpoint.PRE_JCAL,
        lifecycle_id="pytest.other-lifecycle.v3",
        comparison_block_id=targets[0].comparison_block_id,
        authority_role_id=targets[0].authority_role_id,
        design_hash=targets[0].design_hash,
        source_lock_hash=targets[0].source_lock_hash,
        common_ancestry_hash=_hash("f"),
        ledger_pre_head_hash=targets[0].ledger_pre_head_hash,
        evidence_bindings=_bindings(AuthorizationCheckpoint.PRE_JCAL),
        previous_target=None,
    )
    other_authorization = authorize_simulated_phase_checkpoint(
        target=other_first,
        verification=_verification(other_first),
    )
    with pytest.raises(FormalLifecycleError, match="authorization target"):
        validate_v3_phase_checkpoint_chain(
            targets,
            (other_authorization, *authorizations[1:]),
        )


def test_v3_chain_rejects_authority_role_substitution() -> None:
    targets = _targets()
    authorizations = tuple(
        authorize_simulated_phase_checkpoint(
            target=target,
            verification=_verification(target),
        )
        for target in targets
    )
    substituted = replace(
        targets[2],
        authority_role_id="substituted-approval-authority",
    )
    assert substituted.target_hash != targets[2].target_hash

    with pytest.raises(FormalLifecycleError, match="authority role"):
        validate_v3_phase_checkpoint_chain(
            (*targets[:2], substituted, targets[3]),
            authorizations,
        )
