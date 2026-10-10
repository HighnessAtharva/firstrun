"""Docs audit: which pages are stale, which feature has no docs, and what a docs team should ship next.

One blobless clone gives the whole history. Everything after that runs offline and costs nothing,
except the optional Jev call that sorts commits with no conventional prefix.
A page is stale when the product moved and the page did not. An old page nobody's code touched is quiet.
"""

from __future__ import annotations

import bisect
import json
import os
import re
import shutil
import statistics
import subprocess
import tempfile
from collections import Counter, defaultdict
from datetime import datetime, timedelta, timezone
from pathlib import Path
from urllib.parse import quote

import httpx
import neatlogs

from firstrun import config
from firstrun.redact import redact
from firstrun.tracing import set_io

JEV_URL = "https://api.typesafe.ai/v1/systemone"
JEV_MODEL = "jev-latest"
HISTORY_MAX = 20000
PAGES_MAX = 400
FEATURE_WINDOW_DAYS = 120
JEV_MAX = 80
JEV_STALE_MAX = 200
JEV_BATCH = 40
# Jev's stale probabilities run low: on dbt the real cases scored 0.40 to 0.47 and unrelated ones 0.1 to 0.3.
STALE_P = 0.35

DOC_EXT = {".md", ".mdx", ".rst", ".adoc"}
DOC_DIRS = ("docs/", "doc/", "documentation/", "website/docs/", "content/", "guide/", "guides/", "help/", "site/docs/")
DOC_SKIP = re.compile(
    r"(^|/)(node_modules|vendor|\.github|i18n|locales?|translations?|_?build|dist|\.git)(/|$)|"
    r"(^|/)(changelog|history|changes|license|licence|code_of_conduct|security|notice|authors|release[-_ ]?notes?)(\.[a-z]+)?$|"
    r"(^|/)(internal|adrs?|rfcs?|decisions|plans?|proposals?|design-docs|maintainers?|blog|posts|news|contributing)(/|$)|"
    r"(^|/)(releasing|contributing|first-time-contributors|maintaining|governance|support|pull_request_template)(\.[a-z]+)?$|"
    r"(^|/)\d{4}-\d{2}-\d{2}-[^/]*$|(^|/)[^/]*-(adr|rfc|plan)\.[a-z]+$|"
    r"(^|/)(zh|ja|ko|fr|de|es|pt|ru|it|tr|ar|hi|vi|pl|nl|cn|tw)(-[a-z]{2,4})?/",
    re.I,
)
CODE_EXT = {".py", ".js", ".ts", ".tsx", ".jsx", ".go", ".rs", ".java", ".kt", ".rb", ".php", ".cs", ".c", ".cc",
            ".cpp", ".h", ".hpp", ".swift", ".scala", ".sh", ".sql", ".yaml", ".yml", ".toml", ".proto", ".vue", ".svelte"}
NOT_PRODUCT = re.compile(r"(^|/)(tests?|__tests__|spec|\.github|ci|scripts?|examples?|benchmarks?|e2e)(/|$)|"
                         r"(\.lock|-lock\.json|\.snap|_test\.[a-z]+|\.test\.[a-z]+|\.spec\.[a-z]+)$", re.I)
GENERIC = {"index", "readme", "docs", "doc", "guide", "guides", "introduction", "intro", "overview", "getting", "started",
           "start", "quickstart", "tutorial", "reference", "api", "home", "main", "about", "faq", "use", "using", "the"}
STOP = set("""a an and are as at be by for from has have in into is it its of on or that the this to was were with
add adds added fix fixes fixed update updates updated support supports use uses using make makes new when now not
allow allows allowed remove removes removed change changes changed improve improves handle handles handling
issue bug error errors option options feature features command commands file files default value values""".split())

_CONV = re.compile(r"^(?P<t>[a-z]+)(\((?P<s>[^)]*)\))?(?P<bang>!)?:\s*(?P<m>.+)$", re.I)
_FEATURE_T = {"feat", "feature", "add", "new"}
_FIX_T = {"fix", "bugfix", "hotfix", "perf"}
_DOCS_T = {"docs", "doc"}
_INTERNAL_T = {"chore", "ci", "test", "tests", "build", "refactor", "style", "deps", "dep", "bump", "release", "revert", "wip", "merge"}
_FEATURE_WORDS = re.compile(r"^(add|adds|added|introduce|introduces|support|supports|implement|implements|enable|enables|allow|allows|new)\b", re.I)
_FIX_WORDS = re.compile(r"^(fix|fixes|fixed|resolve|resolves|correct|patch|handle|prevent|avoid)\b", re.I)
_INTERNAL_WORDS = re.compile(r"^(bump|merge|revert|update (deps|dependencies)|release|version|chore|ci|test|refactor|lint|format)\b", re.I)


# ----------------------------------------------------------------------------- git plumbing

def _git(repo: Path, *args: str, check: bool = True) -> str:
    p = subprocess.run(["git", "-c", "core.quotepath=off", "-C", str(repo), *args], capture_output=True,
                       text=True, encoding="utf-8", errors="replace")
    if check and p.returncode != 0:
        raise RuntimeError(f"git {args[0]} failed: {p.stderr.strip()[:300]}")
    return p.stdout


def resolve_target(target: str) -> tuple[str, str]:
    """(clone url or local path, display name). Accepts owner/repo, a GitHub URL, or a local git folder."""
    t = target.strip()
    if Path(t).is_dir() and (Path(t) / ".git").exists():
        return str(Path(t).resolve()), Path(t).resolve().name
    m = re.match(r"^(?:https?://github\.com/)?([\w.-]+)/([\w.-]+?)(?:\.git)?(?:/.*)?$", t)
    if m:
        return f"https://github.com/{m.group(1)}/{m.group(2)}.git", f"{m.group(1)}/{m.group(2)}"
    raise ValueError(f"not a GitHub repo or a git folder: {target}")


def clone(url: str, dest: Path) -> Path:
    if Path(url).is_dir():
        return Path(url)
    p = subprocess.run(["git", "clone", "--quiet", "--filter=blob:none", "--no-checkout", url, str(dest)],
                       capture_output=True, text=True, encoding="utf-8", errors="replace")
    if p.returncode != 0:
        raise RuntimeError(f"clone failed: {redact(p.stderr.strip())[:300]}")
    return dest


def is_doc_path(path: str) -> bool:
    p = path.replace("\\", "/")
    if Path(p).suffix.lower() not in DOC_EXT or DOC_SKIP.search(p):
        return False
    low = p.lower()
    return low.startswith(DOC_DIRS) or "/docs/" in low or "/documentation/" in low or "/" not in p and low.startswith("readme")


def _is_product(path: str) -> bool:
    return Path(path).suffix.lower() in CODE_EXT and not NOT_PRODUCT.search(path) and not is_doc_path(path)


def read_history(repo: Path) -> list[dict]:
    """Newest first: sha, date, author, subject, files."""
    out = _git(repo, "log", f"--max-count={HISTORY_MAX}", "--no-renames", "--name-only",
               "--format=%x01%H%x09%cI%x09%an%x09%s")
    commits = []
    for block in out.split("\x01")[1:]:
        head, _, files = block.partition("\n")
        parts = head.split("\t", 3)
        if len(parts) < 4:
            continue
        sha, iso, author, subject = parts
        m = _CONV.match(re.sub(r"^\W+", "", subject.strip()))
        commits.append({"scope": (m.group("s") or "").lower() if m else "",
                        "sha": sha, "date": datetime.fromisoformat(iso).astimezone(timezone.utc),
                        "author": author, "subject": subject.strip(),
                        "files": [f for f in files.splitlines() if f.strip()]})
    return commits


def read_tags(repo: Path) -> list[dict]:
    out = _git(repo, "for-each-ref", "refs/tags", "--sort=-creatordate",
               "--format=%(refname:short)\t%(creatordate:iso-strict)\t%(*objectname)%(objectname)", check=False)
    tags = []
    for line in out.splitlines():
        parts = line.split("\t")
        if len(parts) == 3 and parts[1]:
            tags.append({"name": parts[0], "date": datetime.fromisoformat(parts[1]).astimezone(timezone.utc)})
    return tags


def head_docs(repo: Path) -> list[str]:
    return [f for f in _git(repo, "ls-tree", "-r", "--name-only", "HEAD").splitlines() if is_doc_path(f)]


def _raw_base(repo: Path) -> str:
    """raw.githubusercontent.com prefix for HEAD of a GitHub clone, or '' for anything else."""
    url = _git(repo, "remote", "get-url", "origin", check=False).strip()
    m = re.match(r"^https://github\.com/([\w.-]+)/([\w.-]+?)(?:\.git)?$", url)
    sha = _git(repo, "rev-parse", "HEAD", check=False).strip()
    return f"https://raw.githubusercontent.com/{m.group(1)}/{m.group(2)}/{sha}/" if m and sha else ""


def read_doc_texts(repo: Path, paths: list[str]) -> dict[str, str]:
    """Docs text at HEAD. A batched checkout fetches the blobs. A lazy fetch can hang on a flaky network,
    so each batch has a time limit and raw.githubusercontent.com fills whatever is still missing."""
    if not paths:
        return {}
    env = {**os.environ, "GIT_TERMINAL_PROMPT": "0"}
    if (repo / ".git").is_dir() and not any((repo / p).exists() for p in paths[:3]):
        for i in range(0, len(paths), 400):
            batch = [p for p in paths[i:i + 400] if not (repo / p).exists()]
            for _ in range(2):  # the first lazy fetch of a fresh partial clone often fails, the second works
                if not batch:
                    break
                try:
                    # No `-c` here: a config override on the command line breaks the lazy blob fetch.
                    r = subprocess.run(["git", "-C", str(repo), "checkout", "HEAD", "--", *batch], capture_output=True,
                                       text=True, encoding="utf-8", errors="replace", timeout=90, env=env)
                    if r.returncode == 0:
                        break
                except subprocess.TimeoutExpired:
                    pass
                batch = [p for p in batch if not (repo / p).exists()]
    out = {}
    for p in paths:
        try:
            out[p] = (repo / p).read_text(encoding="utf-8", errors="replace")
        except OSError:
            out[p] = None
    missing = [p for p, t in out.items() if t is None]
    base = _raw_base(repo) if missing else ""
    if missing and base:
        from concurrent.futures import ThreadPoolExecutor

        def get(path: str) -> tuple[str, str]:
            try:
                r = httpx.get(base + quote(path), timeout=20)
                return path, r.text if r.status_code == 200 else ""
            except httpx.HTTPError:
                return path, ""

        with ThreadPoolExecutor(16) as pool:
            for path, text in pool.map(get, missing):
                out[path] = text
    return {p: (t or "") for p, t in out.items()}


# ----------------------------------------------------------------------------- pages

def _title(text: str, path: str) -> str:
    for pat in (r"^title:\s*[\"']?(.+?)[\"']?\s*$", r"^#\s+(.+)$"):
        m = re.search(pat, text[:4000], re.M)
        t = re.sub(r"[`*_\[\]]|<[^>]*>|\{[^}]*\}", "", m.group(1)).strip() if m else ""
        if t and not t.startswith(("<", "{", "!")):
            return t[:100]
    return Path(path).stem.replace("-", " ").replace("_", " ").title()


def _keywords(path: str, title: str) -> set[str]:
    """The page's topic words: its file name, or its folder when the file is an index page."""
    parts = Path(path.lower()).with_suffix("").parts
    name = parts[-1] if parts else ""
    if name in GENERIC and len(parts) > 1:
        name = parts[-2]
    words = re.findall(r"[a-z][a-z0-9]{2,}", name)
    keep = {w for w in words if w not in GENERIC and w not in STOP and w not in {"md", "mdx", "rst", "adoc", "and", "with", "for"}}
    return {w[:-1] if len(w) > 4 and w.endswith("s") and not w.endswith("ss") else w for w in keep}


def analyze_pages(commits: list[dict], docs: list[str], texts: dict[str, str], now: datetime,
                  stale_days: int, product_commits: list[dict] | None = None, repo_name: str = "") -> list[dict]:
    """commits holds the docs history. product_commits holds the code history when docs live in another repo."""
    docset = set(docs)
    last: dict[str, dict] = {}
    for c in commits:  # newest first, so the first sight of a file is its last touch
        for f in c["files"]:
            if f in docset and f not in last:
                last[f] = c
    # Only user-facing change counts as the product moving: bumps, CI and refactors do not.
    product = [c for c in (commits if product_commits is None else product_commits) if any(_is_product(f) for f in c["files"])
               and classify_subject(c["subject"]) not in ("internal", "docs")]
    # Precompute once: each product commit's topic tokens, and its date for a bisect.
    toks = []
    for p in product:
        hay = " ".join(f.lower() for f in p["files"] if _is_product(f)) + " " + " ".join(
            re.findall(r"`([^`]+)`", p["subject"].lower())) + " " + (p.get("scope") or "")
        words = set(re.findall(r"[a-z][a-z0-9]*", hay))
        toks.append(words | {w[:-1] for w in words if len(w) > 4 and w.endswith("s")})
    neg_dates = [-p["date"].timestamp() for p in product]  # product is newest first, so this ascends
    # A topic word that shows up in more than 2% of product commits ("column", "src") names no topic.
    df = Counter(w for t in toks for w in t)
    # Small projects keep every word: with under 200 commits, one area can fairly own most of them.
    rare = int(0.02 * len(product)) if len(product) >= 200 else len(product)
    pages = []
    for path in docs:
        c = last.get(path)
        title = _title(texts.get(path, ""), path)
        # The project's own name matches every commit, so it never marks a topic.
        kw = _keywords(path, title) - set(re.findall(r"[a-z][a-z0-9]{2,}", repo_name.lower()))
        kw = {k for k in kw if 0 < df[k] <= rare}
        if c is None:  # touched before the history window
            touched = None
            age = (now - commits[-1]["date"]).days if commits else 0
        else:
            touched = c["date"]
            age = max(0, (now - touched).days)
        n_since = len(product) if touched is None else bisect.bisect_left(neg_dates, -touched.timestamp())
        since = product[:n_since]
        relevant = [p for p, t in zip(since, toks) if kw and not kw.isdisjoint(t)]
        if age < 90:
            status = "fresh"
        elif age < stale_days:
            status = "aging"
        elif relevant:
            status = "stale"
        else:
            status = "quiet"
        pages.append({
            "path": path, "title": title,
            "last_touched": touched.date().isoformat() if touched else None,
            "age_days": age, "older_than_history": touched is None,
            "status": status, "ancient": age >= 730,
            "relevant_since": len(relevant), "product_since": len(since),
            "last_commit": (c["subject"][:100] if c else ""),
            "evidence": [{"sha": p["sha"][:9], "date": p["date"].date().isoformat(), "subject": p["subject"][:100]}
                         for p in relevant[:3]],
        })
    pages.sort(key=lambda p: (-p["age_days"], p["path"]))
    return pages


def _jev_stale_batch(key: str, cand: list[dict], texts: dict[str, str]) -> dict[int, float] | None:
    state = {str(i): {"docs_page": p["path"], "page_excerpt": (texts.get(p["path"]) or "")[:1500],
                      "commits_since_last_edit": [e["subject"] for e in p["evidence"]]}
             for i, p in enumerate(cand)}
    q = {f"s{i}": {"type": "noul",
                   "instructions": f"Item {i}: would any of these code commits make this docs page wrong, outdated or incomplete for a user?"}
         for i in range(len(cand))}
    try:
        r = httpx.post(JEV_URL, json={"model": JEV_MODEL, "state": state, "questions": q},
                       headers={"Authorization": f"Bearer {key}"}, timeout=90)
        r.raise_for_status()
        ans = r.json()["answers"]
        return {i: float(ans[f"s{i}"]["noul"]) for i in range(len(cand)) if f"s{i}" in ans}
    except Exception:  # noqa: BLE001 - Jev is optional
        return None


def jev_stale(pages: list[dict], texts: dict[str, str]) -> int:
    """Jev reads each stale candidate and the commits behind it. Only a page Jev expects a commit to break stays
    stale. When Jev ran, candidates it never read become "unchecked", because text matching alone over-claims.
    Returns how many pages Jev cleared. Changes nothing when Jev is unavailable."""
    config.load_env()
    key = os.environ.get("TYPESAFE_API_KEY")
    cand = sorted([p for p in pages if p["status"] == "stale"], key=lambda p: -p.get("relevant_since", 0))
    if not key or not cand:
        return 0
    checked, cleared, ran = set(), 0, False
    todo = cand[:JEV_STALE_MAX]
    for i in range(0, len(todo), JEV_BATCH):
        batch = todo[i:i + JEV_BATCH]
        got = _jev_stale_batch(key, batch, texts)
        if got is None:
            continue
        ran = True
        for j, prob in got.items():
            p = batch[j]
            p["stale_p"] = round(prob, 2)
            p["judge"] = "jev"
            checked.add(p["path"])
            if prob < STALE_P:
                p["status"] = "quiet"
                cleared += 1
    if ran:
        for p in cand:
            if p["path"] not in checked:
                p["status"] = "unchecked"
    return cleared


# ----------------------------------------------------------------------------- features

_GITMOJI = {"✨": "feature", "🎉": "feature", "💥": "feature", "🚸": "feature", "🌐": "feature",
            "🐛": "fix", "🚑": "fix", "🩹": "fix", "⚡": "fix", "🔒": "fix", "🔐": "internal",
            "📝": "docs", "📚": "docs", "💡": "docs",
            "⬆": "internal", "⬇": "internal", "♻": "internal", "👷": "internal", "✅": "internal", "🔖": "internal",
            "🔧": "internal", "🎨": "internal", "🔥": "internal", "🚨": "internal", "📌": "internal", "➕": "internal",
            "➖": "internal", "💚": "internal", "🙈": "internal", "🧪": "internal", "🏗": "internal", "🤖": "internal",
            "👥": "internal", "🔨": "internal", "📦": "internal", "🚀": "internal", "⏪": "internal", "🔀": "internal"}


def classify_subject(subject: str) -> str:
    """feature, fix, docs, internal or unknown, from the subject line alone. Reads gitmoji too."""
    s = re.sub(r"\s*\(#\d+\)\s*$", "", subject.strip())
    for emoji, kind in _GITMOJI.items():
        if s.startswith(emoji):
            return kind
    s = re.sub(r"^:[a-z_]+:\s*", "", s)
    m = _CONV.match(s)
    if m:
        t = m.group("t").lower()
        if t in _FEATURE_T:
            return "feature"
        if t in _FIX_T:
            return "fix"
        if t in _DOCS_T:
            return "docs"
        if t in _INTERNAL_T:
            return "internal"
    if _INTERNAL_WORDS.match(s) or s.lower().startswith(("merge ", "revert ")):
        return "internal"
    if _FEATURE_WORDS.match(s):
        return "feature"
    if _FIX_WORDS.match(s):
        return "fix"
    return "unknown"


_CRITERIA = {
    "feature": "A user can now do something new, or a new option, command, integration or capability shipped.",
    "fix": "A bug, crash or wrong behavior was corrected.",
    "docs": "Only documentation changed.",
    "internal": "Refactor, tests, CI, dependency bump or tooling that users never see.",
}


def jev_sort(subjects: list[str]) -> dict[int, str]:
    """One Jev call, one Choice question per commit subject. Returns {index: class}. Empty on any failure."""
    config.load_env()
    key = os.environ.get("TYPESAFE_API_KEY")
    if not key or not subjects:
        return {}
    body = {
        "model": JEV_MODEL,
        "state": {"commit_subjects": {str(i): s for i, s in enumerate(subjects)}},
        "questions": {f"c{i}": {"type": "choice",
                                "instructions": f"What kind of change is commit subject number {i} in this open-source project?",
                                "criteria": _CRITERIA} for i in range(len(subjects))},
    }
    try:
        r = httpx.post(JEV_URL, json=body, headers={"Authorization": f"Bearer {key}"}, timeout=60)
        r.raise_for_status()
        answers = r.json()["answers"]
        out = {}
        for i in range(len(subjects)):
            probs = answers[f"c{i}"]["probabilities"]
            best = max(probs, key=probs.get)
            if best in _CRITERIA and probs[best] >= 0.5:
                out[i] = best
        return out
    except Exception:  # noqa: BLE001 - Jev is optional
        return {}


def _terms(subject: str) -> tuple[list[str], list[str]]:
    """(strong terms, weak words). Strong terms are flags, backticked names and identifiers."""
    s = re.sub(r"\s*\(#\d+\)\s*$", "", subject)
    s = _CONV.sub(lambda m: m.group("m"), s.strip(), count=1)
    strong = re.findall(r"`([^`]{2,40})`", s) + re.findall(r"(?<![\w-])(--[a-z][\w-]{2,})", s)
    # Identifiers only. A hyphenated word in prose ("locally-authored") is English, not a name a page would carry.
    strong += [w for w in re.findall(r"\b[a-z]+[A-Z][A-Za-z]+\b|\b[a-z]+_[a-z_]+\b|\b[A-Z][A-Z0-9]+_[A-Z0-9_]+\b", s)]
    weak = [w for w in re.findall(r"[a-z][a-z0-9]{3,}", s.lower()) if w not in STOP]
    return list(dict.fromkeys(x.lower() for x in strong)), list(dict.fromkeys(weak))


def _pr(subject: str) -> str | None:
    m = re.search(r"\(#(\d+)\)\s*$", subject) or re.match(r"Merge pull request #(\d+)", subject)
    return m.group(1) if m else None


def _excerpt(texts: dict[str, str], words: list[str]) -> tuple[str, str]:
    """(path, about 1,200 characters) of the docs page that shares the most words with a feature."""
    best, score = "", 0
    for path, t in texts.items():
        low = t.lower()
        k = sum(1 for w in words if w in low)
        if k > score:
            best, score = path, k
    if not best:
        return "", ""
    low = texts[best].lower()
    hits = [low.find(w) for w in words if w in low]
    at = max(0, min(hits) - 300) if hits else 0
    return best, texts[best][at:at + 1200]


def jev_features(feats: list[dict], excerpts: list[str]) -> dict[int, tuple[str, float]]:
    """One Jev call. Per feature: is it user-facing, and does the closest docs excerpt cover it?
    Returns {index: (kind, covered probability)}. Empty on any failure."""
    config.load_env()
    key = os.environ.get("TYPESAFE_API_KEY")
    if not key or not feats:
        return {}
    state = {str(i): {"commit": f["subject"], "closest_docs_excerpt": excerpts[i] or "(no page shares a word)"}
             for i, f in enumerate(feats)}
    q = {}
    for i in range(len(feats)):
        q[f"k{i}"] = {"type": "choice", "criteria": _CRITERIA,
                      "instructions": f"Item {i}: what kind of change is this commit, for someone who uses the product?"}
        q[f"d{i}"] = {"type": "noul",
                      "instructions": f"Item {i}: does the docs excerpt explain this change well enough for a user to find and use it?"}
    try:
        r = httpx.post(JEV_URL, json={"model": JEV_MODEL, "state": state, "questions": q},
                       headers={"Authorization": f"Bearer {key}"}, timeout=90)
        r.raise_for_status()
        ans = r.json()["answers"]
        out = {}
        for i in range(len(feats)):
            probs = ans[f"k{i}"]["probabilities"]
            out[i] = (max(probs, key=probs.get), float(ans[f"d{i}"]["noul"]))
        return out
    except Exception:  # noqa: BLE001 - Jev is optional
        return {}


def find_features(commits: list[dict], now: datetime, corpus: str, use_jev: bool,
                  texts: dict[str, str] | None = None) -> list[dict]:
    window = now - timedelta(days=FEATURE_WINDOW_DAYS)
    recent = [c for c in commits if c["date"] >= window and any(_is_product(f) for f in c["files"])]
    kinds = [classify_subject(c["subject"]) for c in recent]
    if use_jev:
        idx = [i for i, k in enumerate(kinds) if k == "unknown"][:JEV_MAX]
        for i, k in jev_sort([recent[i]["subject"] for i in idx]).items():
            kinds[idx[i]] = k
    feats = []
    for c, k in zip(recent, kinds):
        if k != "feature":
            continue
        strong, weak = _terms(c["subject"])
        hits = [t for t in strong if t in corpus]
        if strong:
            covered = bool(hits)
        else:
            covered = bool(weak) and sum(1 for w in weak if w in corpus) >= max(2, len(weak) // 2 + 1)
        top = (strong or weak or [""])[0]
        m = _CONV.match(re.sub(r"^\W+", "", c["subject"]))
        pfiles = [f for f in c["files"] if _is_product(f)]
        stem = Path(pfiles[0]).stem.lower() if pfiles else ""
        area = (m.group("s") or "").lower() if m and m.group("s") else ""
        area_src = "scope" if area else ""
        if not area:
            area = stem if stem and stem not in GENERIC | {"__init__", "core", "main", "utils", "util", "lib"} else top
            area_src = "file" if area == stem else "term"
        feats.append({"sha": c["sha"][:9], "date": c["date"].date().isoformat(), "subject": c["subject"][:140],
                      "author": c["author"], "pr": _pr(c["subject"]), "term": top, "area": area, "area_src": area_src,
                      "strong": strong[:4], "covered": covered, "judge": "text",
                      "files": [f for f in c["files"] if _is_product(f)][:4], "_words": strong + weak})
    texts = texts or {}
    hint = [_excerpt(texts, f["_words"]) for f in feats]
    for f, (path, _) in zip(feats, hint):
        f["closest_page"] = path
    if use_jev and feats:
        top = feats[:JEV_MAX]
        verdict = jev_features(top, [h[1] for h in hint[:JEV_MAX]])
        for i, (kind, p_cov) in verdict.items():
            top[i]["jev_kind"] = kind
            top[i]["covered"] = p_cov >= 0.5
            top[i]["judge"] = "jev"
        feats = [f for f in feats if f.get("jev_kind", "feature") == "feature"]
    for f in feats:
        f.pop("_words", None)
    return feats


def momentum(commits: list[dict], now: datetime, feats: list[dict]) -> dict[str, dict]:
    """Commits and authors that touch the same term in the window. Three or more commits is momentum."""
    window = now - timedelta(days=FEATURE_WINDOW_DAYS)
    out = {}
    for f in feats:
        t = f["area"]
        if not t or t in out:
            continue
        rel = [c for c in commits if c["date"] >= window and classify_subject(c["subject"]) not in ("internal", "docs")
               and t in (c["subject"].lower() + " " + " ".join(x for x in c["files"] if _is_product(x)).lower())]
        out[t] = {"commits": len(rel), "authors": len({c["author"] for c in rel})}
    return out


# ----------------------------------------------------------------------------- releases and drafts

_PRE = re.compile(r"nightly|canary|alpha|beta|rc|-rc|dev|snapshot|preview|next", re.I)


def release_range(commits: list[dict], tags: list[dict], now: datetime) -> dict:
    """The newest stable release and the commits in it. Falls back to the last 30 days when there are no tags."""
    stable = [t for t in tags if not _PRE.search(t["name"])]
    tags = stable or tags
    if len(tags) >= 2:
        newest, prev = tags[0], tags[1]
        sel = [c for c in commits if prev["date"] < c["date"] <= newest["date"] + timedelta(hours=1)]
        return {"name": newest["name"], "previous": prev["name"], "date": newest["date"].date().isoformat(), "commits": sel}
    if len(tags) == 1:
        sel = [c for c in commits if c["date"] <= tags[0]["date"] + timedelta(hours=1)][:60]
        return {"name": tags[0]["name"], "previous": "", "date": tags[0]["date"].date().isoformat(), "commits": sel}
    sel = [c for c in commits if c["date"] >= now - timedelta(days=30)]
    return {"name": "Unreleased", "previous": "", "date": now.date().isoformat(), "commits": sel}


def _clean(subject: str) -> str:
    s = re.sub(r"\s*\(#\d+\)\s*$", "", subject.strip())
    s = re.sub(r"^(?::[a-z_]+:|[^\w`(\[]+)\s*", "", s)
    s = _CONV.sub(lambda m: m.group("m"), s, count=1)
    return s[:1].upper() + s[1:]


def draft_release_notes(repo_name: str, rel: dict, kinds: dict[str, str]) -> str:
    groups = defaultdict(list)
    for c in rel["commits"]:
        k = kinds.get(c["sha"]) or classify_subject(c["subject"])
        low = c["subject"].lower()
        if k == "internal" or low.startswith("merge ") or re.search(r"release notes|changelog|bump version|release version", low):
            continue
        pr = _pr(c["subject"])
        groups[k if k in ("feature", "fix", "docs") else "other"].append(
            f"- {_clean(c['subject'])}" + (f" (#{pr})" if pr else ""))
    names = [("feature", "New"), ("fix", "Fixed"), ("docs", "Docs"), ("other", "Also in this release")]
    lines = [f"# {repo_name} {rel['name']}", ""]
    if rel["previous"]:
        lines += [f"Changes since {rel['previous']}, released {rel['date']}.", ""]
    for key, title in names:
        if groups[key]:
            lines += [f"## {title}", "", *list(dict.fromkeys(groups[key]))[:25], ""]
    if len(lines) <= 3:
        lines.append("No user-facing changes found in this range.")
    lines.append("_Draft from the git history. Edit before you publish._")
    return "\n".join(lines).strip() + "\n"


def draft_highlights(repo_name: str, feats: list[dict], mom: dict[str, dict]) -> list[dict]:
    """Up to three product highlight blurbs for the newest features, strongest momentum first."""
    ranked = sorted(feats, key=lambda f: mom.get(f["area"], {}).get("commits", 0), reverse=True)
    out, seen = [], set()
    for f in ranked:
        if f["subject"] in seen:
            continue
        seen.add(f["subject"])
        head = _clean(f["subject"])
        out.append({"headline": head, "date": f["date"], "pr": f["pr"],
                    "blurb": f"New in {repo_name}: {head.rstrip('.')}. Shipped {f['date']}"
                             + (f" in #{f['pr']}." if f["pr"] else ".")})
        if len(out) == 3:
            break
    return out


# ----------------------------------------------------------------------------- cards

def _n(k: int, word: str) -> str:
    return f"{k} {word}" + ("" if k == 1 else "s")


def build_cards(repo: str, pages: list[dict], feats: list[dict], mom: dict[str, dict], rel: dict,
                notes: str, has_changelog_recent: bool, stale_days: int) -> list[dict]:
    cards: list[dict] = []

    def ev(f):
        return {"sha": f["sha"], "date": f["date"], "subject": f["subject"], "pr": f["pr"]}

    repo_words = set(re.findall(r"[a-z][a-z0-9]{2,}", repo.lower()))
    ordered = sorted(feats, key=lambda f: f["date"], reverse=True)
    ordered = sorted(ordered, key=lambda f: mom.get(f["area"], {}).get("commits", 0), reverse=True)

    # Undocumented features that share an area become one card: a missing page, not 20 missing lines.
    unc = [f for f in ordered if not f["covered"]]
    by_area: dict[str, list[dict]] = defaultdict(list)
    for f in unc:
        by_area[f["area"]].append(f)
    clustered = set()
    for area, fs in sorted(by_area.items(), key=lambda kv: -len(kv[1])):
        if len(fs) < 3 or not area or len(area) < 3 or area in repo_words:
            continue
        clustered.add(area)
        near = Counter(f.get("closest_page") for f in fs if f.get("closest_page")).most_common(1)
        first = min(f["date"] for f in fs)
        judged = any(f.get("judge") == "jev" for f in fs)
        own = sorted((p["path"] for p in pages if area.lower() in p["path"].lower()), key=len)
        if own:
            title = f"Document the new `{area}` changes"
            why = (f"{len(fs)} user-facing changes to `{area}` shipped since {first}. "
                   + ("Jev read the closest docs page for each one and found none of them explained." if judged
                      else "No docs page names them."))
            action = f"Add them to {own[0]}, the `{area}` page, with one example each."
        else:
            title = f"Document the `{area}` feature"
            why = (f"{len(fs)} user-facing changes to `{area}` shipped since {first}, and no docs page is about `{area}`."
                   + (" Jev read the closest page for each change." if judged else ""))
            action = (f"Write one `{area}` page: what it does, how to turn it on, and its commands."
                      + (f" Link it from {near[0][0]}." if near else ""))
        cards.append({"kind": "document", "priority": 0, "title": title, "why": why, "action": action,
                      "evidence": [ev(f) for f in fs[:3]], "count": len(fs)})
    seen = set()
    for f in unc:
        if f["area"] in clustered or f["subject"] in seen:
            continue
        seen.add(f["subject"])
        cards.append({"kind": "document", "priority": 1, "title": f"Document: {_clean(f['subject'])}",
                      "why": (f"Shipped {f['date']}. Jev read the closest docs page and found it does not explain this."
                              if f.get("judge") == "jev" else f"Shipped {f['date']} and no docs page names `{f['term'] or 'it'}`. A user cannot find it."),
                      "action": (f"Add a section to {f['closest_page']}, the closest page, or write a short how-to and link it from the feature list."
                                 if f.get("closest_page") else "Write a short how-to page and link it from the feature list."),
                      "evidence": [ev(f)]})

    # Content: areas the team keeps shipping. Projects that scope their commits get scopes only.
    use_scopes = sum(1 for f in feats if f.get("area_src") == "scope") >= max(3, len(feats) // 3)
    picks: dict[str, tuple[dict, dict]] = {}
    for f in ordered:
        a = f["area"]
        if not a or len(a) < 3 or a in repo_words or a in picks or (use_scopes and f.get("area_src") != "scope"):
            continue
        m = mom.get(a, {"commits": 1, "authors": 1})
        if m["commits"] >= 4 or (m["commits"] >= 3 and m["authors"] >= 2):
            picks[a] = (m, f)
    for a, (m, f) in sorted(picks.items(), key=lambda kv: -kv[1][0]["commits"]):
        cards.append({"kind": "content", "priority": 2, "title": f"Create content around `{a}`",
                      "why": f"{m['commits']} user-facing commits by {m['authors']} "
                             f"{'person' if m['authors'] == 1 else 'people'} touched it in {FEATURE_WINDOW_DAYS} days. "
                             "The team keeps investing here, so it is worth a story."
                             + (" It has no docs page yet, so write that first." if a in clustered else ""),
                      "action": "Publish a tutorial, a 60-second demo and a changelog post. Reuse the highlight draft below.",
                      "evidence": [ev(f)]})
    judged = [f for f in feats if f.get("judge") == "jev"]
    for f in (judged or feats)[:5]:
        if f["date"] >= (datetime.now(timezone.utc) - timedelta(days=45)).date().isoformat():
            cards.append({"kind": "feature", "priority": 2, "title": f"Feature this: {_clean(f['subject'])}",
                          "why": f"Shipped {f['date']}. Recent and user-visible, so it belongs on the homepage and in the release post.",
                          "action": "Add it to the release post, the homepage feature list and the next newsletter.",
                          "evidence": [ev(f)]})
    for p in [x for x in pages if x["status"] == "stale"][:8]:
        cards.append({"kind": "refresh", "priority": 1 if p["ancient"] or p["relevant_since"] >= 5 else 3,
                      "title": f"Refresh {p['path']}",
                      "why": f"Last touched {p['last_touched'] or 'before the history window'} ({p['age_days']} days ago). "
                             f"Since then, {_n(p['relevant_since'], 'commit')} changed code on its topic, "
                             f"out of {_n(p['product_since'], 'user-facing commit')}.",
                      "action": ("Jev read the page and the commits and expects at least one to make it wrong or incomplete. "
                                 if p.get("judge") == "jev" else "") + "Re-read the page against the current code and update or delete what changed.",
                      "evidence": p["evidence"]})
    if rel["commits"]:
        cards.append({"kind": "automate", "priority": 2, "title": f"Release notes for {rel['name']} are ready to edit",
                      "why": f"{_n(len(rel['commits']), 'commit')} since {rel['previous'] or 'the last 30 days'}. "
                             + ("A changelog file changed recently." if has_changelog_recent else "No changelog file changed in this window."),
                      "action": "Open the draft, trim it, and publish it as the GitHub release body.", "evidence": []})
    cards.append({"kind": "quickstart", "priority": 3, "title": "Run the quickstart as a new developer",
                  "why": "An audit reads text. A run proves the steps still work in a clean container.",
                  "action": f"firstrun https://github.com/{repo}#readme", "evidence": []})
    caps = {"document": 8, "refresh": 6, "feature": 4, "content": 4}
    kept, used = [], Counter()
    for c in sorted(cards, key=lambda c: c["priority"]):
        if used[c["kind"]] < caps.get(c["kind"], 3):
            used[c["kind"]] += 1
            kept.append(c)
    return kept


# ----------------------------------------------------------------------------- the audit

def _summary(pages: list[dict]) -> dict:
    ages = [p["age_days"] for p in pages]
    c = Counter(p["status"] for p in pages)
    return {"pages": len(pages), "fresh": c["fresh"], "aging": c["aging"], "stale": c["stale"], "quiet": c["quiet"],
            "unchecked": c["unchecked"],
            "ancient": sum(1 for p in pages if p["ancient"]),
            "median_age_days": int(statistics.median(ages)) if ages else 0,
            "oldest_days": max(ages) if ages else 0}


@neatlogs.span(kind="WORKFLOW", name="firstrun.audit")
def audit(target: str, stale_days: int = 180, use_jev: bool = True, keep: Path | None = None,
          docs_repo: str | None = None) -> dict:
    """docs_repo: a second repo that holds the docs site, when the docs do not live next to the code."""
    now = datetime.now(timezone.utc)
    url, name = resolve_target(target)
    tmp = Path(tempfile.mkdtemp(prefix="firstrun-audit-"))
    try:
        with neatlogs.trace("audit.clone", kind="TOOL") as span:
            repo = clone(url, keep or tmp / "repo")
            set_io(span, input={"repo": name})
        with neatlogs.trace("audit.history", kind="TOOL") as span:
            commits = read_history(repo)
            tags = read_tags(repo)
            set_io(span, output={"commits": len(commits), "tags": len(tags)})
        if not commits:
            raise RuntimeError("the repository has no commits")
        docs_url = f"https://github.com/{name}" if "/" in name and not Path(name).exists() else ""
        with neatlogs.trace("audit.pages", kind="TOOL") as span:
            if docs_repo:
                durl, dname = resolve_target(docs_repo)
                drepo = clone(durl, tmp / "docs")
                dcommits = read_history(drepo)
                docs = [f for f in _git(drepo, "ls-tree", "-r", "--name-only", "HEAD").splitlines()
                        if Path(f).suffix.lower() in DOC_EXT and not DOC_SKIP.search(f)]
                texts = read_doc_texts(drepo, docs)
                pages = analyze_pages(dcommits, docs, texts, now, stale_days, product_commits=commits, repo_name=name)
                docs_url = f"https://github.com/{dname}" if "/" in dname and not Path(dname).exists() else ""
            else:
                docs = head_docs(repo)
                texts = read_doc_texts(repo, docs)
                pages = analyze_pages(commits, docs, texts, now, stale_days, repo_name=name)
            cleared = jev_stale(pages, texts) if use_jev else 0
            set_io(span, input={"docs_repo": docs_repo or name}, output={**_summary(pages), "jev_cleared": cleared})
        corpus = " ".join(texts.values()).lower()
        with neatlogs.trace("audit.features", kind="TOOL") as span:
            feats = find_features(commits, now, corpus, use_jev, texts)
            mom = momentum(commits, now, feats)
            set_io(span, output={"features": len(feats), "uncovered": sum(1 for f in feats if not f["covered"])})
        rel = release_range(commits, tags, now)
        kinds = {c["sha"]: classify_subject(c["subject"]) for c in rel["commits"]}
        notes = draft_release_notes(name, rel, kinds)
        highlights = draft_highlights(name, feats, mom)
        cl = [c for c in commits if c["date"] >= now - timedelta(days=60)
              and any(re.search(r"(^|/)(changelog|history|changes|release[-_ ]?notes?)", f, re.I) for f in c["files"])]
        cards = build_cards(name, pages, feats, mom, rel, notes, bool(cl), stale_days)
        stamp = now.strftime("%Y%m%d-%H%M%S")
        result = {
            "v": 1, "id": f"audit-{stamp}-{re.sub(r'[^a-z0-9]+', '-', name.lower()).strip('-')}",
            "repo": name, "url": f"https://github.com/{name}" if "/" in name and not Path(name).exists() else "",
            "docs_repo": docs_repo or "", "docs_url": docs_url,
            "generated_at": now.isoformat(timespec="seconds"), "stale_days": stale_days,
            "history": {"commits": len(commits), "since": commits[-1]["date"].date().isoformat(),
                        "capped": len(commits) >= HISTORY_MAX},
            "summary": {**_summary(pages), "features": len(feats), "uncovered": sum(1 for f in feats if not f["covered"]),
                        "cards": len(cards)},
            "pages": pages[:PAGES_MAX],
            "release": {"name": rel["name"], "previous": rel["previous"], "date": rel["date"], "commits": len(rel["commits"])},
            "features": feats[:40], "cards": cards[:30],
            "drafts": {"release_notes": notes, "highlights": highlights},
            "jev": bool(use_jev and os.environ.get("TYPESAFE_API_KEY")),
        }
        return result
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


# ----------------------------------------------------------------------------- sitemap mode

def audit_sitemap(site: str, stale_days: int = 180) -> dict:
    """A docs site with no repo: read the sitemap and rank pages by lastmod."""
    base = site.rstrip("/")
    if not base.startswith("http"):
        base = "https://" + base
    now = datetime.now(timezone.utc)
    xml = ""
    for path in ("/sitemap.xml", "/sitemap_index.xml"):
        try:
            r = httpx.get(base + path, timeout=20, follow_redirects=True)
            if r.status_code == 200 and "<url" in r.text:
                xml = r.text
                break
        except httpx.HTTPError:
            continue
    if not xml:
        raise RuntimeError("no sitemap.xml with <lastmod> dates found")
    pages = []
    for loc, mod in re.findall(r"<url>\s*<loc>([^<]+)</loc>(?:.*?<lastmod>([^<]+)</lastmod>)?", xml, re.S):
        if not mod:
            continue
        try:
            d = datetime.fromisoformat(mod.strip().replace("Z", "+00:00"))
        except ValueError:
            continue
        d = d if d.tzinfo else d.replace(tzinfo=timezone.utc)
        age = max(0, (now - d).days)
        pages.append({"path": loc.strip(), "title": loc.strip().rstrip("/").rsplit("/", 1)[-1] or loc,
                      "last_touched": d.date().isoformat(), "age_days": age, "older_than_history": False,
                      "status": "fresh" if age < 90 else "aging" if age < stale_days else "stale",
                      "ancient": age >= 730, "relevant_since": 0, "product_since": 0, "last_commit": "", "evidence": []})
    if not pages:
        raise RuntimeError("the sitemap has no <lastmod> dates")
    pages.sort(key=lambda p: -p["age_days"])
    host = re.sub(r"^https?://", "", base)
    stale = [p for p in pages if p["status"] == "stale"]
    cards = [{"kind": "refresh", "priority": 1 if p["ancient"] else 3, "title": f"Refresh {p['path']}",
              "why": f"Last updated {p['last_touched']}, {p['age_days']} days ago. The sitemap gives no product history, so this is age only.",
              "action": "Re-read the page, then update or retire it.", "evidence": []} for p in stale[:8]]
    cards.append({"kind": "automate", "priority": 3, "title": "Add the source repo for a full audit",
                  "why": "With the repo, the audit can tell stale from quiet and list features with no docs.",
                  "action": f"firstrun audit owner/repo", "evidence": []})
    return {"v": 1, "id": f"audit-{now.strftime('%Y%m%d-%H%M%S')}-{re.sub(r'[^a-z0-9]+', '-', host.lower()).strip('-')}",
            "repo": host, "url": base, "generated_at": now.isoformat(timespec="seconds"), "stale_days": stale_days,
            "mode": "sitemap", "history": {"commits": 0, "since": "", "capped": False},
            "summary": {**_summary(pages), "features": 0, "uncovered": 0, "cards": len(cards)},
            "pages": pages[:PAGES_MAX], "release": {"name": "", "previous": "", "date": "", "commits": 0},
            "features": [], "cards": cards, "drafts": {"release_notes": "", "highlights": []}, "jev": False}


# ----------------------------------------------------------------------------- output

def to_markdown(a: dict) -> str:
    s = a["summary"]
    L = [f"# Docs audit: {a['repo']}", "",
         f"{s['pages']} pages. {s['stale']} stale, {s['quiet']} quiet, {s['aging']} aging, {s['fresh']} fresh. "
         f"Median age {s['median_age_days']} days. Oldest {s['oldest_days']} days.", "",
         "## Oldest Pages", ""]
    for p in a["pages"][:15]:
        L.append(f"- `{p['path']}`: {p['last_touched'] or 'older than history'} ({p['age_days']} days, {p['status']})")
    L += ["", "## Proposal Cards", ""]
    for c in a["cards"]:
        L += [f"**{c['kind']}: {c['title']}**", f"{c['why']} {c['action']}", ""]
    if a["drafts"]["release_notes"]:
        L += ["## Release Notes Draft", "", a["drafts"]["release_notes"]]
    return "\n".join(L).rstrip() + "\n"


def save(a: dict, out_dir: Path) -> Path:
    out_dir.mkdir(parents=True, exist_ok=True)
    (out_dir / "audit.json").write_text(json.dumps(a, indent=1, ensure_ascii=False), encoding="utf-8")
    (out_dir / "audit.md").write_text(to_markdown(a), encoding="utf-8")
    return out_dir / "audit.md"


def find_audit_site(start: Path | None = None) -> Path | None:
    """docs/audits of the firstrun checkout, found the same way as docs/runs."""
    env = os.environ.get("FIRSTRUN_SITE_DIR")
    if env:
        p = Path(env).parent / "audits"
        return p if p.is_dir() else None
    here = (start or Path.cwd()).resolve()
    for base in [here, *here.parents]:
        cand = base / "docs" / "audits"
        if (cand / "index.json").exists():
            return cand
    return None


def publish(a: dict, site: Path) -> Path:
    """Write the audit JSON to the site folder and upsert one row in index.json."""
    site.mkdir(parents=True, exist_ok=True)
    out = site / f"{a['id']}.json"
    out.write_text(json.dumps(a, separators=(",", ":"), ensure_ascii=False), encoding="utf-8")
    idx = site / "index.json"
    try:
        doc = json.loads(idx.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        doc = {}
    s = a["summary"]
    row = {"id": a["id"], "repo": a["repo"], "url": a["url"], "ts": a["generated_at"], "mode": a.get("mode", "repo"),
           "pages": s["pages"], "stale": s["stale"], "quiet": s["quiet"], "oldest_days": s["oldest_days"],
           "median_age_days": s["median_age_days"], "features": s["features"], "uncovered": s["uncovered"],
           "cards": s["cards"], "release": a["release"]["name"]}
    # One current audit per repo: a newer audit replaces the older row and its file.
    key = (a["repo"], a.get("docs_repo", ""))
    rows = []
    for r in doc.get("audits", []):
        if r.get("id") != a["id"] and (r.get("repo"), r.get("docs_repo", "")) == key:
            (site / f"{r['id']}.json").unlink(missing_ok=True)
        elif r.get("id") != a["id"]:
            rows.append(r)
    row["docs_repo"] = a.get("docs_repo", "")
    rows.append(row)
    rows.sort(key=lambda r: r["ts"], reverse=True)
    idx.write_text(json.dumps({"audits": rows}, indent=1) + "\n", encoding="utf-8")
    return out


def issue(a: dict) -> dict:
    """A GitHub issue for the docs team: one checkbox per card, evidence linked, drafts folded."""
    s = a["summary"]
    url = a.get("url") or ""
    L = [f"FirstRun audited the docs of {a['repo']} on {a['generated_at'][:10]}.", "",
         f"- {s['pages']} pages: {s['stale']} stale, {s['quiet']} quiet, {s['aging']} aging, {s['fresh']} fresh.",
         f"- Oldest page: {s['oldest_days']} days. Median: {s['median_age_days']} days.",
         f"- {s['uncovered']} of {s['features']} user-facing features from the last {FEATURE_WINDOW_DAYS} days have no docs page that names them.",
         "", "## Proposed Work", ""]
    for c in a["cards"]:
        if c["kind"] == "quickstart":
            continue
        L.append(f"- [ ] **{c['title']}**. {c['why']}")
        for e in c.get("evidence", [])[:3]:
            ref = f"#{e['pr']}" if e.get("pr") else (f"{url}/commit/{e['sha']}" if url else e["sha"])
            L.append(f"  - {e['date']}: {e['subject']} ({ref})")
    notes = a["drafts"].get("release_notes") or ""
    if notes:
        L += ["", "<details><summary>Release notes draft</summary>", "", notes, "</details>"]
    L += ["", "Stale means product commits on the page's topic landed after its last edit. "
          "Quiet pages are old but nothing changed under them.",
          "", "_Generated by [FirstRun](https://github.com/HighnessAtharva/firstrun) `firstrun audit`._"]
    title = f"Docs audit: {s['stale']} stale pages, {s['uncovered']} features with no docs"
    body = "\n".join(L)
    repo = a["repo"] if "/" in a["repo"] and url else ""
    cmd = f"gh issue create --repo {repo} --title \"{title}\" --body-file issue.md" if repo else ""
    return {"repo": repo, "title": title, "body": body, "commands": [cmd] if cmd else []}
