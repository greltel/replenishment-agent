"""
Integration tests — verify that the full pipeline runs end-to-end.

These tests are slower than unit tests because they:
  • generate sample data
  • run the ETL
  • execute the agent
  • verify proposals are persisted

Run with: pytest tests/test_integration.py -v
"""
from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

import pytest

PROJECT_ROOT = Path(__file__).resolve().parent.parent


@pytest.fixture(scope="module")
def isolated_environment(tmp_path_factory):
    """
    Run the pipeline in a temp data directory so it doesn't pollute the
    user's actual database.
    """
    tmp = tmp_path_factory.mktemp("integration")
    env = os.environ.copy()
    # These are the variable names src/config.py actually reads. (Earlier
    # versions set REPLENISHMENT_* names that nothing consumed, so the
    # integration test silently overwrote the developer's real database.)
    env["DATABASE_URL"] = f"sqlite:///{tmp}/test.db"
    env["DATA_SAMPLES_DIR"] = str(tmp / "data" / "samples")
    env["DATA_RAW_DIR"] = str(tmp / "data" / "raw")
    env["DATA_ANONYMIZED_DIR"] = str(tmp / "data" / "anonymized")
    env["LOG_DIR"] = str(tmp / "logs")
    return env, tmp


def run_script(script_name: str, env: dict, *args: str) -> subprocess.CompletedProcess:
    """Run a script as a subprocess and return its result."""
    script_path = PROJECT_ROOT / "scripts" / script_name
    cmd = [sys.executable, str(script_path), *args]
    return subprocess.run(
        cmd, env=env, capture_output=True, text=True, cwd=PROJECT_ROOT, timeout=120
    )


@pytest.mark.integration
def test_full_pipeline(isolated_environment):
    """
    End-to-end smoke test: generate data → ETL → agent → verify proposals.
    """
    env, tmp = isolated_environment

    # Step 1: generate sample data
    result = run_script("generate_sample_data.py", env)
    assert result.returncode == 0, (
        f"generate_sample_data failed:\nSTDOUT: {result.stdout}\nSTDERR: {result.stderr}"
    )
    assert "materials.csv" in result.stdout
    assert "movements.csv" in result.stdout

    # Step 2: ETL
    result = run_script("run_etl.py", env)
    assert result.returncode == 0, (
        f"run_etl failed:\nSTDOUT: {result.stdout}\nSTDERR: {result.stderr}"
    )
    assert "ETL Summary" in result.stdout

    # Step 3: Agent
    result = run_script("run_agent.py", env, "--horizon", "30")
    assert result.returncode == 0, (
        f"run_agent failed:\nSTDOUT: {result.stdout}\nSTDERR: {result.stderr}"
    )
    assert "Agent Run Summary" in result.stdout
    assert "Total proposals:" in result.stdout

    # Step 4: verify proposals exist in the ISOLATED DB (it must exist —
    # otherwise the scripts wrote somewhere else, e.g. the real project DB)
    from sqlalchemy import create_engine, text
    db_path = tmp / "test.db"
    assert db_path.exists(), "Scripts did not use the isolated DATABASE_URL"
    engine = create_engine(f"sqlite:///{db_path}")
    with engine.connect() as conn:
        count = conn.execute(text("SELECT COUNT(*) FROM proposals")).scalar()
        assert count > 0, "No proposals were persisted to DB"
        n_expedite = conn.execute(
            text("SELECT COUNT(*) FROM proposals WHERE expedite = 1")).scalar()
        # Regression guard: with the as-of date anchored one day before the
        # stock snapshot, EVERY proposal used to be flagged as expedite.
        assert n_expedite < count, "All proposals flagged expedite — as-of/stock bug"


@pytest.mark.integration
def test_validation_runs(isolated_environment):
    """The validation/backtest script completes successfully."""
    env, tmp = isolated_environment

    # Pipeline must already have run from the previous test. Write the report
    # into the temp dir so the developer's real validation_report.csv is kept.
    result = run_script("run_validation.py", env, "--window-days", "30",
                        "--out", str(tmp / "validation_report.csv"))
    assert result.returncode == 0, (
        f"validation failed:\nSTDOUT: {result.stdout}\nSTDERR: {result.stderr}"
    )
    assert (tmp / "validation_report.csv").exists()
    # New output format includes scenario header and section headers
    assert "Scenario:" in result.stdout
    assert "Service-Level KPIs" in result.stdout
    assert "Cost KPIs" in result.stdout


@pytest.mark.integration
def test_dry_run_does_not_persist(isolated_environment):
    """--dry-run option should NOT persist proposals."""
    env, tmp = isolated_environment
    from sqlalchemy import create_engine, text
    engine = create_engine(f"sqlite:///{tmp}/test.db")
    with engine.connect() as conn:
        before = conn.execute(text("SELECT COUNT(*) FROM proposals")).scalar()

    result = run_script("run_agent.py", env, "--dry-run", "--horizon", "14")
    assert result.returncode == 0
    assert "[dry-run]" in result.stdout or "dry-run" in result.stdout.lower()

    with engine.connect() as conn:
        after = conn.execute(text("SELECT COUNT(*) FROM proposals")).scalar()
    assert before == after, "dry-run must leave the proposals table untouched"
