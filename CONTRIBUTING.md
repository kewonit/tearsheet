# Contributing

Thanks for helping. Please read [docs/DATA-USE.md](docs/DATA-USE.md) first, because its rules apply to every change.

## Setup

```sh
uv sync
uv run pytest
```

Run the browser tests, which need Chromium, with:

```sh
uv run playwright install chromium
uv run pytest -m browser
```

## Before you open a pull request

```sh
uv run ruff format .
uv run ruff check .
uv run pytest
```

CI runs the same checks. It never signs in to Tijori or contacts any data source.

Two more suites run only on your machine:

```sh
uv run pytest -m browser   # real Chromium against a local site
uv run pytest -m live      # contacts Tijori, slowly; checks accounting identities
```

Live tests assert behaviour and identities, such as a balance sheet balancing, never specific figures, so no Tijori data enters the repository.

## Evaluations

`evals/run.py` runs analyst tasks through a real agent, which costs money. Tune tool descriptions against the tuning split only, change one tool at a time, and check the held-out split before merging. Don't adjust a held-out check after seeing its result.

## Please don't commit

- Real Tijori responses, cached data or filings, even small ones. Write made-up fixtures instead.
- Session files or cookies, including in logs and bug reports.

Pull requests that add scraping of nseindia.com or bseindia.com, work around a site's access controls, or fetch data a user's Tijori plan doesn't show won't be accepted.

## Writing tools

Tool descriptions are what agents read, so they matter as much as the code. Say what the tool does, when to use it and when not to, and what its limits are. Write them by hand, and change one tool at a time so you can tell what helped.

See [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md) for how responses and errors should look.
