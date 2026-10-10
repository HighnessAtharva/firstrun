"""Track T2. Reads and writes runs/<run_id>/state.json and runbook.json."""

from __future__ import annotations

from pathlib import Path

from firstrun.models import Runbook, RunState


def run_dir(run_id: str) -> Path:
    raise NotImplementedError


def new_run_id(source_url: str) -> str:
    raise NotImplementedError


def save_state(state: RunState) -> Path:
    raise NotImplementedError


def load_state(run_id: str) -> RunState:
    raise NotImplementedError


def save_runbook(run_id: str, runbook: Runbook) -> Path:
    raise NotImplementedError


def load_runbook(run_id: str) -> Runbook:
    raise NotImplementedError
