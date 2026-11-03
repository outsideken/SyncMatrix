# Sync Matrix: working rules for assistants

K (outsideken) owns this repo and decides; assistants propose. Two assistants
work here: **Claude** and **Cursor** (Cursor runs on Grok; "Grok" and "Cursor"
are the same assistant). Read this file at the start of every session.

The shared toolkit rules are in `~/Code/geo-toolkit/AGENTS.md` ("Working
together"). This file repeats what matters here, so nobody depends on another
repo's file, and adds this repo's own rules.

## This repo is public

The repo and its GitHub Pages site (https://outsideken.github.io/SyncMatrix/)
are public on purpose (K, 2026-10-31), so Pages is free. Git keeps history
forever: anything committed stays public even after it is deleted.

- **No personal information, ever (K, 2026-11-03).** No names, email
  addresses, phone numbers, street addresses, account names, home-folder
  paths (a Mac, Linux or Windows user folder), or anything else that identifies a person.
  Commits use the GitHub no-reply address
  (`outsideken@users.noreply.github.com`), not a personal one.
  `tests/test_no_personal_information.py` fails on email addresses and home
  paths in tracked files; the rest of this rule is the reviewer's to check.
- **Nothing above the SECLAB ceiling.** `config/workflow.json` `max_seclab`
  (UNCLASSIFIED) is the ceiling for everything published. The build and
  `scripts/check_data.py` enforce it. RESTRICTED appears only in temporary
  test fixtures, never under `data/` or `web/`.
- **Nothing sensitive at all:** no keys, tokens, credentials, or non-public
  data. The data is public proxy data (Celestrak orbits, demo windows).

## The review cycle

- Work on a branch and open a pull request; never commit to `main` by hand
  (the daily refresh job is the only thing that does).
- **Author ≠ reviewer.** The assistant that wrote a PR doesn't approve it; the
  other one reviews it. Every PR is reviewed, however small.
- **Approvals are PR comments,** because both assistants act as K's GitHub
  account and GitHub refuses an author's own approval. The reviewer posts one
  comment headed exactly:
  - `## Review → <author>: approve`, or
  - `## Review → <author>: request changes`, with a numbered list of what to
    change.
- **Evidence, not impressions.** Say what you ran and what it printed, and
  say what you checked only by reading. "Looks right" is not a review.
- The reviewer comments; it does not push to the author's branch. The author
  answers each point and pushes the fixes, then asks for a re-review.
- **Only K merges,** or tells an assistant to merge. An approval alone is not
  a merge instruction.
- Disagreements go in the PR for K to decide. Never settle one by overwriting.

## What a reviewer runs here

```bash
python -m pytest tests --ignore=tests/browser   # unit tests
python -m pytest tests/browser                  # page tests (run separately: the conftests clash)
python scripts/check_build.py                   # data/ and web/live match a fresh build
python scripts/check_data.py                    # payloads, manifest and SECLAB ceiling
```

CI runs these on every PR; nothing is done until CI is green. After any edit
to `web/sync_matrix.css` or `web/sync_matrix.js`, the author reruns
`python scripts/stamp_assets.py` (a test fails if the stamps are stale).

## Other standing decisions (K)

- **ICOD** is the true information cut-off (when the data was grabbed), never
  export or render time.
- **A chart shows what its data file covers:** it draws the rows the file
  evaluated, nothing more.
- **Colours** come from ColorBrewer ramps; tints come from the same ramp.
- **Branches:** merge `main` into a PR branch to update it; don't rebase or
  force-push. Check that GitHub says MERGED before deleting a branch.
- Decisions that should outlast a session go in this file, through a PR.
  An assistant's private memory doesn't count: the other one can't see it.
