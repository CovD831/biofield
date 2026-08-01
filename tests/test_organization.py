from __future__ import annotations

import json

import pytest

from biofield.contracts import (
    ActiveAgentState,
    AgentCostContribution,
    CentralPresetInfo,
    CommunicationEdgeRecord,
    DistributionCount,
    ExperienceStructuralChange,
    OrganizationSnapshot,
    RequirementCommitmentLink,
    ResourceAmount,
)
from biofield.organization import build_organization_snapshot


def _parts():
    agents = (
        ActiveAgentState("agent-2", 1, ("state-update-2",)),
        ActiveAgentState("agent-1", 2, ("state-update-1",)),
    )
    links = (
        RequirementCommitmentLink(
            "answer",
            "commitment-2",
            "agent-2",
        ),
        RequirementCommitmentLink(
            "sources",
            "commitment-1",
            "agent-1",
        ),
    )
    edges = (
        CommunicationEdgeRecord(
            edge_id="edge-1",
            permit_id="permit-1",
            sender_agent_id="agent-1",
            receiver_agent_ids=("agent-2",),
            related_requirement_id="sources",
            payload_schema="evidence-summary-v1",
            message_count=1,
            payload_bytes=128,
        ),
    )
    duplicates = (
        DistributionCount("sources", 1),
        DistributionCount("answer", 0),
    )
    refusals = (
        DistributionCount("insufficient_evidence", 1),
    )
    costs = (
        AgentCostContribution(
            agent_id="agent-2",
            actual_cost=(ResourceAmount("tokens", 40),),
            accepted_contribution=0.4,
        ),
        AgentCostContribution(
            agent_id="agent-1",
            actual_cost=(ResourceAmount("tokens", 80),),
            accepted_contribution=0.8,
        ),
    )
    preset = CentralPresetInfo(
        role_bindings=(),
        route_refs=(),
        topology_refs=(),
    )
    changes = (
        ExperienceStructuralChange(
            change_id="change-1",
            experience_update_id="experience-1",
            before_structure_hash="0" * 64,
            after_structure_hash="1" * 64,
            affected_edge_ids=("edge-1",),
            source_event_ids=("feedback-1",),
        ),
    )
    parents = (
        "state-update-1",
        "state-update-2",
        "commitment-1",
        "commitment-2",
        "permit-1",
        "experience-1",
        "feedback-1",
    )
    return agents, links, edges, duplicates, refusals, costs, preset, changes, parents


def _build(**overrides: object) -> OrganizationSnapshot:
    (
        agents,
        links,
        edges,
        duplicates,
        refusals,
        costs,
        preset,
        changes,
        parents,
    ) = _parts()
    values: dict[str, object] = {
        "run_id": "run-1",
        "task_id": "task-1",
        "checkpoint_id": "checkpoint-1",
        "requirement_schema_version": 2,
        "public_state_revision": 7,
        "active_agents": agents,
        "requirement_commitments": links,
        "communication_edges": edges,
        "duplicate_distribution": duplicates,
        "refusal_distribution": refusals,
        "agent_cost_contributions": costs,
        "central_preset_info": preset,
        "experience_structural_changes": changes,
        "parent_event_ids": parents,
        "builder_version": "organization-builder-v1",
        "created_at": "2026-07-30T10:00:00+08:00",
    }
    values.update(overrides)
    return build_organization_snapshot(**values)


def test_snapshot_builder_is_order_invariant_and_hash_stable() -> None:
    first = _build()
    parts = _parts()
    second = _build(
        active_agents=tuple(reversed(parts[0])),
        requirement_commitments=tuple(reversed(parts[1])),
        duplicate_distribution=tuple(reversed(parts[3])),
        agent_cost_contributions=tuple(reversed(parts[5])),
        parent_event_ids=tuple(reversed(parts[8])),
    )

    assert first == second
    assert first.snapshot_id == f"organization-snapshot-{first.snapshot_hash}"
    assert len(first.snapshot_hash) == 64


def test_snapshot_round_trip_is_canonical_and_deeply_immutable() -> None:
    snapshot = _build()
    restored = OrganizationSnapshot.from_dict(json.loads(snapshot.to_json()))

    assert restored == snapshot
    assert restored.to_json() == snapshot.to_json()
    with pytest.raises((AttributeError, TypeError)):
        snapshot.active_agents[0].state_version = 99


def test_snapshot_rejects_missing_parent_events_and_tampered_hash() -> None:
    with pytest.raises(ValueError, match="missing parent event"):
        _build(parent_event_ids=("commitment-1",))

    payload = _build().to_dict()
    payload["snapshot_hash"] = "f" * 64
    with pytest.raises(ValueError, match="snapshot_hash"):
        OrganizationSnapshot.from_dict(payload)


def test_snapshot_rejects_duplicate_ids_and_invalid_versions() -> None:
    parts = _parts()
    with pytest.raises(ValueError, match="duplicate active agent"):
        _build(active_agents=(parts[0][0], parts[0][0]))
    with pytest.raises(ValueError, match="requirement_schema_version"):
        _build(requirement_schema_version=0)
    with pytest.raises(ValueError, match="public_state_revision"):
        _build(public_state_revision=-1)
    with pytest.raises(ValueError, match="inactive agent"):
        _build(
            requirement_commitments=(
                RequirementCommitmentLink(
                    "sources",
                    "commitment-1",
                    "agent-missing",
                ),
            )
        )


def test_snapshot_records_absence_of_central_preset_explicitly() -> None:
    snapshot = _build()

    assert snapshot.central_preset_info.role_bindings == ()
    assert snapshot.central_preset_info.route_refs == ()
    assert snapshot.central_preset_info.topology_refs == ()
    assert snapshot.experience_structural_changes[0].experience_update_id == (
        "experience-1"
    )
