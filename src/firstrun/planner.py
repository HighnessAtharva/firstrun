"""Track T1. Reads a docs page and returns a validated runbook."""

from __future__ import annotations

import asyncio
import html
import json
import os
import re
import shutil
import subprocess
import tempfile
from pathlib import Path
from typing import Callable
from urllib.parse import unquote, urlparse
from urllib.request import url2pathname

import neatlogs
from pydantic import ValidationError

from firstrun.config import EFFORT, MODEL, load_env
from firstrun.models import Expected, Runbook, Step

KEYS_SCRIPT = r"D:\Atharva\NOTES\SCRIPTS\keys\keys.py"
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
- Skip steps that need a browser, a GUI or a sign-up. Skip pure explanation.
- Add an env var export step only if the docs show it.
- Number ids from 1. Each step runs in a fresh shell in the same container."""


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


@neatlogs.span(kind="TOOL", name="read_docs", tool_name="firecrawl")
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
        resp = httpx.get(url, follow_redirects=True, timeout=30)
        resp.raise_for_status()
        return _strip_html(resp.text)


# --- model call -----------------------------------------------------------


def ask_claude(prompt: str, system: str) -> tuple[str, dict]:
    """One Claude Agent SDK turn, no tools. Returns (text, usage). Runs outside the repo."""
    load_env()
    import claude_agent_sdk

    sdk = neatlogs.wrap(claude_agent_sdk)
    # Blank these so the CLI does not refuse to nest inside a Claude Code session.
    env = {"CLAUDECODE": "", "CLAUDE_CODE_ENTRYPOINT": ""}
    workdir = tempfile.mkdtemp(prefix="firstrun-llm-")

    async def _go() -> tuple[str, dict]:
        options = claude_agent_sdk.ClaudeAgentOptions(
            model=MODEL, effort=EFFORT, allowed_tools=[], max_turns=1,
            setting_sources=[], cwd=workdir, system_prompt=system, env=env,
        )
        text, usage = "", {}
        async for msg in sdk.query(prompt=prompt, options=options):
            if isinstance(msg, claude_agent_sdk.ResultMessage):
                if getattr(msg, "result", None):
                    text = msg.result
                raw = getattr(msg, "usage", None) or {}
                usage = {
                    "input_tokens": int(raw.get("input_tokens", 0) or 0)
                    + int(raw.get("cache_read_input_tokens", 0) or 0)
                    + int(raw.get("cache_creation_input_tokens", 0) or 0),
                    "output_tokens": int(raw.get("output_tokens", 0) or 0),
                }
        return text, usage

    try:
        return asyncio.run(_go())
    finally:
        shutil.rmtree(workdir, ignore_errors=True)


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
    return Runbook.model_validate(data)


@neatlogs.span(kind="AGENT", name="planner")
def plan_from_markdown(
    markdown: str, source_url: str, llm: Callable[[str], str] | None = None
) -> Runbook:
    """AGENT span `planner`. Claude turns the markdown into a Runbook. Commands are copied exactly."""
    ask = llm or (lambda p: ask_claude(p, SYSTEM_PROMPT)[0])
    prompt = f"Source URL: {source_url}\n\nQuickstart page (markdown):\n\n{markdown}"
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
    for m in _FENCE.finditer(markdown):
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
                Step(id=len(steps) + 1, intent=f"Run: {line[:60]}", command=line,
                     expected=Expected(), source_line=raw.strip())
            )
    title = next((ln.lstrip("# ").strip() for ln in markdown.splitlines() if ln.startswith("# ")), "")
    return Runbook(source_url=source_url, title=title, docs_markdown=markdown, steps=steps)


def plan(url: str, llm: Callable[[str], str] | None = None) -> Runbook:
    """read_docs then plan_from_markdown. Heuristic when offline or when the model call fails."""
    markdown = read_docs(url)
    if os.environ.get("FIRSTRUN_OFFLINE") == "1" and llm is None:
        return heuristic_plan(markdown, url)
    try:
        return plan_from_markdown(markdown, url, llm)
    except Exception as exc:
        neatlogs.log("planner failed, using heuristic: {err}", err=str(exc))
        return heuristic_plan(markdown, url)
