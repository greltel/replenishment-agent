"""
DATA_SOURCE / REPORTS_DIR — keep the sample and the pilot datasets apart.

run_all.bat forces DATA_SOURCE=samples and run_all_pilot.bat forces
DATA_SOURCE=anonymized with its own reports folder, so neither run can pick
up the other dataset's CSVs or reports.
"""
from __future__ import annotations

from dataclasses import replace
from pathlib import Path

import pytest

from src.config import config
from src.data_layer import etl


def _make_dataset(folder: Path) -> Path:
    folder.mkdir(parents=True, exist_ok=True)
    for name in ("materials", "stock", "purchase_orders", "movements"):
        (folder / f"{name}.csv").write_text("material_id\n", encoding="utf-8")
    return folder


@pytest.fixture
def two_datasets(tmp_path):
    return _make_dataset(tmp_path / "anonymized"), _make_dataset(tmp_path / "samples")


def _use(monkeypatch, anon: Path, samp: Path, source: str) -> None:
    cfg = replace(config, data_anonymized_dir=anon, data_samples_dir=samp,
                  data_source=source)
    monkeypatch.setattr(etl, "config", cfg)


def test_auto_prefers_anonymized(monkeypatch, two_datasets):
    anon, samp = two_datasets
    _use(monkeypatch, anon, samp, "auto")
    assert etl._resolve_data_dir() == anon


def test_auto_falls_back_to_samples(monkeypatch, tmp_path):
    samp = _make_dataset(tmp_path / "samples")
    _use(monkeypatch, tmp_path / "empty", samp, "auto")
    assert etl._resolve_data_dir() == samp


def test_samples_forced_even_if_anonymized_exists(monkeypatch, two_datasets):
    anon, samp = two_datasets
    _use(monkeypatch, anon, samp, "samples")
    assert etl._resolve_data_dir() == samp


def test_anonymized_forced_never_falls_back_to_samples(monkeypatch, tmp_path):
    samp = _make_dataset(tmp_path / "samples")
    _use(monkeypatch, tmp_path / "empty", samp, "anonymized")
    with pytest.raises(FileNotFoundError):
        etl._resolve_data_dir()


def test_unknown_data_source_is_rejected(monkeypatch, two_datasets):
    anon, samp = two_datasets
    _use(monkeypatch, anon, samp, "pilot")
    with pytest.raises(ValueError):
        etl._resolve_data_dir()


@pytest.fixture
def report_folders(monkeypatch, tmp_path):
    from dashboard.components import validation_tab

    root = tmp_path / "root"                 # sample-data reports
    pilot = root / "reports" / "pilot"       # pilot reports
    pilot.mkdir(parents=True)
    (root / "bootstrap_report.csv").write_text("window\n1\n", encoding="utf-8")
    (pilot / "validation_report.csv").write_text("metric\nx\n", encoding="utf-8")
    monkeypatch.setattr(validation_tab, "PROJECT_ROOT", root)
    return validation_tab, root, pilot


def test_reports_dir_isolates_the_dashboard_reports(monkeypatch, report_folders):
    validation_tab, root, pilot = report_folders
    monkeypatch.setattr(validation_tab, "config", replace(config, reports_dir=pilot))

    assert validation_tab._load_csv("validation_report.csv") is not None
    # A report missing from REPORTS_DIR is not taken from the project root
    # (that would show sample-data results next to pilot results).
    assert validation_tab._load_csv("bootstrap_report.csv") is None


def test_default_reports_dir_reads_the_project_root(monkeypatch, report_folders):
    validation_tab, root, pilot = report_folders
    monkeypatch.setattr(validation_tab, "config", replace(config, reports_dir=root))

    assert validation_tab._load_csv("bootstrap_report.csv") is not None
    assert validation_tab._load_csv("validation_report.csv") is None
