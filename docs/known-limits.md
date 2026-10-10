# Known Limits

What FirstRun does not do yet, found while testing the edge cases.

- A step that hangs is killed at the time limit and the run stops. FirstRun does not retry a hung step.
- Version pinning in verification covers pip packages only. npm and apt versions can still drift between runs.
- Secret redaction knows common key shapes, `NAME=value` pairs for names that end in KEY, TOKEN, SECRET or PASSWORD, and the exact values in the allowlist. An unusual secret outside the allowlist can pass through.
- A login wall that answers HTTP 200 shows up as "no runnable steps", not as "docs unreachable".
- A run with no terminal and a low-confidence class uses the top class. Only a person at a terminal who stays silent for 60 seconds gets `needs_human`.
- A step's output is held in memory before the cut to 20 KB, so a very large output costs memory first.
- A clean pass ends as `passed`, not `verified`, because nothing was patched.
- Stale container cleanup tells live runs apart by process id, so it works only for runs on the same Windows host. Verification containers older than 1 hour count as stale.
- A step that needs a paid account or a video is marked `skipped_out_of_scope`. A later step that depends on it can still fail.
- The demo rows D1 and D3 to D5 need a human: the evidence folder, the X Submit button, the video length and the logged-out link check.
