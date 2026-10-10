# FirstRun Business Plan

FirstRun runs a dev tool's quickstart in a clean container every night, finds the first step that breaks, proves the fix with a second clean run, and drafts the docs PR. The buyer is a DevRel or docs team at a dev-tool company.

Cost per run comes from neatlogs, not from a guess. The measured model cost is $0.02623 per run, and every other number is labeled as an assumption in `business/inputs.json`.

cfo.ai model: <!-- FILL:cfo_share_link -->

cfo.ai spreadsheet: <!-- FILL:cfo_xlsx -->

## Three Tiers Price by Quickstarts Covered

| Tier | Price per month | Quickstarts | Runs per month |
|---|---|---|---|
| Free | $0 | 1, weekly | 4 |
| Team | $49 | 10, nightly | 300 |
| Scale | $299 | 100, nightly, with PRs, Docs Bisect and Prerequisite Proof | 3,000 |

## Measured Cost per Run Is $0.02771

neatlogs measured 4 v1 `firstrun.run` traces. Compute is a priced assumption, so the total mixes one measured and one assumed cost.

| Input | Value | Measured | Source |
|---|---|---|---|
| Model cost per run | $0.02623 | yes | $0.10491 total over 4 traces, neatlogs |
| Run duration | 128.4 s | yes | neatlogs, v1 group |
| Tool calls per run | 4.25 | yes | neatlogs, v1 group |
| VM price | $0.0416 per hour | no | AWS t3.medium on-demand, instances.vantage.sh/aws/ec2/t3.medium |
| Compute cost per run | $0.00148 | no | $0.0416 x 128.4 / 3600 |
| Recovery multiplier | 1.0 | no | v1 has no recovery. Replace with v2 measured. |
| Total cost per run | $0.02771 | no | $0.02623 + $0.00148 |

The model cost uses Sonnet 5.5 list price. Anthropic did not bill it.

## v2 Measured Cost, With Recovery and Verification, Is $0.02232 per Run

The v1 numbers above assumed a recovery multiplier of 1.0. The 4 final v2 traces measure it directly: they include recovery attempts and the second clean run that verifies a fix.

| Input | Value | Measured | Source |
|---|---|---|---|
| Model cost per run, v2 | $0.0200 | yes | 4 v2 `firstrun.run` traces, neatlogs, evidence/before_after_traces.json |
| Run duration, v2 | 200.8 s | yes | same traces, verification included |
| Compute cost per run, v2 | $0.00232 | no | $0.0416 x 200.8 / 3600 |
| Total cost per run, v2 | $0.02232 | no | $0.0200 + $0.00232 |

| Tier | Revenue | Cost (runs x $0.02232) | Gross profit | Gross margin |
|---|---|---|---|---|
| Team | $49.00 | 300 x 0.02232 = $6.70 | $42.30 | 86.3% |
| Scale | $299.00 | 3,000 x 0.02232 = $66.96 | $232.04 | 77.6% |

A Docs Bisect probe and a Prerequisite Proof replay stored commands, so they cost $0 in model calls. A bisect probe ran about 75 s, which is $0.00087 of compute at the same VM price. 100 bisects of 5 probes each add $0.43 a month to a Scale customer.

## Team and Scale Keep a Gross Margin Above 70%

| Tier | Revenue | Model cost (runs x $0.02623) | Compute cost (runs x $0.00148) | Gross profit | Gross margin |
|---|---|---|---|---|---|
| Free | $0.00 | 4 x 0.02623 = $0.10 | 4 x 0.00148 = $0.01 | -$0.11 | not defined |
| Team | $49.00 | 300 x 0.02623 = $7.87 | 300 x 0.00148 = $0.44 | $40.69 | 83.0% |
| Scale | $299.00 | 3,000 x 0.02623 = $78.69 | 3,000 x 0.00148 = $4.44 | $215.87 | 72.2% |

If every run needs one recovery retry, the multiplier is 2.0. Team margin falls to 66.0% and Scale margin falls to 44.4%. The v2 traces will replace the 1.0 with a measured value.

Stripe takes 2.9% plus $0.30 per paid invoice. The scenarios below include that fee.

## Both Scenarios Pay Back Fixed Costs in Month 2

Both scenarios start with $5,000 cash on 2026-11-01. Fixed costs are $25 a month. Monthly churn is 10% on Free, 5% on Team and 3% on Scale.

- **Base:** 10 new Free users a month. 1 new Team customer a month in months 2 to 6, then 2 a month. 1 new Scale customer in months 9, 12, 15 and 18.
- **Growth:** 30 new Free users a month. 3 new Team customers a month. 1 new Scale customer a month from month 4.

| Scenario | Month | Free | Team | Scale | MRR | Costs | Cumulative cash |
|---|---|---|---|---|---|---|---|
| Base | 1 | 10.0 | 0.0 | 0.0 | $0 | $26 | $4,974 |
| Base | 6 | 46.9 | 4.5 | 0.0 | $222 | $76 | $5,377 |
| Base | 12 | 71.8 | 13.9 | 1.9 | $1,254 | $349 | $8,578 |
| Base | 18 | 85.0 | 20.8 | 3.5 | $2,069 | $566 | $15,747 |
| Growth | 1 | 30.0 | 3.0 | 0.0 | $147 | $58 | $5,089 |
| Growth | 6 | 140.6 | 15.9 | 2.9 | $1,649 | $468 | $8,268 |
| Growth | 12 | 215.3 | 27.6 | 8.0 | $3,741 | $1,062 | $20,757 |
| Growth | 18 | 255.0 | 36.2 | 12.2 | $5,428 | $1,542 | $41,180 |

Customer counts are expected values, so they carry decimals. Costs hold model cost, compute, Stripe fees and fixed costs. No salary is paid.

## A Solo Founder Needs One Team Customer to Cover Costs

The founder takes no salary, so the only cash drain is $25 a month plus the cost of Free runs. With zero paying customers, $5,000 lasts about 190 months. One Team customer earns $40.69 gross profit minus $1.72 in Stripe fees, which is $38.97 and covers the $25 fixed costs. Revenue covers model cost from the first paid customer.

The real risk is demand, not cost. The customer counts are assumptions until the first paying team signs.

## Paste This Prompt Into Ari to Build the Model

Paste this into cfo.ai after you attach `business/inputs.json`.

```text
FirstRun is an AI agent that runs a dev tool's quickstart docs in a clean container every night and opens a pull request when a step breaks. Customers are DevRel and docs teams at developer tool companies. Use the attached inputs.json for every number. Plans: Free at $0 (4 runs a month), Team at $49 per month (300 runs a month), Scale at $299 per month (3,000 runs a month). Cost per run is the measured neatlogs model cost of $0.02623 plus $0.00148 container compute, times a recovery multiplier of 1.0. Add a Stripe fee of 2.9% plus $0.30 per paid invoice, $25 fixed costs a month and no founder salary. Build an 18-month model starting with $5,000 cash on 2026-11-01. Build two scenarios, Base and Growth, with the customer additions and churn rates in inputs.json. Show customers per plan, MRR, gross margin per plan, operating costs, ending cash and cash runway. Mark the neatlogs numbers as measured and name every assumption.
```
