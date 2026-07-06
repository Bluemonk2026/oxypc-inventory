---
name: bulk-csv-import
description: Use when Pankaj asks to upload/import a CSV of devices, dealers, or other inventory data into OxyPC Inventory. Covers the local-vs-production decision, encoding fallback, and dedupe verification.
---

# Bulk CSV Import (OxyPC Inventory)

## Step 1 — Always ask target DB first

Never assume. Use AskUserQuestion: **local dev DB** vs. **Production
(app.oxypc.com)**. A prior answer for one import does not carry over to the
next — ask again each time.

## Step 2 — Pre-check for duplicates before importing

Before running the import, query the target DB for existing `lot_number` /
`barcode` / unique-key values in the CSV so you can report expected
skips/conflicts up front rather than discovering them mid-import.

## Step 3 — Encoding fallback (known gap)

Bulk-upload endpoints must decode with a fallback chain, not a single
`utf-8-sig` call — real-world CSVs from Pankaj have contained non-UTF-8 bytes
that crash a single-encoding `decode()`. Confirm the endpoint you're using
does:
```python
for enc in ("utf-8-sig", "utf-16", "latin-1"):
    try:
        text = content.decode(enc)
        break
    except UnicodeDecodeError:
        continue
```
If it doesn't (check `routers/bulk_upload.py` and any other bulk-upload
endpoint you're about to use), add it before running the import — this
exact bug crashed the devices bulk-upload endpoint on a real file.

## Step 4 — Run and report exact numbers

Report `<imported>/<total>` and list every skipped row's identifying value
(barcode/lot_number) with the reason (duplicate, validation failure, etc.).
Never report just "success" without exact counts — Pankaj needs to
reconcile these against the physical batch.

## Step 5 — Commit/deploy is a separate ask

Importing data into production does not itself require a commit (no code
changed unless you also fixed a bug like Step 3). If you *did* fix code
during the import, that fix still needs its own commit/push go-ahead per
**commit-deploy-gate** — importing data doesn't pre-authorize shipping code.
