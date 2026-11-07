# How tearsheet uses data

tearsheet sits between an AI agent and data other people own, so its design starts from what those owners allow. This page explains those limits and the rules that follow from them.

This is not legal advice. Terms change, and you are responsible for how you use your own accounts. Read the terms yourself.

## Tijori Finance

Tijori's [FAQ](https://www.tijorifinance.com/faq/) says its public developer APIs are limited and points enterprise needs to its support team. tearsheet therefore reads the same pages and data your browser loads when you are signed in. These are undocumented and could change or stop working at any time.

Tijori's [Terms of Use](https://www.tijorifinance.com/terms-of-use) limit copying and storing its content to your own personal, non-commercial use, and restrict reproducing or distributing it. They don't mention automated access. Tijori's `robots.txt` allows AI crawlers, but that is permission to crawl, not a licence to the data.

So tearsheet is built for one person, using their own account, for their own research.

## NSE and BSE

NSE's [Terms of Use](https://www.nseindia.com/nse-terms-of-use) prohibit systematic or automated data collection from its website and app, including scraping. BSE's disclaimers restrict reproducing its content without consent.

**tearsheet never contacts nseindia.com or bseindia.com.** Instead, you download the filings you want by hand and put them in your filings folder, and tearsheet reads them locally. This means figures can only be checked against filings you've added.

NSE also runs its [own MCP server](https://www.nseindia.com/nse-mcp), which you can connect to your assistant separately. NSE provides it for information and learning, not for trading, advice or commercial products.

## The rules

These apply to all code in this project.

1. **Your account only.** tearsheet runs on your machine with your own login. It has no hosted mode, no shared cache and no network server.
2. **No third-party data in the repository.** Test fixtures are made up. Never commit real responses, cached data or filings.
3. **No evasion.** No stealth plugins, disguised user agents, challenge solving or routes around access controls. If a site refuses a request, the tool reports it and stops.
4. **No automated exchange access.** See above.
5. **Be polite.** By default, about one request a second and at most two at a time.
6. **Respect licensing limits.** Tijori can only show changes in commodity prices, so tearsheet doesn't try to work out the prices.
7. **No advice.** Facts and calculations only, with no buy or sell calls and no order placement. Tijori's own opinions, forecasts and red or green flags are left out too.
8. **Respect plan limits.** tearsheet returns only what your Tijori plan shows on the page. Tijori's API returns some data, such as metric history, even to free users whose pages lock it. tearsheet neither requests nor stores that data unless your session's plan unlocks it.
9. **Keep credentials private.** Sessions are stored owner-only, outside the repository, and cookie values are never logged or returned.

If an owner of this data objects to how tearsheet works, please [open an issue](https://github.com/kewonit/tearsheet/issues).
