# neatlogs Evidence

Every FirstRun run is one `firstrun.run` WORKFLOW trace in neatlogs. Its spans are `read_docs` and `step.<id>` (TOOL), `planner` and `recover.<id>` (AGENT), `classify_failure` (TOOL), and `budget` and `verify` (GUARDRAIL). Bisect adds `firstrun.bisect` with a `probe.<version>` span per release. Prerequisite Proof adds a `prereqs.prove` GUARDRAIL.

## Before and After Traces Measure the Fix From Neatlogs

| Target | v1 trace | v2 trace |
|---|---|---|
| neatlogs Python SDK | `fccdbad9a9c6177b90112911fe485bd6` | `495d510fd6da5546dbc6ab6e52bcee68` |
| Entire install | `10c44df9626c19f5ac801f1c6d84610e` | `5520c5cff5e0ea61f130eced082b20c4` |
| Chroma getting started | `66ec093b00333fa221fade5d2fc5f55f` | `f63d2b842c2257ae8c340f6ce44e3848` |
| OpenAI v0 README (fixture) | `b98b419e286acf436083febdb5217cf9` | `78e538e63a65c5d00d0281effa119567` |

Per-trace spans, tool calls, cost and duration are in [before_after_traces.json](before_after_traces.json). The tag summaries are in [neatlogs_runs.json](neatlogs_runs.json).

## One Failed-and-Recovered Trace, Exported

[trace-recovered-entire-v2.md](trace-recovered-entire-v2.md) is trace `5520c5cff5e0ea61f130eced082b20c4`. Step 1 failed with `curl: command not found`, recovery installed curl in the container, step 2 failed until `~/.local/bin` was on `PATH`, and a fresh container then ran all 4 steps with no model calls. The trace status reads ERROR because a failed step span rolls up to the trace, while the run itself ended `verified`.

## Two Detections, One Investigate, One Fix Over MCP

1. Detection "docs step broke": a regex on TOOL span output, `command not found|No module named|unrecognized arguments|No matching distribution`.
2. Detection "planner invented a step": a regex on the `planner` span output. It flagged the planner spans of the Chroma, Entire and OpenAI v1 runs.
3. Investigate (Deep, workflow `firstrun`) traced the invented steps to the planner prompt: [neatlogs-investigation.md](neatlogs-investigation.md).
4. A Claude Code session read the detection and its trend over the neatlogs MCP server and applied the fix in commit `3ca6f11`.

## Three Alerts and One AI Evaluator Watch Every Run

Created over the neatlogs CLI on 2026-10-10. Each alert passed a dry-run test with email as the channel.

| Rule | Fires when | ID |
|---|---|---|
| firstrun p95 run cost above Scale cap | p95 `cost` is above $0.035 over 1 day, the $0.028 Scale cap plus 25% | `56b3b8be` |
| firstrun docs breakage or failed verification spike | 25 or more "docs step broke" hits, or 2 or more "Verification Error Monitor" hits, in 60 minutes | `74e5d64c` |
| firstrun budget guardrail tripped | each "Budget Limit Exceeded Alert" hit | `acd01964` |

The AI evaluator "report names the real failed step" (`a6aa683e`) is an agent judge with neatlogs MCP access, a $0.10 budget and 12 tool calls. It checks that the reported failed step matches the first failed TOOL span, that the failure class fits the container output, and that every patch has a passing verify run. Ad-hoc runs return `NOT_FOUND_OR_OPERATION_DISABLED`, so it scores through a scheduled evaluation.

## The Integration Check Passed the Organizer's Gates

The organizers' setup prompt ran against this repo. Gates 1, 2, 3 and 5 pass and gate 4 is partial: [docs/neatlogs-integration.md](../docs/neatlogs-integration.md).
