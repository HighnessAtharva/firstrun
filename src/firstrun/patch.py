"""Track T5. The docs diff and the draft PR body."""

from __future__ import annotations

from firstrun.models import Patch, RunState


def make_diff(docs_md: str, patches: list[Patch], path: str = "quickstart.md") -> str:
    """Unified diff of the docs markdown with each patched command replaced."""
    raise NotImplementedError


def make_pr_body(state: RunState, patches: list[Patch], trace_url: str = "") -> str:
    raise NotImplementedError
