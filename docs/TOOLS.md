# Tools reference

Generated from the server's tool definitions by `scripts/generate_tools_doc.py`.
Every tool returns the response envelope described in [ARCHITECTURE.md](ARCHITECTURE.md#response-envelope); `data` holds the type named below.

## `find_company`

Find a listed Indian company and its identifiers.

Accepts an NSE symbol, a BSE code, a company name or part of one. Returns each match's name, NSE symbol, BSE code and slug, plus what it matched on. Use this when a name is ambiguous or you need the identifiers. Other tools accept the same input, so you don't need to call this first. An empty match list means nothing was found. ISINs aren't available. Check the warnings: if the input wasn't a real symbol, they give the actual one.

| Parameter | Type | Required | Default |
|---|---|---|---|
| `query` | string (1–200 chars) | yes | — |

Returns `CompanySearch`.

## `get_financials`

Get a company's financial statement.

Covers income statements, balance sheets, cash flow, quarterly results, ratios, and fund flow, which shows where money came from and went over trailing windows of 1 to 10 years. Accepts an NSE symbol, BSE code or name. Every row states its own unit, because statements mix crore, percent, days and multiples. A unit of as_reported means the unit isn't known, so don't assume one. A period starting TTM is trailing twelve months, and one starting Interim covers an unstated period, so don't compare either directly with annual columns. A blank value means no reliable figure exists. If the requested basis doesn't exist, the other is returned with a warning. Set detail to full for line items. Quarterly figures are checked against any matching filing in the filings folder, and the verification field says how that went. Other statements are Tijori's figures, unchecked.

| Parameter | Type | Required | Default |
|---|---|---|---|
| `company` | string (1–200 chars) | yes | — |
| `statement` | one of `income`, `balance_sheet`, `cash_flow`, `quarterly`, `ratios`, `fund_flow` | no | `"income"` |
| `basis` | one of `consolidated`, `standalone` | no | `"consolidated"` |
| `detail` | one of `concise`, `full` | no | `"concise"` |
| `periods` | integer (≥ 1, ≤ 12) | no | `5` |

Returns `FinancialStatement`.

## `company_snapshot`

Get a one-call overview of a listed Indian company.

Returns identifiers, status, size class, delayed price, market cap, P/E, PEG, key ratios with their units, multi-year ROE and margin averages, price changes up to one year, recent dividends and dated key events. Use it first when asked about a company in general. It contains facts only: Tijori's own opinions and forecasts are deliberately left out. Longer-term returns are omitted because their basis isn't stated.

| Parameter | Type | Required | Default |
|---|---|---|---|
| `company` | string (1–200 chars) | yes | — |

Returns `Snapshot`.

## `get_ownership`

Get a company's shareholding pattern by quarter.

Returns promoter, institutional and public holdings in percent, the number of shareholders, and each row's change over the last period. Concise gives categories. Full adds the named holders that companies must disclose above 1%. Use it for questions about who owns a company or how ownership is changing.

| Parameter | Type | Required | Default |
|---|---|---|---|
| `company` | string (1–200 chars) | yes | — |
| `detail` | one of `concise`, `full` | no | `"concise"` |
| `periods` | integer (≥ 1, ≤ 12) | no | `4` |

Returns `Ownership`.

## `get_operating_metrics`

Get a company's operating metrics, such as capacity, volumes or deal wins.

These are company-specific KPIs beyond the financial statements. Many smaller companies have none, which returns an empty list. Use metric to filter by part of a name. Each metric has its own unit. With Tijori's free plan only the latest value is available, matching what Tijori's own pages show, and history needs a paid plan.

| Parameter | Type | Required | Default |
|---|---|---|---|
| `company` | string (1–200 chars) | yes | — |
| `metric` | string (≤ 100 chars) | no | `None` |
| `limit` | integer (≥ 1, ≤ 20) | no | `8` |

Returns `OperatingMetrics`.

## `get_business_mix`

Get how a company's business splits, and its market shares.

Returns the latest revenue split by product, geography, segment or other breakdowns Tijori tracks, each in percent, plus market share figures. Every market share has its own as-of date, and some are years old, so always check it. History of the revenue split and of market shares needs a paid Tijori plan.

| Parameter | Type | Required | Default |
|---|---|---|---|
| `company` | string (1–200 chars) | yes | — |

Returns `BusinessMix`.

## `search_screen_fields`

Find exact screener field names, with their units and periods.

screen_stocks needs exact field names, such as "ROCE" or "3yr Avg ROCE". Search by words, like "roce" or "debt equity". Also lists the preset screens when query is "presets". Searching is local and cheap.

| Parameter | Type | Required | Default |
|---|---|---|---|
| `query` | string (1–100 chars) | yes | — |
| `limit` | integer (≥ 1, ≤ 50) | no | `15` |

Returns `FieldSearch`.

## `screen_stocks`

Find listed companies matching conditions, across the whole market.

financial is a condition on exact field names, such as "Market Capitalization > 1000 AND ROCE > 20%". Find names with search_screen_fields. business filters on what companies do, such as "makes Steel" or "has plant in Gujarat". Or pass a preset name instead. Results are checked to make sure Tijori applied every filter. Use sort_by with a column name, and pass next_cursor back to page through results. Main board by default; set sme for SME listings.

| Parameter | Type | Required | Default |
|---|---|---|---|
| `financial` | string (≤ 500 chars) | no | `None` |
| `business` | string (≤ 300 chars) | no | `None` |
| `preset` | string (≤ 100 chars) | no | `None` |
| `latest_results_only` | boolean | no | `False` |
| `superstar_investors` | boolean | no | `False` |
| `sme` | boolean | no | `False` |
| `sort_by` | string (≤ 100 chars) | no | `None` |
| `descending` | boolean | no | `True` |
| `limit` | integer (≥ 1, ≤ 100) | no | `25` |
| `cursor` | string (≤ 20 chars) | no | `None` |

Returns `ScreenResult`.

## `compare_companies`

Compare 2 to 6 companies side by side on valuation, returns and growth.

Growth is calculated here from annual figures, never from TTM or interim columns: revenue and net profit growth in the latest year, and three-year revenue CAGR. Growth is blank where it isn't defined, such as from a loss. Also gives the minimum, median and maximum of each figure. For a company's own peer list, see company_snapshot.

| Parameter | Type | Required | Default |
|---|---|---|---|
| `companies` | list of string (1–200 chars) (at least 2, at most 6) | yes | — |

Returns `Comparison`.

## `get_sector_view`

Get market indices, Tijori's sector indices or conglomerate groups.

Without a name, lists them with their price changes over periods such as 1D, 1M and 1YR*. With a name, such as "Private Bank" or "Adani", also returns that sector's or group's constituent companies and their weights. Tijori marks some periods with an asterisk and doesn't say what it means, so mention that when quoting them.

| Parameter | Type | Required | Default |
|---|---|---|---|
| `kind` | one of `indices`, `sectors`, `conglomerates` | no | `"sectors"` |
| `name` | string (≤ 100 chars) | no | `None` |
| `limit` | integer (≥ 1, ≤ 100) | no | `30` |

Returns `SectorView`.

## `search_filings`

Search the filings the user downloaded into their filings folder.

Searches PDF text, such as annual reports and concall transcripts, and the figure names in XBRL results filings. company narrows to one company by NSE symbol, BSE code or name. Works offline. Returns the file and page of each hit, which read_filing can then open.

| Parameter | Type | Required | Default |
|---|---|---|---|
| `query` | string (2–100 chars) | yes | — |
| `company` | string (≤ 100 chars) | no | `None` |
| `limit` | integer (≥ 1, ≤ 30) | no | `10` |

Returns `FilingSearch`.

## `read_filing`

Read part of one filing from the filings folder.

Give a file name as search_filings returns it. For a PDF, pages picks a page or range such as "4" or "4-6", up to ten pages. For an XBRL results filing, returns the company, period and basis, and its figures with money in crore and each figure's own period, because a filing for a second quarter also holds half-year figures. Breakdowns are left out. Only files inside the filings folder can be read.

| Parameter | Type | Required | Default |
|---|---|---|---|
| `file` | string (1–300 chars) | yes | — |
| `pages` | string (≤ 20 chars) | no | `"1-3"` |

Returns `FilingContent`.

## `reconcile_figure`

Check a quarterly figure from Tijori against the company's own filing.

metric is revenue, profit_before_tax or net_profit, and period is a quarter such as "Sep 2026". Needs that quarter's XBRL results filing in the filings folder. Returns both figures in crore and their difference. The verification status says matched, mismatch or unchecked, with the reason.

| Parameter | Type | Required | Default |
|---|---|---|---|
| `company` | string (1–200 chars) | yes | — |
| `metric` | one of `revenue`, `profit_before_tax`, `net_profit` | yes | — |
| `period` | string (≤ 20 chars) | yes | — |
| `basis` | one of `consolidated`, `standalone` | no | `"consolidated"` |

Returns `Reconciliation`.

## `server_status`

Report whether tearsheet is ready to use.

Shows whether a Tijori session is saved, what is in the local cache and how many filings the user has added. Call this first if another tool fails, or when the user asks why data is missing. It works offline and never contacts Tijori, so a saved session may still have been ended on Tijori's side. It returns no company data.

No parameters.

Returns `ServerStatus`.

# Prompts

| Prompt | Arguments | Purpose |
|---|---|---|
| `earnings_review` | `company` | Review a company's latest quarterly and annual results. |
| `peer_comparison` | `company` | Compare a company with its closest listed peers. |
| `thesis_check` | `company`, `thesis` | Check a claim about a company against the data. |
