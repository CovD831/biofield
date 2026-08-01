from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from datetime import datetime
from enum import Enum

from .contracts import (
    AgentCommitment,
    CommitmentLifecycleSnapshot,
    CommitmentStatus,
    CommunicationOffer,
    CommunicationPermit,
    CommunicationRequest,
    GovernanceIssuer,
    JsonContract,
    LocalFieldObservation,
    ResourceAmount,
)


class CommunicationGovernanceError(ValueError):
    """A communication proposal violated audience, policy, or lifecycle rules."""


class CommunicationRuntimeIssuer(str, Enum):
    HARNESS_TRANSPORT = "harness_transport"
    HARNESS_CONSUMER = "harness_consumer"


def _require_text(value: str, field_name: str) -> None:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{field_name} must be a non-empty string")


def _parse_timestamp(value: str, field_name: str) -> datetime:
    try:
        parsed = datetime.fromisoformat(value)
    except (TypeError, ValueError) as error:
        raise CommunicationGovernanceError(
            f"{field_name} must be an ISO-8601 timestamp"
        ) from error
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise CommunicationGovernanceError(
            f"{field_name} must include a UTC offset"
        )
    return parsed


def _stable_digest(payload: object) -> str:
    encoded = json.dumps(
        payload,
        allow_nan=False,
        separators=(",", ":"),
        sort_keys=True,
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _validate_resource_cost(
    resource_cost: tuple[ResourceAmount, ...],
) -> tuple[ResourceAmount, ...]:
    normalized = tuple(resource_cost)
    if not normalized:
        raise ValueError("communication resource_cost cannot be empty")
    if not all(isinstance(item, ResourceAmount) for item in normalized):
        raise ValueError("resource_cost must contain ResourceAmount values")
    resource_types = tuple(item.resource_type for item in normalized)
    if len(resource_types) != len(set(resource_types)):
        raise ValueError("duplicate resource_cost resource types")
    return normalized


@dataclass(frozen=True, kw_only=True)
class CommunicationDelivery(JsonContract):
    delivery_id: str
    permit_id: str
    commitment_id: str
    sender_agent_id: str
    receiver_agent_id: str
    payload_schema: str
    payload_sha256: str
    payload_size_bytes: int
    message_count: int
    resource_cost: tuple[ResourceAmount, ...]
    delivered_at: str
    causal_parent_ids: tuple[str, ...]
    issuer: CommunicationRuntimeIssuer

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "resource_cost",
            _validate_resource_cost(self.resource_cost),
        )
        object.__setattr__(
            self,
            "causal_parent_ids",
            tuple(self.causal_parent_ids),
        )
        for field_name in (
            "delivery_id",
            "permit_id",
            "commitment_id",
            "sender_agent_id",
            "receiver_agent_id",
            "payload_schema",
        ):
            _require_text(getattr(self, field_name), field_name)
        if self.sender_agent_id == self.receiver_agent_id:
            raise ValueError("delivery endpoints must differ")
        if (
            len(self.payload_sha256) != 64
            or any(
                character not in "0123456789abcdef"
                for character in self.payload_sha256
            )
        ):
            raise ValueError("payload_sha256 must be a SHA-256 digest")
        for value, field_name in (
            (self.payload_size_bytes, "payload_size_bytes"),
            (self.message_count, "message_count"),
        ):
            if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
                raise ValueError(f"{field_name} must be a positive integer")
        _parse_timestamp(self.delivered_at, "delivered_at")
        if self.causal_parent_ids != (self.permit_id,):
            raise ValueError("delivery parent must be its permit")
        if self.issuer is not CommunicationRuntimeIssuer.HARNESS_TRANSPORT:
            raise ValueError("delivery issuer must be Harness transport")

    @classmethod
    def from_dict(cls, value: dict[str, object]) -> "CommunicationDelivery":
        payload = dict(value)
        payload["resource_cost"] = tuple(
            ResourceAmount(**item) for item in payload["resource_cost"]
        )
        payload["causal_parent_ids"] = tuple(payload["causal_parent_ids"])
        payload["issuer"] = CommunicationRuntimeIssuer(payload["issuer"])
        return cls(**payload)


@dataclass(frozen=True, kw_only=True)
class CommunicationReceipt(JsonContract):
    receipt_id: str
    delivery_id: str
    permit_id: str
    receiver_agent_id: str
    payload_sha256: str
    received_at: str
    causal_parent_ids: tuple[str, ...]
    issuer: CommunicationRuntimeIssuer

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "causal_parent_ids",
            tuple(self.causal_parent_ids),
        )
        for field_name in (
            "receipt_id",
            "delivery_id",
            "permit_id",
            "receiver_agent_id",
        ):
            _require_text(getattr(self, field_name), field_name)
        if (
            len(self.payload_sha256) != 64
            or any(
                character not in "0123456789abcdef"
                for character in self.payload_sha256
            )
        ):
            raise ValueError("payload_sha256 must be a SHA-256 digest")
        _parse_timestamp(self.received_at, "received_at")
        if self.causal_parent_ids != (self.delivery_id,):
            raise ValueError("receipt parent must be its delivery")
        if self.issuer is not CommunicationRuntimeIssuer.HARNESS_TRANSPORT:
            raise ValueError("receipt issuer must be Harness transport")

    @classmethod
    def from_dict(cls, value: dict[str, object]) -> "CommunicationReceipt":
        payload = dict(value)
        payload["causal_parent_ids"] = tuple(payload["causal_parent_ids"])
        payload["issuer"] = CommunicationRuntimeIssuer(payload["issuer"])
        return cls(**payload)


@dataclass(frozen=True, kw_only=True)
class CommunicationConsumption(JsonContract):
    consumption_id: str
    receipt_id: str
    delivery_id: str
    permit_id: str
    consumer_agent_id: str
    payload_sha256: str
    consumed_at: str
    causal_parent_ids: tuple[str, ...]
    issuer: CommunicationRuntimeIssuer

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "causal_parent_ids",
            tuple(self.causal_parent_ids),
        )
        for field_name in (
            "consumption_id",
            "receipt_id",
            "delivery_id",
            "permit_id",
            "consumer_agent_id",
        ):
            _require_text(getattr(self, field_name), field_name)
        if (
            len(self.payload_sha256) != 64
            or any(
                character not in "0123456789abcdef"
                for character in self.payload_sha256
            )
        ):
            raise ValueError("payload_sha256 must be a SHA-256 digest")
        _parse_timestamp(self.consumed_at, "consumed_at")
        if self.causal_parent_ids != (self.receipt_id,):
            raise ValueError("consumption parent must be its receipt")
        if self.issuer is not CommunicationRuntimeIssuer.HARNESS_CONSUMER:
            raise ValueError("consumption issuer must be Harness consumer")

    @classmethod
    def from_dict(
        cls,
        value: dict[str, object],
    ) -> "CommunicationConsumption":
        payload = dict(value)
        payload["causal_parent_ids"] = tuple(payload["causal_parent_ids"])
        payload["issuer"] = CommunicationRuntimeIssuer(payload["issuer"])
        return cls(**payload)


@dataclass(frozen=True)
class CommunicationEdgePermission(JsonContract):
    sender_agent_id: str
    receiver_agent_id: str
    allowed_payload_schemas: tuple[str, ...]
    max_payload_bytes: int
    max_messages: int

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "allowed_payload_schemas",
            tuple(sorted(self.allowed_payload_schemas)),
        )
        _require_text(self.sender_agent_id, "sender_agent_id")
        _require_text(self.receiver_agent_id, "receiver_agent_id")
        if self.sender_agent_id == self.receiver_agent_id:
            raise ValueError("communication edge endpoints must differ")
        if not self.allowed_payload_schemas:
            raise ValueError("allowed_payload_schemas cannot be empty")
        if len(self.allowed_payload_schemas) != len(
            set(self.allowed_payload_schemas)
        ):
            raise ValueError("duplicate allowed_payload_schemas are not allowed")
        for schema in self.allowed_payload_schemas:
            _require_text(schema, "allowed_payload_schema")
        for value, field_name in (
            (self.max_payload_bytes, "max_payload_bytes"),
            (self.max_messages, "max_messages"),
        ):
            if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
                raise ValueError(f"{field_name} must be a positive integer")

    @classmethod
    def from_dict(
        cls,
        value: dict[str, object],
    ) -> "CommunicationEdgePermission":
        payload = dict(value)
        payload["allowed_payload_schemas"] = tuple(
            payload["allowed_payload_schemas"]
        )
        return cls(**payload)


@dataclass(frozen=True)
class CommunicationEdgeUsage(JsonContract):
    sender_agent_id: str
    receiver_agent_id: str
    used_messages: int

    def __post_init__(self) -> None:
        _require_text(self.sender_agent_id, "sender_agent_id")
        _require_text(self.receiver_agent_id, "receiver_agent_id")
        if self.sender_agent_id == self.receiver_agent_id:
            raise ValueError("communication edge endpoints must differ")
        if (
            isinstance(self.used_messages, bool)
            or not isinstance(self.used_messages, int)
            or self.used_messages < 0
        ):
            raise ValueError("used_messages must be a non-negative integer")


@dataclass(frozen=True, kw_only=True)
class CommunicationPolicy(JsonContract):
    schema_version: int
    policy_version: str
    edge_permissions: tuple[CommunicationEdgePermission, ...]

    def __post_init__(self) -> None:
        if self.schema_version != 1 or isinstance(self.schema_version, bool):
            raise ValueError("schema_version must be 1")
        _require_text(self.policy_version, "policy_version")
        permissions = tuple(
            sorted(
                self.edge_permissions,
                key=lambda item: (
                    item.sender_agent_id,
                    item.receiver_agent_id,
                ),
            )
        )
        if not permissions:
            raise ValueError("edge_permissions cannot be empty")
        if not all(
            isinstance(item, CommunicationEdgePermission)
            for item in permissions
        ):
            raise ValueError(
                "edge_permissions must contain CommunicationEdgePermission"
            )
        keys = tuple(
            (item.sender_agent_id, item.receiver_agent_id)
            for item in permissions
        )
        if len(keys) != len(set(keys)):
            raise ValueError("duplicate communication edge permissions")
        object.__setattr__(self, "edge_permissions", permissions)

    def permission_for(
        self,
        sender_agent_id: str,
        receiver_agent_id: str,
    ) -> CommunicationEdgePermission | None:
        for permission in self.edge_permissions:
            if (
                permission.sender_agent_id == sender_agent_id
                and permission.receiver_agent_id == receiver_agent_id
            ):
                return permission
        return None

    @classmethod
    def from_dict(cls, value: dict[str, object]) -> "CommunicationPolicy":
        payload = dict(value)
        payload["edge_permissions"] = tuple(
            CommunicationEdgePermission.from_dict(item)
            for item in payload["edge_permissions"]
        )
        return cls(**payload)


def _usage_map(
    edge_usage: tuple[CommunicationEdgeUsage, ...],
) -> dict[tuple[str, str], int]:
    usage: dict[tuple[str, str], int] = {}
    for item in edge_usage:
        key = (item.sender_agent_id, item.receiver_agent_id)
        if key in usage:
            raise CommunicationGovernanceError(
                "duplicate communication edge usage records"
            )
        usage[key] = item.used_messages
    return usage


def _validate_common(
    *,
    proposer_agent_id: str,
    observation_id: str,
    commitment_id: str,
    related_requirement_id: str,
    created_at: str,
    expires_at: str,
    observation: LocalFieldObservation,
    commitment: AgentCommitment,
    lifecycle: CommitmentLifecycleSnapshot,
    at: str,
    run_finalized: bool,
) -> str:
    if run_finalized:
        raise CommunicationGovernanceError(
            "cannot admit communication after run is finalized"
        )
    if lifecycle.commitment_id != commitment.commitment_id:
        raise CommunicationGovernanceError(
            "communication lifecycle commitment_id mismatch"
        )
    if lifecycle.status is not CommitmentStatus.ACTIVE:
        raise CommunicationGovernanceError("commitment is not active")
    if observation_id != observation.observation_id:
        raise CommunicationGovernanceError(
            "communication observation_id mismatch"
        )
    if proposer_agent_id != observation.agent_id:
        raise CommunicationGovernanceError(
            "communication proposer is outside observation audience"
        )
    if commitment_id != commitment.commitment_id:
        raise CommunicationGovernanceError(
            "communication commitment_id mismatch"
        )
    if proposer_agent_id != commitment.agent_id:
        raise CommunicationGovernanceError(
            "communication proposer does not own commitment"
        )
    if observation.task_id != commitment.task_id:
        raise CommunicationGovernanceError(
            "communication task_id does not match commitment"
        )
    if (
        observation.requirement_schema_version
        != commitment.requirement_schema_version
    ):
        raise CommunicationGovernanceError(
            "communication requirement schema version does not match"
        )
    if related_requirement_id not in commitment.accepted_scope:
        raise CommunicationGovernanceError(
            "communication requirement exceeds commitment scope"
        )
    if related_requirement_id not in observation.visible_requirement_signals:
        raise CommunicationGovernanceError(
            "communication requirement is outside observation visibility"
        )
    checked_at = _parse_timestamp(at, "at")
    proposal_created_at = _parse_timestamp(created_at, "created_at")
    if proposal_created_at < _parse_timestamp(
        commitment.created_at,
        "commitment created_at",
    ):
        raise CommunicationGovernanceError(
            "communication proposal predates commitment"
        )
    if checked_at < proposal_created_at:
        raise CommunicationGovernanceError(
            "communication cannot be admitted before proposal creation"
        )
    proposal_expiry = _parse_timestamp(expires_at, "expires_at")
    commitment_deadline = _parse_timestamp(commitment.deadline, "deadline")
    observation_expiry = _parse_timestamp(
        observation.expires_at,
        "observation expires_at",
    )
    if checked_at >= proposal_expiry:
        raise CommunicationGovernanceError(
            "communication proposal has expired"
        )
    if checked_at >= commitment_deadline:
        raise CommunicationGovernanceError("commitment has expired")
    if checked_at >= observation_expiry:
        raise CommunicationGovernanceError("observation has expired")
    return min(
        (
            (expires_at, proposal_expiry),
            (commitment.deadline, commitment_deadline),
            (observation.expires_at, observation_expiry),
        ),
        key=lambda item: item[1],
    )[0]


def _validate_edge(
    *,
    policy: CommunicationPolicy,
    usage: dict[tuple[str, str], int],
    sender_agent_id: str,
    receiver_agent_id: str,
    payload_schema: str,
    payload_bytes: int,
) -> None:
    permission = policy.permission_for(sender_agent_id, receiver_agent_id)
    if permission is None:
        raise CommunicationGovernanceError(
            "communication edge has no permission"
        )
    if payload_schema not in permission.allowed_payload_schemas:
        raise CommunicationGovernanceError(
            "communication payload schema is not allowed"
        )
    if payload_bytes > permission.max_payload_bytes:
        raise CommunicationGovernanceError(
            "communication payload exceeds byte permission"
        )
    if usage.get((sender_agent_id, receiver_agent_id), 0) >= (
        permission.max_messages
    ):
        raise CommunicationGovernanceError(
            "communication edge message quota is exhausted"
        )


def admit_communication_offer(
    *,
    offer: CommunicationOffer,
    observation: LocalFieldObservation,
    commitment: AgentCommitment,
    lifecycle: CommitmentLifecycleSnapshot,
    policy: CommunicationPolicy,
    edge_usage: tuple[CommunicationEdgeUsage, ...],
    at: str,
    run_finalized: bool,
) -> CommunicationPermit:
    permit_expiry = _validate_common(
        proposer_agent_id=offer.sender_agent_id,
        observation_id=offer.observation_id,
        commitment_id=offer.commitment_id,
        related_requirement_id=offer.related_requirement_id,
        created_at=offer.created_at,
        expires_at=offer.expires_at,
        observation=observation,
        commitment=commitment,
        lifecycle=lifecycle,
        at=at,
        run_finalized=run_finalized,
    )
    usage = _usage_map(tuple(edge_usage))
    for receiver in offer.intended_audience:
        _validate_edge(
            policy=policy,
            usage=usage,
            sender_agent_id=offer.sender_agent_id,
            receiver_agent_id=receiver,
            payload_schema=offer.payload_schema,
            payload_bytes=offer.payload_size_bytes,
        )
    return _permit(
        proposal_kind="offer",
        related_proposal_id=offer.offer_id,
        commitment=commitment,
        requirement_id=offer.related_requirement_id,
        sender_agent_id=offer.sender_agent_id,
        receiver_agent_ids=offer.intended_audience,
        payload_schema=offer.payload_schema,
        payload_bytes=offer.payload_size_bytes,
        policy=policy,
        lifecycle=lifecycle,
        proposal=offer,
        at=at,
        expiry=permit_expiry,
        edge_usage=edge_usage,
        run_finalized=run_finalized,
    )


def admit_communication_request(
    *,
    request: CommunicationRequest,
    observation: LocalFieldObservation,
    commitment: AgentCommitment,
    lifecycle: CommitmentLifecycleSnapshot,
    policy: CommunicationPolicy,
    edge_usage: tuple[CommunicationEdgeUsage, ...],
    at: str,
    run_finalized: bool,
) -> CommunicationPermit:
    permit_expiry = _validate_common(
        proposer_agent_id=request.requester_agent_id,
        observation_id=request.observation_id,
        commitment_id=request.commitment_id,
        related_requirement_id=request.related_requirement_id,
        created_at=request.created_at,
        expires_at=request.expires_at,
        observation=observation,
        commitment=commitment,
        lifecycle=lifecycle,
        at=at,
        run_finalized=run_finalized,
    )
    usage = _usage_map(tuple(edge_usage))
    _validate_edge(
        policy=policy,
        usage=usage,
        sender_agent_id=request.intended_sender_agent_id,
        receiver_agent_id=request.requester_agent_id,
        payload_schema=request.requested_payload_schema,
        payload_bytes=request.max_payload_bytes,
    )
    return _permit(
        proposal_kind="request",
        related_proposal_id=request.request_id,
        commitment=commitment,
        requirement_id=request.related_requirement_id,
        sender_agent_id=request.intended_sender_agent_id,
        receiver_agent_ids=(request.requester_agent_id,),
        payload_schema=request.requested_payload_schema,
        payload_bytes=request.max_payload_bytes,
        policy=policy,
        lifecycle=lifecycle,
        proposal=request,
        at=at,
        expiry=permit_expiry,
        edge_usage=edge_usage,
        run_finalized=run_finalized,
    )


def _permit(
    *,
    proposal_kind: str,
    related_proposal_id: str,
    commitment: AgentCommitment,
    requirement_id: str,
    sender_agent_id: str,
    receiver_agent_ids: tuple[str, ...],
    payload_schema: str,
    payload_bytes: int,
    policy: CommunicationPolicy,
    lifecycle: CommitmentLifecycleSnapshot,
    proposal: CommunicationOffer | CommunicationRequest,
    at: str,
    expiry: str,
    edge_usage: tuple[CommunicationEdgeUsage, ...],
    run_finalized: bool,
) -> CommunicationPermit:
    digest = _stable_digest(
        {
            "at": at,
            "commitment": commitment.to_dict(),
            "edge_usage": [item.to_dict() for item in edge_usage],
            "lifecycle": lifecycle.to_dict(),
            "policy": policy.to_dict(),
            "proposal": proposal.to_dict(),
            "run_finalized": run_finalized,
        }
    )
    return CommunicationPermit(
        schema_version=1,
        permit_id=f"communication-permit-{digest}",
        policy_version=policy.policy_version,
        proposal_kind=proposal_kind,
        related_proposal_id=related_proposal_id,
        commitment_id=commitment.commitment_id,
        related_requirement_id=requirement_id,
        sender_agent_id=sender_agent_id,
        receiver_agent_ids=receiver_agent_ids,
        payload_schema=payload_schema,
        max_payload_bytes=payload_bytes,
        message_quota=1,
        created_at=at,
        expires_at=expiry,
        causal_parent_ids=(
            commitment.commitment_id,
            related_proposal_id,
        ),
        issuer=GovernanceIssuer.HARNESS_ADMISSION,
    )


def _validate_permit_time(permit: CommunicationPermit, at: str) -> datetime:
    checked_at = _parse_timestamp(at, "at")
    if checked_at < _parse_timestamp(permit.created_at, "permit created_at"):
        raise CommunicationGovernanceError(
            "communication cannot precede permit creation"
        )
    if checked_at >= _parse_timestamp(permit.expires_at, "permit expires_at"):
        raise CommunicationGovernanceError("communication permit has expired")
    return checked_at


def _validate_delivery_binding(
    permit: CommunicationPermit,
    delivery: CommunicationDelivery,
) -> None:
    if delivery.permit_id != permit.permit_id:
        raise CommunicationGovernanceError("delivery permit mismatch")
    if delivery.commitment_id != permit.commitment_id:
        raise CommunicationGovernanceError("delivery commitment mismatch")
    if delivery.sender_agent_id != permit.sender_agent_id:
        raise CommunicationGovernanceError("delivery sender exceeds permit")
    if delivery.receiver_agent_id not in permit.receiver_agent_ids:
        raise CommunicationGovernanceError("delivery receiver exceeds permit")
    if delivery.payload_schema != permit.payload_schema:
        raise CommunicationGovernanceError(
            "delivery payload schema exceeds permit"
        )
    if delivery.payload_size_bytes > permit.max_payload_bytes:
        raise CommunicationGovernanceError(
            "delivery payload exceeds byte permit"
        )
    if delivery.message_count > permit.message_quota:
        raise CommunicationGovernanceError(
            "delivery exceeds message permit"
        )


def deliver_communication(
    *,
    permit: CommunicationPermit,
    sender_agent_id: str,
    receiver_agent_id: str,
    payload_schema: str,
    payload: bytes,
    message_count: int,
    resource_cost: tuple[ResourceAmount, ...],
    at: str,
) -> CommunicationDelivery:
    """Materialize one bounded delivery from a Harness-issued permit."""

    _validate_permit_time(permit, at)
    if sender_agent_id != permit.sender_agent_id:
        raise CommunicationGovernanceError("delivery sender exceeds permit")
    if receiver_agent_id not in permit.receiver_agent_ids:
        raise CommunicationGovernanceError("delivery receiver exceeds permit")
    if payload_schema != permit.payload_schema:
        raise CommunicationGovernanceError(
            "delivery payload schema exceeds permit"
        )
    if not isinstance(payload, bytes) or not payload:
        raise CommunicationGovernanceError(
            "delivery payload must be non-empty bytes"
        )
    if len(payload) > permit.max_payload_bytes:
        raise CommunicationGovernanceError(
            "delivery payload exceeds byte permit"
        )
    if (
        isinstance(message_count, bool)
        or not isinstance(message_count, int)
        or message_count <= 0
        or message_count > permit.message_quota
    ):
        raise CommunicationGovernanceError(
            "delivery exceeds message permit"
        )
    normalized_cost = _validate_resource_cost(resource_cost)
    payload_sha256 = hashlib.sha256(payload).hexdigest()
    digest = _stable_digest(
        {
            "at": at,
            "message_count": message_count,
            "payload_sha256": payload_sha256,
            "payload_size_bytes": len(payload),
            "permit": permit.to_dict(),
            "receiver_agent_id": receiver_agent_id,
            "resource_cost": [
                item.to_dict() for item in normalized_cost
            ],
            "sender_agent_id": sender_agent_id,
        }
    )
    delivery = CommunicationDelivery(
        delivery_id=f"communication-delivery-{digest}",
        permit_id=permit.permit_id,
        commitment_id=permit.commitment_id,
        sender_agent_id=sender_agent_id,
        receiver_agent_id=receiver_agent_id,
        payload_schema=payload_schema,
        payload_sha256=payload_sha256,
        payload_size_bytes=len(payload),
        message_count=message_count,
        resource_cost=normalized_cost,
        delivered_at=at,
        causal_parent_ids=(permit.permit_id,),
        issuer=CommunicationRuntimeIssuer.HARNESS_TRANSPORT,
    )
    _validate_delivery_binding(permit, delivery)
    return delivery


def record_communication_receipt(
    *,
    permit: CommunicationPermit,
    delivery: CommunicationDelivery,
    receiver_agent_id: str,
    at: str,
) -> CommunicationReceipt:
    """Record transport-level receipt; the receiver cannot mint this proof."""

    received_at = _validate_permit_time(permit, at)
    _validate_delivery_binding(permit, delivery)
    if receiver_agent_id != delivery.receiver_agent_id:
        raise CommunicationGovernanceError("receipt receiver mismatch")
    if received_at < _parse_timestamp(delivery.delivered_at, "delivered_at"):
        raise CommunicationGovernanceError("receipt predates delivery")
    digest = _stable_digest(
        {
            "at": at,
            "delivery": delivery.to_dict(),
            "permit_id": permit.permit_id,
            "receiver_agent_id": receiver_agent_id,
        }
    )
    return CommunicationReceipt(
        receipt_id=f"communication-receipt-{digest}",
        delivery_id=delivery.delivery_id,
        permit_id=permit.permit_id,
        receiver_agent_id=receiver_agent_id,
        payload_sha256=delivery.payload_sha256,
        received_at=at,
        causal_parent_ids=(delivery.delivery_id,),
        issuer=CommunicationRuntimeIssuer.HARNESS_TRANSPORT,
    )


def consume_communication(
    *,
    permit: CommunicationPermit,
    delivery: CommunicationDelivery,
    receipt: CommunicationReceipt,
    consumer_agent_id: str,
    consumed_receipt_ids: tuple[str, ...],
    at: str,
) -> CommunicationConsumption:
    """Consume exactly one authentic receipt and return a public proof."""

    consumed_at = _validate_permit_time(permit, at)
    _validate_delivery_binding(permit, delivery)
    if receipt.receipt_id in set(consumed_receipt_ids):
        raise CommunicationGovernanceError(
            "communication receipt was already consumed"
        )
    if consumer_agent_id != delivery.receiver_agent_id:
        raise CommunicationGovernanceError("communication consumer mismatch")
    expected_receipt = record_communication_receipt(
        permit=permit,
        delivery=delivery,
        receiver_agent_id=delivery.receiver_agent_id,
        at=receipt.received_at,
    )
    if receipt != expected_receipt:
        raise CommunicationGovernanceError(
            "communication receipt is forged or inconsistent"
        )
    if consumed_at < _parse_timestamp(receipt.received_at, "received_at"):
        raise CommunicationGovernanceError("consumption predates receipt")
    digest = _stable_digest(
        {
            "at": at,
            "delivery_id": delivery.delivery_id,
            "permit_id": permit.permit_id,
            "receipt": receipt.to_dict(),
            "consumer_agent_id": consumer_agent_id,
        }
    )
    return CommunicationConsumption(
        consumption_id=f"communication-consumption-{digest}",
        receipt_id=receipt.receipt_id,
        delivery_id=delivery.delivery_id,
        permit_id=permit.permit_id,
        consumer_agent_id=consumer_agent_id,
        payload_sha256=delivery.payload_sha256,
        consumed_at=at,
        causal_parent_ids=(receipt.receipt_id,),
        issuer=CommunicationRuntimeIssuer.HARNESS_CONSUMER,
    )
