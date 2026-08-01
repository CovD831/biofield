from __future__ import annotations

import json
from dataclasses import replace
from pathlib import Path

import pytest

from biofield.meas0_channel_order import (
    ChannelOrderEvaluatorError,
    load_channel_order_evaluator,
    load_channel_order_subject_fixture,
    load_channel_order_subject_input,
    materialize_channel_order_case,
    verify_channel_order_episode_artifacts,
)
from biofield.measurement import EvaluationStatus, fuse_evidence


CORRECT_SOURCE = """
from decimal import Decimal


def ingest_event(connection, event):
    channel = event["channel"]
    if channel not in {"direct", "marketplace"}:
        raise ValueError("unsupported channel")
    amount_cents = int(Decimal(event["amount"]) * 100)
    existing = connection.execute(
        "SELECT 1 FROM orders WHERE event_id = ?",
        (event["event_id"],),
    ).fetchone()
    if existing is not None:
        return
    connection.execute(
        "INSERT INTO orders "
        "(event_id, channel, source_order_id, amount_cents, currency, recipient_name) "
        "VALUES (?, ?, ?, ?, ?, ?)",
        (
            event["event_id"],
            channel,
            event["external_order_id"],
            amount_cents,
            event["currency"],
            event["recipient_name"],
        ),
    )
    connection.execute(
        "INSERT INTO order_events (event_id, event_type) VALUES (?, ?)",
        (event["event_id"], "created"),
    )
    connection.commit()
""".lstrip()


NON_IDEMPOTENT_SOURCE = """
from decimal import Decimal


def ingest_event(connection, event):
    connection.execute(
        "INSERT INTO orders "
        "(event_id, channel, source_order_id, amount_cents, currency, recipient_name) "
        "VALUES (?, ?, ?, ?, ?, ?)",
        (
            event["event_id"],
            event["channel"],
            event["external_order_id"],
            int(Decimal(event["amount"]) * 100),
            event["currency"],
            event["recipient_name"],
        ),
    )
    connection.execute(
        "INSERT INTO order_events (event_id, event_type) VALUES (?, ?)",
        (event["event_id"], "created"),
    )
    connection.commit()
""".lstrip()

PROTECTED_MUTATING_SOURCE = """
from pathlib import Path


event_path = (
    Path.cwd()
    / "protected"
    / "events"
    / "marketplace_event.json"
)
event_path.write_bytes(b"{}")


def ingest_event(connection, event):
    raise AssertionError("must not execute after protected-tree mutation")
""".lstrip()

NETWORK_ATTEMPT_SOURCE = (
    "import socket\n"
    "socket.socket()\n\n"
    + CORRECT_SOURCE
)


def _delivery_bytes() -> bytes:
    return json.dumps(
        {
            "changed_files": ["workspace/src/order_ingest.py"],
            "checks_run": ["public direct regression", "protected integration"],
            "limitations": ["offline fixture only"],
        },
        sort_keys=True,
        separators=(",", ":"),
    ).encode()


def _statuses(observations: tuple[object, ...]) -> dict[str, object]:
    return {
        observation.measurement_id: observation.status  # type: ignore[attr-defined]
        for observation in observations
    }


def test_channel_order_subject_fixture_is_packaged_and_gold_free(
    tmp_path: Path,
) -> None:
    package_fixture = load_channel_order_subject_fixture()
    fixture_directory = tmp_path / "meas0" / "channel_order_ingest"
    fixture_directory.mkdir(parents=True)
    (fixture_directory / "task.v1.json").write_bytes(
        package_fixture.source_bytes
    )

    isolated = load_channel_order_subject_fixture(fixture_root=tmp_path)
    serialized = json.dumps(isolated.to_dict(), sort_keys=True)

    assert isolated.task_id == "channel_order_ingest"
    assert "evt-market-2001" not in serialized
    assert "MP-8842" not in serialized
    assert "expected" not in serialized


def test_materialized_subject_input_never_reads_protected_tree(
    tmp_path: Path,
) -> None:
    case_directory = materialize_channel_order_case(tmp_path / "case")
    protected = case_directory / "protected"
    hidden = case_directory / "hidden-for-test"
    protected.rename(hidden)

    subject = load_channel_order_subject_input(case_directory)

    assert subject.workspace_directory == case_directory / "workspace"
    assert all("protected" not in value for value in subject.visible_paths)
    assert "protected" not in json.dumps(subject.to_dict(), sort_keys=True)


def test_correct_channel_order_implementation_passes_deterministic_bundle(
    tmp_path: Path,
) -> None:
    case_directory = materialize_channel_order_case(tmp_path / "case")
    source_path = case_directory / "workspace" / "src" / "order_ingest.py"
    source_path.write_text(CORRECT_SOURCE, encoding="utf-8")
    evaluator = load_channel_order_evaluator(case_directory)

    episode = evaluator.execute(
        delivery_bytes=_delivery_bytes(),
        response_bytes=b"Implemented marketplace ingest and ran both checks.",
    )
    verify_channel_order_episode_artifacts(
        episode,
        task_measurement_bundle=evaluator.measurement_bundle,
    )
    observations = evaluator.evaluate(episode)
    result = fuse_evidence(
        result_id="channel-order-correct",
        task_measurement_bundle=evaluator.measurement_bundle,
        sealed_episode=episode.sealed_episode,
        observations=observations,
    )

    assert all(item.status is EvaluationStatus.PASS for item in observations)
    assert sum(item.cost for item in observations) == pytest.approx(
        evaluator.measurement_bundle.measurement_budget
    )
    assert result.outcome is EvaluationStatus.PASS


def test_text_only_claim_cannot_replace_code_state_or_delivery(
    tmp_path: Path,
) -> None:
    case_directory = materialize_channel_order_case(tmp_path / "case")
    evaluator = load_channel_order_evaluator(case_directory)

    episode = evaluator.execute(
        delivery_bytes=None,
        response_bytes=(
            b"Marketplace ingest is implemented, idempotent, and fully tested."
        ),
    )
    observations = evaluator.evaluate(episode)
    statuses = _statuses(observations)

    assert statuses["r2.marketplace_row"] is EvaluationStatus.FAIL
    assert statuses["r2.idempotency"] is not EvaluationStatus.PASS
    assert statuses["r2.delivery_completeness"] is EvaluationStatus.FAIL


def test_non_idempotent_implementation_fails_protected_oracle(
    tmp_path: Path,
) -> None:
    case_directory = materialize_channel_order_case(tmp_path / "case")
    source_path = case_directory / "workspace" / "src" / "order_ingest.py"
    source_path.write_text(NON_IDEMPOTENT_SOURCE, encoding="utf-8")
    evaluator = load_channel_order_evaluator(case_directory)

    episode = evaluator.execute(
        delivery_bytes=_delivery_bytes(),
        response_bytes=b"Implemented ingestion.",
    )
    statuses = _statuses(evaluator.evaluate(episode))

    assert statuses["r2.idempotency"] is EvaluationStatus.FAIL
    assert statuses["r2.marketplace_row"] is EvaluationStatus.FAIL
    assert statuses["r2.no_collateral_change"] is EvaluationStatus.FAIL


def test_delivery_changed_files_must_match_observed_workspace_changes(
    tmp_path: Path,
) -> None:
    case_directory = materialize_channel_order_case(tmp_path / "case")
    source_path = case_directory / "workspace" / "src" / "order_ingest.py"
    source_path.write_text(CORRECT_SOURCE, encoding="utf-8")
    evaluator = load_channel_order_evaluator(case_directory)
    delivery = json.dumps(
        {
            "changed_files": ["workspace/src/not-the-changed-file.py"],
            "checks_run": ["public direct regression", "integration"],
            "limitations": ["offline fixture only"],
        },
        sort_keys=True,
        separators=(",", ":"),
    ).encode()

    episode = evaluator.execute(
        delivery_bytes=delivery,
        response_bytes=b"Implemented ingestion.",
    )
    statuses = _statuses(evaluator.evaluate(episode))

    assert statuses["r2.delivery_completeness"] is EvaluationStatus.FAIL


def test_channel_order_rejects_sealed_bytes_and_protected_tree_tampering(
    tmp_path: Path,
) -> None:
    case_directory = materialize_channel_order_case(tmp_path / "case")
    source_path = case_directory / "workspace" / "src" / "order_ingest.py"
    source_path.write_text(CORRECT_SOURCE, encoding="utf-8")
    evaluator = load_channel_order_evaluator(case_directory)
    episode = evaluator.execute(
        delivery_bytes=_delivery_bytes(),
        response_bytes=b"Implemented ingestion.",
    )
    tampered_artifacts = replace(
        episode.artifacts,
        items=tuple(
            (evidence_id, b"not-a-sqlite-database")
            if evidence_id == "artifact:result.sqlite"
            else (evidence_id, content)
            for evidence_id, content in episode.artifacts.items
        ),
    )

    with pytest.raises(ChannelOrderEvaluatorError, match="content_hash"):
        evaluator.evaluate(replace(episode, artifacts=tampered_artifacts))

    protected_event = (
        case_directory
        / "protected"
        / "events"
        / "marketplace_event.json"
    )
    protected_event.write_text('{"event_id":"tampered"}', encoding="utf-8")
    with pytest.raises(ChannelOrderEvaluatorError, match="protected.*hash"):
        evaluator.execute(
            delivery_bytes=_delivery_bytes(),
            response_bytes=b"retry",
        )


def test_channel_order_rejects_protected_manifest_tampering(
    tmp_path: Path,
) -> None:
    case_directory = materialize_channel_order_case(tmp_path / "case")
    evaluator = load_channel_order_evaluator(case_directory)
    manifest = (
        case_directory
        / "protected"
        / "grader"
        / "original_manifest.json"
    )
    manifest.write_bytes(b"{}")

    with pytest.raises(ChannelOrderEvaluatorError, match="protected.*hash"):
        evaluator.execute(
            delivery_bytes=_delivery_bytes(),
            response_bytes=b"retry",
        )


def test_subject_cannot_modify_protected_tree_during_execution(
    tmp_path: Path,
) -> None:
    case_directory = materialize_channel_order_case(tmp_path / "case")
    source_path = case_directory / "workspace" / "src" / "order_ingest.py"
    source_path.write_text(PROTECTED_MUTATING_SOURCE, encoding="utf-8")
    evaluator = load_channel_order_evaluator(case_directory)

    with pytest.raises(ChannelOrderEvaluatorError, match="protected.*hash"):
        evaluator.execute(
            delivery_bytes=_delivery_bytes(),
            response_bytes=b"attempted implementation",
        )


def test_public_and_integration_execution_block_network_access(
    tmp_path: Path,
) -> None:
    case_directory = materialize_channel_order_case(tmp_path / "case")
    source_path = case_directory / "workspace" / "src" / "order_ingest.py"
    source_path.write_text(NETWORK_ATTEMPT_SOURCE, encoding="utf-8")
    evaluator = load_channel_order_evaluator(case_directory)

    episode = evaluator.execute(
        delivery_bytes=_delivery_bytes(),
        response_bytes=b"attempted implementation",
    )
    trajectory = json.loads(
        episode.artifacts.get("trajectory:execution") or b"{}"
    )

    assert trajectory["public_test"]["returncode"] != 0
    assert "network access blocked" in trajectory["public_test"]["stderr"]
    assert trajectory["marketplace_first"]["returncode"] != 0
    assert "network access blocked" in trajectory["marketplace_first"]["stderr"]
