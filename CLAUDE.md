# DFSRiches

## Versioning
Every push that changes the app or server (not the scheduled data-only refreshes of
`data/optimal_lineups.json` / `data/dk_overrides.json`) bumps the version's third
number first: run `python -m scripts.bump_version` and include the changed
`mobile/app.json`, `mobile/package.json` and `mobile/package-lock.json` in the commit.
Settings shows this version.
