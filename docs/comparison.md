# FirstRun Compared With the Alternatives

| Feature | FirstRun | Claude Code | GitHub Actions | GitHub Agents | Custom workflow |
|---|---|---|---|---|---|
| Runs the quickstart as a new developer | Yes. Every step runs in a fresh Docker container | Runs on your machine unless you set up a sandbox [FILL: sandbox setup] | Yes. A fresh runner per job, but you script each step | [FILL: execution environment] | Depends on the build [FILL: environment] |
| Plans steps from a docs URL | Yes. The planner writes one step per command | Yes, when you prompt it | No. You write each step | [FILL: input it accepts] | You write the parser |
| Adapts when a step fails | Yes. It classifies the failure, patches, and retries up to 3 times per step | Yes, inside one session | No. The job fails and stops | [FILL: retry behavior] | Only what you code |
| Proves the fix | Yes. A second clean container must pass the whole quickstart | Only if you ask | Only if you script it | [FILL: verification step] | Only if you code it |
| Telemetry per run | Yes. neatlogs spans for planner, executor and verifier. Measured cost of $0.02 per run | [FILL: telemetry setup] | Logs and run history. No agent traces | [FILL: telemetry] | You build it |
| Opens the docs PR | Yes, after you approve once | Yes, when you ask | Only if you script it | [FILL: PR behavior] | Only if you code it |
| Ease of use | Paste a docs URL, then paste the prompt into your coding agent | One prompt, no failure classes | A YAML file per quickstart | [FILL: setup steps] | Highest effort |
| Proof in public repos | 4 upstream PRs, all open: dbt-labs/docs.getdbt.com#10149 and #10150, entireio/cli#2724, accuknox/help#671 | [FILL: examples] | [FILL: examples] | [FILL: examples] | [FILL: examples] |

FirstRun reads a docs quickstart and runs every step in a clean container, the way a new developer would. It stops at the first failure and classifies it. It tries a fix up to 3 times, then proves the fix with a second clean run. It asks once before it opens a PR.

FirstRun opened 4 upstream docs PRs, and all are open today. The dbt DuckDB quickstart had a broken `jafgen` command (#10149) and no stated Python version (#10150). The Entire CLI installer put `entire` on a path that a clean shell lacks (entireio/cli#2724). The AccuKnox `knoxctl` page named 0.9.0 as the latest release while its installer fetched 0.9.58, and its APT steps assume `curl`, `gnupg` and `sudo` (accuknox/help#671). MkDocs and Dagster passed with no docs change, so a run also shows when docs hold up.

Every run is a neatlogs trace, so a bad run has a readable cause. A docs bug surfaces in a run instead of in a reader who leaves without filing an issue. [FILL: merge status after the maintainers respond]
