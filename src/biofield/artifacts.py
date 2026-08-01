from __future__ import annotations

import json
import os
import tempfile
import threading
from collections.abc import Mapping
from dataclasses import dataclass
from hashlib import sha256
from pathlib import Path
from typing import Any, Protocol

from jsonschema import Draft202012Validator
from jsonschema.exceptions import SchemaError, ValidationError

from .contracts import RunFinalization, RunTerminalStatus


class SupportsToDict(Protocol):
    def to_dict(self) -> Mapping[str, Any]: ...


JsonObjectInput = Mapping[str, Any] | SupportsToDict


class ArtifactError(Exception):
    """Base error for run artifact creation and serialization."""


class InvalidArtifactPath(ArtifactError, ValueError):
    """Raised when an identifier could escape the explicit output root."""


class ArtifactExistsError(ArtifactError, FileExistsError):
    """Raised rather than silently overwriting a run or result file."""


class ArtifactSerializationError(ArtifactError, ValueError):
    """Raised when an artifact is not a finite JSON object."""


class RunFinalizedError(ArtifactError, RuntimeError):
    """Raised when a caller tries to mutate a sealed run."""


@dataclass(frozen=True)
class RunArtifactSchemas:
    config: Mapping[str, Any]
    event: Mapping[str, Any]
    metrics: Mapping[str, Any]

    def __post_init__(self) -> None:
        for field_name in ("config", "event", "metrics"):
            schema = getattr(self, field_name)
            if not isinstance(schema, Mapping):
                raise ArtifactSerializationError(f"{field_name} schema must be a mapping")
            try:
                Draft202012Validator.check_schema(dict(schema))
            except SchemaError as error:
                raise ArtifactSerializationError(
                    f"{field_name} schema is not a valid JSON schema"
                ) from error


def _validate_segment(value: str, field_name: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise InvalidArtifactPath(f"{field_name} must be a non-empty path segment")
    if value in {".", ".."} or "/" in value or "\\" in value or "\0" in value:
        raise InvalidArtifactPath(f"{field_name} must be a single safe path segment")
    if Path(value).is_absolute() or Path(value).name != value:
        raise InvalidArtifactPath(f"{field_name} must be a single safe path segment")
    return value


def _ensure_below(path: Path, root: Path) -> None:
    try:
        path.resolve().relative_to(root)
    except ValueError as error:
        raise InvalidArtifactPath("artifact path escapes the output directory") from error


def _json_value(payload: JsonObjectInput) -> dict[str, Any]:
    if isinstance(payload, Mapping):
        value: Any = dict(payload)
    else:
        to_dict = getattr(payload, "to_dict", None)
        if not callable(to_dict):
            raise ArtifactSerializationError(
                "artifact must be a mapping or expose to_dict()"
            )
        try:
            value = to_dict()
        except Exception as error:
            raise ArtifactSerializationError("artifact to_dict() failed") from error
        if not isinstance(value, Mapping):
            raise ArtifactSerializationError("artifact to_dict() must return a mapping")
        value = dict(value)

    try:
        json.dumps(
            value,
            allow_nan=False,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        )
    except (TypeError, ValueError) as error:
        raise ArtifactSerializationError("artifact must contain valid JSON") from error
    return value


def _json_object(payload: JsonObjectInput) -> str:
    return json.dumps(
        _json_value(payload),
        allow_nan=False,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    )


def _validate_payload(
    payload: JsonObjectInput,
    schema: Mapping[str, Any] | None,
    label: str,
) -> dict[str, Any]:
    value = _json_value(payload)
    if schema is not None:
        try:
            Draft202012Validator(dict(schema)).validate(value)
        except ValidationError as error:
            raise ArtifactSerializationError(f"{label} schema validation failed") from error
    return value


def _file_sha256(path: Path) -> str:
    return sha256(path.read_bytes()).hexdigest()


def _state_sha256(value: Mapping[str, Any]) -> str:
    encoded = _json_object(value).encode("utf-8")
    return sha256(encoded).hexdigest()


def _atomic_create_text(path: Path, text: str) -> None:
    descriptor, temporary_name = tempfile.mkstemp(
        dir=path.parent,
        prefix=f".{path.name}.",
        suffix=".tmp",
    )
    temporary_path = Path(temporary_name)
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8", newline="") as handle:
            handle.write(text)
            handle.flush()
            os.fsync(handle.fileno())
        try:
            # Publishing with a hard link is atomic and fails if path exists.
            os.link(temporary_path, path)
        except FileExistsError as error:
            raise ArtifactExistsError(f"{path.name} already exists") from error
    finally:
        temporary_path.unlink(missing_ok=True)


def _read_json_object(path: Path) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError) as error:
        raise ArtifactSerializationError(f"cannot read {path.name} as JSON") from error
    if not isinstance(value, dict):
        raise ArtifactSerializationError(f"{path.name} does not contain a JSON object")
    return value


class RunArtifactStore:
    """Write one immutable run under ``root/experiment_id/run_id``.

    The root, experiment ID, and run ID are all mandatory. Result snapshots are
    write-once; only ``events.jsonl`` is append-only.
    """

    def __init__(
        self,
        *,
        output_directory: Path,
        experiment_id: str,
        run_id: str,
        run_directory: Path,
        schemas: RunArtifactSchemas | None,
    ) -> None:
        self.output_directory = output_directory
        self.experiment_id = experiment_id
        self.run_id = run_id
        self.run_directory = run_directory
        self.schemas = schemas
        self._event_lock = threading.Lock()

    @classmethod
    def create(
        cls,
        output_directory: str | os.PathLike[str],
        experiment_id: str,
        run_id: str,
        *,
        schemas: RunArtifactSchemas | None = None,
    ) -> RunArtifactStore:
        if not isinstance(output_directory, (str, os.PathLike)) or (
            isinstance(output_directory, str) and not output_directory.strip()
        ):
            raise InvalidArtifactPath("output_directory must be explicit")
        safe_experiment_id = _validate_segment(experiment_id, "experiment_id")
        safe_run_id = _validate_segment(run_id, "run_id")

        requested_root = Path(output_directory).expanduser()
        requested_root.mkdir(parents=True, exist_ok=True)
        root = requested_root.resolve()
        if not root.is_dir():
            raise InvalidArtifactPath("output_directory must be a directory")

        experiment_directory = root / safe_experiment_id
        if experiment_directory.is_symlink():
            raise InvalidArtifactPath("experiment directory cannot be a symbolic link")
        try:
            experiment_directory.mkdir()
        except FileExistsError:
            if not experiment_directory.is_dir():
                raise InvalidArtifactPath("experiment path must be a directory")
        _ensure_below(experiment_directory, root)

        run_directory = experiment_directory / safe_run_id
        if run_directory.is_symlink():
            raise InvalidArtifactPath("run directory cannot be a symbolic link")
        try:
            run_directory.mkdir()
        except FileExistsError as error:
            raise ArtifactExistsError(
                f"run {safe_experiment_id}/{safe_run_id} already exists"
            ) from error
        _ensure_below(run_directory, root)

        (run_directory / "artifacts").mkdir()
        _atomic_create_text(run_directory / "events.jsonl", "")
        return cls(
            output_directory=root,
            experiment_id=safe_experiment_id,
            run_id=safe_run_id,
            run_directory=run_directory,
            schemas=schemas,
        )

    @property
    def artifacts_directory(self) -> Path:
        return self.run_directory / "artifacts"

    def write_config(self, payload: JsonObjectInput) -> Path:
        self._ensure_mutable()
        value = _validate_payload(
            payload,
            self.schemas.config if self.schemas is not None else None,
            "config",
        )
        return self._write_json_once("config.json", value)

    def write_metrics(self, payload: JsonObjectInput) -> Path:
        self._ensure_mutable()
        value = _validate_payload(
            payload,
            self.schemas.metrics if self.schemas is not None else None,
            "metrics",
        )
        return self._write_json_once("metrics.json", value)

    def write_summary(self, markdown: str) -> Path:
        self._ensure_mutable()
        if not isinstance(markdown, str):
            raise ArtifactSerializationError("summary must be a string")
        if not markdown.strip():
            raise ArtifactSerializationError("summary must not be empty")
        path = self.run_directory / "summary.md"
        _atomic_create_text(path, markdown)
        return path

    def append_event(self, payload: JsonObjectInput) -> None:
        self._ensure_mutable()
        value = _validate_payload(
            payload,
            self.schemas.event if self.schemas is not None else None,
            "event",
        )
        encoded = (_json_object(value) + "\n").encode("utf-8")
        path = self.run_directory / "events.jsonl"
        with self._event_lock:
            descriptor = os.open(path, os.O_WRONLY | os.O_APPEND)
            try:
                view = memoryview(encoded)
                while view:
                    written = os.write(descriptor, view)
                    view = view[written:]
                os.fsync(descriptor)
            finally:
                os.close(descriptor)

    def read_config(self) -> dict[str, Any]:
        return _read_json_object(self.run_directory / "config.json")

    def read_metrics(self) -> dict[str, Any]:
        return _read_json_object(self.run_directory / "metrics.json")

    def read_summary(self) -> str:
        return (self.run_directory / "summary.md").read_text(encoding="utf-8")

    def write_artifact(self, filename: str, payload: JsonObjectInput) -> Path:
        self._ensure_mutable()
        safe_filename = _validate_segment(filename, "artifact filename")
        if not safe_filename.endswith(".json"):
            raise InvalidArtifactPath("artifact filename must end in .json")
        path = self.artifacts_directory / safe_filename
        _atomic_create_text(path, _json_object(payload) + "\n")
        return path

    def finalize(
        self,
        *,
        status: RunTerminalStatus,
        reason: str,
        final_state: Mapping[str, Any],
    ) -> RunFinalization:
        self._ensure_mutable()
        required_files = ("config.json", "events.jsonl", "metrics.json", "summary.md")
        for filename in required_files:
            path = self.run_directory / filename
            if not path.is_file():
                raise ArtifactSerializationError(
                    f"cannot finalize before {filename} exists"
                )
        if not isinstance(final_state, Mapping):
            raise ArtifactSerializationError("final_state must be a mapping")
        finalization = RunFinalization(
            schema_version=1,
            experiment_id=self.experiment_id,
            run_id=self.run_id,
            status=status,
            reason=reason,
            event_count=len(self.read_events()),
            file_sha256={
                filename: _file_sha256(self.run_directory / filename)
                for filename in required_files
            },
            final_state_sha256=_state_sha256(dict(final_state)),
        )
        _atomic_create_text(
            self.run_directory / "finalization.json",
            _json_object(finalization) + "\n",
        )
        return finalization

    def read_finalization(self) -> dict[str, Any]:
        return _read_json_object(self.run_directory / "finalization.json")

    def read_events(self) -> tuple[dict[str, Any], ...]:
        events: list[dict[str, Any]] = []
        path = self.run_directory / "events.jsonl"
        try:
            lines = path.read_text(encoding="utf-8").splitlines()
        except OSError as error:
            raise ArtifactSerializationError("cannot read events.jsonl") from error
        for line_number, line in enumerate(lines, start=1):
            try:
                value = json.loads(line)
            except json.JSONDecodeError as error:
                raise ArtifactSerializationError(
                    f"events.jsonl line {line_number} is not valid JSON"
                ) from error
            if not isinstance(value, dict):
                raise ArtifactSerializationError(
                    f"events.jsonl line {line_number} is not a JSON object"
                )
            events.append(value)
        return tuple(events)

    def _write_json_once(self, filename: str, payload: JsonObjectInput) -> Path:
        path = self.run_directory / filename
        _atomic_create_text(path, _json_object(payload) + "\n")
        return path

    def _ensure_mutable(self) -> None:
        if (self.run_directory / "finalization.json").exists():
            raise RunFinalizedError("run is finalized and cannot be mutated")
