"""Track T2. `firstrun run <url>`, `--targets`, `--resume`, and `firstrun report`."""

from __future__ import annotations

import json
import os
import re
import sys
from pathlib import Path

import click

from firstrun import config
from firstrun.models import RunState, RunStatus


def _recover_fn(budget=None):
    """Layer 2 recovery: classify, ask once, search, patch."""
    from functools import partial

    from firstrun.recovery import recover

    return partial(recover, budget=budget) if budget else recover


def _verify():
    """Model-free re-run of the patched runbook in a brand-new container."""
    from firstrun.verify import verify

    from firstrun import state as state_io

    return lambda runbook, state: verify(runbook, state.patches, pins=state_io.load_pins(state.run_id))

def _elapsed_s(state: RunState) -> float:
    """Wall time of a run from its ISO timestamps. 0 when either is missing."""
    from datetime import datetime

    try:
        return (datetime.fromisoformat(state.finished_at) - datetime.fromisoformat(state.started_at)).total_seconds()
    except (TypeError, ValueError):
        return 0.0


def _first_error_line(state: RunState) -> str:
    for r in reversed(state.results):
        if not r.passed:
            for text in (r.stderr, r.stdout):
                lines = [ln.strip() for ln in text.splitlines() if ln.strip()]
                if lines:
                    return re.sub(r"^/tmp/\.fr_step\.sh: line \d+: ", "", lines[-1])[:120]
            return "timed out" if r.timed_out else f"exit {r.exit_code}"
    return state.stop_reason


def _summary(state: RunState, commands: dict[int, str]) -> list[str]:
    from firstrun.report import reported_failed_step

    total = len(commands)
    passed = sum(1 for s in state.step_status.values() if s.value == "passed")
    fid = reported_failed_step(state)
    if state.status == RunStatus.FAILED and fid is not None:
        return [f"✗ step {fid}/{total}  {commands.get(fid, '')}  ->  {_first_error_line(state)}"]
    if state.status == RunStatus.FAILED and state.stop_reason:
        return [f"✗ {state.stop_reason}"]
    secs = state.time_to_first_success_s or 0
    mark = "✓" if state.status != RunStatus.FAILED else "✗"
    return [f"{mark} {state.status.value} {passed}/{total} steps, {secs:.0f} s, ${state.usage.cost_usd:.2f}"]


# A run that stops for one of these reasons never started a container. The exit code is 2, not 1.
EARLY_STOPS = ("no runnable steps", "out of scope", "docs unreachable", "planner failed", "model auth failed",
               "docker unavailable")


def exit_code(state: RunState) -> int:
    if state.status != RunStatus.FAILED:
        return 0
    return 2 if state.stop_reason.startswith(EARLY_STOPS) else 1


DOCKER_FIX = "Docker is not running in WSL. Start it: wsl -d Ubuntu-22.04 sudo service docker start"
AUTH_FIX = "Claude auth is missing or expired. Add CLAUDE_CODE_OAUTH_TOKEN to your .env (run: claude setup-token)"


def friendly(reason: str) -> str:
    """One sentence plus the fix for a setup failure. Any other reason passes through."""
    low = reason.lower()
    if low.startswith("docker unavailable"):
        return DOCKER_FIX
    if low.startswith("model auth failed"):
        return AUTH_FIX
    return reason


def _setup_exit(message: str):
    click.echo(f"✗ {message}")
    sys.exit(2)


def _quiet_logs() -> None:
    """neatlogs logs at INFO. Show that only when FIRSTRUN_DEBUG=1."""
    import logging

    if os.environ.get("FIRSTRUN_DEBUG") == "1":
        return
    for name in ("neatlogs", "opentelemetry"):
        logging.getLogger(name).setLevel(logging.WARNING)


def _early_stop(url: str, run_id: str, reason: str) -> RunState:
    """Write state.json and report.md for a run that could not start. No container is touched."""
    from datetime import datetime, timezone

    from firstrun import report, state as state_io
    from firstrun.models import Runbook

    now = datetime.now(timezone.utc).isoformat(timespec="seconds")
    state = RunState(run_id=run_id, source_url=url, status=RunStatus.FAILED, stop_reason=reason,
                     started_at=now, finished_at=now)
    runbook = Runbook(source_url=url, steps=[])
    state_io.save_runbook(run_id, runbook)
    state_io.save_state(state)
    report.write_report(state, runbook)
    click.echo(f"✗ {friendly(reason)}")
    click.echo(f"report: {state_io.run_dir(run_id) / 'report.md'}")
    return state


def _echo_share(run_dir) -> None:
    try:
        from firstrun import share

        click.echo(f"share: {share.link_for_run(run_dir)[0]}")
    except Exception:  # noqa: BLE001 - a share failure never breaks a run
        pass
    try:
        from firstrun import publish

        out = publish.publish_run(run_dir)
        if out:
            click.echo(f"site log: {out} (commit docs/runs to show it on the site)")
    except Exception:  # noqa: BLE001 - a publish failure never breaks a run
        pass


def _run_one(url: str, tags: list[str], resume: str | None, verify: bool, recover: bool = True,
             budget=None) -> RunState:
    import neatlogs

    from firstrun import executor, patch, planner, state as state_io
    from firstrun.report import reported_failed_step
    from firstrun.tracing import init_tracing, mark_error, set_io

    init_tracing(tags)
    _quiet_logs()
    run_id = resume or state_io.new_run_id(url)
    source = state_io.load_runbook(resume).source_url if resume else url
    attrs = {
        "target": state_io.target_name(source),
        "run_id": run_id,
        "variant": tags[0] if tags else "dev",
        "tags": list(tags),
    }
    planner.LAST_USAGE.clear()
    click.echo(f"target: {attrs['target']}")
    # One trace per run: reading the docs, planning, every step and verification.
    with neatlogs.trace("firstrun.run", kind="WORKFLOW", **attrs) as root:
        set_io(root, input={"url": source, "run_id": run_id, "resume": bool(resume), "tags": list(tags)})
        try:
            runbook = state_io.load_runbook(resume) if resume else planner.plan(url)
        except planner.PlanError as exc:
            neatlogs.log("run stopped before step 1: {why}", level="error", why=exc.reason)
            set_io(root, output={"status": "failed", "stop_reason": exc.reason})
            mark_error(root, exc.reason)
            return _early_stop(url, run_id, exc.reason)
        final = executor.run(
            runbook, run_id=run_id, resume=bool(resume), tags=tags,
            recover=_recover_fn(budget) if recover else None,
            verify=_verify() if verify else None,
            budget=budget,
            trace=False,
        )
        set_io(root, output={
            "status": final.status.value, "stop_reason": final.stop_reason,
            "steps": len(runbook.steps), "patches": len(final.patches),
            "first_failed_step": final.first_failed_step,
            "reported_failed_step": reported_failed_step(final),
            "time_to_first_success_s": final.time_to_first_success_s,
        })
        if final.status not in (RunStatus.PASSED, RunStatus.VERIFIED):
            mark_error(root, f"{final.status.value}: {final.stop_reason}"[:300])
    if planner.LAST_USAGE:
        final.usage.input_tokens += int(planner.LAST_USAGE.get("input_tokens", 0))
        final.usage.output_tokens += int(planner.LAST_USAGE.get("output_tokens", 0))
        final.usage.cost_usd += float(planner.LAST_USAGE.get("cost_usd", 0.0))
    state_io.save_state(final)
    run_dir = state_io.run_dir(final.run_id)
    from firstrun import report

    report.write_report(final, runbook)
    written = patch.write_outputs(run_dir, final, runbook)
    commands = {s.id: s.command for s in runbook.steps}
    lines = _summary(final, commands)
    for line in lines:
        click.echo("✗ " + friendly(line[2:]) if line.startswith("✗ ") else line)
    if not lines[0].startswith("✓") and final.status == RunStatus.FAILED:
        click.echo(f"ran {_elapsed_s(final):.0f} s, ${final.usage.cost_usd:.2f} list price")
    click.echo(f"report: {run_dir / 'report.md'}")
    for path in written:
        click.echo(f"wrote {path}")
    _echo_share(run_dir)
    return final

class _UrlGroup(click.Group):
    """`firstrun <url>` and `firstrun ./path` mean `firstrun run <url>`."""

    def parse_args(self, ctx, args):
        if args and args[0] not in self.commands and args[0] not in ("--help", "-h"):
            args = ["run", *args]
        return super().parse_args(ctx, args)


@click.group(cls=_UrlGroup)
def cli() -> None:
    """FirstRun: run a quickstart in a fresh container and find the step that breaks."""
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(encoding="utf-8")


@cli.command("run")
@click.argument("url", required=False)
@click.option("--targets", type=click.Path(exists=True, dir_okay=False), help="File with one URL per line.")
@click.option("--resume", "resume_id", help="Resume the run with this id.")
@click.option("--tag", "tags", multiple=True, help="Trace tag. The first one is the variant.")
@click.option("--offline", is_flag=True, help="Plan without a model.")
@click.option("--no-verify", is_flag=True, help="Skip the verification re-run.")
@click.option("--no-recover", is_flag=True, help="Layer 1 only: stop at the first failed step.")
@click.option("--fresh", is_flag=True, help="Ignore a cached result and run again.")
@click.option("--tier", help="Cap spend per run at this plan tier's cap from business/unit_economics.json.")
def run_cmd(url, targets, resume_id, tags, offline, no_verify, no_recover, fresh, tier) -> None:
    if offline:
        os.environ["FIRSTRUN_OFFLINE"] = "1"
    if not (url or targets or resume_id):
        raise click.UsageError("give a URL, --targets FILE or --resume RUN_ID")
    budget = None
    if tier:
        from firstrun import econ

        try:
            budget = econ.budget_for_tier(tier)
        except econ.EconError as exc:
            raise click.ClickException(str(exc))
        click.echo(f"tier: {tier}, cost cap ${budget.cost_usd_per_run:.4f} per run")
    urls: list[str] = []
    if url:
        urls.append(url)
    if targets:
        for line in Path(targets).read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if line and not line.startswith("#"):
                urls.append(line)
    from firstrun import state as state_io
    from firstrun.tracing import close_tracing

    config.load_env()
    if not fresh and not resume_id:
        from firstrun import cache

        todo = []
        for u in urls:
            hit = cache.find_recent(u)
            if hit:
                click.echo(cache.describe(hit))
                click.echo(f"report: {state_io.run_dir(hit) / 'report.md'}")
                _echo_share(state_io.run_dir(hit))
            else:
                todo.append(u)
        urls = todo
        if not urls:
            sys.exit(0)
    if not offline and not resume_id and not os.environ.get("CLAUDE_CODE_OAUTH_TOKEN"):
        _setup_exit(AUTH_FIX)
    if resume_id and not (state_io.run_dir(resume_id) / "state.json").exists():
        raise click.ClickException(f"unknown run id: {resume_id}. Nothing to resume, no run was started.")
    worst = 0
    try:
        if resume_id:
            final = _run_one("", list(tags), resume_id, not no_verify, not no_recover, budget)
            worst = exit_code(final)
        for u in urls:
            final = _run_one(u, list(tags), None, not no_verify, not no_recover, budget)
            worst = max(worst, exit_code(final))
    except Exception as exc:  # noqa: BLE001 - setup failures get one sentence, not a traceback
        from firstrun import llm, planner
        from firstrun.sandbox import DockerUnavailable

        if isinstance(exc, DockerUnavailable):
            _setup_exit(DOCKER_FIX)
        if isinstance(exc, llm.ModelAuthError):
            _setup_exit(AUTH_FIX)
        if isinstance(exc, planner.PlanError):
            _setup_exit(friendly(exc.reason))
        raise
    finally:
        close_tracing()
    sys.exit(worst)


@cli.command("report")
@click.option("--html", "html", is_flag=True, help="Also write an HTML report.")
def report_cmd(html) -> None:
    from firstrun import report

    click.echo(report.summary_table(config.RUNS_DIR))
    if html:
        try:
            from firstrun import report_html
        except ImportError:
            raise click.ClickException("firstrun.report_html is not built yet")
        out = Path("report") / "index.html"
        out.parent.mkdir(exist_ok=True)
        extras = report_html.load_evidence(Path("evidence"), config.RUNS_DIR)
        report_html.write_html(config.RUNS_DIR, out, extras)
        click.echo(f"html: {out}")


@cli.command("share")
@click.argument("run_id", required=False)
def share_cmd(run_id) -> None:
    """Print a share link for a run (default: the newest run)."""
    from firstrun import share, state as state_io

    if not run_id:
        dirs = sorted(d.name for d in Path(config.RUNS_DIR).glob("*") if (d / "state.json").exists())
        if not dirs:
            raise click.ClickException("no runs found")
        run_id = dirs[-1]
    run_dir = state_io.run_dir(run_id)
    if not (run_dir / "state.json").exists():
        raise click.ClickException(f"unknown run id: {run_id}")
    link, code = share.link_for_run(run_dir)
    click.echo(link)
    click.echo(f"code: {code}")
    click.echo(f"code length: {len(code)}")


@cli.command("audit")
@click.argument("target")
@click.option("--days", "stale_days", default=180, show_default=True, help="A page older than this is stale or quiet.")
@click.option("--no-jev", is_flag=True, help="Sort commits by their subject line only. No model call.")
@click.option("--no-publish", is_flag=True, help="Do not write docs/audits for the site.")
@click.option("--docs-repo", help="A second repo that holds the docs, when they do not live next to the code.")
def audit_cmd(target, stale_days, no_jev, no_publish, docs_repo) -> None:
    """Audit a repo's docs: stale pages, features with no docs, and proposal cards. TARGET is owner/repo, a GitHub URL, a git folder, or a docs site with a sitemap."""
    from firstrun import audit as audit_mod, tracing

    tracing.init_tracing(tags=["audit"])
    try:
        if re.match(r"^(https?://)?[\w.-]+\.[a-z]{2,}(/|$)", target) and "github.com" not in target:
            result = audit_mod.audit_sitemap(target, stale_days)
        else:
            click.echo(f"auditing {target}: cloning history, no checkout")
            result = audit_mod.audit(target, stale_days, use_jev=not no_jev, docs_repo=docs_repo)
    except (RuntimeError, ValueError) as e:
        tracing.close_tracing()
        raise click.ClickException(str(e)) from e
    out_dir = Path(config.RUNS_DIR) / result["id"]
    md = audit_mod.save(result, out_dir)
    s = result["summary"]
    click.echo(f"{s['pages']} pages: {s['stale']} stale, {s['quiet']} quiet, {s['aging']} aging, {s['fresh']} fresh"
               + (f", {s['unchecked']} unchecked" if s.get("unchecked") else "") + f". Oldest {s['oldest_days']} days.")
    click.echo(f"{s['features']} recent features, {s['uncovered']} with no docs. {s['cards']} proposal cards.")
    click.echo(f"report: {md}")
    click.echo(f"issue: firstrun audit-issue {result['id']}")
    if not no_publish:
        site = audit_mod.find_audit_site()
        if site:
            click.echo(f"site log: {audit_mod.publish(result, site)} (commit docs/audits to show it on the site)")
    tracing.close_tracing()


@cli.command("audit-issue")
@click.argument("audit_id", required=False)
@click.option("--json", "as_json", is_flag=True, help="Print repo, title, body and commands as JSON.")
def audit_issue_cmd(audit_id, as_json) -> None:
    """Write issue.md for the docs team from an audit and print the gh command. Opens nothing."""
    from firstrun import audit as audit_mod

    dirs = sorted(d for d in Path(config.RUNS_DIR).glob("audit-*") if (d / "audit.json").exists())
    if audit_id:
        dirs = [d for d in dirs if d.name == audit_id]
    if not dirs:
        raise click.ClickException("no audit found. Run firstrun audit owner/repo first.")
    d = dirs[-1]
    data = audit_mod.issue(json.loads((d / "audit.json").read_text(encoding="utf-8")))
    (d / "issue.md").write_text(data["body"], encoding="utf-8")
    data["body_file"] = str(d / "issue.md")
    if as_json:
        click.echo(json.dumps(data, indent=1))
        return
    click.echo(f"title: {data['title']}")
    click.echo(f"body: {d / 'issue.md'}")
    for c in data["commands"]:
        click.echo(f"run from {d}: {c}")


@cli.command("publish")
@click.argument("run_id", required=False)
@click.option("--all", "everything", is_flag=True, help="Publish every run folder, not only the newest.")
def publish_cmd(run_id, everything) -> None:
    """Write a run to docs/runs so the public site lists it. Run it inside the firstrun checkout."""
    from firstrun import publish, state as state_io

    site = publish.find_site_dir()
    if site is None:
        raise click.ClickException("docs/runs not found. Run this inside the firstrun checkout or set FIRSTRUN_SITE_DIR.")
    if everything:
        click.echo(f"published {publish.publish_all(config.RUNS_DIR, site)} runs to {site}")
        return
    if not run_id:
        dirs = sorted(d.name for d in Path(config.RUNS_DIR).glob("*") if (d / "state.json").exists())
        if not dirs:
            raise click.ClickException("no runs found")
        run_id = dirs[-1]
    run_dir = state_io.run_dir(run_id)
    if not (run_dir / "state.json").exists():
        raise click.ClickException(f"unknown run id: {run_id}")
    click.echo(f"published: {publish.publish_run(run_dir, site)}")


@cli.command("bisect")
@click.argument("run_id", required=False)
@click.option("--package", required=True, help="PyPI package whose releases to search.")
@click.option("--step", "step_id", type=int, help="Step to test (default: the run's failed step).")
@click.option("--max-probes", default=8, show_default=True, type=int, help="Container probes to spend.")
def bisect_cmd(run_id, package, step_id, max_probes) -> None:
    """Find the release of PACKAGE that broke a step. Replays stored commands, no model call."""
    from firstrun import bisect, state as state_io
    from firstrun.sandbox import DockerUnavailable
    from firstrun.tracing import close_tracing, init_tracing

    if not run_id:
        dirs = sorted(d.name for d in Path(config.RUNS_DIR).glob("*") if (d / "state.json").exists())
        if not dirs:
            raise click.ClickException("no runs found")
        run_id = dirs[-1]
    if not (state_io.run_dir(run_id) / "state.json").exists():
        raise click.ClickException(f"unknown run id: {run_id}")
    init_tracing(["bisect"])
    _quiet_logs()

    def show(entry: dict) -> None:
        mark = "✓" if entry["passed"] else "✗"
        line = f"{mark} {entry['version']:<10}{entry['date']}"
        if not entry["passed"] and entry["error"]:
            line += f"  {entry['error']}"
        click.echo(line)

    try:
        doc = bisect.run(run_id, package, step_id, max_probes, on_probe=show)
    except DockerUnavailable:
        _setup_exit(DOCKER_FIX)
    except ValueError as exc:
        raise click.ClickException(str(exc))
    finally:
        close_tracing()
    if doc["first_bad"]:
        click.echo(f"First bad: {package} {doc['first_bad']} ({doc['first_bad_date']}). "
                   f"Last good: {doc['last_good']}. {doc['probes']} probes, $0 model cost.")
    else:
        click.echo(f"{doc['verdict']}. {doc['probes']} probes, $0 model cost.")
    click.echo(f"saved: {bisect.bisect_path(run_id)}")


@cli.command("pr")
@click.argument("run_id", required=False)
@click.option("--json", "as_json", is_flag=True, help="Print repo, path, branch, diff, pr_body and commands as JSON.")
def pr_cmd(run_id, as_json) -> None:
    """Print the steps for your own agent to open a docs PR (default: newest verified run). Opens nothing."""
    from firstrun import pr, state as state_io

    if not run_id:
        found = []
        for d in sorted(Path(config.RUNS_DIR).glob("*")):
            sj = d / "state.json"
            if (d / "patch.diff").exists() and sj.exists() and '"status": "verified"' in sj.read_text(encoding="utf-8"):
                found.append(d.name)
        if not found:
            click.echo("✗ no verified run with a patch.diff found")
            sys.exit(1)
        run_id = found[-1]
    try:
        text = pr.as_json(state_io.run_dir(run_id)) if as_json else pr.plan(state_io.run_dir(run_id))
    except pr.NotReady as exc:
        click.echo(f"✗ {exc}")
        sys.exit(1)
    click.echo(text, nl=as_json)


# --- prereqs (Prerequisite Proof) ---------------------------------------------

@cli.command("prereqs")
@click.argument("run_id", required=False)
@click.option("--no-prove", is_flag=True, help="Derive and print the block only. Start no container.")
@click.option("--rounds", default=2, show_default=True, help="Proof rounds. A failure that names a missing tool adds it.")
def prereqs_cmd(run_id, no_prove, rounds) -> None:
    """Print the Prerequisites a run revealed and prove them in a fresh container (default: newest verified run)."""
    import json

    import neatlogs

    from firstrun import prereqs, state as state_io
    from firstrun.tracing import close_tracing, init_tracing

    if not run_id:
        found = [d.name for d in sorted(Path(config.RUNS_DIR).glob("*"))
                 if (d / "state.json").exists() and '"status": "verified"' in (d / "state.json").read_text(encoding="utf-8")]
        if not found:
            raise click.ClickException("no verified run found")
        run_id = found[-1]
    if not (state_io.run_dir(run_id) / "state.json").exists():
        raise click.ClickException(f"unknown run id: {run_id}")
    config.load_env()
    init_tracing(["prereqs"])
    _quiet_logs()
    try:
        runbook = state_io.load_runbook(run_id)
        with neatlogs.trace("firstrun.prereqs", kind="WORKFLOW", run_id=run_id, tags=["prereqs"]):
            if no_prove:
                result = prereqs.derive(state_io.load_state(run_id), runbook)
            else:
                result = prereqs.prove(run_id, rounds=rounds)
        derived = {k: v for k, v in result.items() if k != "proof"}
        click.echo(prereqs.to_markdown(derived, runbook.title))
        if no_prove:
            return
        click.echo(prereqs.proof_line(result))
        click.echo(f"wrote {state_io.run_dir(run_id) / 'prereqs.md'}")
    except Exception as exc:  # noqa: BLE001
        from firstrun.sandbox import DockerUnavailable

        if isinstance(exc, DockerUnavailable):
            _setup_exit(DOCKER_FIX)
        raise
    finally:
        close_tracing()


@cli.command("econ")
@click.option("--traces", "traces_file", type=click.Path(exists=True, dir_okay=False),
              help="A saved `neatlogs traces list --json` payload. Default: read neatlogs now.")
@click.option("--since", default="2026-10-10T00:00:00Z", show_default=True, help="Earliest trace to read.")
@click.option("--margin-floor", default=0.70, show_default=True, type=float, help="Gross margin each tier must keep.")
def econ_cmd(traces_file, since, margin_floor) -> None:
    """Measure cost per run from neatlogs, write drivers.csv for cfo.ai and the per-tier cost caps."""
    from firstrun import econ

    if not 0 <= margin_floor < 1:
        raise click.BadParameter("must be at least 0 and below 1", param_hint="--margin-floor")
    config.load_env()
    inputs = json.loads((econ.BUSINESS / "inputs.json").read_text(encoding="utf-8"))
    try:
        raw = Path(traces_file).read_text(encoding="utf-8") if traces_file else econ.fetch_traces(since)
        result = econ.build(raw, inputs, margin_floor)
    except econ.EconError as exc:
        raise click.ClickException(str(exc))
    d = result["drivers"]
    click.echo(f"{d['traces']} runs: mean ${d['cost_mean']:.4f}, p95 ${d['cost_p95']['usd']:.4f}, "
               f"max ${d['cost_max']['usd']:.4f} per run")
    for name, t in result["tiers"].items():
        line = f"{name}: cap ${t['cap_usd_per_run']:.4f} per run, {t['measured_runs_over_cap_pct']}% of runs over it"
        if "margin_at_p95_pct" in t:
            line += f", margin {t['margin_at_mean_pct']}% at mean, {t['margin_at_p95_pct']}% at p95"
        click.echo(line)
    for path in econ.write(result):
        click.echo(f"wrote {path}")


def main() -> None:
    cli()


if __name__ == "__main__":
    main()
