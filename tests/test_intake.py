from urllib.parse import parse_qs, urlparse

import pytest

from firstrun import intake


def test_repo_name_accepts_names_and_links():
    assert intake.repo_name("fastapi/typer") == "fastapi/typer"
    assert intake.repo_name("https://github.com/dbt-labs/dbt-core.git") == "dbt-labs/dbt-core"
    assert intake.repo_name("https://github.com/o/r/") == "o/r"
    assert intake.repo_name("not a repo") == ""
    assert intake.repo_name("../etc") == ""


def test_request_url_prefills_the_issue_form():
    q = parse_qs(urlparse(intake.request_url("fastapi/typer")).query)
    assert q["template"] == ["audit-request.yml"]
    assert q["repo"] == ["fastapi/typer"]
    assert q["title"] == ["Audit request: fastapi/typer"]


def test_parse_issue_reads_the_form_body():
    body = ("### GitHub repo\n\nhttps://github.com/fastapi/typer\n\n"
            "### Audit gist (private repos only)\n\n_No response_\n")
    assert intake.parse_issue(body) == {"repo": "fastapi/typer", "gist": ""}
    body2 = ("### GitHub repo\n\nacme/private\n\n### Audit gist (private repos only)\n\n"
             "https://gist.github.com/someone/0123456789abcdef0123\n")
    assert intake.parse_issue(body2) == {"repo": "acme/private", "gist": "0123456789abcdef0123"}
    assert intake.parse_issue("$(rm -rf /)") == {"repo": "", "gist": ""}


def _audit():
    return {"id": "audit-20261011-010203-acme-private", "repo": "acme/private", "generated_at": "2026-10-11T01:02:03+00:00",
            "url": "javascript:alert(1)", "release": {"name": "v1"}, "pages": [], "cards": [],
            "summary": {k: 0 for k in ("pages", "stale", "quiet", "oldest_days", "median_age_days", "features",
                                       "uncovered", "cards")}}


def test_validate_keeps_a_good_audit_and_drops_unsafe_links():
    doc = intake.validate(_audit())
    assert doc["url"] == "" and doc["source"] == "submitted"


@pytest.mark.parametrize("breaks", [
    lambda d: d.pop("summary"),
    lambda d: d.update(id="../../etc/passwd"),
    lambda d: d["summary"].pop("stale"),
    lambda d: d.update(pages="x"),
])
def test_validate_refuses_a_broken_audit(breaks):
    d = _audit()
    breaks(d)
    with pytest.raises(ValueError):
        intake.validate(d)
