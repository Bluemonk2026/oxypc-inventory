---
name: commit-deploy-gate
description: Use before running git add/commit/push or restarting the OxyPC Inventory server for any batch of work, no matter how the current work session started. Enforces the standing per-batch confirmation rule.
---

# Commit / Deploy Gate (OxyPC Inventory)

## The rule

Never run `git add` / `git commit` / `git push`, and never restart the live
dev/prod server, without the user's explicit go-ahead **for this specific
batch of changes**. A "yes, commit and deploy" given for one batch of work
does **not** carry forward to the next batch, even in the same session, even
minutes later.

## Before asking, prepare a real summary

List every file touched in this batch and what changed in each — not just
"various fixes." Pankaj is CEO/Director across multiple entities and will
want to know exactly what's shipping. Mention any regression you caught and
fixed proactively (this is a transparency signal he explicitly values, not
just a courtesy).

## Ask, don't assume

Use a direct question: "Ready to commit + push + restart this batch — go
ahead?" Do not infer consent from the fact that the user asked for the
feature in the first place, or from silence.

## After go-ahead

1. `git status` / `git diff` to confirm the exact fileset matches what you
   summarized.
2. Commit with a message describing the *why*, not a file list.
3. Push to `main`.
4. Restart the server only if this project's workflow requires it for the
   change to take effect (most template/route changes need a restart since
   there's no autoreload configured).
5. Confirm health after restart (hit a known route, check server logs) before
   telling the user it's live.

## Exception

None. Even "commit and deploy" said for a CSV-import bug fix does not
authorize committing an unrelated 12-item feature batch finished afterward.
Ask again.
