"""neatlogs setup. Every FirstRun run is one trace."""

from __future__ import annotations

import os
import sys

import neatlogs

from firstrun.config import load_env

_ready = False


def init_tracing(tags: list[str] | None = None, *, disable_export: bool | None = None) -> None:
    """Start neatlogs once per process. Tests set FIRSTRUN_NO_EXPORT=1 to keep spans local."""
    global _ready
    if _ready:
        return
    load_env()
    if disable_export is None:
        disable_export = os.environ.get("FIRSTRUN_NO_EXPORT") == "1" or not os.environ.get("NEATLOGS_API_KEY")
    if not os.environ.get("NEATLOGS_API_KEY") and os.environ.get("FIRSTRUN_NO_EXPORT") != "1":
        print("warning: NEATLOGS_API_KEY is missing. The run works, but no trace is exported.", file=sys.stderr)
    neatlogs.init(
        api_key=os.environ.get("NEATLOGS_API_KEY"),
        workflow_name="firstrun",
        tags=tags or [],
        debug=os.environ.get("FIRSTRUN_DEBUG") == "1",
        capture_logs=True,
        disable_export=disable_export,
    )
    _ready = True


def close_tracing() -> None:
    neatlogs.flush()


@neatlogs.span(kind="WORKFLOW", name="firstrun.hello")
def hello(name: str = "firstrun") -> str:
    neatlogs.log("hello from {name}", name=name)
    return f"hello, {name}"


if __name__ == "__main__":
    init_tracing(tags=["hello"], disable_export=False)
    print(hello())
    neatlogs.flush()
    neatlogs.shutdown()
