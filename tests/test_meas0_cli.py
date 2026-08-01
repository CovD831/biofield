from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from biofield.meas0 import main


def test_pilot_cli_dispatches_prepare_run_replay_and_summarize(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    calls: list[tuple[str, object]] = []
    lock_path = tmp_path / "lock.json"
    run_path = tmp_path / "run"

    def prepare(**kwargs: object) -> Path:
        calls.append(("prepare", kwargs))
        return lock_path

    def run(**kwargs: object) -> Path:
        calls.append(("run", kwargs))
        return run_path

    def replay(path: object) -> object:
        calls.append(("replay", path))
        return SimpleNamespace(to_dict=lambda: {"verified": True})

    def summarize(path: object) -> dict[str, object]:
        calls.append(("summarize", path))
        return {"sealed": True}

    monkeypatch.setattr("biofield.meas0_pilot_run.prepare_pilot_run", prepare)
    monkeypatch.setattr("biofield.meas0_pilot_run.execute_pilot_run", run)
    monkeypatch.setattr("biofield.meas0_pilot_run.replay_pilot_run", replay)
    monkeypatch.setattr("biofield.meas0_pilot_run.summarize_pilot_run", summarize)

    monkeypatch.setattr(
        "sys.argv",
        [
            "biofield-meas0",
            "prepare",
            "--design",
            str(tmp_path / "design.md"),
            "--phase",
            "pilot",
            "--lock-directory",
            str(tmp_path / "locks"),
            "--lock-id",
            "lock-v1",
        ],
    )
    main()
    assert Path(capsys.readouterr().out.strip()) == lock_path

    readiness = tmp_path / "readiness.json"
    monkeypatch.setattr(
        "sys.argv",
        [
            "biofield-meas0",
            "run",
            "--lock",
            str(lock_path),
            "--output-directory",
            str(tmp_path / "runs"),
            "--run-id",
            "run-v1",
            "--execution-mode",
            "formal",
            "--readiness-bundle",
            str(readiness),
            "--comparison-block",
            "formal-block-v1",
        ],
    )
    main()
    assert Path(capsys.readouterr().out.strip()) == run_path

    monkeypatch.setattr(
        "sys.argv",
        ["biofield-meas0", "replay", "--run", str(run_path)],
    )
    main()
    assert json.loads(capsys.readouterr().out) == {"verified": True}

    monkeypatch.setattr(
        "sys.argv",
        ["biofield-meas0", "summarize", "--run", str(run_path)],
    )
    main()
    assert json.loads(capsys.readouterr().out) == {"sealed": True}

    assert [name for name, _ in calls] == [
        "prepare",
        "run",
        "replay",
        "summarize",
    ]
    run_arguments = calls[1][1]
    assert isinstance(run_arguments, dict)
    assert run_arguments["execution_mode"] == "formal"
    assert run_arguments["readiness_bundle_path"] == readiness
    assert run_arguments["comparison_block_id"] == "formal-block-v1"
