# Git History Recovery Record — 2026-08-01

## Purpose

This record documents the repository-history recovery performed after the
Biofield working directory was moved through iCloud Drive and part of its
local Git object database became unavailable. It is an audit record; it does
not claim that the original multi-commit history was restored.

## Preserved repository state

The GitHub `main` branch contains the complete latest project snapshot in
commit `58b1e41fda608f6f4e43e0f43d2ae00189e127fc` (`feat: add MEAS0 V3 offline
implementation`). Its tree was verified locally to contain 261 files and the
current MEAS0 status remains `FAIL / NOT_EVALUATED`.

## Original local commit sequence

The corrupted local reflog records these commits, oldest to newest:

1. `ff052d9b95bd10d4e68afcb9830f5937eac42272` — `chore: import biofield snapshot from OpenPilot workspace`
2. `90c18864ab2d4dcbcf97c187a1b4bb8d6fd5eaee` — `build: make Biofield packaging standalone`
3. `999c2e3021980287551482bbc5fb22ca1c7605f6` — `docs: establish standalone Biofield repository`
4. `9dc412520387d0c9cda700f49744305ff9f99acd` — `build: use wheel installs for Python 3.13 compatibility`
5. `cddfedd1e6f95dac0f742429f1a0337ea76968e9` — `feat: add MEAS0 V3 offline implementation`

## Why the sequence was not rewritten onto `main`

The moved repository has 138 loose Git objects with zero allocated data
blocks. Cross-checking the old OpenPilot worktree and the GitHub snapshot
provided valid sources for 76 objects, but 62 objects have no recoverable
source. iCloud also rejected replacement of the placeholder files in the
original `.git/objects` directory.

The five commit objects and the newest two root trees are readable. However,
the original MEAS0 V3 binary diff requires at least one missing historical
object, so the original change cannot be reproduced and verified against its
parent. Creating a synthetic two-commit equivalent would misrepresent the
historical record.

## Working policy from this point

- Treat the GitHub snapshot plus this record as the durable recovery baseline.
- Continue normal work from this non-iCloud clone.
- If a Time Machine backup, prior disk image, or a complete pre-move clone is
  found later, verify it with `git fsck` before considering restoration of the
  original commit sequence.
- Do not infer that Gate M passed: the documented state remains
  `FAIL / NOT_EVALUATED` pending formal external inputs and evidence.
