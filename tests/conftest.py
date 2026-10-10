import os
from pathlib import Path

import pytest

os.environ.setdefault("FIRSTRUN_NO_EXPORT", "1")

from firstrun import config  # noqa: E402
from firstrun.models import Runbook  # noqa: E402

FIXTURES = Path(__file__).parent / "fixtures"


def pytest_collection_modifyitems(config, items):
    """Skip tests marked live unless FIRSTRUN_LIVE=1."""
    if os.environ.get("FIRSTRUN_LIVE") == "1":
        return
    skip = pytest.mark.skip(reason="live test: set FIRSTRUN_LIVE=1 to run")
    for item in items:
        if "live" in item.keywords:
            item.add_marker(skip)


def pytest_configure(config):
    config.addinivalue_line("markers", "live: needs network, Docker or a model")


@pytest.fixture
def fixtures_dir() -> Path:
    return FIXTURES


@pytest.fixture
def load_doc():
    def _load(name: str) -> str:
        name = name if name.endswith(".md") else f"{name}.md"
        return (FIXTURES / "docs" / name).read_text(encoding="utf-8")
    return _load


@pytest.fixture
def load_runbook():
    def _load(name: str) -> Runbook:
        name = name if name.endswith(".json") else f"{name}.json"
        text = (FIXTURES / "runbooks" / name).read_text(encoding="utf-8")
        return Runbook.model_validate_json(text)
    return _load


@pytest.fixture
def tmp_runs_dir(tmp_path, monkeypatch):
    monkeypatch.setenv("FIRSTRUN_RUNS_DIR", str(tmp_path))
    monkeypatch.setattr(config, "RUNS_DIR", tmp_path)
    return tmp_path


@pytest.fixture
def tmp_precedents(tmp_path, monkeypatch):
    path = tmp_path / "precedents.json"
    monkeypatch.setenv("FIRSTRUN_PRECEDENTS", str(path))
    monkeypatch.setattr(config, "PRECEDENTS_FILE", path)
    return path


@pytest.fixture
def fake_llm():
    """Factory: fake_llm(["a", "b"]) returns a callable that yields the replies in order."""
    def _make(responses):
        queue = list(responses)
        calls = []

        def _call(prompt: str) -> str:
            calls.append(prompt)
            if not queue:
                raise AssertionError("fake_llm ran out of canned responses")
            return queue.pop(0)

        _call.calls = calls
        return _call
    return _make
