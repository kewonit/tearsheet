# Roadmap

## Done

| Version | Work |
|---|---|
| 0.1.0 | 14 tools and 3 prompts. Browser client, guarded screener, company index, plan gating, filing readers, evaluation harness |
| 0.2.0 | Filing tools checked against real integrated filings from a manufacturer, an NBFC, a bank and a life insurer. Paid-plan features checked on a real premium account. Market share history on paid plans. Generated tool reference. Release workflow |

## Next

- [ ] Run `tearsheet login` against Tijori's production sign-in page
- [ ] Test filing templates not yet covered: general insurers, and results filed before 2025
- [ ] Run the full evaluation, and compare against [tijori-finance-mcp](https://github.com/LaZZy0v0/tijori-finance-mcp)
- [ ] Rewrite the held-out filing task's check to accept every correct route
- [ ] Publish to PyPI and an MCP registry

## Out of scope

- Live prices. Run a broker's MCP server alongside tearsheet
- Placing orders
- Investment advice
- Hosted or shared deployments
- Automated access to exchange websites
