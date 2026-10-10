"""Track T1. Reads a docs page and returns a validated runbook."""

from __future__ import annotations

from firstrun.models import Runbook


def read_docs(url: str) -> str:
    """TOOL span `read_docs`. Firecrawl scrape to markdown. A local path or file:// URL reads the file."""
    raise NotImplementedError


def plan_from_markdown(markdown: str, source_url: str) -> Runbook:
    """AGENT span `planner`. Claude turns the markdown into a Runbook. Commands are copied exactly."""
    raise NotImplementedError


def plan(url: str) -> Runbook:
    """read_docs then plan_from_markdown."""
    raise NotImplementedError
