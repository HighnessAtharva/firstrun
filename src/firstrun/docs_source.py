"""Find the GitHub repo and file that hold a docs page, so a docs fix can become a PR."""

from __future__ import annotations

import re
from urllib.parse import urlparse

_EDIT = re.compile(
    r"https?://github\.com/([\w.-]+)/([\w.-]+)/(?:edit|blob)/([\w./-]+?)/([^\s)\"'<>#?]+\.(?:mdx?|rst|txt))",
    re.IGNORECASE,
)

# host -> list of (path fragment, repo, file path). A fragment of "" matches any path on the host.
KNOWN_SITES: dict[str, list[tuple[str, str, str]]] = {
    "docs.getdbt.com": [("guides/duckdb", "dbt-labs/docs.getdbt.com", "website/docs/guides/duckdb-qs.md")],
    "docs.dagster.io": [("getting-started/quickstart", "dagster-io/dagster", "docs/docs/getting-started/quickstart.md")],
    "mkdocs.org": [("getting-started", "mkdocs/mkdocs", "docs/getting-started.md")],
    "help.accuknox.com": [("knoxctl/", "AccuKnox/help", "docs/knoxctl/index.md")],
    "docs.neatlogs.com": [("", "neatlogs/neatlogs", "README.MD")],
    "docs.entire.io": [("", "entireio/cli", "README.md")],
}


def find(source_url: str, docs_markdown: str = "") -> dict:
    """Return {"repo", "path", "branch", "how"}. how is edit-link, known-site or unknown."""
    m = _EDIT.search(docs_markdown or "")
    if m:
        owner, repo, branch, path = m.groups()
        return {"repo": f"{owner}/{repo}", "path": path, "branch": branch, "how": "edit-link"}
    parsed = urlparse(source_url or "")
    host = (parsed.netloc or "").split(":")[0].lower()
    host = host[4:] if host.startswith("www.") else host
    for fragment, repo, path in KNOWN_SITES.get(host, []):
        if fragment in parsed.path:
            return {"repo": repo, "path": path, "branch": "main", "how": "known-site"}
    return {"repo": "", "path": "", "branch": "main", "how": "unknown"}
