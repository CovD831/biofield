from __future__ import annotations

import argparse
import json
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

from biofield.a0_action_probe import (
    ACTION_ENUM,
    ActionChoiceArm,
    ActionChoiceRequest,
    ActionChoiceResult,
    resolve_action_request,
)
from biofield.a0_runner import ExecutionOrder
from biofield.artifacts import RunArtifactStore
from biofield.ollama_adapter import OllamaAdapter
from biofield.probe_assets import ProbeAssetResolver

CYCLIC_ACTION_ORDERS: tuple[tuple[str, tuple[str, ...]], ...] = (
    (
        "inspect_first",
        ("inspect_facts", "cross_check_conflicts", "synthesize_decision"),
    ),
    (
        "cross_check_first",
        ("cross_check_conflicts", "synthesize_decision", "inspect_facts"),
    ),
    (
        "synthesize_first",
        ("synthesize_decision", "inspect_facts", "cross_check_conflicts"),
    ),
)
_ORDER_IDS = tuple(order_id for order_id, _ in CYCLIC_ACTION_ORDERS)
_SAFE_IDENTIFIER = re.compile(r"^[A-Za-z0-9_.-]+$")


@dataclass(frozen=True)
class ActionBiasPair:
    pair_id: str
    task_id: str
    agent_label: str
    repeat_index: int
    primary_seed: int
    tie_break_enabled: bool
    order_id: str
    action_order: tuple[str, ...]
    execution_order: ExecutionOrder
    control: ActionChoiceArm
    treatment: ActionChoiceArm

    def __post_init__(self) -> None:
        object.__setattr__(self, "action_order", tuple(self.action_order))
        if not self.pair_id or _SAFE_IDENTIFIER.fullmatch(self.pair_id) is None:
            raise ValueError("pair_id must be a safe identifier")
        if self.repeat_index <= 0:
            raise ValueError("repeat_index must be positive")
        if self.primary_seed < 0:
            raise ValueError("primary_seed cannot be negative")
        if not isinstance(self.tie_break_enabled, bool):
            raise ValueError("tie_break_enabled must be boolean")
        if self.order_id not in _ORDER_IDS:
            raise ValueError("order_id is not a registered cyclic order")
        if (
            len(self.action_order) != len(ACTION_ENUM)
            or set(self.action_order) != set(ACTION_ENUM)
        ):
            raise ValueError("action_order must be a permutation of ACTION_ENUM")
        if self.execution_order not in ("control_first", "treatment_first"):
            raise ValueError("invalid execution_order")

    @property
    def control_seed(self) -> int:
        return self.primary_seed

    @property
    def treatment_seed(self) -> int:
        return self.primary_seed


@dataclass(frozen=True)
class ActionBiasPairResult:
    pair: ActionBiasPair
    control: ActionChoiceResult
    treatment: ActionChoiceResult


def _validate_identifier(value: str, name: str) -> None:
    if not isinstance(value, str) or _SAFE_IDENTIFIER.fullmatch(value) is None:
        raise ValueError(f"{name} must be a safe non-empty identifier")


def build_action_bias_schedule(
    *,
    repeats: int = 5,
    base_seed: int = 11100,
    seed_stride: int = 100,
    task_id: str = "software_release_readiness",
    agent_label: str = "agent.a",
) -> tuple[ActionBiasPair, ...]:
    """Repeat each seed block over the six tie-break/order factorial cells."""

    if isinstance(repeats, bool) or not isinstance(repeats, int) or repeats <= 0:
        raise ValueError("repeats must be a positive integer")
    if isinstance(base_seed, bool) or not isinstance(base_seed, int) or base_seed < 0:
        raise ValueError("base_seed must be a non-negative integer")
    if isinstance(seed_stride, bool) or not isinstance(seed_stride, int) or seed_stride < 1:
        raise ValueError("seed_stride must be a positive integer")
    _validate_identifier(task_id, "task_id")
    _validate_identifier(agent_label, "agent_label")

    schedule: list[ActionBiasPair] = []
    factorial_cells = tuple(
        (
            order_index,
            order_id,
            action_order,
            tie_index,
            tie_break_enabled,
        )
        for order_index, (order_id, action_order) in enumerate(
            CYCLIC_ACTION_ORDERS
        )
        for tie_index, tie_break_enabled in enumerate((True, False))
    )
    for repeat_offset in range(repeats):
        primary_seed = base_seed + repeat_offset * seed_stride
        rotation = repeat_offset % len(factorial_cells)
        ordered_cells = (
            factorial_cells[rotation:] + factorial_cells[:rotation]
        )
        for (
            order_index,
            order_id,
            action_order,
            tie_index,
            tie_break_enabled,
        ) in ordered_cells:
            tie_label = "on" if tie_break_enabled else "off"
            pair_id = (
                f"a0b.{tie_label}.{order_id}."
                f"rep{repeat_offset + 1:02d}"
            )
            common = {
                "task_id": task_id,
                "agent_label": agent_label,
                "manual_conflict_role": False,
                "sample_id": 0,
            }
            control = ActionChoiceArm(
                run_id=f"{pair_id}.control",
                history_id="history.common.v1",
                **common,
            )
            treatment = ActionChoiceArm(
                run_id=f"{pair_id}.treatment",
                history_id="history.specialized.v1",
                **common,
            )
            control_first = (
                tie_index + order_index + repeat_offset
            ) % 2 == 0
            schedule.append(
                ActionBiasPair(
                    pair_id=pair_id,
                    task_id=task_id,
                    agent_label=agent_label,
                    repeat_index=repeat_offset + 1,
                    primary_seed=primary_seed,
                    tie_break_enabled=tie_break_enabled,
                    order_id=order_id,
                    action_order=action_order,
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


def _safe_rate(numerator: int, denominator: int) -> float | None:
    if denominator == 0:
        return None
    return round(numerator / denominator, 6)


def _group_metrics(results: Sequence[ActionBiasPairResult]) -> dict[str, Any]:
    completed_pairs = [
        item
        for item in results
        if item.control.status == "completed"
        and item.treatment.status == "completed"
    ]
    calls = [
        (item.pair, "control", item.control)
        for item in results
    ] + [
        (item.pair, "treatment", item.treatment)
        for item in results
    ]
    completed_calls = [item for item in calls if item[2].status == "completed"]
    transitions = Counter(
        f"{item.control.selected_action}->{item.treatment.selected_action}"
        for item in completed_pairs
    )
    target_transition_successes = sum(
        item.control.selected_action == "inspect_facts"
        and item.treatment.selected_action == "cross_check_conflicts"
        for item in completed_pairs
    )
    semantic_target_successes = sum(
        result.selected_action
        == (
            "inspect_facts"
            if condition == "control"
            else "cross_check_conflicts"
        )
        for _, condition, result in completed_calls
    )
    position_follow_successes = sum(
        result.selected_action == pair.action_order[0]
        for pair, _, result in completed_calls
    )
    selected_positions = Counter(
        f"position_{pair.action_order.index(result.selected_action) + 1}"
        for pair, _, result in completed_calls
        if result.selected_action in pair.action_order
    )
    control_actions = Counter(
        item.control.selected_action
        for item in results
        if item.control.status == "completed"
    )
    treatment_actions = Counter(
        item.treatment.selected_action
        for item in results
        if item.treatment.status == "completed"
    )
    planned_pairs = len(results)
    planned_calls = planned_pairs * 2
    return {
        "planned_pairs": planned_pairs,
        "planned_calls": planned_calls,
        "completed_pairs": len(completed_pairs),
        "completed_calls": len(completed_calls),
        "failed_calls": planned_calls - len(completed_calls),
        "changed_pairs": sum(
            item.control.selected_action != item.treatment.selected_action
            for item in completed_pairs
        ),
        "target_transition": "inspect_facts->cross_check_conflicts",
        "target_transition_successes": target_transition_successes,
        "target_transition_rate_planned_pairs": _safe_rate(
            target_transition_successes,
            planned_pairs,
        ),
        "semantic_target_successes": semantic_target_successes,
        "semantic_target_rate_planned_calls": _safe_rate(
            semantic_target_successes,
            planned_calls,
        ),
        "position_follow_successes": position_follow_successes,
        "position_follow_rate_planned_calls": _safe_rate(
            position_follow_successes,
            planned_calls,
        ),
        "selected_position_counts": dict(sorted(selected_positions.items())),
        "transition_counts": dict(sorted(transitions.items())),
        "control_action_counts": dict(sorted(control_actions.items())),
        "treatment_action_counts": dict(sorted(treatment_actions.items())),
    }


def _all_orders_target_success(
    results: Sequence[ActionBiasPairResult],
) -> dict[str, dict[str, int]]:
    blocks: dict[tuple[bool, int], list[ActionBiasPairResult]] = defaultdict(list)
    for item in results:
        blocks[(item.pair.tie_break_enabled, item.pair.primary_seed)].append(item)

    summary: dict[str, dict[str, int]] = {}
    for tie_break_enabled in (False, True):
        relevant = {
            seed: items
            for (tie_mode, seed), items in blocks.items()
            if tie_mode is tie_break_enabled
        }
        successes = 0
        for items in relevant.values():
            order_ids = {item.pair.order_id for item in items}
            if order_ids != set(_ORDER_IDS) or len(items) != len(_ORDER_IDS):
                continue
            if all(
                item.control.status == "completed"
                and item.treatment.status == "completed"
                and item.control.selected_action == "inspect_facts"
                and item.treatment.selected_action == "cross_check_conflicts"
                for item in items
            ):
                successes += 1
        summary["on" if tie_break_enabled else "off"] = {
            "planned_seed_blocks": len(relevant),
            "all_orders_target_success_blocks": successes,
        }
    return summary


def summarize_action_bias_results(
    schedule: Sequence[ActionBiasPair],
    results: Sequence[ActionBiasPairResult],
) -> dict[str, Any]:
    cases = tuple(schedule)
    observed = tuple(results)
    if len(cases) != len(observed) or any(
        pair != result.pair for pair, result in zip(cases, observed, strict=True)
    ):
        raise ValueError("bias results do not match the frozen schedule")

    overall = _group_metrics(observed)
    unique_primary_seeds = len({pair.primary_seed for pair in cases})
    calls = [
        result
        for item in observed
        for result in (item.control, item.treatment)
    ]
    input_tokens = [item.input_tokens for item in calls if item.input_tokens is not None]
    output_tokens = [
        item.output_tokens for item in calls if item.output_tokens is not None
    ]
    by_tie = {
        label: _group_metrics(
            [
                item
                for item in observed
                if item.pair.tie_break_enabled is enabled
            ]
        )
        for label, enabled in (("off", False), ("on", True))
    }
    by_order = {
        order_id: _group_metrics(
            [item for item in observed if item.pair.order_id == order_id]
        )
        for order_id in _ORDER_IDS
    }
    by_cell = {
        f"{tie_label}.{order_id}": _group_metrics(
            [
                item
                for item in observed
                if item.pair.tie_break_enabled is enabled
                and item.pair.order_id == order_id
            ]
        )
        for tie_label, enabled in (("off", False), ("on", True))
        for order_id in _ORDER_IDS
    }
    return {
        "schema_version": "a0a.action-bias.metrics.v1",
        "evidence_level": "exploratory_technical",
        "scientific_claim_eligible": False,
        "design_interpretation": (
            f"{unique_primary_seeds}_seed_blocks_repeated_across_six_cells"
        ),
        "unique_primary_seeds": unique_primary_seeds,
        **overall,
        "total_input_tokens": sum(input_tokens),
        "total_output_tokens": sum(output_tokens),
        "mean_latency_ms": (
            None
            if not calls
            else round(sum(item.latency_ms for item in calls) / len(calls), 6)
        ),
        "execution_order_counts": dict(
            sorted(Counter(pair.execution_order for pair in cases).items())
        ),
        "all_orders_target_success_by_tie": _all_orders_target_success(
            observed
        ),
        "by_tie_break": by_tie,
        "by_action_order": by_order,
        "by_factorial_cell": by_cell,
    }


def _invoke_bias_arm(
    *,
    arm: ActionChoiceArm,
    pair: ActionBiasPair,
    effective_seed: int,
    resolver: ProbeAssetResolver,
    adapter: OllamaAdapter,
) -> tuple[ActionChoiceResult, ActionChoiceRequest]:
    request = resolve_action_request(
        arm,
        resolver,
        action_order=pair.action_order,
        use_tie_break=pair.tie_break_enabled,
    )
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


def _append_bias_event(
    *,
    store: RunArtifactStore,
    call_index: int,
    pair: ActionBiasPair,
    condition: Literal["control", "treatment"],
    arm: ActionChoiceArm,
    seed: int,
    request: ActionChoiceRequest,
    result: ActionChoiceResult,
) -> None:
    selected_position = (
        pair.action_order.index(result.selected_action) + 1
        if result.selected_action in pair.action_order
        else None
    )
    event: dict[str, Any] = {
        "event_type": "a0a_action_bias_choice",
        "call_index": call_index,
        "pair_id": pair.pair_id,
        "task_id": pair.task_id,
        "agent_label": pair.agent_label,
        "repeat_index": pair.repeat_index,
        "primary_seed": pair.primary_seed,
        "tie_break_enabled": pair.tie_break_enabled,
        "order_id": pair.order_id,
        "action_order": list(pair.action_order),
        "first_action": pair.action_order[0],
        "execution_order": pair.execution_order,
        "condition": condition,
        "semantic_target": (
            "inspect_facts"
            if condition == "control"
            else "cross_check_conflicts"
        ),
        "run_id": arm.run_id,
        "history_id": arm.history_id,
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
                "selected_position": selected_position,
                "structured_output": result.content,
                "input_tokens": result.input_tokens,
                "output_tokens": result.output_tokens,
                "invocation_audit": (
                    asdict(result.audit) if result.audit is not None else None
                ),
            }
        )
    store.append_event(event)


def execute_action_bias_schedule(
    schedule: Sequence[ActionBiasPair],
    *,
    resolver: ProbeAssetResolver,
    adapter: OllamaAdapter,
    store: RunArtifactStore,
) -> tuple[ActionBiasPairResult, ...]:
    results: list[ActionBiasPairResult] = []
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
            result, request = _invoke_bias_arm(
                arm=arm,
                pair=pair,
                effective_seed=seed,
                resolver=resolver,
                adapter=adapter,
            )
            call_index += 1
            _append_bias_event(
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
            ActionBiasPairResult(
                pair=pair,
                control=observed["control"],
                treatment=observed["treatment"],
            )
        )
    return tuple(results)


def _parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Run the A0a action position/tie-break ablation"
    )
    parser.add_argument("--output-directory", required=True)
    parser.add_argument("--run-id", required=True)
    parser.add_argument("--model", default="qwen3:8b")
    parser.add_argument("--endpoint", default="http://127.0.0.1:11434")
    parser.add_argument("--repeats", type=int, default=5)
    parser.add_argument("--task", default="software_release_readiness")
    parser.add_argument("--agent", default="agent.a")
    parser.add_argument("--base-seed", type=int, default=11100)
    parser.add_argument("--timeout-seconds", type=float, default=120.0)
    return parser.parse_args(argv)


def main(argv: Sequence[str] | None = None) -> int:
    from biofield.a0_pilot import _git_snapshot, _source_hashes, read_ollama_identity

    args = _parse_args(argv)
    experiment_root = Path(__file__).parents[2]
    resolver = ProbeAssetResolver()
    schedule = build_action_bias_schedule(
        repeats=args.repeats,
        base_seed=args.base_seed,
        task_id=args.task,
        agent_label=args.agent,
    )
    identity = read_ollama_identity(args.endpoint, args.model)
    store = RunArtifactStore.create(
        args.output_directory,
        "a0a-action-bias",
        args.run_id,
    )
    store.write_config(
        {
            "schema_version": "a0a.action-bias.config.v1",
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
                "task": args.task,
                "agent": args.agent,
                "repeats": args.repeats,
                "unique_primary_seed_blocks": args.repeats,
                "tie_break_modes": ["on", "off"],
                "cyclic_action_orders": {
                    order_id: list(action_order)
                    for order_id, action_order in CYCLIC_ACTION_ORDERS
                },
                "cell_order_rule": "cyclic_rotation_by_seed_block",
                "planned_pairs": len(schedule),
                "planned_calls": len(schedule) * 2,
                "schedule": [
                    {
                        "pair_id": pair.pair_id,
                        "repeat_index": pair.repeat_index,
                        "primary_seed": pair.primary_seed,
                        "tie_break_enabled": pair.tie_break_enabled,
                        "order_id": pair.order_id,
                        "action_order": list(pair.action_order),
                        "execution_order": pair.execution_order,
                        "control_seed": pair.control_seed,
                        "treatment_seed": pair.treatment_seed,
                        "control_run_id": pair.control.run_id,
                        "treatment_run_id": pair.treatment.run_id,
                    }
                    for pair in schedule
                ],
            },
            "preregistered_interpretation": {
                "target_transition": "inspect_facts->cross_check_conflicts",
                "claim": "action follows injected history semantics rather than menu or enum position",
                "primary_block_metric": "all_orders_target_success_by_tie",
                "independence_warning": (
                    f"{args.repeats} seed blocks are repeated across six "
                    f"factorial cells; {len(schedule)} pairs are not "
                    "independent trials"
                ),
                "scope": "structured action choice only; no tool or route is executed",
            },
            "rules": {
                "pair_arms_adjacent_and_serial": True,
                "same_seed_within_pair": True,
                "retries": "none",
                "failures_remain_in_planned_denominator": True,
                "menu_and_schema_order_match": True,
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
    results = execute_action_bias_schedule(
        schedule,
        resolver=resolver,
        adapter=adapter,
        store=store,
    )
    metrics = summarize_action_bias_results(schedule, results)
    store.write_metrics(metrics)
    store.write_summary(
        "# A0a 位置与 tie-break 消融技术摘要\n\n"
        f"- 完成：{metrics['completed_calls']}/{metrics['planned_calls']}\n"
        f"- 目标转移：{metrics['target_transition_successes']}/{metrics['planned_pairs']}\n"
        f"- 首位跟随：{metrics['position_follow_successes']}/{metrics['planned_calls']}\n"
        f"- 设计：{metrics['unique_primary_seeds']} 个 seed 跨 6 个 cell 的重复测量；"
        f"{metrics['planned_pairs']} 对不是独立样本。\n"
        "- 证据级别：exploratory_technical，不支持确认性结论。\n"
    )
    print(store.run_directory)
    return 0 if metrics["failed_calls"] == 0 else 2


if __name__ == "__main__":
    raise SystemExit(main())
