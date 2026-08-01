from __future__ import annotations

import argparse
import hashlib
import json
from collections.abc import Mapping
from dataclasses import asdict, is_dataclass
from pathlib import Path
from typing import Any, Protocol

from .contracts import ActionStatus
from .evidence_task import EvidenceTaskBundle, load_task_bundle
from .f0 import (
    CONFLICT_REQUIREMENT,
    DECISION_REQUIREMENT,
    FACT_REQUIREMENT,
    F0Execution,
    F0Experiment,
    F0RunConfig,
)
from .ollama_adapter import OllamaAdapter, OllamaAdapterError, StructuredInvocation
from .probe_assets import ProbeAssetResolver


class StructuredAdapter(Protocol):
    model_id: str

    def invoke_structured(
        self,
        *,
        system_prompt: str,
        messages: tuple[Mapping[str, str], ...],
        response_schema: Mapping[str, Any],
        effective_seed: int,
        request_fingerprint: str,
    ) -> StructuredInvocation: ...


class OllamaF0Executor:
    def __init__(
        self,
        *,
        bundle: EvidenceTaskBundle,
        adapter: StructuredAdapter,
        base_seed: int = 9000,
        token_reservation: int | None = None,
    ) -> None:
        if isinstance(base_seed, bool) or not isinstance(base_seed, int) or base_seed < 0:
            raise ValueError("base_seed must be a non-negative integer")
        if token_reservation is None:
            token_reservation = getattr(adapter, "num_ctx", 8192)
        if (
            isinstance(token_reservation, bool)
            or not isinstance(token_reservation, int)
            or token_reservation < 1
        ):
            raise ValueError("token_reservation must be a positive integer")
        self.bundle = bundle
        self.adapter = adapter
        self.base_seed = base_seed
        self.token_reservation = token_reservation
        self.mode = f"ollama:{adapter.model_id}"

    def execute(
        self,
        *,
        requirement_id: str,
        action_id: str,
        cycle: int,
        prior_artifacts: Mapping[str, Mapping[str, Any]],
    ) -> F0Execution:
        schema = _role_schema(self.bundle, requirement_id)
        system_prompt = _system_prompt(requirement_id)
        user_prompt = _user_prompt(
            self.bundle,
            requirement_id=requirement_id,
            prior_artifacts=prior_artifacts,
        )
        seed = self.base_seed + cycle
        fingerprint = _request_fingerprint(
            system_prompt=system_prompt,
            user_prompt=user_prompt,
            schema=schema,
            seed=seed,
        )
        try:
            invocation = self.adapter.invoke_structured(
                system_prompt=system_prompt,
                messages=({"role": "user", "content": user_prompt},),
                response_schema=schema,
                effective_seed=seed,
                request_fingerprint=fingerprint,
            )
        except (OllamaAdapterError, ValueError) as error:
            return F0Execution(
                status=ActionStatus.FAILED,
                artifact={
                    "requirement_id": requirement_id,
                    "action_id": action_id,
                    "error": str(error),
                },
                error=str(error),
            )
        return F0Execution(
            status=ActionStatus.SUCCEEDED,
            artifact=dict(invocation.structured_output),
            input_tokens=invocation.input_tokens,
            output_tokens=invocation.output_tokens,
            latency_ns=invocation.audit.total_duration_ns,
            provider_audit=_audit_mapping(invocation.audit),
        )


def _audit_mapping(audit: Any) -> dict[str, Any]:
    if is_dataclass(audit) and not isinstance(audit, type):
        value = asdict(audit)
    else:
        value = vars(audit)
    return dict(value)


class InjectInvalidFirstExecutor:
    """One-shot F0 fault injection used to verify feedback-driven recovery."""

    def __init__(self, delegate: OllamaF0Executor) -> None:
        self.delegate = delegate
        self.mode = f"injected-invalid-first+{delegate.mode}"
        self.token_reservation = delegate.token_reservation
        self._injected = False

    def execute(
        self,
        *,
        requirement_id: str,
        action_id: str,
        cycle: int,
        prior_artifacts: Mapping[str, Mapping[str, Any]],
    ) -> F0Execution:
        if not self._injected:
            self._injected = True
            return F0Execution(
                status=ActionStatus.SUCCEEDED,
                artifact={"key_facts": []},
            )
        return self.delegate.execute(
            requirement_id=requirement_id,
            action_id=action_id,
            cycle=cycle,
            prior_artifacts=prior_artifacts,
        )


def _role_schema(
    bundle: EvidenceTaskBundle,
    requirement_id: str,
) -> dict[str, Any]:
    field = {
        FACT_REQUIREMENT: "key_facts",
        CONFLICT_REQUIREMENT: "contradictions",
        DECISION_REQUIREMENT: "decision",
    }.get(requirement_id)
    if field is None:
        raise ValueError(f"unknown F0 requirement: {requirement_id}")
    properties = bundle.task.answer_schema.get("properties")
    if not isinstance(properties, Mapping) or not isinstance(
        properties.get(field), Mapping
    ):
        raise ValueError(f"R1 answer schema has no {field!r} property")
    property_schema = dict(properties[field])
    if requirement_id == FACT_REQUIREMENT:
        base_items = property_schema.get("items")
        if not isinstance(base_items, Mapping):
            raise ValueError("R1 key_facts schema must define item properties")
        base_properties = base_items.get("properties")
        if not isinstance(base_properties, Mapping) or not isinstance(
            base_properties.get("citations"), Mapping
        ):
            raise ValueError("R1 key_facts schema must define citations")
        citation_schema = dict(base_properties["citations"])
        citation_schema["minItems"] = 1
        citation_schema["uniqueItems"] = True
        # Ollama's grammar compiler does not currently accept the per-fact
        # oneOf schema. Keep the provider schema inside its supported subset;
        # the prompt exposes the per-ID value contracts and the deterministic
        # verifier remains the final authority.
        property_schema = {
            "type": "array",
            "minItems": len(bundle.task.fact_value_contracts),
            "maxItems": len(bundle.task.fact_value_contracts),
            "items": {
                "type": "object",
                "additionalProperties": False,
                "required": ["fact_id", "value", "citations"],
                "properties": {
                    "fact_id": {
                        "type": "string",
                        "enum": list(bundle.task.fact_value_contracts),
                    },
                    "value": {"type": "string"},
                    "citations": citation_schema,
                },
            },
        }
    return {
        "type": "object",
        "additionalProperties": False,
        "required": [field],
        "properties": {field: property_schema},
    }


def _system_prompt(requirement_id: str) -> str:
    role_instruction = {
        FACT_REQUIREMENT: (
            "Extract only material facts and cite every fact with the supplied material IDs."
        ),
        CONFLICT_REQUIREMENT: (
            "Identify only genuine contradictions between supplied materials."
        ),
        DECISION_REQUIREMENT: (
            "Synthesize the final decision only from verified prior artifacts and materials."
        ),
    }.get(requirement_id)
    if role_instruction is None:
        raise ValueError(f"unknown F0 requirement: {requirement_id}")
    return (
        "You are one fixed-role worker in an auditable evidence workflow. "
        f"{role_instruction} Return only the JSON object required by the schema."
    )


def _user_prompt(
    bundle: EvidenceTaskBundle,
    *,
    requirement_id: str,
    prior_artifacts: Mapping[str, Mapping[str, Any]],
) -> str:
    expected_ids: Mapping[str, Any]
    if requirement_id == FACT_REQUIREMENT:
        expected_ids = {
            "allowed_fact_ids": [item.fact_id for item in bundle.answer_key.key_facts],
            "value_contracts": {
                fact_id: dict(schema)
                for fact_id, schema in bundle.task.fact_value_contracts.items()
            },
            "minimum_citations": {
                item.fact_id: item.minimum_citations
                for item in bundle.answer_key.key_facts
            },
        }
    elif requirement_id == CONFLICT_REQUIREMENT:
        expected_ids = {
            "allowed_contradiction_ids": [
                item.contradiction_id for item in bundle.answer_key.contradictions
            ]
        }
    else:
        expected_ids = {}
    materials = [item.to_dict() for item in bundle.task.materials]
    return (
        f"task: {bundle.task.prompt}\n"
        f"current requirement: {requirement_id}\n"
        f"output identifiers: {json.dumps(expected_ids, ensure_ascii=False, sort_keys=True)}\n"
        f"materials: {json.dumps(materials, ensure_ascii=False, sort_keys=True)}\n"
        "prior verified artifacts: "
        f"{json.dumps(dict(prior_artifacts), ensure_ascii=False, sort_keys=True)}"
    )


def _request_fingerprint(
    *,
    system_prompt: str,
    user_prompt: str,
    schema: Mapping[str, Any],
    seed: int,
) -> str:
    payload = {
        "system_prompt": system_prompt,
        "user_prompt": user_prompt,
        "schema": dict(schema),
        "seed": seed,
    }
    encoded = json.dumps(
        payload,
        ensure_ascii=False,
        allow_nan=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def main() -> int:
    parser = argparse.ArgumentParser(description="Run one local-model F0 episode")
    parser.add_argument("--output-directory", default="runs")
    parser.add_argument("--run-id", required=True)
    parser.add_argument("--task-id", default="cold_chain_readiness")
    parser.add_argument("--model", default="qwen3:8b")
    parser.add_argument("--endpoint", default="http://127.0.0.1:11434")
    parser.add_argument("--seed", type=int, default=9000)
    parser.add_argument("--action-budget", type=int, default=3)
    parser.add_argument("--token-budget", type=int, default=50000)
    parser.add_argument("--token-reservation", type=int, default=8192)
    parser.add_argument("--max-cycles", type=int, default=3)
    parser.add_argument("--inject-invalid-first", action="store_true")
    arguments = parser.parse_args()

    bundle = load_task_bundle(arguments.task_id)
    adapter = OllamaAdapter(
        model_id=arguments.model,
        resolver=ProbeAssetResolver(),
        base_seed=arguments.seed,
        temperature=0.0,
        endpoint=arguments.endpoint,
    )
    executor: Any = OllamaF0Executor(
        bundle=bundle,
        adapter=adapter,
        base_seed=arguments.seed,
        token_reservation=arguments.token_reservation,
    )
    if arguments.inject_invalid_first:
        executor = InjectInvalidFirstExecutor(executor)
    result = F0Experiment(
        bundle=bundle,
        executor=executor,
        config=F0RunConfig(
            output_directory=Path(arguments.output_directory),
            run_id=arguments.run_id,
            action_budget=arguments.action_budget,
            token_budget=arguments.token_budget,
            max_cycles=arguments.max_cycles,
        ),
    ).run()
    print(
        json.dumps(
            {
                "status": result.status.value,
                "reason": result.reason,
                "cycles": result.cycles,
                "complete": result.residual.complete,
                "spent_tokens": str(result.ledger_totals["tokens"].spent),
                "final_state_sha256": result.final_state_sha256,
                "run_directory": str(result.run_directory),
            },
            ensure_ascii=False,
            sort_keys=True,
        )
    )
    return 0 if result.status.value == "completed" else 1


if __name__ == "__main__":
    raise SystemExit(main())
