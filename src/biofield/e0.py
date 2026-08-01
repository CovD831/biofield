from __future__ import annotations

import json
import os
import tempfile
from collections.abc import Callable, Iterable, Mapping
from dataclasses import dataclass
from decimal import Decimal
from hashlib import sha256
from pathlib import Path
from types import MappingProxyType
from typing import Any

from .contracts import (
    DependencyKind,
    FeedbackDisposition,
    FeedbackEvent,
    FeedbackSourceKind,
    ClaimAuthority,
    RequirementDelta,
    RequirementDependency,
    RequirementSpec,
    ResourceEvent,
    ResourceLimit,
    ResourceOperation,
    RunTerminalStatus,
    TaskSpec,
)
from .evidence_task import (
    EvidenceTaskBundle,
    EvidenceTaskError,
    f0_requirement_disposition,
    f0_verifier_binding,
    load_task_bundle,
)
from .ledger import ResourceLedger, SHARED_POOL
from .residual import ResidualStateMachine


PUBLIC_EVENT_SCHEMA_VERSION = 1
PUBLIC_REPLAY_CHECKPOINT_SCHEMA_VERSION = 1
_TERMINAL_EVENT_TYPE = "run_terminal"


def _canonical_json(value: Any) -> str:
    try:
        return json.dumps(
            value,
            allow_nan=False,
            ensure_ascii=False,
            separators=(",", ":"),
            sort_keys=True,
        )
    except (TypeError, ValueError) as error:
        raise ValueError("value must be finite JSON") from error


def _freeze_json(value: Any) -> Any:
    if isinstance(value, Mapping):
        return MappingProxyType(
            {str(key): _freeze_json(item) for key, item in value.items()}
        )
    if isinstance(value, (list, tuple)):
        return tuple(_freeze_json(item) for item in value)
    return value


def _thaw_json(value: Any) -> Any:
    if isinstance(value, Mapping):
        return {str(key): _thaw_json(item) for key, item in value.items()}
    if isinstance(value, tuple):
        return [_thaw_json(item) for item in value]
    return value


def _require_text(value: object, field_name: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{field_name} must be a non-empty string")
    return value


def _require_sha256(value: object, field_name: str) -> str:
    digest = _require_text(value, field_name)
    if len(digest) != 64 or any(character not in "0123456789abcdef" for character in digest):
        raise ValueError(f"{field_name} must be a lowercase SHA-256 digest")
    return digest


@dataclass(frozen=True, kw_only=True)
class PublicEvent:
    """Versioned event consumed by the deterministic public-state projector."""

    schema_version: int
    event_id: str
    event_type: str
    sequence: int
    causal_parent_ids: tuple[str, ...]
    payload: Mapping[str, Any]

    def __post_init__(self) -> None:
        object.__setattr__(self, "causal_parent_ids", tuple(self.causal_parent_ids))
        if self.schema_version != PUBLIC_EVENT_SCHEMA_VERSION:
            raise ValueError(
                "schema_version must equal "
                f"{PUBLIC_EVENT_SCHEMA_VERSION}; version jumps are not accepted"
            )
        _require_text(self.event_id, "event_id")
        _require_text(self.event_type, "event_type")
        if (
            isinstance(self.sequence, bool)
            or not isinstance(self.sequence, int)
            or self.sequence < 0
        ):
            raise ValueError("sequence must be a non-negative integer")
        if not all(
            isinstance(parent_id, str) and parent_id.strip()
            for parent_id in self.causal_parent_ids
        ):
            raise ValueError("causal_parent_ids must contain non-empty strings")
        if len(set(self.causal_parent_ids)) != len(self.causal_parent_ids):
            raise ValueError("causal_parent_ids must be unique")
        if self.event_id in self.causal_parent_ids:
            raise ValueError("an event cannot be its own causal parent")
        if not isinstance(self.payload, Mapping):
            raise ValueError("payload must be a mapping")
        # Canonical JSON round-tripping both validates the payload and detaches
        # every nested container from caller-owned mutable input before freezing.
        detached_payload = json.loads(_canonical_json(dict(self.payload)))
        object.__setattr__(self, "payload", _freeze_json(detached_payload))

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "event_id": self.event_id,
            "event_type": self.event_type,
            "sequence": self.sequence,
            "causal_parent_ids": list(self.causal_parent_ids),
            "payload": _thaw_json(self.payload),
        }

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> PublicEvent:
        if not isinstance(value, Mapping):
            raise ValueError("public event must be a mapping")
        try:
            return cls(
                schema_version=value["schema_version"],
                event_id=value["event_id"],
                event_type=value["event_type"],
                sequence=value["sequence"],
                causal_parent_ids=tuple(value["causal_parent_ids"]),
                payload=value["payload"],
            )
        except (KeyError, TypeError) as error:
            raise ValueError("public event is missing required fields") from error

    @property
    def fingerprint(self) -> str:
        return sha256(_canonical_json(self.to_dict()).encode("utf-8")).hexdigest()


class PublicEventReplayError(RuntimeError):
    """Fail-closed replay error with stable fields for machine consumers."""

    def __init__(
        self,
        code: str,
        message: str,
        *,
        event_id: str | None = None,
        input_index: int | None = None,
    ) -> None:
        super().__init__(message)
        self.code = code
        self.event_id = event_id
        self.input_index = input_index

    def to_dict(self) -> dict[str, Any]:
        return {
            "code": self.code,
            "message": str(self),
            "event_id": self.event_id,
            "input_index": self.input_index,
        }


EventMigrator = Callable[
    [dict[str, Any], dict[str, Any]],
    Mapping[str, Any],
]


@dataclass(frozen=True)
class PublicEventMigrationOutcome:
    events: tuple[PublicEvent, ...]
    source_schema_versions: tuple[int, ...]
    primitive_semantics_preserved: bool


@dataclass(frozen=True)
class _MigrationRule:
    migrator: EventMigrator
    primitive_semantics_preserved: bool


def _identity_event_migrator(
    record: dict[str, Any],
    context: dict[str, Any],
) -> Mapping[str, Any]:
    del context
    return record


def _legacy_event_migrator(
    record: dict[str, Any],
    context: dict[str, Any],
) -> Mapping[str, Any]:
    return {
        "schema_version": PUBLIC_EVENT_SCHEMA_VERSION,
        "event_id": f"{context['event_id_prefix']}{record['event_id']}",
        "event_type": record["event_type"],
        "sequence": context["sequence"],
        "causal_parent_ids": list(context["causal_parent_ids"]),
        "payload": {
            "source_cycle": record.get("cycle"),
            "data": record.get("payload", {}),
        },
    }


class PublicEventMigrationRegistry:
    """Explicit deterministic migrations into the current PublicEvent form."""

    def __init__(self) -> None:
        self._rules: dict[int, _MigrationRule] = {}

    @classmethod
    def default(cls) -> PublicEventMigrationRegistry:
        registry = cls()
        registry.register(
            0,
            _legacy_event_migrator,
            primitive_semantics_preserved=False,
        )
        registry.register(
            PUBLIC_EVENT_SCHEMA_VERSION,
            _identity_event_migrator,
            primitive_semantics_preserved=True,
        )
        return registry

    def register(
        self,
        source_schema_version: int,
        migrator: EventMigrator,
        *,
        primitive_semantics_preserved: bool,
    ) -> None:
        if (
            isinstance(source_schema_version, bool)
            or not isinstance(source_schema_version, int)
            or source_schema_version < 0
            or not callable(migrator)
            or not isinstance(primitive_semantics_preserved, bool)
        ):
            raise ValueError("migration registration is invalid")
        if source_schema_version in self._rules:
            raise ValueError("migration source version is already registered")
        self._rules[source_schema_version] = _MigrationRule(
            migrator=migrator,
            primitive_semantics_preserved=primitive_semantics_preserved,
        )

    def migrate_stream(
        self,
        records: Iterable[Mapping[str, Any]],
        *,
        sequence_offset: int = 0,
        initial_parent_id: str | None = None,
        event_id_prefix: str = "",
        expected_event_fingerprints: Mapping[str, str] | None = None,
    ) -> PublicEventMigrationOutcome:
        if (
            isinstance(sequence_offset, bool)
            or not isinstance(sequence_offset, int)
            or sequence_offset < 0
        ):
            raise ValueError("sequence_offset must be a non-negative integer")
        if initial_parent_id is not None:
            _require_text(initial_parent_id, "initial_parent_id")
        if not isinstance(event_id_prefix, str):
            raise ValueError("event_id_prefix must be a string")

        migrated_events: list[PublicEvent] = []
        source_versions: list[int] = []
        semantics_preserved = True
        for index, source_record in enumerate(records):
            if not isinstance(source_record, Mapping):
                raise PublicEventReplayError(
                    "invalid_migration_input",
                    "event migration input must contain mappings",
                    input_index=index,
                )
            record = json.loads(_canonical_json(dict(source_record)))
            source_version = record.get("schema_version", 0)
            if isinstance(source_version, bool) or not isinstance(
                source_version, int
            ):
                raise PublicEventReplayError(
                    "unknown_event_schema",
                    "event schema_version must be an integer",
                    event_id=record.get("event_id"),
                    input_index=index,
                )
            rule = self._rules.get(source_version)
            if rule is None:
                raise PublicEventReplayError(
                    "unknown_event_schema",
                    f"no migration is registered for schema_version {source_version}",
                    event_id=record.get("event_id"),
                    input_index=index,
                )
            sequence = sequence_offset + len(migrated_events)
            if migrated_events:
                default_parents = (migrated_events[-1].event_id,)
            elif initial_parent_id is not None:
                default_parents = (initial_parent_id,)
            else:
                default_parents = ()
            context = {
                "sequence": sequence,
                "causal_parent_ids": list(default_parents),
                "event_id_prefix": event_id_prefix,
            }
            try:
                first = dict(
                    rule.migrator(
                        json.loads(_canonical_json(record)),
                        json.loads(_canonical_json(context)),
                    )
                )
                second = dict(
                    rule.migrator(
                        json.loads(_canonical_json(record)),
                        json.loads(_canonical_json(context)),
                    )
                )
            except Exception as error:
                raise PublicEventReplayError(
                    "migration_failed",
                    f"event migration failed: {error}",
                    event_id=record.get("event_id"),
                    input_index=index,
                ) from error
            if _canonical_json(first) != _canonical_json(second):
                raise PublicEventReplayError(
                    "non_idempotent_migration",
                    "event migration produced different canonical outputs",
                    event_id=record.get("event_id"),
                    input_index=index,
                )
            if source_version == PUBLIC_EVENT_SCHEMA_VERSION and _canonical_json(
                first
            ) != _canonical_json(record):
                raise PublicEventReplayError(
                    "non_idempotent_migration",
                    "canonical event migration must be identity",
                    event_id=record.get("event_id"),
                    input_index=index,
                )
            if source_version == PUBLIC_EVENT_SCHEMA_VERSION and set(record) != {
                "schema_version",
                "event_id",
                "event_type",
                "sequence",
                "causal_parent_ids",
                "payload",
            }:
                raise PublicEventReplayError(
                    "migration_failed",
                    "canonical event contains missing or unbound fields",
                    event_id=record.get("event_id"),
                    input_index=index,
                )
            try:
                event = PublicEvent.from_dict(first)
            except ValueError as error:
                raise PublicEventReplayError(
                    "migration_failed",
                    str(error),
                    event_id=record.get("event_id"),
                    input_index=index,
                ) from error
            if event.sequence != sequence:
                raise PublicEventReplayError(
                    "migration_causal_integrity",
                    "migration changed the expected event sequence",
                    event_id=event.event_id,
                    input_index=index,
                )
            migrated_events.append(event)
            source_versions.append(source_version)
            semantics_preserved = (
                semantics_preserved and rule.primitive_semantics_preserved
            )

        known_parent_ids = (
            {initial_parent_id} if initial_parent_id is not None else set()
        )
        terminal_seen = False
        known_event_ids: set[str] = set()
        for index, event in enumerate(migrated_events):
            if event.sequence != sequence_offset + index:
                raise PublicEventReplayError(
                    "migration_causal_integrity",
                    "migrated stream contains a sequence gap",
                    event_id=event.event_id,
                    input_index=index,
                )
            if terminal_seen or any(
                parent_id not in known_parent_ids
                for parent_id in event.causal_parent_ids
            ):
                raise PublicEventReplayError(
                    "migration_causal_integrity",
                    "migrated stream contains an invalid parent or terminal suffix",
                    event_id=event.event_id,
                    input_index=index,
                )
            if event.event_id in known_event_ids:
                raise PublicEventReplayError(
                    "migration_causal_integrity",
                    "migrated stream contains a duplicate event ID",
                    event_id=event.event_id,
                    input_index=index,
                )
            known_event_ids.add(event.event_id)
            known_parent_ids.add(event.event_id)
            terminal_seen = event.event_type == _TERMINAL_EVENT_TYPE

        if sequence_offset == 0 and initial_parent_id is None:
            try:
                PublicEventReplayer.replay(migrated_events)
            except PublicEventReplayError as error:
                raise PublicEventReplayError(
                    "migration_causal_integrity",
                    f"migrated stream is not replayable: {error}",
                    event_id=error.event_id,
                    input_index=error.input_index,
                ) from error

        if expected_event_fingerprints is not None:
            for event in migrated_events:
                expected = expected_event_fingerprints.get(event.event_id)
                if expected is None or expected != event.fingerprint:
                    raise PublicEventReplayError(
                        "migration_hash_mismatch",
                        "migrated event fingerprint differs from expectation",
                        event_id=event.event_id,
                    )
        return PublicEventMigrationOutcome(
            events=tuple(migrated_events),
            source_schema_versions=tuple(sorted(set(source_versions))),
            primitive_semantics_preserved=semantics_preserved,
        )


def _checkpoint_content(
    *,
    applied_event_ids: tuple[str, ...],
    applied_event_fingerprints: tuple[str, ...],
    next_sequence: int,
    terminal_status: str | None,
    source_final_state_sha256: str | None,
) -> dict[str, Any]:
    return {
        "checkpoint_schema_version": PUBLIC_REPLAY_CHECKPOINT_SCHEMA_VERSION,
        "public_event_schema_version": PUBLIC_EVENT_SCHEMA_VERSION,
        "applied_event_ids": list(applied_event_ids),
        "applied_event_fingerprints": list(applied_event_fingerprints),
        "next_sequence": next_sequence,
        "terminal_status": terminal_status,
        "source_final_state_sha256": source_final_state_sha256,
    }


def _checkpoint_sha256(
    *,
    applied_event_ids: tuple[str, ...],
    applied_event_fingerprints: tuple[str, ...],
    next_sequence: int,
    terminal_status: str | None,
    source_final_state_sha256: str | None,
) -> str:
    content = _checkpoint_content(
        applied_event_ids=applied_event_ids,
        applied_event_fingerprints=applied_event_fingerprints,
        next_sequence=next_sequence,
        terminal_status=terminal_status,
        source_final_state_sha256=source_final_state_sha256,
    )
    return sha256(_canonical_json(content).encode("utf-8")).hexdigest()


@dataclass(frozen=True, kw_only=True)
class PublicReplayCheckpoint:
    """Immutable, content-addressed replay cursor.

    The checkpoint stores the immutable public events required to reproduce the
    same projection. Its digest binds the ordered event IDs/fingerprints, next
    sequence, and terminal fields; it does not claim equality with the legacy
    F0 internal final-state hash.
    """

    checkpoint_schema_version: int
    public_event_schema_version: int
    applied_events: tuple[PublicEvent, ...]
    applied_event_ids: tuple[str, ...]
    applied_event_fingerprints: tuple[str, ...]
    next_sequence: int
    terminal_status: str | None
    source_final_state_sha256: str | None
    checkpoint_sha256: str

    def __post_init__(self) -> None:
        for field_name in (
            "applied_events",
            "applied_event_ids",
            "applied_event_fingerprints",
        ):
            object.__setattr__(self, field_name, tuple(getattr(self, field_name)))
        if (
            self.checkpoint_schema_version
            != PUBLIC_REPLAY_CHECKPOINT_SCHEMA_VERSION
        ):
            raise PublicEventReplayError(
                "invalid_checkpoint",
                "unsupported checkpoint_schema_version",
            )
        if self.public_event_schema_version != PUBLIC_EVENT_SCHEMA_VERSION:
            raise PublicEventReplayError(
                "invalid_checkpoint",
                "checkpoint public_event_schema_version does not match replay",
            )
        try:
            _require_sha256(self.checkpoint_sha256, "checkpoint_sha256")
        except ValueError as error:
            raise PublicEventReplayError(
                "checkpoint_hash_mismatch",
                str(error),
            ) from error

        expected_checkpoint_sha256 = _checkpoint_sha256(
            applied_event_ids=self.applied_event_ids,
            applied_event_fingerprints=self.applied_event_fingerprints,
            next_sequence=self.next_sequence,
            terminal_status=self.terminal_status,
            source_final_state_sha256=self.source_final_state_sha256,
        )
        if self.checkpoint_sha256 != expected_checkpoint_sha256:
            raise PublicEventReplayError(
                "checkpoint_hash_mismatch",
                "checkpoint content does not match checkpoint_sha256",
            )

        if not all(isinstance(event, PublicEvent) for event in self.applied_events):
            raise PublicEventReplayError(
                "checkpoint_event_mismatch",
                "applied_events must contain PublicEvent values",
            )
        expected_ids = tuple(event.event_id for event in self.applied_events)
        expected_fingerprints = tuple(
            event.fingerprint for event in self.applied_events
        )
        if (
            self.applied_event_ids != expected_ids
            or self.applied_event_fingerprints != expected_fingerprints
            or self.next_sequence != len(self.applied_events)
        ):
            raise PublicEventReplayError(
                "checkpoint_event_mismatch",
                "checkpoint events do not match IDs, fingerprints, or next sequence",
            )

    def to_dict(self) -> dict[str, Any]:
        return {
            **_checkpoint_content(
                applied_event_ids=self.applied_event_ids,
                applied_event_fingerprints=self.applied_event_fingerprints,
                next_sequence=self.next_sequence,
                terminal_status=self.terminal_status,
                source_final_state_sha256=self.source_final_state_sha256,
            ),
            "applied_events": [event.to_dict() for event in self.applied_events],
            "checkpoint_sha256": self.checkpoint_sha256,
        }

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> PublicReplayCheckpoint:
        if not isinstance(value, Mapping):
            raise PublicEventReplayError(
                "invalid_checkpoint",
                "checkpoint must be a mapping",
            )
        try:
            raw_events = value["applied_events"]
            if not isinstance(raw_events, (list, tuple)):
                raise TypeError
            events = tuple(PublicEvent.from_dict(event) for event in raw_events)
            return cls(
                checkpoint_schema_version=value["checkpoint_schema_version"],
                public_event_schema_version=value["public_event_schema_version"],
                applied_events=events,
                applied_event_ids=tuple(value["applied_event_ids"]),
                applied_event_fingerprints=tuple(
                    value["applied_event_fingerprints"]
                ),
                next_sequence=value["next_sequence"],
                terminal_status=value["terminal_status"],
                source_final_state_sha256=value["source_final_state_sha256"],
                checkpoint_sha256=value["checkpoint_sha256"],
            )
        except PublicEventReplayError:
            raise
        except (KeyError, TypeError, ValueError) as error:
            raise PublicEventReplayError(
                "invalid_checkpoint",
                "checkpoint is missing or has invalid fields",
            ) from error


class CheckpointPersistenceError(RuntimeError):
    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code


class CheckpointExistsError(CheckpointPersistenceError, FileExistsError):
    def __init__(self, message: str) -> None:
        super().__init__("checkpoint_exists", message)


@dataclass(frozen=True)
class CheckpointPersistenceReceipt:
    path: Path
    file_sha256: str


class PublicReplayCheckpointStore:
    FORMAT = "biofield.public-replay-checkpoint"
    FORMAT_VERSION = 1

    @staticmethod
    def _fsync_directory(directory: Path) -> None:
        flags = os.O_RDONLY | getattr(os, "O_DIRECTORY", 0)
        try:
            descriptor = os.open(directory, flags)
        except OSError as error:
            raise CheckpointPersistenceError(
                "checkpoint_publish_error",
                f"cannot open checkpoint directory {directory} for fsync",
            ) from error
        try:
            os.fsync(descriptor)
        except OSError as error:
            raise CheckpointPersistenceError(
                "checkpoint_publish_error",
                f"cannot fsync checkpoint directory {directory}",
            ) from error
        finally:
            os.close(descriptor)

    @staticmethod
    def _is_unpublished_temporary_path(path: Path) -> bool:
        return path.name.startswith(".") and path.name.endswith(".tmp")

    @classmethod
    def write(
        cls,
        path: str | os.PathLike[str],
        checkpoint: PublicReplayCheckpoint,
    ) -> CheckpointPersistenceReceipt:
        if not isinstance(checkpoint, PublicReplayCheckpoint):
            raise TypeError("checkpoint must be a PublicReplayCheckpoint")
        destination = Path(path)
        if not destination.name or destination.name in {".", ".."}:
            raise CheckpointPersistenceError(
                "invalid_checkpoint_path",
                "checkpoint path must name a file",
            )
        parent = destination.parent
        if not parent.is_dir():
            raise CheckpointPersistenceError(
                "invalid_checkpoint_path",
                "checkpoint parent directory must already exist",
            )

        # Round-trip through the public validator before persisting.
        validated = PublicReplayCheckpoint.from_dict(checkpoint.to_dict())
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

        temporary_descriptor, temporary_name = tempfile.mkstemp(
            dir=parent,
            prefix=f".{destination.name}.",
            suffix=".tmp",
        )
        temporary_path = Path(temporary_name)
        reserved = False
        published = False
        try:
            with os.fdopen(temporary_descriptor, "wb") as handle:
                handle.write(file_bytes)
                handle.flush()
                os.fsync(handle.fileno())
            try:
                reservation_descriptor = os.open(
                    destination,
                    os.O_WRONLY | os.O_CREAT | os.O_EXCL,
                    0o600,
                )
            except FileExistsError as error:
                raise CheckpointExistsError(
                    f"checkpoint {destination} already exists"
                ) from error
            else:
                os.close(reservation_descriptor)
                reserved = True
            try:
                os.replace(temporary_path, destination)
            except OSError as error:
                raise CheckpointPersistenceError(
                    "checkpoint_publish_error",
                    f"cannot atomically publish checkpoint {destination}",
                ) from error
            published = True
            cls._fsync_directory(parent)
        finally:
            temporary_path.unlink(missing_ok=True)
            if reserved and not published:
                destination.unlink(missing_ok=True)
        return CheckpointPersistenceReceipt(
            path=destination,
            file_sha256=file_sha256,
        )

    @classmethod
    def load(
        cls,
        path: str | os.PathLike[str],
        *,
        expected_file_sha256: str | None = None,
    ) -> PublicReplayCheckpoint:
        source = Path(path)
        if cls._is_unpublished_temporary_path(source):
            raise CheckpointPersistenceError(
                "unpublished_checkpoint",
                f"temporary checkpoint {source} has not been atomically published",
            )
        try:
            file_bytes = source.read_bytes()
        except OSError as error:
            raise CheckpointPersistenceError(
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
            except ValueError as error:
                raise CheckpointPersistenceError(
                    "checkpoint_file_hash_mismatch",
                    str(error),
                ) from error
            if actual_file_sha256 != expected:
                raise CheckpointPersistenceError(
                    "checkpoint_file_hash_mismatch",
                    "checkpoint file bytes do not match expected SHA-256",
                )
        try:
            envelope = json.loads(file_bytes)
        except (UnicodeDecodeError, json.JSONDecodeError) as error:
            raise CheckpointPersistenceError(
                "checkpoint_content_hash_mismatch",
                "checkpoint file is not valid UTF-8 JSON",
            ) from error
        if not isinstance(envelope, dict):
            raise CheckpointPersistenceError(
                "checkpoint_content_hash_mismatch",
                "checkpoint envelope must be an object",
            )
        if set(envelope) != {
            "format",
            "format_version",
            "checkpoint",
            "content_sha256",
        }:
            raise CheckpointPersistenceError(
                "checkpoint_content_hash_mismatch",
                "checkpoint envelope contains missing or unbound fields",
            )
        declared_content_sha256 = envelope.get("content_sha256")
        content = {
            "format": envelope.get("format"),
            "format_version": envelope.get("format_version"),
            "checkpoint": envelope.get("checkpoint"),
        }
        try:
            declared = _require_sha256(
                declared_content_sha256,
                "content_sha256",
            )
        except ValueError as error:
            raise CheckpointPersistenceError(
                "checkpoint_content_hash_mismatch",
                str(error),
            ) from error
        computed = sha256(_canonical_json(content).encode("utf-8")).hexdigest()
        if (
            declared != computed
            or content["format"] != cls.FORMAT
            or content["format_version"] != cls.FORMAT_VERSION
        ):
            raise CheckpointPersistenceError(
                "checkpoint_content_hash_mismatch",
                "checkpoint envelope content hash or format is invalid",
            )
        try:
            return PublicReplayCheckpoint.from_dict(content["checkpoint"])
        except (PublicEventReplayError, TypeError, ValueError) as error:
            raise CheckpointPersistenceError(
                "checkpoint_payload_invalid",
                f"checkpoint payload failed validation: {error}",
            ) from error


@dataclass(frozen=True)
class PublicReplayResult:
    applied_event_count: int
    applied_event_ids: tuple[str, ...]
    terminal: bool
    terminal_status: str | None
    source_final_state_sha256: str | None
    public_terminal_projection: Mapping[str, Any] | None
    public_terminal_projection_sha256: str | None
    primitive_replay_verified: bool
    evidence_feedback_verified: bool
    final_state_sha256: str

    def public_terminal_projection_to_dict(self) -> dict[str, Any] | None:
        if self.public_terminal_projection is None:
            return None
        return _thaw_json(self.public_terminal_projection)


def _task_spec_from_dict(value: Mapping[str, Any]) -> TaskSpec:
    return TaskSpec(
        task_id=value["task_id"],
        requirement_schema_version=value["requirement_schema_version"],
        goal=value["goal"],
        requirements=tuple(
            RequirementSpec(
                requirement_id=item["requirement_id"],
                description=item["description"],
                required=item["required"],
            )
            for item in value["requirements"]
        ),
        requirement_dependencies=tuple(
            RequirementDependency(
                requirement_id=item["requirement_id"],
                depends_on_requirement_id=item["depends_on_requirement_id"],
                kind=DependencyKind(item["kind"]),
            )
            for item in value["requirement_dependencies"]
        ),
        constraints=tuple(value["constraints"]),
        acceptance_rules=tuple(value["acceptance_rules"]),
        resource_limits=tuple(
            ResourceLimit(
                resource_type=item["resource_type"],
                amount=item["amount"],
            )
            for item in value["resource_limits"]
        ),
    )


def _feedback_from_dict(value: Mapping[str, Any]) -> FeedbackEvent:
    return FeedbackEvent(
        feedback_id=value["feedback_id"],
        task_id=value["task_id"],
        action_id=value["action_id"],
        requirement_deltas=tuple(
            RequirementDelta(
                requirement_id=item["requirement_id"],
                disposition=FeedbackDisposition(item["disposition"]),
                evidence_refs=tuple(item["evidence_refs"]),
                invalidates_feedback_ids=tuple(item["invalidates_feedback_ids"]),
            )
            for item in value["requirement_deltas"]
        ),
        source_kind=FeedbackSourceKind(value["source_kind"]),
        source_authority_by_claim_type=tuple(
            ClaimAuthority(
                claim_type=item["claim_type"],
                authority=item["authority"],
            )
            for item in value["source_authority_by_claim_type"]
        ),
        confidence=value["confidence"],
        evidence_refs=tuple(value["evidence_refs"]),
    )


class _F0PrimitiveReplay:
    """Independent F0 projection derived from primitive semantic events."""

    STREAM_KINDS = frozenset({"f0.native.v1", "f0.native.v2"})
    VERIFIER_BOUND_STREAM_KIND = "f0.native.v2"

    def __init__(self, started: PublicEvent) -> None:
        try:
            self.task = _task_spec_from_dict(started.payload["task_spec"])
            raw_resources = started.payload["initial_resources"]
            if not isinstance(raw_resources, Mapping):
                raise TypeError("initial_resources must be a mapping")
            initial_resources = {
                str(resource_type): Decimal(str(amount))
                for resource_type, amount in raw_resources.items()
            }
            self.max_cycles = int(started.payload["max_cycles"])
            self.token_reservation = Decimal(
                str(started.payload["token_reservation"])
            )
        except (KeyError, TypeError, ValueError) as error:
            raise PublicEventReplayError(
                "primitive_start_error",
                "native F0 run_started lacks a valid task or resource contract",
                event_id=started.event_id,
            ) from error
        stream_kind = started.payload.get("stream_kind")
        binding = started.payload.get("verifier_binding")
        self.evidence_bundle: EvidenceTaskBundle | None = None
        if (
            stream_kind == self.VERIFIER_BOUND_STREAM_KIND
            and not isinstance(binding, Mapping)
        ):
            raise PublicEventReplayError(
                "primitive_verifier_binding_mismatch",
                "native F0 run_started lacks verifier_binding",
                event_id=started.event_id,
            )
        if isinstance(binding, Mapping):
            try:
                if binding.get("fixture_namespace") != "biofield.fixtures.r1":
                    raise ValueError("unsupported fixture namespace")
                self.evidence_bundle = load_task_bundle(
                    binding["task_id"],
                    task_version=binding["task_version"],
                    answer_key_version=binding["answer_key_version"],
                )
                expected_binding = f0_verifier_binding(self.evidence_bundle)
            except (KeyError, TypeError, ValueError, EvidenceTaskError) as error:
                raise PublicEventReplayError(
                    "primitive_verifier_binding_mismatch",
                    "verifier fixture binding cannot be resolved",
                    event_id=started.event_id,
                ) from error
            if _canonical_json(_thaw_json(binding)) != _canonical_json(
                expected_binding
            ):
                raise PublicEventReplayError(
                    "primitive_verifier_binding_mismatch",
                    "verifier fixture identity or hash does not match package data",
                    event_id=started.event_id,
                )
            expected_task_id = (
                f"f0.{self.evidence_bundle.task.task_id}."
                f"v{self.evidence_bundle.task.task_version}"
            )
            if self.task.task_id != expected_task_id:
                raise PublicEventReplayError(
                    "primitive_verifier_binding_mismatch",
                    "verifier fixture does not match the replayed TaskSpec",
                    event_id=started.event_id,
                )
        self.machine = ResidualStateMachine(self.task)
        self.ledger = ResourceLedger(initial_resources)
        self.resource_types = tuple(initial_resources)
        self.allocations: dict[str, Mapping[str, Any]] = {}
        self.actions: dict[str, Mapping[str, Any]] = {}
        self.evidence_by_action: dict[str, str] = {}
        self.evidence_artifact_by_action: dict[str, Mapping[str, Any]] = {}
        self.settlement_seen = False
        self.terminal_projection: Mapping[str, Any] | None = None
        self.terminal_projection_sha256: str | None = None

    @classmethod
    def maybe_start(cls, event: PublicEvent) -> _F0PrimitiveReplay | None:
        if (
            event.event_type == "run_started"
            and event.payload.get("stream_kind") in cls.STREAM_KINDS
        ):
            return cls(event)
        return None

    def apply(self, event: PublicEvent) -> None:
        handlers = {
            "allocation": self._apply_allocation,
            "resource": self._apply_resource,
            "action": self._apply_action,
            "evidence": self._apply_evidence,
            "feedback": self._apply_feedback,
            "residual": self._verify_residual,
            "run_settlement": self._verify_settlement,
            "run_terminal": self._verify_terminal,
        }
        handler = handlers.get(event.event_type)
        if handler is not None:
            handler(event)

    def _apply_allocation(self, event: PublicEvent) -> None:
        payload = event.payload
        requirement_id = payload.get("requirement_id")
        known_requirements = {
            requirement.requirement_id for requirement in self.task.requirements
        }
        snapshot = self.machine.snapshot()
        status_by_requirement = snapshot.status_by_requirement()
        prerequisites = {
            dependency.depends_on_requirement_id
            for dependency in self.task.requirement_dependencies
            if dependency.requirement_id == requirement_id
            and dependency.kind is DependencyKind.REQUIRES
        }
        requirement_ready = (
            requirement_id in status_by_requirement
            and status_by_requirement[requirement_id].value != "satisfied"
            and all(
                status_by_requirement[prerequisite].value == "satisfied"
                for prerequisite in prerequisites
            )
        )
        if (
            payload.get("allocation_id") != event.event_id
            or event.event_id in self.allocations
            or requirement_id not in known_requirements
            or payload.get("residual_revision") != snapshot.revision
            or not requirement_ready
        ):
            raise PublicEventReplayError(
                "primitive_allocation_error",
                "allocation conflicts with independently replayed residual state",
                event_id=event.event_id,
            )
        self.allocations[event.event_id] = payload

    def _apply_resource(self, event: PublicEvent) -> None:
        payload = event.payload
        try:
            resource_event = ResourceEvent(
                event_id=payload["event_id"],
                operation=ResourceOperation(payload["operation"]),
                resource_type=payload["resource_type"],
                amount=payload["amount"],
                source_account=payload["source_account"],
                target_account=payload["target_account"],
                idempotency_key=payload["idempotency_key"],
            )
            if resource_event.event_id != event.event_id:
                raise ValueError("resource payload event_id differs from public event")
            self.ledger.apply(resource_event)
        except (KeyError, TypeError, ValueError, RuntimeError) as error:
            raise PublicEventReplayError(
                "primitive_resource_error",
                f"resource event cannot be independently applied: {error}",
                event_id=event.event_id,
            ) from error

    def _apply_action(self, event: PublicEvent) -> None:
        payload = event.payload
        allocation_id = payload.get("allocation_id")
        allocation = self.allocations.get(allocation_id)
        requirement_ids = payload.get("requirement_ids")
        if (
            payload.get("action_id") != event.event_id
            or allocation is None
            or not isinstance(requirement_ids, tuple)
            or len(requirement_ids) != 1
            or allocation.get("requirement_id") != requirement_ids[0]
            or allocation.get("agent_id") != payload.get("agent_id")
        ):
            raise PublicEventReplayError(
                "primitive_action_error",
                "action does not match an admitted allocation",
                event_id=event.event_id,
            )
        self.actions[event.event_id] = payload

    def _apply_evidence(self, event: PublicEvent) -> None:
        action_id = event.payload.get("action_id")
        action = self.actions.get(action_id)
        artifact = event.payload.get("evidence")
        declared_sha256 = event.payload.get("artifact_sha256")
        if (
            action is None
            or action_id in self.evidence_by_action
            or event.payload.get("artifact_ref")
            not in action.get("evidence_refs", ())
        ):
            raise PublicEventReplayError(
                "primitive_evidence_error",
                "evidence does not match a unique applied action",
                event_id=event.event_id,
            )
        if not isinstance(artifact, Mapping):
            raise PublicEventReplayError(
                "primitive_evidence_hash_mismatch",
                "evidence payload must contain the artifact object",
                event_id=event.event_id,
            )
        try:
            declared_sha256 = _require_sha256(
                declared_sha256,
                "evidence payload.artifact_sha256",
            )
        except ValueError as error:
            raise PublicEventReplayError(
                "primitive_evidence_hash_mismatch",
                str(error),
                event_id=event.event_id,
            ) from error
        artifact_bytes = (
            _canonical_json(_thaw_json(artifact)) + "\n"
        ).encode("utf-8")
        if sha256(artifact_bytes).hexdigest() != declared_sha256:
            raise PublicEventReplayError(
                "primitive_evidence_hash_mismatch",
                "evidence content does not match artifact_sha256",
                event_id=event.event_id,
            )
        self.evidence_by_action[action_id] = event.event_id
        self.evidence_artifact_by_action[action_id] = artifact

    def _apply_feedback(self, event: PublicEvent) -> None:
        try:
            feedback = _feedback_from_dict(event.payload)
        except (KeyError, TypeError, ValueError) as error:
            raise PublicEventReplayError(
                "primitive_feedback_error",
                "feedback payload cannot be reconstructed",
                event_id=event.event_id,
            ) from error
        if feedback.action_id not in self.actions:
            raise PublicEventReplayError(
                "primitive_missing_action",
                "feedback references an action absent from primitive replay",
                event_id=event.event_id,
            )
        if feedback.action_id not in self.evidence_by_action:
            raise PublicEventReplayError(
                "primitive_missing_evidence",
                "feedback has no independently replayed evidence event",
                event_id=event.event_id,
            )
        action = self.actions[feedback.action_id]
        requirement_ids = action["requirement_ids"]
        artifact = self.evidence_artifact_by_action[feedback.action_id]
        if (
            len(feedback.requirement_deltas) != 1
            or feedback.requirement_deltas[0].requirement_id
            != requirement_ids[0]
        ):
            raise PublicEventReplayError(
                "primitive_feedback_disposition_mismatch",
                "feedback requirement does not match action/evidence",
                event_id=event.event_id,
            )
        if self.evidence_bundle is not None:
            try:
                expected_disposition = f0_requirement_disposition(
                    self.evidence_bundle,
                    requirement_id=requirement_ids[0],
                    artifact=_thaw_json(artifact),
                )
            except (TypeError, ValueError, EvidenceTaskError) as error:
                raise PublicEventReplayError(
                    "primitive_feedback_disposition_mismatch",
                    "frozen verifier could not evaluate evidence",
                    event_id=event.event_id,
                ) from error
            if (
                feedback.requirement_deltas[0].disposition
                is not expected_disposition
            ):
                raise PublicEventReplayError(
                    "primitive_feedback_disposition_mismatch",
                    "feedback disposition differs from frozen verifier replay",
                    event_id=event.event_id,
                )
        try:
            self.machine.apply_feedback(feedback)
        except (TypeError, ValueError) as error:
            raise PublicEventReplayError(
                "primitive_feedback_error",
                f"feedback cannot be independently applied: {error}",
                event_id=event.event_id,
            ) from error

    def _verify_residual(self, event: PublicEvent) -> None:
        snapshot = event.payload.get("snapshot")
        if not isinstance(snapshot, Mapping) or _canonical_json(
            _thaw_json(snapshot)
        ) != _canonical_json(self.machine.snapshot().to_dict()):
            raise PublicEventReplayError(
                "primitive_residual_mismatch",
                "committed residual differs from primitive feedback replay",
                event_id=event.event_id,
            )

    def _ledger_projection(self) -> dict[str, Any]:
        projection: dict[str, Any] = {}
        for resource_type in self.resource_types:
            totals = self.ledger.totals(resource_type)
            projection[resource_type] = {
                "expected": str(totals.expected),
                "accounted": str(totals.accounted),
                "spent": str(totals.spent),
                "shared_pool": str(totals.shared_pool),
            }
        return projection

    def _verify_settlement(self, event: PublicEvent) -> None:
        ledger = event.payload.get("ledger")
        if not isinstance(ledger, Mapping) or _canonical_json(
            _thaw_json(ledger)
        ) != _canonical_json(self._ledger_projection()):
            raise PublicEventReplayError(
                "primitive_settlement_mismatch",
                "committed settlement differs from primitive resource replay",
                event_id=event.event_id,
            )
        self.settlement_seen = True

    def _derive_terminal(self) -> tuple[str, str]:
        snapshot = self.machine.snapshot()
        if snapshot.complete:
            return RunTerminalStatus.COMPLETED.value, "all required evidence accepted"
        failed_actions = tuple(
            action
            for action in self.actions.values()
            if action.get("status") != "succeeded"
        )
        if failed_actions:
            reason = failed_actions[-1].get("failure_reason")
            if not isinstance(reason, str) or not reason:
                reason = "action failed"
            return RunTerminalStatus.FAILED.value, reason
        if len(self.actions) >= self.max_cycles:
            return RunTerminalStatus.MAX_CYCLES.value, "maximum cycle count reached"
        if self.ledger.balance("action_units", SHARED_POOL) < Decimal(1):
            return (
                RunTerminalStatus.BUDGET_EXHAUSTED.value,
                "no action budget remains",
            )
        if self.ledger.balance("tokens", SHARED_POOL) < self.token_reservation:
            return (
                RunTerminalStatus.BUDGET_EXHAUSTED.value,
                "insufficient tokens for the next action reservation",
            )
        return (
            RunTerminalStatus.FAILED.value,
            "no dependency-ready unmet requirement",
        )

    def _verify_terminal(self, event: PublicEvent) -> None:
        if not self.settlement_seen:
            raise PublicEventReplayError(
                "primitive_missing_settlement",
                "terminal event has no verified primitive settlement",
                event_id=event.event_id,
            )
        status, reason = self._derive_terminal()
        if event.payload.get("status") != status or event.payload.get("reason") != reason:
            raise PublicEventReplayError(
                "primitive_terminal_mismatch",
                "terminal status or reason differs from primitive replay",
                event_id=event.event_id,
            )
        projection = {
            "status": status,
            "reason": reason,
            "residual": self.machine.snapshot().to_dict(),
            "ledger": self._ledger_projection(),
        }
        projection_sha256 = sha256(
            _canonical_json(projection).encode("utf-8")
        ).hexdigest()
        if (
            event.payload.get("source_final_state_sha256") != projection_sha256
            or event.payload.get("public_terminal_projection_sha256")
            != projection_sha256
        ):
            raise PublicEventReplayError(
                "primitive_terminal_hash_mismatch",
                "terminal hashes differ from primitive replay projection",
                event_id=event.event_id,
            )
        self.terminal_projection = _freeze_json(projection)
        self.terminal_projection_sha256 = projection_sha256


class PublicEventReplayer:
    """Deterministic, append-only projection over public events."""

    @classmethod
    def replay(cls, events: Iterable[PublicEvent]) -> PublicReplayResult:
        return cls._replay(events)

    @classmethod
    def create_checkpoint(
        cls,
        events: Iterable[PublicEvent],
    ) -> PublicReplayCheckpoint:
        materialized = tuple(events)
        result = cls.replay(materialized)
        applied_by_id: dict[str, PublicEvent] = {}
        for event in materialized:
            applied_by_id.setdefault(event.event_id, event)
        applied = tuple(
            applied_by_id[event_id] for event_id in result.applied_event_ids
        )
        fingerprints = tuple(event.fingerprint for event in applied)
        checkpoint_digest = _checkpoint_sha256(
            applied_event_ids=result.applied_event_ids,
            applied_event_fingerprints=fingerprints,
            next_sequence=len(applied),
            terminal_status=result.terminal_status,
            source_final_state_sha256=result.source_final_state_sha256,
        )
        return PublicReplayCheckpoint(
            checkpoint_schema_version=PUBLIC_REPLAY_CHECKPOINT_SCHEMA_VERSION,
            public_event_schema_version=PUBLIC_EVENT_SCHEMA_VERSION,
            applied_events=applied,
            applied_event_ids=result.applied_event_ids,
            applied_event_fingerprints=fingerprints,
            next_sequence=len(applied),
            terminal_status=result.terminal_status,
            source_final_state_sha256=result.source_final_state_sha256,
            checkpoint_sha256=checkpoint_digest,
        )

    @classmethod
    def replay_from_checkpoint(
        cls,
        checkpoint: PublicReplayCheckpoint,
        events: Iterable[PublicEvent],
    ) -> PublicReplayResult:
        if not isinstance(checkpoint, PublicReplayCheckpoint):
            raise PublicEventReplayError(
                "invalid_checkpoint",
                "checkpoint must be a PublicReplayCheckpoint",
            )
        # Validate the causal semantics captured by the content-addressed
        # checkpoint before trusting it as seed state.
        checkpoint_result = cls.replay(checkpoint.applied_events)
        if (
            checkpoint_result.applied_event_ids != checkpoint.applied_event_ids
            or checkpoint_result.applied_event_count != checkpoint.next_sequence
            or checkpoint_result.terminal_status != checkpoint.terminal_status
            or checkpoint_result.source_final_state_sha256
            != checkpoint.source_final_state_sha256
        ):
            raise PublicEventReplayError(
                "checkpoint_event_mismatch",
                "checkpoint events do not reproduce checkpoint state",
            )
        return cls._replay(
            events,
            checkpoint=checkpoint,
            checkpoint_result=checkpoint_result,
        )

    @classmethod
    def _replay(
        cls,
        events: Iterable[PublicEvent],
        *,
        checkpoint: PublicReplayCheckpoint | None = None,
        checkpoint_result: PublicReplayResult | None = None,
    ) -> PublicReplayResult:
        if checkpoint is None:
            fingerprints_by_id: dict[str, str] = {}
            applied: list[PublicEvent] = []
            terminal_status: str | None = None
            source_final_state_sha256: str | None = None
        else:
            fingerprints_by_id = dict(
                zip(
                    checkpoint.applied_event_ids,
                    checkpoint.applied_event_fingerprints,
                    strict=True,
                )
            )
            applied = list(checkpoint.applied_events)
            terminal_status = checkpoint.terminal_status
            source_final_state_sha256 = checkpoint.source_final_state_sha256
        latest_residual: Mapping[str, Any] | None = None
        settlement_ledger: Mapping[str, Any] | None = None
        for previous_event in applied:
            if previous_event.event_type == "residual":
                snapshot = previous_event.payload.get("snapshot")
                if isinstance(snapshot, Mapping):
                    latest_residual = snapshot
            elif previous_event.event_type == "run_settlement":
                ledger = previous_event.payload.get("ledger")
                if isinstance(ledger, Mapping):
                    settlement_ledger = ledger
        primitive_replay: _F0PrimitiveReplay | None = None
        for previous_event in applied:
            if primitive_replay is None:
                primitive_replay = _F0PrimitiveReplay.maybe_start(previous_event)
            elif previous_event.event_type != "run_started":
                primitive_replay.apply(previous_event)
        public_terminal_projection = (
            checkpoint_result.public_terminal_projection
            if checkpoint_result is not None
            else None
        )
        public_terminal_projection_sha256 = (
            checkpoint_result.public_terminal_projection_sha256
            if checkpoint_result is not None
            else None
        )

        for input_index, event in enumerate(events):
            if not isinstance(event, PublicEvent):
                raise PublicEventReplayError(
                    "invalid_event",
                    "public replay accepts PublicEvent values only",
                    input_index=input_index,
                )

            previous_fingerprint = fingerprints_by_id.get(event.event_id)
            if previous_fingerprint is not None:
                if previous_fingerprint == event.fingerprint:
                    continue
                raise PublicEventReplayError(
                    "conflicting_duplicate",
                    f"event_id {event.event_id!r} has a conflicting payload",
                    event_id=event.event_id,
                    input_index=input_index,
                )

            if terminal_status is not None:
                raise PublicEventReplayError(
                    "event_after_terminal",
                    "events cannot be applied after run_terminal",
                    event_id=event.event_id,
                    input_index=input_index,
                )

            expected_sequence = len(applied)
            if event.sequence != expected_sequence:
                raise PublicEventReplayError(
                    "sequence_mismatch",
                    f"expected sequence {expected_sequence}, got {event.sequence}",
                    event_id=event.event_id,
                    input_index=input_index,
                )

            missing_parents = tuple(
                parent_id
                for parent_id in event.causal_parent_ids
                if parent_id not in fingerprints_by_id
            )
            if missing_parents:
                raise PublicEventReplayError(
                    "missing_causal_parent",
                    f"missing causal parent(s): {', '.join(missing_parents)}",
                    event_id=event.event_id,
                    input_index=input_index,
                )

            if primitive_replay is None:
                primitive_replay = _F0PrimitiveReplay.maybe_start(event)
            elif event.event_type != "run_started":
                primitive_replay.apply(event)

            if event.event_type == "residual":
                snapshot = event.payload.get("snapshot")
                if not isinstance(snapshot, Mapping):
                    raise PublicEventReplayError(
                        "invalid_residual_event",
                        "residual payload.snapshot must be a mapping",
                        event_id=event.event_id,
                        input_index=input_index,
                    )
                latest_residual = snapshot
            elif event.event_type == "run_settlement":
                ledger = event.payload.get("ledger")
                if ledger is not None and not isinstance(ledger, Mapping):
                    raise PublicEventReplayError(
                        "invalid_settlement_event",
                        "run_settlement payload.ledger must be a mapping",
                        event_id=event.event_id,
                        input_index=input_index,
                    )
                settlement_ledger = ledger

            if event.event_type == _TERMINAL_EVENT_TYPE:
                try:
                    terminal_status = _require_text(
                        event.payload.get("status"),
                        "run_terminal payload.status",
                    )
                    source_final_state_sha256 = _require_sha256(
                        event.payload.get("source_final_state_sha256"),
                        "run_terminal payload.source_final_state_sha256",
                    )
                except ValueError as error:
                    raise PublicEventReplayError(
                        "invalid_terminal_event",
                        str(error),
                        event_id=event.event_id,
                        input_index=input_index,
                    ) from error
                declared_projection_sha256 = event.payload.get(
                    "public_terminal_projection_sha256"
                )
                if declared_projection_sha256 is not None:
                    try:
                        declared_projection_sha256 = _require_sha256(
                            declared_projection_sha256,
                            "run_terminal payload.public_terminal_projection_sha256",
                        )
                    except ValueError as error:
                        raise PublicEventReplayError(
                            "invalid_terminal_projection",
                            str(error),
                            event_id=event.event_id,
                            input_index=input_index,
                        ) from error
                    if latest_residual is None or settlement_ledger is None:
                        raise PublicEventReplayError(
                            "invalid_terminal_projection",
                            "terminal projection requires residual and settlement events",
                            event_id=event.event_id,
                            input_index=input_index,
                        )
                    projection = {
                        "status": terminal_status,
                        "reason": event.payload.get("reason"),
                        "residual": _thaw_json(latest_residual),
                        "ledger": _thaw_json(settlement_ledger),
                    }
                    computed_projection_sha256 = sha256(
                        _canonical_json(projection).encode("utf-8")
                    ).hexdigest()
                    if computed_projection_sha256 != declared_projection_sha256:
                        raise PublicEventReplayError(
                            "terminal_projection_hash_mismatch",
                            "reconstructed terminal projection does not match declaration",
                            event_id=event.event_id,
                            input_index=input_index,
                        )
                    public_terminal_projection = _freeze_json(projection)
                    public_terminal_projection_sha256 = (
                        computed_projection_sha256
                    )

            fingerprints_by_id[event.event_id] = event.fingerprint
            applied.append(event)

        primitive_replay_verified = (
            primitive_replay is not None
            and terminal_status is not None
            and primitive_replay.terminal_projection is not None
        )
        if primitive_replay_verified:
            public_terminal_projection = primitive_replay.terminal_projection
            public_terminal_projection_sha256 = (
                primitive_replay.terminal_projection_sha256
            )
        evidence_feedback_verified = (
            primitive_replay_verified
            and primitive_replay is not None
            and primitive_replay.evidence_bundle is not None
        )
        public_state = {
            "schema_version": PUBLIC_EVENT_SCHEMA_VERSION,
            "events": [event.to_dict() for event in applied],
            "terminal_status": terminal_status,
            "source_final_state_sha256": source_final_state_sha256,
        }
        final_state_sha256 = sha256(
            _canonical_json(public_state).encode("utf-8")
        ).hexdigest()
        return PublicReplayResult(
            applied_event_count=len(applied),
            applied_event_ids=tuple(event.event_id for event in applied),
            terminal=terminal_status is not None,
            terminal_status=terminal_status,
            source_final_state_sha256=source_final_state_sha256,
            public_terminal_projection=public_terminal_projection,
            public_terminal_projection_sha256=public_terminal_projection_sha256,
            primitive_replay_verified=primitive_replay_verified,
            evidence_feedback_verified=evidence_feedback_verified,
            final_state_sha256=final_state_sha256,
        )


class F0PublicEventAdapter:
    """Adapt one sealed F0 run into the public E0 event contract.

    The adapter verifies every file sealed by ``finalization.json`` before it
    trusts the legacy event stream. Legacy F0 events are preserved as payload
    data, while sequencing and causal parents are made explicit. Settlement
    and terminal state become events in that same stream.
    """

    @classmethod
    def from_run_directory(cls, run_directory: str | Path) -> tuple[PublicEvent, ...]:
        root = Path(run_directory)
        finalization = cls._read_object(root / "finalization.json")
        cls._verify_sealed_files(root, finalization)
        config = cls._read_object(root / "config.json")
        metrics = cls._read_object(root / "metrics.json")
        source_events = cls._read_jsonl(root / "events.jsonl")

        expected_event_count = finalization.get("event_count")
        if expected_event_count != len(source_events):
            raise PublicEventReplayError(
                "event_count_mismatch",
                "sealed event_count does not match events.jsonl",
            )

        source_final_state_sha256 = cls._validated_digest(
            finalization.get("final_state_sha256"),
            code="invalid_finalization",
            field_name="final_state_sha256",
        )
        native_flags = tuple(
            "schema_version" in source_event
            or "sequence" in source_event
            or "causal_parent_ids" in source_event
            for source_event in source_events
        )
        if any(native_flags):
            if not all(native_flags):
                raise PublicEventReplayError(
                    "mixed_event_format",
                    "sealed F0 stream mixes legacy and native public events",
                )
            native_events = (
                PublicEventMigrationRegistry.default()
                .migrate_stream(source_events)
                .events
            )
            replayed = PublicEventReplayer.replay(native_events)
            if not replayed.terminal:
                raise PublicEventReplayError(
                    "missing_terminal_event",
                    "native sealed F0 stream must end in run_terminal",
                )
            if replayed.source_final_state_sha256 != source_final_state_sha256:
                raise PublicEventReplayError(
                    "source_final_state_mismatch",
                    "native terminal source hash does not match finalization",
                )
            cls._verify_native_evidence_artifacts(root, native_events)
            return native_events

        events: list[PublicEvent] = []
        events.append(
            PublicEvent(
                schema_version=PUBLIC_EVENT_SCHEMA_VERSION,
                event_id="e0.run-started",
                event_type="run_started",
                sequence=0,
                causal_parent_ids=(),
                payload={
                    "experiment_id": config.get("experiment_id"),
                    "protocol_version": config.get("protocol_version"),
                    "task_id": config.get("task_id"),
                    "run_id": finalization.get("run_id"),
                },
            )
        )

        migrated_legacy = PublicEventMigrationRegistry.default().migrate_stream(
            source_events,
            sequence_offset=len(events),
            initial_parent_id=events[-1].event_id,
            event_id_prefix="e0.f0.",
        )
        if migrated_legacy.primitive_semantics_preserved:
            raise PublicEventReplayError(
                "legacy_capability_mismatch",
                "legacy F0 migration cannot claim primitive semantics",
            )
        events.extend(migrated_legacy.events)
        previous_id = events[-1].event_id

        settlement = PublicEvent(
            schema_version=PUBLIC_EVENT_SCHEMA_VERSION,
            event_id="e0.run-settlement",
            event_type="run_settlement",
            sequence=len(events),
            causal_parent_ids=(previous_id,),
            payload={
                "spent_action_units": metrics.get("spent_action_units"),
                "spent_tokens": metrics.get("spent_tokens"),
                "source_final_state_sha256": source_final_state_sha256,
            },
        )
        events.append(settlement)
        events.append(
            PublicEvent(
                schema_version=PUBLIC_EVENT_SCHEMA_VERSION,
                event_id="e0.run-terminal",
                event_type=_TERMINAL_EVENT_TYPE,
                sequence=len(events),
                causal_parent_ids=(settlement.event_id,),
                payload={
                    "status": finalization.get("status"),
                    "reason": finalization.get("reason"),
                    "source_final_state_sha256": source_final_state_sha256,
                },
            )
        )
        return tuple(events)

    @staticmethod
    def _read_object(path: Path) -> dict[str, Any]:
        try:
            value = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as error:
            raise PublicEventReplayError(
                "invalid_artifact",
                f"cannot read {path.name} as a JSON object",
            ) from error
        if not isinstance(value, dict):
            raise PublicEventReplayError(
                "invalid_artifact",
                f"{path.name} must contain a JSON object",
            )
        return value

    @staticmethod
    def _read_jsonl(path: Path) -> tuple[dict[str, Any], ...]:
        try:
            lines = path.read_text(encoding="utf-8").splitlines()
        except OSError as error:
            raise PublicEventReplayError(
                "invalid_artifact",
                "cannot read events.jsonl",
            ) from error
        events: list[dict[str, Any]] = []
        for line_number, line in enumerate(lines, start=1):
            if not line.strip():
                continue
            try:
                value = json.loads(line)
            except json.JSONDecodeError as error:
                raise PublicEventReplayError(
                    "invalid_artifact",
                    f"events.jsonl line {line_number} is invalid JSON",
                ) from error
            if not isinstance(value, dict):
                raise PublicEventReplayError(
                    "invalid_artifact",
                    f"events.jsonl line {line_number} is not an object",
                )
            events.append(value)
        return tuple(events)

    @classmethod
    def _verify_sealed_files(
        cls,
        root: Path,
        finalization: Mapping[str, Any],
    ) -> None:
        hashes = finalization.get("file_sha256")
        if not isinstance(hashes, Mapping) or not hashes:
            raise PublicEventReplayError(
                "invalid_finalization",
                "finalization file_sha256 must be a non-empty mapping",
            )
        for filename, expected_digest in hashes.items():
            if not isinstance(filename, str) or Path(filename).name != filename:
                raise PublicEventReplayError(
                    "invalid_finalization",
                    "sealed filenames must be safe path segments",
                )
            expected = cls._validated_digest(
                expected_digest,
                code="invalid_finalization",
                field_name=f"file_sha256[{filename!r}]",
            )
            path = root / filename
            try:
                actual = sha256(path.read_bytes()).hexdigest()
            except OSError as error:
                raise PublicEventReplayError(
                    "artifact_hash_mismatch",
                    f"sealed file {filename!r} cannot be read",
                ) from error
            if actual != expected:
                raise PublicEventReplayError(
                    "artifact_hash_mismatch",
                    f"sealed file {filename!r} does not match finalization hash",
                )

    @classmethod
    def _verify_native_evidence_artifacts(
        cls,
        root: Path,
        events: tuple[PublicEvent, ...],
    ) -> None:
        artifacts_root = (root / "artifacts").resolve()
        for event in events:
            if event.event_type != "evidence":
                continue
            artifact_ref = event.payload.get("artifact_ref")
            if not isinstance(artifact_ref, str) or not artifact_ref.strip():
                raise PublicEventReplayError(
                    "invalid_source_event",
                    "native evidence event must contain artifact_ref",
                    event_id=event.event_id,
                )
            relative_path = Path(artifact_ref)
            if relative_path.is_absolute() or ".." in relative_path.parts:
                raise PublicEventReplayError(
                    "invalid_source_event",
                    "native evidence artifact_ref must stay under artifacts/",
                    event_id=event.event_id,
                )
            artifact_path = (root / relative_path).resolve()
            try:
                artifact_path.relative_to(artifacts_root)
            except ValueError as error:
                raise PublicEventReplayError(
                    "invalid_source_event",
                    "native evidence artifact_ref must stay under artifacts/",
                    event_id=event.event_id,
                ) from error
            expected_digest = cls._validated_digest(
                event.payload.get("artifact_sha256"),
                code="invalid_source_event",
                field_name="evidence payload.artifact_sha256",
            )
            try:
                actual_digest = sha256(artifact_path.read_bytes()).hexdigest()
            except OSError as error:
                raise PublicEventReplayError(
                    "artifact_hash_mismatch",
                    f"evidence artifact {artifact_ref!r} cannot be read",
                    event_id=event.event_id,
                ) from error
            if actual_digest != expected_digest:
                raise PublicEventReplayError(
                    "artifact_hash_mismatch",
                    f"evidence artifact {artifact_ref!r} does not match event hash",
                    event_id=event.event_id,
                )

    @staticmethod
    def _validated_digest(
        value: object,
        *,
        code: str,
        field_name: str,
    ) -> str:
        try:
            return _require_sha256(value, field_name)
        except ValueError as error:
            raise PublicEventReplayError(code, str(error)) from error
