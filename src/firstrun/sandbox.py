"""Track T2. One fresh Docker container per run, through `wsl -d Ubuntu-22.04 docker`."""

from __future__ import annotations

import os
import secrets
import shlex
import subprocess
import time

from firstrun import config
from firstrun.models import FileSpec, StepResult

OUTPUT_CAP = 20 * 1024  # keep the last 20 KB of each stream
WORKDIR = "/work"

# Runs inside the container. Reads the step script from stdin, then runs it in its own
# bash with stdin closed, so a command that reads stdin cannot eat the script.
_RUNNER = """#!/bin/bash
cat > /tmp/.fr_step.sh
exec bash /tmp/.fr_step.sh < /dev/null
"""

# Restore env and cwd, run the command, save env and cwd, keep the exit code.
_PREFIX = """if [ -f /tmp/.fr_env ]; then . /tmp/.fr_env; fi
cd "$(cat /tmp/.fr_cwd 2>/dev/null || echo /work)" 2>/dev/null || cd /work
trap '__fr_rc=$?; pwd > /tmp/.fr_cwd; export -p > /tmp/.fr_env; exit $__fr_rc' EXIT
"""

# Kill every process except PID 1 (sleep infinity) and this shell.
_KILL_ALL = (
    "for d in /proc/[0-9]*; do p=${d#/proc/}; "
    '[ "$p" -gt 1 ] && [ "$p" != "$$" ] && kill -9 "$p" 2>/dev/null; done; true'
)


def _tail(data: bytes, cap: int = OUTPUT_CAP) -> str:
    if len(data) > cap:
        data = data[-cap:]
    return data.decode("utf-8", errors="replace")


def _allowlist_env() -> dict[str, str]:
    """KEY=VALUE lines from config.SECRETS_ALLOWLIST. Missing file means no secrets."""
    from firstrun import config

    out: dict[str, str] = {}
    try:
        text = config.SECRETS_ALLOWLIST.read_text(encoding="utf-8")
    except OSError:
        return out
    for line in text.splitlines():
        line = line.strip()
        if line and not line.startswith("#") and "=" in line:
            key, value = line.split("=", 1)
            out[key.strip()] = value.strip()
    return out


class Container:
    """A running container. Use as a context manager: the container is removed on exit."""

    def __init__(
        self,
        image: str = "python:3.11-slim",
        name: str | None = None,
        env: dict[str, str] | None = None,
        run: str | None = None,
    ):
        self.image = image
        # Default env: the test keys from the secrets allowlist, nothing else from the host.
        self.env = dict(env) if env is not None else _allowlist_env()
        label = run or "run"
        self.name = name or f"firstrun-{label}-{os.getpid()}-{secrets.token_hex(3)}"
        self.started = False

    # --- docker plumbing --------------------------------------------------

    def _docker(self, args: list[str], input_bytes: bytes | None = None, timeout: float | None = 120):
        return subprocess.run(
            [*config.DOCKER_CMD, *args],
            input=input_bytes, capture_output=True, timeout=timeout,
        )

    def _sh(self, script: str, timeout: float | None = 60) -> subprocess.CompletedProcess:
        """Run a small bash script in the container through stdin."""
        return self._docker(["exec", "-i", self.name, "bash", "-s"], script.encode("utf-8"), timeout)

    def __enter__(self) -> "Container":
        probe = self._docker(["image", "inspect", self.image])
        if probe.returncode != 0:
            pulled = self._docker(["pull", self.image], timeout=900)
            if pulled.returncode != 0:
                raise RuntimeError(f"docker pull {self.image} failed: {_tail(pulled.stderr, 500)}")
        run = self._docker(["run", "-d", "--name", self.name, "--network", "bridge", self.image, "sleep", "infinity"])
        if run.returncode != 0:
            raise RuntimeError(f"docker run failed: {_tail(run.stderr, 500)}")
        self.started = True
        try:
            # Env goes in through stdin, so secrets never show up on a command line.
            env_lines = "".join(f"export {k}={shlex.quote(v)}\n" for k, v in self.env.items())
            setup = (
                f"mkdir -p {WORKDIR}\n"
                f"cat > /usr/local/bin/fr_run <<'FR_RUNNER_EOF'\n{_RUNNER}FR_RUNNER_EOF\n"
                "chmod +x /usr/local/bin/fr_run\n"
                f"cat > /tmp/.fr_env <<'FR_ENV_EOF'\n{env_lines}FR_ENV_EOF\n"
                f"echo {WORKDIR} > /tmp/.fr_cwd\n"
            )
            done = self._sh(setup)
            if done.returncode != 0:
                raise RuntimeError(f"container setup failed: {_tail(done.stderr, 500)}")
        except BaseException:
            self.__exit__()
            raise
        return self

    def __exit__(self, *exc) -> None:
        if not self.started:
            return
        self.started = False
        try:
            self._docker(["rm", "-f", self.name], timeout=60)
        except Exception:
            pass

    # --- public API -------------------------------------------------------

    def write_files(self, files: list[FileSpec]) -> None:
        for f in files:
            mark = f"FR_EOF_{secrets.token_hex(4)}"
            path = shlex.quote(f.path)
            content = f.content if f.content.endswith("\n") or not f.content else f.content + "\n"
            script = (
                f"{_PREFIX}"
                f'mkdir -p "$(dirname {path})"\n'
                f"cat > {path} <<'{mark}'\n{content}{mark}\n"
            )
            done = self._sh(script)
            if done.returncode != 0:
                raise RuntimeError(f"write_files {f.path} failed: {_tail(done.stderr, 500)}")

    def exec(self, command: str, timeout_s: int = 300) -> StepResult:
        """Run one shell command in the container workdir. Never raises on a non-zero exit."""
        script = _PREFIX + command + "\n"
        start = time.monotonic()
        proc = subprocess.Popen(
            [*config.DOCKER_CMD, "exec", "-i", self.name, "fr_run"],
            stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
        )
        timed_out = False
        try:
            out, err = proc.communicate(script.encode("utf-8"), timeout=timeout_s)
            code = proc.returncode
        except subprocess.TimeoutExpired:
            timed_out = True
            proc.kill()
            try:
                self._sh(_KILL_ALL, timeout=30)
            except Exception:
                pass
            out, err = proc.communicate()
            code = 124
        return StepResult(
            step_id=0,
            command=command,
            exit_code=code,
            stdout=_tail(out or b""),
            stderr=_tail(err or b""),
            duration_s=round(time.monotonic() - start, 3),
            timed_out=timed_out,
        )
