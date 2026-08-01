from __future__ import annotations

import argparse
import hashlib
import json
import math
import platform
import re
import sys
from collections import Counter, defaultdict
from collections.abc import Sequence
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path
from time import perf_counter
from typing import Any, Literal

from biofield.a0_runner import ExecutionOrder, ModelInvocationAudit
from biofield.artifacts import RunArtifactStore
from biofield.model_probe import ProbeArm
from biofield.ollama_adapter import OllamaAdapter
from biofield.probe_assets import ProbeAssetResolver

ACTION_CONTRAST_IDS = (
    "sampling_noise",
    "execution_history",
    "manual_role",
    "role_channel",
)
ACTION_ENUM = (
    "inspect_facts",
    "cross_check_conflicts",
    "synthesize_decision",
)
_TARGET_TRANSITIONS = {
    "sampling_noise": ("inspect_facts", "inspect_facts"),
    "execution_history": ("inspect_facts", "cross_check_conflicts"),
    "manual_role": ("inspect_facts", "cross_check_conflicts"),
    "role_channel": ("cross_check_conflicts", "cross_check_conflicts"),
}
_SAFE_IDENTIFIER = re.compile(r"^[A-Za-z0-9_.-]+$")
_BASE_SYSTEM_PROMPT = (
    "你是证据审查工作流中的路由 Agent。你现在只选择下一项会被环境执行的动作，"
    "不得提前完成整项任务，不得输出解释。"
)
_HISTORY_TIE_BREAK = (
    "三个需求的数值优先级相同时，沿用对话历史或系统中已经形成的工作倾向；"
    "没有倾向时使用稳定判断。"
)
_CONFLICT_ROLE = (
    "固定工作倾向：优先交叉核验相互矛盾且需要复查的陈述；比较日期、状态和来源，"
    "并标记争议。"
)


@dataclass(frozen=True)
class ActionChoiceArm:
    run_id: str
    task_id: str
    agent_label: str
    history_id: str
    manual_conflict_role: bool
    sample_id: int

    def __post_init__(self) -> None:
        for value in (self.run_id, self.task_id, self.agent_label, self.history_id):
            if not isinstance(value, str) or not value:
                raise ValueError("action arm identifiers must be non-empty")
        if self.sample_id < 0:
            raise ValueError("sample_id cannot be negative")


@dataclass(frozen=True)
class ActionChoicePair:
    pair_id: str
    contrast_id: str
    task_id: str
    agent_label: str
    repeat_index: int
    primary_seed: int
    alternate_seed: int
    execution_order: ExecutionOrder
    control: ActionChoiceArm
    treatment: ActionChoiceArm

    @property
    def control_seed(self) -> int:
        return self.primary_seed

    @property
    def treatment_seed(self) -> int:
        return (
            self.alternate_seed
            if self.contrast_id == "sampling_noise"
            else self.primary_seed
        )


@dataclass(frozen=True)
class ActionChoiceRequest:
    run_id: str
    task_id: str
    system_prompt: str
    messages: tuple[dict[str, str], ...]
    response_schema: dict[str, Any]
    request_fingerprint: str

    def __post_init__(self) -> None:
        object.__setattr__(self, "messages", tuple(dict(item) for item in self.messages))
        object.__setattr__(self, "response_schema", dict(self.response_schema))


@dataclass(frozen=True)
class ActionChoiceResult:
    status: Literal["completed", "failed"]
    selected_action: str | None
    latency_ms: float
    input_tokens: int | None = None
    output_tokens: int | None = None
    content: str | None = None
    audit: ModelInvocationAudit | None = None
    failure_type: str | None = None
    failure_message: str | None = None

    def __post_init__(self) -> None:
        if self.status not in ("completed", "failed"):
            raise ValueError("invalid action result status")
        if not math.isfinite(self.latency_ms) or self.latency_ms < 0:
            raise ValueError("latency_ms must be finite and non-negative")
        if self.status == "completed":
            if self.selected_action not in ACTION_ENUM:
                raise ValueError("completed result requires a supported action")
            if self.failure_type is not None or self.failure_message is not None:
                raise ValueError("completed result cannot contain failure metadata")
        else:
            if self.selected_action is not None:
                raise ValueError("failed result cannot contain an action")
            if not self.failure_type or not self.failure_message:
                raise ValueError("failed result requires failure metadata")


@dataclass(frozen=True)
class ActionPairResult:
    pair: ActionChoicePair
    control: ActionChoiceResult
    treatment: ActionChoiceResult


def _validate_identifiers(values: tuple[str, ...], name: str) -> None:
    if not values or len(set(values)) != len(values):
        raise ValueError(f"{name} must be non-empty and unique")
    if any(
        not isinstance(value, str)
        or _SAFE_IDENTIFIER.fullmatch(value) is None
        for value in values
    ):
        raise ValueError(f"{name} contains an unsafe identifier")


def _arms_for(
    contrast_id: str,
    *,
    pair_id: str,
    task_id: str,
    agent_label: str,
) -> tuple[ActionChoiceArm, ActionChoiceArm]:
    common = {
        "task_id": task_id,
        "agent_label": agent_label,
        "sample_id": 0,
    }
    if contrast_id == "sampling_noise":
        control = ActionChoiceArm(
            run_id=f"{pair_id}.control",
            history_id="history.neutral.v1",
            manual_conflict_role=False,
            **common,
        )
        treatment = ActionChoiceArm(
            run_id=f"{pair_id}.treatment",
            history_id="history.neutral.v1",
            manual_conflict_role=False,
            **{**common, "sample_id": 1},
        )
    elif contrast_id == "execution_history":
        control = ActionChoiceArm(
            run_id=f"{pair_id}.control",
            history_id="history.common.v1",
            manual_conflict_role=False,
            **common,
        )
        treatment = ActionChoiceArm(
            run_id=f"{pair_id}.treatment",
            history_id="history.specialized.v1",
            manual_conflict_role=False,
            **common,
        )
    elif contrast_id == "manual_role":
        control = ActionChoiceArm(
            run_id=f"{pair_id}.control",
            history_id="history.neutral.v1",
            manual_conflict_role=False,
            **common,
        )
        treatment = ActionChoiceArm(
            run_id=f"{pair_id}.treatment",
            history_id="history.neutral.v1",
            manual_conflict_role=True,
            **common,
        )
    elif contrast_id == "role_channel":
        control = ActionChoiceArm(
            run_id=f"{pair_id}.control",
            history_id="history.specialized.v1",
            manual_conflict_role=False,
            **common,
        )
        treatment = ActionChoiceArm(
            run_id=f"{pair_id}.treatment",
            history_id="history.neutral.v1",
            manual_conflict_role=True,
            **common,
        )
    else:
        raise ValueError(f"unsupported action contrast: {contrast_id}")
    return control, treatment


def build_action_schedule(
    *,
    task_ids: tuple[str, ...],
    agent_labels: tuple[str, ...],
    repeats: int,
    base_seed: int,
    seed_stride: int = 100,
) -> tuple[ActionChoicePair, ...]:
    _validate_identifiers(task_ids, "task_ids")
    _validate_identifiers(agent_labels, "agent_labels")
    if isinstance(repeats, bool) or not isinstance(repeats, int) or repeats <= 0:
        raise ValueError("repeats must be a positive integer")
    if isinstance(base_seed, bool) or not isinstance(base_seed, int) or base_seed < 0:
        raise ValueError("base_seed must be a non-negative integer")
    if seed_stride < 2:
        raise ValueError("seed_stride must be at least two")

    schedule: list[ActionChoicePair] = []
    task_count = len(task_ids)
    agent_count = len(agent_labels)
    for repeat_offset in range(repeats):
        for task_index, task_id in enumerate(task_ids):
            for agent_index, agent_label in enumerate(agent_labels):
                block_index = (
                    repeat_offset * task_count * agent_count
                    + task_index * agent_count
                    + agent_index
                )
                primary_seed = base_seed + block_index * seed_stride
                alternate_seed = primary_seed + 1
                for contrast_index, contrast_id in enumerate(ACTION_CONTRAST_IDS):
                    pair_id = (
                        f"a0a.{contrast_id}.{task_id}.{agent_label}."
                        f"rep{repeat_offset + 1:02d}"
                    )
                    control, treatment = _arms_for(
                        contrast_id,
                        pair_id=pair_id,
                        task_id=task_id,
                        agent_label=agent_label,
                    )
                    offset = task_index * agent_count + agent_index + contrast_index
                    control_first = (offset + repeat_offset) % 2 == 0
                    schedule.append(
                        ActionChoicePair(
                            pair_id=pair_id,
                            contrast_id=contrast_id,
                            task_id=task_id,
                            agent_label=agent_label,
                            repeat_index=repeat_offset + 1,
                            primary_seed=primary_seed,
                            alternate_seed=alternate_seed,
                            execution_order=(
                                "control_first"
                                if control_first
                                else "treatment_first"
                            ),
                            control=control,
                            treatment=treatment,
                        )
                    )
    return tuple(schedule)


def resolve_action_request(
    arm: ActionChoiceArm,
    resolver: ProbeAssetResolver,
    *,
    action_order: tuple[str, ...] = ACTION_ENUM,
    menu_order: tuple[str, ...] | None = None,
    schema_order: tuple[str, ...] | None = None,
    use_tie_break: bool = True,
) -> ActionChoiceRequest:
    if not isinstance(arm, ActionChoiceArm):
        raise ValueError("arm must be ActionChoiceArm")
    if len(action_order) != len(ACTION_ENUM) or set(action_order) != set(ACTION_ENUM):
        raise ValueError("action_order must be a permutation of ACTION_ENUM")
    if action_order != ACTION_ENUM and (
        menu_order is not None or schema_order is not None
    ):
        raise ValueError(
            "action_order cannot be combined with menu_order or schema_order"
        )
    resolved_menu_order = action_order if menu_order is None else menu_order
    resolved_schema_order = action_order if schema_order is None else schema_order
    for name, resolved_order in (
        ("menu_order", resolved_menu_order),
        ("schema_order", resolved_schema_order),
    ):
        if (
            len(resolved_order) != len(ACTION_ENUM)
            or set(resolved_order) != set(ACTION_ENUM)
        ):
            raise ValueError(f"{name} must be a permutation of ACTION_ENUM")
    if not isinstance(use_tie_break, bool):
        raise ValueError("use_tie_break must be a boolean")
    source_arm = ProbeArm(
        run_id=arm.run_id,
        system_prompt_id="prompt.common.v1",
        input_id="input.common.v1",
        history_id=arm.history_id,
        agent_label=arm.agent_label,
        task_id=arm.task_id,
        role_induction="history",
        clear_history=False,
        sample_id=arm.sample_id,
    )
    history = resolver.resolve(source_arm).history
    system_prompt = _BASE_SYSTEM_PROMPT
    if use_tie_break:
        system_prompt += _HISTORY_TIE_BREAK
    if arm.manual_conflict_role:
        system_prompt += "\n\n" + _CONFLICT_ROLE
    action_requirements = {
        "inspect_facts": "fact_extraction",
        "cross_check_conflicts": "contradiction_resolution",
        "synthesize_decision": "decision_synthesis",
    }
    action_menu = "\n".join(
        f"- {action_requirements[action]}：可执行 {action}"
        for action in resolved_menu_order
    )
    user_prompt = (
        f"任务标识：{arm.task_id}\n"
        "当前 ResidualSnapshot 中有三个未完成需求，数值优先级都为 1.0，"
        "前置条件都已满足：\n"
        f"{action_menu}\n"
        "列表顺序不代表优先级。剩余能量预算：1 个动作。选择会被路由器执行，"
        "只能选择一个；不得同时完成其他动作。"
    )
    messages = tuple(
        {"role": message.role, "content": message.content}
        for message in history
    ) + ({"role": "user", "content": user_prompt},)
    schema: dict[str, Any] = {
        "type": "object",
        "additionalProperties": False,
        "required": ["selected_action"],
        "properties": {
            "selected_action": {
                "type": "string",
                "enum": list(resolved_schema_order),
            }
        },
    }
    fingerprint_payload = {
        "task_id": arm.task_id,
        "system_prompt": system_prompt,
        "messages": messages,
        "response_schema": schema,
    }
    canonical = json.dumps(
        fingerprint_payload,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    )
    return ActionChoiceRequest(
        run_id=arm.run_id,
        task_id=arm.task_id,
        system_prompt=system_prompt,
        messages=messages,
        response_schema=schema,
        request_fingerprint=hashlib.sha256(canonical.encode("utf-8")).hexdigest(),
    )


def _group_metrics(
    contrast_id: str,
    results: Sequence[ActionPairResult],
) -> dict[str, Any]:
    completed_pairs = [
        item
        for item in results
        if item.control.status == "completed"
        and item.treatment.status == "completed"
    ]
    control_counts = Counter(
        item.control.selected_action
        for item in results
        if item.control.selected_action is not None
    )
    treatment_counts = Counter(
        item.treatment.selected_action
        for item in results
        if item.treatment.selected_action is not None
    )
    transitions = Counter(
        f"{item.control.selected_action}->{item.treatment.selected_action}"
        for item in completed_pairs
    )
    target_control, target_treatment = _TARGET_TRANSITIONS[contrast_id]
    return {
        "planned_pairs": len(results),
        "completed_pairs": len(completed_pairs),
        "changed_pairs": sum(
            item.control.selected_action != item.treatment.selected_action
            for item in completed_pairs
        ),
        "control_action_counts": dict(sorted(control_counts.items())),
        "treatment_action_counts": dict(sorted(treatment_counts.items())),
        "transition_counts": dict(sorted(transitions.items())),
        "target_transition": f"{target_control}->{target_treatment}",
        "target_transition_successes": sum(
            item.control.selected_action == target_control
            and item.treatment.selected_action == target_treatment
            for item in completed_pairs
        ),
    }


def _nearest_rank_p90(values: Sequence[int]) -> int | None:
    if not values:
        return None
    ordered = sorted(values)
    return ordered[math.ceil(0.9 * len(ordered)) - 1]


def summarize_action_results(
    schedule: Sequence[ActionChoicePair],
    results: Sequence[ActionPairResult],
) -> dict[str, Any]:
    cases = tuple(schedule)
    observed = tuple(results)
    if len(cases) != len(observed) or any(
        pair != result.pair for pair, result in zip(cases, observed, strict=True)
    ):
        raise ValueError("action results do not match the frozen schedule")
    calls = [
        result
        for pair_result in observed
        for result in (pair_result.control, pair_result.treatment)
    ]
    by_contrast: dict[str, list[ActionPairResult]] = defaultdict(list)
    by_task_and_contrast: dict[
        tuple[str, str], list[ActionPairResult]
    ] = defaultdict(list)
    for item in observed:
        by_contrast[item.pair.contrast_id].append(item)
        by_task_and_contrast[(item.pair.task_id, item.pair.contrast_id)].append(
            item
        )
    input_tokens = [item.input_tokens for item in calls if item.input_tokens is not None]
    output_tokens = [
        item.output_tokens for item in calls if item.output_tokens is not None
    ]
    sampling_pairs = [
        item
        for item in by_contrast.get("sampling_noise", [])
        if item.control.status == "completed"
        and item.treatment.status == "completed"
    ]
    return {
        "schema_version": "a0a.action-choice.metrics.v1",
        "evidence_level": "exploratory_technical",
        "scientific_claim_eligible": False,
        "planned_pairs": len(cases),
        "planned_calls": len(cases) * 2,
        "completed_calls": sum(item.status == "completed" for item in calls),
        "failed_calls": sum(item.status == "failed" for item in calls),
        "total_input_tokens": sum(input_tokens),
        "total_output_tokens": sum(output_tokens),
        "mean_latency_ms": (
            None
            if not calls
            else round(sum(item.latency_ms for item in calls) / len(calls), 6)
        ),
        "sampling_noise_band_p90": _nearest_rank_p90(
            [
                int(item.control.selected_action != item.treatment.selected_action)
                for item in sampling_pairs
            ]
        ),
        "by_contrast": {
            contrast_id: _group_metrics(
                contrast_id,
                by_contrast[contrast_id],
            )
            for contrast_id in ACTION_CONTRAST_IDS
            if contrast_id in by_contrast
        },
        "by_task_and_contrast": {
            task_id: {
                contrast_id: _group_metrics(
                    contrast_id,
                    by_task_and_contrast[(task_id, contrast_id)]
                )
                for contrast_id in ACTION_CONTRAST_IDS
                if (task_id, contrast_id) in by_task_and_contrast
            }
            for task_id in dict.fromkeys(pair.task_id for pair in cases)
        },
    }


def _invoke_action(
    *,
    arm: ActionChoiceArm,
    effective_seed: int,
    resolver: ProbeAssetResolver,
    adapter: OllamaAdapter,
) -> tuple[ActionChoiceResult, ActionChoiceRequest]:
    request = resolve_action_request(arm, resolver)
    start = perf_counter()
    try:
        invocation = adapter.invoke_structured(
            system_prompt=request.system_prompt,
            messages=request.messages,
            response_schema=request.response_schema,
            effective_seed=effective_seed,
            request_fingerprint=request.request_fingerprint,
        )
        if invocation.audit.effective_seed != effective_seed:
            raise ValueError("adapter audit effective seed does not match schedule")
        if invocation.audit.request_fingerprint != request.request_fingerprint:
            raise ValueError(
                "adapter audit request fingerprint does not match resolved request"
            )
        selected_action = invocation.structured_output.get("selected_action")
        if selected_action not in ACTION_ENUM:
            raise ValueError("structured invocation returned an unsupported action")
        result = ActionChoiceResult(
            status="completed",
            selected_action=selected_action,
            latency_ms=(perf_counter() - start) * 1000,
            input_tokens=invocation.input_tokens,
            output_tokens=invocation.output_tokens,
            content=json.dumps(
                dict(invocation.structured_output),
                ensure_ascii=False,
                sort_keys=True,
                separators=(",", ":"),
            ),
            audit=invocation.audit,
        )
    except Exception as error:
        result = ActionChoiceResult(
            status="failed",
            selected_action=None,
            latency_ms=(perf_counter() - start) * 1000,
            failure_type=type(error).__name__,
            failure_message=str(error) or "<no failure message>",
        )
    return result, request


def _append_action_event(
    *,
    store: RunArtifactStore,
    call_index: int,
    pair: ActionChoicePair,
    condition: Literal["control", "treatment"],
    arm: ActionChoiceArm,
    seed: int,
    request: ActionChoiceRequest,
    result: ActionChoiceResult,
) -> None:
    event: dict[str, Any] = {
        "event_type": "a0a_action_choice",
        "call_index": call_index,
        "pair_id": pair.pair_id,
        "contrast_id": pair.contrast_id,
        "task_id": pair.task_id,
        "agent_label": pair.agent_label,
        "repeat_index": pair.repeat_index,
        "execution_order": pair.execution_order,
        "condition": condition,
        "run_id": arm.run_id,
        "history_id": arm.history_id,
        "manual_conflict_role": arm.manual_conflict_role,
        "effective_seed": seed,
        "request_fingerprint": request.request_fingerprint,
        "status": result.status,
        "latency_ms": result.latency_ms,
    }
    if result.status == "failed":
        event.update(
            {
                "failure_type": result.failure_type,
                "failure_message": result.failure_message,
            }
        )
    else:
        event.update(
            {
                "selected_action": result.selected_action,
                "structured_output": result.content,
                "input_tokens": result.input_tokens,
                "output_tokens": result.output_tokens,
                "invocation_audit": asdict(result.audit)
                if result.audit is not None
                else None,
            }
        )
    store.append_event(event)


def execute_action_schedule(
    schedule: Sequence[ActionChoicePair],
    *,
    resolver: ProbeAssetResolver,
    adapter: OllamaAdapter,
    store: RunArtifactStore,
) -> tuple[ActionPairResult, ...]:
    results: list[ActionPairResult] = []
    call_index = 0
    for pair in schedule:
        ordered = (
            (
                ("control", pair.control, pair.control_seed),
                ("treatment", pair.treatment, pair.treatment_seed),
            )
            if pair.execution_order == "control_first"
            else (
                ("treatment", pair.treatment, pair.treatment_seed),
                ("control", pair.control, pair.control_seed),
            )
        )
        observed: dict[str, ActionChoiceResult] = {}
        for condition, arm, seed in ordered:
            result, request = _invoke_action(
                arm=arm,
                effective_seed=seed,
                resolver=resolver,
                adapter=adapter,
            )
            call_index += 1
            _append_action_event(
                store=store,
                call_index=call_index,
                pair=pair,
                condition=condition,  # type: ignore[arg-type]
                arm=arm,
                seed=seed,
                request=request,
                result=result,
            )
            observed[condition] = result
        results.append(
            ActionPairResult(
                pair=pair,
                control=observed["control"],
                treatment=observed["treatment"],
            )
        )
    return tuple(results)


def _parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run the A0a action-choice probe")
    parser.add_argument("--output-directory", required=True)
    parser.add_argument("--run-id", required=True)
    parser.add_argument("--model", default="qwen3:8b")
    parser.add_argument("--endpoint", default="http://127.0.0.1:11434")
    parser.add_argument("--repeats", type=int, default=1)
    parser.add_argument(
        "--tasks",
        nargs="+",
        default=["software_release_readiness", "cold_chain_readiness"],
    )
    parser.add_argument("--agents", nargs="+", default=["agent.a"])
    parser.add_argument("--base-seed", type=int, default=8100)
    parser.add_argument("--timeout-seconds", type=float, default=120.0)
    return parser.parse_args(argv)


def main(argv: Sequence[str] | None = None) -> int:
    from biofield.a0_pilot import (
        _git_snapshot,
        _source_hashes,
        read_ollama_identity,
    )

    args = _parse_args(argv)
    experiment_root = Path(__file__).parents[2]
    resolver = ProbeAssetResolver()
    schedule = build_action_schedule(
        task_ids=tuple(args.tasks),
        agent_labels=tuple(args.agents),
        repeats=args.repeats,
        base_seed=args.base_seed,
    )
    identity = read_ollama_identity(args.endpoint, args.model)
    store = RunArtifactStore.create(
        args.output_directory,
        "a0a-action-choice",
        args.run_id,
    )
    store.write_config(
        {
            "schema_version": "a0a.action-choice.config.v1",
            "created_at_utc": datetime.now(timezone.utc).isoformat(),
            "evidence_level": "exploratory_technical",
            "model": identity,
            "host": {
                "platform": platform.platform(),
                "machine": platform.machine(),
                "python": sys.version,
            },
            "generation": {
                "temperature": 0.6,
                "num_ctx": 4096,
                "top_p": 0.9,
                "top_k": 40,
                "num_predict": 32,
                "repeat_penalty": 1.1,
                "think": False,
                "stream": False,
                "timeout_seconds": args.timeout_seconds,
            },
            "design": {
                "tasks": list(args.tasks),
                "agents": list(args.agents),
                "repeats": args.repeats,
                "contrasts": list(ACTION_CONTRAST_IDS),
                "actions": list(ACTION_ENUM),
                "planned_pairs": len(schedule),
                "planned_calls": len(schedule) * 2,
                "schedule": [
                    {
                        "pair_id": pair.pair_id,
                        "contrast_id": pair.contrast_id,
                        "task_id": pair.task_id,
                        "agent_label": pair.agent_label,
                        "repeat_index": pair.repeat_index,
                        "execution_order": pair.execution_order,
                        "primary_seed": pair.primary_seed,
                        "alternate_seed": pair.alternate_seed,
                        "control_seed": pair.control_seed,
                        "treatment_seed": pair.treatment_seed,
                        "control_run_id": pair.control.run_id,
                        "treatment_run_id": pair.treatment.run_id,
                    }
                    for pair in schedule
                ],
            },
            "rules": {
                "pair_arms_adjacent_and_serial": True,
                "retries": "none",
                "failures_remain_in_denominator": True,
                "three_numeric_priorities_equal": True,
            },
            "source_sha256": _source_hashes(experiment_root),
            "git": _git_snapshot(experiment_root),
        }
    )
    adapter = OllamaAdapter(
        model_id=args.model,
        resolver=resolver,
        base_seed=args.base_seed,
        temperature=0.6,
        num_ctx=4096,
        top_p=0.9,
        top_k=40,
        num_predict=32,
        repeat_penalty=1.1,
        endpoint=args.endpoint,
        timeout_seconds=args.timeout_seconds,
    )
    results = execute_action_schedule(
        schedule,
        resolver=resolver,
        adapter=adapter,
        store=store,
    )
    metrics = summarize_action_results(schedule, results)
    store.write_metrics(metrics)
    store.write_summary(
        "# A0a 受限动作选择技术摘要\n\n"
        f"- 完成：{metrics['completed_calls']}/{metrics['planned_calls']}\n"
        f"- 失败：{metrics['failed_calls']}\n"
        "- 证据级别：exploratory_technical，不支持确认性结论。\n"
    )
    print(store.run_directory)
    return 0 if metrics["failed_calls"] == 0 else 2


if __name__ == "__main__":
    raise SystemExit(main())
