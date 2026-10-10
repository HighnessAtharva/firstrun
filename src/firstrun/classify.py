"""Track T4. Classifies a failed step's error output into the four failure classes."""

from __future__ import annotations

from firstrun.models import Classification


def signature(error_text: str) -> str:
    """Short stable signature of an error: strips paths, numbers and hashes."""
    raise NotImplementedError


def classify(error_text: str, command: str = "") -> Classification:
    """TOOL span `classify_failure`. Jev first, Claude as fallback. Returns four probabilities."""
    raise NotImplementedError
