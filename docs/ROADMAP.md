# Roadmap

## Done

- Response envelope, error types and unit conversion
- Rate limiter and persistent local cache
- Session storage and browser sign-in, tested against a local page
- MCP server with `server_status`, tested on current and 2025 protocol revisions
- CI

## Next: prove Tijori access

Nothing below is worth building until this works.

- [ ] Run sign-in against the real site and confirm the session cookie is what we expect
- [ ] Find out which Tijori pages and data still work as documented
- [ ] Decide whether requests need a browser, or plain HTTP with the session is enough

## Then

**Tijori tools.** A company resolver, then the data tools. Each upstream response is validated, so site changes fail loudly instead of returning bad data.

**Filings.** Index a local folder and read XBRL results (Regulation 33) and shareholding (Regulation 31) with a small in-house reader, tested on real filings. Add `search_filings`, `read_filing` and `reconcile_figure`, then turn on the `verification` field.

**Analytics.** A ratio library, `compare_companies`, the three prompts, and `as_of` queries for filings-based figures that avoid look-ahead bias.

**Evaluation.** About 30 analyst tasks with a held-out set, measuring correct answers, tool calls, tokens and errors. Tearsheet should match [tijori-finance-mcp](https://github.com/LaZZy0v0/tijori-finance-mcp) on accuracy and use clearly fewer calls and tokens.

## Out of scope

Live prices (run a broker's MCP alongside this one), placing orders, investment advice, hosted or shared deployments, and automated access to exchange websites.
