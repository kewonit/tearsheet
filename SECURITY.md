# Security

Tearsheet stores a live Tijori login session on your machine, so please report anything that could expose it.

## Reporting a problem

Please use GitHub's [private vulnerability reporting](https://github.com/kewonit/tearsheet/security/advisories/new) rather than a public issue. Don't include real cookies or session files.

## Protecting your session

- Your session is in `~/.tearsheet/session.json`, readable only by your user. Treat it like a password.
- Never paste it into an issue, a chat or an AI assistant.
- If you think it has leaked, sign out of Tijori on all devices if you can, then run `tearsheet login` again.

## Filings and prompt injection

Filings and other documents are written by third parties and could contain text aimed at manipulating an AI agent. Treat them as source material, not instructions. Tearsheet's tools only read data, but your agent may have other tools connected.
