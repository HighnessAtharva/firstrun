"""Track T4. Hard limits. Each check is a GUARDRAIL span `budget`."""

from __future__ import annotations

from firstrun.models import Budget, RunState


class BudgetExceeded(Exception):
    pass


def check(state: RunState, budget: Budget, step_id: int | None = None) -> None:
    """Raise BudgetExceeded when a limit trips."""
    raise NotImplementedError
