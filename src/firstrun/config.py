"""One place for every setting. No other file names a model."""

from __future__ import annotations

import os
from pathlib import Path

MODEL = "claude-sonnet-5-5"
EFFORT = "medium"

# Sonnet 5.5 list price per million tokens, used for "list price, not billed" cost.
PRICE_INPUT_PER_MTOK = 2.00
PRICE_OUTPUT_PER_MTOK = 10.00
PRICE_CACHE_READ_PER_MTOK = 0.20

ENV_FILE = Path(os.environ.get("FIRSTRUN_ENV_FILE", r"D:\Atharva\NOTES\.env"))
RUNS_DIR = Path(os.environ.get("FIRSTRUN_RUNS_DIR", "runs"))
PRECEDENTS_FILE = Path(os.environ.get("FIRSTRUN_PRECEDENTS", "precedents.json"))
SECRETS_ALLOWLIST = Path(os.environ.get("FIRSTRUN_SECRETS", "secrets.allowlist"))

DOCKER_CMD = os.environ.get("FIRSTRUN_DOCKER", "wsl -d Ubuntu-22.04 docker").split()
DEFAULT_IMAGE = "python:3.11-slim"

KEYS = ("NEATLOGS_API_KEY", "CLAUDE_CODE_OAUTH_TOKEN", "TYPESAFE_API_KEY", "FIRECRAWL_API_KEY_1")


def load_env(path: Path | None = None) -> None:
    """Load KEY=VALUE lines into os.environ at run time. Never overwrites a set value."""
    path = path or ENV_FILE
    if not path.exists():
        return
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        key = key.strip()
        value = value.strip().strip('"').strip("'")
        if key and value and key not in os.environ:
            os.environ[key] = value
    if "FIRECRAWL_API_KEY" not in os.environ and os.environ.get("FIRECRAWL_API_KEY_1"):
        os.environ["FIRECRAWL_API_KEY"] = os.environ["FIRECRAWL_API_KEY_1"]
    # The Agent SDK must use the subscription token, never an API key.
    os.environ.pop("ANTHROPIC_API_KEY", None)
