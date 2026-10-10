"""Track T1. Reads a docs page and returns a validated runbook."""

from __future__ import annotations

import html
import json
import os
import re
import shutil
import subprocess
from pathlib import Path
from typing import Callable
from urllib.parse import unquote, urlparse
from urllib.request import url2pathname

import neatlogs
from pydantic import ValidationError

from firstrun.models import Expected, Runbook, Step

KEYS_SCRIPT = r"D:\Atharva\NOTES\SCRIPTS\keys\keys.py"
MAX_STEPS = 10
SHELL_TAGS = {"bash", "sh", "shell", "console", "zsh", "terminal", "cmd"}

SYSTEM_PROMPT = """You turn a developer tool's quickstart page into a runbook of shell steps.
Reply with one JSON object only, no prose:
{"title": str, "image": str, "steps": [{"id": int, "intent": str, "command": str,
 "files": [{"path": str, "content": str}],
 "expected": {"exit_code": 0, "output_contains": str|null, "file_exists": str|null},
 "source_line": str}]}
Rules:
- Copy each command EXACTLY as the docs show it. Never fix, update or improve a command.
- source_line is the exact docs line the command came from.
- files holds any file the docs tell the reader to create, with its exact content.
  Put the command that runs it in a later step.
- image is python:3.11-slim unless the quickstart clearly needs another (for example node:22-slim).
- Ignore web archive banners and site chrome (Wayback toolbar, captures, cookie text). Keep only the docs.
- A step that needs a paid account, a video, a screenshot, a browser, a GUI or a sign-up stays in the list
  with "skipped_out_of_scope": true and "skip_reason": one plain sentence. Skip pure explanation.
- Add an env var export step only if the docs show it.
- Number ids from 1. Each step runs in a fresh shell in the same container."""


class PlanError(Exception):
    """The run cannot start. `reason` is the plain sentence the report prints."""

    def __init__(self, reason: str):
        super().__init__(reason)
        self.reason = reason


class DocsUnreachable(PlanError):
    pass


# --- Windows paths and archive banners ----------------------------------------

_DRIVE_PATH = re.compile(r"(?<![\w/])[A-Za-z]:\\[^\s\"'|&;<>]*")
_DOT_PATH = re.compile(r"(?<![\w/.])\.{1,2}\\[^\s\"'|&;<>]*")


def posix_paths(command: str) -> str:
    r"""Rewrite Windows paths to Linux paths. Only paths change: C:\a\b becomes /work/a/b, .\a becomes ./a."""
    def drive(m: re.Match) -> str:
        return "/work/" + m.group(0)[3:].replace("\\", "/")

    def dot(m: re.Match) -> str:
        return m.group(0).replace("\\", "/")

    return _DOT_PATH.sub(dot, _DRIVE_PATH.sub(drive, command))


_WAYBACK_LINE = re.compile(
    r"(?i)wayback machine|\bcaptures?\b.*\bsee a list|^\s*\[?\d+ captures|"
    r"share via my web archive|close the toolbar|get some help using|^\s*(?:success|fail)\s*$|"
    r"^\|\s*(?:jul|aug|sep|---|\d{4}).*\|\s*$|^\s*\d{1,2} \w{3} \d{4} - \d{1,2} \w{3} \d{4}\s*$"
)


def strip_archive_banner(markdown: str) -> str:
    """Drop Wayback toolbar lines before the docs reach the planner. Code fences are never touched."""
    out, in_fence = [], False
    for line in markdown.splitlines():
        if line.lstrip().startswith(("```", "~~~")):
            in_fence = not in_fence
        if not in_fence and _WAYBACK_LINE.search(line):
            continue
        out.append(line)
    return "\n".join(out)


# --- docs reading ---------------------------------------------------------


def _strip_html(text: str) -> str:
    text = re.sub(r"(?is)<(script|style|noscript)[^>]*>.*?</\1>", " ", text)
    text = re.sub(r"(?i)<br\s*/?>|</(p|div|li|h[1-6]|pre|tr)>", "\n", text)
    text = re.sub(r"(?s)<[^>]+>", "", text)
    text = html.unescape(text)
    return re.sub(r"\n\s*\n+", "\n\n", text).strip()


def _run_firecrawl(exe: str, url: str) -> subprocess.CompletedProcess:
    return subprocess.run(
        [exe, "scrape", url, "--format", "markdown"],
        capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=120,
    )


def _firecrawl_scrape(url: str) -> str:
    exe = shutil.which("firecrawl") or shutil.which("firecrawl.cmd")
    if not exe:
        raise RuntimeError("firecrawl CLI not found")
    proc = _run_firecrawl(exe, url)
    if "Insufficient credits" in (proc.stdout + proc.stderr) and Path(KEYS_SCRIPT).exists():
        subprocess.run(["python", KEYS_SCRIPT, "activate"], capture_output=True, timeout=120)
        proc = _run_firecrawl(exe, url)
    if proc.returncode != 0 or not proc.stdout.strip():
        raise RuntimeError(f"firecrawl failed: {(proc.stderr or proc.stdout).strip()[:200]}")
    return proc.stdout


def _local_path(url: str) -> Path | None:
    if url.startswith("file://"):
        parsed = urlparse(url)
        return Path(url2pathname(unquote(parsed.netloc + parsed.path)))
    if not re.match(r"https?://", url):
        return Path(url)
    return None


@neatlogs.span(kind="TOOL", name="read_docs")
def read_docs(url: str) -> str:
    """TOOL span `read_docs`. Firecrawl scrape to markdown. A local path or file:// URL reads the file."""
    path = _local_path(url)
    if path is not None:
        return path.read_text(encoding="utf-8")
    try:
        return _firecrawl_scrape(url)
    except Exception as exc:  # fall back to a plain GET
        import httpx

        neatlogs.log("firecrawl failed, using httpx: {err}", err=str(exc))
        try:
            resp = httpx.get(url, follow_redirects=True, timeout=30)
        except httpx.HTTPError as http_exc:
            raise DocsUnreachable(f"docs unreachable: {url} ({str(exc)[:120]}; {http_exc.__class__.__name__})") from http_exc
        if resp.status_code in (401, 403, 404, 410) or resp.status_code >= 500:
            neatlogs.log("docs unreachable: http {code}", level="error", code=resp.status_code, firecrawl_error=str(exc)[:200])
            raise DocsUnreachable(f"docs unreachable: HTTP {resp.status_code} for {url} (firecrawl: {str(exc)[:120]})")
        return _strip_html(resp.text)


# --- model call -----------------------------------------------------------


# Usage of the planner's model calls since the last reset. The CLI adds it to the run's usage.
LAST_USAGE: dict = {}


def ask_claude(prompt: str, system: str) -> tuple[str, dict]:
    """One Claude Agent SDK turn, no tools. Returns (text, usage). Runs outside the repo."""
    from firstrun import llm

    text, usage = llm.ask(prompt, system)
    for key, value in usage.items():
        LAST_USAGE[key] = LAST_USAGE.get(key, 0) + value
    return text, usage


def _extract_json(text: str) -> dict:
    m = re.search(r"```(?:json)?\s*(\{.*\})\s*```", text, re.S)
    if m:
        text = m.group(1)
    else:
        start, end = text.find("{"), text.rfind("}")
        if start != -1 and end > start:
            text = text[start : end + 1]
    return json.loads(text)


def _build(data: dict, markdown: str, source_url: str) -> Runbook:
    data["source_url"] = source_url
    data["docs_markdown"] = markdown
    data.setdefault("image", "python:3.11-slim")
    runbook = Runbook.model_validate(data)
    for step in runbook.steps:
        step.command = posix_paths(step.command)
    return runbook


@neatlogs.span(kind="AGENT", name="planner")
def plan_from_markdown(
    markdown: str, source_url: str, llm: Callable[[str], str] | None = None
) -> Runbook:
    """AGENT span `planner`. Claude turns the markdown into a Runbook. Commands are copied exactly."""
    ask = llm or (lambda p: ask_claude(p, SYSTEM_PROMPT)[0])
    prompt = f"Source URL: {source_url}\n\nQuickstart page (markdown):\n\n{strip_archive_banner(markdown)}"
    error = ""
    for _ in range(2):
        text = ask(prompt if not error else f"{prompt}\n\nYour last reply was invalid: {error}\nReturn corrected JSON only.")
        try:
            return _build(_extract_json(text), markdown, source_url)
        except (ValueError, ValidationError) as exc:  # JSONDecodeError is a ValueError
            error = str(exc)[:800]
    raise ValueError(f"planner output invalid after retry: {error}")


# --- no-model planner -----------------------------------------------------

_FENCE = re.compile(r"^[ \t]*(```|~~~)[ \t]*([\w+-]*)[^\n]*\n(.*?)^[ \t]*\1[ \t]*$", re.S | re.M)


def heuristic_plan(markdown: str, source_url: str) -> Runbook:
    """No model. One step per command line in shell-tagged fenced blocks."""
    steps: list[Step] = []
    for m in _FENCE.finditer(strip_archive_banner(markdown)):
        if m.group(2).lower() not in SHELL_TAGS:
            continue
        lines = m.group(3).splitlines()
        i = 0
        while i < len(lines):
            raw = lines[i].rstrip()
            i += 1
            line = raw.strip()
            if not line or line.startswith("#"):
                continue
            if line.startswith("$ ") or line.startswith("> "):
                line = line[2:].strip()
            elif line.startswith("$"):
                line = line[1:].strip()
            # join backslash continuations
            while line.endswith("\\") and i < len(lines):
                line = line[:-1].rstrip() + " " + lines[i].strip()
                i += 1
            if not line:
                continue
            steps.append(
                Step(id=len(steps) + 1, intent=f"Run: {line[:60]}", command=posix_paths(line),
                     expected=Expected(), source_line=raw.strip())
            )
    title = next((ln.lstrip("# ").strip() for ln in markdown.splitlines() if ln.startswith("# ")), "")
    return Runbook(source_url=source_url, title=title, docs_markdown=markdown, steps=steps)


def check_scope(runbook: Runbook) -> Runbook:
    """Raise PlanError when the runbook has nothing to run or is too long."""
    if len(runbook.steps) > MAX_STEPS:
        raise PlanError(f"out of scope: more than {MAX_STEPS} steps ({len(runbook.steps)} found)")
    if not any(not s.skipped_out_of_scope for s in runbook.steps):
        raise PlanError("no runnable steps")
    return runbook


def plan(url: str, llm: Callable[[str], str] | None = None) -> Runbook:
    """read_docs then plan_from_markdown. Raises PlanError when the run cannot start.

    The heuristic planner runs only offline. A model failure stops the run with "planner failed".
    """
    markdown = read_docs(url)
    if os.environ.get("FIRSTRUN_OFFLINE") == "1" and llm is None:
        return check_scope(heuristic_plan(markdown, url))
    try:
        return check_scope(plan_from_markdown(markdown, url, llm))
    except PlanError:
        raise
    except Exception as exc:
        from firstrun.llm import ModelAuthError

        neatlogs.log("planner failed: {err}", level="error", err=str(exc)[:300])
        if isinstance(exc, ModelAuthError):
            raise PlanError(str(exc)) from exc
        raise PlanError(f"planner failed: {str(exc)[:300]}") from exc
