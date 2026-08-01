"""Offline provider contracts for MEAS0 subject and external Judge probes.

This module never authenticates, reads credential files, copies tokens, opens a
network connection, or enters the Harness authority boundary.  It can:

* build a ``codex exec`` command that relies on an already authenticated
  ChatGPT subscription session;
* validate externally captured Codex JSONL/final-output metadata;
* build a DeepSeek V4 Pro request for an external Evaluation Plane;
* parse bytes returned by an injected transport and seal their provenance.

Neither adapter produces formal MEAS0 evidence by itself.
"""

from __future__ import annotations

import hashlib
import json
import math
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Protocol

from jsonschema import Draft202012Validator
from jsonschema.exceptions import SchemaError, ValidationError

from .meas0_protected_artifacts import (
    ProtectedRawArtifactReceipt,
    ProtectedRawArtifactStore,
    RawArtifactHandlingManifest,
)
from .meas0_trust import (
    SignedTransportReceipt,
    TransportClaimScope,
    TransportOutcome,
    TrustContractError,
)


DEEPSEEK_V4_PRO_MODEL = "deepseek-v4-pro"
DEEPSEEK_V4_PRO_JUDGE_CARD_ID = "meas0.deepseek-v4-pro.card.v1"
DEEPSEEK_CHAT_URL = "https://api.deepseek.com/chat/completions"
CODEX_SUBSCRIPTION_SUBJECT_MODEL = "gpt-5.6-terra"
EXTERNAL_JUDGE_AUTHORITY = "external_evaluation_plane"
CODEX_SUBJECT_CLAIM_SCOPE = "subject_probe_nonformal"


class ProviderContractError(ValueError):
    """Raised when a provider request or captured result is unsafe/malformed."""


def _canonical(value: Any) -> bytes:
    return json.dumps(
        value,
        allow_nan=False,
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
    ).encode("utf-8")


def _sha256(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def _text(value: object, label: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ProviderContractError(f"{label} must be non-empty text")
    return value


def _sha256_text(value: object, label: str) -> str:
    if (
        not isinstance(value, str)
        or len(value) != 64
        or any(character not in "0123456789abcdef" for character in value)
    ):
        raise ProviderContractError(f"{label} must be a lowercase SHA-256")
    return value


def _non_negative_int(value: object, label: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        raise ProviderContractError(f"{label} must be a non-negative integer")
    return value


def _normalized_absolute_path(value: object, label: str) -> Path:
    text = _text(value, label)
    if "\0" in text:
        raise ProviderContractError(f"{label} is invalid")
    path = Path(text)
    if not path.is_absolute():
        raise ProviderContractError(f"{label} must be absolute")
    normalized = path.resolve(strict=False)
    if str(path) != str(normalized):
        raise ProviderContractError(f"{label} must be normalized")
    return normalized


def _contained_path(
    value: object,
    *,
    working_directory: Path,
    label: str,
) -> Path:
    path = _normalized_absolute_path(value, label)
    try:
        relative = path.relative_to(working_directory)
    except ValueError as error:
        raise ProviderContractError(
            f"{label} must remain within the working directory"
        ) from error
    if not relative.parts:
        raise ProviderContractError(
            f"{label} must be a file within the working directory"
        )
    return path


def _strict_schema(schema: object, label: str) -> dict[str, Any]:
    if not isinstance(schema, Mapping):
        raise ProviderContractError(f"{label} must be a JSON schema object")
    normalized = {str(key): value for key, value in schema.items()}
    try:
        Draft202012Validator.check_schema(normalized)
    except SchemaError as error:
        raise ProviderContractError(f"{label} is not a valid JSON schema") from error
    if (
        normalized.get("type") != "object"
        or normalized.get("additionalProperties") is not False
    ):
        raise ProviderContractError(f"{label} must reject additional properties")
    return normalized


def _json_object(value: bytes, label: str) -> dict[str, Any]:
    def unique_pairs(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
        result: dict[str, Any] = {}
        for key, item in pairs:
            if key in result:
                raise ProviderContractError(f"{label} contains duplicate keys")
            result[key] = item
        return result

    try:
        parsed = json.loads(
            value.decode("utf-8"),
            object_pairs_hook=unique_pairs,
        )
    except (UnicodeDecodeError, json.JSONDecodeError) as error:
        raise ProviderContractError(f"{label} must be UTF-8 JSON") from error
    if not isinstance(parsed, dict):
        raise ProviderContractError(f"{label} must be a JSON object")
    return parsed


class _HashBound:
    def _body(self) -> dict[str, Any]:
        raise NotImplementedError

    @property
    def contract_hash(self) -> str:
        return _sha256(_canonical(self._body()))

    def to_dict(self) -> dict[str, Any]:
        return {**self._body(), "contract_hash": self.contract_hash}


@dataclass(frozen=True)
class CodexSubjectRequest:
    prompt: bytes
    model: str
    working_directory: str
    output_schema_path: str
    output_path: str
    output_schema: Mapping[str, Any]
    sandbox: str

    def __post_init__(self) -> None:
        if not isinstance(self.prompt, bytes) or not self.prompt:
            raise ProviderContractError("Codex subject prompt must be non-empty bytes")
        if self.model != CODEX_SUBSCRIPTION_SUBJECT_MODEL:
            raise ProviderContractError(
                "Codex subscription Subject model is not frozen"
            )
        working_directory = _normalized_absolute_path(
            self.working_directory,
            "working_directory",
        )
        output_schema_path = _contained_path(
            self.output_schema_path,
            working_directory=working_directory,
            label="output_schema_path",
        )
        output_path = _contained_path(
            self.output_path,
            working_directory=working_directory,
            label="output_path",
        )
        object.__setattr__(self, "working_directory", str(working_directory))
        object.__setattr__(self, "output_schema_path", str(output_schema_path))
        object.__setattr__(self, "output_path", str(output_path))
        if output_schema_path == output_path:
            raise ProviderContractError("schema path and output path must differ")
        object.__setattr__(
            self,
            "output_schema",
            _strict_schema(self.output_schema, "Codex output schema"),
        )
        if self.sandbox not in {"read-only", "workspace-write"}:
            raise ProviderContractError(
                "Codex subject sandbox must be read-only or workspace-write"
            )


@dataclass(frozen=True)
class CodexSubscriptionCommand(_HashBound):
    argv: tuple[str, ...]
    stdin_bytes: bytes
    working_directory: str
    environment: tuple[tuple[str, str], ...]
    authentication: str
    output_schema: Mapping[str, Any]
    prompt_sha256: str
    output_schema_sha256: str

    def __post_init__(self) -> None:
        object.__setattr__(self, "argv", tuple(self.argv))
        object.__setattr__(self, "environment", tuple(self.environment))
        if not isinstance(self.stdin_bytes, bytes) or not self.stdin_bytes:
            raise ProviderContractError("Codex command stdin must be bytes")
        _sha256_text(self.prompt_sha256, "prompt_sha256")
        _sha256_text(self.output_schema_sha256, "output_schema_sha256")
        schema = _strict_schema(self.output_schema, "Codex output schema")
        object.__setattr__(self, "output_schema", schema)
        if self.prompt_sha256 != _sha256(self.stdin_bytes):
            raise ProviderContractError("Codex prompt hash mismatch")
        if self.output_schema_sha256 != _sha256(_canonical(schema)):
            raise ProviderContractError("Codex output schema hash mismatch")
        if self.authentication != "existing_chatgpt_subscription_session":
            raise ProviderContractError("Codex authentication mode is invalid")
        if self.environment:
            raise ProviderContractError(
                "Codex subscription command cannot carry environment secrets"
            )
        working_directory = _normalized_absolute_path(
            self.working_directory,
            "working_directory",
        )
        object.__setattr__(self, "working_directory", str(working_directory))
        if len(self.argv) != 14:
            raise ProviderContractError("Codex command must use the exact argv")
        sandbox = self.argv[8]
        if sandbox not in {"read-only", "workspace-write"}:
            raise ProviderContractError("Codex command sandbox is invalid")
        output_schema_path = _contained_path(
            self.argv[10],
            working_directory=working_directory,
            label="output_schema_path",
        )
        output_path = _contained_path(
            self.argv[12],
            working_directory=working_directory,
            label="output_path",
        )
        expected_argv = (
            "codex",
            "exec",
            "--ephemeral",
            "--json",
            "--ignore-user-config",
            "--model",
            CODEX_SUBSCRIPTION_SUBJECT_MODEL,
            "--sandbox",
            sandbox,
            "--output-schema",
            str(output_schema_path),
            "--output-last-message",
            str(output_path),
            "-",
        )
        if self.argv != expected_argv:
            raise ProviderContractError("Codex command must use the exact argv")
        if output_schema_path == output_path:
            raise ProviderContractError("schema path and output path must differ")
        if any(
            marker in argument
            for argument in self.argv
            for marker in (
                "auth.json",
                "OPENAI_API_KEY",
                "CODEX_API_KEY",
                "CODEX_ACCESS_TOKEN",
                "--with-api-key",
                "--with-access-token",
            )
        ):
            raise ProviderContractError(
                "Codex command may not inspect or carry authentication material"
            )

    @property
    def command_hash(self) -> str:
        return self.contract_hash

    def _body(self) -> dict[str, Any]:
        return {
            "argv": list(self.argv),
            "working_directory": self.working_directory,
            "environment": dict(self.environment),
            "authentication": self.authentication,
            "prompt_sha256": self.prompt_sha256,
            "output_schema": dict(self.output_schema),
            "output_schema_sha256": self.output_schema_sha256,
            "prompt_delivery": "stdin",
            "subscription_black_box": True,
            "build_only": True,
            "schema_file_bytes_verified": False,
            "parent_environment_verified": False,
            "claim_scope": CODEX_SUBJECT_CLAIM_SCOPE,
        }


def build_codex_subscription_command(
    request: CodexSubjectRequest,
) -> CodexSubscriptionCommand:
    """Build only; the caller is responsible for invoking the command."""

    if not isinstance(request, CodexSubjectRequest):
        raise ProviderContractError("Codex subject request is invalid")
    argv = (
        "codex",
        "exec",
        "--ephemeral",
        "--json",
        "--ignore-user-config",
        "--model",
        request.model,
        "--sandbox",
        request.sandbox,
        "--output-schema",
        request.output_schema_path,
        "--output-last-message",
        request.output_path,
        "-",
    )
    return CodexSubscriptionCommand(
        argv=argv,
        stdin_bytes=request.prompt,
        working_directory=request.working_directory,
        environment=(),
        authentication="existing_chatgpt_subscription_session",
        output_schema=request.output_schema,
        prompt_sha256=_sha256(request.prompt),
        output_schema_sha256=_sha256(_canonical(request.output_schema)),
    )


@dataclass(frozen=True)
class CodexSubjectExecutionSeal(_HashBound):
    command_hash: str
    cli_version: str
    exit_code: int
    thread_id: str
    raw_jsonl_sha256: str
    final_output_sha256: str
    input_tokens: int
    cached_input_tokens: int
    output_tokens: int
    reasoning_output_tokens: int
    completed_at: str
    subscription_black_box: bool = True
    replay_capability: str = "output_and_metadata_only"
    claim_scope: str = CODEX_SUBJECT_CLAIM_SCOPE

    def __post_init__(self) -> None:
        _sha256_text(self.command_hash, "command_hash")
        _text(self.cli_version, "Codex CLI version")
        if isinstance(self.exit_code, bool) or not isinstance(self.exit_code, int):
            raise ProviderContractError("Codex exit_code must be an integer")
        _text(self.thread_id, "Codex thread_id")
        _sha256_text(self.raw_jsonl_sha256, "raw_jsonl_sha256")
        _sha256_text(self.final_output_sha256, "final_output_sha256")
        for field_name in (
            "input_tokens",
            "cached_input_tokens",
            "output_tokens",
            "reasoning_output_tokens",
        ):
            _non_negative_int(getattr(self, field_name), field_name)
        if self.cached_input_tokens > self.input_tokens:
            raise ProviderContractError("Codex cached token usage is invalid")
        _text(self.completed_at, "Codex completed_at")
        if (
            self.subscription_black_box is not True
            or self.replay_capability != "output_and_metadata_only"
            or self.claim_scope != CODEX_SUBJECT_CLAIM_SCOPE
        ):
            raise ProviderContractError(
                "Codex subscription result cannot claim formal replay"
            )

    def _body(self) -> dict[str, Any]:
        return {
            "command_hash": self.command_hash,
            "cli_version": self.cli_version,
            "exit_code": self.exit_code,
            "thread_id": self.thread_id,
            "raw_jsonl_sha256": self.raw_jsonl_sha256,
            "final_output_sha256": self.final_output_sha256,
            "input_tokens": self.input_tokens,
            "cached_input_tokens": self.cached_input_tokens,
            "output_tokens": self.output_tokens,
            "reasoning_output_tokens": self.reasoning_output_tokens,
            "completed_at": self.completed_at,
            "subscription_black_box": self.subscription_black_box,
            "replay_capability": self.replay_capability,
            "claim_scope": self.claim_scope,
        }


def seal_codex_subject_execution(
    *,
    command: CodexSubscriptionCommand,
    exit_code: int,
    raw_jsonl: bytes,
    final_output: bytes,
    cli_version: str,
    completed_at: str,
) -> CodexSubjectExecutionSeal:
    """Validate externally captured bytes and return metadata-only sealing."""

    if not isinstance(command, CodexSubscriptionCommand):
        raise ProviderContractError("Codex command contract is required")
    if exit_code != 0:
        raise ProviderContractError("Codex subject execution did not succeed")
    if not isinstance(raw_jsonl, bytes) or not raw_jsonl.strip():
        raise ProviderContractError("Codex JSONL output is missing")
    events = []
    for line in raw_jsonl.splitlines():
        if line.strip():
            events.append(_json_object(line, "Codex JSONL event"))
    if any(event.get("type") in {"error", "turn.failed"} for event in events):
        raise ProviderContractError("Codex JSONL contains a failed turn")
    started = [event for event in events if event.get("type") == "thread.started"]
    completed = [event for event in events if event.get("type") == "turn.completed"]
    if len(started) != 1 or len(completed) != 1:
        raise ProviderContractError(
            "Codex JSONL must contain one started and completed event"
        )
    output = _json_object(final_output, "Codex final output")
    try:
        Draft202012Validator(command.output_schema).validate(output)
    except ValidationError as error:
        raise ProviderContractError(
            "Codex final output failed local schema validation"
        ) from error
    usage = completed[0].get("usage")
    if not isinstance(usage, Mapping):
        raise ProviderContractError("Codex completed event has no usage")
    return CodexSubjectExecutionSeal(
        command_hash=command.command_hash,
        cli_version=_text(cli_version, "Codex CLI version"),
        exit_code=exit_code,
        thread_id=_text(started[0].get("thread_id"), "Codex thread_id"),
        raw_jsonl_sha256=_sha256(raw_jsonl),
        final_output_sha256=_sha256(final_output),
        input_tokens=_non_negative_int(usage.get("input_tokens"), "input_tokens"),
        cached_input_tokens=_non_negative_int(
            usage.get("cached_input_tokens"), "cached_input_tokens"
        ),
        output_tokens=_non_negative_int(usage.get("output_tokens"), "output_tokens"),
        reasoning_output_tokens=_non_negative_int(
            usage.get("reasoning_output_tokens"), "reasoning_output_tokens"
        ),
        completed_at=_text(completed_at, "Codex completed_at"),
    )


def deepseek_input_sha256(
    *,
    system_prompt: str,
    user_content: str,
    criterion_id: str,
    allowed_evidence_refs: Sequence[str],
) -> str:
    refs = tuple(allowed_evidence_refs)
    if not refs or len(set(refs)) != len(refs):
        raise ProviderContractError("allowed evidence refs must be non-empty unique")
    for ref in refs:
        _text(ref, "allowed evidence ref")
    return _sha256(
        _canonical(
            {
                "system_prompt": _text(system_prompt, "system_prompt"),
                "user_content": _text(user_content, "user_content"),
                "criterion_id": _text(criterion_id, "criterion_id"),
                "allowed_evidence_refs": list(refs),
            }
        )
    )


@dataclass(frozen=True)
class DataHandlingAttestation(_HashBound):
    attestation_id: str
    attestor_id: str
    attested_at: str
    input_sha256: str
    deidentified: bool
    non_sensitive: bool

    def __post_init__(self) -> None:
        _text(self.attestation_id, "data attestation_id")
        _text(self.attestor_id, "data attestor_id")
        _text(self.attested_at, "data attested_at")
        _sha256_text(self.input_sha256, "attested input_sha256")
        if not isinstance(self.deidentified, bool):
            raise ProviderContractError("deidentified must be boolean")
        if not isinstance(self.non_sensitive, bool):
            raise ProviderContractError("non_sensitive must be boolean")

    def _body(self) -> dict[str, Any]:
        return {
            "attestation_id": self.attestation_id,
            "attestor_id": self.attestor_id,
            "attested_at": self.attested_at,
            "input_sha256": self.input_sha256,
            "deidentified": self.deidentified,
            "non_sensitive": self.non_sensitive,
        }


JUDGE_OUTPUT_SCHEMA: dict[str, Any] = {
    "$schema": "https://json-schema.org/draft/2020-12/schema",
    "type": "object",
    "properties": {
        "criterion_id": {"type": "string", "minLength": 1},
        "verdict": {"enum": ["pass", "fail", "unknown"]},
        "evidence_refs": {
            "type": "array",
            "items": {"type": "string", "minLength": 1},
            "uniqueItems": True,
        },
        "rationale": {"type": "string", "minLength": 1},
        "confidence_0_1": {
            "type": "number",
            "minimum": 0,
            "maximum": 1,
        },
        "p_pass_0_1": {
            "type": "number",
            "minimum": 0,
            "maximum": 1,
        },
        "judge_version": {"const": DEEPSEEK_V4_PRO_JUDGE_CARD_ID},
    },
    "required": [
        "criterion_id",
        "verdict",
        "evidence_refs",
        "rationale",
        "confidence_0_1",
        "p_pass_0_1",
        "judge_version",
    ],
    "additionalProperties": False,
}
JUDGE_OUTPUT_SCHEMA_SHA256 = _sha256(_canonical(JUDGE_OUTPUT_SCHEMA))


@dataclass(frozen=True)
class DeepSeekJudgeRequest(_HashBound):
    url: str
    headers: tuple[tuple[str, str], ...]
    body_bytes: bytes
    criterion_id: str
    allowed_evidence_refs: tuple[str, ...]
    data_attestation: DataHandlingAttestation
    effective_seed: str
    requested_temperature: float | None
    temperature_disposition: str
    judge_output_schema_sha256: str = JUDGE_OUTPUT_SCHEMA_SHA256
    authority: str = EXTERNAL_JUDGE_AUTHORITY

    def __post_init__(self) -> None:
        self._validate_contract()

    @property
    def body(self) -> dict[str, Any]:
        """Return a detached copy; canonical request bytes remain immutable."""

        return _json_object(self.body_bytes, "DeepSeek request body")

    def _validate_contract(self) -> None:
        if self.url != DEEPSEEK_CHAT_URL:
            raise ProviderContractError("DeepSeek Judge URL is not frozen")
        object.__setattr__(self, "headers", tuple(self.headers))
        if self.headers != (("Content-Type", "application/json"),):
            raise ProviderContractError(
                "Judge request headers cannot include authentication"
            )
        if not isinstance(self.body_bytes, bytes) or not self.body_bytes:
            raise ProviderContractError(
                "DeepSeek canonical request body bytes are required"
            )
        body = self.body
        if self.body_bytes != _canonical(body):
            raise ProviderContractError("DeepSeek request body bytes must be canonical")
        _text(self.criterion_id, "criterion_id")
        object.__setattr__(
            self,
            "allowed_evidence_refs",
            tuple(self.allowed_evidence_refs),
        )
        refs = self.allowed_evidence_refs
        if not refs or len(set(refs)) != len(refs):
            raise ProviderContractError(
                "allowed evidence refs must be non-empty unique"
            )
        for ref in refs:
            _text(ref, "allowed evidence ref")
        if not isinstance(self.data_attestation, DataHandlingAttestation):
            raise ProviderContractError("data handling attestation is required")
        if self.data_attestation.deidentified is not True:
            raise ProviderContractError(
                "DeepSeek input requires deidentified attestation"
            )
        if self.data_attestation.non_sensitive is not True:
            raise ProviderContractError(
                "DeepSeek input requires non_sensitive attestation"
            )
        if self.effective_seed != "unsupported" or "seed" in body:
            raise ProviderContractError("DeepSeek V4 Pro seed is unsupported")
        if self.authority != EXTERNAL_JUDGE_AUTHORITY:
            raise ProviderContractError(
                "DeepSeek Judge must remain in the external Evaluation Plane"
            )
        if (
            set(body)
            != {
                "model",
                "messages",
                "thinking",
                "reasoning_effort",
                "response_format",
                "stream",
            }
            or body.get("model") != DEEPSEEK_V4_PRO_MODEL
            or body.get("thinking") != {"type": "enabled"}
            or body.get("reasoning_effort") != "high"
            or body.get("stream") is not False
            or body.get("response_format") != {"type": "json_object"}
        ):
            raise ProviderContractError("DeepSeek thinking request is not frozen")
        messages = body.get("messages")
        if (
            not isinstance(messages, list)
            or len(messages) != 2
            or not isinstance(messages[0], Mapping)
            or not isinstance(messages[1], Mapping)
            or set(messages[0]) != {"role", "content"}
            or set(messages[1]) != {"role", "content"}
            or messages[0].get("role") != "system"
            or messages[1].get("role") != "user"
        ):
            raise ProviderContractError("DeepSeek request messages are not frozen")
        system_prompt = _text(
            messages[0].get("content"),
            "DeepSeek system prompt",
        )
        user_content = _text(
            messages[1].get("content"),
            "DeepSeek user content",
        )
        if "json" not in system_prompt.casefold():
            raise ProviderContractError(
                "DeepSeek JSON mode requires JSON in the prompt"
            )
        expected_input_hash = deepseek_input_sha256(
            system_prompt=system_prompt,
            user_content=user_content,
            criterion_id=self.criterion_id,
            allowed_evidence_refs=refs,
        )
        if self.data_attestation.input_sha256 != expected_input_hash:
            raise ProviderContractError(
                "data attestation input hash does not match request"
            )
        if self.judge_output_schema_sha256 != JUDGE_OUTPUT_SCHEMA_SHA256:
            raise ProviderContractError(
                "DeepSeek Judge output schema hash is not frozen"
            )
        if self.requested_temperature is None:
            if self.temperature_disposition != "not_set_unsupported_in_thinking_mode":
                raise ProviderContractError(
                    "DeepSeek temperature disposition is invalid"
                )
        else:
            if (
                isinstance(self.requested_temperature, bool)
                or not isinstance(self.requested_temperature, (int, float))
                or not math.isfinite(float(self.requested_temperature))
                or not 0 <= float(self.requested_temperature) <= 2
                or self.temperature_disposition
                != "ignored_unsupported_in_thinking_mode"
            ):
                raise ProviderContractError(
                    "DeepSeek temperature disposition is invalid"
                )

    @property
    def request_fingerprint(self) -> str:
        return self.contract_hash

    def _body(self) -> dict[str, Any]:
        return {
            "url": self.url,
            "headers": dict(self.headers),
            "body": self.body,
            "criterion_id": self.criterion_id,
            "allowed_evidence_refs": list(self.allowed_evidence_refs),
            "data_attestation": self.data_attestation.to_dict(),
            "effective_seed": self.effective_seed,
            "requested_temperature": self.requested_temperature,
            "temperature_disposition": self.temperature_disposition,
            "judge_output_schema_sha256": self.judge_output_schema_sha256,
            "authority": self.authority,
        }


@dataclass(frozen=True)
class DeepSeekTransportResponse:
    status_code: int
    raw_response: bytes = field(repr=False)
    received_at: str
    transport_receipt: SignedTransportReceipt | None = None

    def __post_init__(self) -> None:
        if isinstance(self.status_code, bool) or not isinstance(self.status_code, int):
            raise ProviderContractError("transport status_code must be integer")
        if not isinstance(self.raw_response, bytes):
            raise ProviderContractError("transport raw_response must be bytes")
        _text(self.received_at, "transport received_at")
        if self.transport_receipt is not None:
            if not isinstance(self.transport_receipt, SignedTransportReceipt):
                raise ProviderContractError(
                    "transport_receipt must be typed or explicitly absent"
                )
            payload = self.transport_receipt.payload
            if (
                payload.outcome is not TransportOutcome.SUCCESS
                or payload.claim_scope
                is not TransportClaimScope.GATEWAY_TLS_REQUEST_RESPONSE_OBSERVATION
                or payload.http_status != self.status_code
                or payload.response_hash != _sha256(self.raw_response)
                or payload.response_size != len(self.raw_response)
            ):
                raise ProviderContractError(
                    "DeepSeek transport receipt binding is invalid"
                )


class DeepSeekTransport(Protocol):
    transport_id: str
    test_only: bool

    def send(
        self,
        request: DeepSeekJudgeRequest,
    ) -> DeepSeekTransportResponse: ...


@dataclass(frozen=True)
class DeepSeekUsage(_HashBound):
    prompt_tokens: int
    prompt_cache_hit_tokens: int
    prompt_cache_miss_tokens: int
    completion_tokens: int
    total_tokens: int
    reasoning_tokens: int

    def __post_init__(self) -> None:
        for field_name in (
            "prompt_tokens",
            "prompt_cache_hit_tokens",
            "prompt_cache_miss_tokens",
            "completion_tokens",
            "total_tokens",
            "reasoning_tokens",
        ):
            _non_negative_int(getattr(self, field_name), field_name)
        if (
            self.prompt_tokens
            != self.prompt_cache_hit_tokens + self.prompt_cache_miss_tokens
            or self.total_tokens != self.prompt_tokens + self.completion_tokens
            or self.reasoning_tokens > self.completion_tokens
        ):
            raise ProviderContractError("DeepSeek usage accounting is invalid")

    def _body(self) -> dict[str, Any]:
        return {
            "prompt_tokens": self.prompt_tokens,
            "prompt_cache_hit_tokens": self.prompt_cache_hit_tokens,
            "prompt_cache_miss_tokens": self.prompt_cache_miss_tokens,
            "completion_tokens": self.completion_tokens,
            "total_tokens": self.total_tokens,
            "reasoning_tokens": self.reasoning_tokens,
        }


def _deepseek_response_derivatives(raw_response: bytes) -> dict[str, Any]:
    raw = _json_object(raw_response, "DeepSeek response")
    for field_name in (
        "id",
        "object",
        "created",
        "model",
        "system_fingerprint",
        "choices",
        "usage",
    ):
        if field_name not in raw:
            raise ProviderContractError(f"DeepSeek response is missing {field_name}")
    if raw["object"] != "chat.completion":
        raise ProviderContractError("DeepSeek response object is invalid")
    if raw["model"] != DEEPSEEK_V4_PRO_MODEL:
        raise ProviderContractError("DeepSeek response model mismatch")
    system_fingerprint = _text(
        raw["system_fingerprint"],
        "DeepSeek system fingerprint",
    )
    choices = raw["choices"]
    if not isinstance(choices, list) or len(choices) != 1:
        raise ProviderContractError("DeepSeek response must contain exactly one choice")
    choice = choices[0]
    if (
        not isinstance(choice, Mapping)
        or choice.get("index") != 0
        or choice.get("finish_reason") != "stop"
    ):
        raise ProviderContractError("DeepSeek response choice is invalid")
    message = choice.get("message")
    if (
        not isinstance(message, Mapping)
        or message.get("role") != "assistant"
        or not isinstance(message.get("content"), str)
    ):
        raise ProviderContractError("DeepSeek response message is invalid")
    output = _json_object(
        message["content"].encode("utf-8"),
        "DeepSeek Judge output",
    )
    try:
        Draft202012Validator(JUDGE_OUTPUT_SCHEMA).validate(output)
    except ValidationError as error:
        raise ProviderContractError(
            "DeepSeek Judge output failed local JSON schema validation"
        ) from error
    usage_raw = raw["usage"]
    if not isinstance(usage_raw, Mapping):
        raise ProviderContractError("DeepSeek usage is missing")
    details = usage_raw.get("completion_tokens_details")
    if not isinstance(details, Mapping):
        raise ProviderContractError("DeepSeek usage reasoning details are missing")
    usage = DeepSeekUsage(
        prompt_tokens=_non_negative_int(
            usage_raw.get("prompt_tokens"),
            "prompt_tokens",
        ),
        prompt_cache_hit_tokens=_non_negative_int(
            usage_raw.get("prompt_cache_hit_tokens"),
            "prompt_cache_hit_tokens",
        ),
        prompt_cache_miss_tokens=_non_negative_int(
            usage_raw.get("prompt_cache_miss_tokens"),
            "prompt_cache_miss_tokens",
        ),
        completion_tokens=_non_negative_int(
            usage_raw.get("completion_tokens"),
            "completion_tokens",
        ),
        total_tokens=_non_negative_int(
            usage_raw.get("total_tokens"),
            "total_tokens",
        ),
        reasoning_tokens=_non_negative_int(
            details.get("reasoning_tokens"),
            "reasoning_tokens",
        ),
    )
    reasoning = message.get("reasoning_content")
    if reasoning is not None and not isinstance(reasoning, str):
        raise ProviderContractError("DeepSeek reasoning_content must be text or null")
    reasoning_present = bool(reasoning)
    return {
        "response_id": _text(raw["id"], "DeepSeek response id"),
        "model": raw["model"],
        "system_fingerprint": system_fingerprint,
        "created": _non_negative_int(raw["created"], "DeepSeek created"),
        "finish_reason": choice["finish_reason"],
        "output": output,
        "usage": usage,
        "reasoning_content_present": reasoning_present,
        "reasoning_content_sha256": (
            _sha256(reasoning.encode("utf-8")) if reasoning_present else None
        ),
    }


def _validate_deepseek_transport_receipt(
    *,
    receipt: SignedTransportReceipt,
    request_fingerprint: str,
    request_bytes_sha256: str,
    data_attestation_hash: str,
    criterion_id: str,
    observed_model_id: str,
    raw_response: bytes | None,
    raw_response_sha256: str | None = None,
    raw_response_size: int | None = None,
    http_status: int,
    transport_test_only: bool,
) -> None:
    """Validate byte/identity bindings; signature authority is batch-level."""

    if not isinstance(receipt, SignedTransportReceipt):
        raise ProviderContractError(
            "DeepSeek transport receipt binding requires a typed receipt"
        )
    payload = receipt.payload
    if raw_response is not None:
        expected_response_hash = _sha256(raw_response)
        expected_response_size = len(raw_response)
    else:
        expected_response_hash = _sha256_text(
            raw_response_sha256,
            "protected raw response hash",
        )
        expected_response_size = _non_negative_int(
            raw_response_size,
            "protected raw response size",
        )
    if (
        payload.claim_scope
        is not TransportClaimScope.GATEWAY_TLS_REQUEST_RESPONSE_OBSERVATION
        or payload.outcome is not TransportOutcome.SUCCESS
        or payload.provider_id != "deepseek"
        or payload.endpoint_origin != "https://api.deepseek.com"
        or payload.requested_model_id != DEEPSEEK_V4_PRO_MODEL
        or payload.observed_model_id != observed_model_id
        or payload.criterion_id != criterion_id
        or payload.data_attestation_hash != data_attestation_hash
        or payload.request_fingerprint != request_fingerprint
        or payload.request_bytes_hash != request_bytes_sha256
        or payload.response_hash != expected_response_hash
        or payload.response_size != expected_response_size
        or payload.http_status != http_status
        or receipt.envelope.test_only is not transport_test_only
    ):
        raise ProviderContractError("DeepSeek transport receipt binding is invalid")


@dataclass(frozen=True)
class DeepSeekJudgeEvidence(_HashBound):
    request_fingerprint: str
    request_bytes_sha256: str
    data_attestation_hash: str
    response_id: str
    model: str
    system_fingerprint: str
    created: int
    finish_reason: str
    output_json: bytes
    raw_response: bytes = field(repr=False)
    raw_response_sha256: str
    usage: DeepSeekUsage
    reasoning_content_present: bool
    reasoning_content_sha256: str | None
    transport_id: str
    transport_test_only: bool
    received_at: str
    transport_receipt: SignedTransportReceipt | None = None
    authority: str = EXTERNAL_JUDGE_AUTHORITY
    raw_artifact_handling: str = "in_memory_not_in_public_serialization"

    @property
    def output(self) -> dict[str, Any]:
        return _json_object(self.output_json, "DeepSeek Judge output")

    def __post_init__(self) -> None:
        _sha256_text(self.request_fingerprint, "request_fingerprint")
        _sha256_text(self.request_bytes_sha256, "request_bytes_sha256")
        _sha256_text(self.data_attestation_hash, "data_attestation_hash")
        _text(self.response_id, "DeepSeek response_id")
        if self.model != DEEPSEEK_V4_PRO_MODEL:
            raise ProviderContractError("DeepSeek response model is invalid")
        _text(self.system_fingerprint, "DeepSeek system_fingerprint")
        _non_negative_int(self.created, "DeepSeek created")
        if self.finish_reason != "stop":
            raise ProviderContractError("DeepSeek finish_reason is not accepted")
        if not isinstance(self.output_json, bytes) or not self.output_json:
            raise ProviderContractError(
                "DeepSeek canonical Judge output bytes are required"
            )
        output = self.output
        if self.output_json != _canonical(output):
            raise ProviderContractError("DeepSeek Judge output bytes must be canonical")
        if not isinstance(self.raw_response, bytes) or not self.raw_response:
            raise ProviderContractError("DeepSeek raw response bytes are required")
        _sha256_text(self.raw_response_sha256, "raw_response_sha256")
        if self.raw_response_sha256 != _sha256(self.raw_response):
            raise ProviderContractError("DeepSeek raw response hash mismatch")
        if not isinstance(self.usage, DeepSeekUsage):
            raise ProviderContractError("DeepSeek usage is invalid")
        if not isinstance(self.reasoning_content_present, bool):
            raise ProviderContractError("reasoning presence must be boolean")
        if self.reasoning_content_present:
            _sha256_text(
                self.reasoning_content_sha256,
                "reasoning_content_sha256",
            )
        elif self.reasoning_content_sha256 is not None:
            raise ProviderContractError("absent reasoning cannot have a hash")
        _text(self.transport_id, "DeepSeek transport_id")
        if not isinstance(self.transport_test_only, bool):
            raise ProviderContractError("transport_test_only must be boolean")
        _text(self.received_at, "DeepSeek received_at")
        if self.authority != EXTERNAL_JUDGE_AUTHORITY:
            raise ProviderContractError("Judge authority boundary is invalid")
        if self.raw_artifact_handling != "in_memory_not_in_public_serialization":
            raise ProviderContractError("DeepSeek raw artifact handling is invalid")
        derived = _deepseek_response_derivatives(self.raw_response)
        if (
            self.response_id != derived["response_id"]
            or self.model != derived["model"]
            or self.system_fingerprint != derived["system_fingerprint"]
            or self.created != derived["created"]
            or self.finish_reason != derived["finish_reason"]
            or output != derived["output"]
            or self.usage != derived["usage"]
            or self.reasoning_content_present
            is not derived["reasoning_content_present"]
            or self.reasoning_content_sha256 != derived["reasoning_content_sha256"]
        ):
            raise ProviderContractError(
                "DeepSeek evidence fields do not match raw response"
            )
        if self.transport_receipt is not None:
            _validate_deepseek_transport_receipt(
                receipt=self.transport_receipt,
                request_fingerprint=self.request_fingerprint,
                request_bytes_sha256=self.request_bytes_sha256,
                data_attestation_hash=self.data_attestation_hash,
                criterion_id=output["criterion_id"],
                observed_model_id=self.model,
                raw_response=self.raw_response,
                http_status=200,
                transport_test_only=self.transport_test_only,
            )

    def _body(self) -> dict[str, Any]:
        return {
            "request_fingerprint": self.request_fingerprint,
            "request_bytes_sha256": self.request_bytes_sha256,
            "data_attestation_hash": self.data_attestation_hash,
            "response_id": self.response_id,
            "model": self.model,
            "system_fingerprint": self.system_fingerprint,
            "created": self.created,
            "finish_reason": self.finish_reason,
            "output": self.output,
            "raw_response_sha256": self.raw_response_sha256,
            "usage": self.usage.to_dict(),
            "reasoning_content_present": self.reasoning_content_present,
            "reasoning_content_sha256": self.reasoning_content_sha256,
            "transport_id": self.transport_id,
            "transport_test_only": self.transport_test_only,
            "received_at": self.received_at,
            "transport_receipt": (
                self.transport_receipt.to_dict()
                if self.transport_receipt is not None
                else None
            ),
            "authority": self.authority,
            "raw_artifact_handling": self.raw_artifact_handling,
            "claim_scope": "contract_only",
        }


_DEEPSEEK_PUBLIC_EVIDENCE_FIELDS = {
    "request_fingerprint",
    "request_bytes_sha256",
    "data_attestation_hash",
    "response_id",
    "model",
    "system_fingerprint",
    "created",
    "finish_reason",
    "output",
    "raw_response_sha256",
    "usage",
    "reasoning_content_present",
    "reasoning_content_sha256",
    "transport_id",
    "transport_test_only",
    "received_at",
    "transport_receipt",
    "authority",
    "raw_artifact_handling",
    "claim_scope",
    "contract_hash",
}


@dataclass(frozen=True)
class ProtectedDeepSeekJudgeEvidence(_HashBound):
    """Public Judge evidence bound to a path-free protected-raw receipt."""

    public_evidence_json: bytes = field(repr=False)
    source_evidence_hash: str
    raw_artifact_receipt: ProtectedRawArtifactReceipt

    @property
    def public_evidence(self) -> dict[str, Any]:
        return _json_object(
            self.public_evidence_json,
            "protected DeepSeek public evidence",
        )

    @property
    def transport_receipt(self) -> SignedTransportReceipt | None:
        raw = self.public_evidence["transport_receipt"]
        if raw is None:
            return None
        try:
            return SignedTransportReceipt.from_dict(raw)
        except (TrustContractError, TypeError, ValueError) as error:
            raise ProviderContractError(
                "protected DeepSeek transport receipt is invalid"
            ) from error

    def __post_init__(self) -> None:
        if (
            not isinstance(self.public_evidence_json, bytes)
            or not self.public_evidence_json
        ):
            raise ProviderContractError(
                "protected DeepSeek public evidence bytes are required"
            )
        public = self.public_evidence
        if (
            set(public) != _DEEPSEEK_PUBLIC_EVIDENCE_FIELDS
            or self.public_evidence_json != _canonical(public)
        ):
            raise ProviderContractError(
                "protected DeepSeek public evidence schema is invalid"
            )
        _sha256_text(self.source_evidence_hash, "source_evidence_hash")
        embedded_contract_hash = public["contract_hash"]
        _sha256_text(
            embedded_contract_hash,
            "protected DeepSeek public evidence contract_hash",
        )
        public_body = {
            key: value for key, value in public.items() if key != "contract_hash"
        }
        if (
            _sha256(_canonical(public_body)) != embedded_contract_hash
            or self.source_evidence_hash != embedded_contract_hash
        ):
            raise ProviderContractError(
                "protected DeepSeek public evidence hash mismatch"
            )
        if public["raw_artifact_handling"] != ("in_memory_not_in_public_serialization"):
            raise ProviderContractError(
                "protected DeepSeek source evidence handling is invalid"
            )
        if public["authority"] != EXTERNAL_JUDGE_AUTHORITY:
            raise ProviderContractError("Judge authority boundary is invalid")
        if public["claim_scope"] != "contract_only":
            raise ProviderContractError(
                "protected DeepSeek source evidence claim scope is invalid"
            )
        _sha256_text(
            public["request_bytes_sha256"],
            "protected DeepSeek request_bytes_sha256",
        )
        _sha256_text(
            public["data_attestation_hash"],
            "protected DeepSeek data_attestation_hash",
        )
        _text(public["transport_id"], "protected DeepSeek transport_id")
        if not isinstance(public["transport_test_only"], bool):
            raise ProviderContractError(
                "protected DeepSeek transport_test_only must be boolean"
            )
        _text(public["received_at"], "protected DeepSeek received_at")
        if not isinstance(self.raw_artifact_receipt, ProtectedRawArtifactReceipt):
            raise ProviderContractError(
                "protected DeepSeek raw artifact receipt is required"
            )
        if (
            public["raw_response_sha256"] != self.raw_artifact_receipt.raw_sha256
            or self.source_evidence_hash
            != self.raw_artifact_receipt.source_evidence_hash
            or public["request_fingerprint"]
            != self.raw_artifact_receipt.request_fingerprint
        ):
            raise ProviderContractError(
                "protected DeepSeek raw receipt/source binding mismatch"
            )
        transport_receipt = self.transport_receipt
        if transport_receipt is not None:
            _validate_deepseek_transport_receipt(
                receipt=transport_receipt,
                request_fingerprint=public["request_fingerprint"],
                request_bytes_sha256=public["request_bytes_sha256"],
                data_attestation_hash=public["data_attestation_hash"],
                criterion_id=public["output"]["criterion_id"],
                observed_model_id=public["model"],
                raw_response=None,
                raw_response_sha256=public["raw_response_sha256"],
                raw_response_size=self.raw_artifact_receipt.byte_length,
                http_status=200,
                transport_test_only=public["transport_test_only"],
            )

    def _body(self) -> dict[str, Any]:
        return {
            "judge_evidence": self.public_evidence,
            "raw_artifact_receipt": self.raw_artifact_receipt.to_dict(),
            "raw_artifact_handling": "write_once_protected_store_receipt",
            "claim_scope": "protected_external_judge_provider_evidence",
        }


def seal_protected_deepseek_evidence(
    *,
    evidence: DeepSeekJudgeEvidence,
    store: ProtectedRawArtifactStore,
    handling_manifest: RawArtifactHandlingManifest,
    artifact_id: str,
) -> ProtectedDeepSeekJudgeEvidence:
    if not isinstance(evidence, DeepSeekJudgeEvidence):
        raise ProviderContractError("typed DeepSeek Judge evidence is required")
    if not isinstance(store, ProtectedRawArtifactStore):
        raise ProviderContractError("protected raw artifact store is required")
    receipt = store.seal(
        artifact_id=artifact_id,
        raw=evidence.raw_response,
        handling_manifest=handling_manifest,
        source_evidence_hash=evidence.contract_hash,
        request_fingerprint=evidence.request_fingerprint,
    )
    return ProtectedDeepSeekJudgeEvidence(
        public_evidence_json=_canonical(evidence.to_dict()),
        source_evidence_hash=evidence.contract_hash,
        raw_artifact_receipt=receipt,
    )


def verify_protected_deepseek_evidence(
    *,
    evidence: ProtectedDeepSeekJudgeEvidence,
    store: ProtectedRawArtifactStore,
    handling_manifest: RawArtifactHandlingManifest,
) -> ProtectedDeepSeekJudgeEvidence:
    if not isinstance(evidence, ProtectedDeepSeekJudgeEvidence):
        raise ProviderContractError("protected DeepSeek Judge evidence is required")
    if not isinstance(store, ProtectedRawArtifactStore):
        raise ProviderContractError("protected raw artifact store is required")
    raw_response = store.read_verified(
        receipt=evidence.raw_artifact_receipt,
        handling_manifest=handling_manifest,
    )
    derived = _deepseek_response_derivatives(raw_response)
    public = evidence.public_evidence
    if (
        public["response_id"] != derived["response_id"]
        or public["model"] != derived["model"]
        or public["system_fingerprint"] != derived["system_fingerprint"]
        or public["created"] != derived["created"]
        or public["finish_reason"] != derived["finish_reason"]
        or public["output"] != derived["output"]
        or public["usage"] != derived["usage"].to_dict()
        or public["reasoning_content_present"]
        is not derived["reasoning_content_present"]
        or public["reasoning_content_sha256"] != derived["reasoning_content_sha256"]
    ):
        raise ProviderContractError(
            "protected DeepSeek evidence fields do not match raw response"
        )
    return evidence


class DeepSeekV4ProJudgeAdapter:
    """Request/parse boundary for an external, non-Harness Judge."""

    model = DEEPSEEK_V4_PRO_MODEL
    authority = EXTERNAL_JUDGE_AUTHORITY

    def build_request(
        self,
        *,
        system_prompt: str,
        user_content: str,
        criterion_id: str,
        allowed_evidence_refs: Sequence[str],
        data_attestation: DataHandlingAttestation,
        temperature: float | None = None,
    ) -> DeepSeekJudgeRequest:
        if "json" not in _text(system_prompt, "system_prompt").casefold():
            raise ProviderContractError(
                "DeepSeek JSON mode requires JSON in the prompt"
            )
        _text(user_content, "user_content")
        refs = tuple(allowed_evidence_refs)
        expected_input_hash = deepseek_input_sha256(
            system_prompt=system_prompt,
            user_content=user_content,
            criterion_id=criterion_id,
            allowed_evidence_refs=refs,
        )
        if not isinstance(data_attestation, DataHandlingAttestation):
            raise ProviderContractError("data handling attestation is required")
        if data_attestation.deidentified is not True:
            raise ProviderContractError(
                "DeepSeek input requires deidentified attestation"
            )
        if data_attestation.non_sensitive is not True:
            raise ProviderContractError(
                "DeepSeek input requires non_sensitive attestation"
            )
        if data_attestation.input_sha256 != expected_input_hash:
            raise ProviderContractError(
                "data attestation input hash does not match request"
            )
        if temperature is not None:
            if (
                isinstance(temperature, bool)
                or not isinstance(temperature, (int, float))
                or not math.isfinite(float(temperature))
                or not 0 <= float(temperature) <= 2
            ):
                raise ProviderContractError("requested temperature is invalid")
            requested_temperature = float(temperature)
            temperature_disposition = "ignored_unsupported_in_thinking_mode"
        else:
            requested_temperature = None
            temperature_disposition = "not_set_unsupported_in_thinking_mode"
        body = {
            "model": self.model,
            "messages": [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_content},
            ],
            "thinking": {"type": "enabled"},
            "reasoning_effort": "high",
            "response_format": {"type": "json_object"},
            "stream": False,
        }
        return DeepSeekJudgeRequest(
            url=DEEPSEEK_CHAT_URL,
            headers=(("Content-Type", "application/json"),),
            body_bytes=_canonical(body),
            criterion_id=criterion_id,
            allowed_evidence_refs=refs,
            data_attestation=data_attestation,
            effective_seed="unsupported",
            requested_temperature=requested_temperature,
            temperature_disposition=temperature_disposition,
        )

    def execute(
        self,
        *,
        request: DeepSeekJudgeRequest,
        transport: DeepSeekTransport,
    ) -> DeepSeekJudgeEvidence:
        """Delegate I/O to an injected transport; this class has no network."""

        if not isinstance(request, DeepSeekJudgeRequest):
            raise ProviderContractError("DeepSeek request contract is required")
        request._validate_contract()
        transport_id = _text(
            getattr(transport, "transport_id", None),
            "DeepSeek transport_id",
        )
        test_only = getattr(transport, "test_only", None)
        if not isinstance(test_only, bool):
            raise ProviderContractError(
                "DeepSeek transport must explicitly declare test_only"
            )
        response = transport.send(request)
        if not isinstance(response, DeepSeekTransportResponse):
            raise ProviderContractError(
                "DeepSeek transport returned an invalid response"
            )
        if response.status_code != 200:
            raise ProviderContractError(
                f"DeepSeek transport returned HTTP {response.status_code}"
            )
        if not test_only and response.transport_receipt is None:
            raise ProviderContractError(
                "production DeepSeek transport requires a signed transport receipt"
            )
        return self.parse_response(
            request=request,
            transport_id=transport_id,
            transport_test_only=test_only,
            received_at=response.received_at,
            raw_response=response.raw_response,
            transport_receipt=response.transport_receipt,
            http_status=response.status_code,
        )

    def parse_response(
        self,
        *,
        request: DeepSeekJudgeRequest,
        transport_id: str,
        transport_test_only: bool,
        received_at: str,
        raw_response: bytes,
        transport_receipt: SignedTransportReceipt | None = None,
        http_status: int = 200,
    ) -> DeepSeekJudgeEvidence:
        if not isinstance(request, DeepSeekJudgeRequest):
            raise ProviderContractError("DeepSeek request contract is required")
        request._validate_contract()
        derived = _deepseek_response_derivatives(raw_response)
        output = derived["output"]
        if output["criterion_id"] != request.criterion_id or not set(
            output["evidence_refs"]
        ) <= set(request.allowed_evidence_refs):
            raise ProviderContractError(
                "DeepSeek Judge output identity/evidence refs are invalid"
            )
        if transport_receipt is not None:
            _validate_deepseek_transport_receipt(
                receipt=transport_receipt,
                request_fingerprint=request.request_fingerprint,
                request_bytes_sha256=_sha256(request.body_bytes),
                data_attestation_hash=request.data_attestation.contract_hash,
                criterion_id=request.criterion_id,
                observed_model_id=derived["model"],
                raw_response=raw_response,
                http_status=http_status,
                transport_test_only=transport_test_only,
            )
        return DeepSeekJudgeEvidence(
            request_fingerprint=request.request_fingerprint,
            request_bytes_sha256=_sha256(request.body_bytes),
            data_attestation_hash=request.data_attestation.contract_hash,
            response_id=derived["response_id"],
            model=derived["model"],
            system_fingerprint=derived["system_fingerprint"],
            created=derived["created"],
            finish_reason=derived["finish_reason"],
            output_json=_canonical(output),
            raw_response=raw_response,
            raw_response_sha256=_sha256(raw_response),
            usage=derived["usage"],
            reasoning_content_present=derived["reasoning_content_present"],
            reasoning_content_sha256=derived["reasoning_content_sha256"],
            transport_id=_text(transport_id, "DeepSeek transport_id"),
            transport_test_only=transport_test_only,
            received_at=_text(received_at, "DeepSeek received_at"),
            transport_receipt=transport_receipt,
        )


def require_production_deepseek_evidence(
    evidence: DeepSeekJudgeEvidence | ProtectedDeepSeekJudgeEvidence,
) -> DeepSeekJudgeEvidence | ProtectedDeepSeekJudgeEvidence:
    if isinstance(evidence, ProtectedDeepSeekJudgeEvidence):
        public = evidence.public_evidence
        if public["transport_test_only"]:
            raise ProviderContractError(
                "test_only DeepSeek transport cannot produce formal evidence"
            )
    elif not isinstance(evidence, DeepSeekJudgeEvidence):
        raise ProviderContractError("production requires typed DeepSeek Judge evidence")
    elif evidence.transport_test_only:
        raise ProviderContractError(
            "test_only DeepSeek transport cannot produce formal evidence"
        )
    raise ProviderContractError(
        "production DeepSeek evidence requires aggregate production-authorized "
        "transport batch authorization; a per-call receipt remains contract-only"
    )


__all__ = [
    "CODEX_SUBJECT_CLAIM_SCOPE",
    "CODEX_SUBSCRIPTION_SUBJECT_MODEL",
    "DEEPSEEK_CHAT_URL",
    "DEEPSEEK_V4_PRO_JUDGE_CARD_ID",
    "DEEPSEEK_V4_PRO_MODEL",
    "DataHandlingAttestation",
    "DeepSeekJudgeEvidence",
    "ProtectedDeepSeekJudgeEvidence",
    "DeepSeekJudgeRequest",
    "DeepSeekTransport",
    "DeepSeekTransportResponse",
    "DeepSeekUsage",
    "DeepSeekV4ProJudgeAdapter",
    "EXTERNAL_JUDGE_AUTHORITY",
    "JUDGE_OUTPUT_SCHEMA",
    "JUDGE_OUTPUT_SCHEMA_SHA256",
    "ProviderContractError",
    "CodexSubjectExecutionSeal",
    "CodexSubjectRequest",
    "CodexSubscriptionCommand",
    "build_codex_subscription_command",
    "deepseek_input_sha256",
    "require_production_deepseek_evidence",
    "seal_protected_deepseek_evidence",
    "seal_codex_subject_execution",
    "verify_protected_deepseek_evidence",
]
