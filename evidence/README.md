# Evidence

Every claim in the README has a file here or a public link. Nothing in this folder holds a key.

| Claim | Proof |
|---|---|
| Each run is one neatlogs trace, and v2 beat v1 on the same 4 targets | [neatlogs.md](neatlogs.md), [before_after_traces.json](before_after_traces.json), [neatlogs_runs.json](neatlogs_runs.json) |
| A failed step was recovered and verified in a fresh container | [trace-recovered-entire-v2.md](trace-recovered-entire-v2.md) |
| neatlogs found the agent's own bug, and the fix came over MCP | [neatlogs-investigation.md](neatlogs-investigation.md), commit `3ca6f11` |
| Every commit carries its Entire session, and Trails reviewed every layer | [entire.md](entire.md) |
| The build agents used the Entire graph | [graph.ndjson](graph.ndjson), [entire.json](entire.json) |
| The Entire judge ranks the repo with no excluded work | [jury-selftest.txt](jury-selftest.txt) |
| FirstRun found real docs bugs and opened upstream PRs | [dbt #10149](https://github.com/dbt-labs/docs.getdbt.com/pull/10149), [dbt #10150](https://github.com/dbt-labs/docs.getdbt.com/pull/10150), [entireio/cli #2724](https://github.com/entireio/cli/pull/2724), [accuknox/help #671](https://github.com/accuknox/help/pull/671) |
| The jafgen release that broke the dbt guide | [comment on dbt #10149](https://github.com/dbt-labs/docs.getdbt.com/pull/10149#issuecomment-6096827074) |
| Cost per run comes from neatlogs | [../business/BUSINESS_PLAN.md](../business/BUSINESS_PLAN.md), [../business/inputs.json](../business/inputs.json) |

Refresh the generated files with `python scripts/collect_evidence.py`.
