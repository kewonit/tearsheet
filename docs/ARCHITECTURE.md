# Architecture

Tearsheet is a Python MCP server that runs on your machine over stdio.

```
src/tearsheet/
  server.py           Tool and prompt registration
  cli.py              The tearsheet command
  login.py            Browser sign-in
  prompts.py          Research workflows
  core/               Envelope, errors, units, cache, rate limiter, session, paths
  analytics/          Growth, CAGR and peer statistics
  sources/tijori/     Browser client, page parsers, screener, company index
  sources/filings/    Local filings: safe file access, XBRL and PDF readers
  tools/              One module per tool family
```

## Responses

Every tool returns the same envelope (`core/envelope.py`), so an agent always knows where to look:

```json
{
  "data": {},
  "entity": {"name": "Example Ltd", "nse": "EXAMPLE", "bse": "500000"},
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
- Money is always in crore. Mistaking the scale is an easy error that's hard to spot, so rows in a statement also state their own unit, because statements mix crore, percentages, days and multiples.
- `verification.status` is `unchecked` unless a filing proves otherwise.

## Errors

Expected failures raise `TearsheetError`, which gives the agent a `code`, a `message`, a `retryable` flag and, where useful, a `hint`. The MCP SDK hides the message of any other exception, so don't raise plain exceptions for failures you can foresee.

Finding nothing isn't an error. It's a normal result with a note, because errors tend to make agents retry in a loop.

`BLOCKED` is never retryable. If a site refuses a request, Tearsheet stops. See [DATA-USE.md](DATA-USE.md).

## Protocol

Tearsheet targets MCP revision 2026-07-28 and also serves 2025-11-25 clients. `tests/test_protocol.py` checks both by driving the real server process. stdout is reserved for protocol messages, so diagnostics go to stderr.

## Tools

There are 14 tools, listed in the [README](../README.md#tools). Each accepts a company name, NSE symbol or BSE code, so agents don't chain IDs between calls. Tools register in a fixed order, which helps clients cache the list.

## Paid features

Company pages state the session's plan and which features it unlocks. Tearsheet reads that, and anything unclear counts as locked. Without a paid plan it keeps only the latest value of operating metrics, never requests revenue mix history, and refuses premium presets. Tijori's own page scripts do the same, and its API is more generous than its pages, so the pages are the rule Tearsheet follows.

## Filings

Filings are files the user downloads. Paths an agent supplies are resolved inside the filings folder and refused otherwise, including through symlinks. XML is parsed with defusedxml. XBRL elements are matched by local name, a quarter is chosen by its three-month context, and dimensioned breakdowns are never taken as totals. This part is experimental until it has been tested on real filings.

## How Tijori behaves

Tested on 8 November 2026 with a signed-in paid account. [tijori-finance-mcp](https://github.com/LaZZy0v0/tijori-finance-mcp) documented much of this first, and Tearsheet's Tijori code must handle all of it.

**Requests have to come from a browser.** A plain HTTP client gets a 403, while an ordinary headless browser that identifies itself honestly is served normally. Tearsheet will keep one headless browser open and make requests from inside a page.

**Nothing tested needs rendering.** Company, shareholding, raw material, macro and market pages carry their data in the HTML, and the financials page embeds its statements as JSON in a script tag. The popular screens page is the exception, as JavaScript builds it, but it gets its data from a JSON endpoint that can be called directly. Parsing what comes back avoids loading pages and clicking tabs, which keeps each call fast. The IDs that operating metrics, fund flow and revenue history need are in the company page.

**Keep the browser somewhere quiet.** Real pages poll for live prices, so Tearsheet's browser sits on `/robots.txt`, which makes no background requests, and closes when the server does.

**Symbols need a local index.** Company search matches names, not symbols, and company pages show no identifiers at all. Screener rows do carry the NSE symbol and BSE code, so one market-wide screen builds an index that Tearsheet refreshes weekly. A lookup tries the exact symbol, the BSE code, the slug, the name, then Tijori's search. Tijori exposes no ISINs.

**Financial data has traps that produce confident wrong numbers:**

- The last income column can be trailing twelve months under a plain date. It's labelled `TTM` when it breaks the yearly pattern.
- That column can lag the latest quarterly results, which gets a warning.
- A final cash flow column off the year end looks like about twelve months, but Tijori doesn't say what it covers, so it's labelled `Interim` with a warning.
- Tijori calls some percentages ratios, such as CASA Ratio. Only names on an explicit list count as multiples, and an unknown row in a ratio section is `as_reported`, never assumed to be crore.
- A figure missing from a recent quarter can be stored as 0, beside rows that prove it isn't. These are blanked with a warning, never replaced with a guess.
- Section headers are stored as rows of zeros, so they're dropped.
- Periods before a company had subsidiaries are blank in consolidated tables, so they're dropped too.
- A row can have fewer values than there are periods. It's left out and named in a warning, because its alignment can't be known.

**Company pages hold more than they show.** Named JSON blocks include `company_details_data`, `ratios_table`, `peers_table_data` and `corporate_actions`. `ratios_table` gives each ratio an explicit unit, which is better than working one out from its name, so `company_snapshot` should read it. Blocks such as `plan_details` and `user_prefs` describe the signed-in user and must be left alone.

**Most data needs no sign-in.** Company pages, shareholding, operating metrics, fund flow, revenue history and screens all work anonymously. Some presets are marked with a premium `plan_tier`. Small companies can have no operating metrics at all, which is a normal result rather than an error.

**Don't trust `Content-Type`.** Company search returns valid JSON labelled `text/html`, so responses are judged by their body.

**The screener needs guarding in three ways:**

- Unknown parameters are silently ignored. Sending the business filter under the wrong name returned about 25 times as many companies, with status 200 and no error. Every parameter must be on an allow-list.
- The response echoes the query it applied in `financial_q` and `alternate_q`. Tearsheet must compare these with what it sent, and return an error rather than results if a filter was dropped.
- An unknown field returns a 500. Check fields against the cached catalogue first, so agents get a useful error and Tijori doesn't get bad queries.

**Other details:**

- Searching the screener's fields with a query only covers financials, so fetch the full catalogue once and search it locally.
- Screener result keys can contain HTML. Preset links on the page contain raw newlines and `%` signs, so read presets from the JSON endpoint instead, where the business filter is called `alt_query`.
- The markets page has separate tables for headline indices, sectors and conglomerates, and sectors and conglomerates each have their own constituents endpoint. Using the wrong one returns an empty list rather than an error.
- Company search also returns `brands` and `InActive` entries, which need filtering out or handling.
- Operating metrics responses include peer data alongside the company's own series, which `compare_companies` can use.
- Pages poll for live prices, so waiting for the network to go idle never finishes.
