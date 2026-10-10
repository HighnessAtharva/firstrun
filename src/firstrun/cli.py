"""Track T2. `firstrun run <url>`, `--targets`, `--resume`, and `firstrun report`."""

from __future__ import annotations

import os
import sys
from pathlib import Path

import click

from firstrun import config
from firstrun.models import RunState, RunStatus


def _recover_fn():
    """TODO(lead): return firstrun.recovery.recover once T4 lands. None means no recovery."""
    return None


def _verify():
    """TODO(lead): return a callable (runbook, state) -> RunStatus using firstrun.verify.verify."""
    return None


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
    secs = state.time_to_first_success_s or 0
    mark = "✓" if state.status != RunStatus.FAILED else "✗"
    return [f"{mark} {state.status.value} {passed}/{total} steps, {secs:.0f} s, ${state.usage.cost_usd:.2f}"]


def _run_one(url: str, tags: list[str], resume: str | None, verify: bool) -> RunState:
    from firstrun import executor, state as state_io
    from firstrun.tracing import init_tracing

    init_tracing(tags)
    if resume:
        runbook = state_io.load_runbook(resume)
    else:
        from firstrun import planner  # built by another worker, so import late

        runbook = planner.plan(url)
    final = executor.run(runbook, run_id=resume, resume=bool(resume), tags=tags, recover=_recover_fn())
    verifier = _verify() if verify else None
    if verifier is not None and final.status == RunStatus.PASSED:
        final.status = verifier(runbook, final)
        state_io.save_state(final)
    commands = {s.id: s.command for s in runbook.steps}
    for line in _summary(final, commands):
        click.echo(line)
    click.echo(f"run dir: {state_io.run_dir(final.run_id)}")
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
def run_cmd(url, targets, resume_id, tags, offline, no_verify) -> None:
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
    from firstrun.tracing import close_tracing

    worst = 0
    try:
        if resume_id:
            final = _run_one("", list(tags), resume_id, not no_verify)
            worst = 1 if final.status == RunStatus.FAILED else 0
        for u in urls:
            final = _run_one(u, list(tags), None, not no_verify)
            if final.status == RunStatus.FAILED:
                worst = 1
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
        out = Path(config.RUNS_DIR) / "report.html"
        report_html.write_html(config.RUNS_DIR, out)
        click.echo(f"html: {out}")


def main() -> None:
    cli()


if __name__ == "__main__":
    main()
