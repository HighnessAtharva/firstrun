"""Track T2. One fresh Docker container per run, through `wsl -d Ubuntu-22.04 docker`."""

from __future__ import annotations

from firstrun.models import FileSpec, StepResult


class Container:
    """A running container. Use as a context manager: the container is removed on exit."""

    def __init__(self, image: str = "python:3.11-slim", name: str | None = None, env: dict[str, str] | None = None):
        raise NotImplementedError

    def __enter__(self) -> "Container":
        raise NotImplementedError

    def __exit__(self, *exc) -> None:
        raise NotImplementedError

    def write_files(self, files: list[FileSpec]) -> None:
        raise NotImplementedError

    def exec(self, command: str, timeout_s: int = 300) -> StepResult:
        """Run one shell command in the container workdir. Never raises on a non-zero exit."""
        raise NotImplementedError
