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

## Собственные Telegram-аккаунты (отдельный модуль)

Опциональный Telethon-модуль работает **от лица вашего аккаунта**, а не бота. Он доступен только в настоящем режиме с паролем: публичное и локальное демо не принимают StringSession и не подключаются к Telegram. Вход по номеру/коду/2FA **в панели не реализован**: сначала создайте авторизованную Telethon StringSession на доверенном компьютере. Подключайте лишь аккаунт, который принадлежит вам. Общий пароль TeleFlow открывает доступ ко **всем** подключённым аккаунтам; отдельных ролей операторов нет.

1. Получите `api_id` и `api_hash` вашего приложения на [my.telegram.org](https://my.telegram.org/) (раздел API development tools), установите необязательные зависимости. Бот продолжит работать без них.
2. Сгенерируйте отдельный ключ Fernet **один раз** и храните его вне репозитория, отдельно от резервной копии базы. Для уже существующей базы ограничьте права до `600`; каталог базы не должен быть доступен на запись другим пользователям.
3. На доверенном компьютере создайте сессию командой ниже; Telethon запросит номер, код Telegram и, если включён, пароль 2FA. Вывод команды — секрет полного доступа: не записывайте его в чат, скриншот, историю команд, CI или журнал. Не запускайте команду в публичном Preview.

```sh
cd apps/teleflow
umask 077
python3 -m venv .venv
.venv/bin/python -m pip install -r requirements-accounts.txt
export TELEFLOW_API_ID='<задайте локально>'
export TELEFLOW_API_HASH='<задайте локально>'
export TELEFLOW_PASSWORD='<задайте локально: длинный уникальный пароль>'
export TELEFLOW_SESSION_KEY="$(.venv/bin/python -c 'from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())')"
# При повторном запуске используйте СОХРАНЁННЫЙ ключ, а не генерируйте новый.
if [ -e teleflow.sqlite3 ]; then chmod 600 teleflow.sqlite3; fi
.venv/bin/python server.py
```

```sh
# В отдельном терминале доверенного компьютера, с теми же API_ID/API_HASH:
.venv/bin/python - <<'PY'
import os
from telethon import TelegramClient
from telethon.sessions import StringSession

with TelegramClient(StringSession(), int(os.environ['TELEFLOW_API_ID']), os.environ['TELEFLOW_API_HASH']) as client:
    print(StringSession.save(client.session))  # Секрет: вставить ТОЛЬКО в свою панель, затем закрыть терминал.
PY
```

После входа в защищённую панель откройте «Telegram-аккаунты», вставьте StringSession в скрытое поле и нажмите «Подключить». Не разрешайте менеджеру паролей сохранять это поле; TeleFlow очищает его после запроса и не записывает сессию в хранилище браузера. Сервер проверит, что это авторизованный **пользовательский**, не бот-аккаунт, и сохранит сессию в SQLite только в виде Fernet-шифротекста; API не возвращает сессию. Для работы выберите аккаунт и один из **первых 100 уже существующих** диалогов: видны последние 40 сообщений, медиа не загружаются. Ручной ответ в личном диалоге возможен, только если среди последних 100 сообщений есть входящее от собеседника (в том числе медиа); публикация разрешена в собственном канале (или группе, создателем которой вы являетесь). Нельзя искать получателей по имени/номеру, рассылать произвольным пользователям или использовать `/start` бота как согласие на сообщения от личного аккаунта. Ограничение ручной отправки: минимум 5 секунд между попытками и не более 30 попыток в час на аккаунт; FloodWait Telegram устанавливает дополнительную паузу. Лимиты — защита от ошибок, **не разрешение на массовые отправки**.

«Отозвать сессию» запрашивает `log_out` в Telegram и удаляет запись только после подтверждения; если Telegram недоступен, запись остаётся. «Только удалить локально» не отзывает действующую сессию — после этого вручную завершите её в Telegram → Настройки → Устройства. Кнопка «Выйти» завершает только сеанс панели, но **не** отзывает Telegram-сессию: открытые вкладки получают сигнал выхода; при возврате к вкладке и периодически доступ проверяется повторно. Если ключ Fernet потерян или заменён, приложение остановится с ошибкой расшифровки существующих сессий: восстановите исходный ключ из отдельной защищённой резервной копии. Ключ и копию SQLite нельзя публиковать. При компрометации завершите все соответствующие сеансы в Telegram независимо от состояния панели. Сервер использует один поток asyncio для Telethon и не запускает второй процесс на той же базе; планового «прогрева» или массовых задач нет. При тайм-ауте исход отправки может быть неизвестен: запись сохранится после перезапуска, и новые сообщения **в этот диалог** будут заблокированы до явного подтверждения проверки в Telegram. Подтверждение не означает, что доставка удалась, и не отправляет ничего. При известном отказе Telegram (например, FloodWait/429) новая попытка после паузы требует **нового идентификатора запроса**: тот же `request_id` останется отклонённым.

Браузер сохраняет **только** `request_id` и ID аккаунта/диалога в `sessionStorage` текущей вкладки до выяснения результата; не сохраняет текст ответа или StringSession. После потери ответа он проверяет состояние попытки на сервере: `sent` подтверждает, что повторять её нельзя; `unknown` требует проверки чата в Telegram и явного снятия блокировки; если запись не найдена, перед новым ответом тоже требуется ручная проверка. После закрытия вкладки или явного выхода (`POST /api/signout`) локальный идентификатор исчезнет: сверяйте сообщения в Telegram, прежде чем отправлять тот же текст из новой вкладки. Серверная блокировка неизвестных исходов действует независимо от вкладки и переживает перезапуск.

HTTP API этого модуля — `/api/accounts`, `/api/accounts/{id}/dialogs`, `/api/accounts/{id}/dialogs/{dialog_id}` и `/reply` (для ответа нужен уникальный `request_id` в каноническом формате 8-4-4-4-12); `GET` истории возвращает список `unresolved` с состоянием попытки. `GET /api/accounts/{id}/dialogs/{dialog_id}/replies/{request_id}` возвращает её сохранённый статус, не выполняя повторную отправку. После ручной проверки Telegram `POST /api/accounts/{id}/dialogs/{dialog_id}/review` с полями `request_id` (из `unresolved`) и `confirm=checked_in_telegram` снимает блокировку этой попытки. `DELETE /api/accounts/{id}` отзывает сеанс, а `POST /api/accounts/{id}/forget` с `{"confirm":"forget_without_revocation"}` удаляет только локально. Все маршруты требуют входа в панель даже на localhost, изменяющие запросы — того же Origin/Referer. Идентификаторы аккаунтов и диалогов в JSON отдаются строками во избежание потери точности 64-битных ID в браузере.

Сопоставление пятнадцати заявленных модулей GramGPT с допустимыми сценариями и фактическими возможностями TeleFlow: [MODULES.md](MODULES.md).

## API and operating notes

The JSON API is under `/api`; `GET /api/health` is a simple health check and `GET /api/status` reports bot, AI, account-integration availability, demo, and auth state. When `TELEFLOW_PASSWORD` is set, the browser logs in through `POST /api/login`; the server uses an in-memory, expiring, HttpOnly/SameSite session cookie. Five failed logins within ten minutes from one direct peer address lock that address out for fifteen minutes (`429` with `Retry-After`); a successful login resets the counter. The limit is keyed by the address the server actually sees, so behind a reverse proxy every visitor shares one address — add proxy-level rate limiting too. The database persists campaigns, subscribers, opt-in state, inbox messages, rules, update offsets, and queued delivery state.

Campaign broadcasts target only contacts who sent `/start`; channel/group campaigns target only chats the administrator added and the bot passed verification for. There is no member scraping, importing, or unsolicited direct messaging. Incoming private messages do not opt a person in unless they use `/start`. Keyword replies only go to opted-in contacts. Respect Telegram's current limits and applicable messaging/privacy laws.

Schedules accept UTC ISO timestamps (for example `2026-11-03T15:30:00Z`). `POST /api/campaigns/{id}/cancel` returns a scheduled campaign to draft before activation, so a mistaken plan can be stopped ahead of time; a campaign already dispatching cannot be cancelled this way. Dispatch is rate-limited and persisted in SQLite. A restart resumes queued work; if the process stops after Telegram accepted a send but before SQLite recorded it, that single delivery can be retried, so delivery is at-least-once around a crash. Transient campaign and keyword-reply failures (including Telegram `retry_after`/429, 5xx and network timeouts) are persisted with bounded backoff and retried up to eight attempts; permanent errors count as failures. When a campaign has failed deliveries, an operator can explicitly retry only those recipients from the campaign list; successful deliveries are never requeued, and unsubscribed contacts are skipped. A scheduled campaign with no recipients returns to draft. An operator can also opt a subscriber out through `PATCH /api/subscribers/{id}` with `{"opted_in": false}`; pending keyword replies for that chat are cancelled immediately, and consent can only be restored by the subscriber sending `/start` again. Manual inbox replies return transient API failures to the caller with `Retry-After` when Telegram provides it, so the client can retry explicitly. Only one Teleflow process may own a database at a time; a sidecar advisory lock prevents a second worker from recovering active sends. AI drafts, replies, campaigns, and stored inbox history should be treated as sensitive; protect, back up, and delete the SQLite file according to your retention policy.

The server does not configure webhooks, verify ownership of a public channel, provide multi-user roles, handle media uploads, or guarantee analytics beyond its locally recorded campaign delivery attempts. Use BotFather / Telegram controls to revoke a compromised bot token. Telethon sessions have separate revocation controls as described above.

## Tests

```sh
python3 -m unittest discover -s tests -v
```

Install `requirements-accounts.txt` first for account integration tests; without those optional packages, the bot-only suite still runs and account-specific tests are skipped.

With Ruff 0.8.1 and Node.js installed, run the same local lint and browser syntax checks used during development:

```sh
ruff check server.py accounts.py account_transport.py tests
ruff format --check server.py accounts.py account_transport.py tests
node --check static/app.js
```
