# Teleflow

## Быстрый старт

Запустите из каталога `apps/teleflow`. Демо-режим не отправляет сообщения в Telegram:

```sh
python3 server.py --demo
```

Для работы с ботом задайте переменные окружения локально, заменив подсказки своими значениями. Не добавляйте реальные токены или пароли в README или Git:

```sh
export TELEFLOW_BOT_TOKEN='<задайте локально>'
export TELEFLOW_PASSWORD='<задайте локально>'
python3 server.py
```

Откройте <http://127.0.0.1:3000/>. Подробные требования к настройке бота и безопасному размещению описаны ниже.

Teleflow is a small, independent Telegram campaign web app. Its backend uses only the Python standard library; the browser UI is served from `apps/teleflow/static/`.

## Run locally

Python 3.10 or newer is recommended. From this directory:

```sh
python3 server.py
```

Open <http://127.0.0.1:3000/>. The database is created as `teleflow.sqlite3` next to `server.py`; override it with `--db /path/to/file.sqlite3`. `--host` and `--port` change the bind address and port. The default bind is loopback-only.

The UI can be run without a bot in demo mode:

```sh
python3 server.py --demo
```

Loopback demo mode supports draft/rule editing and can use `OPENAI_API_KEY` if configured, but disables Telegram polling and sends. It does not create fake subscribers or success statistics. Due scheduled campaigns remain queued as scheduled until run in real mode.

An unauthenticated demo bound to a non-loopback address (for example `--host 0.0.0.0 --demo`) is treated as a public demo, not a remote real deployment: it gets a new temporary SQLite database on every start and removes it on shutdown. It never uses `TELEFLOW_DB`, an explicit `--db`, `TELEFLOW_BOT_TOKEN`, or `OPENAI_API_KEY`; Telegram and AI are disabled even if those variables happen to be present. An explicit shared database is rejected. All visitors to this demo share its temporary drafts and rules until restart, so do not enter personal information or confidential content. Set `TELEFLOW_PUBLIC_ORIGIN` to the exact public origin when available; without it, only this isolated, no-secrets public demo accepts requests through arbitrary valid hostnames so managed previews remain reachable.

## Real Telegram setup

1. Create a bot with Telegram's `@BotFather` and keep its token private.
2. Set `TELEFLOW_BOT_TOKEN` in the server process environment. Never put it in browser code, a URL, or the database.
3. Start the app on loopback. Open the bot in Telegram and explicitly send `/start` to opt in. `/stop` opts out immediately; the app will not queue future campaign sends or replies to that contact.
4. For a group, supergroup, or channel campaign, add the bot as an administrator with message/post permission, then add the chat in the app. Teleflow verifies bot membership before saving and again when scheduling or sending.
5. Set a strong `TELEFLOW_PASSWORD` and the canonical `TELEFLOW_PUBLIC_ORIGIN` before exposing a real server beyond loopback. Non-loopback real deployments require both and require an HTTPS origin, such as `https://teleflow.example.com`. The HTTP `Host` and browser `Origin` must match this exact origin; forwarded host/protocol headers do not override it. Use HTTPS at a trusted reverse proxy, preserve the public `Host`, firewall the backend port, and keep the password out of source control.

Example (replace placeholders locally; do not commit real values):

```sh
export TELEFLOW_BOT_TOKEN='<set locally>'
export TELEFLOW_PASSWORD='<set locally>'
export TELEFLOW_PUBLIC_ORIGIN='https://teleflow.example.com'
python3 server.py --host 0.0.0.0 --port 3000
```

On loopback, no public-origin setting is required; the server accepts only loopback `Host` values on its listening port. For non-loopback requests, configured origins are checked on static pages and all API endpoints. State-changing API calls also require a same-origin `Origin` or `Referer`; requests with missing or cross-site origins are rejected.

`OPENAI_API_KEY` optionally enables AI draft suggestions; `OPENAI_MODEL` selects the model (default `gpt-4o-mini`). Prompts and supplied context are sent to OpenAI when this feature is used. Do not include data you are not allowed to share with that provider.

The app uses Telegram `getUpdates` polling; if the bot has a webhook configured, Telegram will reject polling. Disable that webhook through the Bot API before starting Teleflow. Polling is intended for this app alone; do not run another consumer of the same bot updates concurrently.

## API and operating notes

The JSON API is under `/api`; `GET /api/health` is a simple health check and `GET /api/status` reports bot, AI, demo, and auth state. When `TELEFLOW_PASSWORD` is set, the browser logs in through `POST /api/login`; the server uses an in-memory, expiring, HttpOnly/SameSite session cookie. The database persists campaigns, subscribers, opt-in state, inbox messages, rules, update offsets, and queued delivery state.

Campaign broadcasts target only contacts who sent `/start`; channel/group campaigns target only chats the administrator added and the bot passed verification for. There is no member scraping, importing, or unsolicited direct messaging. Incoming private messages do not opt a person in unless they use `/start`. Keyword replies only go to opted-in contacts. Respect Telegram's current limits and applicable messaging/privacy laws.

Schedules accept UTC ISO timestamps (for example `2026-11-03T15:30:00Z`). Dispatch is rate-limited and persisted in SQLite. A restart resumes queued work; if the process stops after Telegram accepted a send but before SQLite recorded it, that single delivery can be retried, so delivery is at-least-once around a crash. Transient campaign and keyword-reply failures (including Telegram `retry_after`/429, 5xx and network timeouts) are persisted with bounded backoff and retried up to eight attempts; permanent errors count as failures. When a campaign has failed deliveries, an operator can explicitly retry only those recipients from the campaign list; successful deliveries are never requeued, and unsubscribed contacts are skipped. A scheduled campaign with no recipients returns to draft. Manual inbox replies return transient API failures to the caller with `Retry-After` when Telegram provides it, so the client can retry explicitly. Only one Teleflow process may own a database at a time; a sidecar advisory lock prevents a second worker from recovering active sends. AI drafts, replies, campaigns, and stored inbox history should be treated as sensitive; protect, back up, and delete the SQLite file according to your retention policy.

The server does not configure webhooks, verify ownership of a public channel, provide multi-user roles, handle media uploads, or guarantee analytics beyond its locally recorded campaign delivery attempts. Use BotFather / Telegram controls to revoke a compromised bot token.

## Tests

```sh
python3 -m unittest discover -s tests -v
```

With Ruff 0.8.1 and Node.js installed, run the same local lint and browser syntax checks used during development:

```sh
ruff check server.py tests/test_server.py
ruff format --check server.py tests/test_server.py
node --check static/app.js
```
