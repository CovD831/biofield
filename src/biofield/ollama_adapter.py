from __future__ import annotations

import hashlib
import json
import math
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

from jsonschema import Draft202012Validator
from jsonschema.exceptions import SchemaError, ValidationError

from biofield.a0_runner import ModelInvocationAudit, ProbeResponse
from biofield.model_probe import ProbeArm
from biofield.probe_assets import ProbeAssetError, ProbeAssetResolver

JsonTransport = Callable[[str, Mapping[str, Any], float], Mapping[str, Any]]


class OllamaAdapterError(RuntimeError):
    """Raised when Ollama cannot produce one valid normalized A0 response."""


@dataclass(frozen=True)
class StructuredInvocation:
    structured_output: Mapping[str, Any]
    input_tokens: int
    output_tokens: int
    audit: ModelInvocationAudit

    def __post_init__(self) -> None:
        object.__setattr__(self, "structured_output", dict(self.structured_output))
        if not isinstance(self.audit, ModelInvocationAudit):
            raise ValueError("audit must be ModelInvocationAudit")


def _post_json(
    url: str,
    payload: Mapping[str, Any],
    timeout_seconds: float,
) -> Mapping[str, Any]:
    body = json.dumps(
        dict(payload),
        ensure_ascii=False,
        allow_nan=False,
        separators=(",", ":"),
    ).encode("utf-8")
    request = Request(
        url,
        data=body,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urlopen(request, timeout=timeout_seconds) as response:
            response_body = response.read()
    except HTTPError as error:
        detail = error.read().decode("utf-8", errors="replace")
        raise OllamaAdapterError(
            f"Ollama HTTP {error.code}: {detail or error.reason}"
        ) from error
    except (URLError, TimeoutError, OSError) as error:
        raise OllamaAdapterError(f"cannot reach Ollama: {error}") from error

    try:
        value = json.loads(response_body)
    except (UnicodeDecodeError, json.JSONDecodeError) as error:
        raise OllamaAdapterError("Ollama response is not valid JSON") from error
    if not isinstance(value, Mapping):
        raise OllamaAdapterError("Ollama response must be a JSON object")
    return value


def _required_count(value: Any, field_name: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        raise OllamaAdapterError(f"{field_name} must be a non-negative integer")
    return value


def _canonical_hash(value: Mapping[str, Any]) -> str:
    try:
        encoded = json.dumps(
            dict(value),
            ensure_ascii=False,
            allow_nan=False,
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
    except (TypeError, ValueError) as error:
        raise OllamaAdapterError("provider data is not canonical JSON") from error
    return hashlib.sha256(encoded).hexdigest()


class OllamaAdapter:
    """Translate frozen A0 assets to Ollama's local structured chat API."""

    def __init__(
        self,
        *,
        model_id: str,
        resolver: ProbeAssetResolver,
        base_seed: int = 4100,
        temperature: float = 0.6,
        num_ctx: int = 8192,
        top_p: float = 0.9,
        top_k: int = 40,
        num_predict: int = 1024,
        repeat_penalty: float = 1.1,
        endpoint: str = "http://127.0.0.1:11434",
        timeout_seconds: float = 180.0,
        keep_alive: str = "10m",
        transport: JsonTransport = _post_json,
    ) -> None:
        if not isinstance(model_id, str) or not model_id.strip():
            raise ValueError("model_id must be a non-empty string")
        if not isinstance(resolver, ProbeAssetResolver):
            raise ValueError("resolver must be a ProbeAssetResolver")
        if (
            isinstance(base_seed, bool)
            or not isinstance(base_seed, int)
            or base_seed < 0
        ):
            raise ValueError("base_seed must be a non-negative integer")
        if (
            isinstance(temperature, bool)
            or not isinstance(temperature, (int, float))
            or not math.isfinite(temperature)
            or temperature < 0
        ):
            raise ValueError("temperature must be finite and non-negative")
        if isinstance(num_ctx, bool) or not isinstance(num_ctx, int) or num_ctx <= 0:
            raise ValueError("num_ctx must be a positive integer")
        if (
            isinstance(top_p, bool)
            or not isinstance(top_p, (int, float))
            or not math.isfinite(top_p)
            or not 0 < top_p <= 1
        ):
            raise ValueError("top_p must be in (0, 1]")
        if isinstance(top_k, bool) or not isinstance(top_k, int) or top_k <= 0:
            raise ValueError("top_k must be a positive integer")
        if (
            isinstance(num_predict, bool)
            or not isinstance(num_predict, int)
            or num_predict <= 0
        ):
            raise ValueError("num_predict must be a positive integer")
        if (
            isinstance(repeat_penalty, bool)
            or not isinstance(repeat_penalty, (int, float))
            or not math.isfinite(repeat_penalty)
            or repeat_penalty <= 0
        ):
            raise ValueError("repeat_penalty must be finite and positive")
        if (
            isinstance(timeout_seconds, bool)
            or not isinstance(timeout_seconds, (int, float))
            or not math.isfinite(timeout_seconds)
            or timeout_seconds <= 0
        ):
            raise ValueError("timeout_seconds must be finite and positive")
        if not isinstance(endpoint, str) or not endpoint.strip():
            raise ValueError("endpoint must be a non-empty string")
        if not isinstance(keep_alive, str) or not keep_alive.strip():
            raise ValueError("keep_alive must be a non-empty string")
        if not callable(transport):
            raise ValueError("transport must be callable")

        self.model_id = model_id
        self.resolver = resolver
        self.base_seed = base_seed
        self.temperature = float(temperature)
        self.num_ctx = num_ctx
        self.top_p = float(top_p)
        self.top_k = top_k
        self.num_predict = num_predict
        self.repeat_penalty = float(repeat_penalty)
        self.endpoint = endpoint.rstrip("/")
        self.timeout_seconds = float(timeout_seconds)
        self.keep_alive = keep_alive
        self._transport = transport

    def seed_for(self, arm: ProbeArm) -> int:
        if not isinstance(arm, ProbeArm):
            raise ValueError("arm must be a ProbeArm")
        return self.base_seed + arm.sample_id

    def invoke(self, arm: ProbeArm) -> ProbeResponse:
        request = self.resolver.resolve(arm)
        schema = json.loads(request.response_schema_json)
        invocation = self.invoke_structured(
            system_prompt=request.system_prompt,
            messages=tuple(
                {"role": message.role, "content": message.content}
                for message in request.messages
            ),
            response_schema=schema,
            effective_seed=self.seed_for(arm),
            request_fingerprint=request.request_fingerprint,
        )
        try:
            return self.resolver.normalize_response(
                request,
                model_id=self.model_id,
                structured_output=invocation.structured_output,
                input_tokens=invocation.input_tokens,
                output_tokens=invocation.output_tokens,
                audit=invocation.audit,
            )
        except ProbeAssetError as error:
            raise OllamaAdapterError(
                f"response schema validation failed: {error}"
            ) from error

    def invoke_structured(
        self,
        *,
        system_prompt: str,
        messages: Sequence[Mapping[str, str]],
        response_schema: Mapping[str, Any],
        effective_seed: int,
        request_fingerprint: str,
    ) -> StructuredInvocation:
        """Invoke the same strict local contract for another structured probe."""

        if not isinstance(system_prompt, str) or not system_prompt.strip():
            raise ValueError("system_prompt must be a non-empty string")
        if (
            isinstance(effective_seed, bool)
            or not isinstance(effective_seed, int)
            or effective_seed < 0
        ):
            raise ValueError("effective_seed must be a non-negative integer")
        normalized_messages: list[dict[str, str]] = []
        for message in messages:
            if not isinstance(message, Mapping):
                raise ValueError("messages must contain mappings")
            role = message.get("role")
            content = message.get("content")
            if role not in ("user", "assistant"):
                raise ValueError("message role must be user or assistant")
            if not isinstance(content, str) or not content.strip():
                raise ValueError("message content must be non-empty")
            normalized_messages.append({"role": role, "content": content})
        if not normalized_messages:
            raise ValueError("messages cannot be empty")
        if not isinstance(response_schema, Mapping):
            raise ValueError("response_schema must be a mapping")

        schema = dict(response_schema)
        messages_payload = [
            {"role": "system", "content": system_prompt},
            *normalized_messages,
        ]
        payload = {
            "model": self.model_id,
            "messages": messages_payload,
            "format": schema,
            "stream": False,
            "think": False,
            "options": {
                "temperature": self.temperature,
                "seed": effective_seed,
                "num_ctx": self.num_ctx,
                "top_p": self.top_p,
                "top_k": self.top_k,
                "num_predict": self.num_predict,
                "repeat_penalty": self.repeat_penalty,
            },
            "keep_alive": self.keep_alive,
        }
        provider_response = self._transport(
            f"{self.endpoint}/api/chat",
            payload,
            self.timeout_seconds,
        )
        if not isinstance(provider_response, Mapping):
            raise OllamaAdapterError("Ollama response must be a JSON object")

        provider_model_id = provider_response.get("model")
        if provider_model_id != self.model_id:
            raise OllamaAdapterError(
                f"Ollama model mismatch: expected {self.model_id}, "
                f"received {provider_model_id!r}"
            )
        if provider_response.get("done") is not True:
            raise OllamaAdapterError("Ollama response must report done=true")
        done_reason = provider_response.get("done_reason")
        if done_reason != "stop":
            raise OllamaAdapterError(
                f"Ollama response did not stop cleanly: {done_reason!r}"
            )

        input_tokens = _required_count(
            provider_response.get("prompt_eval_count"),
            "prompt_eval_count",
        )
        output_tokens = _required_count(
            provider_response.get("eval_count"),
            "eval_count",
        )
        total_duration_ns = _required_count(
            provider_response.get("total_duration"),
            "total_duration",
        )
        load_duration_ns = _required_count(
            provider_response.get("load_duration"),
            "load_duration",
        )
        prompt_eval_duration_ns = _required_count(
            provider_response.get("prompt_eval_duration"),
            "prompt_eval_duration",
        )
        eval_duration_ns = _required_count(
            provider_response.get("eval_duration"),
            "eval_duration",
        )
        message = provider_response.get("message")
        if not isinstance(message, Mapping):
            raise OllamaAdapterError("Ollama response is missing message")
        if message.get("role") != "assistant":
            raise OllamaAdapterError("Ollama message must have the assistant role")
        content = message.get("content")
        if not isinstance(content, str) or not content.strip():
            raise OllamaAdapterError("Ollama response is missing message.content")
        try:
            structured_output = json.loads(content)
        except json.JSONDecodeError as error:
            raise OllamaAdapterError(
                "Ollama message.content must be a valid JSON object"
            ) from error
        if not isinstance(structured_output, Mapping):
            raise OllamaAdapterError("Ollama message.content must be a JSON object")

        try:
            Draft202012Validator(schema).validate(dict(structured_output))
        except SchemaError as error:
            raise OllamaAdapterError("response schema is invalid") from error
        except ValidationError as error:
            location = ".".join(str(item) for item in error.absolute_path) or "<root>"
            raise OllamaAdapterError(
                f"response schema validation failed at {location}: {error.message}"
            ) from error

        audit = ModelInvocationAudit(
            request_fingerprint=request_fingerprint,
            provider_payload_hash=_canonical_hash(payload),
            provider_response_hash=_canonical_hash(provider_response),
            effective_seed=effective_seed,
            provider_model_id=provider_model_id,
            done_reason=done_reason,
            total_duration_ns=total_duration_ns,
            load_duration_ns=load_duration_ns,
            prompt_eval_duration_ns=prompt_eval_duration_ns,
            eval_duration_ns=eval_duration_ns,
        )
        return StructuredInvocation(
            structured_output=structured_output,
            input_tokens=input_tokens,
            output_tokens=output_tokens,
            audit=audit,
        )
