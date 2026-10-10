"""Track T4. The ask-once store, precedents.json, keyed by error signature."""

from __future__ import annotations

import json
from datetime import datetime, timezone

from firstrun import config
from firstrun.models import FailureClass


def _read() -> dict:
    path = config.PRECEDENTS_FILE  # read at call time so tests can patch it
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    return data if isinstance(data, dict) else {}


def lookup(signature: str) -> FailureClass | None:
    entry = _read().get(signature)
    if not isinstance(entry, dict):
        return None
    try:
        return FailureClass(entry.get("class"))
    except ValueError:
        return None


def store(signature: str, cls: FailureClass, example: str = "") -> None:
    data = _read()
    data[signature] = {
        "class": FailureClass(cls).value,
        "stored_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "example": example[:200],
    }
    path = config.PRECEDENTS_FILE
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, indent=2), encoding="utf-8")
