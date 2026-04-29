from __future__ import annotations

import shutil
from pathlib import Path

from property_workflow.orchestration.pipeline import execute_task, run_pipeline_task


def test_full_pipeline_generates_artifacts() -> None:
    root = Path(__file__).resolve().parents[1]
    config = root / "property-workflow-config.yaml"
    run_dir = run_pipeline_task(task="full", config_path=config, date_token="20990101")

    assert (run_dir / "raw_listings.json").exists()
    assert (run_dir / "clean_listings.json").exists()
    assert (run_dir / "analysis_report.json").exists()
    assert (run_dir / "analysis_report.md").exists()
    assert (run_dir / "copywriting.json").exists()


def test_execute_task_returns_config_error_when_config_missing(tmp_path: Path, capsys) -> None:
    missing_config = tmp_path / "missing-config.yaml"
    exit_code = execute_task(task="full", config_path=missing_config, date_token="20990102")

    assert exit_code == 10
    output = capsys.readouterr().out
    assert '"error_code": "E_CONFIG_NOT_FOUND"' in output


def test_execute_task_returns_input_missing_when_clean_without_collect(capsys) -> None:
    root = Path(__file__).resolve().parents[1]
    config = root / "property-workflow-config.yaml"
    date_token = "2099_missing_clean_input"
    run_dir = root / "runtime" / date_token
    if run_dir.exists():
        shutil.rmtree(run_dir)
    exit_code = execute_task(task="clean", config_path=config, date_token=date_token)

    assert exit_code == 12
    output = capsys.readouterr().out
    assert '"error_code": "E_INPUT_MISSING"' in output
