# Security

## Reporting a vulnerability

Use GitHub's [private vulnerability reporting](https://github.com/kewonit/tearsheet/security/advisories/new). Don't open a public issue, and don't include real cookies or session files.

In scope:

- Anything that could expose `session.json` or its cookie values
- Reading files outside the filings folder
- Requests to hosts other than `tijorifinance.com`
- Parsing flaws in the XBRL or PDF readers

## What tearsheet stores

| File | Contents | Permissions |
|---|---|---|
| `~/.tearsheet/session.json` | Tijori session cookies | Owner-only, written atomically |
| `~/.tearsheet/cache.sqlite3` | Cached Tijori data | Owner-only |
| `~/.tearsheet/` | The folder holding both | Owner-only when tearsheet creates it |

`session.json` grants access to your Tijori account. Treat it like a password: don't share it, paste it into an issue, or give it to an AI assistant. `server_status` warns if other users can read it.

If it may have leaked, sign out of Tijori on all devices where Tijori allows it, delete the file, and run `tearsheet login` again.

## Untrusted content

Filings and the key events on company pages are written by third parties. They can contain text aimed at an AI agent. tearsheet labels them as source material and its tools only read, but your agent may have other tools connected that act. Treat that text as data.

The filing tools resolve every path inside the filings folder, including through symlinks, and refuse anything outside it. XML is parsed with `defusedxml`. Files over 50 MB are refused.
