"""Share format v1 (docs/share-format.md). One run folder becomes one URL-safe code."""

from __future__ import annotations

import base64
import gzip
import json
import os
from pathlib import Path

from firstrun import state as state_io
from firstrun.models import RunState, Runbook
from firstrun.redact import redact

DEFAULT_BASE = "https://1run.netlify.app/run.html"
ERROR_TAIL_MAX = 600
DIFF_MAX = 4000
PR_BODY_MAX = 3000


def _cap(text: str, limit: int) -> str:
    return text if len(text) <= limit else text[:limit]


def _scrub(value):
    """Redact every string in a JSON-like value once more."""
    if isinstance(value, str):
        return redact(value)
    if isinstance(value, list):
        return [_scrub(v) for v in value]
    if isinstance(value, dict):
        return {k: _scrub(v) for k, v in value.items()}
    return value


def _read(path: Path) -> str:
    try:
        return path.read_text(encoding="utf-8")
    except OSError:
        return ""


def _is_fixture(source: str, title: str) -> bool:
    return "FIXTURE" in source.upper() or "FIXTURE" in title.upper() or "web.archive.org" in source.lower()


def _steps(state: RunState, runbook: Runbook) -> list[dict]:
    out = []
    for step in runbook.steps:
        results = [r for r in state.results if r.step_id == step.id]
        failed = [r for r in results if not r.passed]
        status = state.step_status.get(step.id)
        status = status.value if status else ("skipped" if step.skipped_out_of_scope else "pending")
        if status == "recovering" or status == "running":
            status = "pending"
        last = results[-1] if results else None
        tail = ""
        if failed:
            tail = redact(failed[-1].stderr + failed[-1].stdout)[-ERROR_TAIL_MAX:]
        out.append({
            "id": step.id,
            "intent": step.intent,
            "command": step.command,
            "status": status,
            "attempts": max(state.attempts.get(step.id, 0), len(results)),
            "exit_code": last.exit_code if last else None,
            "duration_s": round(last.duration_s, 1) if last else None,
            "skipped": step.skipped_out_of_scope,
            "skip_reason": step.skip_reason,
            "error_tail": tail,
        })
    return out


def build_payload(run_dir) -> dict:
    run_dir = Path(run_dir)
    state = RunState.model_validate_json(_read(run_dir / "state.json"))
    runbook = Runbook.model_validate_json(_read(run_dir / "runbook.json"))
    steps = _steps(state, runbook)
    counted = [s for s in steps if not s["skipped"]]
    trace = _read(run_dir / "trace_id").strip()
    payload = {
        "v": 1,
        "run_id": state.run_id,
        "target": state_io.target_name(state.source_url or runbook.source_url),
        "title": runbook.title,
        "source_url": state.source_url or runbook.source_url,
        "status": state.status.value,
        "fixture": _is_fixture(state.source_url or runbook.source_url, runbook.title),
        "tags": list(state.tags),
        "started_at": state.started_at,
        "finished_at": state.finished_at,
        "time_to_first_success_s": state.time_to_first_success_s,
        "tool_calls": state.usage.tool_calls,
        "cost_usd": round(state.usage.cost_usd, 2),
        "image": runbook.image,
        "steps": steps,
        "classifications": {
            str(sid): {"source": c.source,
                       "probabilities": {k.value: round(v, 4) for k, v in c.probabilities.items()}}
            for sid, c in state.classifications.items()
        },
        "patches": [
            {"step_id": p.step_id, "old_command": p.old_command, "new_command": p.new_command,
             "failure_class": p.failure_class.value, "reason": p.reason, "source": p.source}
            for p in state.patches
        ],
        "gave_up": [
            {"step_id": g.step_id, "reason": g.reason,
             "failure_class": g.failure_class.value if g.failure_class else None}
            for g in state.gave_up
        ],
        "verify": {
            "status": state.status.value,
            "steps_passed": sum(1 for s in counted if s["status"] == "passed"),
            "steps_total": len(counted),
        },
        "diff": _cap(_read(run_dir / "patch.diff"), DIFF_MAX),
        "pr_body": _cap(_read(run_dir / "pr_body.md"), PR_BODY_MAX),
        "trace_id": trace,
    }
    payload = _scrub(payload)
    for step in payload["steps"]:
        step["error_tail"] = step["error_tail"][-ERROR_TAIL_MAX:]
    payload["diff"] = payload["diff"][:DIFF_MAX]
    payload["pr_body"] = payload["pr_body"][:PR_BODY_MAX]
    return payload


def encode(payload: dict) -> str:
    raw = json.dumps(payload, separators=(",", ":"), ensure_ascii=False).encode("utf-8")
    return base64.urlsafe_b64encode(gzip.compress(raw, 9)).decode("ascii").rstrip("=")


def decode(code: str) -> dict:
    code = code.strip()
    raw = base64.urlsafe_b64decode(code + "=" * (-len(code) % 4))
    return json.loads(gzip.decompress(raw).decode("utf-8"))


def share_link(code: str) -> str:
    return f"{os.environ.get('FIRSTRUN_SHARE_BASE') or DEFAULT_BASE}#r={code}"


def link_for_run(run_dir) -> tuple[str, str]:
    """(link, code) for a run folder."""
    code = encode(build_payload(run_dir))
    return share_link(code), code
