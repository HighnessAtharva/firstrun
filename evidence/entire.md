# Entire Evidence

Entire recorded the agent session behind every commit, reviewed every layer on a Trail, mapped the repo for the build agents, and kept the decisions in Brain. Numbers below were read on 2026-10-10 at about 18:45 IST.

## Every Commit Carries the Session That Wrote It

- 87 checkpoint refs are on GitHub (counted 2026-10-11, after the launch merge) under `refs/entire/checkpoints/*`. Check with `git ls-remote origin 'refs/entire/checkpoints/*'`.
- 91 of 129 non-merge commits on main up to `b88bcc9` carry an `Entire-Checkpoint:` trailer, counted with `git log --no-merges` on 2026-10-11. The 38 without are the 4 setup commits before the first agent session and site commits from 2026-10-10 and 2026-10-11. On many of those the Entire commit hook hung and was stopped so the commit could land. Merge commits carry none, because Entire's hook skips merges.
- The neatlogs fix commit shows its whole session, from the MCP calls to the green tests: [checkpoint 01M4JGJ6NTE7YNB9Z0YW5FYVHN](https://entire.io/gh/HighnessAtharva/firstrun/commit/3ca6f118ecb0a8915315eea27b5588dd8a7c6299).
- One checkpoint was lost: Git 2.33 hung the post-commit hook for 206 s on the scaffold commit. Git 2.55 fixed it, and no checkpoint was lost after that.

## Trails Reviewed Every Layer, and the Runners Found 3 Real Bugs

| Trail | Covers | Runner findings |
|---|---|---|
| [3](https://entire.io/gh/HighnessAtharva/firstrun/trails/3) | Layer 1, every commit from the scaffold to the wiring | 1 high, 1 medium, both fixed in e2aacb7 |
| [4](https://entire.io/gh/HighnessAtharva/firstrun/trails/4) | Layer 2: recovery, edge cases, the neatlogs fix | none blocking |
| [5](https://entire.io/gh/HighnessAtharva/firstrun/trails/5) | Layer 3: share codes, replay, agent launcher, cache | none blocking |
| [6](https://entire.io/gh/HighnessAtharva/firstrun/trails/6) | Real-world runs, CI | none blocking |
| [7](https://entire.io/gh/HighnessAtharva/firstrun/trails/7) | Agent hardening from real runs | 1 high, fixed in f0f1517 |
| [8](https://entire.io/gh/HighnessAtharva/firstrun/trails/8) to [12](https://entire.io/gh/HighnessAtharva/firstrun/trails/12) | Bisect, Prerequisite Proof, website, build log, README self-test | merged |

The 3 bugs the runners found:

1. **High:** a `needs_secret` step with its key already in the container retried the same command until the budget ran out.
2. **Medium:** the Docker command defaulted to the author's WSL setup, so FirstRun could not start containers on Linux or macOS.
3. **High:** the `cd` guard from d22eb69 was written and unit-tested but never called by `Container.exec`.

Each finding was resolved with `entire trail finding resolve <id> -m "fixed in <sha>"`.

## The Build Agents Searched the Repo Through the Graph

- `entire graph stats --repo .`: 10 graph calls, about 56,254 tokens saved, graph-first in 1 of 4 sessions. The first session started with grep, and the session noted it and switched.
- The full graph is in [graph.ndjson](graph.ndjson): 96 files and 1,526 symbols at the last Brain refresh.

## Brain Answers Why a Decision Was Made

`entire brain recall "why does recovery stop at 3 attempts"` returns the decision fact recorded during the build: a looping agent is the most common failure the neatlogs judges look for, so recovery stops at 3 attempts, 25 tool calls and $0.50 per run. Brain holds 7 such facts, from the Git version constraint to the one-trace-per-run rule.

## The Jury Self-Test Ranked the Repo With No Excluded Work

The Entire judge plugin, run on a fresh clone with the real start time, scored 3.93 of 5: authenticity 4.5, integrity 5.0, prompting 4.0, CLI awareness 4.5. The full report is [jury-selftest.txt](jury-selftest.txt). The test also found that `entire judge add` fetches only `refs/heads/entire/*`, while the default backend writes `refs/entire/checkpoints/*`. Brain's refresh fetched the refs on its own, so the repo was not dropped.
