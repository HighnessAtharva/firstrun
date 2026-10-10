"""Track T4. Classify, search, patch, retry. At most 3 attempts per step."""

from __future__ import annotations

import re
import sys
from typing import Callable

import httpx
import neatlogs

from firstrun import budget as budget_mod
from firstrun import classify as classify_mod
from firstrun import config, llm, precedents
from firstrun.budget import BudgetExceeded
from firstrun.models import (
    Budget,
    Classification,
    FailureClass,
    GaveUp,
    Patch,
    RunState,
    Step,
    StepResult,
)

CONFIDENT = 0.7        # below this, ask the human once
STORE_CONFIDENT = 0.9  # at or above this, a model answer is stored as a precedent

_LETTERS = {"d": FailureClass.DOCS_BUG, "e": FailureClass.ENVIRONMENT,
            "p": FailureClass.PRODUCT_BUG, "s": FailureClass.NEEDS_SECRET}

Asker = Callable[[str], str]


def _error_line(error_text: str) -> str:
    lines = [ln.strip() for ln in error_text.splitlines() if ln.strip()]
    return (lines[-1] if lines else "no output")[:200]


def _terminal_asker(question: str) -> str | None:
    if not sys.stdin or not sys.stdin.isatty():
        return None
    return input(question + " ")


def _parse_answer(answer: str | None) -> FailureClass | None:
    if not answer:
        return None
    a = answer.strip().lower()
    for cls in FailureClass:
        if a == cls.value or a == cls.value.replace("_", " "):
            return cls
    return _LETTERS.get(a[:1]) if len(a) == 1 else None


def _resolve(error_text: str, command: str, asker: Asker | None, step_id: int | None) -> Classification:
    sig = classify_mod.signature(error_text)
    known = precedents.lookup(sig)
    if known is not None:
        neatlogs.log("precedent reused", signature=sig, failure_class=known.value)
        return Classification(probabilities={c: (1.0 if c == known else 0.0) for c in FailureClass},
                              source="precedent")
    cls = classify_mod.classify(error_text, command)
    if cls.confidence >= CONFIDENT:
        if cls.confidence >= STORE_CONFIDENT:
            precedents.store(sig, cls.top, example=error_text)
        return cls
    where = f"Step {step_id}" if step_id is not None else "Step"
    question = (f"{where} failed: {_error_line(error_text)}. Is this a docs bug, an environment issue, "
                "a product bug, or a missing secret? [d/e/p/s]")
    ask = asker or _terminal_asker
    answer = _parse_answer(ask(question))
    if answer is None:
        neatlogs.log("no human answer, using the top class", level="warning",
                     failure_class=cls.top.value, confidence=cls.confidence)
        return cls
    precedents.store(sig, answer, example=error_text)
    return Classification(probabilities={c: (1.0 if c == answer else 0.0) for c in FailureClass},
                          source="human")


def resolve_class(error_text: str, command: str, asker: Asker | None = None,
                  step_id: int | None = None) -> tuple[FailureClass, str]:
    """Precedent first, then the classifier, then ask the human once if unsure."""
    cls = _resolve(error_text, command, asker, step_id)
    return cls.top, cls.source


# --- environment fixes -------------------------------------------------------

# (error pattern, apt packages). A small known table so most fixes need no model.
_ENV_FIXES: list[tuple[re.Pattern, str]] = [
    (re.compile(r"\bcurl: (?:command )?not found|curl: not found|\bcurl\b.*not found", re.I), "curl"),
    (re.compile(r"\bgit: (?:command )?not found|\bgit\b.*not found|No such file or directory: 'git'", re.I), "git"),
    (re.compile(r"\bwget: (?:command )?not found|\bwget\b.*not found", re.I), "wget"),
    (re.compile(r"\b(?:gcc|cc|g\+\+|make): (?:command )?not found|command 'gcc' failed|unable to execute 'gcc'|"
                r"failed to build wheel|python\.h: no such file", re.I), "build-essential"),
    (re.compile(r"\b(?:node|npm|npx): (?:command )?not found", re.I), "nodejs npm"),
]


def _env_packages(error_text: str) -> str | None:
    for pattern, pkgs in _ENV_FIXES:
        if pattern.search(error_text):
            return pkgs
    return None


# --- docs bug hints ----------------------------------------------------------

_PIP_MISSING = re.compile(r"No matching distribution found for ([A-Za-z0-9_.\-]+)(?:\[[^\]]*\])?\s*(?:==|>=|<=|~=|>|<)?\s*([\w.]*)")


def _pypi_hint(error_text: str) -> str:
    """Cheap first hint with no model: valid versions of the package pip could not find."""
    m = _PIP_MISSING.search(error_text)
    if not m:
        return ""
    name = m.group(1)
    try:
        r = httpx.get(f"https://pypi.org/pypi/{name}/json", timeout=10)
        if r.status_code == 404:
            return f"PyPI hint: no package named {name} exists on PyPI. It may have been renamed."
        r.raise_for_status()
        releases = [v for v, files in r.json().get("releases", {}).items() if files and not all(f.get("yanked") for f in files)]
        try:
            from packaging.version import Version
            releases.sort(key=Version)
        except Exception:
            pass
        latest = r.json().get("info", {}).get("version", "")
        return f"PyPI hint: {name} has these versions (newest last): {', '.join(releases[-15:])}. Latest is {latest}."
    except Exception:
        return ""


def _read_allowlist() -> dict[str, str]:
    """KEY=VALUE lines. Values are never logged or returned to callers outside this module."""
    out: dict[str, str] = {}
    try:
        for line in config.SECRETS_ALLOWLIST.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if line and not line.startswith("#") and "=" in line:
                k, v = line.split("=", 1)
                out[k.strip()] = v.strip()
    except OSError:
        pass
    return out


def _add_usage(state: RunState, usage: dict) -> None:
    state.usage.tool_calls += int(usage.get("tool_calls", 0))
    state.usage.input_tokens += int(usage.get("input_tokens", 0))
    state.usage.output_tokens += int(usage.get("output_tokens", 0))
    state.usage.cost_usd += float(usage.get("cost_usd", 0.0))


def _error_text(result: StepResult) -> str:
    text = (result.stderr or "") + ("\n" if result.stderr and result.stdout else "") + (result.stdout or "")
    if result.timed_out:
        text += "\n(command timed out)"
    return text[-3000:]


def _ask_fix(prompt: str, tools: tuple[str, ...], max_turns: int, state: RunState, bud: Budget,
             step: Step, old_command: str, cls: FailureClass, tried: list[str]) -> Patch | GaveUp:
    """One budgeted Claude call that must return {new_command, reason, source}."""
    try:
        budget_mod.check(state, bud, step.id)
    except BudgetExceeded as exc:
        return GaveUp(step_id=step.id, reason=str(exc), failure_class=cls)
    try:
        data, usage = llm.ask_json(prompt, system="You fix failing shell commands from developer quickstart guides.",
                                   tools=tools, max_turns=max_turns)
    except Exception as exc:  # noqa: BLE001
        return GaveUp(step_id=step.id, reason=f"model call failed: {type(exc).__name__}", failure_class=cls)
    _add_usage(state, usage)
    new = str(data.get("new_command") or "").strip()
    if not new or new == old_command.strip() or new in tried:
        return GaveUp(step_id=step.id, reason="no new fix found: the model repeated an earlier command",
                      failure_class=cls)
    return Patch(step_id=step.id, old_command=old_command, new_command=new,
                 reason=str(data.get("reason") or "")[:300], failure_class=cls,
                 source=str(data.get("source") or ""))


def recover(step: Step, result: StepResult, state: RunState, docs_markdown: str = "",
            asker: Asker | None = None, budget: Budget | None = None) -> Patch | GaveUp:
    """AGENT span `recover.<id>`. Returns a Patch to retry with, or GaveUp."""
    bud = budget or Budget()
    with neatlogs.trace(f"recover.{step.id}", kind="AGENT"):
        return _recover(step, result, state, docs_markdown, asker, bud)


def _recover(step: Step, result: StepResult, state: RunState, docs_markdown: str,
             asker: Asker | None, bud: Budget) -> Patch | GaveUp:
    error_text = _error_text(result)
    old_command = result.command or step.command
    attempts = state.attempts.get(step.id, 0)
    neatlogs.log("retry {attempt} after {error}", level="warning",
                 attempt=max(attempts, 1), error=_error_line(error_text))
    try:
        budget_mod.check(state, bud, step.id)
    except BudgetExceeded as exc:
        return GaveUp(step_id=step.id, reason=str(exc))

    classify_mod.LAST_USAGE.clear()
    cls = _resolve(error_text, old_command, asker, step.id)
    if classify_mod.LAST_USAGE:  # the classifier fell back to Claude
        _add_usage(state, classify_mod.LAST_USAGE)
        classify_mod.LAST_USAGE.clear()
    state.classifications[step.id] = cls
    top = cls.top

    tried = [p.new_command for p in state.patches if p.step_id == step.id]

    if top == FailureClass.PRODUCT_BUG:
        return GaveUp(step_id=step.id, reason=f"product bug: {_error_line(error_text)}", failure_class=top)

    if top == FailureClass.NEEDS_SECRET:
        allow = _read_allowlist()
        haystack = f"{error_text}\n{old_command}\n{docs_markdown}"
        name = next((k for k in allow if re.search(rf"\b{re.escape(k)}\b", haystack)), None)
        if name is None:
            return GaveUp(step_id=step.id, reason="needs a secret that is not in the allowlist: "
                          + _error_line(error_text), failure_class=top)
        # The executor injects the value into the container. The name goes in `source`.
        return Patch(step_id=step.id, old_command=old_command, new_command=old_command,
                     reason="secret supplied from allowlist", failure_class=top, source=name)

    if top == FailureClass.ENVIRONMENT:
        pkgs = _env_packages(error_text)
        if pkgs:
            new = f"apt-get update -qq && apt-get install -y -qq {pkgs} && {old_command}"
            if new not in tried:
                return Patch(step_id=step.id, old_command=old_command, new_command=new,
                             reason=f"the base image lacks {pkgs}; install it first", failure_class=top,
                             source="apt")
        prompt = (f"A command failed in a clean python:3.11-slim container because of the environment.\n"
                  f"Command: {old_command}\nError tail:\n{error_text}\n"
                  f"Earlier fixes that did not work: {tried or 'none'}\n"
                  'Return JSON {"new_command": "...", "reason": "...", "source": "..."}. '
                  "new_command must run the original command after any container fix, as one shell line.")
        return _ask_fix(prompt, (), 1, state, bud, step, old_command, top, tried)

    # docs_bug
    hint = _pypi_hint(error_text)
    prompt = (f"A step from a developer quickstart failed in a clean Docker container (python:3.11-slim).\n"
              f"Step intent: {step.intent}\nCommand: {old_command}\nError tail:\n{error_text}\n"
              f"{hint}\n"
              f"Earlier patches for this step that also failed: {tried or 'none'}\n"
              f"Docs excerpt:\n{docs_markdown[:3000]}\n\n"
              "Find the current, correct command with WebSearch and WebFetch. Prefer the tool's own docs, "
              "its registry page or its issue tracker. "
              'Return JSON {"new_command": "...", "reason": "...", "source": "<url you used>"}.')
    return _ask_fix(prompt, ("WebSearch", "WebFetch"), 6, state, bud, step, old_command, top, tried)
