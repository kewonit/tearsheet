# tearsheet

tearsheet is a local [MCP](https://modelcontextprotocol.io) server that helps AI agents research Indian listed companies. It reads [Tijori Finance](https://www.tijorifinance.com) the way your browser does, and can check figures against filings you download yourself.

> **Alpha.** The Tijori tools are tested against the live site, and the filing tools against real filings. Sign-in hasn't been tested on Tijori itself yet.

> tearsheet isn't affiliated with or endorsed by Tijori Financial Services, NSE or BSE. Read [how it uses data](docs/DATA-USE.md) before you use it.

## What it's for

Agents are good at reasoning about a company and bad at getting exact figures right. tearsheet is built around that:

- **Units on every figure.** Statements mix crore, percentages, days and multiples, so every row says which it is.
- **Honest periods.** Trailing twelve months and interim columns are labelled, rather than passing as financial years.
- **Gaps stay visible.** A figure that Tijori's own data contradicts is left blank, with the reason, and the model is never left to guess.
- **Maths on the server.** Growth, CAGR and peer statistics are calculated, not left to the model.
- **Filters that are proven to apply.** A screen's filter that Tijori silently drops is reported as an error, never returned as results.
- **Small responses.** Typical results are 1 to 15 KB.
- **Facts, not advice.** Tijori's own opinions and forecasts are left out, and nothing says buy or sell.

## Tools

| Tool | What it does |
|---|---|
| `find_company` | Finds a company by NSE symbol, BSE code or name, and gives the real symbol if yours was wrong |
| `company_snapshot` | One-call overview: price, size, valuation, key ratios, dividends and recent events |
| `get_financials` | Income, balance sheet, cash flow, quarterly results, ratios and fund flow |
| `get_ownership` | Shareholding pattern by quarter, with each row's change |
| `get_operating_metrics` | Company-specific KPIs such as capacity or deal wins |
| `get_business_mix` | Revenue split by product, region or segment, and market shares with their dates |
| `screen_stocks` | Whole-market screens on financial conditions, business filters or presets |
| `search_screen_fields` | Finds exact screener field names, with units |
| `compare_companies` | Compares 2 to 6 companies, with growth and peer statistics calculated on the server |
| `get_sector_view` | Market indices, sector indices and conglomerates, with their constituents |
| `search_filings` | Searches filings you downloaded |
| `read_filing` | Reads pages or figures from one of those filings |
| `reconcile_figure` | Checks a quarterly figure against its filing |
| `server_status` | Reports the session, cache and filings folder |

There are also three prompts: `earnings_review`, `peer_comparison` and `thesis_check`.

## Install

tearsheet needs [uv](https://docs.astral.sh/uv/) and isn't on PyPI yet.

```sh
git clone https://github.com/kewonit/tearsheet.git
cd tearsheet
uv sync
uv run playwright install chromium
```

**Claude Code:**

```sh
claude mcp add tearsheet -- uv --directory /path/to/tearsheet run tearsheet
```

**Claude Desktop and other MCP clients**, in the client's MCP settings file:

```json
{
  "mcpServers": {
    "tearsheet": {
      "command": "uv",
      "args": ["--directory", "/path/to/tearsheet", "run", "tearsheet"]
    }
  }
}
```

## Signing in

You don't need to sign in: every tool works from Tijori's public pages. If your Tijori plan includes data that free accounts don't get, such as metric history, run `uv run tearsheet login` and sign in on Tijori's page. Your password goes to Tijori, never to tearsheet.

tearsheet only returns what your plan shows. On the free plan that means the latest value of operating metrics, revenue mix and market share, but not their history. See [DATA-USE.md](docs/DATA-USE.md) for why.

## Filings

The exchanges prohibit automated collection, so tearsheet never downloads filings. Download them yourself and put them in `~/.tearsheet/filings`:

- **Quarterly results as XBRL.** From 2025, these are on NSE under *Integrated Filing - Financials*. Each file names its own company, so any file name works.
- **PDFs** such as annual reports and concall transcripts. Put these in a folder named after the NSE symbol or BSE code, such as `filings/NGLFINE/annual-report-2026.pdf`.

`get_financials` then checks quarterly revenue, profit before tax and net profit against any matching filing, and `reconcile_figure` compares one figure in detail.

Checking real filings shows why this matters. Tijori's quarterly figures matched to within rounding for a manufacturer, an NBFC, a bank and a life insurer, but its profit before tax for the bank and the insurer wasn't the statutory figure. The bank's differs by its minority interest. Reconciliation reports those as mismatches with both figures.

Templates other than these four, and results filed before 2025, haven't been tested.

## Where your data lives

| Setting | Default | Holds |
|---|---|---|
| `TEARSHEET_HOME` | `~/.tearsheet` | Your session and the cache |
| `TEARSHEET_FILINGS_DIR` | `~/.tearsheet/filings` | Filings you downloaded |

Everything stays on your machine. tearsheet makes at most about one request a second to Tijori, and none to NSE or BSE.

## Know the limits

- Prices on Tijori are delayed, not live.
- Figures are Tijori's, and are marked unchecked unless a filing confirms them.
- tearsheet reads Tijori's web pages, which can change without notice. When they do, tools fail with a clear error rather than returning bad data.
- Some of Tijori's own presets are broken, and tearsheet passes on Tijori's error when one fails.

## Evaluation

`evals/` holds 30 analyst tasks, 10 of them held out, and a runner that scores a real agent's tool choice, answers, tool calls and tokens. A first sample of 6 tasks passed 5. The miss was a held-out task where the agent answered correctly by a different route than the check requires. See [evals/run.py](evals/run.py).

## Not investment advice

tearsheet provides facts and calculations for research. It doesn't recommend buying, selling or holding anything, can't place orders, and isn't a SEBI-registered adviser or research analyst. Data can be wrong or out of date, so check anything you plan to rely on.

## Contributing

See [CONTRIBUTING.md](CONTRIBUTING.md). To report a security problem, see [SECURITY.md](SECURITY.md). Changes are listed in [CHANGELOG.md](CHANGELOG.md).

## Licence

[MIT](LICENSE). See [NOTICE](NOTICE) for credits.
