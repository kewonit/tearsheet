# Changelog

## Unreleased

### Filings

- Checked against real integrated filings for a manufacturer, an NBFC, a bank and a life insurer, and a real annual report. The filing tools are no longer experimental.
- Recognises the element names banks and life insurers use, and falls back to total profit when a filing gives 0 for profit attributable to owners.
- Matching now allows only rounding differences. The old tolerance would have passed a ₹60 crore gap.
- Quarterly verification also checks profit before tax, which surfaces Tijori's non-statutory figure for banks and insurers.
- Filing values show money in crore with their period, and leave out breakdowns.
- PDF search finds pages with every word of the query, ranking exact phrases first.

## 0.1.0 (2026-11-08)

First release.

### Tools

- `find_company`, `company_snapshot`, `get_financials`, `get_ownership`, `get_operating_metrics`, `get_business_mix`, `screen_stocks`, `search_screen_fields`, `compare_companies`, `get_sector_view` and `server_status`.
- Experimental filing tools: `search_filings`, `read_filing` and `reconcile_figure`, for filings you download by hand.
- Prompts: `earnings_review`, `peer_comparison` and `thesis_check`.

### Behaviour worth knowing

- Requests to Tijori run inside one headless browser, at about one a second, from a page that makes no background requests.
- Trailing-twelve-month and interim columns are labelled, and contradicted zeros are blanked with a warning.
- Screens are checked against the query Tijori says it applied, and unknown fields are rejected before they're sent.
- Data Tijori keeps for paid plans is only requested when your session's plan unlocks it.
- Results are capped at about 20,000 tokens.

### Known limits

- `tearsheet login` hasn't been tested against Tijori's real sign-in.
- The filing tools have been tested only on made-up filings.
- No ISINs, because Tijori doesn't expose them.
