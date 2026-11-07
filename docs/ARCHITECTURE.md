# Architecture

Tearsheet is a Python MCP server that runs on your machine over stdio. Parts marked *planned* don't exist yet.

```
src/tearsheet/
  server.py           Tool registration
  cli.py              The tearsheet command
  login.py            Browser sign-in
  core/               Envelope, errors, units, cache, rate limiter, session, paths
  sources/tijori/     Planned: requests and parsers
  sources/filings/    Planned: local folder index, XBRL reader, PDF text
  analytics/          Planned: ratios and reconciliation
  tools/              Planned: one module per tool family
```

## Responses

Every tool returns the same envelope (`core/envelope.py`), so an agent always knows where to look:

```json
{
  "data": {},
  "entity": {"name": "Example Ltd", "nse": "EXAMPLE", "isin": "INE000A00000"},
  "as_of": "2026-09-30",
  "retrieved_at": "2026-11-08T04:30:00Z",
  "units": {"currency": "INR", "scale": "crore"},
  "sources": [{"provider": "tijori", "url": "https://example.com/source"}],
  "verification": {"status": "unchecked"},
  "warnings": [],
  "next_cursor": null
}
```

- Results include `structuredContent` that matches a declared `outputSchema`, and repeat it as compact JSON text for clients that only read text.
- Empty optional fields are left out to save tokens.
- Money is always in crore, converted through `Decimal`. Mistaking the scale is an easy error that's hard to spot.
- `verification.status` is `unchecked` unless a filing proves otherwise.

## Errors

Expected failures raise `TearsheetError`, which gives the agent a `code`, a `message`, a `retryable` flag and, where useful, a `hint`. The MCP SDK hides the message of any other exception, so don't raise plain exceptions for failures you can foresee.

Finding nothing isn't an error. It's a normal result with a note, because errors tend to make agents retry in a loop.

`BLOCKED` is never retryable. If a site refuses a request, Tearsheet stops. See [DATA-USE.md](DATA-USE.md).

## Protocol

Tearsheet targets MCP revision 2026-07-28 and also serves 2025-11-25 clients. `tests/test_protocol.py` checks both by driving the real server process. stdout is reserved for protocol messages, so diagnostics go to stderr.

## Planned tools

There will be 14 tools. Each accepts a company name, NSE symbol, BSE code or ISIN, so agents don't have to chain IDs between calls.

| Tool | Purpose | Status |
|---|---|---|
| `server_status` | Session, cache and filings health | Done |
| `find_company` | Resolve a company to all its identifiers | Planned |
| `company_snapshot` | One-call overview of a company | Planned |
| `get_financials` | Statements with fixed units and computed ratios | Planned |
| `get_operating_metrics` | Company-specific KPIs over time | Planned |
| `get_business_mix` | Revenue mix, market share and raw materials | Planned |
| `get_ownership` | Shareholding and fund flow trends | Planned |
| `screen_stocks` | Screens with validated fields and paging | Planned |
| `search_screen_fields` | Search the screener's field catalogue | Planned |
| `compare_companies` | Peer table computed on the server | Planned |
| `get_sector_view` | Sector, constituents and drivers | Planned |
| `search_filings` | Search your local filings | Planned |
| `read_filing` | Read page ranges from a local filing | Planned |
| `reconcile_figure` | Compare a figure with your filing | Planned |

Three prompts are planned too: `earnings_review`, `peer_comparison` and `thesis_check`.

## Lessons from tijori-finance-mcp

[tijori-finance-mcp](https://github.com/LaZZy0v0/tijori-finance-mcp) documented how Tijori's site behaves. Tearsheet's Tijori code will need to handle these:

- The screener silently ignores unknown parameters, which gives plausible but wrong results. Every parameter must be checked against an allow-list.
- Searching the screener's fields with a query only covers financials, so the full catalogue should be fetched once and searched locally.
- Screener result keys can contain HTML, and preset links can contain raw newlines and `%` signs.
- Pages poll for live prices, so waiting for the network to go idle never finishes.
