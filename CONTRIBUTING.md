# Contributing

Read [docs/DATA-USE.md](docs/DATA-USE.md) first. Its rules apply to every change, and pull requests that break them won't be merged.

## Setup

```sh
uv sync
uv run playwright install chromium
```

## Checks

CI runs these on every push and pull request:

```sh
uv run ruff format --check .
uv run ruff check .
uv run pytest
uv run python evals/run.py --validate
uv build
```

CI never signs in to Tijori and never contacts a data source.

## Test suites

| Suite | Command | In CI | Needs |
|---|---|---|---|
| Unit and protocol | `uv run pytest` | Yes | Nothing |
| Browser | `uv run pytest -m browser` | No | Chromium. Runs against a local site |
| Live | `uv run pytest -m live` | No | Network access to Tijori. Runs signed out. The filing check uses XBRL files in your filings folder, if any |

Live tests assert behaviour and accounting identities, such as assets equalling liabilities plus equity. They never assert specific figures, so no Tijori data enters the repository.

## Fixtures

Write fixtures by hand with made-up companies and numbers. Never commit:

- Tijori responses, pages or cached data, in whole or in part
- Filings
- Session files or cookie values, including in logs and bug reports

`tests/unit/filing_fixtures.py` shows how to build synthetic XBRL.

## Tools

Agents choose tools from their descriptions, so a description change is a behaviour change.

- State what the tool returns, when to use it, and its limits.
- Write descriptions by hand. Change one tool at a time so evaluation results can be attributed.
- Raise `ToolFailure` with an `ErrorCode` for every foreseeable failure. Return an empty result with a warning rather than an error when nothing matches.
- Return an `Envelope` via `to_result`.

After changing any tool or prompt signature or description, regenerate the reference:

```sh
uv run python scripts/generate_tools_doc.py
```

`tests/unit/test_tools_doc.py` fails if `docs/TOOLS.md` is out of date.

## Evaluations

`evals/run.py` runs the tasks in `evals/tasks.toml` through headless Claude Code sessions with only tearsheet connected. Each run costs money. Results go to `.local/evals`, which is gitignored.

```sh
uv run python evals/run.py --split tuning
uv run python evals/run.py --split held_out
```

Tune against the `tuning` split only. Run `held_out` before merging, and don't edit a held-out check after seeing its result.

## Not accepted

- Requests to nseindia.com or bseindia.com
- Stealth plugins, disguised user agents, challenge solving, or retries after a 403
- Requests for data the user's Tijori plan doesn't show
- Buy, sell or hold recommendations, or order placement

## Releases

Maintainers only.

1. Set `__version__` in `src/tearsheet/__init__.py`.
2. Move the `Unreleased` entries in `CHANGELOG.md` under the new version and date.
3. Regenerate `docs/TOOLS.md` and run every suite, including browser and live.
4. Commit, then tag and push:

   ```sh
   git tag v0.2.0
   git push origin v0.2.0
   ```

`.github/workflows/release.yml` runs the checks, confirms the tag matches `__version__`, builds, and publishes to PyPI.

Publishing uses [PyPI trusted publishing](https://docs.pypi.org/trusted-publishers/), so no API token is stored. Before the first release:

1. On PyPI, add a pending trusted publisher for project `tearsheet`: owner `kewonit`, repository `tearsheet`, workflow `release.yml`, environment `pypi`.
2. On GitHub, create an environment named `pypi` under *Settings → Environments*. Add required reviewers if releases should need approval.
