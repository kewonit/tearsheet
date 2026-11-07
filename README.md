# Tearsheet

Tearsheet is a local [MCP](https://modelcontextprotocol.io) server that helps AI agents research Indian listed companies. It uses your own Tijori Finance account, plus any filings you download yourself.

> **Early development.** The foundation works, but there are no company data tools yet. See the [roadmap](docs/ROADMAP.md).

> **Unofficial.** Tearsheet is not affiliated with or endorsed by Tijori Financial Services, NSE or BSE. Read [how it uses data](docs/DATA-USE.md) before you use it.

## What it's for

Agents are good at reasoning about a company and bad at getting exact figures right. Tearsheet is designed to help with that:

- **Answers in one call.** Tools work at the level of a research question, and accept a name, NSE symbol, BSE code or ISIN.
- **Numbers you can trust.** Results state their units, date and source, and maths is done on the server rather than by the model.
- **Figures you can check.** A figure can be compared with a filing you've added, and anything unchecked is labelled `unchecked`.
- **Small responses.** Output is typed and compact, so research doesn't fill the context window.

## What works today

- `tearsheet login` signs in through a real browser window. Your password goes to Tijori's page, never to Tearsheet.
- `server_status` is the only MCP tool so far. It reports the saved session, cache contents and added filings.
- The shared response format, rate limiting and a local cache are in place for the tools to come.

The sign-in has been tested against a local test page, but not yet against Tijori itself.

## Install

Tearsheet needs [uv](https://docs.astral.sh/uv/) and isn't on PyPI yet.

```sh
git clone https://github.com/kewonit/tearsheet.git
cd tearsheet
uv sync
uv run playwright install chromium
uv run tearsheet login
```

To add it to Claude Code:

```sh
claude mcp add tearsheet -- uv --directory /path/to/tearsheet run tearsheet
```

## Where your data lives

Everything stays on your machine, in `~/.tearsheet` by default.

| Setting | Default | Holds |
|---|---|---|
| `TEARSHEET_HOME` | `~/.tearsheet` | Your session and the cache |
| `TEARSHEET_FILINGS_DIR` | `~/.tearsheet/filings` | Filings you downloaded |

## Not investment advice

Tearsheet provides facts and calculations for research. It doesn't recommend buying or selling anything, can't place orders, and isn't a SEBI-registered adviser or research analyst. Data can be wrong or out of date, so check anything you plan to rely on.

## Contributing

See [CONTRIBUTING.md](CONTRIBUTING.md). To report a security problem, see [SECURITY.md](SECURITY.md).

## Licence

[MIT](LICENSE). See [NOTICE](NOTICE) for credits.
