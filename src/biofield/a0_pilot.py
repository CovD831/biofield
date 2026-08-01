from __future__ import annotations

import argparse
import hashlib
import json
import platform
import subprocess
import sys
from collections import Counter, defaultdict
from collections.abc import Callable, Mapping, Sequence
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.request import urlopen

from biofield.a0_runner import ModelAdapter, PairedRun, RunRecord, run_contrast
from biofield.a0_schedule import (
    A0ScheduledPair,
    CORE_CONTRAST_IDS,
    build_core_schedule,
)
from biofield.artifacts import RunArtifactStore
from biofield.ollama_adapter import OllamaAdapter
from biofield.probe_assets import ProbeAssetResolver

AdapterFactory = Callable[[A0ScheduledPair], ModelAdapter]


@dataclass(frozen=True)
class A0PilotOutcome:
    case: A0ScheduledPair
    paired: PairedRun


def _record_event(
    *,
    case: A0ScheduledPair,
    record: RunRecord,
    resolver: ProbeAssetResolver,
    call_index: int,
) -> dict[str, Any]:
    request = resolver.resolve(record.arm)
    expected_seed = (
        case.control_seed
        if record.condition == "control"
        else case.treatment_seed
    )
    event: dict[str, Any] = {
        "event_type": "a0_model_call",
        "call_index": call_index,
        "pair_id": case.pair_id,
        "contrast_id": case.contrast_id,
        "causal_factor": case.contrast.causal_factor,
        "task_id": case.task_id,
        "agent_label": case.agent_label,
        "repeat_index": case.repeat_index,
        "execution_order": case.execution_order,
        "condition": record.condition,
        "run_id": record.arm.run_id,
        "primary_seed": case.primary_seed,
        "alternate_seed": case.alternate_seed,
        "effective_seed": expected_seed,
        "request_fingerprint": request.request_fingerprint,
        "arm": asdict(record.arm),
        "status": record.status,
        "latency_ms": record.latency_ms,
    }
    if record.status == "failed":
        event.update(
            {
                "failure_type": record.failure_type,
                "failure_message": record.failure_message,
            }
        )
        return event

    response = record.response
    if response is None:
        raise ValueError("completed record has no response")
    audit = response.audit
    if audit is not None:
        if audit.effective_seed != expected_seed:
            raise ValueError("adapter effective seed does not match frozen schedule")
        if audit.request_fingerprint != request.request_fingerprint:
            raise ValueError("adapter request fingerprint does not match frozen assets")
    event.update(
        {
            "model_id": response.model_id,
            "behavior_signature": {
                "requirement_id": response.requirement_id,
                "action_type": response.action_type,
            },
            "structured_output": response.content,
            "input_tokens": response.input_tokens,
            "output_tokens": response.output_tokens,
            "evidence_score": response.evidence_score,
            "score_components": {
                "critical_fact_score": response.critical_fact_score,
                "citation_score": response.citation_score,
                "contradiction_score": response.contradiction_score,
                "decision_score": response.decision_score,
            },
            "scoring_issues": list(response.scoring_issues),
            "invocation_audit": asdict(audit) if audit is not None else None,
        }
    )
    return event


def execute_core_schedule(
    schedule: Sequence[A0ScheduledPair],
    *,
    adapter_factory: AdapterFactory,
    resolver: ProbeAssetResolver,
    store: RunArtifactStore | None = None,
) -> tuple[A0PilotOutcome, ...]:
    """Run a frozen schedule serially and retain failures in their planned slots."""

    cases = tuple(schedule)
    if not cases or not all(isinstance(case, A0ScheduledPair) for case in cases):
        raise ValueError("schedule must contain A0ScheduledPair values")
    if len({case.pair_id for case in cases}) != len(cases):
        raise ValueError("schedule pair IDs must be unique")
    if not callable(adapter_factory):
        raise ValueError("adapter_factory must be callable")
    if not isinstance(resolver, ProbeAssetResolver):
        raise ValueError("resolver must be a ProbeAssetResolver")

    outcomes: list[A0PilotOutcome] = []
    call_index = 0
    for case in cases:
        paired = run_contrast(
            case.contrast,
            adapter_factory(case),
            pair_id=case.pair_id,
            pair_seed=case.primary_seed,
            execution_order=case.execution_order,
        )
        outcome = A0PilotOutcome(case=case, paired=paired)
        outcomes.append(outcome)
        ordered_records = (
            paired.records
            if case.execution_order == "control_first"
            else (paired.treatment, paired.control)
        )
        for record in ordered_records:
            call_index += 1
            if store is not None:
                store.append_event(
                    _record_event(
                        case=case,
                        record=record,
                        resolver=resolver,
                        call_index=call_index,
                    )
                )
    return tuple(outcomes)


def _mean(values: Sequence[float]) -> float | None:
    return None if not values else round(sum(values) / len(values), 6)


def _signature_key(record: RunRecord) -> str | None:
    signature = record.behavior_signature
    if signature is None:
        return None
    return f"{signature.requirement_id}|{signature.action_type}"


def _contrast_metrics(outcomes: Sequence[A0PilotOutcome]) -> dict[str, Any]:
    records = [record for outcome in outcomes for record in outcome.paired.records]
    completed_pairs = [
        outcome
        for outcome in outcomes
        if all(record.status == "completed" for record in outcome.paired.records)
    ]
    requirement_changed = sum(
        outcome.paired.control.response.requirement_id
        != outcome.paired.treatment.response.requirement_id
        for outcome in completed_pairs
        if outcome.paired.control.response is not None
        and outcome.paired.treatment.response is not None
    )
    action_changed = sum(
        outcome.paired.control.response.action_type
        != outcome.paired.treatment.response.action_type
        for outcome in completed_pairs
        if outcome.paired.control.response is not None
        and outcome.paired.treatment.response is not None
    )
    joint_changed = sum(
        outcome.paired.control.behavior_signature
        != outcome.paired.treatment.behavior_signature
        for outcome in completed_pairs
    )
    score_deltas = [
        outcome.paired.treatment.evidence_score
        - outcome.paired.control.evidence_score
        for outcome in completed_pairs
        if outcome.paired.control.evidence_score is not None
        and outcome.paired.treatment.evidence_score is not None
    ]
    signature_counts: dict[str, Counter[str]] = {
        "control": Counter(),
        "treatment": Counter(),
    }
    for record in records:
        key = _signature_key(record)
        if key is not None:
            signature_counts[record.condition][key] += 1
    return {
        "planned_pairs": len(outcomes),
        "completed_pairs": len(completed_pairs),
        "failed_calls": sum(record.status == "failed" for record in records),
        "requirement_changed_pairs": requirement_changed,
        "action_changed_pairs": action_changed,
        "joint_signature_changed_pairs": joint_changed,
        "mean_treatment_minus_control_score": _mean(score_deltas),
        "signature_counts": {
            condition: dict(sorted(counts.items()))
            for condition, counts in signature_counts.items()
        },
    }


def summarize_core_outcomes(
    schedule: Sequence[A0ScheduledPair],
    outcomes: Sequence[A0PilotOutcome],
) -> dict[str, Any]:
    cases = tuple(schedule)
    results = tuple(outcomes)
    if len(cases) != len(results) or any(
        case != outcome.case for case, outcome in zip(cases, results, strict=True)
    ):
        raise ValueError("outcomes do not match the frozen schedule")
    records = [record for outcome in results for record in outcome.paired.records]
    by_contrast: dict[str, list[A0PilotOutcome]] = defaultdict(list)
    for outcome in results:
        by_contrast[outcome.case.contrast_id].append(outcome)

    tasks = {case.task_id for case in cases}
    agents = {case.agent_label for case in cases}
    cell_repeats: dict[tuple[str, str, str], set[int]] = defaultdict(set)
    for case in cases:
        cell_repeats[(case.task_id, case.agent_label, case.contrast_id)].add(
            case.repeat_index
        )
    has_full_core_shape = (
        len(tasks) == 2
        and len(agents) == 3
        and set(by_contrast) == set(CORE_CONTRAST_IDS)
        and all(len(repeats) >= 5 for repeats in cell_repeats.values())
        and len(cell_repeats) == 24
    )
    failed_calls = sum(record.status == "failed" for record in records)
    input_tokens = [
        record.input_tokens for record in records if record.input_tokens is not None
    ]
    output_tokens = [
        record.output_tokens for record in records if record.output_tokens is not None
    ]
    return {
        "schema_version": "a0.core-pilot.metrics.v1",
        "evidence_level": (
            "exploratory_scientific_candidate"
            if has_full_core_shape
            else "exploratory_technical"
        ),
        "scientific_claim_eligible": has_full_core_shape and failed_calls == 0,
        "planned_pairs": len(cases),
        "planned_calls": len(cases) * 2,
        "completed_calls": sum(record.status == "completed" for record in records),
        "failed_calls": failed_calls,
        "completed_pairs": sum(
            all(record.status == "completed" for record in outcome.paired.records)
            for outcome in results
        ),
        "total_input_tokens": sum(input_tokens),
        "total_output_tokens": sum(output_tokens),
        "mean_latency_ms": _mean([record.latency_ms for record in records]),
        "execution_order_counts": dict(
            sorted(Counter(case.execution_order for case in cases).items())
        ),
        "failure_type_counts": dict(
            sorted(
                Counter(
                    record.failure_type
                    for record in records
                    if record.failure_type is not None
                ).items()
            )
        ),
        "by_contrast": {
            contrast_id: _contrast_metrics(by_contrast.get(contrast_id, ()))
            for contrast_id in CORE_CONTRAST_IDS
            if contrast_id in by_contrast
        },
    }


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _get_json(url: str, timeout_seconds: float = 10.0) -> Mapping[str, Any]:
    try:
        with urlopen(url, timeout=timeout_seconds) as response:
            value = json.loads(response.read())
    except (HTTPError, URLError, TimeoutError, OSError, json.JSONDecodeError) as error:
        raise RuntimeError(f"cannot read Ollama metadata from {url}: {error}") from error
    if not isinstance(value, Mapping):
        raise RuntimeError(f"Ollama metadata at {url} is not a JSON object")
    return value


def read_ollama_identity(endpoint: str, model_id: str) -> dict[str, Any]:
    base = endpoint.rstrip("/")
    version = _get_json(f"{base}/api/version").get("version")
    tags = _get_json(f"{base}/api/tags").get("models")
    if not isinstance(version, str) or not version:
        raise RuntimeError("Ollama API did not report a runtime version")
    if not isinstance(tags, list):
        raise RuntimeError("Ollama API did not report a model list")
    model = next(
        (
            item
            for item in tags
            if isinstance(item, Mapping)
            and (item.get("name") == model_id or item.get("model") == model_id)
        ),
        None,
    )
    if model is None:
        raise RuntimeError(f"Ollama model is not installed: {model_id}")
    return {
        "runtime_version": version,
        "requested_model_id": model_id,
        "resolved_name": model.get("name"),
        "resolved_model": model.get("model"),
        "digest": model.get("digest"),
        "size_bytes": model.get("size"),
        "modified_at": model.get("modified_at"),
        "details": dict(model.get("details", {}))
        if isinstance(model.get("details"), Mapping)
        else None,
    }


def _git_snapshot(experiment_root: Path) -> dict[str, Any]:
    try:
        repository_root = Path(
            subprocess.run(
                ["git", "rev-parse", "--show-toplevel"],
                cwd=experiment_root,
                check=True,
                capture_output=True,
                text=True,
            ).stdout.strip()
        ).resolve()
        head = subprocess.run(
            ["git", "rev-parse", "HEAD"],
            cwd=repository_root,
            check=True,
            capture_output=True,
            text=True,
        ).stdout.strip()
        status = subprocess.run(
            ["git", "status", "--short", "--", "."],
            cwd=repository_root,
            check=True,
            capture_output=True,
            text=True,
        ).stdout.splitlines()
    except (OSError, subprocess.CalledProcessError):
        return {
            "head": None,
            "repository_root": None,
            "repository_status": None,
        }
    return {
        "head": head or None,
        "repository_root": str(repository_root),
        "repository_status": status,
    }


def _source_hashes(experiment_root: Path) -> dict[str, str]:
    relative_paths = (
        "pyproject.toml",
        "src/biofield/a0_runner.py",
        "src/biofield/a0_action_axis.py",
        "src/biofield/a0_action_bias.py",
        "src/biofield/a0_action_probe.py",
        "src/biofield/a0_schedule.py",
        "src/biofield/a0_pilot.py",
        "src/biofield/a0_t0.py",
        "src/biofield/model_probe.py",
        "src/biofield/ollama_adapter.py",
        "src/biofield/probe_assets.py",
        "src/biofield/fixtures/a0/assets.v1.json",
        "src/biofield/fixtures/r1/software_release_readiness/task.v1.json",
        "src/biofield/fixtures/r1/software_release_readiness/answer_key.v1.json",
        "src/biofield/fixtures/r1/cold_chain_readiness/task.v1.json",
        "src/biofield/fixtures/r1/cold_chain_readiness/answer_key.v1.json",
    )
    return {
        relative_path: _sha256_file(experiment_root / relative_path)
        for relative_path in relative_paths
    }


def _schedule_config(schedule: Sequence[A0ScheduledPair]) -> list[dict[str, Any]]:
    return [
        {
            "pair_id": case.pair_id,
            "contrast_id": case.contrast_id,
            "task_id": case.task_id,
            "agent_label": case.agent_label,
            "repeat_index": case.repeat_index,
            "primary_seed": case.primary_seed,
            "alternate_seed": case.alternate_seed,
            "control_seed": case.control_seed,
            "treatment_seed": case.treatment_seed,
            "execution_order": case.execution_order,
            "control_run_id": case.contrast.control.run_id,
            "treatment_run_id": case.contrast.treatment.run_id,
        }
        for case in schedule
    ]


def _summary_markdown(metrics: Mapping[str, Any]) -> str:
    lines = [
        "# A0 核心条件运行摘要",
        "",
        f"- 证据级别：`{metrics['evidence_level']}`",
        f"- 计划调用：{metrics['planned_calls']}",
        f"- 完成调用：{metrics['completed_calls']}",
        f"- 失败调用：{metrics['failed_calls']}",
        f"- 科学主张门槛：{'可进入人工审查' if metrics['scientific_claim_eligible'] else '未达到'}",
        "",
        "本文件只汇总技术事实；行为机制结论必须结合完整样本、噪声带和历史 token 平衡人工审查。",
        "",
    ]
    return "\n".join(lines)


def _parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run the frozen A0 core pilot")
    parser.add_argument("--output-directory", required=True)
    parser.add_argument("--run-id", required=True)
    parser.add_argument("--model", default="qwen3:8b")
    parser.add_argument("--endpoint", default="http://127.0.0.1:11434")
    parser.add_argument("--repeats", type=int, default=2)
    parser.add_argument(
        "--tasks",
        nargs="+",
        default=["software_release_readiness", "cold_chain_readiness"],
    )
    parser.add_argument("--agents", nargs="+", default=["agent.a"])
    parser.add_argument("--base-seed", type=int, default=4100)
    parser.add_argument("--temperature", type=float, default=0.6)
    parser.add_argument("--num-ctx", type=int, default=8192)
    parser.add_argument("--top-p", type=float, default=0.9)
    parser.add_argument("--top-k", type=int, default=40)
    parser.add_argument("--num-predict", type=int, default=1024)
    parser.add_argument("--repeat-penalty", type=float, default=1.1)
    parser.add_argument("--timeout-seconds", type=float, default=180.0)
    return parser.parse_args(argv)


def main(argv: Sequence[str] | None = None) -> int:
    args = _parse_args(argv)
    experiment_root = Path(__file__).parents[2]
    resolver = ProbeAssetResolver()
    schedule = build_core_schedule(
        task_ids=tuple(args.tasks),
        agent_labels=tuple(args.agents),
        repeats=args.repeats,
        base_seed=args.base_seed,
    )
    identity = read_ollama_identity(args.endpoint, args.model)
    store = RunArtifactStore.create(
        args.output_directory,
        "a0-core-pilot",
        args.run_id,
    )
    config = {
        "schema_version": "a0.core-pilot.config.v1",
        "created_at_utc": datetime.now(timezone.utc).isoformat(),
        "evidence_level": "exploratory_technical",
        "scientific_claim_allowed_without_manual_review": False,
        "model": identity,
        "host": {
            "platform": platform.platform(),
            "machine": platform.machine(),
            "python": sys.version,
        },
        "generation": {
            "temperature": args.temperature,
            "num_ctx": args.num_ctx,
            "top_p": args.top_p,
            "top_k": args.top_k,
            "num_predict": args.num_predict,
            "repeat_penalty": args.repeat_penalty,
            "think": False,
            "stream": False,
            "timeout_seconds": args.timeout_seconds,
        },
        "design": {
            "tasks": list(args.tasks),
            "agents": list(args.agents),
            "repeats": args.repeats,
            "core_contrasts": list(CORE_CONTRAST_IDS),
            "planned_pairs": len(schedule),
            "planned_calls": len(schedule) * 2,
            "schedule": _schedule_config(schedule),
        },
        "rules": {
            "retries": "none",
            "pair_arms_adjacent_and_serial": True,
            "failures_remain_in_denominator": True,
            "exclusions": [
                "only calls absent because the process terminated before invocation"
            ],
        },
        "source_sha256": _source_hashes(experiment_root),
        "git": _git_snapshot(experiment_root),
    }
    store.write_config(config)

    def adapter_factory(case: A0ScheduledPair) -> OllamaAdapter:
        return OllamaAdapter(
            model_id=args.model,
            resolver=resolver,
            base_seed=case.primary_seed,
            temperature=args.temperature,
            num_ctx=args.num_ctx,
            top_p=args.top_p,
            top_k=args.top_k,
            num_predict=args.num_predict,
            repeat_penalty=args.repeat_penalty,
            endpoint=args.endpoint,
            timeout_seconds=args.timeout_seconds,
        )

    outcomes = execute_core_schedule(
        schedule,
        adapter_factory=adapter_factory,
        resolver=resolver,
        store=store,
    )
    metrics = summarize_core_outcomes(schedule, outcomes)
    store.write_metrics(metrics)
    store.write_summary(_summary_markdown(metrics))
    print(store.run_directory)
    return 0 if metrics["failed_calls"] == 0 else 2


if __name__ == "__main__":
    raise SystemExit(main())
