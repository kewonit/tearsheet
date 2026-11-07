# Roadmap

## Done

- Response envelope, error types and unit conversion
- Rate limiter and persistent local cache
- Session storage and browser sign-in, tested against a local page
- MCP server with `server_status`, tested on current and 2025 protocol revisions
- CI
- Checked which Tijori pages and data work on a paid account, and that requests need a browser. See [How Tijori behaves](ARCHITECTURE.md#how-tijori-behaves)

## Next: finish proving Tijori access

- [ ] Run `tearsheet login` against the real site and confirm the session cookie is what we expect
- [ ] Confirm a saved session works from a headless browser

## Then

**Tijori tools.** A browser-based client, a company resolver, then the data tools. Each upstream response is validated, so site changes fail loudly instead of returning bad data.

**Filings.** Index a local folder and read XBRL results (Regulation 33) and shareholding (Regulation 31) with a small in-house reader, tested on real filings. Add `search_filings`, `read_filing` and `reconcile_figure`, then turn on the `verification` field.

**Analytics.** A ratio library, `compare_companies`, the three prompts, and `as_of` queries for filings-based figures that avoid look-ahead bias.

**Evaluation.** About 30 analyst tasks with a held-out set, measuring correct answers, tool calls, tokens and errors. Tearsheet should match [tijori-finance-mcp](https://github.com/LaZZy0v0/tijori-finance-mcp) on accuracy and use clearly fewer calls and tokens.

## Out of scope

Live prices (run a broker's MCP alongside this one), placing orders, investment advice, hosted or shared deployments, and automated access to exchange websites.
