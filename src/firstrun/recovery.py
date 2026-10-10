"""Track T4. Classify, search, patch, retry. At most 3 attempts per step."""

from __future__ import annotations

from firstrun.models import GaveUp, Patch, RunState, Step, StepResult


def recover(step: Step, result: StepResult, state: RunState, docs_markdown: str = "") -> Patch | GaveUp:
    """AGENT span `recover.<id>`. Returns a Patch to retry with, or GaveUp."""
    raise NotImplementedError
