# Roadmap

## Done in 0.1.0

- 14 tools and 3 prompts. The 11 Tijori tools are tested against the live site, with accounting identities checked on real data
- Browser client, guarded screener, company index and plan-aware access to paid data, checked against real free and premium accounts
- Filings layer, checked against real integrated filings from four kinds of company and a real annual report
- Evaluation harness with tuning and held-out tasks

## Next

- [ ] Run `tearsheet login` against Tijori's real sign-in. What a premium plan unlocks has been checked from a signed-in browser.
- [ ] Fetch market share history for paid plans. It's detected as unlocked but not requested yet.
- [ ] Check filing templates not yet tested, such as general insurers, and results filed before 2025
- [ ] Run the full evaluation, and compare against [tijori-finance-mcp](https://github.com/LaZZy0v0/tijori-finance-mcp) once it can be run with a login
- [ ] Revisit the held-out filing task, whose check only accepts one of several correct routes
- [ ] Publish to PyPI and an MCP registry

## Out of scope

Live prices (run a broker's MCP alongside this one), placing orders, investment advice, hosted or shared deployments, and automated access to exchange websites.
