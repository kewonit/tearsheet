# tearsheet

tearsheet is an [MCP](https://modelcontextprotocol.io) server for researching companies listed in India. It reads [Tijori Finance](https://www.tijorifinance.com) through a local headless browser and checks quarterly figures against XBRL filings you download yourself.

It runs on your machine over stdio. Version 0.2.0 is alpha.

tearsheet isn't affiliated with or endorsed by Tijori Financial Services, NSE or BSE. Read [docs/DATA-USE.md](docs/DATA-USE.md) before using it.

## Requirements

- Python 3.12 or later
- [uv](https://docs.astral.sh/uv/)
- Chromium for Playwright, installed below
- An MCP client that can launch stdio servers, such as Claude Code or Claude Desktop

## Install

tearsheet isn't on PyPI yet. Install it from source:

```sh
git clone https://github.com/kewonit/tearsheet.git
cd tearsheet
uv sync
uv run playwright install chromium
```

## Add it to a client

Claude Code:

```sh
claude mcp add tearsheet -- uv --directory /path/to/tearsheet run tearsheet
```

Claude Desktop and other clients take this in their MCP settings file:

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

## Tools

Tools that take a company accept its name, NSE symbol or BSE code. [docs/TOOLS.md](docs/TOOLS.md) lists every parameter.

| Tool | Returns |
|---|---|
| `find_company` | Name, NSE symbol, BSE code and Tijori slug |
| `company_snapshot` | Delayed price, market cap, P/E, PEG, key ratios, 3- and 5-year averages, price changes, dividends and dated events |
| `get_financials` | Income statement, balance sheet, cash flow, quarterly results, ratios or fund flow |
| `get_ownership` | Shareholding by quarter, with each row's change from the previous quarter |
| `get_operating_metrics` | Company-specific KPIs, such as capacity, volumes or deal wins |
| `get_business_mix` | Revenue split by product, region or segment, and market shares with their dates |
| `search_screen_fields` | Exact screener field names, with units |
| `screen_stocks` | Companies matching a financial condition, a business filter or a preset |
| `compare_companies` | 2 to 6 companies side by side, with growth, 3-year CAGR and peer minimum, median and maximum calculated by tearsheet |
| `get_sector_view` | Headline indices, sector indices and conglomerates. Sectors and conglomerates include constituents |
| `search_filings` | Pages and figures in your filings that match a query |
| `read_filing` | PDF pages, or XBRL figures in crore with their periods |
| `reconcile_figure` | One quarterly figure from Tijori beside the filed figure |
| `server_status` | Session state, cache contents and filing count. Works offline |

Prompts: `earnings_review`, `peer_comparison` and `thesis_check`.

## Results

Every tool returns the same envelope, as `structuredContent` with a declared output schema and as compact JSON text:

```json
{
  "data": {},
  "entity": {"name": "Example Ltd", "nse": "EXAMPLE", "bse": "500000"},
  "as_of": "2026-09-30",
  "retrieved_at": "2026-11-08T04:30:00Z",
  "units": {"currency": "INR", "scale": "crore"},
  "sources": [{"provider": "tijori", "url": "https://www.tijorifinance.com/company/example/financials/"}],
  "verification": {"status": "matched", "detail": "Checked against filings: revenue Sep 2026."},
  "warnings": []
}
```

| Field | Meaning |
|---|---|
| `units` | Money is in crore unless a row states otherwise |
| Row `unit` | One of `crore`, `crore_shares`, `percent`, `days`, `multiple`, `rupees_per_share` or `as_reported`. `as_reported` means the unit is unknown |
| Period labels | `TTM` marks trailing twelve months. `Interim` marks a column whose length Tijori doesn't state |
| `null` value | No reliable figure exists. A warning gives the reason |
| `verification.status` | `matched` or `mismatch` against a filing, otherwise `unchecked` |
| `warnings` | Anything that affects how to read the data |

Errors return `code`, `message`, `retryable` and, where useful, `hint`. The codes are listed in [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md#errors).

## Plan access

| Data | Free plan or signed out | Paid plan |
|---|---|---|
| Statements, ratios, fund flow, ownership, screens, sectors | Yes | Yes |
| Latest operating metrics, revenue split and market shares | Yes | Yes |
| History of operating metrics, revenue split and market shares | No | Yes |
| Premium screen presets | No | Yes |

tearsheet reads the plan from the signed-in session's company pages and returns only what that plan shows there. Some Tijori responses include history even for free accounts. On a free plan tearsheet keeps only the latest value from them, caches nothing else, and never calls the revenue mix history endpoint.

## Sign in

Only needed for paid-plan data.

```sh
uv run tearsheet login
```

This opens Chromium on Tijori's sign-in page. You sign in there, so tearsheet never handles your password. When Tijori sets a session cookie, tearsheet saves the browser session to `~/.tearsheet/session.json` with owner-only permissions and closes the window. It waits up to 10 minutes. If a sign-in method is refused in that window, use another.

`tearsheet login` has been tested against a local sign-in page, not yet against Tijori's.

## Filings

tearsheet never downloads filings, because NSE and BSE prohibit automated collection. Download them yourself into `~/.tearsheet/filings`:

| File | Source | Naming |
|---|---|---|
| Quarterly results, XBRL | NSE, *Integrated Filing - Financials* (results from 2025 on) | Any name. The file states its company |
| Annual reports and transcripts, PDF | NSE, BSE or the company's website | Inside a folder named after the NSE symbol or BSE code, such as `NGLFINE/annual-report-2026.pdf` |

With a matching XBRL filing, `get_financials` checks quarterly revenue, profit before tax and net profit. A figure matches when it is within ₹5 lakh or 0.01% of the filed value, whichever is larger. Tijori rounds to two decimals in crore, so anything wider is a real difference.

Tested on integrated filings from a manufacturer, an NBFC, a bank and a life insurer. In those, Tijori's profit before tax differed from the statutory figure for the bank (by its minority interest) and the insurer, and tearsheet reports both as mismatches. General insurers and results filed before 2025 are untested.

## Files and settings

| Variable | Default | Contents |
|---|---|---|
| `TEARSHEET_HOME` | `~/.tearsheet` | `session.json` and `cache.sqlite3`, both owner-only |
| `TEARSHEET_FILINGS_DIR` | `~/.tearsheet/filings` | Filings you downloaded |

tearsheet sends at most one request a second to Tijori, two at a time, and none to NSE or BSE.

## Limitations

- Prices are delayed.
- Figures are Tijori's. Only quarterly revenue, profit before tax and net profit can be verified, and only for quarters with a filing.
- tearsheet parses Tijori's pages and private endpoints. When their shape changes, tools return `UPSTREAM_CHANGED` instead of partial data.
- Some of Tijori's presets fail on Tijori's side. tearsheet returns Tijori's error.
- Tijori doesn't expose ISINs.

## Not investment advice

tearsheet returns facts and calculations. It doesn't recommend buying, selling or holding anything, can't place orders, and isn't registered with SEBI as an adviser or research analyst.

## Development

[CONTRIBUTING.md](CONTRIBUTING.md) covers setup, test suites and releases. [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md) describes the design. Report vulnerabilities as described in [SECURITY.md](SECURITY.md). Changes are in [CHANGELOG.md](CHANGELOG.md).

## Licence

[MIT](LICENSE). Credits are in [NOTICE](NOTICE).
