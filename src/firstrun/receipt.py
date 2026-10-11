"""A receipt for one run: the work, its price, the tier caps, the proof it passed, and file hashes.

`firstrun receipt` reads runs/<id>/state.json and business/unit_economics.json, so the price and the
caps on a receipt are the same numbers cfo.ai models. The receipt hash and the evidence hashes let
`firstrun receipt --check` detect an edited receipt or an edited run folder.
"""

from __future__ import annotations

import hashlib
import html
import json
from datetime import datetime, timezone
from pathlib import Path

from firstrun import report
from firstrun.models import RunState, RunStatus, StepStatus

EVIDENCE = ("state.json", "runbook.json", "report.md")
UNHASHED = ("hash", "issued_at")


def _sha(data: bytes) -> str:
    return "sha256:" + hashlib.sha256(data).hexdigest()


def body_hash(receipt: dict) -> str:
    body = {k: v for k, v in receipt.items() if k not in UNHASHED}
    return _sha(json.dumps(body, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode("utf-8"))


def _caps(cost: float, tiers: dict, compute: float, bills: str | None) -> list[dict]:
    rows = []
    for name, t in tiers.items():
        cap = float(t["cap_usd_per_run"])
        rev = t.get("revenue_per_run")
        rows.append({
            "tier": name,
            "bills_this_run": bool(bills) and name.lower() == bills.lower(),
            "cap_usd": cap,
            "used_pct": round(100 * cost / cap, 1) if cap > 0 else None,
            "within_cap": cost <= cap,
            "price_per_run_usd": rev,
            "margin_pct": round(100 * (1 - (cost + compute) / rev), 1) if rev else None,
        })
    return rows


def _proof(state: RunState, steps: int, passed: int) -> dict:
    ok = state.status == RunStatus.VERIFIED
    if ok:
        claim = "A second clean container ran the patched steps with no model calls, and every step passed."
    elif state.status == RunStatus.PASSED and not state.patches:
        claim = "Every step passed on the first run. No fix was needed, so no second run was made."
    else:
        claim = f"The run ended {state.status.value}. Nothing here is verified."
    return {"status": state.status.value, "verified": ok, "steps_passed": passed, "steps_total": steps, "claim": claim}


def build(state: RunState, run_dir: Path, econ: dict, bills: str | None = None, cfo_url: str = "",
          steps_total: int | None = None) -> dict:
    cost = round(state.usage.cost_usd, 4)
    compute = float(econ["drivers"]["compute_per_run"])
    passed = sum(1 for s in state.step_status.values() if s == StepStatus.PASSED)
    steps = steps_total if steps_total is not None else len(state.step_status)
    first = state.first_failed_step
    cls = state.classifications.get(first) if first is not None else None
    evidence = {n: _sha((run_dir / n).read_bytes()) for n in EVIDENCE if (run_dir / n).exists()}
    r = {
        "receipt_id": f"FR-{state.run_id}",
        "issued_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "work": {
            "source_url": state.source_url,
            "run_id": state.run_id,
            "started_at": state.started_at,
            "finished_at": state.finished_at,
            "seconds": round(report._duration(state) or 0, 1),
            "first_failed_step": first,
            "failure_class": cls.top.value if cls else None,
            "classified_by": cls.source if cls else None,
            "patches": [{"step": p.step_id, "was": p.old_command, "now": p.new_command, "reason": p.reason}
                        for p in state.patches],
        },
        "price": {
            "model_cost_usd": cost,
            "input_tokens": state.usage.input_tokens,
            "output_tokens": state.usage.output_tokens,
            "tool_calls": state.usage.tool_calls,
            "compute_per_run_usd": compute,
            "basis": "list price, not billed",
        },
        "caps": _caps(cost, econ["tiers"], compute, bills),
        "proof": _proof(state, steps, passed),
        "audit": {
            "run_id": state.run_id,
            "tags": state.tags,
            "evidence_sha256": evidence,
            "caps_from": f"business/unit_economics.json, generated {econ.get('generated_at', 'unknown')}",
            "margin_floor": econ.get("margin_floor"),
            "cfo_model": cfo_url,
        },
    }
    r["hash"] = body_hash(r)
    return r


def check(receipt_path: Path) -> list[str]:
    """Problems found, empty when the receipt and the evidence files next to it are untouched."""
    r = json.loads(receipt_path.read_text(encoding="utf-8"))
    problems = []
    if r.get("hash") != body_hash(r):
        problems.append("the receipt was edited: its hash does not match its content")
    for name, want in (r.get("audit", {}).get("evidence_sha256") or {}).items():
        f = receipt_path.parent / name
        if not f.exists():
            problems.append(f"{name} is missing")
        elif _sha(f.read_bytes()) != want:
            problems.append(f"{name} changed after the receipt was issued")
    return problems


def _flat(text: str, width: int) -> str:
    """One line: backslash-newlines and newlines folded, long text cut."""
    flat = " ".join(text.replace("\\\n", " ").split())
    return flat if len(flat) <= width else flat[: width - 1].rstrip() + "..."


def _cell(text: str, width: int = 110) -> str:
    """A Markdown table cell: one line, pipes escaped."""
    return _flat(text, width).replace("|", "\\|")


def _usd(v: float | None, places: int = 4) -> str:
    return "n/a" if v is None else f"${v:.{places}f}"


def render_md(r: dict) -> str:
    w, p, pf, a = r["work"], r["price"], r["proof"], r["audit"]
    out = [f"# Receipt {r['receipt_id']}", "",
           f"Issued {r['issued_at']}. Hash `{r['hash']}`.", "",
           "## Work", "",
           f"- Source: {w['source_url']}",
           f"- Run: `{w['run_id']}`, {w['seconds']} s",
           f"- Steps passed: {pf['steps_passed']} of {pf['steps_total']}"]
    if w["first_failed_step"] is not None:
        out.append(f"- First failed step: {w['first_failed_step']}, classed {w['failure_class']} by {w['classified_by']}")
    if w["patches"]:
        out += ["", "| Step | Was | Now | Why |", "|---|---|---|---|"]
        out += [f"| {x['step']} | `{_cell(x['was'])}` | `{_cell(x['now'])}` | {_cell(x['reason'], 160)} |" for x in w["patches"]]
    out += ["", "## Price", "",
            f"Model cost {_usd(p['model_cost_usd'])} ({p['input_tokens']:,} tokens in, {p['output_tokens']:,} out, "
            f"{p['tool_calls']} tool calls), {p['basis']}. Compute adds {_usd(p['compute_per_run_usd'], 5)}.", "",
            "## Cap", "", "| Tier | Cap per run | Used | Within cap | Price per run | Margin on this run |",
            "|---|---|---|---|---|---|"]
    for c in r["caps"]:
        used = "n/a" if c["used_pct"] is None else f"{c['used_pct']}%"
        margin = "n/a" if c["margin_pct"] is None else f"{c['margin_pct']}%"
        name = c["tier"] + (" (bills this run)" if c["bills_this_run"] else "")
        out.append(f"| {name} | {_usd(c['cap_usd'], 5)} | {used} | {'yes' if c['within_cap'] else 'NO'} | "
                   f"{_usd(c['price_per_run_usd'], 5)} | {margin} |")
    out += ["", "## Proof", "", f"**{'Verified' if pf['verified'] else 'Not verified'}.** {pf['claim']}", "",
            "## Audit Trail", "", f"Caps and prices: {a['caps_from']}."]
    if a["cfo_model"]:
        out.append(f"cfo.ai model: {a['cfo_model']}")
    out += ["", "| File | SHA-256 |", "|---|---|"]
    out += [f"| {n} | `{h}` |" for n, h in a["evidence_sha256"].items()]
    out += ["", f"Check it: `firstrun receipt --check runs/{w['run_id']}/receipt.json`", ""]
    return "\n".join(out)


def _shell(title: str, stamp: str, inner: str) -> str:
    """The shared receipt page. `stamp` is the CSS color of the proof stamp."""
    return f"""<!doctype html>
<html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>{html.escape(title)}</title>
<style>
:root{{--ink:#1d1d1f;--mut:#6e6e73;--line:#e5e5ea;--bg:#f5f5f7;--ok:#1a7f37;--no:#c62828;--gold:#b7791f}}
*{{box-sizing:border-box}}body{{margin:0;background:var(--bg);color:var(--ink);font:16px/1.5 -apple-system,BlinkMacSystemFont,"Segoe UI",sans-serif;padding:32px 16px}}
.r{{max-width:760px;margin:0 auto;background:#fff;border:1px solid var(--line);border-radius:20px;padding:32px;box-shadow:0 8px 30px rgba(0,0,0,.06)}}
h1{{font-size:26px;margin:0}}h2{{font-size:13px;letter-spacing:.08em;text-transform:uppercase;color:var(--mut);margin:28px 0 8px;border-top:1px solid var(--line);padding-top:18px}}
.m{{color:var(--mut);font-size:14px;word-break:break-all}}code{{font:13px ui-monospace,Menlo,Consolas,monospace;word-break:break-all}}
table{{width:100%;border-collapse:collapse;font-size:14px}}td,th{{text-align:left;padding:6px 8px;border-bottom:1px solid var(--line);vertical-align:top}}th{{color:var(--mut);font-weight:600}}
.big{{font-size:32px;font-weight:700}}.ok{{color:var(--ok);font-weight:600}}.no{{color:var(--no);font-weight:600}}tr.bill{{background:#fff8e6}}
.stamp{{display:inline-block;margin-top:8px;padding:4px 14px;border:2px solid {stamp};color:{stamp};border-radius:8px;font-weight:700;letter-spacing:.06em;text-transform:uppercase}}
@media(max-width:560px){{.r{{padding:20px}}table{{font-size:13px}}}}
</style></head><body><main class="r">
{inner}</main></body></html>
"""


def render_html(r: dict) -> str:
    e = html.escape
    w, p, pf, a = r["work"], r["price"], r["proof"], r["audit"]
    patches = "".join(
        f"<tr><td>{x['step']}</td><td><code title=\"{e(x['was'])}\">{e(_flat(x['was'], 70))}</code></td><td><code title=\"{e(x['now'])}\">{e(_flat(x['now'], 70))}</code></td><td>{e(_flat(x['reason'], 120))}</td></tr>"
        for x in w["patches"])
    caps = "".join(
        f"<tr class=\"{'bill' if c['bills_this_run'] else ''}\"><td>{e(c['tier'])}</td><td>{_usd(c['cap_usd'], 5)}</td>"
        f"<td>{'n/a' if c['used_pct'] is None else str(c['used_pct']) + '%'}</td>"
        f"<td class=\"{'ok' if c['within_cap'] else 'no'}\">{'within' if c['within_cap'] else 'over'}</td>"
        f"<td>{_usd(c['price_per_run_usd'], 5)}</td><td>{'n/a' if c['margin_pct'] is None else str(c['margin_pct']) + '%'}</td></tr>"
        for c in r["caps"])
    files = "".join(f"<tr><td>{e(n)}</td><td><code>{e(h)}</code></td></tr>" for n, h in a["evidence_sha256"].items())
    cfo = f"<p><a href=\"{e(a['cfo_model'])}\">cfo.ai model behind these caps</a></p>" if a["cfo_model"] else ""
    return _shell(f"Receipt {r['receipt_id']}", "var(--ok)" if pf["verified"] else "var(--no)", f"""<h1>Receipt {e(r['receipt_id'])}</h1>
<p class="m">Issued {e(r['issued_at'])} by FirstRun. Hash <code>{e(r['hash'])}</code></p>
<h2>Work</h2>
<p><a href="{e(w['source_url'])}">{e(w['source_url'])}</a><br>{pf['steps_passed']} of {pf['steps_total']} steps passed in {w['seconds']} s.
{('First failed step ' + str(w['first_failed_step']) + ', classed ' + e(str(w['failure_class'])) + ' by ' + e(str(w['classified_by'])) + '.') if w['first_failed_step'] is not None else ''}</p>
{('<table><tr><th>Step</th><th>Was</th><th>Now</th><th>Why</th></tr>' + patches + '</table>') if patches else ''}
<h2>Price</h2>
<p class="big">{_usd(p['model_cost_usd'])}</p>
<p class="m">{p['input_tokens']:,} tokens in, {p['output_tokens']:,} out, {p['tool_calls']} tool calls. {e(p['basis'])}. Compute adds {_usd(p['compute_per_run_usd'], 5)}.</p>
<h2>Cap</h2>
<table><tr><th>Tier</th><th>Cap per run</th><th>Used</th><th>Result</th><th>Price per run</th><th>Margin</th></tr>{caps}</table>
<h2>Proof</h2>
<span class="stamp">{'Verified' if pf['verified'] else 'Not verified'}</span>
<p>{e(pf['claim'])}</p>
<h2>Audit Trail</h2>
<p class="m">{e(a['caps_from'])}.</p>{cfo}
<table><tr><th>File</th><th>SHA-256</th></tr>{files}</table>
<p class="m">Check it: <code>firstrun receipt --check runs/{e(w['run_id'])}/receipt.json</code></p>
""")


def write(run_dir: Path, receipt: dict, with_html: bool = False) -> list[Path]:
    md, page = (render_audit_md, render_audit_html) if receipt.get("kind") == "audit" else (render_md, render_html)
    out = [run_dir / "receipt.json", run_dir / "receipt.md"]
    out[0].write_text(json.dumps(receipt, indent=1, ensure_ascii=False) + "\n", encoding="utf-8")
    out[1].write_text(md(receipt), encoding="utf-8")
    if with_html:
        out.append(run_dir / "receipt.html")
        out[-1].write_text(page(receipt), encoding="utf-8")
    return out


# ----------------------------------------------------------------------------- audit receipts

AUDIT_EVIDENCE = ("audit.json", "audit.md", "issue.md")


def build_audit(a: dict, audit_dir: Path) -> dict:
    """A receipt for one doc audit. An old audit carries no cost, and the receipt says so."""
    from firstrun import audit as audit_mod

    s, h = a["summary"], a["history"]
    cost = a.get("cost")
    cards = a.get("cards", [])
    cited = sum(1 for c in cards if c.get("evidence"))
    kinds: dict[str, int] = {}
    for c in cards:
        kinds[c["kind"]] = kinds.get(c["kind"], 0) + 1
    evidence = {n: _sha((audit_dir / n).read_bytes()) for n in AUDIT_EVIDENCE if (audit_dir / n).exists()}
    r = {
        "kind": "audit",
        "receipt_id": f"FR-{a['id']}",
        "issued_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "work": {
            "repo": a["repo"], "docs_repo": a.get("docs_repo", ""), "url": a.get("url", ""),
            "audited_at": a["generated_at"], "head": h.get("head", ""),
            "commits_read": h["commits"], "since": h["since"], "history_capped": h["capped"],
            "pages": s["pages"], "fresh": s["fresh"], "aging": s["aging"], "stale": s["stale"], "quiet": s["quiet"],
            "features": s["features"], "uncovered": s["uncovered"], "cards": kinds, "judged_by_jev": bool(a.get("jev")),
        },
        "price": {
            "recorded": cost is not None,
            "jev_calls": (cost or {}).get("jev_calls"),
            "jev_input_tokens": (cost or {}).get("jev_input_tokens"),
            "usd": (cost or {}).get("jev_usd"),
            "basis": (cost or {}).get("basis", "This audit ran before cost tracking, so its cost was not recorded."),
        },
        "limits": {
            "dollar_cap_per_audit": None,
            "jev_stale_pages_max": audit_mod.JEV_STALE_MAX,
            "jev_commit_sorts_max": audit_mod.JEV_MAX,
            "jev_batch_size": audit_mod.JEV_BATCH,
            "history_commits_max": audit_mod.HISTORY_MAX,
            "note": "The plan sets no dollar cap per audit. Jev reads are limited by the counts below.",
        },
        "proof": {
            "cards": len(cards), "cards_citing_evidence": cited,
            "all_cited": bool(cards) and cited == len(cards),
            "claim": f"{cited} of {len(cards)} cards cite commits or pages you can open." + (
                f" The audit read the history up to commit {h['head'][:9]}." if h.get("head")
                else " This audit did not record the commit it read."),
        },
        "audit": {"audit_id": a["id"], "evidence_sha256": evidence, "generated_by": "firstrun audit"},
    }
    r["hash"] = body_hash(r)
    return r


def render_audit_md(r: dict) -> str:
    w, p, lim, pf, a = r["work"], r["price"], r["limits"], r["proof"], r["audit"]
    cost = (f"Jev cost {_usd(p['usd'], 6)} ({p['jev_calls']} calls, {p['jev_input_tokens']:,} input tokens). {p['basis']}"
            if p["recorded"] else p["basis"])
    out = [f"# Receipt {r['receipt_id']}", "",
           f"Issued {r['issued_at']}. Hash `{r['hash']}`.", "",
           "## Work", "",
           f"- Repo: {w['repo']}" + (f", docs in {w['docs_repo']}" if w["docs_repo"] else ""),
           f"- Read {w['commits_read']:,} commits since {w['since']}" + (", capped" if w["history_capped"] else "")
           + (f", up to `{w['head'][:9]}`" if w["head"] else ""),
           f"- Pages: {w['pages']}, {w['stale']} stale, {w['aging']} aging, {w['quiet']} quiet, {w['fresh']} fresh",
           f"- Features: {w['features']}, {w['uncovered']} with no docs",
           "- Cards: " + (", ".join(f"{n} {k}" for k, n in w["cards"].items()) or "none"),
           "", "## Price", "", cost, "",
           "## Limits", "", lim["note"], "",
           f"- Jev reads at most {lim['jev_stale_pages_max']} stale pages, sorts at most {lim['jev_commit_sorts_max']} commits, "
           f"and sends {lim['jev_batch_size']} per call.",
           f"- The audit reads at most {lim['history_commits_max']:,} commits.", "",
           "## Proof", "", f"**{pf['cards_citing_evidence']} of {pf['cards']} cards cited.** {pf['claim']}", "",
           "## Audit Trail", "", "| File | SHA-256 |", "|---|---|"]
    out += [f"| {n} | `{h}` |" for n, h in a["evidence_sha256"].items()]
    out += ["", f"Check it: `firstrun receipt --check runs/{a['audit_id']}/receipt.json`", ""]
    return "\n".join(out)


def render_audit_html(r: dict) -> str:
    e = html.escape
    w, p, lim, pf, a = r["work"], r["price"], r["limits"], r["proof"], r["audit"]
    cards = ", ".join(f"{n} {e(k)}" for k, n in w["cards"].items()) or "none"
    price = (f"<p class=\"big\">{_usd(p['usd'], 6)}</p><p class=\"m\">{p['jev_calls']} Jev calls, "
             f"{p['jev_input_tokens']:,} input tokens. {e(p['basis'])}</p>" if p["recorded"]
             else f"<p class=\"big\">Not recorded</p><p class=\"m\">{e(p['basis'])}</p>")
    files = "".join(f"<tr><td>{e(n)}</td><td><code>{e(h)}</code></td></tr>" for n, h in a["evidence_sha256"].items())
    head = f", up to <code>{e(w['head'][:9])}</code>" if w["head"] else ""
    docs = (", docs in " + e(w["docs_repo"])) if w["docs_repo"] else ""
    capped = ", capped" if w["history_capped"] else ""
    return _shell(f"Receipt {r['receipt_id']}", "var(--ok)" if pf["all_cited"] else "var(--gold)", f"""<h1>Receipt {e(r['receipt_id'])}</h1>
<p class="m">Issued {e(r['issued_at'])} by FirstRun. Hash <code>{e(r['hash'])}</code></p>
<h2>Work</h2>
<p><a href="{e(w['url'])}">{e(w['repo'])}</a>{docs}<br>Read {w['commits_read']:,} commits since {e(w['since'])}{capped}{head}.</p>
<table><tr><th>Pages</th><th>Stale</th><th>Aging</th><th>Quiet</th><th>Fresh</th><th>Features</th><th>No docs</th></tr>
<tr><td>{w['pages']}</td><td>{w['stale']}</td><td>{w['aging']}</td><td>{w['quiet']}</td><td>{w['fresh']}</td><td>{w['features']}</td><td>{w['uncovered']}</td></tr></table>
<p class="m">Cards: {cards}.</p>
<h2>Price</h2>
{price}
<h2>Limits</h2>
<p>{e(lim['note'])}</p>
<p class="m">Jev reads at most {lim['jev_stale_pages_max']} stale pages, sorts at most {lim['jev_commit_sorts_max']} commits, and sends {lim['jev_batch_size']} per call. The audit reads at most {lim['history_commits_max']:,} commits.</p>
<h2>Proof</h2>
<span class="stamp">{pf['cards_citing_evidence']} of {pf['cards']} cards cited</span>
<p>{e(pf['claim'])}</p>
<h2>Audit Trail</h2>
<table><tr><th>File</th><th>SHA-256</th></tr>{files}</table>
<p class="m">Check it: <code>firstrun receipt --check runs/{e(a['audit_id'])}/receipt.json</code></p>
""")
