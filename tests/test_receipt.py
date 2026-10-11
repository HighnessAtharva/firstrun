"""Receipts: price, tier caps, proof wording, and tamper detection. Offline."""

from __future__ import annotations

import json

from firstrun import receipt
from firstrun.models import Patch, RunState, RunStatus, StepStatus, Usage

ECON = {
    "generated_at": "2026-10-11T00:00:00Z",
    "margin_floor": 0.7,
    "drivers": {"compute_per_run": 0.002},
    "tiers": {
        "Free": {"cap_usd_per_run": 0.01},
        "Team": {"cap_usd_per_run": 0.05, "revenue_per_run": 0.2},
    },
}


def _state(status=RunStatus.VERIFIED, cost=0.04, patches=True) -> RunState:
    return RunState(
        run_id="20261011-000000-example", source_url="https://docs.example.com/start", status=status,
        step_status={1: StepStatus.PASSED, 2: StepStatus.PASSED},
        patches=[Patch(step_id=2, old_command="a \\\n| b", new_command="c", reason="x | y")] if patches else [],
        usage=Usage(input_tokens=1000, output_tokens=200, cost_usd=cost),
    )


def _run_dir(tmp_path, state):
    d = tmp_path / state.run_id
    d.mkdir()
    (d / "state.json").write_text(state.model_dump_json(), encoding="utf-8")
    (d / "report.md").write_text("# report\n", encoding="utf-8")
    return d


def test_caps_flag_a_run_over_a_tier(tmp_path):
    s = _state(cost=0.04)
    r = receipt.build(s, _run_dir(tmp_path, s), ECON, bills="team")
    free, team = r["caps"]
    assert not free["within_cap"] and free["margin_pct"] is None
    assert team["within_cap"] and team["bills_this_run"]
    assert team["used_pct"] == 80.0
    assert team["margin_pct"] == round(100 * (1 - (0.04 + 0.002) / 0.2), 1)


def test_proof_only_claims_what_ran(tmp_path):
    s = _state(status=RunStatus.UNVERIFIED)
    r = receipt.build(s, _run_dir(tmp_path, s), ECON)
    assert r["proof"]["verified"] is False and "Nothing here is verified" in r["proof"]["claim"]


def test_a_clean_first_pass_says_no_fix_was_needed(tmp_path):
    s = _state(status=RunStatus.PASSED, patches=False)
    assert "No fix was needed" in receipt.build(s, _run_dir(tmp_path, s), ECON)["proof"]["claim"]


def test_check_detects_an_edited_receipt_and_edited_evidence(tmp_path):
    s = _state()
    d = _run_dir(tmp_path, s)
    path = receipt.write(d, receipt.build(s, d, ECON))[0]
    assert receipt.check(path) == []
    edited = json.loads(path.read_text(encoding="utf-8"))
    edited["price"]["model_cost_usd"] = 0.001
    path.write_text(json.dumps(edited), encoding="utf-8")
    assert "edited" in receipt.check(path)[0]
    path.write_text(json.dumps(json.loads(json.dumps(edited)) | {"price": {**edited["price"], "model_cost_usd": 0.04}}), encoding="utf-8")
    (d / "report.md").write_text("# changed\n", encoding="utf-8")
    assert any("report.md changed" in p for p in receipt.check(path))


def test_markdown_patch_table_stays_one_line_per_row(tmp_path):
    s = _state()
    md = receipt.render_md(receipt.build(s, _run_dir(tmp_path, s), ECON))
    rows = [ln for ln in md.splitlines() if ln.startswith("| 2 |")]
    assert len(rows) == 1 and "\\|" in rows[0]
