from __future__ import annotations

from pathlib import Path

from biofield.evidence_task import _fixture_root, available_task_ids, load_task_bundle
from biofield.meas0_channel_order import load_channel_order_subject_fixture
from biofield.meas0_pilot_runner import load_pilot_mutation_manifest
from biofield.probe_assets import _default_asset_path, _default_r1_root


PACKAGE_ROOT = Path(__file__).parents[1] / "src" / "biofield"


def test_default_fixtures_live_inside_the_installable_package() -> None:
    assert _default_asset_path() == PACKAGE_ROOT / "fixtures" / "a0" / "assets.v1.json"
    assert _default_r1_root() == PACKAGE_ROOT / "fixtures" / "r1"
    assert _fixture_root() == PACKAGE_ROOT / "fixtures" / "r1"


def test_packaged_defaults_load_without_checkout_relative_paths() -> None:
    assert available_task_ids() == (
        "cold_chain_readiness",
        "software_release_readiness",
    )
    assert load_task_bundle("cold_chain_readiness").task.task_version == "1"
    assert load_channel_order_subject_fixture().task_version == "1"
    assert load_pilot_mutation_manifest().version == 8
