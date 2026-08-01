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

CANONICAL_ORDER = ACTION_ENUM
SYNTH_FIRST_ORDER = (
    "synthesize_decision",
    "inspect_facts",
    "cross_check_conflicts",
)
AXIS_CELLS: tuple[tuple[str, tuple[str, ...], tuple[str, ...]], ...] = (
    ("menu_canonical_schema_canonical", CANONICAL_ORDER, CANONICAL_ORDER),
    ("menu_synth_schema_canonical", SYNTH_FIRST_ORDER, CANONICAL_ORDER),
    ("menu_synth_schema_synth", SYNTH_FIRST_ORDER, SYNTH_FIRST_ORDER),
    ("menu_canonical_schema_synth", CANONICAL_ORDER, SYNTH_FIRST_ORDER),
)
_CELL_IDS = tuple(cell_id for cell_id, _, _ in AXIS_CELLS)
_SAFE_IDENTIFIER = re.compile(r"^[A-Za-z0-9_.-]+$")


@dataclass(frozen=True)
class ActionAxisPair:
    pair_id: str
    task_id: str
    agent_label: str
    repeat_index: int
    primary_seed: int
    cell_id: str
    menu_order: tuple[str, ...]
    schema_order: tuple[str, ...]
    execution_order: ExecutionOrder
    control: ActionChoiceArm
    treatment: ActionChoiceArm

    def __post_init__(self) -> None:
        object.__setattr__(self, "menu_order", tuple(self.menu_order))
        object.__setattr__(self, "schema_order", tuple(self.schema_order))
        if not self.pair_id or _SAFE_IDENTIFIER.fullmatch(self.pair_id) is None:
            raise ValueError("pair_id must be a safe identifier")
        if self.repeat_index <= 0:
            raise ValueError("repeat_index must be positive")
        if self.primary_seed < 0:
            raise ValueError("primary_seed cannot be negative")
        if self.cell_id not in _CELL_IDS:
            raise ValueError("cell_id is not registered")
        for name, order in (
            ("menu_order", self.menu_order),
            ("schema_order", self.schema_order),
        ):
            if len(order) != len(ACTION_ENUM) or set(order) != set(ACTION_ENUM):
                raise ValueError(f"{name} must be a permutation of ACTION_ENUM")
        if self.execution_order not in ("control_first", "treatment_first"):
            raise ValueError("invalid execution_order")

    @property
    def control_seed(self) -> int:
        return self.primary_seed

    @property
    def treatment_seed(self) -> int:
        return self.primary_seed


@dataclass(frozen=True)
class ActionAxisPairResult:
    pair: ActionAxisPair
    control: ActionChoiceResult
    treatment: ActionChoiceResult


def _validate_identifier(value: str, name: str) -> None:
    if not isinstance(value, str) or _SAFE_IDENTIFIER.fullmatch(value) is None:
        raise ValueError(f"{name} must be a safe non-empty identifier")


def build_action_axis_schedule(
    *,
    repeats: int = 5,
    base_seed: int = 11100,
    seed_stride: int = 100,
    task_id: str = "software_release_readiness",
    agent_label: str = "agent.a",
) -> tuple[ActionAxisPair, ...]:
    """Build a fresh four-cell menu/schema experiment with repeated seed blocks."""

    if isinstance(repeats, bool) or not isinstance(repeats, int) or repeats <= 0:
        raise ValueError("repeats must be a positive integer")
    if isinstance(base_seed, bool) or not isinstance(base_seed, int) or base_seed < 0:
        raise ValueError("base_seed must be a non-negative integer")
    if isinstance(seed_stride, bool) or not isinstance(seed_stride, int) or seed_stride < 1:
        raise ValueError("seed_stride must be a positive integer")
    _validate_identifier(task_id, "task_id")
    _validate_identifier(agent_label, "agent_label")

    schedule: list[ActionAxisPair] = []
    for repeat_offset in range(repeats):
        primary_seed = base_seed + repeat_offset * seed_stride
        rotation = repeat_offset % len(AXIS_CELLS)
        ordered_cells = AXIS_CELLS[rotation:] + AXIS_CELLS[:rotation]
        for cell_id, menu_order, schema_order in ordered_cells:
            cell_index = _CELL_IDS.index(cell_id)
            pair_id = f"a0c.{cell_id}.rep{repeat_offset + 1:02d}"
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
            control_first = (cell_index + repeat_offset) % 2 == 0
            schedule.append(
                ActionAxisPair(
                    pair_id=pair_id,
                    task_id=task_id,
                    agent_label=agent_label,
                    repeat_index=repeat_offset + 1,
                    primary_seed=primary_seed,
                    cell_id=cell_id,
                    menu_order=menu_order,
                    schema_order=schema_order,
                    execution_order=(
                        "control_first" if control_first else "treatment_first"
                    ),
                    control=control,
                    treatment=treatment,
                )
            )
    return tuple(schedule)


def _safe_rate(numerator: int, denominator: int) -> float | None:
    return None if denominator == 0 else round(numerator / denominator, 6)


def _group_metrics(results: Sequence[ActionAxisPairResult]) -> dict[str, Any]:
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
    menu_first_follow_successes = sum(
        result.selected_action == pair.menu_order[0]
        for pair, _, result in completed_calls
    )
    schema_first_follow_successes = sum(
        result.selected_action == pair.schema_order[0]
        for pair, _, result in completed_calls
    )
    menu_positions = Counter(
        f"position_{pair.menu_order.index(result.selected_action) + 1}"
        for pair, _, result in completed_calls
        if result.selected_action in pair.menu_order
    )
    schema_positions = Counter(
        f"position_{pair.schema_order.index(result.selected_action) + 1}"
        for pair, _, result in completed_calls
        if result.selected_action in pair.schema_order
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
        "menu_first_follow_successes": menu_first_follow_successes,
        "menu_first_follow_rate_planned_calls": _safe_rate(
            menu_first_follow_successes,
            planned_calls,
        ),
        "schema_first_follow_successes": schema_first_follow_successes,
        "schema_first_follow_rate_planned_calls": _safe_rate(
            schema_first_follow_successes,
            planned_calls,
        ),
        "selected_menu_position_counts": dict(sorted(menu_positions.items())),
        "selected_schema_position_counts": dict(sorted(schema_positions.items())),
        "transition_counts": dict(sorted(transitions.items())),
        "control_action_counts": dict(sorted(control_actions.items())),
        "treatment_action_counts": dict(sorted(treatment_actions.items())),
    }


def _classify_seed_pattern(actions: dict[str, str]) -> str:
    if set(actions) != set(_CELL_IDS):
        return "incomplete"
    canonical = "inspect_facts"
    synth = "synthesize_decision"
    expected = {
        "menu_dominant": {
            "menu_canonical_schema_canonical": canonical,
            "menu_synth_schema_canonical": synth,
            "menu_canonical_schema_synth": canonical,
            "menu_synth_schema_synth": synth,
        },
        "schema_dominant": {
            "menu_canonical_schema_canonical": canonical,
            "menu_synth_schema_canonical": canonical,
            "menu_canonical_schema_synth": synth,
            "menu_synth_schema_synth": synth,
        },
        "alignment_conjunction": {
            "menu_canonical_schema_canonical": canonical,
            "menu_synth_schema_canonical": canonical,
            "menu_canonical_schema_synth": canonical,
            "menu_synth_schema_synth": synth,
        },
        "either_axis_sufficient": {
            "menu_canonical_schema_canonical": canonical,
            "menu_synth_schema_canonical": synth,
            "menu_canonical_schema_synth": synth,
            "menu_synth_schema_synth": synth,
        },
        "no_synthesis_bias": {
            cell_id: canonical for cell_id in _CELL_IDS
        },
        "always_synthesis": {
            cell_id: synth for cell_id in _CELL_IDS
        },
    }
    for label, pattern in expected.items():
        if actions == pattern:
            return label
    return "other"


def _seed_patterns(
    results: Sequence[ActionAxisPairResult],
) -> tuple[dict[str, Any], dict[str, int]]:
    by_seed: dict[int, list[ActionAxisPairResult]] = defaultdict(list)
    for item in results:
        by_seed[item.pair.primary_seed].append(item)
    details: dict[str, Any] = {}
    counts: Counter[str] = Counter()
    for seed, items in sorted(by_seed.items()):
        actions = {
            item.pair.cell_id: item.control.selected_action
            for item in items
            if item.control.status == "completed"
            and item.control.selected_action is not None
        }
        classification = _classify_seed_pattern(actions)
        counts[classification] += 1
        details[str(seed)] = {
            "control_actions": actions,
            "classification": classification,
            "treatment_all_cross_check": (
                len(items) == len(_CELL_IDS)
                and all(
                    item.treatment.status == "completed"
                    and item.treatment.selected_action == "cross_check_conflicts"
                    for item in items
                )
            ),
        }
    return details, dict(sorted(counts.items()))


def _axis_effects(results: Sequence[ActionAxisPairResult]) -> dict[str, Any]:
    by_cell: dict[str, list[ActionAxisPairResult]] = defaultdict(list)
    for item in results:
        by_cell[item.pair.cell_id].append(item)
    synth_rates: dict[str, float | None] = {}
    for cell_id in _CELL_IDS:
        items = by_cell[cell_id]
        synth_count = sum(
            item.control.status == "completed"
            and item.control.selected_action == "synthesize_decision"
            for item in items
        )
        synth_rates[cell_id] = _safe_rate(synth_count, len(items))
    z00 = synth_rates["menu_canonical_schema_canonical"]
    z10 = synth_rates["menu_synth_schema_canonical"]
    z01 = synth_rates["menu_canonical_schema_synth"]
    z11 = synth_rates["menu_synth_schema_synth"]
    if any(value is None for value in (z00, z10, z01, z11)):
        effects = None
    else:
        assert z00 is not None and z10 is not None and z01 is not None and z11 is not None
        effects = {
            "menu_effect_when_schema_canonical": round(z10 - z00, 6),
            "menu_effect_when_schema_synth": round(z11 - z01, 6),
            "schema_effect_when_menu_canonical": round(z01 - z00, 6),
            "schema_effect_when_menu_synth": round(z11 - z10, 6),
            "interaction": round(z11 - z10 - z01 + z00, 6),
        }
    return {
        "control_synthesis_rate_by_cell_planned_denominator": synth_rates,
        "binary_synthesis_effects": effects,
    }


def summarize_action_axis_results(
    schedule: Sequence[ActionAxisPair],
    results: Sequence[ActionAxisPairResult],
) -> dict[str, Any]:
    cases = tuple(schedule)
    observed = tuple(results)
    if len(cases) != len(observed) or any(
        pair != result.pair for pair, result in zip(cases, observed, strict=True)
    ):
        raise ValueError("axis results do not match the frozen schedule")

    overall = _group_metrics(observed)
    calls = [
        result
        for item in observed
        for result in (item.control, item.treatment)
    ]
    input_tokens = [item.input_tokens for item in calls if item.input_tokens is not None]
    output_tokens = [
        item.output_tokens for item in calls if item.output_tokens is not None
    ]
    seed_details, seed_counts = _seed_patterns(observed)
    return {
        "schema_version": "a0a.action-axis.metrics.v1",
        "evidence_level": "exploratory_technical",
        "scientific_claim_eligible": False,
        "design_interpretation": (
            f"{len({pair.primary_seed for pair in cases})}_seed_blocks_repeated_"
            "across_four_campaign_cells"
        ),
        "unique_primary_seeds": len({pair.primary_seed for pair in cases}),
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
        "by_cell": {
            cell_id: _group_metrics(
                [item for item in observed if item.pair.cell_id == cell_id]
            )
            for cell_id in _CELL_IDS
        },
        "seed_patterns": seed_details,
        "seed_pattern_counts": seed_counts,
        **_axis_effects(observed),
    }


def _invoke_axis_arm(
    *,
    arm: ActionChoiceArm,
    pair: ActionAxisPair,
    effective_seed: int,
    resolver: ProbeAssetResolver,
    adapter: OllamaAdapter,
) -> tuple[ActionChoiceResult, ActionChoiceRequest]:
    request = resolve_action_request(
        arm,
        resolver,
        menu_order=pair.menu_order,
        schema_order=pair.schema_order,
        use_tie_break=False,
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


def _append_axis_event(
    *,
    store: RunArtifactStore,
    call_index: int,
    pair: ActionAxisPair,
    condition: Literal["control", "treatment"],
    arm: ActionChoiceArm,
    seed: int,
    request: ActionChoiceRequest,
    result: ActionChoiceResult,
) -> None:
    event: dict[str, Any] = {
        "event_type": "a0a_action_axis_choice",
        "call_index": call_index,
        "pair_id": pair.pair_id,
        "task_id": pair.task_id,
        "agent_label": pair.agent_label,
        "repeat_index": pair.repeat_index,
        "primary_seed": pair.primary_seed,
        "cell_id": pair.cell_id,
        "menu_order": list(pair.menu_order),
        "schema_order": list(pair.schema_order),
        "menu_first_action": pair.menu_order[0],
        "schema_first_action": pair.schema_order[0],
        "tie_break_enabled": False,
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
                "selected_menu_position": (
                    pair.menu_order.index(result.selected_action) + 1
                    if result.selected_action in pair.menu_order
                    else None
                ),
                "selected_schema_position": (
                    pair.schema_order.index(result.selected_action) + 1
                    if result.selected_action in pair.schema_order
                    else None
                ),
                "structured_output": result.content,
                "input_tokens": result.input_tokens,
                "output_tokens": result.output_tokens,
                "invocation_audit": (
                    asdict(result.audit) if result.audit is not None else None
                ),
            }
        )
    store.append_event(event)


def execute_action_axis_schedule(
    schedule: Sequence[ActionAxisPair],
    *,
    resolver: ProbeAssetResolver,
    adapter: OllamaAdapter,
    store: RunArtifactStore,
) -> tuple[ActionAxisPairResult, ...]:
    cases = tuple(schedule)
    if not cases or len({pair.pair_id for pair in cases}) != len(cases):
        raise ValueError("schedule must be non-empty with unique pair IDs")
    results: list[ActionAxisPairResult] = []
    call_index = 0
    for pair in cases:
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
            result, request = _invoke_axis_arm(
                arm=arm,
                pair=pair,
                effective_seed=seed,
                resolver=resolver,
                adapter=adapter,
            )
            call_index += 1
            _append_axis_event(
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
            ActionAxisPairResult(
                pair=pair,
                control=observed["control"],
                treatment=observed["treatment"],
            )
        )
    return tuple(results)


def _parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Run the A0a menu/schema axis localization"
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
    schedule = build_action_axis_schedule(
        repeats=args.repeats,
        base_seed=args.base_seed,
        task_id=args.task,
        agent_label=args.agent,
    )
    identity = read_ollama_identity(args.endpoint, args.model)
    store = RunArtifactStore.create(
        args.output_directory,
        "a0a-action-axis",
        args.run_id,
    )
    store.write_config(
        {
            "schema_version": "a0a.action-axis.config.v1",
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
                "tie_break_enabled": False,
                "factorial_cells": {
                    cell_id: {
                        "menu_order": list(menu_order),
                        "schema_order": list(schema_order),
                    }
                    for cell_id, menu_order, schema_order in AXIS_CELLS
                },
                "cell_order_rule": "cyclic_rotation_by_seed_block",
                "planned_pairs": len(schedule),
                "planned_calls": len(schedule) * 2,
                "schedule": [
                    {
                        "pair_id": pair.pair_id,
                        "repeat_index": pair.repeat_index,
                        "primary_seed": pair.primary_seed,
                        "cell_id": pair.cell_id,
                        "menu_order": list(pair.menu_order),
                        "schema_order": list(pair.schema_order),
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
                "primary_unit": "seed block repeated across four fresh cells",
                "strict_stop": (
                    f"{len(schedule) * 2}/{len(schedule) * 2} calls complete; "
                    "all seed blocks share one control pattern; all conflict-history treatments select cross_check_conflicts"
                ),
                "scope": (
                    "tie-off canonical-vs-synth-first structured choice only; "
                    "does not execute routes or tools"
                ),
                "prior_run_role": (
                    "a0a-action-bias/qwen3-8b-position-tie-v1 motivated the design but is not pooled into primary effects"
                ),
            },
            "rules": {
                "complete_factorial_reissued_in_one_campaign": True,
                "pair_arms_adjacent_and_serial": True,
                "same_seed_within_pair": True,
                "retries": "none",
                "failures_remain_in_planned_denominator": True,
                "menu_and_schema_orders_decoupled": True,
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
    results = execute_action_axis_schedule(
        schedule,
        resolver=resolver,
        adapter=adapter,
        store=store,
    )
    metrics = summarize_action_axis_results(schedule, results)
    store.write_metrics(metrics)
    store.write_summary(
        "# A0a 菜单/Schema 顺序轴定位摘要\n\n"
        f"- 完成：{metrics['completed_calls']}/{metrics['planned_calls']}\n"
        f"- 目标转移：{metrics['target_transition_successes']}/{metrics['planned_pairs']}\n"
        f"- seed 模式：{json.dumps(metrics['seed_pattern_counts'], ensure_ascii=False, sort_keys=True)}\n"
        f"- 设计：{metrics['unique_primary_seeds']} 个 seed 跨 4 个 fresh cell 的重复测量。\n"
        "- 证据级别：exploratory_technical，不支持确认性结论。\n"
    )
    print(store.run_directory)
    return 0 if metrics["failed_calls"] == 0 else 2


if __name__ == "__main__":
    raise SystemExit(main())
