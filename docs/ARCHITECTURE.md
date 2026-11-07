# Architecture

tearsheet is a single Python process that an MCP client starts over stdio. It reads Tijori Finance through one headless Chromium, keeps a local SQLite cache, and reads filings from a folder on disk. It has no network listener and no shared state.

## Contents

- [Components](#components)
- [Module map](#module-map)
- [Tool call lifecycle](#tool-call-lifecycle)
- [Browser client](#browser-client)
- [Company resolution](#company-resolution)
- [Plan gating](#plan-gating)
- [Screens](#screens)
- [Financial statements](#financial-statements)
- [Filing verification](#filing-verification)
- [Sign-in](#sign-in)
- [Results](#results)
- [Errors](#errors)
- [Cache](#cache)
- [Upstream behaviour](#upstream-behaviour)
- [Protocol](#protocol)
- [Testing](#testing)

## Components

```mermaid
flowchart LR
    subgraph machine["Your machine"]
        mcpclient["MCP client"]
        subgraph proc["tearsheet process"]
            server["server.py<br/>MCPServer"]
            tools["tools/"]
            tijoriparse["sources/tijori/<br/>parsers, index, screener"]
            filingread["sources/filings/<br/>XBRL and PDF readers"]
            analytics["analytics/"]
            tclient["TijoriClient<br/>RateLimiter"]
        end
        chromium["Headless Chromium"]
        cache[("cache.sqlite3")]
        session[("session.json")]
        folder[("filings folder")]
        login["tearsheet login"]
    end
    tijori["tijorifinance.com"]

    mcpclient -->|"stdio"| server
    server --> tools
    tools --> tijoriparse
    tools --> analytics
    tools --> filingread
    tools --> cache
    tools --> tclient
    tijoriparse --> tclient
    tclient --> chromium
    session --> tclient
    chromium -->|"HTTPS"| tijori
    filingread --> folder
    login --> session
```

The only outbound traffic goes to `tijorifinance.com`. Filings are read from disk, and nothing contacts NSE or BSE.

## Module map

| Path | Responsibility |
|---|---|
| `server.py` | Builds the `MCPServer`, registers tools in a fixed order, implements `server_status`, closes the browser on exit |
| `cli.py` | `tearsheet` (serve, the default) and `tearsheet login` |
| `login.py` | Sign-in window and session capture |
| `prompts.py` | `earnings_review`, `peer_comparison`, `thesis_check` |
| `core/envelope.py` | Result envelope, compact text, 80,000-character cap |
| `core/errors.py` | `ErrorCode` and `ToolFailure` |
| `core/cache.py` | SQLite cache with an expiry per entry |
| `core/ratelimit.py` | Minimum spacing between request starts, and a concurrency cap |
| `core/session.py` | Writes and inspects the session file without exposing cookie values |
| `core/paths.py` | `TEARSHEET_HOME` and `TEARSHEET_FILINGS_DIR` |
| `core/units.py` | Converts rupees, lakh and million to crore |
| `analytics/ratios.py` | Growth, CAGR, and minimum, median and maximum |
| `sources/tijori/client.py` | Browser client |
| `sources/tijori/companies.py` | Company index and resolver |
| `sources/tijori/screener.py` | Guarded screens and presets |
| `sources/tijori/catalogue.py` | Screener field catalogue and query check |
| `sources/tijori/financials.py` | Statement builder and fund flow |
| `sources/tijori/company_page.py` | Snapshot, plan entitlements, metric list, revenue mix, market share |
| `sources/tijori/ownership.py` | Shareholding table |
| `sources/tijori/markets.py` | Market monitor tables and constituents |
| `sources/tijori/pages.py` | Shared HTML and embedded JSON parsing |
| `sources/filings/files.py` | Folder listing, path guard, size limits |
| `sources/filings/xbrl.py` | XBRL contexts and facts |
| `sources/filings/pdf.py` | PDF page text and search |
| `sources/filings/library.py` | Matches filings to a company and quarter |
| `tools/` | One module per tool family |

## Tool call lifecycle

`get_financials` for a quarterly statement, with an empty cache:

```mermaid
sequenceDiagram
    autonumber
    participant C as MCP client
    participant S as MCPServer
    participant T as get_financials
    participant I as Company index
    participant K as Cache
    participant B as TijoriClient
    participant X as Tijori

    C->>S: tools/call
    S->>T: arguments validated against the input schema
    T->>I: find_one(company)
    I->>K: get companies/index
    alt index cached
        K-->>I: companies
    else missing or expired
        I->>B: screen the whole main board, then SME
        B->>X: GET advanced_search
        X-->>B: rows with NSE symbol and BSE code
        I->>K: put companies/index, 7 days
    end
    I-->>T: exactly one company, or an error
    T->>K: get financials/slug
    K-->>T: miss
    T->>B: GET /company/slug/financials/
    B->>B: wait for a rate-limit slot
    B->>X: fetch() inside the browser page
    X-->>B: HTML with fin_tables_data
    B-->>T: status and body
    T->>K: put financials/slug, 6 hours
    T->>T: build the statement
    T->>T: verify quarters against local filings
    T-->>S: Envelope
    S-->>C: structuredContent and compact JSON text
```

Tools that never contact Tijori, such as `server_status` and the filing tools, don't start the browser.

## Browser client

Tijori answers plain HTTP clients with 403 and serves a normal browser. `TijoriClient` keeps one headless Chromium with an ordinary user agent and runs `fetch()` from a page on `/robots.txt`. Company pages poll for live prices, so leaving one open would keep sending requests.

```mermaid
stateDiagram-v2
    [*] --> Idle
    Idle --> Starting: first get()
    Starting --> Ready: Chromium launched and /robots.txt loaded
    Starting --> Idle: launch failed or refused, error raised
    Ready --> Ready: get(path) runs fetch() in the page
    Ready --> Idle: browser error, UPSTREAM_UNAVAILABLE
    Ready --> [*]: server exits, browser closed
    Idle --> [*]: server exits
```

- Callers that arrive during start-up share one start task. It is shielded, so a cancelled call can't leave a half-started browser that stops the server exiting.
- Every request takes a slot from `RateLimiter`: request starts are at least 1 second apart, with at most 2 in flight.
- Paths must start with `/`, so a request can't leave the site.
- The saved session is loaded only when its cookie exists and hasn't expired.

## Company resolution

Tijori's search matches names only, and company pages show no identifiers. Screener rows include the NSE symbol and BSE code, so two whole-market screens (main board and SME) build an index of about 6,700 companies, cached for 7 days.

```mermaid
flowchart TD
    query["Query"] --> sym{"Exact NSE symbol?"}
    sym -->|yes| found["Matches"]
    sym -->|no| code{"Digits matching a BSE code?"}
    code -->|yes| found
    code -->|no| slug{"Exact Tijori slug?"}
    slug -->|yes| found
    slug -->|no| long{"Normalised name has<br/>3 or more characters?"}
    long -->|no| search["Tijori company search<br/>up to 5 results"]
    long -->|yes| exact{"Exact normalised name?"}
    exact -->|yes| found
    exact -->|no| prefix{"Names starting with it?<br/>up to 5, shortest first"}
    prefix -->|yes| found
    prefix -->|no| search
    search -->|results| found
    search -->|none| missing["NOT_FOUND"]
    found --> one{"Exactly one?"}
    one -->|yes| company["Resolved company"]
    one -->|no| ambiguous["INVALID_INPUT<br/>listing the candidates"]
```

Normalising lowercases the text, removes anything that isn't a letter or digit, and drops a trailing "limited" or "ltd".

## Plan gating

Company pages embed `plan_details` and `overview_locks`, which describe the signed-in user's plan. A feature counts as unlocked only when its lock reads `historic: true`. A missing or malformed block counts as locked. Without a saved session, the plan is `free` and no request is made to find out.

```mermaid
flowchart TD
    page["Company page"] --> ent["Entitlements<br/>from plan_details and overview_locks"]
    ent --> metrics{"Metric history<br/>unlocked?"}
    metrics -->|yes| mfull["Return and cache the full series"]
    metrics -->|no| mlast["Return and cache the latest point only"]
    ent --> mix{"Revenue mix history<br/>unlocked?"}
    mix -->|yes| mget["Request the revenue mix history endpoint"]
    mix -->|no| mskip["No request, warning added"]
    ent --> share{"Market share history<br/>unlocked?"}
    share -->|yes| sfull["Keep the embedded series"]
    share -->|no| slast["Keep the latest value and date only"]
    preset["Preset marked paid"] --> tier{"Plan is free?"}
    tier -->|yes| refused["PLAN_REQUIRED, nothing sent"]
    tier -->|no| run["Run the preset"]
```

Tijori's metric endpoint returns the full series to any account, and every company page embeds the market share series. On a free plan the extra points are discarded before anything is cached or returned.

## Screens

Tijori ignores screener parameters it doesn't recognise and still returns 200, so a misnamed filter yields an unfiltered list. Three guards prevent that.

```mermaid
sequenceDiagram
    autonumber
    participant A as Agent
    participant T as screen_stocks
    participant F as Field catalogue
    participant X as Tijori

    A->>T: financial condition, business filter
    T->>F: load the catalogue, cached 7 days
    T->>T: mask known field names, longest first
    alt a name isn't in the catalogue
        T-->>A: INVALID_INPUT with the closest field names
    else every name is known
        T->>X: GET advanced_search with allow-listed parameters only
        X-->>T: rows, plus the financial_q and alternate_q it applied
        alt Tijori returns 500 or an error body
            T-->>A: INVALID_INPUT with Tijori's message
        else a filter sent is missing from the echo
            T-->>A: UPSTREAM_CHANGED, no rows
        else every filter applied
            T->>T: strip HTML from keys, attach units, sort, paginate
            T-->>A: Envelope with rows and next_cursor
        end
    end
```

1. **Allow-list.** `run_screen` takes named arguments only and builds the query string itself.
2. **Catalogue check.** Field names are matched longest first, because some contain "and", such as "Depreciation and Amortization". Whatever remains between operators must be a number.
3. **Echo check.** The query Tijori reports applying must contain each filter sent, ignoring spacing and case.

Presets run through Tijori's preset endpoint, the only one that applies a preset's business filter. Raw rows are cached for 30 minutes, keyed by a hash of the arguments.

## Financial statements

Statements come from the `fin_tables_data` JSON block on the financials page. `build_statement` applies these steps in order:

```mermaid
flowchart TD
    html["Financials page"] --> block["fin_tables_data"]
    block --> table{"Requested basis<br/>has figures?"}
    table -->|no| other["Use the other basis, with a warning"]
    table -->|yes| flatten
    other --> flatten["Flatten rows. Drop section headers.<br/>Drop rows with the wrong number of values, with a warning"]
    flatten --> label["Label a final column off the yearly pattern:<br/>TTM for income, Interim for cash flow"]
    label --> trim["Drop periods with no figures.<br/>Keep the last N periods"]
    trim --> lag["Warn if TTM ends before the latest quarter,<br/>or if a column is Interim"]
    lag --> units["Assign each row a unit"]
    units --> zeros["Blank zeros that a related row contradicts,<br/>with a warning"]
    zeros --> statement["FinancialStatement, as_of = last period's month end"]
```

Units come from the row name. Names containing `%` or "margin" are percent, "(Crs)" is crore, EPS is rupees per share, and names with "days" or "cycle" are days. Only names on an explicit list are multiples. An unrecognised row in a ratio section is `as_reported`. Elsewhere the default is crore.

Fund flow comes from its own endpoint and covers trailing windows of 1, 3, 5, 7 and 10 years.

## Filing verification

For a quarterly statement, `get_financials` compares revenue, profit before tax and net profit for each period with any matching XBRL filing.

```mermaid
sequenceDiagram
    autonumber
    participant T as get_financials
    participant L as Filing library
    participant D as Filings folder
    participant P as XBRL reader

    T->>L: verify each period and metric
    L->>D: list XBRL files inside the folder
    L->>P: parse, once per file version
    P-->>L: symbol, BSE code, basis, contexts, facts
    L->>L: keep filings for this company, basis and quarter end
    L->>P: amount for the metric's element names, three-month context
    P-->>L: value in crore and the element used
    L->>L: compare within the larger of 0.05 crore and 0.01 percent
    L-->>T: matched, mismatch or unchecked, with detail
```

| Rule | Reason |
|---|---|
| Elements are matched by local name, from an ordered list per metric | Templates differ. Banks file `ProfitLossForThePeriod`, insurers `NetPremiumIncome` |
| Only three-month contexts count for a quarter | A second-quarter filing also holds half-year figures |
| Values are converted from rupees to crore and shown with their period | Filings use rupees; Tijori uses crore |
| Consolidated net profit prefers profit attributable to owners. If that is filed as 0, total profit is used with a note | Companies without minority holders often file 0 there |
| Comparisons use the statutory figure | Picking whichever element matches Tijori would hide real differences |
| Tolerance is the larger of 0.05 crore and 0.01% | Tijori rounds to two decimals in crore |
| XML is parsed with `defusedxml` | Filings are untrusted input |
| Paths resolve inside the filings folder, including through symlinks. Files over 50 MB are refused | Agents supply the paths |

PDF search returns pages containing every word of the query, with exact phrases ranked first.

## Sign-in

```mermaid
sequenceDiagram
    autonumber
    actor U as User
    participant L as tearsheet login
    participant B as Chromium window
    participant X as Tijori
    participant F as session.json

    L->>B: launch and open Tijori's sign-in page
    U->>B: sign in
    B->>X: credentials, sent to Tijori only
    X-->>B: sessionid cookie
    loop every second, for up to 10 minutes
        L->>B: check the browser's cookies
    end
    L->>F: write storage state to an owner-only temp file, then rename
    L->>B: close
```

The loop watches the whole browser context, so redirects and popups during sign-in work. Closing every window cancels, and so does the time limit. Neither saves anything.

## Results

`core/envelope.py` defines the envelope every tool returns.

| Field | Type | Notes |
|---|---|---|
| `data` | object | Tool-specific, typed by the tool's output schema |
| `entity` | object | `name`, `nse`, `bse` |
| `as_of` | date | Date the data describes, such as the last period end or price date |
| `retrieved_at` | datetime | When the data was fetched from Tijori, which may be earlier than the call if cached |
| `units` | object | `currency` INR, `scale` crore |
| `sources` | list | `provider` with a `url` or a `document` |
| `verification` | object | `status` and `detail` |
| `warnings` | list | Anything that changes how to read the data |
| `next_cursor` | string | Present when more rows exist |

Empty top-level fields are omitted. Fields inside `data` are always present, and `null` there means the figure is missing. Results over 80,000 characters, about 20,000 tokens, are refused with a hint to narrow the request.

## Errors

Expected failures raise `ToolFailure`, which the SDK returns as a tool error with a JSON body: `code`, `message`, `retryable` and an optional `hint`. Any other exception reaches the agent only as a generic error, so foreseeable failures must use `ToolFailure`.

| Code | Retryable | Raised when |
|---|---|---|
| `SESSION_EXPIRED` | No | Tijori returns 401 |
| `BLOCKED` | No | Tijori returns 403. tearsheet stops and tells the agent not to retry |
| `RATE_LIMITED` | Yes | Tijori returns 429 |
| `UPSTREAM_UNAVAILABLE` | Yes | Tijori returns 502, 503 or 504, or the browser can't reach it |
| `UPSTREAM_CHANGED` | No | A page or response lacks the expected structure, or a screen filter wasn't applied |
| `INVALID_INPUT` | No | Bad arguments, an unknown screener field, an ambiguous company, a path outside the filings folder, or a result over the size cap |
| `NOT_FOUND` | No | No company, statement, sector or filing matches |
| `SETUP_REQUIRED` | No | Chromium isn't installed |
| `PLAN_REQUIRED` | No | A paid preset is requested on a free plan |

An empty result is not an error. It returns normally with a warning, because error responses push agents to retry.

## Cache

One SQLite file, `cache.sqlite3`, created owner-only. Entries are stored per dataset and key, each with its own expiry.

| Dataset | Key | Expiry | Contents |
|---|---|---|---|
| `companies` | `index` | 7 days | Name, slug, NSE symbol, BSE code, board |
| `catalogue` | `fields` | 7 days | Screener field names and units |
| `presets` | `all` | 24 hours | Preset names, queries and plan tier |
| `screens` | argument hash | 30 minutes | Raw screen rows |
| `company_pages` | slug | 1 hour | Parsed company page, with plan entitlements |
| `financials` | slug | 6 hours | `fin_tables_data` |
| `fund_flow` | slug | 6 hours | Fund flow response |
| `shareholding_pages` | slug | 6 hours | Shareholding page HTML |
| `operating_metrics` | company, metric, scope | 6 hours | Points kept for the plan: latest only on free |
| `markets` | `monitor` | 1 hour | Index, sector and conglomerate tables |
| `constituents` | kind and ID | 6 hours | Constituents and weights |

Revenue mix history is fetched on each call and not cached.

## Upstream behaviour

Tijori has no public API for this data. These behaviours were observed on the live site on 8 November 2026, many first documented by [tijori-finance-mcp](https://github.com/LaZZy0v0/tijori-finance-mcp).

| Behaviour | Handling |
|---|---|
| Plain HTTP clients get 403 | Requests run inside a headless browser that doesn't disguise itself |
| Pages poll for live prices, so the network never goes idle | The browser stays on `/robots.txt`. Navigation waits for `domcontentloaded` only |
| JSON is served as `text/html` | Bodies are parsed regardless of `Content-Type`. Non-JSON is `UPSTREAM_CHANGED` |
| Search matches names, not symbols. Pages show no identifiers | Local index built from screener rows |
| Unknown screener parameters are ignored with status 200 | Parameter allow-list |
| A dropped filter returns unfiltered rows | Echo check on `financial_q` and `alternate_q` |
| An unknown screener field returns 500 | Catalogue check before sending |
| Field search with a query covers financial fields only | Full catalogue fetched once and searched locally |
| Screener result keys contain HTML | Tags stripped |
| Preset links contain raw newlines and `%` | Presets read from their JSON endpoint, where the business filter is `alt_query` |
| The last income column can be trailing twelve months under a plain date | Labelled `TTM`. Warning if it ends before the latest quarter |
| The last cash flow column can cover an unstated period | Labelled `Interim`, with a warning |
| Section headers are stored as rows of zeros | Dropped |
| A missing figure can be stored as 0 | Blanked when a related row contradicts it, with a warning |
| Consolidated tables list periods before subsidiaries existed | Dropped, using `skip_report_dates` |
| A row can have fewer values than periods | Dropped, named in a warning |
| Some percentages are called ratios, such as CASA Ratio | Only listed names are multiples. Unknown ratio rows are `as_reported` |
| Chart points mark a month with a day that varies | Sorted by date and labelled by month, such as "Mar 2026" |
| Sectors and conglomerates have separate constituents endpoints. The wrong one returns an empty list | Endpoint chosen by kind |
| Search returns brands as well as companies | Only company entries kept |
| The API returns plan-locked history to free accounts | See [Plan gating](#plan-gating) |

Blocks that describe the signed-in user, such as `plan_details` and `user_prefs`, are never returned. Only `plan_details` and `overview_locks` are read, to work out entitlements.

## Protocol

- Uses the `mcp` Python SDK 2.3. Serves MCP 2026-07-28 clients and 2025-11-25 clients.
- `server/discover` and `tools/list` carry a one-hour cache hint. Tools register in a fixed order so the list is stable.
- Every tool is annotated `readOnlyHint: true`.
- stdout carries protocol messages only. Diagnostics go to stderr.
- [docs/TOOLS.md](TOOLS.md) is generated from the registered tools by `scripts/generate_tools_doc.py`, and a test fails if it is out of date.

## Testing

| Suite | Command | In CI | Scope |
|---|---|---|---|
| Unit | `uv run pytest` | Yes | Parsers on synthetic fixtures, guards, units, cache, envelope, filing readers, generated tool reference |
| Protocol | `uv run pytest` | Yes | Starts the real server process. Checks discovery, tool list stability, output schemas, older clients and a clean stdout |
| Browser | `uv run pytest -m browser` | No | Real Chromium against a local site: client start-up, refusals, concurrency, sign-in |
| Live | `uv run pytest -m live` | No | Tijori itself. Asserts behaviour and accounting identities, never specific figures |
| Evaluations | `uv run python evals/run.py` | Validation only | 30 analyst tasks, 10 held out, run through a real agent |

Fixtures are synthetic. No Tijori response or filing is committed. See [DATA-USE.md](DATA-USE.md).
