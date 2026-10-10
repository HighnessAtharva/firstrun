"""Track T4. The ask-once store, precedents.json, keyed by error signature."""

from __future__ import annotations

from firstrun.models import FailureClass


def lookup(signature: str) -> FailureClass | None:
    raise NotImplementedError


def store(signature: str, cls: FailureClass) -> None:
    raise NotImplementedError
