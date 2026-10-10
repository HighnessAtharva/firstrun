"""Track T4. Small sync helpers over the Claude Agent SDK. Wrapped by neatlogs."""

from __future__ import annotations

import asyncio
import json
import os
import re
import tempfile
import threading
from typing import Any, Sequence

import claude_agent_sdk
import neatlogs

from firstrun import config

# Wrapped once. Every query shows up in the neatlogs trace.
try:
    sdk = neatlogs.wrap(claude_agent_sdk)
except Exception:  # wrapping is best effort, the plain SDK still works
    sdk = claude_agent_sdk

# A cwd outside the repo, so Entire hooks and project settings never fire.
_WORKDIR = os.path.join(tempfile.gettempdir(), "firstrun-llm")


def _cost(input_tokens: int, output_tokens: int) -> float:
    return (input_tokens * config.PRICE_INPUT_PER_MTOK + output_tokens * config.PRICE_OUTPUT_PER_MTOK) / 1_000_000


def extract_json(text: str) -> dict:
    """Pull the first JSON object out of a reply, with or without a code fence."""
    text = text.strip()
    fence = re.search(r"```(?:json)?\s*(\{.*?\})\s*```", text, re.S)
    candidates = [fence.group(1)] if fence else []
    start = text.find("{")
    end = text.rfind("}")
    if start != -1 and end > start:
        candidates.append(text[start:end + 1])
    for c in candidates:
        try:
            value = json.loads(c)
        except json.JSONDecodeError:
            continue
        if isinstance(value, dict):
            return value
    raise ValueError("no JSON object in model reply")


async def _run(prompt: str, system: str, tools: Sequence[str], max_turns: int) -> tuple[str, dict]:
    config.load_env()
    os.makedirs(_WORKDIR, exist_ok=True)
    env = {k: v for k, v in os.environ.items() if k not in ("CLAUDECODE", "CLAUDE_CODE_ENTRYPOINT", "ANTHROPIC_API_KEY")}
    options = claude_agent_sdk.ClaudeAgentOptions(
        model=config.MODEL,
        effort=config.EFFORT,
        system_prompt=system,
        setting_sources=[],
        cwd=_WORKDIR,
        tools=list(tools),
        allowed_tools=list(tools),
        max_turns=max_turns,
        env=env,
    )
    text, tool_calls, usage = "", 0, {}
    async for msg in sdk.query(prompt=prompt, options=options):
        if isinstance(msg, claude_agent_sdk.AssistantMessage):
            for block in msg.content:
                if isinstance(block, claude_agent_sdk.ToolUseBlock):
                    tool_calls += 1
                elif isinstance(block, claude_agent_sdk.TextBlock):
                    text = block.text  # the last text block is the answer
        elif isinstance(msg, claude_agent_sdk.ResultMessage):
            usage = msg.usage or {}
            if msg.is_error and not text:
                raise RuntimeError(f"claude query failed: {msg.result or msg.subtype}")
            if msg.result:
                text = msg.result
    tin = int(usage.get("input_tokens", 0) or 0) + int(usage.get("cache_creation_input_tokens", 0) or 0) \
        + int(usage.get("cache_read_input_tokens", 0) or 0)
    tout = int(usage.get("output_tokens", 0) or 0)
    return text, {"input_tokens": tin, "output_tokens": tout, "tool_calls": tool_calls, "cost_usd": _cost(tin, tout)}


def _run_sync(prompt: str, system: str, tools: Sequence[str], max_turns: int) -> tuple[str, dict]:
    try:
        asyncio.get_running_loop()
    except RuntimeError:
        return asyncio.run(_run(prompt, system, tools, max_turns))
    # Already inside an event loop: run in a worker thread.
    box: dict[str, Any] = {}

    def work() -> None:
        try:
            box["out"] = asyncio.run(_run(prompt, system, tools, max_turns))
        except BaseException as exc:  # noqa: BLE001
            box["err"] = exc

    t = threading.Thread(target=work)
    t.start()
    t.join()
    if "err" in box:
        raise box["err"]
    return box["out"]


def ask(prompt: str, system: str = "", tools: Sequence[str] = (), max_turns: int = 1) -> tuple[str, dict]:
    """Plain text reply plus a usage dict."""
    return _run_sync(prompt, system, tools, max_turns)


def ask_json(prompt: str, system: str = "", tools: Sequence[str] = (), max_turns: int = 1) -> tuple[dict, dict]:
    """JSON reply plus a usage dict {input_tokens, output_tokens, tool_calls, cost_usd}."""
    system = (system + "\n\n" if system else "") + "Reply with one JSON object and nothing else."
    text, usage = _run_sync(prompt, system, tools, max_turns)
    return extract_json(text), usage
