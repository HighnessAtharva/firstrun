# neatHack Build Log: FirstRun

## Project

- **Name:** FirstRun
- **Purpose:** FirstRun runs your quickstart in a clean container, finds the first step that breaks, and proves the fix with a second clean run.
- **Problem:** Quickstarts break when a package is renamed, a flag is removed or a version moves. Nobody on the team gets an alert. The first person who finds the break is a new user, and most new users leave.

## Team

- Atharva Shah ([@HighnessAtharva](https://github.com/HighnessAtharva)), solo.

## Stack

| Part | Tool |
|---|---|
| Language | Python 3.11 |
| Agent | Claude Agent SDK, model `claude-sonnet-5-5` at medium effort, auth through `CLAUDE_CODE_OAUTH_TOKEN` |
| Tracing | neatlogs Python SDK 1.4.26, neatlogs CLI 0.2.0 |
| Sandbox | Docker Engine 29.8.2 in WSL Ubuntu 22.04, one fresh container per run |
| Docs reader | Firecrawl CLI 1.25.3 |
| Failure classifier | Jev (TypeSafe System One) |
| Session capture | Entire CLI 0.11.4: Checkpoints, Graph, Brain, Trails |
| Business plan | cfo.ai |

## Planning Happened Before the Event

Planning and tool tests happened before the event in a private repo. No FirstRun code was written before kickoff (Sat 2026-10-10, 12:30 PM IST).

## Build Log

### 2026-10-10 (Saturday)

- **12:30 to 13:10 IST.** Created the public repo, ran `entire enable --agent claude-code --search-skill --agent-help-skill` before commit 1, and pushed the Entire config, 6 Trail runners, and the Graph and Brain agent instructions.
- **13:20 IST.** Preflight passed: 4 keys present (lengths only checked), Docker 29.8.2 in WSL, `gh`, Firecrawl 1.25.3, Entire 0.11.4, the venv on Python 3.11. `entire doctor` reports no problems.
- **13:30 IST.** Scaffold: `pyproject.toml`, `src/firstrun/config.py` (the only file that names a model), `src/firstrun/tracing.py`.
  - `python -m neatlogs doctor --probe` passed 8 of 8 checks, including `TRACE_VISIBLE` and `TRACE_FINALIZED`.
  - The first FirstRun trace, `firstrun.hello`, is trace `fdcab847f3129a251c6ae45f00c76a1c`. It is finalized with 2 spans and tag `hello`, and the neatlogs CLI read it back.

Entire state at the scaffold commit, run by the build agent:

```text
$ entire status
● Enabled · branch main
  Agents · Claude Code
  Checkpoints sync to: origin
1 session

$ entire checkpoint list
  branch       main
  checkpoints  0
No checkpoints found on this branch.
```

The checkpoint count is 0 because the scaffold commit is the first commit made inside an agent session. Later entries record the count after it.

## Demo

Pending. The 60-second demo shows a red step, the agent's reason, a green verified run, and the drafted PR, then one click into the neatlogs trace.

## Known Limitations and Next Steps

- The Entire Brain watcher does not run on Windows, so Brain runs with `--no-daemon` and is refreshed by hand.

## Submission

Confirmed requirements from https://neatlogs.com/hackathon:

- [ ] Uses neatlogs, Entire and cfo.ai, with a clear role for each.
- [ ] Demo video of 3 minutes or less covering all three tools.
- [ ] Public repo with setup and run instructions.
- [ ] Entire checkpoint link plus its ID.
- [ ] cfo.ai business plan with pricing, costs, revenue and runway.
- [ ] Quote post on X between 7:00 and 11:55 PM IST on Mon 2026-10-12.
