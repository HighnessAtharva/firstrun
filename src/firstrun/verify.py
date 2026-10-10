"""Track T5. Model-free re-run of the patched runbook in a brand-new container."""

from __future__ import annotations

from firstrun.models import Patch, Runbook, RunStatus


def apply_patches(runbook: Runbook, patches: list[Patch]) -> Runbook:
    raise NotImplementedError


def verify(runbook: Runbook, patches: list[Patch]) -> RunStatus:
    """GUARDRAIL span `verify`. Returns RunStatus.VERIFIED or RunStatus.UNVERIFIED. Never calls a model."""
    raise NotImplementedError
