# Changelog

## Unreleased

## 0.2.0 (2026-11-08)

### Added

- Market share history on paid plans, read from the series every company page embeds. Free plans get the latest value and its date. The series is neither returned nor cached.
- `docs/TOOLS.md`, generated from the registered tools by `scripts/generate_tools_doc.py`. A test fails when it is out of date.
- Release workflow publishing to PyPI through trusted publishing, triggered by a `v*` tag that must match the package version.

### Changed

- Filing tools checked against real integrated filings for a manufacturer, an NBFC, a bank and a life insurer, and a real annual report. They're no longer experimental.
- Recognises the element names banks and life insurers file. When profit attributable to owners is filed as 0, total profit is used, with a note.
- Match tolerance is now the larger of ₹5 lakh and 0.01%. The previous 0.5% would have passed a ₹60 crore gap.
- Quarterly verification also checks profit before tax. This reports Tijori's non-statutory figure for banks and insurers as a mismatch.
- Filing values are shown in crore with their period. Segment breakdowns are excluded.
- PDF search returns pages containing every word of the query, exact phrases first.
- Operating metric and revenue mix histories are labelled by month, such as "Mar 2026", and sorted by date. Tijori marks the same month with different days, which made yearly figures look like different period types.
- Paid-plan features checked on a real premium account: plan detection, metric history, revenue mix history, and all five premium presets, with their filters confirmed applied.
- README, architecture and contributor docs rewritten. Architecture now includes component, sequence and flow diagrams.

### Removed

- The unused `NOT_SIGNED_IN` error code. Signing in is optional, and Tijori refusals use `SESSION_EXPIRED` or `BLOCKED`.

## 0.1.0 (2026-11-08)

First release.

### Tools

- `find_company`, `company_snapshot`, `get_financials`, `get_ownership`, `get_operating_metrics`, `get_business_mix`, `screen_stocks`, `search_screen_fields`, `compare_companies`, `get_sector_view` and `server_status`.
- Experimental filing tools: `search_filings`, `read_filing` and `reconcile_figure`, for filings you download yourself.
- Prompts: `earnings_review`, `peer_comparison` and `thesis_check`.

### Behaviour

- Requests to Tijori run inside one headless browser, at most one a second, from a page that makes no background requests.
- Trailing-twelve-month and interim columns are labelled. Contradicted zeros are blanked with a warning.
- Screens are checked against the query Tijori reports applying. Unknown fields are rejected before sending.
- Data Tijori reserves for paid plans is requested only when the session's plan unlocks it.
- Results are capped at 80,000 characters, about 20,000 tokens.

### Known limits

- `tearsheet login` untested against Tijori's sign-in.
- Filing tools tested only on synthetic filings.
- No ISINs, because Tijori doesn't expose them.
