# Roadmap

## Done in 0.1.0

- 14 tools and 3 prompts. The 11 Tijori tools are tested against the live site, with accounting identities checked on real data
- Browser client, guarded screener, company index and plan-aware access to paid data
- Experimental filings layer, tested on made-up filings
- Evaluation harness with tuning and held-out tasks

## Next

- [ ] Run `tearsheet login` against Tijori's real sign-in, and check what a paid plan unlocks
- [ ] Test the filing tools on real filings downloaded by hand, and confirm the XBRL element names they rely on
- [ ] Run the full evaluation, and compare against [tijori-finance-mcp](https://github.com/LaZZy0v0/tijori-finance-mcp) once it can be run with a login
- [ ] Revisit the held-out filing task, whose check only accepts one of several correct routes
- [ ] Publish to PyPI and an MCP registry

## Out of scope

Live prices (run a broker's MCP alongside this one), placing orders, investment advice, hosted or shared deployments, and automated access to exchange websites.
