from __future__ import annotations

import json
import os
import tempfile
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation
from hashlib import sha256
from pathlib import Path
from types import MappingProxyType
from typing import Any, Mapping

from .admission import AdmissionPolicy
from .contracts import (
    AgentCommitment,
    CommitmentLifecycleSnapshot,
    CommitmentStatus,
    CommitmentTransition,
    OrganizationSnapshot,
    ResourceAmount,
)
from .failure_runtime import (
    FailureReorganizationReplay,
    ScriptedFailureExecution,
    _materialize,
    _organization,
    _terminal_hash,
    replay_failure_reorganization,
)
from .ledger import ResourceLedger
from .local_runtime import (
    HarnessCycleError,
    HarnessRuntimeEvent,
    _canonical_hash,
    _ledger_totals,
)
from .multi_admission import (
    BidCandidate,
    MultiAdmissionPolicy,
    MultiAdmissionResult,
)
from .refusal_runtime import _one_selected, _select

CHECKPOINT_SCHEMA_VERSION = 1
RUNTIME_VERSION = "failure-reorganization-v1"
CHECKPOINT_AUTHORITY = "harness_runtime"
_SAFE_PHASE = "failed_settled"
_TERMINAL_PHASE = "terminal"
_FORBIDDEN_PRIVATE_KEYS = frozenset(
    {"values", "proposed_values", "committed_values", "changed_fields"}
)


def _require_sha256(value: object, field_name: str) -> str:
    if (
        not isinstance(value, str)
        or len(value) != 64
        or any(character not in "0123456789abcdef" for character in value)
    ):
        raise HarnessCycleError(
            f"{field_name} must be a lowercase SHA-256 digest"
        )
    return value


def _canonical_json(value: object) -> str:
    return json.dumps(
        value,
        allow_nan=False,
        separators=(",", ":"),
        sort_keys=True,
    )


def _decimal_text(value: Decimal) -> str:
    normalized = value.normalize()
    if normalized == 0:
        return "0"
    return format(normalized, "f")


def _contains_private_state(value: object) -> bool:
    if isinstance(value, Mapping):
        return any(
            key in _FORBIDDEN_PRIVATE_KEYS or _contains_private_state(item)
            for key, item in value.items()
        )
    if isinstance(value, (tuple, list)):
        return any(_contains_private_state(item) for item in value)
    return False


def _event_fingerprint(event: HarnessRuntimeEvent) -> str:
    return _canonical_hash(event.to_dict())


def _prefix_hash(
    event_ids: tuple[str, ...],
    event_fingerprints: tuple[str, ...],
) -> str:
    return _canonical_hash(
        {
            "event_ids": event_ids,
            "event_fingerprints": event_fingerprints,
        }
    )


def _configuration_hash(
    *,
    candidates: tuple[BidCandidate, ...],
    admission_policy: AdmissionPolicy,
    multi_policy: MultiAdmissionPolicy,
    run_budget: tuple[ResourceAmount, ...],
) -> str:
    return _canonical_hash(
        {
            "admission_policy": admission_policy.to_dict(),
            "candidates": [
                item.to_dict()
                for item in sorted(
                    candidates,
                    key=lambda candidate: candidate.bid.bid_id,
                )
            ],
            "multi_policy": multi_policy.to_dict(),
            "run_budget": [
                item.to_dict()
                for item in sorted(
                    run_budget,
                    key=lambda amount: amount.resource_type,
                )
            ],
        }
    )


@dataclass(frozen=True, kw_only=True)
class FailureCheckpointLocalState:
    agent_id: str
    state_version: int
    observation_id: str
    public_projection_sha256: str

    def __post_init__(self) -> None:
        if not isinstance(self.agent_id, str) or not self.agent_id:
            raise HarnessCycleError("checkpoint local-state agent_id is invalid")
        if (
            isinstance(self.state_version, bool)
            or not isinstance(self.state_version, int)
            or self.state_version < 0
        ):
            raise HarnessCycleError("checkpoint local-state version is invalid")
        if not isinstance(self.observation_id, str) or not self.observation_id:
            raise HarnessCycleError(
                "checkpoint local-state observation_id is invalid"
            )
        _require_sha256(
            self.public_projection_sha256,
            "local-state public_projection_sha256",
        )
        expected = _canonical_hash(
            {
                "agent_id": self.agent_id,
                "observation_id": self.observation_id,
                "state_version": self.state_version,
            }
        )
        if expected != self.public_projection_sha256:
            raise HarnessCycleError(
                "local-state public hash does not match projection"
            )

    def to_dict(self) -> dict[str, object]:
        return {
            "agent_id": self.agent_id,
            "observation_id": self.observation_id,
            "public_projection_sha256": self.public_projection_sha256,
            "state_version": self.state_version,
        }

    @classmethod
    def from_dict(
        cls,
        value: Mapping[str, object],
    ) -> FailureCheckpointLocalState:
        try:
            if set(value) != {
                "agent_id",
                "observation_id",
                "public_projection_sha256",
                "state_version",
            }:
                raise KeyError
            return cls(
                agent_id=value["agent_id"],
                state_version=value["state_version"],
                observation_id=value["observation_id"],
                public_projection_sha256=value[
                    "public_projection_sha256"
                ],
            )
        except HarnessCycleError:
            raise
        except (KeyError, TypeError, ValueError) as error:
            raise HarnessCycleError(
                "invalid checkpoint local-state projection"
            ) from error


def _local_states(
    candidates: tuple[BidCandidate, ...],
) -> tuple[FailureCheckpointLocalState, ...]:
    result: list[FailureCheckpointLocalState] = []
    for item in sorted(candidates, key=lambda candidate: candidate.bid.agent_id):
        content = {
            "agent_id": item.bid.agent_id,
            "observation_id": item.observation.observation_id,
            "state_version": item.intent.local_state_version,
        }
        result.append(
            FailureCheckpointLocalState(
                **content,
                public_projection_sha256=_canonical_hash(content),
            )
        )
    return tuple(result)


def _normalize_ledger_totals(
    value: Mapping[str, Mapping[str, object]],
) -> Mapping[str, Mapping[str, str]]:
    expected_fields = {
        "expected",
        "shared_pool",
        "escrow",
        "reserved",
        "spent",
    }
    normalized: dict[str, Mapping[str, str]] = {}
    if not isinstance(value, Mapping) or not value:
        raise HarnessCycleError("checkpoint Ledger projection is empty")
    for resource_type, raw_totals in sorted(value.items()):
        if not isinstance(resource_type, str) or not resource_type:
            raise HarnessCycleError("checkpoint Ledger resource type is invalid")
        if not isinstance(raw_totals, Mapping) or set(raw_totals) != expected_fields:
            raise HarnessCycleError("checkpoint Ledger fields are incomplete")
        decimals: dict[str, Decimal] = {}
        for field_name in sorted(expected_fields):
            raw_value = raw_totals[field_name]
            if not isinstance(raw_value, str):
                raise HarnessCycleError(
                    "checkpoint Ledger amounts must be decimal strings"
                )
            try:
                amount = Decimal(raw_value)
            except InvalidOperation as error:
                raise HarnessCycleError(
                    "checkpoint Ledger amount is invalid"
                ) from error
            if not amount.is_finite() or amount < 0:
                raise HarnessCycleError(
                    "checkpoint Ledger amount is invalid"
                )
            decimals[field_name] = amount
        accounted = sum(
            (
                decimals["shared_pool"],
                decimals["escrow"],
                decimals["reserved"],
                decimals["spent"],
            ),
            Decimal(0),
        )
        if accounted != decimals["expected"]:
            raise HarnessCycleError(
                "checkpoint Ledger projection violates conservation"
            )
        normalized[resource_type] = MappingProxyType(
            {
                field_name: _decimal_text(decimals[field_name])
                for field_name in (
                    "expected",
                    "shared_pool",
                    "escrow",
                    "reserved",
                    "spent",
                )
            }
        )
    return MappingProxyType(normalized)


@dataclass(frozen=True, kw_only=True)
class FailureReorganizationCheckpoint:
    checkpoint_schema_version: int
    event_schema_version: int
    runtime_version: str
    authority: str
    run_id: str
    phase: str
    terminal: bool
    next_public_state_revision: int
    last_event_id: str
    prefix_event_ids: tuple[str, ...]
    prefix_event_fingerprints: tuple[str, ...]
    prefix_sha256: str
    configuration_sha256: str
    ledger_totals: Mapping[str, Mapping[str, str]]
    commitments: tuple[AgentCommitment, ...]
    lifecycles: tuple[CommitmentLifecycleSnapshot, ...]
    executions: tuple[ScriptedFailureExecution, ...]
    initial_selection: MultiAdmissionResult
    local_states: tuple[FailureCheckpointLocalState, ...]
    organization_parent_event_ids: tuple[str, ...]
    organization_snapshot_id: str | None
    organization_snapshot_sha256: str | None
    terminal_projection_sha256: str | None
    checkpoint_sha256: str

    def __post_init__(self) -> None:
        for field_name in (
            "prefix_event_ids",
            "prefix_event_fingerprints",
            "commitments",
            "lifecycles",
            "executions",
            "local_states",
            "organization_parent_event_ids",
        ):
            object.__setattr__(self, field_name, tuple(getattr(self, field_name)))
        object.__setattr__(
            self,
            "ledger_totals",
            _normalize_ledger_totals(self.ledger_totals),
        )
        if self.checkpoint_schema_version != CHECKPOINT_SCHEMA_VERSION:
            raise HarnessCycleError("unsupported checkpoint schema version")
        if self.event_schema_version != 1:
            raise HarnessCycleError("unsupported checkpoint event version")
        if self.runtime_version != RUNTIME_VERSION:
            raise HarnessCycleError("checkpoint runtime version mismatch")
        if self.authority != CHECKPOINT_AUTHORITY:
            raise HarnessCycleError("checkpoint authority is invalid")
        if not isinstance(self.run_id, str) or not self.run_id:
            raise HarnessCycleError("checkpoint run_id is invalid")
        if self.phase not in {_SAFE_PHASE, _TERMINAL_PHASE}:
            raise HarnessCycleError("checkpoint phase is invalid")
        if self.terminal != (self.phase == _TERMINAL_PHASE):
            raise HarnessCycleError("checkpoint terminal phase is inconsistent")
        if (
            isinstance(self.next_public_state_revision, bool)
            or not isinstance(self.next_public_state_revision, int)
            or self.next_public_state_revision <= 0
        ):
            raise HarnessCycleError("checkpoint next revision is invalid")
        if (
            len(self.prefix_event_ids)
            != self.next_public_state_revision
            or len(self.prefix_event_fingerprints)
            != self.next_public_state_revision
            or len(set(self.prefix_event_ids)) != len(self.prefix_event_ids)
        ):
            raise HarnessCycleError("checkpoint prefix binding is incomplete")
        if self.last_event_id != self.prefix_event_ids[-1]:
            raise HarnessCycleError("checkpoint prefix binding has wrong tip")
        for fingerprint in self.prefix_event_fingerprints:
            _require_sha256(fingerprint, "prefix event fingerprint")
        expected_prefix = _prefix_hash(
            self.prefix_event_ids,
            self.prefix_event_fingerprints,
        )
        if self.prefix_sha256 != expected_prefix:
            raise HarnessCycleError("checkpoint prefix binding hash mismatch")
        _require_sha256(self.configuration_sha256, "configuration_sha256")
        if not self.commitments or len(self.commitments) != len(self.lifecycles):
            raise HarnessCycleError(
                "checkpoint commitment projection is incomplete"
            )
        for commitment, lifecycle in zip(
            self.commitments,
            self.lifecycles,
            strict=True,
        ):
            if commitment.commitment_id != lifecycle.commitment_id:
                raise HarnessCycleError(
                    "checkpoint commitment lifecycle linkage is invalid"
                )
            if lifecycle.status is CommitmentStatus.ACTIVE:
                raise HarnessCycleError(
                    "checkpoint cannot capture an unsettled active commitment"
                )
        if not self.executions:
            raise HarnessCycleError("checkpoint execution projection is empty")
        if tuple(item.agent_id for item in self.local_states) != tuple(
            sorted(item.agent_id for item in self.local_states)
        ):
            raise HarnessCycleError(
                "checkpoint local-state projection is not canonical"
            )
        if len({item.agent_id for item in self.local_states}) != len(
            self.local_states
        ):
            raise HarnessCycleError(
                "checkpoint local-state projection contains duplicates"
            )
        required_links = {
            item.commitment_id for item in self.commitments
        } | {
            transition_id
            for item in self.lifecycles
            for transition_id in item.transition_ids
        }
        if not required_links <= set(self.organization_parent_event_ids):
            raise HarnessCycleError(
                "checkpoint organization linkage is incomplete"
            )
        if self.terminal:
            if (
                self.organization_snapshot_id is None
                or self.organization_snapshot_sha256 is None
                or self.terminal_projection_sha256 is None
            ):
                raise HarnessCycleError(
                    "terminal checkpoint projection is incomplete"
                )
            _require_sha256(
                self.organization_snapshot_sha256,
                "organization_snapshot_sha256",
            )
            _require_sha256(
                self.terminal_projection_sha256,
                "terminal_projection_sha256",
            )
        elif any(
            value is not None
            for value in (
                self.organization_snapshot_id,
                self.organization_snapshot_sha256,
                self.terminal_projection_sha256,
            )
        ):
            raise HarnessCycleError(
                "non-terminal checkpoint cannot claim a terminal projection"
            )
        if _contains_private_state(self._content_dict()):
            raise HarnessCycleError("checkpoint contains private local-state values")
        _require_sha256(self.checkpoint_sha256, "checkpoint_sha256")
        if self.checkpoint_sha256 != _canonical_hash(self._content_dict()):
            raise HarnessCycleError("checkpoint self hash mismatch")

    def _content_dict(self) -> dict[str, object]:
        commitments = [item.to_dict() for item in self.commitments]
        executions = [
            item.to_public_dict(commitment["commitment_id"])
            for item, commitment in zip(
                self.executions,
                commitments,
                strict=True,
            )
        ]
        return {
            "authority": self.authority,
            "checkpoint_schema_version": self.checkpoint_schema_version,
            "commitments": commitments,
            "configuration_sha256": self.configuration_sha256,
            "event_schema_version": self.event_schema_version,
            "executions": executions,
            "initial_selection": self.initial_selection.to_dict(),
            "last_event_id": self.last_event_id,
            "ledger_totals": {
                key: dict(value)
                for key, value in sorted(self.ledger_totals.items())
            },
            "lifecycles": [item.to_dict() for item in self.lifecycles],
            "local_states": [item.to_dict() for item in self.local_states],
            "next_public_state_revision": self.next_public_state_revision,
            "organization_parent_event_ids": list(
                self.organization_parent_event_ids
            ),
            "organization_snapshot_id": self.organization_snapshot_id,
            "organization_snapshot_sha256": (
                self.organization_snapshot_sha256
            ),
            "phase": self.phase,
            "prefix_event_fingerprints": list(
                self.prefix_event_fingerprints
            ),
            "prefix_event_ids": list(self.prefix_event_ids),
            "prefix_sha256": self.prefix_sha256,
            "run_id": self.run_id,
            "runtime_version": self.runtime_version,
            "terminal": self.terminal,
            "terminal_projection_sha256": self.terminal_projection_sha256,
        }

    def to_dict(self) -> dict[str, object]:
        return {
            **self._content_dict(),
            "checkpoint_sha256": self.checkpoint_sha256,
        }

    @classmethod
    def from_dict(
        cls,
        value: Mapping[str, object],
    ) -> FailureReorganizationCheckpoint:
        expected_fields = {
            "authority",
            "checkpoint_schema_version",
            "checkpoint_sha256",
            "commitments",
            "configuration_sha256",
            "event_schema_version",
            "executions",
            "initial_selection",
            "last_event_id",
            "ledger_totals",
            "lifecycles",
            "local_states",
            "next_public_state_revision",
            "organization_parent_event_ids",
            "organization_snapshot_id",
            "organization_snapshot_sha256",
            "phase",
            "prefix_event_fingerprints",
            "prefix_event_ids",
            "prefix_sha256",
            "run_id",
            "runtime_version",
            "terminal",
            "terminal_projection_sha256",
        }
        try:
            if not isinstance(value, Mapping) or set(value) != expected_fields:
                raise KeyError
            commitments = tuple(
                AgentCommitment.from_dict(item) for item in value["commitments"]
            )
            raw_executions = tuple(value["executions"])
            if len(raw_executions) != len(commitments):
                raise ValueError
            executions = tuple(
                ScriptedFailureExecution.from_public_dict(item)
                for item in raw_executions
            )
            return cls(
                checkpoint_schema_version=value[
                    "checkpoint_schema_version"
                ],
                event_schema_version=value["event_schema_version"],
                runtime_version=value["runtime_version"],
                authority=value["authority"],
                run_id=value["run_id"],
                phase=value["phase"],
                terminal=value["terminal"],
                next_public_state_revision=value[
                    "next_public_state_revision"
                ],
                last_event_id=value["last_event_id"],
                prefix_event_ids=tuple(value["prefix_event_ids"]),
                prefix_event_fingerprints=tuple(
                    value["prefix_event_fingerprints"]
                ),
                prefix_sha256=value["prefix_sha256"],
                configuration_sha256=value["configuration_sha256"],
                ledger_totals=value["ledger_totals"],
                commitments=commitments,
                lifecycles=tuple(
                    CommitmentLifecycleSnapshot.from_dict(item)
                    for item in value["lifecycles"]
                ),
                executions=executions,
                initial_selection=MultiAdmissionResult.from_dict(
                    value["initial_selection"]
                ),
                local_states=tuple(
                    FailureCheckpointLocalState.from_dict(item)
                    for item in value["local_states"]
                ),
                organization_parent_event_ids=tuple(
                    value["organization_parent_event_ids"]
                ),
                organization_snapshot_id=value["organization_snapshot_id"],
                organization_snapshot_sha256=value[
                    "organization_snapshot_sha256"
                ],
                terminal_projection_sha256=value[
                    "terminal_projection_sha256"
                ],
                checkpoint_sha256=value["checkpoint_sha256"],
            )
        except HarnessCycleError:
            raise
        except (KeyError, TypeError, ValueError) as error:
            raise HarnessCycleError("invalid failure checkpoint payload") from error


def _checkpoint(
    *,
    run_id: str,
    phase: str,
    events: tuple[HarnessRuntimeEvent, ...],
    configuration_sha256: str,
    ledger_totals: Mapping[str, Mapping[str, str]],
    commitments: tuple[AgentCommitment, ...],
    lifecycles: tuple[CommitmentLifecycleSnapshot, ...],
    executions: tuple[ScriptedFailureExecution, ...],
    initial_selection: MultiAdmissionResult,
    local_states: tuple[FailureCheckpointLocalState, ...],
    organization_parent_event_ids: tuple[str, ...],
    organization: OrganizationSnapshot | None,
    terminal_projection_sha256: str | None,
) -> FailureReorganizationCheckpoint:
    ids = tuple(event.event_id for event in events)
    fingerprints = tuple(_event_fingerprint(event) for event in events)
    content: dict[str, object] = {
        "authority": CHECKPOINT_AUTHORITY,
        "checkpoint_schema_version": CHECKPOINT_SCHEMA_VERSION,
        "commitments": [item.to_dict() for item in commitments],
        "configuration_sha256": configuration_sha256,
        "event_schema_version": 1,
        "executions": [
            item.to_public_dict(commitment.commitment_id)
            for item, commitment in zip(executions, commitments, strict=True)
        ],
        "initial_selection": initial_selection.to_dict(),
        "last_event_id": ids[-1],
        "ledger_totals": {
            key: dict(value) for key, value in sorted(ledger_totals.items())
        },
        "lifecycles": [item.to_dict() for item in lifecycles],
        "local_states": [item.to_dict() for item in local_states],
        "next_public_state_revision": len(events),
        "organization_parent_event_ids": list(
            organization_parent_event_ids
        ),
        "organization_snapshot_id": (
            None if organization is None else organization.snapshot_id
        ),
        "organization_snapshot_sha256": (
            None if organization is None else organization.snapshot_hash
        ),
        "phase": phase,
        "prefix_event_fingerprints": list(fingerprints),
        "prefix_event_ids": list(ids),
        "prefix_sha256": _prefix_hash(ids, fingerprints),
        "run_id": run_id,
        "runtime_version": RUNTIME_VERSION,
        "terminal": phase == _TERMINAL_PHASE,
        "terminal_projection_sha256": terminal_projection_sha256,
    }
    return FailureReorganizationCheckpoint.from_dict(
        {
            **content,
            "checkpoint_sha256": _canonical_hash(content),
        }
    )


def _validate_event_stream(
    events: tuple[HarnessRuntimeEvent, ...],
    *,
    revision_offset: int = 0,
    known_event_ids: tuple[str, ...] = (),
) -> None:
    known = set(known_event_ids)
    for index, event in enumerate(events, start=revision_offset):
        if event.event_id in known:
            raise HarnessCycleError(
                "duplicate or conflicting checkpoint runtime event"
            )
        if event.public_state_revision != index:
            raise HarnessCycleError(
                "checkpoint runtime event revisions are not contiguous"
            )
        if _canonical_hash(event.payload) != event.payload_sha256:
            raise HarnessCycleError(
                "checkpoint runtime event payload hash mismatch"
            )
        if index and not set(event.causal_parent_ids) <= known:
            raise HarnessCycleError(
                "checkpoint runtime event has unknown parent"
            )
        if _contains_private_state(event.payload):
            raise HarnessCycleError(
                "checkpoint runtime event leaks private local-state values"
            )
        known.add(event.event_id)


def _failed_prefix_projection(
    *,
    candidates: tuple[BidCandidate, ...],
    admission_policy: AdmissionPolicy,
    multi_policy: MultiAdmissionPolicy,
    run_budget: tuple[ResourceAmount, ...],
    events: tuple[HarnessRuntimeEvent, ...],
) -> tuple[
    str,
    MultiAdmissionResult,
    AgentCommitment,
    CommitmentLifecycleSnapshot,
    ScriptedFailureExecution,
    Mapping[str, Mapping[str, str]],
]:
    if (
        not events
        or events[0].event_type != "failure_initial_admission"
        or events[-1].event_type != "failure_settlement"
    ):
        raise HarnessCycleError("unsafe failure checkpoint boundary")
    try:
        run_id = events[0].payload["run_id"]
        initial_at = events[0].payload["at"]
        execution_event = next(
            event
            for event in events
            if event.event_type == "failure_execution"
        )
        execution = ScriptedFailureExecution.from_public_dict(
            execution_event.payload["execution"]
        )
    except (KeyError, StopIteration, TypeError, ValueError) as error:
        raise HarnessCycleError(
            "failure checkpoint prefix projection is incomplete"
        ) from error
    ordered = tuple(sorted(candidates, key=lambda item: item.bid.bid_id))
    initial = _select(
        candidates=ordered,
        run_budget=run_budget,
        admission_policy=admission_policy,
        multi_policy=multi_policy,
        at=initial_at,
    )
    first = _one_selected(initial, ordered)
    ledger = ResourceLedger(
        {
            item.resource_type: Decimal(str(item.amount))
            for item in run_budget
        }
    )
    writer = _SeededEventWriter()
    writer.append(
        initial.result_id,
        "failure_initial_admission",
        (),
        {
            "at": initial_at,
            "candidate_bid_ids": tuple(item.bid.bid_id for item in ordered),
            "result": initial.to_dict(),
            "run_id": run_id,
        },
    )
    commitment, lifecycle, _ = _materialize(
        writer=writer,
        ledger=ledger,
        candidate=first,
        selection_parent_id=initial.result_id,
        selection_event_type="failure",
        admission_policy=admission_policy,
        run_budget=run_budget,
        admission_at=initial_at,
        execution=execution,
        execution_event_type="failure_execution",
        terminal_status=CommitmentStatus.CANCELLED,
    )
    if tuple(writer.events) != events:
        raise HarnessCycleError(
            "failure checkpoint prefix semantics do not replay"
        )
    return (
        run_id,
        initial,
        commitment,
        lifecycle,
        execution,
        _ledger_totals(
            ledger,
            tuple(item.resource_type for item in run_budget),
        ),
    )


def _terminal_components(
    events: tuple[HarnessRuntimeEvent, ...],
) -> tuple[
    str,
    MultiAdmissionResult,
    tuple[AgentCommitment, ...],
    tuple[CommitmentLifecycleSnapshot, ...],
    tuple[ScriptedFailureExecution, ...],
]:
    try:
        run_id = events[0].payload["run_id"]
        initial = MultiAdmissionResult.from_dict(events[0].payload["result"])
        commitments = tuple(
            AgentCommitment.from_dict(event.payload["commitment"])
            for event in events
            if event.event_type
            in {"failure_commitment", "takeover_commitment"}
        )
        transitions = tuple(
            CommitmentTransition.from_dict(event.payload["transition"])
            for event in events
            if event.event_type
            in {
                "failure_commitment_transition",
                "takeover_commitment_transition",
            }
        )
        lifecycle_by_id = {
            item.commitment_id: CommitmentLifecycleSnapshot(
                schema_version=1,
                commitment_id=item.commitment_id,
                status=item.next_status,
                revision=item.next_revision,
                transition_ids=(item.transition_id,),
            )
            for item in transitions
        }
        lifecycles = tuple(
            lifecycle_by_id[item.commitment_id] for item in commitments
        )
        executions = tuple(
            ScriptedFailureExecution.from_public_dict(
                event.payload["execution"]
            )
            for event in events
            if event.event_type in {"failure_execution", "takeover_execution"}
        )
    except (KeyError, TypeError, ValueError) as error:
        raise HarnessCycleError(
            "terminal checkpoint projection is incomplete"
        ) from error
    return run_id, initial, commitments, lifecycles, executions


def create_failure_reorganization_checkpoint(
    *,
    candidates: tuple[BidCandidate, ...],
    admission_policy: AdmissionPolicy,
    multi_policy: MultiAdmissionPolicy,
    run_budget: tuple[ResourceAmount, ...],
    events: tuple[HarnessRuntimeEvent, ...],
) -> FailureReorganizationCheckpoint:
    materialized = tuple(events)
    if not materialized:
        raise HarnessCycleError("unsafe empty checkpoint boundary")
    _validate_event_stream(materialized)
    configuration_sha256 = _configuration_hash(
        candidates=candidates,
        admission_policy=admission_policy,
        multi_policy=multi_policy,
        run_budget=run_budget,
    )
    local_states = _local_states(candidates)
    if materialized[-1].event_type == "failure_terminal":
        replayed = replay_failure_reorganization(
            candidates=candidates,
            admission_policy=admission_policy,
            multi_policy=multi_policy,
            run_budget=run_budget,
            events=materialized,
        )
        (
            run_id,
            initial,
            commitments,
            lifecycles,
            executions,
        ) = _terminal_components(materialized)
        organization = replayed.organization_snapshot
        return _checkpoint(
            run_id=run_id,
            phase=_TERMINAL_PHASE,
            events=materialized,
            configuration_sha256=configuration_sha256,
            ledger_totals=replayed.ledger_totals,
            commitments=commitments,
            lifecycles=lifecycles,
            executions=executions,
            initial_selection=initial,
            local_states=local_states,
            organization_parent_event_ids=organization.parent_event_ids,
            organization=organization,
            terminal_projection_sha256=(
                replayed.terminal_projection_sha256
            ),
        )
    (
        run_id,
        initial,
        commitment,
        lifecycle,
        execution,
        totals,
    ) = _failed_prefix_projection(
        candidates=candidates,
        admission_policy=admission_policy,
        multi_policy=multi_policy,
        run_budget=run_budget,
        events=materialized,
    )
    return _checkpoint(
        run_id=run_id,
        phase=_SAFE_PHASE,
        events=materialized,
        configuration_sha256=configuration_sha256,
        ledger_totals=totals,
        commitments=(commitment,),
        lifecycles=(lifecycle,),
        executions=(execution,),
        initial_selection=initial,
        local_states=local_states,
        organization_parent_event_ids=(
            commitment.commitment_id,
            *lifecycle.transition_ids,
            materialized[-1].event_id,
        ),
        organization=None,
        terminal_projection_sha256=None,
    )


class _SeededEventWriter:
    def __init__(
        self,
        *,
        revision_offset: int = 0,
        known_event_ids: tuple[str, ...] = (),
    ) -> None:
        self.events: list[HarnessRuntimeEvent] = []
        self._revision_offset = revision_offset
        self._ids = set(known_event_ids)

    def append(
        self,
        event_id: str,
        event_type: str,
        parents: tuple[str, ...],
        payload: Mapping[str, Any],
    ) -> HarnessRuntimeEvent:
        if event_id in self._ids:
            raise HarnessCycleError(
                f"duplicate runtime event ID: {event_id}"
            )
        if self._revision_offset + len(self.events) and not parents:
            raise HarnessCycleError("non-initial runtime event requires parents")
        missing = set(parents) - self._ids
        if missing:
            raise HarnessCycleError(
                "runtime event references missing parents: "
                + ",".join(sorted(missing))
            )
        event = HarnessRuntimeEvent(
            event_id=event_id,
            event_type=event_type,
            event_schema_version=1,
            public_state_revision=self._revision_offset + len(self.events),
            causal_parent_ids=parents,
            payload=payload,
            payload_sha256=_canonical_hash(payload),
        )
        self.events.append(event)
        self._ids.add(event_id)
        return event


def _combined_totals(
    checkpoint_totals: Mapping[str, Mapping[str, str]],
    resumed_ledger: ResourceLedger,
    resource_types: tuple[str, ...],
) -> Mapping[str, Mapping[str, str]]:
    resumed = _ledger_totals(resumed_ledger, resource_types)
    result: dict[str, Mapping[str, str]] = {}
    for resource_type in sorted(set(resource_types)):
        before = checkpoint_totals[resource_type]
        after = resumed[resource_type]
        result[resource_type] = MappingProxyType(
            {
                "expected": before["expected"],
                "shared_pool": after["shared_pool"],
                "escrow": _decimal_text(
                    Decimal(before["escrow"]) + Decimal(after["escrow"])
                ),
                "reserved": _decimal_text(
                    Decimal(before["reserved"]) + Decimal(after["reserved"])
                ),
                "spent": _decimal_text(
                    Decimal(before["spent"]) + Decimal(after["spent"])
                ),
            }
        )
    return _normalize_ledger_totals(result)


def resume_failure_reorganization(
    *,
    checkpoint: FailureReorganizationCheckpoint,
    candidates: tuple[BidCandidate, ...],
    admission_policy: AdmissionPolicy,
    multi_policy: MultiAdmissionPolicy,
    run_budget: tuple[ResourceAmount, ...],
    suffix_events: tuple[HarnessRuntimeEvent, ...],
) -> FailureReorganizationReplay:
    if not isinstance(checkpoint, FailureReorganizationCheckpoint):
        raise HarnessCycleError(
            "resume requires a failure reorganization checkpoint"
        )
    trusted = FailureReorganizationCheckpoint.from_dict(checkpoint.to_dict())
    if trusted.terminal:
        raise HarnessCycleError("cannot resume a terminal checkpoint")
    if trusted.configuration_sha256 != _configuration_hash(
        candidates=candidates,
        admission_policy=admission_policy,
        multi_policy=multi_policy,
        run_budget=run_budget,
    ):
        raise HarnessCycleError("checkpoint configuration binding mismatch")
    suffix = tuple(suffix_events)
    if not suffix:
        raise HarnessCycleError("failure resume suffix is empty")
    _validate_event_stream(
        suffix,
        revision_offset=trusted.next_public_state_revision,
        known_event_ids=trusted.prefix_event_ids,
    )
    if (
        suffix[0].event_type != "failure_readmission"
        or suffix[0].causal_parent_ids != (trusted.last_event_id,)
    ):
        raise HarnessCycleError(
            "failure resume suffix parent skips checkpoint settlement"
        )

    ordered = tuple(sorted(candidates, key=lambda item: item.bid.bid_id))
    failed_bid_ids = trusted.initial_selection.admitted_bid_ids
    remaining = tuple(
        item for item in ordered if item.bid.bid_id not in failed_bid_ids
    )
    available = tuple(
        ResourceAmount(
            item.resource_type,
            float(
                Decimal(
                    trusted.ledger_totals[item.resource_type]["shared_pool"]
                )
            ),
        )
        for item in run_budget
    )
    try:
        readmission_at = suffix[0].payload["at"]
        takeover_event = next(
            event
            for event in suffix
            if event.event_type == "takeover_execution"
        )
        takeover_execution = ScriptedFailureExecution.from_public_dict(
            takeover_event.payload["execution"]
        )
    except (KeyError, StopIteration, TypeError, ValueError) as error:
        raise HarnessCycleError(
            "failure resume suffix semantics are incomplete"
        ) from error
    readmission = _select(
        candidates=remaining,
        run_budget=available,
        admission_policy=admission_policy,
        multi_policy=multi_policy,
        at=readmission_at,
    )
    takeover = _one_selected(readmission, remaining)
    ledger = ResourceLedger(
        {
            item.resource_type: Decimal(str(item.amount))
            for item in available
        }
    )
    writer = _SeededEventWriter(
        revision_offset=trusted.next_public_state_revision,
        known_event_ids=trusted.prefix_event_ids,
    )
    writer.append(
        readmission.result_id,
        "failure_readmission",
        (trusted.last_event_id,),
        {
            "at": readmission_at,
            "available_budget": tuple(item.to_dict() for item in available),
            "candidate_bid_ids": tuple(item.bid.bid_id for item in remaining),
            "excluded_failed_bid_ids": failed_bid_ids,
            "result": readmission.to_dict(),
        },
    )
    second_commitment, second_lifecycle, second_settlement = _materialize(
        writer=writer,
        ledger=ledger,
        candidate=takeover,
        selection_parent_id=readmission.result_id,
        selection_event_type="takeover",
        admission_policy=admission_policy,
        run_budget=available,
        admission_at=readmission_at,
        execution=takeover_execution,
        execution_event_type="takeover_execution",
        terminal_status=CommitmentStatus.COMPLETED,
    )
    commitments = (*trusted.commitments, second_commitment)
    lifecycles = (*trusted.lifecycles, second_lifecycle)
    totals = _combined_totals(
        trusted.ledger_totals,
        ledger,
        tuple(item.resource_type for item in run_budget),
    )
    organization = _organization(
        run_id=trusted.run_id,
        candidates=ordered,
        commitments=commitments,
        lifecycles=lifecycles,
        executions=(*trusted.executions, takeover_execution),
        checkpoint_revision=(
            trusted.next_public_state_revision + len(writer.events)
        ),
    )
    writer.append(
        organization.snapshot_id,
        "failure_organization_snapshot",
        (
            trusted.commitments[0].commitment_id,
            second_commitment.commitment_id,
            trusted.lifecycles[0].transition_ids[0],
            second_lifecycle.transition_ids[0],
            second_settlement,
        ),
        {"organization_snapshot": organization.to_dict()},
    )
    terminal_projection_sha256 = _terminal_hash(
        initial=trusted.initial_selection,
        readmission=readmission,
        commitments=commitments,
        lifecycles=lifecycles,
        organization=organization,
        totals=totals,
    )
    writer.append(
        f"failure-terminal-{trusted.run_id}",
        "failure_terminal",
        (organization.snapshot_id,),
        {
            "terminal_projection_sha256": (
                terminal_projection_sha256
            )
        },
    )
    if tuple(writer.events) != suffix:
        raise HarnessCycleError(
            "failure resume suffix semantics do not replay"
        )
    return FailureReorganizationReplay(
        organization_snapshot=organization,
        ledger_totals=totals,
        terminal_projection_sha256=terminal_projection_sha256,
    )


class FailureCheckpointPersistenceError(RuntimeError):
    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code


class FailureCheckpointExistsError(
    FailureCheckpointPersistenceError,
    FileExistsError,
):
    def __init__(self, message: str) -> None:
        super().__init__("checkpoint_exists", message)


@dataclass(frozen=True)
class FailureCheckpointPersistenceReceipt:
    path: Path
    file_sha256: str


class FailureCheckpointStore:
    FORMAT = "biofield.failure-reorganization-checkpoint"
    FORMAT_VERSION = 1

    @staticmethod
    def _temporary(path: Path) -> bool:
        return path.name.startswith(".") and path.name.endswith(".tmp")

    @staticmethod
    def _fsync_directory(directory: Path) -> None:
        flags = os.O_RDONLY | getattr(os, "O_DIRECTORY", 0)
        try:
            descriptor = os.open(directory, flags)
        except OSError as error:
            raise FailureCheckpointPersistenceError(
                "checkpoint_publish_error",
                f"cannot open checkpoint directory {directory}",
            ) from error
        try:
            os.fsync(descriptor)
        except OSError as error:
            raise FailureCheckpointPersistenceError(
                "checkpoint_publish_error",
                f"cannot fsync checkpoint directory {directory}",
            ) from error
        finally:
            os.close(descriptor)

    @classmethod
    def write(
        cls,
        path: str | os.PathLike[str],
        checkpoint: FailureReorganizationCheckpoint,
    ) -> FailureCheckpointPersistenceReceipt:
        if not isinstance(checkpoint, FailureReorganizationCheckpoint):
            raise TypeError(
                "checkpoint must be a FailureReorganizationCheckpoint"
            )
        destination = Path(path)
        if not destination.name or destination.name in {".", ".."}:
            raise FailureCheckpointPersistenceError(
                "invalid_checkpoint_path",
                "checkpoint path must name a file",
            )
        if not destination.parent.is_dir():
            raise FailureCheckpointPersistenceError(
                "invalid_checkpoint_path",
                "checkpoint parent directory must already exist",
            )
        validated = FailureReorganizationCheckpoint.from_dict(
            checkpoint.to_dict()
        )
        content = {
            "format": cls.FORMAT,
            "format_version": cls.FORMAT_VERSION,
            "checkpoint": validated.to_dict(),
        }
        content_sha256 = sha256(
            _canonical_json(content).encode("utf-8")
        ).hexdigest()
        envelope = {**content, "content_sha256": content_sha256}
        file_bytes = (_canonical_json(envelope) + "\n").encode("utf-8")
        file_sha256 = sha256(file_bytes).hexdigest()

        descriptor, temporary_name = tempfile.mkstemp(
            dir=destination.parent,
            prefix=f".{destination.name}.",
            suffix=".tmp",
        )
        temporary = Path(temporary_name)
        try:
            with os.fdopen(descriptor, "wb") as handle:
                handle.write(file_bytes)
                handle.flush()
                os.fsync(handle.fileno())
            try:
                os.link(temporary, destination)
            except FileExistsError as error:
                raise FailureCheckpointExistsError(
                    f"checkpoint {destination} already exists"
                ) from error
            except OSError as error:
                raise FailureCheckpointPersistenceError(
                    "checkpoint_publish_error",
                    f"cannot publish checkpoint {destination}",
                ) from error
            cls._fsync_directory(destination.parent)
        finally:
            temporary.unlink(missing_ok=True)
        return FailureCheckpointPersistenceReceipt(
            path=destination,
            file_sha256=file_sha256,
        )

    @classmethod
    def load(
        cls,
        path: str | os.PathLike[str],
        *,
        expected_file_sha256: str | None = None,
    ) -> FailureReorganizationCheckpoint:
        source = Path(path)
        if cls._temporary(source):
            raise FailureCheckpointPersistenceError(
                "unpublished_checkpoint",
                f"unpublished temporary checkpoint {source}",
            )
        try:
            file_bytes = source.read_bytes()
        except OSError as error:
            raise FailureCheckpointPersistenceError(
                "checkpoint_read_error",
                f"cannot read checkpoint {source}",
            ) from error
        actual_file_sha256 = sha256(file_bytes).hexdigest()
        if expected_file_sha256 is not None:
            try:
                expected = _require_sha256(
                    expected_file_sha256,
                    "expected_file_sha256",
                )
            except HarnessCycleError as error:
                raise FailureCheckpointPersistenceError(
                    "checkpoint_file_hash_mismatch",
                    str(error),
                ) from error
            if actual_file_sha256 != expected:
                raise FailureCheckpointPersistenceError(
                    "checkpoint_file_hash_mismatch",
                    "checkpoint file hash mismatch",
                )
        try:
            envelope = json.loads(file_bytes)
        except (UnicodeDecodeError, json.JSONDecodeError) as error:
            raise FailureCheckpointPersistenceError(
                "checkpoint_content_hash_mismatch",
                "checkpoint is not valid UTF-8 JSON",
            ) from error
        if not isinstance(envelope, dict) or set(envelope) != {
            "format",
            "format_version",
            "checkpoint",
            "content_sha256",
        }:
            raise FailureCheckpointPersistenceError(
                "checkpoint_content_hash_mismatch",
                "checkpoint envelope is invalid",
            )
        content = {
            "format": envelope["format"],
            "format_version": envelope["format_version"],
            "checkpoint": envelope["checkpoint"],
        }
        declared = envelope["content_sha256"]
        computed = sha256(
            _canonical_json(content).encode("utf-8")
        ).hexdigest()
        if (
            declared != computed
            or content["format"] != cls.FORMAT
            or content["format_version"] != cls.FORMAT_VERSION
        ):
            raise FailureCheckpointPersistenceError(
                "checkpoint_content_hash_mismatch",
                "checkpoint content hash or format is invalid",
            )
        try:
            return FailureReorganizationCheckpoint.from_dict(
                content["checkpoint"]
            )
        except (HarnessCycleError, TypeError, ValueError) as error:
            raise FailureCheckpointPersistenceError(
                "checkpoint_payload_invalid",
                f"checkpoint payload is invalid: {error}",
            ) from error
