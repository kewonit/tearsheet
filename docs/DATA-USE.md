# Data use

tearsheet reads data owned by Tijori Finance and filings published through the exchanges. This page sets out what those owners allow and the rules the code follows as a result.

This isn't legal advice. Terms change, and you're responsible for how you use your own accounts.

## Tijori Finance

- Tijori's [FAQ](https://www.tijorifinance.com/faq/) says its public developer APIs are limited and directs enterprise users to its support team.
- Its [Terms of Use](https://www.tijorifinance.com/terms-of-use) allow copying and storing content for personal, non-commercial use, and restrict reproduction and distribution. They don't address automated access.
- Its `robots.txt` allows AI crawlers. That is permission to crawl, not a licence to the data.

tearsheet reads the same pages and endpoints your browser loads on Tijori's site. They're undocumented and may change or stop working. tearsheet is built for one person using their own account for their own research.

## NSE and BSE

- NSE's [Terms of Use](https://www.nseindia.com/nse-terms-of-use) prohibit systematic or automated data collection from its website and app, including scraping.
- BSE's disclaimers restrict reproduction of its content without consent.

tearsheet never contacts nseindia.com or bseindia.com. You download filings yourself and tearsheet reads them from disk, so figures can only be verified against filings you've added.

NSE runs its own [MCP server](https://www.nseindia.com/nse-mcp), which you can connect to your assistant separately.

## Rules

Every change to tearsheet must keep to these.

| Rule | In the code |
|---|---|
| **Your account only** | stdio only. No hosted mode, network listener or shared cache |
| **No third-party data in the repository** | Fixtures are synthetic. The cache and sessions live in `~/.tearsheet` |
| **No evasion** | Ordinary headless Chromium. No stealth plugins, disguised user agents or challenge solving. A 403 raises `BLOCKED`, which is not retryable |
| **No automated exchange access** | No code contacts NSE or BSE |
| **Limited request rate** | Request starts at least 1 second apart, at most 2 at once |
| **Plan limits respected** | Data a plan locks on Tijori's pages is never requested, and is discarded before caching when a response includes it. See [ARCHITECTURE.md](ARCHITECTURE.md#plan-gating) |
| **Licensing limits respected** | Tijori shows only changes in commodity prices, so tearsheet doesn't derive the prices |
| **No advice** | Facts and calculations only. Tijori's own opinions, forecasts and red or green flags are excluded. No order placement |
| **Credentials kept private** | Sessions are stored owner-only. Cookie values are never logged or returned |

If you own any of this data and object to how tearsheet uses it, [open an issue](https://github.com/kewonit/tearsheet/issues).
