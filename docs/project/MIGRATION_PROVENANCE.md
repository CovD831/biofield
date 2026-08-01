# Migration provenance

Biofield became a standalone repository on 2026-07-20.

## Source snapshot

- Source workspace: `/Users/abab/Documents/openpilot/experiments/biofield_architecture`
- OpenPilot working-tree HEAD at extraction: `76b910ba061eb12a83fa5442ce61d3ec348593a3`
- Standalone import commit: `ff052d9`
- Standalone import tag: `migration-import`
- Imported files: 75 non-ignored files

The Biofield directory was entirely untracked in the OpenPilot repository. The OpenPilot commit above identifies the surrounding workspace state but does not contain the Biofield files. There was therefore no real Biofield Git history to extract with `git subtree split` or `git filter-repo`.

Before the import commit, all 75 copied files were compared to the source with SHA-256 and matched byte for byte. The imported snapshot passed 188 tests. Subsequent standalone commits intentionally record packaging, repository-discovery, documentation, and CI changes.

The extraction excluded `.venv/`, `.pytest_cache/`, `__pycache__/`, `.DS_Store`, generated egg-info, and ignored `runs/` output. Historical architecture documents and reviewed Markdown results were retained.
