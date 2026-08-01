"""Construct deterministic offline proposals for multi-Commitment transactions.

The returned batch is internally all-or-none, but this module does not claim
atomic persistence to an external ledger or event store.
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping
from dataclasses import dataclass
from decimal import Decimal
from types import MappingProxyType
from typing import Any

from .admission import (
    AdmissionDecision,
    AdmissionPolicy,
    AdmissionStatus,
    resolve_admission,
)
from .commitment import initial_commitment_lifecycle
from .contracts import (
    CommitmentLifecycleSnapshot,
    JsonContract,
    ResourceAmount,
    ResourceEvent,
    ResourceOperation,
)
from .ledger import ResourceLedger, SHARED_POOL, agent_escrow_account
from .local_runtime import HarnessRuntimeEvent
from .multi_admission import (
    BidCandidate,
    MultiAdmissionPolicy,
    MultiAdmissionResult,
    RequirementLoad,
    resolve_multi_admission,
)


def _canonical_hash(value: Any) -> str:
    if isinstance(value, JsonContract):
        value = value.to_dict()

    def jsonable(item: Any) -> Any:
        if isinstance(item, Mapping):
            return {str(key): jsonable(nested) for key, nested in item.items()}
        if isinstance(item, (list, tuple)):
            return [jsonable(nested) for nested in item]
        return item

    return hashlib.sha256(
        json.dumps(
            jsonable(value),
            allow_nan=False,
            separators=(",", ":"),
            sort_keys=True,
        ).encode("utf-8")
    ).hexdigest()


def _freeze(value: Any) -> Any:
    if isinstance(value, Mapping):
        return MappingProxyType({key: _freeze(item) for key, item in value.items()})
    if isinstance(value, (list, tuple)):
        return tuple(_freeze(item) for item in value)
    return value


def _strict_equal(left: Any, right: Any) -> bool:
    if type(left) is not type(right):
        return False
    if isinstance(left, dict):
        if len(left) != len(right):
            return False
        return all(
            key in right and _strict_equal(value, right[key])
            for key, value in left.items()
        )
    if isinstance(left, list):
        return len(left) == len(right) and all(
            _strict_equal(left_item, right_item)
            for left_item, right_item in zip(left, right, strict=True)
        )
    return bool(left == right)


def _canonical_decimal(value: Decimal) -> str:
    if not value.is_finite():
        raise ValueError("ledger total must be finite")
    text = format(value, "f")
    if "." in text:
        text = text.rstrip("0").rstrip(".")
    return "0" if text in {"", "-0"} else text


_TOTAL_FIELDS = ("expected", "shared_pool", "escrow", "reserved", "spent")


def _normalize_totals(
    totals: Mapping[str, Mapping[str, str]],
) -> dict[str, dict[str, str]]:
    normalized: dict[str, dict[str, str]] = {}
    for resource_type, values in totals.items():
        if not isinstance(resource_type, str) or not resource_type.strip():
            raise ValueError("ledger total resource type must be non-empty")
        if tuple(sorted(values)) != tuple(sorted(_TOTAL_FIELDS)):
            raise ValueError("ledger totals have unexpected fields")
        normalized[resource_type] = {
            field_name: _canonical_decimal(Decimal(str(values[field_name])))
            for field_name in _TOTAL_FIELDS
        }
    return dict(sorted(normalized.items()))


def _post_grant_totals(
    pre_totals: Mapping[str, Mapping[str, str]],
    grants: tuple[ResourceEvent, ...],
) -> dict[str, dict[str, str]]:
    result = _normalize_totals(pre_totals)
    for grant in grants:
        if grant.resource_type not in result:
            raise ValueError("grant resource type missing from pre-ledger totals")
        amount = Decimal(str(grant.amount))
        values = result[grant.resource_type]
        shared = Decimal(values["shared_pool"]) - amount
        if shared < 0:
            raise ValueError("grant exceeds pre-ledger shared pool")
        values["shared_pool"] = _canonical_decimal(shared)
        values["escrow"] = _canonical_decimal(Decimal(values["escrow"]) + amount)
    return result


def _derived_id(namespace: str, payload: Mapping[str, Any]) -> str:
    return (
        f"{namespace}-{_canonical_hash({'namespace': namespace, 'payload': payload})}"
    )


@dataclass(frozen=True, kw_only=True)
class AtomicCommitmentEntry(JsonContract):
    bid_id: str
    resource_grants: tuple[ResourceEvent, ...]
    decision: AdmissionDecision
    lifecycle: CommitmentLifecycleSnapshot

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "resource_grants",
            tuple(sorted(self.resource_grants, key=lambda item: item.event_id)),
        )
        if not isinstance(self.bid_id, str) or not self.bid_id.strip():
            raise ValueError("bid_id must be a non-empty string")
        if not self.resource_grants:
            raise ValueError("resource_grants cannot be empty")
        if len({item.event_id for item in self.resource_grants}) != len(
            self.resource_grants
        ):
            raise ValueError("duplicate resource grant IDs are not allowed")
        if len({item.resource_type for item in self.resource_grants}) != len(
            self.resource_grants
        ):
            raise ValueError("duplicate resource grant types are not allowed")
        if self.decision.status is not AdmissionStatus.ADMITTED:
            raise ValueError("atomic entry requires an admitted decision")
        commitment = self.decision.commitment
        if commitment is None or commitment.bid_id != self.bid_id:
            raise ValueError("atomic entry decision does not match bid_id")
        expected_target = agent_escrow_account(commitment.agent_id)
        for grant in self.resource_grants:
            if (
                grant.operation is not ResourceOperation.GRANT
                or grant.source_account != SHARED_POOL
                or grant.target_account != expected_target
            ):
                raise ValueError(
                    "atomic entry contains a non-authoritative resource grant"
                )
        if tuple(commitment.admitted_resource_grant_ids) != tuple(
            item.event_id for item in self.resource_grants
        ):
            raise ValueError("atomic entry grants do not match commitment")
        granted = {
            item.resource_type: Decimal(str(item.amount))
            for item in self.resource_grants
        }
        admitted = {
            item.resource_type: Decimal(str(item.amount))
            for item in commitment.admitted_resources
        }
        if granted != admitted:
            raise ValueError(
                "atomic entry grant amounts do not match admitted resources"
            )
        if self.lifecycle != initial_commitment_lifecycle(commitment):
            raise ValueError("atomic entry lifecycle does not match commitment")


@dataclass(frozen=True, kw_only=True)
class AtomicCommitmentBatch(JsonContract):
    schema_version: int
    candidates: tuple[BidCandidate, ...]
    run_budget: tuple[ResourceAmount, ...]
    reserved_resources: tuple[ResourceAmount, ...]
    existing_requirement_loads: tuple[RequirementLoad, ...]
    ready_requirement_ids: tuple[str, ...]
    current_concurrency: int
    admission_policy: AdmissionPolicy
    multi_admission_policy: MultiAdmissionPolicy
    at: str
    run_finalized: bool
    prior_resource_events: tuple[ResourceEvent, ...]
    prior_public_events: tuple[HarnessRuntimeEvent, ...]
    selection: MultiAdmissionResult
    entries: tuple[AtomicCommitmentEntry, ...]
    appended_resource_events: tuple[ResourceEvent, ...]
    appended_public_events: tuple[HarnessRuntimeEvent, ...]
    pre_ledger_totals: Mapping[str, Mapping[str, str]]
    ledger_totals: Mapping[str, Mapping[str, str]]
    prior_resource_event_ids: tuple[str, ...]
    prior_public_event_ids: tuple[str, ...]
    public_revision_start: int
    public_parent_id: str | None
    claim_scope: str
    production_authorized: bool
    scientific_claim: bool
    batch_sha256: str

    def __post_init__(self) -> None:
        for field_name in (
            "candidates",
            "run_budget",
            "reserved_resources",
            "existing_requirement_loads",
            "ready_requirement_ids",
            "prior_resource_events",
            "prior_public_events",
            "entries",
            "appended_resource_events",
            "appended_public_events",
            "prior_resource_event_ids",
            "prior_public_event_ids",
        ):
            object.__setattr__(self, field_name, tuple(getattr(self, field_name)))
        object.__setattr__(
            self,
            "candidates",
            tuple(sorted(self.candidates, key=lambda item: item.bid.bid_id)),
        )
        object.__setattr__(
            self,
            "run_budget",
            tuple(sorted(self.run_budget, key=lambda item: item.resource_type)),
        )
        object.__setattr__(
            self,
            "reserved_resources",
            tuple(
                sorted(
                    self.reserved_resources,
                    key=lambda item: item.resource_type,
                )
            ),
        )
        object.__setattr__(
            self,
            "existing_requirement_loads",
            tuple(
                sorted(
                    self.existing_requirement_loads,
                    key=lambda item: item.requirement_id,
                )
            ),
        )
        object.__setattr__(
            self,
            "ready_requirement_ids",
            tuple(sorted(self.ready_requirement_ids)),
        )
        object.__setattr__(self, "pre_ledger_totals", _freeze(self.pre_ledger_totals))
        object.__setattr__(self, "ledger_totals", _freeze(self.ledger_totals))
        if self.schema_version != 1 or isinstance(self.schema_version, bool):
            raise ValueError("schema_version must be 1")
        expected_selection = resolve_multi_admission(
            candidates=self.candidates,
            run_budget=self.run_budget,
            reserved_resources=self.reserved_resources,
            existing_requirement_loads=self.existing_requirement_loads,
            ready_requirement_ids=self.ready_requirement_ids,
            current_concurrency=self.current_concurrency,
            admission_policy=self.admission_policy,
            policy=self.multi_admission_policy,
            at=self.at,
            run_finalized=self.run_finalized,
        )
        if self.selection != expected_selection:
            raise ValueError("selection does not match embedded typed resolver sources")
        if len(self.selection.admitted_bid_ids) < 2:
            raise ValueError("proposal requires at least two admitted bids")
        (
            replayed_ledger,
            resource_types,
            expected_pre_totals,
            expected_prior_resource_ids,
            expected_prior_public_ids,
        ) = _replay_typed_prior_sources(
            run_budget=self.run_budget,
            reserved_resources=self.reserved_resources,
            prior_resource_events=self.prior_resource_events,
            prior_public_events=self.prior_public_events,
        )
        if _normalize_totals(self.pre_ledger_totals) != expected_pre_totals:
            raise ValueError(
                "pre-ledger totals do not match embedded typed prior sources"
            )
        if self.prior_resource_event_ids != expected_prior_resource_ids:
            raise ValueError("prior resource IDs do not match embedded typed events")
        if self.prior_public_event_ids != expected_prior_public_ids:
            raise ValueError("prior public IDs do not match embedded typed events")
        expected_entries = _derive_entries(
            selection=self.selection,
            candidates=self.candidates,
            run_budget=self.run_budget,
            admission_policy=self.admission_policy,
            at=self.at,
            run_finalized=self.run_finalized,
        )
        if self.entries != expected_entries:
            raise ValueError(
                "entries do not match commitments derived from typed sources"
            )
        bid_ids = tuple(entry.bid_id for entry in self.entries)
        if bid_ids != tuple(sorted(bid_ids)) or len(bid_ids) != len(set(bid_ids)):
            raise ValueError("atomic entries must have unique, sorted bid IDs")
        if bid_ids != self.selection.admitted_bid_ids:
            raise ValueError("atomic entries must exactly match admitted bids")
        grants = tuple(
            grant for entry in self.entries for grant in entry.resource_grants
        )
        if grants != self.appended_resource_events:
            raise ValueError("appended resource events must exactly match entries")
        grant_ids = tuple(event.event_id for event in grants)
        if len(grant_ids) != len(set(grant_ids)):
            raise ValueError("resource grant event IDs must be globally unique")
        expected_totals = _post_grant_totals(self.pre_ledger_totals, grants)
        if _normalize_totals(self.ledger_totals) != expected_totals:
            raise ValueError(
                "ledger totals do not derive from pre-ledger totals and grants"
            )
        for grant in grants:
            if not replayed_ledger.apply(grant):
                raise ValueError("derived grant duplicates a typed prior event")
        replayed_ledger.assert_conserved()
        if _normalize_totals(self.ledger_totals) != _normalize_totals(
            _ledger_totals(replayed_ledger, resource_types)
        ):
            raise ValueError(
                "ledger totals do not match replayed typed sources and grants"
            )
        if (
            isinstance(self.public_revision_start, bool)
            or not isinstance(self.public_revision_start, int)
            or self.public_revision_start < 0
        ):
            raise ValueError("public_revision_start must be non-negative")
        if self.public_parent_id is not None and (
            not isinstance(self.public_parent_id, str)
            or not self.public_parent_id.strip()
        ):
            raise ValueError("public_parent_id must be non-empty when present")
        expected_public = _expected_public_events(
            selection=self.selection,
            entries=self.entries,
            revision_start=self.public_revision_start,
            parent_id=self.public_parent_id,
        )
        if self.appended_public_events != expected_public:
            raise ValueError(
                "public events do not exactly match the derived event stream"
            )
        all_event_ids = (
            *self.prior_resource_event_ids,
            *self.prior_public_event_ids,
            *grant_ids,
            *(event.event_id for event in self.appended_public_events),
        )
        if len(all_event_ids) != len(set(all_event_ids)):
            raise ValueError("resource/public event IDs must be globally unique")
        if self.public_revision_start != len(self.prior_public_event_ids):
            raise ValueError("public_revision_start must follow prior public events")
        expected_parent = (
            self.prior_public_event_ids[-1] if self.prior_public_event_ids else None
        )
        if self.public_parent_id != expected_parent:
            raise ValueError("public parent must be the last prior public event")
        if (
            self.claim_scope
            != "deterministic_offline_atomic_proposal_construction_only"
        ):
            raise ValueError("atomic batch cannot broaden its claim scope")
        if self.production_authorized or self.scientific_claim:
            raise ValueError(
                "atomic batch cannot authorize production or science claims"
            )
        if len(self.batch_sha256) != 64 or any(
            character not in "0123456789abcdef" for character in self.batch_sha256
        ):
            raise ValueError("batch_sha256 must be a lowercase SHA-256 digest")
        expected_hash = _batch_hash(
            selection=self.selection,
            entries=self.entries,
            appended_resource_events=self.appended_resource_events,
            appended_public_events=self.appended_public_events,
            pre_ledger_totals=self.pre_ledger_totals,
            ledger_totals=self.ledger_totals,
            prior_resource_event_ids=self.prior_resource_event_ids,
            prior_public_event_ids=self.prior_public_event_ids,
            public_revision_start=self.public_revision_start,
            public_parent_id=self.public_parent_id,
            candidates=self.candidates,
            run_budget=self.run_budget,
            reserved_resources=self.reserved_resources,
            existing_requirement_loads=self.existing_requirement_loads,
            ready_requirement_ids=self.ready_requirement_ids,
            current_concurrency=self.current_concurrency,
            admission_policy=self.admission_policy,
            multi_admission_policy=self.multi_admission_policy,
            at=self.at,
            run_finalized=self.run_finalized,
            prior_resource_events=self.prior_resource_events,
            prior_public_events=self.prior_public_events,
        )
        if self.batch_sha256 != expected_hash:
            raise ValueError("batch_sha256 does not match batch content")

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "candidates": [item.to_dict() for item in self.candidates],
            "run_budget": [item.to_dict() for item in self.run_budget],
            "reserved_resources": [item.to_dict() for item in self.reserved_resources],
            "existing_requirement_loads": [
                item.to_dict() for item in self.existing_requirement_loads
            ],
            "ready_requirement_ids": list(self.ready_requirement_ids),
            "current_concurrency": self.current_concurrency,
            "admission_policy": self.admission_policy.to_dict(),
            "multi_admission_policy": self.multi_admission_policy.to_dict(),
            "at": self.at,
            "run_finalized": self.run_finalized,
            "prior_resource_events": [
                event.to_dict() for event in self.prior_resource_events
            ],
            "prior_public_events": [
                event.to_dict() for event in self.prior_public_events
            ],
            "selection": self.selection.to_dict(),
            "entries": [entry.to_dict() for entry in self.entries],
            "appended_resource_events": [
                event.to_dict() for event in self.appended_resource_events
            ],
            "appended_public_events": [
                event.to_dict() for event in self.appended_public_events
            ],
            "pre_ledger_totals": {
                resource_type: dict(totals)
                for resource_type, totals in self.pre_ledger_totals.items()
            },
            "ledger_totals": {
                resource_type: dict(totals)
                for resource_type, totals in self.ledger_totals.items()
            },
            "prior_resource_event_ids": list(self.prior_resource_event_ids),
            "prior_public_event_ids": list(self.prior_public_event_ids),
            "public_revision_start": self.public_revision_start,
            "public_parent_id": self.public_parent_id,
            "claim_scope": self.claim_scope,
            "production_authorized": self.production_authorized,
            "scientific_claim": self.scientific_claim,
            "batch_sha256": self.batch_sha256,
        }

    @classmethod
    def restore_from_typed_sources(
        cls,
        value: Mapping[str, Any],
        **sources: Any,
    ) -> AtomicCommitmentBatch:
        expected = materialize_atomic_commitments(**sources)
        if not _strict_equal(dict(value), expected.to_dict()):
            raise ValueError("strict restore differs from typed-source replay")
        return expected


def _batch_hash(
    *,
    candidates: tuple[BidCandidate, ...],
    run_budget: tuple[ResourceAmount, ...],
    reserved_resources: tuple[ResourceAmount, ...],
    existing_requirement_loads: tuple[RequirementLoad, ...],
    ready_requirement_ids: tuple[str, ...],
    current_concurrency: int,
    admission_policy: AdmissionPolicy,
    multi_admission_policy: MultiAdmissionPolicy,
    at: str,
    run_finalized: bool,
    prior_resource_events: tuple[ResourceEvent, ...],
    prior_public_events: tuple[HarnessRuntimeEvent, ...],
    selection: MultiAdmissionResult,
    entries: tuple[AtomicCommitmentEntry, ...],
    appended_resource_events: tuple[ResourceEvent, ...],
    appended_public_events: tuple[HarnessRuntimeEvent, ...],
    pre_ledger_totals: Mapping[str, Mapping[str, str]] | None = None,
    ledger_totals: Mapping[str, Mapping[str, str]],
    prior_resource_event_ids: tuple[str, ...] = (),
    prior_public_event_ids: tuple[str, ...] = (),
    public_revision_start: int = 0,
    public_parent_id: str | None = None,
) -> str:
    return _canonical_hash(
        {
            "admission_policy": admission_policy.to_dict(),
            "appended_public_events": [
                event.to_dict() for event in appended_public_events
            ],
            "appended_resource_events": [
                event.to_dict() for event in appended_resource_events
            ],
            "at": at,
            "candidates": [item.to_dict() for item in candidates],
            "current_concurrency": current_concurrency,
            "entries": [entry.to_dict() for entry in entries],
            "existing_requirement_loads": [
                item.to_dict() for item in existing_requirement_loads
            ],
            "pre_ledger_totals": {
                resource_type: dict(totals)
                for resource_type, totals in (pre_ledger_totals or {}).items()
            },
            "ledger_totals": {
                resource_type: dict(totals)
                for resource_type, totals in ledger_totals.items()
            },
            "production_authorized": False,
            "prior_public_events": [event.to_dict() for event in prior_public_events],
            "prior_public_event_ids": list(prior_public_event_ids),
            "prior_resource_events": [
                event.to_dict() for event in prior_resource_events
            ],
            "prior_resource_event_ids": list(prior_resource_event_ids),
            "public_parent_id": public_parent_id,
            "public_revision_start": public_revision_start,
            "schema_version": 1,
            "scientific_claim": False,
            "selection": selection.to_dict(),
            "multi_admission_policy": multi_admission_policy.to_dict(),
            "ready_requirement_ids": list(ready_requirement_ids),
            "reserved_resources": [item.to_dict() for item in reserved_resources],
            "run_budget": [item.to_dict() for item in run_budget],
            "run_finalized": run_finalized,
            "claim_scope": ("deterministic_offline_atomic_proposal_construction_only"),
        }
    )


def _validate_prior_public_events(
    events: tuple[HarnessRuntimeEvent, ...],
) -> None:
    seen: set[str] = set()
    for revision, event in enumerate(events):
        if not isinstance(event, HarnessRuntimeEvent):
            raise ValueError("prior_public_events must contain HarnessRuntimeEvent")
        if event.public_state_revision != revision:
            raise ValueError("prior public event revisions must be contiguous")
        if event.event_id in seen:
            raise ValueError("duplicate prior public event IDs are not allowed")
        if set(event.causal_parent_ids) - seen:
            raise ValueError("prior public event has a missing causal parent")
        if event.payload_sha256 != _canonical_hash(dict(event.payload)):
            raise ValueError("prior public event payload hash mismatch")
        seen.add(event.event_id)


def _ledger_totals(
    ledger: ResourceLedger,
    resource_types: tuple[str, ...],
) -> Mapping[str, Mapping[str, str]]:
    result: dict[str, Mapping[str, str]] = {}
    for resource_type in sorted(set(resource_types)):
        totals = ledger.totals(resource_type)
        result[resource_type] = {
            "expected": _canonical_decimal(totals.expected),
            "shared_pool": _canonical_decimal(totals.shared_pool),
            "escrow": _canonical_decimal(totals.escrow),
            "reserved": _canonical_decimal(totals.reserved),
            "spent": _canonical_decimal(totals.spent),
        }
    return result


def _replay_typed_prior_sources(
    *,
    run_budget: tuple[ResourceAmount, ...],
    reserved_resources: tuple[ResourceAmount, ...],
    prior_resource_events: tuple[ResourceEvent, ...],
    prior_public_events: tuple[HarnessRuntimeEvent, ...],
) -> tuple[
    ResourceLedger,
    tuple[str, ...],
    dict[str, dict[str, str]],
    tuple[str, ...],
    tuple[str, ...],
]:
    initial = {item.resource_type: Decimal(str(item.amount)) for item in run_budget}
    if len(initial) != len(run_budget):
        raise ValueError("run_budget has duplicate resource types")
    ledger = ResourceLedger(initial)
    for event in prior_resource_events:
        if not isinstance(event, ResourceEvent):
            raise ValueError("prior_resource_events must contain ResourceEvent")
        if not ledger.apply(event):
            raise ValueError("duplicate prior resource event")
    ledger.assert_conserved()
    resource_types = tuple(
        sorted(
            set(initial)
            | {event.resource_type for event in prior_resource_events}
            | {item.resource_type for item in reserved_resources}
        )
    )
    actual_reserved = {
        resource_type: (
            ledger.totals(resource_type).escrow
            + ledger.totals(resource_type).reserved
            + ledger.totals(resource_type).spent
        )
        for resource_type in resource_types
        if (
            ledger.totals(resource_type).escrow
            + ledger.totals(resource_type).reserved
            + ledger.totals(resource_type).spent
        )
    }
    declared_reserved = {
        item.resource_type: Decimal(str(item.amount)) for item in reserved_resources
    }
    if actual_reserved != declared_reserved:
        raise ValueError("reserved_resources do not match replayed resource ledger")
    _validate_prior_public_events(prior_public_events)
    prior_resource_ids = tuple(event.event_id for event in prior_resource_events)
    prior_public_ids = tuple(event.event_id for event in prior_public_events)
    prior_global_ids = (*prior_resource_ids, *prior_public_ids)
    if len(prior_global_ids) != len(set(prior_global_ids)):
        raise ValueError("prior resource/public event IDs must be globally unique")
    return (
        ledger,
        resource_types,
        _normalize_totals(_ledger_totals(ledger, resource_types)),
        prior_resource_ids,
        prior_public_ids,
    )


def _derive_entries(
    *,
    selection: MultiAdmissionResult,
    candidates: tuple[BidCandidate, ...],
    run_budget: tuple[ResourceAmount, ...],
    admission_policy: AdmissionPolicy,
    at: str,
    run_finalized: bool,
) -> tuple[AtomicCommitmentEntry, ...]:
    by_bid_id = {item.bid.bid_id: item for item in candidates}
    entries: list[AtomicCommitmentEntry] = []
    for bid_id in selection.admitted_bid_ids:
        candidate = by_bid_id[bid_id]
        grants_list: list[ResourceEvent] = []
        for amount in sorted(
            candidate.bid.requested_budget_vector,
            key=lambda item: item.resource_type,
        ):
            identity = {
                "agent_id": candidate.bid.agent_id,
                "bid_id": bid_id,
                "resource": amount.to_dict(),
                "selection_result_id": selection.result_id,
            }
            event_id = _derived_id("atomic-resource-grant", identity)
            grants_list.append(
                ResourceEvent(
                    event_id=event_id,
                    operation=ResourceOperation.GRANT,
                    resource_type=amount.resource_type,
                    amount=amount.amount,
                    source_account=SHARED_POOL,
                    target_account=agent_escrow_account(candidate.bid.agent_id),
                    idempotency_key=event_id,
                )
            )
        grants = tuple(grants_list)
        decision = resolve_admission(
            bid=candidate.bid,
            intent=candidate.intent,
            observation=candidate.observation,
            resource_grants=grants,
            run_budget=run_budget,
            policy=admission_policy,
            at=at,
            run_finalized=run_finalized,
        )
        if decision.status is not AdmissionStatus.ADMITTED:
            raise ValueError(f"admitted bid failed commitment preflight: {bid_id}")
        assert decision.commitment is not None
        entries.append(
            AtomicCommitmentEntry(
                bid_id=bid_id,
                resource_grants=grants,
                decision=decision,
                lifecycle=initial_commitment_lifecycle(decision.commitment),
            )
        )
    return tuple(entries)


def _public_event(
    *,
    revision: int,
    event_id: str,
    event_type: str,
    parents: tuple[str, ...],
    payload: Mapping[str, Any],
) -> HarnessRuntimeEvent:
    frozen = _freeze(payload)
    return HarnessRuntimeEvent(
        event_id=event_id,
        event_type=event_type,
        event_schema_version=1,
        public_state_revision=revision,
        causal_parent_ids=parents,
        payload=frozen,
        payload_sha256=_canonical_hash(dict(frozen)),
    )


def _expected_public_events(
    *,
    selection: MultiAdmissionResult,
    entries: tuple[AtomicCommitmentEntry, ...],
    revision_start: int,
    parent_id: str | None,
) -> tuple[HarnessRuntimeEvent, ...]:
    events: list[HarnessRuntimeEvent] = []

    def append(
        event_type: str,
        parents: tuple[str, ...],
        payload: Mapping[str, Any],
    ) -> str:
        event_id = _derived_id(f"atomic-public-{event_type}", payload)
        events.append(
            _public_event(
                revision=revision_start + len(events),
                event_id=event_id,
                event_type=event_type,
                parents=parents,
                payload=payload,
            )
        )
        return event_id

    selection_event_id = append(
        "multi_admission_selected",
        () if parent_id is None else (parent_id,),
        selection.to_dict(),
    )
    for entry in entries:
        public_grant_ids = tuple(
            append(
                "resource_grant",
                (selection_event_id,),
                grant.to_dict(),
            )
            for grant in entry.resource_grants
        )
        append(
            "commitment_materialized",
            public_grant_ids,
            entry.decision.to_dict(),
        )
    return tuple(events)


def _after_preflight_hook() -> None:
    """Test seam invoked before any proposal batch is constructed."""


def construct_atomic_commitment_proposal(
    *,
    selection: MultiAdmissionResult,
    candidates: tuple[BidCandidate, ...],
    run_budget: tuple[ResourceAmount, ...],
    reserved_resources: tuple[ResourceAmount, ...],
    existing_requirement_loads: tuple[RequirementLoad, ...],
    ready_requirement_ids: tuple[str, ...],
    current_concurrency: int,
    admission_policy: AdmissionPolicy,
    policy: MultiAdmissionPolicy,
    at: str,
    run_finalized: bool,
    prior_resource_events: tuple[ResourceEvent, ...] = (),
    prior_public_events: tuple[HarnessRuntimeEvent, ...] = (),
) -> AtomicCommitmentBatch:
    """Construct an immutable all-or-none proposal from preflighted Bids.

    This pure function does not commit to an external ledger or event store.
    Durable atomicity requires a transactional sink outside this module.
    """

    ordered_candidates = tuple(sorted(candidates, key=lambda item: item.bid.bid_id))
    budget = tuple(sorted(run_budget, key=lambda item: item.resource_type))
    reserved = tuple(sorted(reserved_resources, key=lambda item: item.resource_type))
    loads = tuple(
        sorted(
            existing_requirement_loads,
            key=lambda item: item.requirement_id,
        )
    )
    ready = tuple(sorted(ready_requirement_ids))
    prior_resources = tuple(prior_resource_events)
    prior_public = tuple(prior_public_events)
    expected_selection = resolve_multi_admission(
        candidates=ordered_candidates,
        run_budget=budget,
        reserved_resources=reserved,
        existing_requirement_loads=loads,
        ready_requirement_ids=ready,
        current_concurrency=current_concurrency,
        admission_policy=admission_policy,
        policy=policy,
        at=at,
        run_finalized=run_finalized,
    )
    if selection != expected_selection:
        raise ValueError("selection does not match deterministic resolver replay")
    if len(selection.admitted_bid_ids) < 2:
        raise ValueError(
            "atomic proposal construction requires at least two admitted bids"
        )

    (
        ledger,
        resource_types,
        pre_totals,
        prior_resource_ids,
        prior_public_ids,
    ) = _replay_typed_prior_sources(
        run_budget=budget,
        reserved_resources=reserved,
        prior_resource_events=prior_resources,
        prior_public_events=prior_public,
    )
    prior_global_ids = (*prior_resource_ids, *prior_public_ids)
    entry_tuple = _derive_entries(
        selection=selection,
        candidates=ordered_candidates,
        run_budget=budget,
        admission_policy=admission_policy,
        at=at,
        run_finalized=run_finalized,
    )

    _after_preflight_hook()

    appended_resources = tuple(
        grant for entry in entry_tuple for grant in entry.resource_grants
    )
    for event in appended_resources:
        if not ledger.apply(event):
            raise ValueError("new resource grant unexpectedly duplicated")
    ledger.assert_conserved()

    totals = _ledger_totals(ledger, resource_types)
    public_parent_id = prior_public_ids[-1] if prior_public_ids else None
    public_tuple = _expected_public_events(
        selection=selection,
        entries=entry_tuple,
        revision_start=len(prior_public_ids),
        parent_id=public_parent_id,
    )
    new_global_ids = (
        *(event.event_id for event in appended_resources),
        *(event.event_id for event in public_tuple),
    )
    all_global_ids = (*prior_global_ids, *new_global_ids)
    if len(all_global_ids) != len(set(all_global_ids)):
        raise ValueError("resource/public event IDs must be globally unique")
    batch_sha256 = _batch_hash(
        candidates=ordered_candidates,
        run_budget=budget,
        reserved_resources=reserved,
        existing_requirement_loads=loads,
        ready_requirement_ids=ready,
        current_concurrency=current_concurrency,
        admission_policy=admission_policy,
        multi_admission_policy=policy,
        at=at,
        run_finalized=run_finalized,
        prior_resource_events=prior_resources,
        prior_public_events=prior_public,
        selection=selection,
        entries=entry_tuple,
        appended_resource_events=appended_resources,
        appended_public_events=public_tuple,
        pre_ledger_totals=pre_totals,
        ledger_totals=totals,
        prior_resource_event_ids=prior_resource_ids,
        prior_public_event_ids=prior_public_ids,
        public_revision_start=len(prior_public_ids),
        public_parent_id=public_parent_id,
    )
    return AtomicCommitmentBatch(
        schema_version=1,
        candidates=ordered_candidates,
        run_budget=budget,
        reserved_resources=reserved,
        existing_requirement_loads=loads,
        ready_requirement_ids=ready,
        current_concurrency=current_concurrency,
        admission_policy=admission_policy,
        multi_admission_policy=policy,
        at=at,
        run_finalized=run_finalized,
        prior_resource_events=prior_resources,
        prior_public_events=prior_public,
        selection=selection,
        entries=entry_tuple,
        appended_resource_events=appended_resources,
        appended_public_events=public_tuple,
        pre_ledger_totals=pre_totals,
        ledger_totals=totals,
        prior_resource_event_ids=prior_resource_ids,
        prior_public_event_ids=prior_public_ids,
        public_revision_start=len(prior_public_ids),
        public_parent_id=public_parent_id,
        claim_scope="deterministic_offline_atomic_proposal_construction_only",
        production_authorized=False,
        scientific_claim=False,
        batch_sha256=batch_sha256,
    )


def materialize_atomic_commitments(**sources: Any) -> AtomicCommitmentBatch:
    """Compatibility name for proposal construction, not external commit."""

    return construct_atomic_commitment_proposal(**sources)


def replay_atomic_commitments(
    *,
    batch: AtomicCommitmentBatch,
    **sources: Any,
) -> AtomicCommitmentBatch:
    replayed = materialize_atomic_commitments(**sources)
    if replayed != batch:
        raise ValueError("atomic commitment replay differs from recorded batch")
    return replayed


__all__ = [
    "AtomicCommitmentBatch",
    "AtomicCommitmentEntry",
    "construct_atomic_commitment_proposal",
    "materialize_atomic_commitments",
    "replay_atomic_commitments",
]
