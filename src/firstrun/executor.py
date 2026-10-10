"""Track T2. Runs a runbook step by step and checkpoints after each step."""

from __future__ import annotations

from firstrun.models import Runbook, RunState, Step, StepResult
from firstrun.sandbox import Container


def check_expected(step: Step, result: StepResult) -> bool:
    """True when the result meets step.expected."""
    raise NotImplementedError


def run_step(container: Container, step: Step) -> StepResult:
    """TOOL span `step.<id>`. Writes the step's files, runs its command, checks `expected`."""
    raise NotImplementedError


def run(runbook: Runbook, run_id: str | None = None, resume: bool = False, tags: list[str] | None = None) -> RunState:
    """WORKFLOW span `firstrun.run`. Writes runbook.json, state.json after each step, then report.md."""
    raise NotImplementedError
