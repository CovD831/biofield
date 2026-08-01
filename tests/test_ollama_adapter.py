from __future__ import annotations

import json
from collections.abc import Mapping
from typing import Any

import pytest

from biofield.model_probe import ProbeArm, build_a0_contrasts
from biofield.ollama_adapter import OllamaAdapter, OllamaAdapterError
from biofield.probe_assets import ProbeAssetResolver


class RecordingTransport:
    def __init__(self, response: Mapping[str, Any]) -> None:
        self.response = response
        self.calls: list[tuple[str, dict[str, Any], float]] = []

    def __call__(
        self,
        url: str,
        payload: Mapping[str, Any],
        timeout_seconds: float,
    ) -> Mapping[str, Any]:
        self.calls.append((url, dict(payload), timeout_seconds))
        return self.response


def _structured_answer() -> dict[str, object]:
    return {
        "decision": "hold",
        "key_facts": [],
        "contradictions": [],
        "behavior_signature": {
            "requirement_id": "contradiction_resolution",
            "action_type": "cross_check",
        },
    }


def _provider_response(
    structured_answer: Mapping[str, Any] | None = None,
) -> dict[str, object]:
    answer = structured_answer or _structured_answer()
    return {
        "model": "qwen3:8b",
        "message": {
            "role": "assistant",
            "content": json.dumps(answer, ensure_ascii=False),
        },
        "done": True,
        "done_reason": "stop",
        "prompt_eval_count": 321,
        "eval_count": 87,
        "total_duration": 1_000_000,
        "load_duration": 100_000,
        "prompt_eval_duration": 400_000,
        "eval_duration": 500_000,
    }


def test_adapter_builds_a_schema_bound_non_thinking_request() -> None:
    transport = RecordingTransport(_provider_response())
    resolver = ProbeAssetResolver()
    adapter = OllamaAdapter(
        model_id="qwen3:8b",
        resolver=resolver,
        base_seed=4100,
        temperature=0.6,
        num_ctx=8192,
        endpoint="http://127.0.0.1:11434",
        timeout_seconds=90,
        transport=transport,
    )
    arm = ProbeArm.reference()

    response = adapter.invoke(arm)

    assert response.model_id == "qwen3:8b"
    assert response.requirement_id == "contradiction_resolution"
    assert response.action_type == "cross_check"
    assert response.input_tokens == 321
    assert response.output_tokens == 87
    assert response.evidence_score is not None
    assert response.audit is not None
    assert response.audit.effective_seed == 4100
    assert response.audit.provider_model_id == "qwen3:8b"
    assert response.audit.done_reason == "stop"
    assert response.audit.request_fingerprint == resolver.resolve(
        arm
    ).request_fingerprint
    assert len(response.audit.provider_payload_hash) == 64
    assert len(response.audit.provider_response_hash) == 64
    assert response.audit.total_duration_ns == 1_000_000

    assert len(transport.calls) == 1
    url, payload, timeout_seconds = transport.calls[0]
    assert url == "http://127.0.0.1:11434/api/chat"
    assert timeout_seconds == 90
    assert payload["model"] == "qwen3:8b"
    assert payload["stream"] is False
    assert payload["think"] is False
    assert payload["format"] == json.loads(
        resolver.resolve(arm).response_schema_json
    )
    assert payload["options"] == {
        "temperature": 0.6,
        "seed": 4100,
        "num_ctx": 8192,
        "top_p": 0.9,
        "top_k": 40,
        "num_predict": 1024,
        "repeat_penalty": 1.1,
    }
    assert payload["keep_alive"] == "10m"
    messages = payload["messages"]
    assert isinstance(messages, list)
    assert messages[0]["role"] == "system"
    assert messages[-1]["role"] == "user"
    assert any(message["role"] == "assistant" for message in messages)


def test_sampling_arm_changes_only_the_provider_seed_not_request_fingerprint() -> None:
    transport = RecordingTransport(_provider_response())
    resolver = ProbeAssetResolver()
    adapter = OllamaAdapter(
        model_id="qwen3:8b",
        resolver=resolver,
        base_seed=700,
        transport=transport,
    )
    contrast = next(
        item
        for item in build_a0_contrasts(ProbeArm.reference())
        if item.contrast_id == "sampling_noise"
    )

    adapter.invoke(contrast.control)
    adapter.invoke(contrast.treatment)

    control_payload = transport.calls[0][1]
    treatment_payload = transport.calls[1][1]
    assert control_payload["options"]["seed"] == 700
    assert treatment_payload["options"]["seed"] == 701
    assert resolver.resolve(contrast.control).request_fingerprint == resolver.resolve(
        contrast.treatment
    ).request_fingerprint


def test_generic_structured_invocation_reuses_the_strict_provider_contract() -> None:
    transport = RecordingTransport(
        _provider_response({"selected_action": "inspect_facts"})
    )
    adapter = OllamaAdapter(
        model_id="qwen3:8b",
        resolver=ProbeAssetResolver(),
        base_seed=1,
        transport=transport,
    )
    schema = {
        "type": "object",
        "additionalProperties": False,
        "required": ["selected_action"],
        "properties": {
            "selected_action": {
                "type": "string",
                "enum": [
                    "inspect_facts",
                    "cross_check_conflicts",
                    "synthesize_decision",
                ],
            }
        },
    }

    result = adapter.invoke_structured(
        system_prompt="Choose one next action.",
        messages=({"role": "user", "content": "All priorities are equal."},),
        response_schema=schema,
        effective_seed=9900,
        request_fingerprint="a" * 64,
    )

    assert result.structured_output == {"selected_action": "inspect_facts"}
    assert result.input_tokens == 321
    assert result.output_tokens == 87
    assert result.audit.effective_seed == 9900
    assert result.audit.request_fingerprint == "a" * 64
    payload = transport.calls[0][1]
    assert payload["messages"] == [
        {"role": "system", "content": "Choose one next action."},
        {"role": "user", "content": "All priorities are equal."},
    ]
    assert payload["format"] == schema
    assert payload["options"]["seed"] == 9900


@pytest.mark.parametrize(
    ("provider_response", "message"),
    [
        (
            {**_provider_response(), "model": "other-model"},
            "model mismatch",
        ),
        ({**_provider_response(), "done": False}, "done=true"),
        ({**_provider_response(), "done_reason": "length"}, "stop cleanly"),
        (
            {
                **_provider_response(),
                "message": {"role": "tool", "content": "{}"},
            },
            "assistant role",
        ),
        (
            {
                **_provider_response(),
                "message": {"role": "assistant", "content": "not-json"},
            },
            "valid JSON object",
        ),
        (
            {
                **_provider_response(),
                "message": {"role": "assistant"},
            },
            "message.content",
        ),
        (
            {
                **_provider_response(),
                "message": {"role": "assistant", "content": "[]"},
            },
            "JSON object",
        ),
        (
            {**_provider_response(), "prompt_eval_count": -1},
            "prompt_eval_count",
        ),
        (
            {key: value for key, value in _provider_response().items() if key != "eval_count"},
            "eval_count",
        ),
        (
            _provider_response(
                {
                    **_structured_answer(),
                    "decision": "invented_decision",
                }
            ),
            "response schema",
        ),
    ],
)
def test_adapter_rejects_malformed_provider_responses(
    provider_response: Mapping[str, Any],
    message: str,
) -> None:
    adapter = OllamaAdapter(
        model_id="qwen3:8b",
        resolver=ProbeAssetResolver(),
        transport=RecordingTransport(provider_response),
    )

    with pytest.raises(OllamaAdapterError, match=message):
        adapter.invoke(ProbeArm.reference())


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("model_id", ""),
        ("base_seed", -1),
        ("temperature", -0.1),
        ("num_ctx", 0),
        ("timeout_seconds", 0),
    ],
)
def test_adapter_rejects_invalid_runtime_configuration(
    field: str,
    value: object,
) -> None:
    kwargs: dict[str, object] = {
        "model_id": "qwen3:8b",
        "resolver": ProbeAssetResolver(),
        "base_seed": 1,
        "temperature": 0.6,
        "num_ctx": 8192,
        "timeout_seconds": 90,
        "transport": RecordingTransport(_provider_response()),
    }
    kwargs[field] = value

    with pytest.raises(ValueError):
        OllamaAdapter(**kwargs)  # type: ignore[arg-type]
