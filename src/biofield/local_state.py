from __future__ import annotations

import hashlib
import json
from datetime import datetime

from .contracts import (
    ExperienceUpdateRecord,
    ExperienceValidationStatus,
    LocalStateSnapshot,
    LocalStateUpdate,
    LocalStateUpdateIssuer,
    LocalStateUpdateProposal,
    UpdateSurfaceManifest,
)


class LocalStateGovernanceError(ValueError):
    """A proposed or replayed private-state mutation violated frozen governance."""


def _parse_timestamp(value: str, field_name: str) -> datetime:
    if not isinstance(value, str) or not value.strip():
        raise LocalStateGovernanceError(
            f"{field_name} must be a non-empty timestamp"
        )
    try:
        parsed = datetime.fromisoformat(value)
    except ValueError as error:
        raise LocalStateGovernanceError(
            f"{field_name} must be an ISO-8601 timestamp"
        ) from error
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise LocalStateGovernanceError(
            f"{field_name} must include a UTC offset"
        )
    return parsed


def _field_is_within_surface(field: str, surface: str) -> bool:
    return field == surface or field.startswith(f"{surface}.")


def _stable_digest(payload: object) -> str:
    encoded = json.dumps(
        payload,
        allow_nan=False,
        separators=(",", ":"),
        sort_keys=True,
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _validate_authorized_sources(
    source_event_window: tuple[str, ...],
    authorized_event_ids: tuple[str, ...],
) -> None:
    authorized = set(authorized_event_ids)
    unauthorized = sorted(set(source_event_window) - authorized)
    if unauthorized:
        raise LocalStateGovernanceError(
            "unauthorized source events: " + ",".join(unauthorized)
        )


def _next_snapshot(
    snapshot: LocalStateSnapshot,
    *,
    update_id: str,
    committed_values: object,
) -> LocalStateSnapshot:
    next_values = dict(snapshot.values)
    next_values.update(committed_values)
    return LocalStateSnapshot(
        schema_version=1,
        agent_id=snapshot.agent_id,
        state_version=snapshot.state_version + 1,
        values=next_values,
        source_update_ids=(*snapshot.source_update_ids, update_id),
    )


def compile_local_state_update(
    *,
    snapshot: LocalStateSnapshot,
    proposal: LocalStateUpdateProposal,
    manifest: UpdateSurfaceManifest,
    authorized_event_ids: tuple[str, ...],
    compiler_policy_version: str,
    run_finalized: bool,
) -> LocalStateUpdate:
    """Compile an Agent proposal into a deterministic Harness-owned update."""

    if run_finalized:
        raise LocalStateGovernanceError(
            "cannot compile a state update after run is finalized"
        )
    if (
        not isinstance(compiler_policy_version, str)
        or not compiler_policy_version.strip()
    ):
        raise LocalStateGovernanceError(
            "compiler_policy_version must be non-empty"
        )
    if proposal.agent_id != snapshot.agent_id:
        raise LocalStateGovernanceError(
            "proposal agent_id does not match local state owner"
        )
    if proposal.previous_state_version != snapshot.state_version:
        raise LocalStateGovernanceError(
            "proposal previous state version is not current"
        )
    if (
        proposal.manifest_id != manifest.manifest_id
        or proposal.manifest_version != manifest.manifest_version
    ):
        raise LocalStateGovernanceError(
            "proposal does not reference the frozen manifest version"
        )
    _validate_authorized_sources(
        proposal.source_event_window,
        tuple(authorized_event_ids),
    )

    rule = manifest.rule_for(proposal.destination_surface)
    if rule is None:
        raise LocalStateGovernanceError(
            f"destination surface {proposal.destination_surface!r} is not mutable"
        )
    outside = [
        field
        for field in proposal.changed_fields
        if not _field_is_within_surface(field, proposal.destination_surface)
    ]
    if outside:
        raise LocalStateGovernanceError(
            "changed fields are outside destination surface: "
            + ",".join(sorted(outside))
        )
    serialized_values = json.dumps(
        proposal.to_dict()["proposed_values"],
        allow_nan=False,
        separators=(",", ":"),
        sort_keys=True,
    ).encode("utf-8")
    if len(serialized_values) > rule.max_serialized_bytes:
        raise LocalStateGovernanceError(
            "proposed update exceeds surface size limit"
        )
    if len(snapshot.source_update_ids) >= rule.max_updates_per_run:
        raise LocalStateGovernanceError(
            "proposed update exceeds surface update-rate limit"
        )

    before_hash = snapshot.state_hash()
    update_digest = _stable_digest(
        {
            "before_hash": before_hash,
            "compiler_policy_version": compiler_policy_version,
            "manifest": manifest.to_dict(),
            "proposal": proposal.to_dict(),
        }
    )
    update_id = f"local-state-update-{update_digest}"
    next_snapshot = _next_snapshot(
        snapshot,
        update_id=update_id,
        committed_values=proposal.proposed_values,
    )
    update = LocalStateUpdate(
        schema_version=1,
        update_id=update_id,
        proposal_id=proposal.proposal_id,
        agent_id=proposal.agent_id,
        manifest_id=manifest.manifest_id,
        manifest_version=manifest.manifest_version,
        compiler_policy_version=compiler_policy_version,
        previous_state_version=snapshot.state_version,
        next_state_version=next_snapshot.state_version,
        destination_surface=proposal.destination_surface,
        update_kind=proposal.update_kind,
        source_event_window=proposal.source_event_window,
        changed_fields=proposal.changed_fields,
        committed_values=proposal.proposed_values,
        before_hash=before_hash,
        after_hash=next_snapshot.state_hash(),
        reversible=proposal.reversible,
        rollback_ref=proposal.rollback_ref,
        issuer=LocalStateUpdateIssuer.HARNESS_COMPILER,
    )
    apply_local_state_update(snapshot, update)
    return update


def apply_local_state_update(
    snapshot: LocalStateSnapshot,
    update: LocalStateUpdate,
) -> LocalStateSnapshot:
    if update.agent_id != snapshot.agent_id:
        raise LocalStateGovernanceError(
            "update agent_id does not match local state owner"
        )
    if update.previous_state_version != snapshot.state_version:
        raise LocalStateGovernanceError(
            "update version is not contiguous with local state"
        )
    if update.update_id in snapshot.source_update_ids:
        raise LocalStateGovernanceError("update has already been applied")
    if update.before_hash != snapshot.state_hash():
        raise LocalStateGovernanceError(
            "update before_hash does not match local state"
        )
    next_snapshot = _next_snapshot(
        snapshot,
        update_id=update.update_id,
        committed_values=update.committed_values,
    )
    if next_snapshot.state_version != update.next_state_version:
        raise LocalStateGovernanceError(
            "update next state version is inconsistent"
        )
    if next_snapshot.state_hash() != update.after_hash:
        raise LocalStateGovernanceError(
            "update after_hash does not match replayed state"
        )
    return next_snapshot


def replay_local_state_updates(
    initial_snapshot: LocalStateSnapshot,
    updates: tuple[LocalStateUpdate, ...],
) -> LocalStateSnapshot:
    current = initial_snapshot
    for update in updates:
        current = apply_local_state_update(current, update)
    return current


def rollback_local_state_update(
    current_snapshot: LocalStateSnapshot,
    update: LocalStateUpdate,
    checkpoint: LocalStateSnapshot,
) -> LocalStateSnapshot:
    if not update.reversible:
        raise LocalStateGovernanceError("state update is not reversible")
    if current_snapshot.state_hash() != update.after_hash:
        raise LocalStateGovernanceError(
            "current state does not match update after_hash"
        )
    if checkpoint.state_hash() != update.before_hash:
        raise LocalStateGovernanceError(
            "rollback checkpoint does not match update before_hash"
        )
    if checkpoint.agent_id != current_snapshot.agent_id:
        raise LocalStateGovernanceError(
            "rollback checkpoint belongs to a different agent"
        )
    if checkpoint.state_version != update.previous_state_version:
        raise LocalStateGovernanceError(
            "rollback checkpoint version does not match update"
        )
    return checkpoint


def consume_experience(
    record: ExperienceUpdateRecord,
    manifest: UpdateSurfaceManifest,
    *,
    authorized_event_ids: tuple[str, ...],
    at: str,
) -> str:
    """Return the promoted candidate reference only when governance permits use."""

    if (
        record.manifest_id != manifest.manifest_id
        or record.manifest_version != manifest.manifest_version
    ):
        raise LocalStateGovernanceError(
            "experience does not reference the frozen manifest version"
        )
    if manifest.rule_for(record.destination_surface) is None:
        raise LocalStateGovernanceError(
            "experience destination surface is not mutable"
        )
    _validate_authorized_sources(
        record.source_event_window,
        tuple(authorized_event_ids),
    )
    if record.validation_status is not ExperienceValidationStatus.PROMOTED:
        raise LocalStateGovernanceError(
            "experience is not promoted and cannot be consumed"
        )
    if _parse_timestamp(at, "at") >= _parse_timestamp(
        record.expires_at,
        "expires_at",
    ):
        raise LocalStateGovernanceError("promoted experience has expired")
    return record.candidate_hash
