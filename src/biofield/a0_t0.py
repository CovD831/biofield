from __future__ import annotations

import argparse
import platform
import sys
from collections.abc import Sequence
from dataclasses import asdict, replace
from datetime import datetime, timezone
from pathlib import Path
from time import perf_counter
from typing import Any

from biofield.a0_pilot import _git_snapshot, _source_hashes, read_ollama_identity
from biofield.a0_runner import ProbeResponse
from biofield.artifacts import RunArtifactStore
from biofield.model_probe import ProbeArm
from biofield.ollama_adapter import OllamaAdapter
from biofield.probe_assets import ProbeAssetResolver


def build_t0_arms(
    task_ids: tuple[str, ...],
    *,
    repeats: int = 2,
) -> tuple[ProbeArm, ...]:
    if not task_ids or len(set(task_ids)) != len(task_ids):
        raise ValueError("task_ids must be non-empty and unique")
    if isinstance(repeats, bool) or not isinstance(repeats, int) or repeats < 2:
        raise ValueError("T0 requires at least two repeats")
    return tuple(
        replace(
            ProbeArm.reference(),
            run_id=f"a0.t0.{task_id}.rep{repeat_index:02d}",
            task_id=task_id,
            sample_id=0,
        )
        for task_id in task_ids
        for repeat_index in range(1, repeats + 1)
    )


def summarize_t0(
    arms: Sequence[ProbeArm],
    responses: Sequence[ProbeResponse | None],
) -> dict[str, Any]:
    planned = tuple(arms)
    observed = tuple(responses)
    if len(planned) != len(observed):
        raise ValueError("T0 responses must align with planned arms")
    by_task: dict[str, dict[str, Any]] = {}
    for task_id in dict.fromkeys(arm.task_id for arm in planned):
        task_responses = [
            response
            for arm, response in zip(planned, observed, strict=True)
            if arm.task_id == task_id and response is not None
        ]
        expected_count = sum(arm.task_id == task_id for arm in planned)
        complete = len(task_responses) == expected_count
        by_task[task_id] = {
            "planned_repeats": expected_count,
            "completed_repeats": len(task_responses),
            "exact_content_repeatable": complete
            and len({response.content for response in task_responses}) == 1,
            "behavior_signature_repeatable": complete
            and len(
                {
                    (
                        response.requirement_id,
                        response.action_type,
                    )
                    for response in task_responses
                }
            )
            == 1,
            "input_token_counts": [
                response.input_tokens for response in task_responses
            ],
            "output_token_counts": [
                response.output_tokens for response in task_responses
            ],
            "evidence_scores": [
                response.evidence_score for response in task_responses
            ],
        }
    return {
        "schema_version": "a0.t0.metrics.v1",
        "evidence_level": "engineering_smoke",
        "scientific_claim_eligible": False,
        "planned_calls": len(planned),
        "completed_calls": sum(response is not None for response in observed),
        "failed_calls": sum(response is None for response in observed),
        "by_task": by_task,
    }


def _parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run A0 T0 same-seed checks")
    parser.add_argument("--output-directory", required=True)
    parser.add_argument("--run-id", required=True)
    parser.add_argument("--model", default="qwen3:8b")
    parser.add_argument("--endpoint", default="http://127.0.0.1:11434")
    parser.add_argument("--seed", type=int, default=4200)
    parser.add_argument("--temperature", type=float, default=0.6)
    parser.add_argument("--timeout-seconds", type=float, default=300.0)
    parser.add_argument("--warmup-already-completed", action="store_true")
    return parser.parse_args(argv)


def main(argv: Sequence[str] | None = None) -> int:
    args = _parse_args(argv)
    experiment_root = Path(__file__).parents[2]
    task_ids = ("software_release_readiness", "cold_chain_readiness")
    arms = build_t0_arms(task_ids, repeats=2)
    resolver = ProbeAssetResolver()
    identity = read_ollama_identity(args.endpoint, args.model)
    adapter = OllamaAdapter(
        model_id=args.model,
        resolver=resolver,
        base_seed=args.seed,
        temperature=args.temperature,
        num_ctx=8192,
        top_p=0.9,
        top_k=40,
        num_predict=1024,
        repeat_penalty=1.1,
        endpoint=args.endpoint,
        timeout_seconds=args.timeout_seconds,
    )
    store = RunArtifactStore.create(
        args.output_directory,
        "a0-t0",
        args.run_id,
    )
    source_hashes = _source_hashes(experiment_root)
    store.write_config(
        {
            "schema_version": "a0.t0.config.v1",
            "created_at_utc": datetime.now(timezone.utc).isoformat(),
            "evidence_level": "engineering_smoke",
            "warmup_excluded_from_metrics": True,
            "warmup_already_completed": args.warmup_already_completed,
            "model": identity,
            "host": {
                "platform": platform.platform(),
                "machine": platform.machine(),
                "python": sys.version,
            },
            "generation": {
                "seed": args.seed,
                "temperature": args.temperature,
                "num_ctx": 8192,
                "top_p": 0.9,
                "top_k": 40,
                "num_predict": 1024,
                "repeat_penalty": 1.1,
                "think": False,
                "stream": False,
            },
            "plan": [
                {
                    "run_id": arm.run_id,
                    "task_id": arm.task_id,
                    "seed": args.seed,
                    "request_fingerprint": resolver.resolve(
                        arm
                    ).request_fingerprint,
                }
                for arm in arms
            ],
            "source_sha256": source_hashes,
            "git": _git_snapshot(experiment_root),
        }
    )

    responses: list[ProbeResponse | None] = []
    for call_index, arm in enumerate(arms, start=1):
        request = resolver.resolve(arm)
        start = perf_counter()
        try:
            response = adapter.invoke(arm)
        except Exception as error:
            responses.append(None)
            store.append_event(
                {
                    "event_type": "a0_t0_call",
                    "call_index": call_index,
                    "run_id": arm.run_id,
                    "task_id": arm.task_id,
                    "seed": args.seed,
                    "request_fingerprint": request.request_fingerprint,
                    "status": "failed",
                    "latency_ms": round((perf_counter() - start) * 1000, 6),
                    "failure_type": type(error).__name__,
                    "failure_message": str(error) or "<no failure message>",
                }
            )
            continue
        responses.append(response)
        store.append_event(
            {
                "event_type": "a0_t0_call",
                "call_index": call_index,
                "run_id": arm.run_id,
                "task_id": arm.task_id,
                "seed": args.seed,
                "request_fingerprint": request.request_fingerprint,
                "status": "completed",
                "latency_ms": round((perf_counter() - start) * 1000, 6),
                "model_id": response.model_id,
                "behavior_signature": asdict(response.behavior_signature),
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
                "invocation_audit": asdict(response.audit)
                if response.audit is not None
                else None,
            }
        )
    metrics = summarize_t0(arms, responses)
    store.write_metrics(metrics)
    store.write_summary(
        "# A0 T0 同 seed 重复性检查\n\n"
        f"- 完成：{metrics['completed_calls']}/{metrics['planned_calls']}\n"
        f"- 失败：{metrics['failed_calls']}\n"
        "- 证据级别：engineering_smoke，不支持架构科学结论。\n"
    )
    print(store.run_directory)
    return 0 if metrics["failed_calls"] == 0 else 2


if __name__ == "__main__":
    raise SystemExit(main())
