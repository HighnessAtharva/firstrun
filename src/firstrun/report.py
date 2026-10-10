"""Track T2. Writes runs/<run_id>/report.md and the cross-run summary table."""

from __future__ import annotations

from pathlib import Path

from firstrun.models import Runbook, RunState


def write_report(state: RunState, runbook: Runbook) -> Path:
    raise NotImplementedError


def summary_table(runs_dir: Path | None = None) -> str:
    """Markdown table over every run in runs/."""
    raise NotImplementedError
