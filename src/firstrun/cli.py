"""Track T2. `firstrun run <url>`, `--targets`, `--resume`, and `firstrun report`."""

from __future__ import annotations

import os
import sys
from pathlib import Path

import click

from firstrun import config
from firstrun.models import RunState, RunStatus


def _recover_fn():
    """Layer 2 recovery: classify, ask once, search, patch."""
    from firstrun.recovery import recover

    return recover


def _verify():
    """Model-free re-run of the patched runbook in a brand-new container."""
    from firstrun.verify import verify

    from firstrun import state as state_io

    return lambda runbook, state: verify(runbook, state.patches, pins=state_io.load_pins(state.run_id))

def _first_error_line(state: RunState) -> str:
    for r in reversed(state.results):
        if not r.passed:
            for text in (r.stderr, r.stdout):
                lines = [ln.strip() for ln in text.splitlines() if ln.strip()]
                if lines:
                    return lines[-1][:120]
            return "timed out" if r.timed_out else f"exit {r.exit_code}"
    return state.stop_reason


def _summary(state: RunState, commands: dict[int, str]) -> list[str]:
    total = len(commands)
    passed = sum(1 for s in state.step_status.values() if s.value == "passed")
    if state.status == RunStatus.FAILED and state.first_failed_step is not None:
        fid = state.first_failed_step
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
    click.echo(f"✗ {reason}")
    click.echo(f"run dir: {state_io.run_dir(run_id)}")
    return state


def _run_one(url: str, tags: list[str], resume: str | None, verify: bool, recover: bool = True) -> RunState:
    import neatlogs

    from firstrun import executor, patch, planner, state as state_io
    from firstrun.tracing import init_tracing, mark_error, set_io

    init_tracing(tags)
    run_id = resume or state_io.new_run_id(url)
    source = state_io.load_runbook(resume).source_url if resume else url
    attrs = {
        "target": state_io.target_name(source),
        "run_id": run_id,
        "variant": tags[0] if tags else "dev",
        "tags": list(tags),
    }
    planner.LAST_USAGE.clear()
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
            recover=_recover_fn() if recover else None,
            verify=_verify() if verify else None,
            trace=False,
        )
        set_io(root, output={
            "status": final.status.value, "stop_reason": final.stop_reason,
            "steps": len(runbook.steps), "patches": len(final.patches),
            "first_failed_step": final.first_failed_step,
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
    for line in _summary(final, commands):
        click.echo(line)
    for path in written:
        click.echo(f"wrote {path}")
    click.echo(f"run dir: {run_dir}")
    return final

@click.group()
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
def run_cmd(url, targets, resume_id, tags, offline, no_verify, no_recover) -> None:
    if offline:
        os.environ["FIRSTRUN_OFFLINE"] = "1"
    if not (url or targets or resume_id):
        raise click.UsageError("give a URL, --targets FILE or --resume RUN_ID")
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

    if resume_id and not (state_io.run_dir(resume_id) / "state.json").exists():
        raise click.ClickException(f"unknown run id: {resume_id}. Nothing to resume, no run was started.")
    worst = 0
    try:
        if resume_id:
            final = _run_one("", list(tags), resume_id, not no_verify, not no_recover)
            worst = exit_code(final)
        for u in urls:
            final = _run_one(u, list(tags), None, not no_verify, not no_recover)
            worst = max(worst, exit_code(final))
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
        report_html.write_html(config.RUNS_DIR, out)
        click.echo(f"html: {out}")


def main() -> None:
    cli()


if __name__ == "__main__":
    main()
