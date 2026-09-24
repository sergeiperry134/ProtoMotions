#!/usr/bin/env python3
# SPDX-License-Identifier: Apache-2.0
"""Telegram bot workspace with optional, separate user-account transport."""

from __future__ import annotations

import argparse
import datetime as dt
import http.cookies
import http.server
import ipaddress
import json
import logging
import math
import mimetypes
import os
import re
import secrets
import socket
import sqlite3
import stat
import threading
import tempfile
import time
import urllib.error
import urllib.parse
import urllib.request
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Iterator

from accounts import AccountError, AccountManager

try:
    import fcntl
except ImportError:  # pragma: no cover - exercised on Windows only
    fcntl = None

try:
    import msvcrt
except ImportError:  # pragma: no cover - exercised on POSIX only
    msvcrt = None


BASE_DIR = Path(__file__).resolve().parent
MAX_BODY_BYTES = 64 * 1024
MAX_CAMPAIGN_BODY = 4096
SESSION_COOKIE = "teleflow_session"
SESSION_TTL_SECONDS = 12 * 60 * 60
LOGIN_FAILURE_WINDOW_SECONDS = 600
MAX_LOGIN_FAILURES = 5
LOGIN_LOCKOUT_SECONDS = 900
MAX_DELIVERY_ATTEMPTS = 8
LOG = logging.getLogger("teleflow")


def utc_now() -> dt.datetime:
    return dt.datetime.now(dt.timezone.utc)


def iso_utc(value: dt.datetime | None = None) -> str:
    value = value or utc_now()
    if value.tzinfo is None:
        value = value.replace(tzinfo=dt.timezone.utc)
    return (
        value.astimezone(dt.timezone.utc)
        .replace(microsecond=0)
        .isoformat()
        .replace("+00:00", "Z")
    )


class DatabaseInUseError(RuntimeError):
    """Raised when another Teleflow process already owns the SQLite database."""


def _normalized_host(host: str) -> str:
    if not host or any(
        character.isspace() or ord(character) < 33 for character in host
    ):
        raise ValueError("Invalid hostname")
    if "%" in host:
        raise ValueError("Scoped IP addresses are not supported")
    try:
        return ipaddress.ip_address(host).compressed.casefold()
    except ValueError:
        normalized = host.rstrip(".").encode("idna").decode("ascii").casefold()
        if (
            not normalized
            or len(normalized) > 253
            or any(
                not re.fullmatch(r"[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?", label)
                for label in normalized.split(".")
            )
        ):
            raise ValueError("Invalid hostname") from None
        return normalized


def _parse_authority(authority: str, scheme: str) -> tuple[str, int]:
    if not authority or any(
        character.isspace() or ord(character) < 33 for character in authority
    ):
        raise ValueError("Invalid authority")
    if any(character in authority for character in "\\/@?#"):
        raise ValueError("Invalid authority")
    parsed = urllib.parse.urlsplit("//" + authority)
    if (
        parsed.path
        or parsed.query
        or parsed.fragment
        or parsed.username is not None
        or parsed.password is not None
    ):
        raise ValueError("Invalid authority")
    hostname = parsed.hostname
    if hostname is None:
        raise ValueError("Invalid authority")
    normalized = _normalized_host(hostname)
    port = parsed.port
    if port is None:
        port = 443 if scheme == "https" else 80
    if not 1 <= port <= 65535:
        raise ValueError("Invalid port")
    return normalized, port


def normalize_public_origin(value: str) -> str:
    parsed = urllib.parse.urlsplit(value)
    scheme = parsed.scheme.casefold()
    if (
        scheme not in {"http", "https"}
        or not parsed.netloc
        or parsed.path not in {"", "/"}
        or parsed.query
        or parsed.fragment
        or parsed.username is not None
        or parsed.password is not None
    ):
        raise ValueError(
            "TELEFLOW_PUBLIC_ORIGIN must be an HTTP(S) origin without a path"
        )
    hostname, port = _parse_authority(parsed.netloc, scheme)
    host_text = f"[{hostname}]" if ":" in hostname else hostname
    default_port = 443 if scheme == "https" else 80
    port_text = f":{port}" if port != default_port else ""
    return f"{scheme}://{host_text}{port_text}"


class APIError(Exception):
    def __init__(self, status: int, message: str, retry_after: int | None = None):
        super().__init__(message)
        self.status = status
        self.message = message
        self.retry_after = retry_after


class TelegramError(Exception):
    def __init__(
        self, message: str, retry_after: int | None = None, transient: bool = False
    ):
        super().__init__(message)
        self.message = message
        self.retry_after = retry_after
        self.transient = transient


class TelegramClient:
    """Minimal Bot API transport. It never includes the token in an error."""

    def __init__(self, token: str, timeout: float = 12.0):
        self._token = token
        self.timeout = timeout

    def call(self, method: str, params: dict[str, Any] | None = None) -> Any:
        if not self._token:
            raise TelegramError("TELEFLOW_BOT_TOKEN is not configured")
        if not re.fullmatch(r"[A-Za-z][A-Za-z0-9]+", method):
            raise TelegramError("Invalid Telegram method")
        url = f"https://api.telegram.org/bot{self._token}/{method}"
        body = json.dumps(params or {}).encode("utf-8")
        request = urllib.request.Request(
            url,
            data=body,
            headers={"Content-Type": "application/json", "Accept": "application/json"},
            method="POST",
        )
        http_error_code = None
        try:
            with urllib.request.urlopen(request, timeout=self.timeout) as response:
                payload = json.loads(response.read().decode("utf-8"))
        except urllib.error.HTTPError as error:
            http_error_code = error.code
            try:
                payload = json.loads(error.read().decode("utf-8"))
            except (ValueError, UnicodeDecodeError):
                raise TelegramError(
                    "Telegram request failed",
                    transient=error.code == 429 or error.code >= 500,
                ) from None
        except (
            urllib.error.URLError,
            TimeoutError,
            OSError,
            ValueError,
            UnicodeDecodeError,
        ):
            raise TelegramError(
                "Could not reach the Telegram Bot API", transient=True
            ) from None

        if not isinstance(payload, dict) or payload.get("ok") is not True:
            description = (
                payload.get("description") if isinstance(payload, dict) else None
            )
            if not isinstance(description, str) or not description.strip():
                description = "Telegram request failed"
            description = description.replace(self._token, "[redacted]")[:300]
            parameters = (
                payload.get("parameters") if isinstance(payload, dict) else None
            )
            retry_after = (
                parameters.get("retry_after") if isinstance(parameters, dict) else None
            )
            if not isinstance(retry_after, int) or retry_after < 0:
                retry_after = None
            code = payload.get("error_code") if isinstance(payload, dict) else None
            transient = (
                retry_after is not None
                or code == 429
                or (isinstance(code, int) and code >= 500)
                or http_error_code == 429
                or (http_error_code is not None and http_error_code >= 500)
            )
            raise TelegramError(
                description, retry_after=retry_after, transient=transient
            )
        return payload.get("result")


class OpenAIClient:
    def __init__(self, api_key: str, model: str = "gpt-4o-mini", timeout: float = 30.0):
        self._api_key = api_key
        self.model = model
        self.timeout = timeout

    def draft(self, prompt: str, tone: str, kind: str, context: str) -> str:
        user_content = f"Campaign type: {kind}\nTone: {tone}\nRequest: {prompt}"
        if context:
            user_content += f"\nContext: {context}"
        payload = {
            "model": self.model,
            "messages": [
                {
                    "role": "system",
                    "content": (
                        "Write one concise, useful Telegram message draft. Return only the draft text. "
                        "Do not invent discounts, facts, or claims not supplied by the user."
                    ),
                },
                {"role": "user", "content": user_content},
            ],
        }
        request = urllib.request.Request(
            "https://api.openai.com/v1/chat/completions",
            data=json.dumps(payload).encode("utf-8"),
            headers={
                "Authorization": f"Bearer {self._api_key}",
                "Content-Type": "application/json",
                "Accept": "application/json",
            },
            method="POST",
        )
        try:
            with urllib.request.urlopen(request, timeout=self.timeout) as response:
                result = json.loads(response.read().decode("utf-8"))
        except (
            urllib.error.URLError,
            TimeoutError,
            OSError,
            ValueError,
            UnicodeDecodeError,
        ):
            raise APIError(502, "The AI draft request failed") from None
        try:
            text = result["choices"][0]["message"]["content"]
        except (KeyError, IndexError, TypeError):
            raise APIError(
                502, "The AI provider returned an invalid response"
            ) from None
        if not isinstance(text, str) or not text.strip():
            raise APIError(502, "The AI provider returned an empty draft")
        return text.strip()


class RateLimiter:
    def __init__(self, interval: float = 0.05):
        self.interval = max(0.0, interval)
        self._lock = threading.Lock()
        self._last_sent = 0.0

    def wait(self) -> None:
        with self._lock:
            delay = self.interval - (time.monotonic() - self._last_sent)
            if delay > 0:
                time.sleep(delay)
            self._last_sent = time.monotonic()


class TeleflowService:
    def __init__(
        self,
        db_path: str | os.PathLike[str],
        *,
        bot_token: str | None = None,
        openai_api_key: str | None = None,
        openai_model: str = "gpt-4o-mini",
        password: str | None = None,
        demo: bool = False,
        telegram: Any | None = None,
        ai_client: Any | None = None,
        send_interval: float = 0.05,
        clock: Any = utc_now,
        public_origin: str | None = None,
        public_demo: bool = False,
        account_api_id: int | None = None,
        account_api_hash: str | None = None,
        account_session_key: str | None = None,
        account_gateway: Any | None = None,
    ):
        self.db_path = Path(db_path).resolve()
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self.password = password or None
        self.demo = bool(demo)
        self.public_demo = bool(public_demo)
        if self.public_demo and (not self.demo or self.password is not None):
            raise ValueError(
                "Public demo mode must be unauthenticated and Telegram-disabled"
            )
        self.accounts: AccountManager | None = None
        account_configured = any(
            (account_api_id is not None, account_api_hash, account_session_key)
        )
        if account_configured:
            if self.demo or not self.password:
                raise ValueError(
                    "Account mode requires TELEFLOW_PASSWORD and non-demo mode"
                )
            if (
                isinstance(account_api_id, bool)
                or not isinstance(account_api_id, int)
                or account_api_id < 1
                or not account_api_hash
                or not re.fullmatch(r"[a-fA-F0-9]{32}", account_api_hash)
                or not account_session_key
            ):
                raise ValueError(
                    "Account mode needs TELEFLOW_API_ID, TELEFLOW_API_HASH and TELEFLOW_SESSION_KEY"
                )
        self.public_origin = (
            normalize_public_origin(public_origin) if public_origin else None
        )
        if self.public_demo:
            bot_token = None
            openai_api_key = None
            telegram = None
            ai_client = None
        self.telegram = (
            telegram if telegram is not None else TelegramClient(bot_token or "")
        )
        self._telegram_configured = bool(bot_token) or telegram is not None
        self.ai_client = (
            ai_client
            if ai_client is not None
            else (
                OpenAIClient(openai_api_key, openai_model) if openai_api_key else None
            )
        )
        self._ai_configured = self.ai_client is not None
        self._clock = clock
        self._rate_limiter = RateLimiter(send_interval)
        self._consent_lock = threading.RLock()
        self._poll_lock = threading.Lock()
        self._bot_status_lock = threading.Lock()
        self._bot_checked_at = 0.0
        self._bot_status = {
            "connected": False,
            "username": None,
            "error": "TELEFLOW_BOT_TOKEN is not configured"
            if not self._telegram_configured
            else None,
        }
        self._bot_id: int | None = None
        self._sessions: dict[str, float] = {}
        self._sessions_lock = threading.Lock()
        self._login_lock = threading.Lock()
        self._login_failures: dict[str, list[dt.datetime]] = {}
        self._login_locks: dict[str, dt.datetime] = {}
        self._database_lock_fd: int | None = None
        self._database_lock_path = self.db_path.with_name(self.db_path.name + ".lock")
        if account_configured:
            if self.db_path.parent.stat().st_mode & 0o022:
                raise ValueError(
                    "Account mode requires a directory without group/other write access"
                )
            try:
                descriptor = os.open(
                    self.db_path, os.O_CREAT | os.O_EXCL | os.O_RDWR, 0o600
                )
            except FileExistsError:
                mode = self.db_path.stat().st_mode
                if not stat.S_ISREG(mode) or mode & 0o077:
                    raise ValueError(
                        "Account mode requires a private SQLite database (chmod 600)"
                    ) from None
            else:
                os.close(descriptor)
        self._acquire_database_lock()
        try:
            self._init_db()
            if account_configured:
                if account_gateway is None:
                    from account_transport import TelethonGateway

                    account_gateway = TelethonGateway(account_api_id, account_api_hash)
                try:
                    self.accounts = AccountManager(
                        self, account_session_key, account_gateway
                    )
                except BaseException:
                    account_gateway.close()
                    raise
        except BaseException:
            self.close()
            raise

    def _acquire_database_lock(self) -> None:
        descriptor = os.open(
            self._database_lock_path,
            os.O_CREAT | os.O_RDWR,
            0o600,
        )
        try:
            if fcntl is not None:
                fcntl.flock(descriptor, fcntl.LOCK_EX | fcntl.LOCK_NB)
            else:  # pragma: no cover - exercised on Windows only
                if os.fstat(descriptor).st_size == 0:
                    os.write(descriptor, b"0")
                    os.fsync(descriptor)
                os.lseek(descriptor, 0, os.SEEK_SET)
                msvcrt.locking(descriptor, msvcrt.LK_NBLCK, 1)
        except (BlockingIOError, OSError):
            os.close(descriptor)
            raise DatabaseInUseError(
                f"Another Teleflow process already owns {self.db_path}"
            ) from None
        self._database_lock_fd = descriptor

    def close(self) -> None:
        accounts = self.accounts
        self.accounts = None
        try:
            if accounts is not None:
                accounts.close()
        finally:
            descriptor = self._database_lock_fd
            if descriptor is not None:
                self._database_lock_fd = None
                try:
                    if fcntl is not None:
                        fcntl.flock(descriptor, fcntl.LOCK_UN)
                    else:  # pragma: no cover - exercised on Windows only
                        os.lseek(descriptor, 0, os.SEEK_SET)
                        msvcrt.locking(descriptor, msvcrt.LK_UNLCK, 1)
                finally:
                    os.close(descriptor)

    def _now(self) -> dt.datetime:
        value = self._clock()
        if value.tzinfo is None:
            value = value.replace(tzinfo=dt.timezone.utc)
        return value.astimezone(dt.timezone.utc)

    def _now_iso(self) -> str:
        return iso_utc(self._now())

    @contextmanager
    def _connection(self) -> Iterator[sqlite3.Connection]:
        connection = sqlite3.connect(self.db_path, timeout=15.0)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA foreign_keys = ON")
        try:
            yield connection
        finally:
            connection.close()

    @contextmanager
    def _transaction(self) -> Iterator[sqlite3.Connection]:
        with self._connection() as connection:
            connection.execute("BEGIN IMMEDIATE")
            try:
                yield connection
                connection.commit()
            except BaseException:
                connection.rollback()
                raise

    def _init_db(self) -> None:
        with self._connection() as connection:
            connection.execute("PRAGMA journal_mode = WAL")
            connection.executescript(
                """
                CREATE TABLE IF NOT EXISTS settings (
                    key TEXT PRIMARY KEY,
                    value TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS subscribers (
                    chat_id INTEGER PRIMARY KEY,
                    first_name TEXT NOT NULL DEFAULT '',
                    username TEXT,
                    opted_in INTEGER NOT NULL DEFAULT 0 CHECK (opted_in IN (0, 1)),
                    joined_at TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS chats (
                    chat_id TEXT PRIMARY KEY,
                    title TEXT NOT NULL,
                    username TEXT,
                    type TEXT NOT NULL,
                    verified_at TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS campaigns (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    title TEXT NOT NULL,
                    body TEXT NOT NULL,
                    target_type TEXT NOT NULL CHECK (target_type IN ('subscribers', 'chat')),
                    chat_id TEXT,
                    status TEXT NOT NULL CHECK (status IN ('draft', 'scheduled', 'sending', 'completed', 'partial', 'failed')),
                    scheduled_at TEXT,
                    created_at TEXT NOT NULL,
                    sent_count INTEGER NOT NULL DEFAULT 0,
                    failed_count INTEGER NOT NULL DEFAULT 0,
                    recipient_count INTEGER NOT NULL DEFAULT 0
                );
                CREATE TABLE IF NOT EXISTS campaign_deliveries (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    campaign_id INTEGER NOT NULL REFERENCES campaigns(id) ON DELETE CASCADE,
                    chat_id TEXT NOT NULL,
                    status TEXT NOT NULL CHECK (status IN ('queued', 'sending', 'sent', 'failed', 'skipped')),
                    message_id INTEGER,
                    error TEXT,
                    next_attempt_at TEXT,
                    attempt_count INTEGER NOT NULL DEFAULT 0,
                    created_at TEXT NOT NULL,
                    sent_at TEXT,
                    failed_at TEXT,
                    UNIQUE (campaign_id, chat_id)
                );
                CREATE INDEX IF NOT EXISTS campaign_deliveries_queue_idx
                    ON campaign_deliveries(status, campaign_id, id);
                CREATE TABLE IF NOT EXISTS messages (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    chat_id TEXT NOT NULL,
                    direction TEXT NOT NULL CHECK (direction IN ('in', 'out')),
                    body TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    telegram_message_id INTEGER
                );
                CREATE INDEX IF NOT EXISTS messages_chat_idx ON messages(chat_id, id);
                CREATE TABLE IF NOT EXISTS rules (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    keyword TEXT NOT NULL,
                    reply TEXT NOT NULL,
                    enabled INTEGER NOT NULL DEFAULT 1 CHECK (enabled IN (0, 1)),
                    hits INTEGER NOT NULL DEFAULT 0
                );
                CREATE TABLE IF NOT EXISTS processed_updates (
                    update_id INTEGER PRIMARY KEY,
                    processed_at TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS reply_queue (
                    update_id INTEGER PRIMARY KEY REFERENCES processed_updates(update_id) ON DELETE CASCADE,
                    chat_id INTEGER NOT NULL,
                    body TEXT NOT NULL,
                    status TEXT NOT NULL CHECK (status IN ('pending', 'sending', 'sent', 'failed', 'cancelled')),
                    next_attempt_at TEXT,
                    attempt_count INTEGER NOT NULL DEFAULT 0,
                    created_at TEXT NOT NULL,
                    error TEXT
                );
                """
            )
            delivery_columns = {
                row["name"]
                for row in connection.execute(
                    "PRAGMA table_info(campaign_deliveries)"
                ).fetchall()
            }
            if "next_attempt_at" not in delivery_columns:
                connection.execute(
                    "ALTER TABLE campaign_deliveries ADD COLUMN next_attempt_at TEXT"
                )
            if "attempt_count" not in delivery_columns:
                connection.execute(
                    "ALTER TABLE campaign_deliveries ADD COLUMN attempt_count INTEGER NOT NULL DEFAULT 0"
                )
            reply_columns = {
                row["name"]
                for row in connection.execute(
                    "PRAGMA table_info(reply_queue)"
                ).fetchall()
            }
            if "next_attempt_at" not in reply_columns:
                connection.execute(
                    "ALTER TABLE reply_queue ADD COLUMN next_attempt_at TEXT"
                )
            if "attempt_count" not in reply_columns:
                connection.execute(
                    "ALTER TABLE reply_queue ADD COLUMN attempt_count INTEGER NOT NULL DEFAULT 0"
                )
            connection.commit()
        with self._transaction() as connection:
            connection.execute(
                "UPDATE campaign_deliveries SET status = 'queued' WHERE status = 'sending'"
            )
            connection.execute(
                "UPDATE reply_queue SET status = 'pending' WHERE status = 'sending'"
            )

    def _ensure_telegram(self, force: bool = False) -> dict[str, Any]:
        with self._bot_status_lock:
            elapsed = time.monotonic() - self._bot_checked_at
            refresh_after = 5.0 if not self._bot_status["connected"] else 30.0
            if not force and self._bot_checked_at and elapsed < refresh_after:
                return dict(self._bot_status)
            if not self._telegram_configured:
                self._bot_status = {
                    "connected": False,
                    "username": None,
                    "error": "TELEFLOW_BOT_TOKEN is not configured",
                }
                self._bot_checked_at = time.monotonic()
                self._bot_id = None
                return dict(self._bot_status)
            try:
                me = self.telegram.call("getMe")
                if not isinstance(me, dict) or not isinstance(me.get("id"), int):
                    raise TelegramError("Telegram returned an invalid bot profile")
                username = me.get("username")
                self._bot_id = me["id"]
                self._bot_status = {
                    "connected": True,
                    "username": username if isinstance(username, str) else None,
                    "error": None,
                }
            except TelegramError as error:
                self._bot_id = None
                self._bot_status = {
                    "connected": False,
                    "username": None,
                    "error": error.message,
                }
            except Exception:
                self._bot_id = None
                self._bot_status = {
                    "connected": False,
                    "username": None,
                    "error": "Telegram connection failed",
                }
            self._bot_checked_at = time.monotonic()
            return dict(self._bot_status)

    def status(self) -> dict[str, Any]:
        return {
            "telegram": self._ensure_telegram(),
            "ai": {"configured": self._ai_configured},
            "demo": self.demo,
            "public_demo": self.public_demo,
            "accounts": {"enabled": self.accounts is not None},
            "auth_required": self.password is not None,
        }

    def _require_connected(self) -> None:
        if self.demo:
            raise APIError(403, "Telegram sends are disabled in demo mode")
        status = self._ensure_telegram()
        if not status["connected"]:
            raise APIError(503, status["error"] or "Telegram is not connected")

    @staticmethod
    def _required_text(
        value: Any, field: str, max_length: int, *, preserve: bool = False
    ) -> str:
        if not isinstance(value, str):
            raise APIError(400, f"{field} must be text")
        text = value if preserve else value.strip()
        if not text.strip():
            raise APIError(400, f"{field} is required")
        if len(text) > max_length:
            raise APIError(400, f"{field} must be at most {max_length} characters")
        return text

    def _verify_chat(self, supplied_id: Any) -> dict[str, str]:
        chat_ref = self._required_text(supplied_id, "chat_id", 64)
        if not (
            re.fullmatch(r"@[A-Za-z][A-Za-z0-9_]{4,31}", chat_ref)
            or re.fullmatch(r"-\d{1,20}", chat_ref)
        ):
            raise APIError(
                400, "chat_id must be a public @username or a negative Telegram chat ID"
            )
        self._require_connected()
        try:
            chat = self.telegram.call("getChat", {"chat_id": chat_ref})
            if not isinstance(chat, dict) or not isinstance(chat.get("id"), (int, str)):
                raise TelegramError("Telegram returned an invalid chat")
            chat_id = str(chat["id"])
            chat_type = chat.get("type")
            if chat_type not in {"group", "supergroup", "channel"}:
                raise APIError(
                    400, "Only Telegram groups, supergroups, and channels can be added"
                )
            member = self.telegram.call(
                "getChatMember", {"chat_id": chat_id, "user_id": self._bot_id}
            )
            if not isinstance(member, dict) or member.get("status") not in {
                "administrator",
                "creator",
            }:
                raise APIError(403, "The bot must be an administrator of this chat")
            if (
                chat_type == "channel"
                and member.get("status") != "creator"
                and member.get("can_post_messages") is not True
            ):
                raise APIError(
                    403, "The bot needs permission to post messages in this channel"
                )
            if (
                chat_type in {"group", "supergroup"}
                and member.get("can_send_messages") is False
            ):
                raise APIError(403, "The bot cannot send messages in this chat")
            title = chat.get("title") or chat.get("username") or chat_id
            username = chat.get("username")
            return {
                "id": chat_id,
                "title": str(title)[:256],
                "username": username if isinstance(username, str) else None,
                "type": chat_type,
            }
        except TelegramError as error:
            raise APIError(503 if error.transient else 400, error.message) from None
        except APIError:
            raise
        except Exception:
            raise APIError(502, "Telegram chat verification failed") from None

    def add_chat(self, supplied_id: Any) -> dict[str, str | None]:
        verified = self._verify_chat(supplied_id)
        with self._transaction() as connection:
            connection.execute(
                """INSERT INTO chats(chat_id, title, username, type, verified_at)
                   VALUES (?, ?, ?, ?, ?)
                   ON CONFLICT(chat_id) DO UPDATE SET title=excluded.title,
                     username=excluded.username, type=excluded.type, verified_at=excluded.verified_at""",
                (
                    verified["id"],
                    verified["title"],
                    verified["username"],
                    verified["type"],
                    self._now_iso(),
                ),
            )
        return verified

    def list_chats(self) -> list[dict[str, str | None]]:
        with self._connection() as connection:
            rows = connection.execute(
                "SELECT chat_id, title, username, type FROM chats ORDER BY title COLLATE NOCASE"
            ).fetchall()
        return [
            {
                "id": row["chat_id"],
                "title": row["title"],
                "username": row["username"],
                "type": row["type"],
            }
            for row in rows
        ]

    def delete_chat(self, chat_id: str) -> None:
        with self._transaction() as connection:
            cursor = connection.execute(
                "DELETE FROM chats WHERE chat_id = ?", (chat_id,)
            )
            if cursor.rowcount == 0:
                raise APIError(404, "Chat not found")

    def _require_saved_chat(self, chat_id: Any) -> str:
        if not isinstance(chat_id, str) or not chat_id:
            raise APIError(400, "chat_id is required for a chat campaign")
        with self._connection() as connection:
            row = connection.execute(
                "SELECT chat_id FROM chats WHERE chat_id = ?", (chat_id,)
            ).fetchone()
        if row is None:
            raise APIError(
                400, "Add and verify this chat before using it in a campaign"
            )
        return row["chat_id"]

    def _campaign_dict(self, row: sqlite3.Row) -> dict[str, Any]:
        return {
            "id": int(row["id"]),
            "title": row["title"],
            "body": row["body"],
            "target_type": row["target_type"],
            "chat_id": row["chat_id"],
            "status": row["status"],
            "scheduled_at": row["scheduled_at"],
            "created_at": row["created_at"],
            "sent_count": int(row["sent_count"]),
            "failed_count": int(row["failed_count"]),
            "recipient_count": int(row["recipient_count"]),
        }

    def _campaign(
        self, campaign_id: int, connection: sqlite3.Connection | None = None
    ) -> dict[str, Any]:
        if connection is not None:
            row = connection.execute(
                "SELECT * FROM campaigns WHERE id = ?", (campaign_id,)
            ).fetchone()
        else:
            with self._connection() as db:
                row = db.execute(
                    "SELECT * FROM campaigns WHERE id = ?", (campaign_id,)
                ).fetchone()
        if row is None:
            raise APIError(404, "Campaign not found")
        return self._campaign_dict(row)

    def list_campaigns(self) -> list[dict[str, Any]]:
        with self._connection() as connection:
            rows = connection.execute(
                "SELECT * FROM campaigns ORDER BY id DESC"
            ).fetchall()
        return [self._campaign_dict(row) for row in rows]

    def get_campaign(self, campaign_id: int) -> dict[str, Any]:
        return self._campaign(campaign_id)

    def _campaign_fields(
        self, data: dict[str, Any], existing: dict[str, Any] | None = None
    ) -> tuple[str, str, str, str | None]:
        title_value = data.get("title", existing["title"] if existing else None)
        body_value = data.get("body", existing["body"] if existing else None)
        title = self._required_text(title_value, "title", 160)
        body = self._required_text(body_value, "body", MAX_CAMPAIGN_BODY, preserve=True)
        target_type = data.get(
            "target_type", existing["target_type"] if existing else None
        )
        if target_type not in {"subscribers", "chat"}:
            raise APIError(400, "target_type must be 'subscribers' or 'chat'")
        supplied_chat = data.get("chat_id", existing["chat_id"] if existing else None)
        if target_type == "chat":
            chat_id = self._require_saved_chat(supplied_chat)
        else:
            chat_id = None
        return title, body, target_type, chat_id

    def create_campaign(self, data: dict[str, Any]) -> dict[str, Any]:
        title, body, target_type, chat_id = self._campaign_fields(data)
        with self._transaction() as connection:
            cursor = connection.execute(
                """INSERT INTO campaigns(title, body, target_type, chat_id, status, created_at)
                   VALUES (?, ?, ?, ?, 'draft', ?)""",
                (title, body, target_type, chat_id, self._now_iso()),
            )
            return self._campaign(int(cursor.lastrowid), connection)

    def update_campaign(self, campaign_id: int, data: dict[str, Any]) -> dict[str, Any]:
        with self._transaction() as connection:
            current = self._campaign(campaign_id, connection)
            if current["status"] not in {"draft", "scheduled"}:
                raise APIError(409, "Only draft or scheduled campaigns can be edited")
            title, body, target_type, chat_id = self._campaign_fields(data, current)
            connection.execute(
                "UPDATE campaigns SET title=?, body=?, target_type=?, chat_id=? WHERE id=?",
                (title, body, target_type, chat_id, campaign_id),
            )
            return self._campaign(campaign_id, connection)

    def delete_campaign(self, campaign_id: int) -> None:
        with self._transaction() as connection:
            current = self._campaign(campaign_id, connection)
            if current["status"] not in {"draft", "scheduled"}:
                raise APIError(409, "Only draft or scheduled campaigns can be deleted")
            connection.execute("DELETE FROM campaigns WHERE id=?", (campaign_id,))

    def _parse_schedule_time(self, value: Any) -> str:
        if not isinstance(value, str) or not value.strip():
            raise APIError(400, "scheduled_at must be a UTC ISO timestamp")
        raw = value.strip()
        try:
            parsed = dt.datetime.fromisoformat(
                raw[:-1] + "+00:00" if raw.endswith("Z") else raw
            )
        except ValueError:
            raise APIError(400, "scheduled_at must be a UTC ISO timestamp") from None
        if parsed.tzinfo is None or parsed.utcoffset() != dt.timedelta(0):
            raise APIError(400, "scheduled_at must include a UTC timezone")
        parsed = parsed.astimezone(dt.timezone.utc).replace(microsecond=0)
        if parsed <= self._now().replace(microsecond=0):
            raise APIError(400, "scheduled_at must be in the future")
        return iso_utc(parsed)

    def schedule_campaign(self, campaign_id: int, scheduled_at: Any) -> dict[str, Any]:
        normalized = self._parse_schedule_time(scheduled_at)
        current = self.get_campaign(campaign_id)
        if current["status"] not in {"draft", "scheduled"}:
            raise APIError(409, "Only draft or scheduled campaigns can be scheduled")
        if current["target_type"] == "chat":
            self._verify_saved_chat(current["chat_id"])
        with self._transaction() as connection:
            latest = self._campaign(campaign_id, connection)
            if latest["status"] not in {"draft", "scheduled"}:
                raise APIError(
                    409, "Only draft or scheduled campaigns can be scheduled"
                )
            if (latest["target_type"], latest["chat_id"]) != (
                current["target_type"],
                current["chat_id"],
            ):
                raise APIError(
                    409, "Campaign target changed; verify it again before scheduling"
                )
            connection.execute(
                "UPDATE campaigns SET status='scheduled', scheduled_at=? WHERE id=?",
                (normalized, campaign_id),
            )
            return self._campaign(campaign_id, connection)

    def _verify_saved_chat(self, chat_id: str | None) -> None:
        if not chat_id:
            raise APIError(400, "Campaign chat is no longer configured")
        verified = self._verify_chat(chat_id)
        if verified["id"] != chat_id:
            raise APIError(400, "Telegram resolved a different chat ID")
        with self._transaction() as connection:
            connection.execute(
                """UPDATE chats SET title=?, username=?, type=?, verified_at=? WHERE chat_id=?""",
                (
                    verified["title"],
                    verified["username"],
                    verified["type"],
                    self._now_iso(),
                    chat_id,
                ),
            )
            exists = connection.execute(
                "SELECT 1 FROM chats WHERE chat_id=?", (chat_id,)
            ).fetchone()
            if exists is None:
                raise APIError(
                    400, "Add and verify this chat before using it in a campaign"
                )

    def send_campaign(self, campaign_id: int) -> dict[str, Any]:
        current = self.get_campaign(campaign_id)
        if current["status"] not in {"draft", "scheduled"}:
            raise APIError(409, "Only draft or scheduled campaigns can be sent")
        self._require_connected()
        self._activate_campaign(campaign_id, scheduled_only=False, reject_empty=True)
        return self.get_campaign(campaign_id)

    def retry_failed_campaign(self, campaign_id: int) -> dict[str, Any]:
        current = self.get_campaign(campaign_id)
        if (
            current["status"] not in {"partial", "failed"}
            or not current["failed_count"]
        ):
            raise APIError(409, "This campaign has no failed deliveries to retry")
        self._require_connected()
        if current["target_type"] == "chat":
            self._verify_saved_chat(current["chat_id"])
        with self._transaction() as connection:
            latest = self._campaign(campaign_id, connection)
            if (
                latest["status"] not in {"partial", "failed"}
                or not latest["failed_count"]
            ):
                raise APIError(409, "This campaign has no failed deliveries to retry")
            retried = connection.execute(
                """UPDATE campaign_deliveries
                   SET status='queued', attempt_count=0, next_attempt_at=NULL,
                       error=NULL, failed_at=NULL
                   WHERE campaign_id=? AND status='failed'""",
                (campaign_id,),
            ).rowcount
            if not retried:
                raise APIError(409, "This campaign has no failed deliveries to retry")
            self._update_campaign_counts(connection, campaign_id)
            return self._campaign(campaign_id, connection)

    def cancel_campaign_schedule(self, campaign_id: int) -> dict[str, Any]:
        with self._transaction() as connection:
            cursor = connection.execute(
                """UPDATE campaigns SET status='draft', scheduled_at=NULL
                   WHERE id=? AND status='scheduled'""",
                (campaign_id,),
            )
            if not cursor.rowcount:
                exists = connection.execute(
                    "SELECT 1 FROM campaigns WHERE id=?", (campaign_id,)
                ).fetchone()
                if exists is None:
                    raise APIError(404, "Campaign not found")
                raise APIError(409, "Only scheduled campaigns can be cancelled")
            return self._campaign(campaign_id, connection)

    def _activate_campaign(
        self, campaign_id: int, *, scheduled_only: bool, reject_empty: bool
    ) -> bool:
        with self._connection() as connection:
            current_row = connection.execute(
                "SELECT * FROM campaigns WHERE id=?", (campaign_id,)
            ).fetchone()
            if current_row is None:
                if reject_empty:
                    raise APIError(404, "Campaign not found")
                return False
            current = self._campaign_dict(current_row)
        allowed = {"scheduled"} if scheduled_only else {"draft", "scheduled"}
        if current["status"] not in allowed:
            if reject_empty:
                raise APIError(409, "Only draft or scheduled campaigns can be sent")
            return False
        if current["target_type"] == "chat":
            try:
                self._verify_saved_chat(current["chat_id"])
            except APIError as error:
                if reject_empty:
                    raise
                if error.status in {502, 503}:
                    return False
                self._fail_scheduled_campaign(
                    campaign_id, failed_count=1, recipient_count=1
                )
                return False

        with self._transaction() as connection:
            row = connection.execute(
                "SELECT * FROM campaigns WHERE id=?", (campaign_id,)
            ).fetchone()
            if row is None:
                if reject_empty:
                    raise APIError(404, "Campaign not found")
                return False
            if row["status"] not in allowed:
                if reject_empty:
                    raise APIError(409, "Only draft or scheduled campaigns can be sent")
                return False
            if (row["target_type"], row["chat_id"]) != (
                current["target_type"],
                current["chat_id"],
            ):
                if reject_empty:
                    raise APIError(
                        409, "Campaign target changed; verify it again before sending"
                    )
                return False
            if row["target_type"] == "subscribers":
                recipients = [
                    str(item[0])
                    for item in connection.execute(
                        "SELECT chat_id FROM subscribers WHERE opted_in=1 ORDER BY joined_at, chat_id"
                    ).fetchall()
                ]
            else:
                exists = connection.execute(
                    "SELECT 1 FROM chats WHERE chat_id=?", (row["chat_id"],)
                ).fetchone()
                recipients = [row["chat_id"]] if exists else []
            if not recipients:
                if reject_empty:
                    raise APIError(409, "This campaign has no opted-in recipients")
                connection.execute(
                    "UPDATE campaigns SET status='draft', scheduled_at=NULL, recipient_count=0, sent_count=0, failed_count=0 WHERE id=?",
                    (campaign_id,),
                )
                return False
            now = self._now_iso()
            connection.executemany(
                """INSERT OR IGNORE INTO campaign_deliveries(campaign_id, chat_id, status, created_at)
                   VALUES (?, ?, 'queued', ?)""",
                [(campaign_id, recipient, now) for recipient in recipients],
            )
            count = connection.execute(
                "SELECT COUNT(*) FROM campaign_deliveries WHERE campaign_id=?",
                (campaign_id,),
            ).fetchone()[0]
            connection.execute(
                """UPDATE campaigns SET status='sending', scheduled_at=NULL, recipient_count=?,
                     sent_count=0, failed_count=0 WHERE id=?""",
                (count, campaign_id),
            )
        return True

    def _fail_scheduled_campaign(
        self, campaign_id: int, *, failed_count: int, recipient_count: int
    ) -> None:
        with self._transaction() as connection:
            cursor = connection.execute(
                """UPDATE campaigns SET status='failed', scheduled_at=NULL, recipient_count=?,
                     sent_count=0, failed_count=? WHERE id=? AND status='scheduled'""",
                (recipient_count, failed_count, campaign_id),
            )
            if cursor.rowcount and recipient_count and failed_count:
                row = connection.execute(
                    "SELECT chat_id FROM campaigns WHERE id=?", (campaign_id,)
                ).fetchone()
                if row and row["chat_id"]:
                    now = self._now_iso()
                    connection.execute(
                        """INSERT OR IGNORE INTO campaign_deliveries
                           (campaign_id, chat_id, status, error, created_at, failed_at)
                           VALUES (?, ?, 'failed', 'Chat verification failed', ?, ?)""",
                        (campaign_id, row["chat_id"], now, now),
                    )

    def _activate_due_campaigns(self) -> int:
        if self.demo or not self._ensure_telegram()["connected"]:
            return 0
        with self._connection() as connection:
            due = [
                row[0]
                for row in connection.execute(
                    "SELECT id FROM campaigns WHERE status='scheduled' AND scheduled_at<=? ORDER BY scheduled_at, id",
                    (self._now_iso(),),
                ).fetchall()
            ]
        activated = 0
        for campaign_id in due:
            if self._activate_campaign(
                campaign_id, scheduled_only=True, reject_empty=False
            ):
                activated += 1
        return activated

    def _update_campaign_counts(
        self, connection: sqlite3.Connection, campaign_id: int
    ) -> None:
        counts = connection.execute(
            """SELECT
                 SUM(CASE WHEN status='sent' THEN 1 ELSE 0 END) AS sent,
                 SUM(CASE WHEN status='failed' THEN 1 ELSE 0 END) AS failed,
                 SUM(CASE WHEN status IN ('queued', 'sending') THEN 1 ELSE 0 END) AS pending
               FROM campaign_deliveries WHERE campaign_id=?""",
            (campaign_id,),
        ).fetchone()
        sent = int(counts["sent"] or 0)
        failed = int(counts["failed"] or 0)
        pending = int(counts["pending"] or 0)
        status = (
            "sending"
            if pending
            else (
                "failed"
                if failed and not sent
                else "partial"
                if failed
                else "completed"
            )
        )
        connection.execute(
            "UPDATE campaigns SET sent_count=?, failed_count=?, status=? WHERE id=?",
            (sent, failed, status, campaign_id),
        )

    def _claim_delivery(self) -> dict[str, Any] | None:
        with self._transaction() as connection:
            row = connection.execute(
                """SELECT d.id, d.campaign_id, d.chat_id, d.attempt_count,
                          c.target_type, c.body
                   FROM campaign_deliveries d JOIN campaigns c ON c.id=d.campaign_id
                   WHERE d.status='queued' AND c.status='sending'
                     AND (d.next_attempt_at IS NULL OR d.next_attempt_at<=?)
                   ORDER BY d.campaign_id, d.id LIMIT 1""",
                (self._now_iso(),),
            ).fetchone()
            if row is None:
                return None
            changed = connection.execute(
                """UPDATE campaign_deliveries
                   SET status='sending', attempt_count=attempt_count+1, next_attempt_at=NULL
                   WHERE id=? AND status='queued'""",
                (row["id"],),
            ).rowcount
            if not changed:
                return None
            delivery = dict(row)
            delivery["attempt_count"] += 1
            return delivery

    def _finish_skipped_delivery(self, delivery: dict[str, Any]) -> None:
        with self._transaction() as connection:
            connection.execute(
                """UPDATE campaign_deliveries
                   SET status='skipped', next_attempt_at=NULL
                   WHERE id=? AND status='sending'""",
                (delivery["id"],),
            )
            connection.execute(
                "UPDATE campaigns SET recipient_count=MAX(0, recipient_count-1) WHERE id=?",
                (delivery["campaign_id"],),
            )
            self._update_campaign_counts(connection, delivery["campaign_id"])

    def _send_message(self, chat_id: int | str, body: str) -> dict[str, Any]:
        self._require_connected()
        self._rate_limiter.wait()
        try:
            result = self.telegram.call(
                "sendMessage", {"chat_id": chat_id, "text": body}
            )
        except TelegramError:
            raise
        if not isinstance(result, dict):
            raise TelegramError("Telegram returned an invalid sent message")
        return result

    def _retry_at(self, error: Exception, attempt_count: int) -> str | None:
        transient = isinstance(error, TelegramError) and error.transient
        transient = transient or (isinstance(error, APIError) and error.status == 503)
        if not transient:
            return None
        if attempt_count >= MAX_DELIVERY_ATTEMPTS:
            return None
        retry_after = error.retry_after if isinstance(error, TelegramError) else None
        now = self._now()
        if retry_after is not None:
            remaining = dt.datetime.max.replace(tzinfo=dt.timezone.utc) - now
            max_seconds = remaining.days * 86_400 + remaining.seconds
            delay = min(max(1, retry_after), max_seconds)
        else:
            delay = min(60, 2 ** max(0, attempt_count - 1))
        return iso_utc(now + dt.timedelta(seconds=delay))

    def _deliver_campaign_delivery(self, delivery: dict[str, Any]) -> bool:
        with self._consent_lock:
            if delivery["target_type"] == "subscribers":
                try:
                    subscriber_id = int(delivery["chat_id"])
                except (TypeError, ValueError):
                    subscriber_id = -1
                with self._connection() as connection:
                    opted = connection.execute(
                        "SELECT opted_in FROM subscribers WHERE chat_id=?",
                        (subscriber_id,),
                    ).fetchone()
                if opted is None or not opted["opted_in"]:
                    self._finish_skipped_delivery(delivery)
                    return False
            try:
                result = self._send_message(delivery["chat_id"], delivery["body"])
            except Exception as error:
                detail = (
                    error.message
                    if isinstance(error, TelegramError)
                    else "Telegram delivery failed"
                )
                retry_at = self._retry_at(error, delivery["attempt_count"])
                with self._transaction() as connection:
                    if retry_at is not None:
                        connection.execute(
                            """UPDATE campaign_deliveries
                               SET status='queued', error=?, next_attempt_at=?, failed_at=NULL
                               WHERE id=? AND status='sending'""",
                            (detail[:300], retry_at, delivery["id"]),
                        )
                    else:
                        connection.execute(
                            """UPDATE campaign_deliveries
                               SET status='failed', error=?, next_attempt_at=NULL, failed_at=?
                               WHERE id=? AND status='sending'""",
                            (detail[:300], self._now_iso(), delivery["id"]),
                        )
                    self._update_campaign_counts(connection, delivery["campaign_id"])
                return False

            message_id = (
                result.get("message_id")
                if isinstance(result.get("message_id"), int)
                else None
            )
            sent_at = self._now_iso()
            with self._transaction() as connection:
                connection.execute(
                    """UPDATE campaign_deliveries
                       SET status='sent', message_id=?, sent_at=?, error=NULL,
                           next_attempt_at=NULL
                       WHERE id=? AND status='sending'""",
                    (message_id, sent_at, delivery["id"]),
                )
                if delivery["target_type"] == "subscribers":
                    connection.execute(
                        """INSERT INTO messages
                           (chat_id, direction, body, created_at, telegram_message_id)
                           VALUES (?, 'out', ?, ?, ?)""",
                        (
                            delivery["chat_id"],
                            delivery["body"],
                            sent_at,
                            message_id,
                        ),
                    )
                self._update_campaign_counts(connection, delivery["campaign_id"])
            return True

    def _deliver_campaigns(self, limit: int = 100) -> int:
        if self.demo or not self._ensure_telegram()["connected"]:
            return 0
        delivered = 0
        for _ in range(max(1, limit)):
            delivery = self._claim_delivery()
            if delivery is None:
                break
            if self._deliver_campaign_delivery(delivery):
                delivered += 1
        return delivered

    def _claim_reply(self) -> dict[str, Any] | None:
        with self._transaction() as connection:
            row = connection.execute(
                """SELECT q.update_id, q.chat_id, q.body, q.attempt_count, s.opted_in
                   FROM reply_queue q LEFT JOIN subscribers s ON s.chat_id=q.chat_id
                   WHERE q.status='pending'
                     AND (q.next_attempt_at IS NULL OR q.next_attempt_at<=?)
                   ORDER BY q.update_id LIMIT 1""",
                (self._now_iso(),),
            ).fetchone()
            if row is None:
                return None
            if not row["opted_in"]:
                connection.execute(
                    "UPDATE reply_queue SET status='cancelled' WHERE update_id=?",
                    (row["update_id"],),
                )
                return {"cancelled": True}
            connection.execute(
                """UPDATE reply_queue
                   SET status='sending', attempt_count=attempt_count+1, next_attempt_at=NULL
                   WHERE update_id=?""",
                (row["update_id"],),
            )
            reply = dict(row)
            reply["attempt_count"] = int(row["attempt_count"] or 0) + 1
            return reply

    def _deliver_keyword_reply(self, reply: dict[str, Any]) -> bool:
        with self._consent_lock:
            with self._connection() as connection:
                contact = connection.execute(
                    "SELECT opted_in FROM subscribers WHERE chat_id=?",
                    (reply["chat_id"],),
                ).fetchone()
            if contact is None or not contact["opted_in"]:
                with self._transaction() as connection:
                    connection.execute(
                        "UPDATE reply_queue SET status='cancelled' WHERE update_id=? AND status='sending'",
                        (reply["update_id"],),
                    )
                return False
            try:
                result = self._send_message(reply["chat_id"], reply["body"])
            except Exception as error:
                detail = (
                    error.message
                    if isinstance(error, TelegramError)
                    else "Telegram reply failed"
                )
                retry_at = self._retry_at(error, reply["attempt_count"])
                with self._transaction() as connection:
                    if retry_at is not None:
                        connection.execute(
                            """UPDATE reply_queue
                               SET status='pending', error=?, next_attempt_at=?
                               WHERE update_id=? AND status='sending'""",
                            (detail[:300], retry_at, reply["update_id"]),
                        )
                    else:
                        connection.execute(
                            """UPDATE reply_queue
                               SET status='failed', error=?, next_attempt_at=NULL
                               WHERE update_id=? AND status='sending'""",
                            (detail[:300], reply["update_id"]),
                        )
                return False

            sent_at = self._now_iso()
            message_id = (
                result.get("message_id")
                if isinstance(result.get("message_id"), int)
                else None
            )
            with self._transaction() as connection:
                connection.execute(
                    """UPDATE reply_queue
                       SET status='sent', error=NULL, next_attempt_at=NULL
                       WHERE update_id=? AND status='sending'""",
                    (reply["update_id"],),
                )
                connection.execute(
                    """INSERT INTO messages
                       (chat_id, direction, body, created_at, telegram_message_id)
                       VALUES (?, 'out', ?, ?, ?)""",
                    (str(reply["chat_id"]), reply["body"], sent_at, message_id),
                )
            return True

    def _deliver_replies(self, limit: int = 100) -> int:
        if self.demo or not self._ensure_telegram()["connected"]:
            return 0
        delivered = 0
        for _ in range(max(1, limit)):
            reply = self._claim_reply()
            if reply is None:
                break
            if reply.get("cancelled"):
                continue
            if self._deliver_keyword_reply(reply):
                delivered += 1
        return delivered

    def dispatch_pending(self, limit: int = 100) -> int:
        if self.demo or not self._ensure_telegram()["connected"]:
            return 0
        self._activate_due_campaigns()
        return self._deliver_replies(limit) + self._deliver_campaigns(limit)

    def _read_offset(self, connection: sqlite3.Connection) -> int:
        row = connection.execute(
            "SELECT value FROM settings WHERE key='poll_offset'"
        ).fetchone()
        return int(row["value"]) if row else 0

    def _process_update(self, update: dict[str, Any]) -> bool:
        with self._consent_lock:
            return self._process_update_with_consent(update)

    def _process_update_with_consent(self, update: dict[str, Any]) -> bool:
        update_id = update.get("update_id")
        if not isinstance(update_id, int) or update_id < 0 or update_id > 2**63 - 2:
            return False
        with self._transaction() as connection:
            cursor = connection.execute(
                "INSERT OR IGNORE INTO processed_updates(update_id, processed_at) VALUES (?, ?)",
                (update_id, self._now_iso()),
            )
            inserted = cursor.rowcount == 1
            old_offset = self._read_offset(connection)
            connection.execute(
                """INSERT INTO settings(key, value) VALUES ('poll_offset', ?)
                   ON CONFLICT(key) DO UPDATE SET value=excluded.value""",
                (str(max(old_offset, update_id + 1)),),
            )
            if not inserted:
                return False
            message = update.get("message")
            if not isinstance(message, dict):
                return True
            sender = message.get("from")
            chat = message.get("chat")
            if (
                not isinstance(sender, dict)
                or not isinstance(chat, dict)
                or chat.get("type") != "private"
            ):
                return True
            sender_id = sender.get("id")
            chat_id = chat.get("id")
            if (
                not isinstance(sender_id, int)
                or sender_id <= 0
                or not isinstance(chat_id, int)
                or sender_id != chat_id
            ):
                return True
            if sender.get("is_bot") is True:
                return True
            raw_text = message.get("text")
            caption = message.get("caption")
            text = (
                raw_text
                if isinstance(raw_text, str)
                else caption
                if isinstance(caption, str)
                else "[non-text message]"
            )
            first_name = (
                sender.get("first_name")
                if isinstance(sender.get("first_name"), str)
                else ""
            )
            username = (
                sender.get("username")
                if isinstance(sender.get("username"), str)
                else None
            )
            created_at = self._now_iso()
            message_date = message.get("date")
            if isinstance(message_date, int):
                try:
                    created_at = iso_utc(
                        dt.datetime.fromtimestamp(message_date, tz=dt.timezone.utc)
                    )
                except (OverflowError, OSError, ValueError):
                    pass
            command = ""
            if isinstance(raw_text, str) and raw_text.startswith("/"):
                command = raw_text.split(maxsplit=1)[0].lower()
                if "@" in command:
                    command_name, mention = command.split("@", 1)
                    own_username = self._bot_status.get("username")
                    if own_username and mention.casefold() != own_username.casefold():
                        command = ""
                    else:
                        command = command_name
            opted_in = 1 if command == "/start" else 0
            connection.execute(
                """INSERT INTO subscribers(chat_id, first_name, username, opted_in, joined_at)
                   VALUES (?, ?, ?, ?, ?)
                   ON CONFLICT(chat_id) DO UPDATE SET first_name=excluded.first_name,
                     username=excluded.username,
                     opted_in=CASE WHEN ? = 1 THEN 1 WHEN ? = 1 THEN 0 ELSE subscribers.opted_in END""",
                (
                    sender_id,
                    first_name,
                    username,
                    opted_in,
                    created_at,
                    opted_in,
                    int(command == "/stop"),
                ),
            )
            connection.execute(
                "INSERT INTO messages(chat_id, direction, body, created_at) VALUES (?, 'in', ?, ?)",
                (str(sender_id), text[:MAX_BODY_BYTES], created_at),
            )
            if command in {"/start", "/stop"} or not isinstance(raw_text, str):
                return True
            subscriber = connection.execute(
                "SELECT opted_in FROM subscribers WHERE chat_id=?", (sender_id,)
            ).fetchone()
            if not subscriber or not subscriber["opted_in"]:
                return True
            folded_text = raw_text.casefold()
            rules = connection.execute(
                "SELECT id, keyword, reply FROM rules WHERE enabled=1 ORDER BY id"
            ).fetchall()
            for rule in rules:
                if rule["keyword"].casefold() in folded_text:
                    connection.execute(
                        "UPDATE rules SET hits=hits+1 WHERE id=?", (rule["id"],)
                    )
                    connection.execute(
                        "INSERT OR IGNORE INTO reply_queue(update_id, chat_id, body, status, created_at) VALUES (?, ?, ?, 'pending', ?)",
                        (update_id, sender_id, rule["reply"], created_at),
                    )
                    break
        return True

    def poll_updates(self) -> int:
        if (
            self.demo
            or not self._telegram_configured
            or not self._ensure_telegram()["connected"]
        ):
            return 0
        with self._poll_lock:
            with self._connection() as connection:
                offset = self._read_offset(connection)
            try:
                updates = self.telegram.call(
                    "getUpdates",
                    {"offset": offset, "timeout": 0, "allowed_updates": ["message"]},
                )
            except TelegramError:
                raise
            if not isinstance(updates, list):
                raise TelegramError("Telegram returned an invalid updates list")
            processed = 0
            for update in sorted(
                (item for item in updates if isinstance(item, dict)),
                key=lambda item: item.get("update_id")
                if isinstance(item.get("update_id"), int)
                else -1,
            ):
                if self._process_update(update):
                    processed += 1
            return processed

    def list_subscribers(self) -> list[dict[str, Any]]:
        with self._connection() as connection:
            rows = connection.execute(
                "SELECT chat_id, first_name, username, opted_in, joined_at FROM subscribers ORDER BY joined_at DESC, chat_id"
            ).fetchall()
        return [
            {
                "chat_id": int(row["chat_id"]),
                "first_name": row["first_name"],
                "username": row["username"],
                "opted_in": bool(row["opted_in"]),
                "joined_at": row["joined_at"],
            }
            for row in rows
        ]

    def opt_out_subscriber(self, chat_id: int) -> dict[str, Any]:
        with self._transaction() as connection:
            cursor = connection.execute(
                "UPDATE subscribers SET opted_in=0 WHERE chat_id=?", (chat_id,)
            )
            if not cursor.rowcount:
                raise APIError(404, "Subscriber not found")
            connection.execute(
                """UPDATE reply_queue SET status='cancelled'
                   WHERE chat_id=? AND status='pending'""",
                (chat_id,),
            )
            row = connection.execute(
                """SELECT chat_id, first_name, username, opted_in, joined_at
                   FROM subscribers WHERE chat_id=?""",
                (chat_id,),
            ).fetchone()
            return {
                "chat_id": int(row["chat_id"]),
                "first_name": row["first_name"],
                "username": row["username"],
                "opted_in": bool(row["opted_in"]),
                "joined_at": row["joined_at"],
            }

    def list_inbox(self) -> list[dict[str, Any]]:
        with self._connection() as connection:
            rows = connection.execute(
                """SELECT m.chat_id, COALESCE(s.first_name, '') AS first_name, s.username,
                          COALESCE(s.opted_in, 0) AS opted_in, m.body AS last_text, m.created_at AS last_at
                   FROM messages m
                   JOIN (SELECT chat_id, MAX(id) AS last_id FROM messages GROUP BY chat_id) latest ON latest.last_id=m.id
                   LEFT JOIN subscribers s ON CAST(s.chat_id AS TEXT)=m.chat_id
                   ORDER BY m.id DESC"""
            ).fetchall()
        items = []
        for row in rows:
            try:
                chat_id: int | str = int(row["chat_id"])
            except (TypeError, ValueError):
                chat_id = row["chat_id"]
            items.append(
                {
                    "chat_id": chat_id,
                    "first_name": row["first_name"],
                    "username": row["username"],
                    "last_text": row["last_text"],
                    "last_at": row["last_at"],
                    "opted_in": bool(row["opted_in"]),
                }
            )
        return items

    def get_conversation(self, chat_id: int) -> dict[str, Any]:
        with self._connection() as connection:
            contact = connection.execute(
                "SELECT chat_id, first_name, username, opted_in FROM subscribers WHERE chat_id=?",
                (chat_id,),
            ).fetchone()
            if contact is None:
                raise APIError(404, "Contact not found")
            rows = connection.execute(
                "SELECT id, direction, body, created_at FROM messages WHERE chat_id=? ORDER BY id",
                (str(chat_id),),
            ).fetchall()
        return {
            "contact": {
                "chat_id": int(contact["chat_id"]),
                "first_name": contact["first_name"],
                "username": contact["username"],
                "opted_in": bool(contact["opted_in"]),
            },
            "items": [
                {
                    "id": int(row["id"]),
                    "direction": row["direction"],
                    "body": row["body"],
                    "created_at": row["created_at"],
                }
                for row in rows
            ],
        }

    def reply_to_contact(self, chat_id: int, body: Any) -> dict[str, Any]:
        text = self._required_text(body, "body", MAX_CAMPAIGN_BODY, preserve=True)
        self._require_connected()
        with self._consent_lock:
            with self._connection() as connection:
                contact = connection.execute(
                    "SELECT opted_in FROM subscribers WHERE chat_id=?", (chat_id,)
                ).fetchone()
            if contact is None:
                raise APIError(404, "Contact not found")
            if not contact["opted_in"]:
                raise APIError(403, "This contact has not opted in")
            try:
                result = self._send_message(chat_id, text)
            except Exception as error:
                detail = (
                    error.message
                    if isinstance(error, (TelegramError, APIError))
                    else "Telegram reply failed"
                )
                status = (
                    503
                    if (isinstance(error, TelegramError) and error.transient)
                    or (isinstance(error, APIError) and error.status == 503)
                    else 502
                )
                retry_after = (
                    error.retry_after if isinstance(error, TelegramError) else None
                )
                raise APIError(status, detail, retry_after=retry_after) from None
            created_at = self._now_iso()
            telegram_message_id = (
                result.get("message_id")
                if isinstance(result.get("message_id"), int)
                else None
            )
            with self._transaction() as connection:
                cursor = connection.execute(
                    "INSERT INTO messages(chat_id, direction, body, created_at, telegram_message_id) VALUES (?, 'out', ?, ?, ?)",
                    (str(chat_id), text, created_at, telegram_message_id),
                )
                message_id = int(cursor.lastrowid)
        return {
            "id": message_id,
            "direction": "out",
            "body": text,
            "created_at": created_at,
        }

    def list_rules(self) -> list[dict[str, Any]]:
        with self._connection() as connection:
            rows = connection.execute(
                "SELECT id, keyword, reply, enabled, hits FROM rules ORDER BY id DESC"
            ).fetchall()
        return [
            {
                "id": int(row["id"]),
                "keyword": row["keyword"],
                "reply": row["reply"],
                "enabled": bool(row["enabled"]),
                "hits": int(row["hits"]),
            }
            for row in rows
        ]

    def create_rule(self, data: dict[str, Any]) -> dict[str, Any]:
        keyword = self._required_text(data.get("keyword"), "keyword", 80)
        reply = self._required_text(
            data.get("reply"), "reply", MAX_CAMPAIGN_BODY, preserve=True
        )
        with self._transaction() as connection:
            cursor = connection.execute(
                "INSERT INTO rules(keyword, reply, enabled, hits) VALUES (?, ?, 1, 0)",
                (keyword, reply),
            )
            row = connection.execute(
                "SELECT id, keyword, reply, enabled, hits FROM rules WHERE id=?",
                (cursor.lastrowid,),
            ).fetchone()
        return {
            "id": int(row["id"]),
            "keyword": row["keyword"],
            "reply": row["reply"],
            "enabled": bool(row["enabled"]),
            "hits": int(row["hits"]),
        }

    def set_rule_enabled(self, rule_id: int, enabled: Any) -> dict[str, Any]:
        if not isinstance(enabled, bool):
            raise APIError(400, "enabled must be a boolean")
        with self._transaction() as connection:
            cursor = connection.execute(
                "UPDATE rules SET enabled=? WHERE id=?", (int(enabled), rule_id)
            )
            if not cursor.rowcount:
                raise APIError(404, "Rule not found")
            row = connection.execute(
                "SELECT id, keyword, reply, enabled, hits FROM rules WHERE id=?",
                (rule_id,),
            ).fetchone()
        return {
            "id": int(row["id"]),
            "keyword": row["keyword"],
            "reply": row["reply"],
            "enabled": bool(row["enabled"]),
            "hits": int(row["hits"]),
        }

    def delete_rule(self, rule_id: int) -> None:
        with self._transaction() as connection:
            cursor = connection.execute("DELETE FROM rules WHERE id=?", (rule_id,))
            if not cursor.rowcount:
                raise APIError(404, "Rule not found")

    def draft_with_ai(self, data: dict[str, Any]) -> dict[str, str]:
        if not self._ai_configured:
            raise APIError(503, "OPENAI_API_KEY is not configured")
        prompt = self._required_text(data.get("prompt"), "prompt", 5000)
        tone_value = data.get("tone", "clear and friendly")
        kind_value = data.get("kind", "campaign announcement")
        context_value = data.get("context", "")
        tone = self._required_text(tone_value, "tone", 100)
        kind = self._required_text(kind_value, "kind", 100)
        if not isinstance(context_value, str) or len(context_value) > 5000:
            raise APIError(400, "context must be text of at most 5000 characters")
        return {"text": self.ai_client.draft(prompt, tone, kind, context_value)}

    def analytics(self) -> dict[str, Any]:
        today = self._now().date()
        start_day = today - dt.timedelta(days=29)
        start = start_day.isoformat() + "T00:00:00Z"
        with self._connection() as connection:
            totals = connection.execute(
                """SELECT COALESCE(SUM(sent_count), 0) AS sent,
                          COALESCE(SUM(failed_count), 0) AS failed,
                          (SELECT COUNT(*) FROM subscribers WHERE opted_in=1) AS subscribers,
                          COUNT(*) AS campaigns
                   FROM campaigns"""
            ).fetchone()
            events = connection.execute(
                """SELECT day, SUM(sent) AS sent, SUM(failed) AS failed FROM (
                     SELECT substr(sent_at, 1, 10) AS day, 1 AS sent, 0 AS failed
                       FROM campaign_deliveries WHERE sent_at >= ?
                     UNION ALL
                     SELECT substr(failed_at, 1, 10) AS day, 0 AS sent, 1 AS failed
                       FROM campaign_deliveries WHERE failed_at >= ?
                   ) GROUP BY day""",
                (start, start),
            ).fetchall()
        by_day = {
            row["day"]: (int(row["sent"] or 0), int(row["failed"] or 0))
            for row in events
        }
        daily = []
        for offset in range(30):
            day = (start_day + dt.timedelta(days=offset)).isoformat()
            sent, failed = by_day.get(day, (0, 0))
            daily.append({"date": day, "sent": sent, "failed": failed})
        return {
            "totals": {
                "sent": int(totals["sent"]),
                "failed": int(totals["failed"]),
                "subscribers": int(totals["subscribers"]),
                "campaigns": int(totals["campaigns"]),
            },
            "daily": daily,
        }

    def issue_session(self) -> str:
        token = secrets.token_urlsafe(32)
        with self._sessions_lock:
            now = time.monotonic()
            self._sessions = {
                key: expires for key, expires in self._sessions.items() if expires > now
            }
            self._sessions[token] = now + SESSION_TTL_SECONDS
        return token

    def valid_session(self, token: str | None) -> bool:
        if not token:
            return False
        with self._sessions_lock:
            expires = self._sessions.get(token)
            if expires is None:
                return False
            if expires <= time.monotonic():
                self._sessions.pop(token, None)
                return False
            return True

    def revoke_session(self, token: str | None) -> None:
        if token:
            with self._sessions_lock:
                self._sessions.pop(token, None)

    def login_retry_after(self, peer: str) -> int | None:
        with self._login_lock:
            now = self._now()
            locked_until = self._login_locks.get(peer)
            if locked_until is not None and locked_until > now:
                return math.ceil((locked_until - now).total_seconds())
            self._login_locks.pop(peer, None)
            window = dt.timedelta(seconds=LOGIN_FAILURE_WINDOW_SECONDS)
            failures = [
                stamp
                for stamp in self._login_failures.get(peer, [])
                if now - stamp < window
            ]
            if failures:
                self._login_failures[peer] = failures
            else:
                self._login_failures.pop(peer, None)
            return None

    def record_login_failure(self, peer: str) -> None:
        with self._login_lock:
            now = self._now()
            window = dt.timedelta(seconds=LOGIN_FAILURE_WINDOW_SECONDS)
            failures = [
                stamp
                for stamp in self._login_failures.get(peer, [])
                if now - stamp < window
            ]
            failures.append(now)
            self._login_failures[peer] = failures
            if len(failures) >= MAX_LOGIN_FAILURES:
                self._login_locks[peer] = now + dt.timedelta(
                    seconds=LOGIN_LOCKOUT_SECONDS
                )

    def record_login_success(self, peer: str) -> None:
        with self._login_lock:
            self._login_failures.pop(peer, None)
            self._login_locks.pop(peer, None)


class BackgroundWorker:
    def __init__(self, service: TeleflowService, interval: float = 2.0):
        self.service = service
        self.interval = max(0.25, interval)
        self._stop = threading.Event()
        self._thread = threading.Thread(
            target=self._run, name="teleflow-worker", daemon=True
        )

    def start(self) -> None:
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()
        self._thread.join()

    def _run(self) -> None:
        while not self._stop.is_set():
            if not self.service.demo:
                try:
                    self.service.poll_updates()
                except TelegramError as error:
                    LOG.warning(
                        "Telegram update polling failed: %s", error.message[:160]
                    )
                except Exception as error:
                    LOG.warning(
                        "Telegram update polling failed (%s)", type(error).__name__
                    )
                try:
                    self.service.dispatch_pending()
                except (TelegramError, APIError) as error:
                    LOG.warning("Background dispatch failed: %s", error.message[:160])
                except Exception as error:
                    LOG.warning("Background dispatch failed (%s)", type(error).__name__)
            self._stop.wait(self.interval)


class TeleflowRequestHandler(http.server.BaseHTTPRequestHandler):
    server_version = "Teleflow/1.0"
    sys_version = ""
    protocol_version = "HTTP/1.1"

    def __init__(
        self, *args: Any, service: TeleflowService, static_root: Path, **kwargs: Any
    ):
        self.service = service
        self.static_root = static_root.resolve()
        super().__init__(*args, **kwargs)

    def log_message(self, _format: str, *args: Any) -> None:
        path = self.path.split("?", 1)[0]
        LOG.info("%s %s", self.command, path)

    def log_error(self, _format: str, *args: Any) -> None:
        LOG.warning("HTTP request error")

    def do_GET(self) -> None:
        self._dispatch()

    def do_HEAD(self) -> None:
        self._dispatch(head_only=True)

    def do_POST(self) -> None:
        self._dispatch()

    def do_PUT(self) -> None:
        self._dispatch()

    def do_PATCH(self) -> None:
        self._dispatch()

    def do_DELETE(self) -> None:
        self._dispatch()

    def do_OPTIONS(self) -> None:
        self._dispatch()

    def send_error(
        self, code: int, message: str | None = None, explain: str | None = None
    ) -> None:
        if self.path.startswith("/api"):
            self._send_json(
                code,
                {
                    "error": message
                    or http.server.BaseHTTPRequestHandler.responses.get(
                        code, ("Request failed",)
                    )[0]
                },
            )
        else:
            self.send_response(code)
            self.send_header("Content-Length", "0")
            self.end_headers()

    def _dispatch(self, head_only: bool = False) -> None:
        self._body_consumed = False
        if not self._host_is_trusted():
            self._discard_request_body()
            self.close_connection = True
            self._send_json(
                403, {"error": "Untrusted Host header"}, head_only=head_only
            )
            return
        parsed = urllib.parse.urlsplit(self.path)
        try:
            path = urllib.parse.unquote(parsed.path, errors="strict")
        except (UnicodeDecodeError, ValueError):
            self._send_json(400, {"error": "Invalid URL path"})
            return
        if path == "/api" or path.startswith("/api/"):
            try:
                self._handle_api(path)
            except APIError as error:
                if (
                    self.command in {"POST", "PUT", "PATCH", "DELETE"}
                    and not self._body_consumed
                ):
                    self._discard_request_body()
                extra_headers = (
                    [("Retry-After", str(error.retry_after))]
                    if error.retry_after is not None
                    else None
                )
                self._send_json(
                    error.status,
                    {"error": error.message},
                    extra_headers=extra_headers,
                )
            except sqlite3.Error:
                LOG.error("Database operation failed")
                self._send_json(500, {"error": "Database operation failed"})
            except TelegramError as error:
                self._send_json(502, {"error": error.message})
            except Exception as error:
                LOG.error("Request failed (%s)", type(error).__name__)
                self._send_json(500, {"error": "Internal server error"})
            return
        if self.command not in {"GET", "HEAD"}:
            self.close_connection = True
            self._send_json(405, {"error": "Method not allowed"})
            return
        self._serve_static(path, head_only=head_only)

    def _request_cookie(self) -> str | None:
        cookie = http.cookies.SimpleCookie()
        try:
            cookie.load(self.headers.get("Cookie", ""))
        except http.cookies.CookieError:
            return None
        morsel = cookie.get(SESSION_COOKIE)
        return morsel.value if morsel else None

    def _host_header(self) -> str | None:
        values = self.headers.get_all("Host", [])
        if len(values) != 1:
            return None
        return values[0]

    def _host_is_trusted(self) -> bool:
        authority = self._host_header()
        if authority is None:
            return False
        public_origin = self.service.public_origin
        scheme = (
            urllib.parse.urlsplit(public_origin).scheme if public_origin else "http"
        )
        try:
            request_host = _parse_authority(authority, scheme)
        except ValueError:
            return False
        if public_origin:
            configured = urllib.parse.urlsplit(public_origin)
            try:
                return request_host == _parse_authority(
                    configured.netloc, configured.scheme
                )
            except ValueError:
                return False

        bound_host = str(self.server.server_address[0]).strip("[]").casefold()
        bound_port = int(self.server.server_address[1])
        if is_loopback_host(bound_host):
            configured_host = (
                str(getattr(self.server, "teleflow_bind_host", bound_host))
                .strip("[]")
                .casefold()
            )
            allowed_hosts = {bound_host, configured_host, "localhost"}
            return request_host[0] in allowed_hosts and request_host[1] == bound_port
        return self.service.public_demo

    def _origin_is_same(self) -> bool:
        fetch_site = self.headers.get("Sec-Fetch-Site", "").lower()
        if fetch_site == "cross-site":
            return False
        origin_headers = self.headers.get_all("Origin", [])
        referer_headers = self.headers.get_all("Referer", [])
        if len(origin_headers) > 1 or len(referer_headers) > 1:
            return False
        source = origin_headers[0] if origin_headers else None
        is_referer = source is None
        if is_referer:
            source = referer_headers[0] if referer_headers else None
        if source is None:
            return False
        try:
            origin = urllib.parse.urlsplit(source)
            scheme = origin.scheme.casefold()
            if scheme not in {"http", "https"} or not origin.netloc:
                return False
            if not is_referer and (origin.path or origin.query or origin.fragment):
                return False
            source_authority = _parse_authority(origin.netloc, scheme)
            if self.service.public_origin:
                configured = urllib.parse.urlsplit(self.service.public_origin)
                return (scheme, source_authority) == (
                    configured.scheme,
                    _parse_authority(configured.netloc, configured.scheme),
                )

            request_host = _parse_authority(self._host_header() or "", scheme)
            if source_authority != request_host:
                return False
            bound_host = str(self.server.server_address[0]).strip("[]").casefold()
            if is_loopback_host(bound_host):
                return scheme == "http"
            if not self.service.public_demo:
                return False
            forwarded = (
                self.headers.get("X-Forwarded-Proto", "")
                .split(",", 1)[0]
                .strip()
                .casefold()
            )
            return not forwarded or forwarded == scheme
        except ValueError:
            return False

    def _set_session_cookie(self, token: str, max_age: int) -> None:
        secure = bool(
            self.service.public_origin
            and urllib.parse.urlsplit(self.service.public_origin).scheme == "https"
        )
        value = f"{SESSION_COOKIE}={token}; Path=/; HttpOnly; SameSite=Strict; Max-Age={max_age}"
        if secure:
            value += "; Secure"
        self._extra_headers = [("Set-Cookie", value)]

    def _discard_request_body(self) -> None:
        if self.headers.get("Transfer-Encoding"):
            self.close_connection = True
            return
        lengths = self.headers.get_all("Content-Length", [])
        if len(lengths) > 1:
            self.close_connection = True
            return
        try:
            length = int(lengths[0]) if lengths else 0
        except ValueError:
            self.close_connection = True
            return
        if length < 0 or length > MAX_BODY_BYTES:
            self.close_connection = True
            return
        remaining = length
        while remaining:
            try:
                chunk = self.rfile.read(min(8192, remaining))
            except OSError:
                self.close_connection = True
                return
            if not chunk:
                self.close_connection = True
                return
            remaining -= len(chunk)
        self._body_consumed = True

    def _send_json(
        self,
        status: int,
        payload: dict[str, Any],
        *,
        head_only: bool = False,
        extra_headers: list[tuple[str, str]] | None = None,
    ) -> None:
        body = json.dumps(payload, ensure_ascii=False, separators=(",", ":")).encode(
            "utf-8"
        )
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("Referrer-Policy", "same-origin")
        self.send_header("X-Frame-Options", "SAMEORIGIN")
        if self.close_connection:
            self.send_header("Connection", "close")
        for key, value in getattr(self, "_extra_headers", []):
            self.send_header(key, value)
        self._extra_headers = []
        for key, value in extra_headers or []:
            self.send_header(key, value)
        self.end_headers()
        if not head_only:
            self.wfile.write(body)

    def _read_json(self) -> dict[str, Any]:
        if self.headers.get("Transfer-Encoding"):
            self.close_connection = True
            raise APIError(400, "Transfer-Encoding is not supported")
        lengths = self.headers.get_all("Content-Length", [])
        if len(lengths) > 1:
            self.close_connection = True
            raise APIError(400, "Duplicate Content-Length")
        raw_length = lengths[0] if lengths else "0"
        try:
            length = int(raw_length)
        except ValueError:
            self.close_connection = True
            raise APIError(400, "Invalid Content-Length") from None
        if length < 0:
            self.close_connection = True
            raise APIError(400, "Invalid Content-Length")
        if length > MAX_BODY_BYTES:
            self.close_connection = True
            raise APIError(413, "Request body is too large")
        if length == 0:
            self._body_consumed = True
            return {}
        content_type = (
            self.headers.get("Content-Type", "").split(";", 1)[0].strip().lower()
        )
        if content_type != "application/json":
            raise APIError(415, "Content-Type must be application/json")
        try:
            body = self.rfile.read(length)
        except OSError:
            self.close_connection = True
            raise APIError(400, "Incomplete request body") from None
        if len(body) != length:
            self.close_connection = True
            raise APIError(400, "Incomplete request body")
        self._body_consumed = True
        try:
            result = json.loads(body.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError):
            raise APIError(400, "Request body must be valid JSON") from None
        if not isinstance(result, dict):
            raise APIError(400, "Request body must be a JSON object")
        return result

    def _require_id(self, value: str, name: str) -> int:
        if not re.fullmatch(r"[1-9]\d{0,17}", value):
            raise APIError(404, f"{name} not found")
        return int(value)

    def _handle_api(self, path: str) -> None:
        method = self.command
        if method == "OPTIONS":
            raise APIError(405, "Method not allowed")
        public_routes = {
            "/api/health",
            "/api/status",
            "/api/login",
            "/api/signout",
            "/api/logout",
        }
        mutating = method in {"POST", "PUT", "PATCH", "DELETE"}
        if mutating and not self._origin_is_same():
            raise APIError(403, "Cross-site request rejected")
        if self.service.password is not None and path not in public_routes:
            if not self.service.valid_session(self._request_cookie()):
                raise APIError(401, "Authentication required")

        if path == "/api/health" and method == "GET":
            self._send_json(200, {"ok": True})
            return
        if path == "/api/status" and method == "GET":
            self._send_json(200, self.service.status())
            return
        if path == "/api/login" and method == "POST":
            data = self._read_json()
            if self.service.password is None:
                self._send_json(200, {"ok": True})
                return
            peer = str(self.client_address[0]) if self.client_address else "unknown"
            retry_after = self.service.login_retry_after(peer)
            if retry_after is not None:
                raise APIError(
                    429,
                    "Too many failed login attempts; wait before retrying",
                    retry_after,
                )
            password = data.get("password")
            if not isinstance(password, str) or not secrets.compare_digest(
                password.encode("utf-8"), self.service.password.encode("utf-8")
            ):
                self.service.record_login_failure(peer)
                raise APIError(401, "Invalid password")
            self.service.record_login_success(peer)
            token = self.service.issue_session()
            self._set_session_cookie(token, SESSION_TTL_SECONDS)
            self._send_json(200, {"ok": True})
            return
        if path in {"/api/signout", "/api/logout"} and method == "POST":
            self.service.revoke_session(self._request_cookie())
            self._set_session_cookie("", 0)
            self._send_json(200, {"ok": True})
            return

        if path == "/api/accounts" or path.startswith("/api/accounts/"):
            self._handle_accounts(path, method)
            return

        if path == "/api/subscribers" and method == "GET":
            self._send_json(200, {"items": self.service.list_subscribers()})
            return
        match = re.fullmatch(r"/api/subscribers/(-?\d+)", path)
        if match:
            if method != "PATCH":
                raise APIError(405, "Method not allowed")
            data = self._read_json()
            if set(data) != {"opted_in"} or not isinstance(data["opted_in"], bool):
                raise APIError(400, "PATCH subscriber accepts only opted_in boolean")
            if data["opted_in"]:
                raise APIError(
                    400, "Only the subscriber can restore consent by sending /start"
                )
            try:
                chat_id = int(match.group(1))
            except ValueError:
                raise APIError(404, "Subscriber not found") from None
            self._send_json(200, {"item": self.service.opt_out_subscriber(chat_id)})
            return
        if path == "/api/chats":
            if method == "GET":
                self._send_json(200, {"items": self.service.list_chats()})
            elif method == "POST":
                item = self.service.add_chat(self._read_json().get("chat_id"))
                self._send_json(201, {"item": item})
            else:
                raise APIError(405, "Method not allowed")
            return
        match = re.fullmatch(r"/api/chats/([^/]+)", path)
        if match:
            if method != "DELETE":
                raise APIError(405, "Method not allowed")
            self.service.delete_chat(match.group(1))
            self._send_json(200, {"ok": True})
            return

        if path == "/api/campaigns":
            if method == "GET":
                self._send_json(200, {"items": self.service.list_campaigns()})
            elif method == "POST":
                self._send_json(201, self.service.create_campaign(self._read_json()))
            else:
                raise APIError(405, "Method not allowed")
            return
        match = re.fullmatch(
            r"/api/campaigns/(\d+)(?:/(schedule|send|retry|cancel))?", path
        )
        if match:
            campaign_id = self._require_id(match.group(1), "Campaign")
            action = match.group(2)
            if action == "schedule" and method == "POST":
                data = self._read_json()
                self._send_json(
                    200,
                    self.service.schedule_campaign(
                        campaign_id, data.get("scheduled_at")
                    ),
                )
            elif action == "send" and method == "POST":
                self._read_json()
                self._send_json(202, self.service.send_campaign(campaign_id))
            elif action == "retry" and method == "POST":
                self._read_json()
                self._send_json(202, self.service.retry_failed_campaign(campaign_id))
            elif action == "cancel" and method == "POST":
                self._read_json()
                self._send_json(200, self.service.cancel_campaign_schedule(campaign_id))
            elif action is None and method == "PUT":
                self._send_json(
                    200, self.service.update_campaign(campaign_id, self._read_json())
                )
            elif action is None and method == "DELETE":
                self.service.delete_campaign(campaign_id)
                self._send_json(200, {"ok": True})
            else:
                raise APIError(405, "Method not allowed")
            return

        if path == "/api/inbox" and method == "GET":
            self._send_json(200, {"items": self.service.list_inbox()})
            return
        match = re.fullmatch(r"/api/inbox/(-?\d+)(?:/(reply))?", path)
        if match:
            try:
                chat_id = int(match.group(1))
            except ValueError:
                raise APIError(404, "Contact not found") from None
            if chat_id <= 0 or chat_id > 2**63 - 1:
                raise APIError(404, "Contact not found")
            if match.group(2) == "reply" and method == "POST":
                body = self.service.reply_to_contact(
                    chat_id, self._read_json().get("body")
                )
                self._send_json(200, {"message": body})
            elif match.group(2) is None and method == "GET":
                self._send_json(200, self.service.get_conversation(chat_id))
            else:
                raise APIError(405, "Method not allowed")
            return

        if path == "/api/rules":
            if method == "GET":
                self._send_json(200, {"items": self.service.list_rules()})
            elif method == "POST":
                self._send_json(
                    201, {"item": self.service.create_rule(self._read_json())}
                )
            else:
                raise APIError(405, "Method not allowed")
            return
        match = re.fullmatch(r"/api/rules/(\d+)", path)
        if match:
            rule_id = self._require_id(match.group(1), "Rule")
            if method == "PATCH":
                data = self._read_json()
                if set(data) != {"enabled"}:
                    raise APIError(400, "PATCH rule accepts only enabled")
                self._send_json(
                    200,
                    {
                        "item": self.service.set_rule_enabled(
                            rule_id, data.get("enabled")
                        )
                    },
                )
            elif method == "DELETE":
                self.service.delete_rule(rule_id)
                self._send_json(200, {"ok": True})
            else:
                raise APIError(405, "Method not allowed")
            return

        if path == "/api/ai/draft" and method == "POST":
            self._send_json(200, self.service.draft_with_ai(self._read_json()))
            return
        if path == "/api/sync" and method == "POST":
            self._read_json()
            try:
                processed = self.service.poll_updates()
            except TelegramError as error:
                raise APIError(502, error.message) from None
            if not self.service.demo:
                self.service.dispatch_pending()
            self._send_json(200, {"processed": processed})
            return
        if path == "/api/analytics" and method == "GET":
            self._send_json(200, self.service.analytics())
            return
        raise APIError(404, "Not found")

    def _handle_accounts(self, path: str, method: str) -> None:
        if self.service.password is None or not self.service.valid_session(
            self._request_cookie()
        ):
            raise APIError(401, "Authentication required")
        accounts = self.service.accounts
        if accounts is None:
            raise APIError(403, "User-account integration is disabled")
        try:
            if path == "/api/accounts":
                if method == "GET":
                    self._send_json(200, {"items": accounts.list_accounts()})
                elif method == "POST":
                    data = self._read_json()
                    self._send_json(
                        201,
                        {
                            "item": accounts.import_session(
                                data.get("session"), data.get("label")
                            )
                        },
                    )
                else:
                    raise APIError(405, "Method not allowed")
                return
            match = re.fullmatch(r"/api/accounts/([1-9]\d{0,18})", path)
            if match:
                if method != "DELETE":
                    raise APIError(405, "Method not allowed")
                accounts.remove(int(match.group(1)))
                self._send_json(200, {"ok": True, "revoked": True})
                return
            match = re.fullmatch(r"/api/accounts/([1-9]\d{0,18})/forget", path)
            if match:
                if method != "POST":
                    raise APIError(405, "Method not allowed")
                if self._read_json().get("confirm") != "forget_without_revocation":
                    raise APIError(
                        400, "Explicit local-forget confirmation is required"
                    )
                accounts.remove(int(match.group(1)), revoke=False)
                self._send_json(200, {"ok": True, "revoked": False})
                return
            match = re.fullmatch(r"/api/accounts/([1-9]\d{0,18})/dialogs", path)
            if match:
                if method != "GET":
                    raise APIError(405, "Method not allowed")
                self._send_json(200, accounts.list_dialogs(int(match.group(1))))
                return
            match = re.fullmatch(
                r"/api/accounts/([1-9]\d{0,18})/dialogs/(-?\d{1,19})/replies/([0-9a-f-]{36})",
                path,
            )
            if match:
                if method != "GET":
                    raise APIError(405, "Method not allowed")
                self._send_json(
                    200,
                    accounts.reply_status(
                        int(match.group(1)), int(match.group(2)), match.group(3)
                    ),
                )
                return
            match = re.fullmatch(
                r"/api/accounts/([1-9]\d{0,18})/dialogs/(-?\d{1,19})(?:/(reply|review))?",
                path,
            )
            if match:
                account_id, dialog_id = int(match.group(1)), int(match.group(2))
                if match.group(3) == "reply" and method == "POST":
                    data = self._read_json()
                    self._send_json(
                        200,
                        {
                            "message": accounts.send_reply(
                                account_id,
                                dialog_id,
                                data.get("body"),
                                data.get("request_id"),
                            )
                        },
                    )
                elif match.group(3) == "review" and method == "POST":
                    data = self._read_json()
                    accounts.acknowledge_unknown(
                        account_id,
                        dialog_id,
                        data.get("request_id"),
                        data.get("confirm"),
                    )
                    self._send_json(200, {"ok": True})
                elif match.group(3) is None and method == "GET":
                    self._send_json(200, accounts.conversation(account_id, dialog_id))
                else:
                    raise APIError(405, "Method not allowed")
                return
            raise APIError(404, "Not found")
        except AccountError as error:
            raise APIError(error.status, error.message, error.retry_after) from None

    def _serve_static(self, path: str, *, head_only: bool) -> None:
        if "\\" in path or "\x00" in path:
            self._send_json(404, {"error": "Not found"}, head_only=head_only)
            return
        pieces = [piece for piece in path.split("/") if piece]
        if any(piece in {".", ".."} or piece.startswith(".") for piece in pieces):
            self._send_json(404, {"error": "Not found"}, head_only=head_only)
            return
        relative = Path(*pieces) if pieces else Path("index.html")
        try:
            candidate = (self.static_root / relative).resolve(strict=True)
            candidate.relative_to(self.static_root)
            if candidate.is_dir():
                candidate = (candidate / "index.html").resolve(strict=True)
                candidate.relative_to(self.static_root)
            if not candidate.is_file():
                raise FileNotFoundError
            content = candidate.read_bytes()
        except (OSError, ValueError, RuntimeError):
            self._send_json(404, {"error": "Not found"}, head_only=head_only)
            return
        content_type = (
            mimetypes.guess_type(candidate.name)[0] or "application/octet-stream"
        )
        self.send_response(200)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(content)))
        self.send_header("Cache-Control", "no-cache")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("Referrer-Policy", "same-origin")
        self.send_header("X-Frame-Options", "SAMEORIGIN")
        self.end_headers()
        if not head_only:
            self.wfile.write(content)


class TeleflowHTTPServer(http.server.ThreadingHTTPServer):
    daemon_threads = False
    block_on_close = True
    allow_reuse_address = True

    def get_request(self):
        request, client_address = super().get_request()
        request.settimeout(15)
        return request, client_address


class TeleflowHTTPServerV6(TeleflowHTTPServer):
    address_family = socket.AF_INET6


def is_loopback_host(host: str) -> bool:
    normalized = host.strip().strip("[]").casefold()
    if normalized == "localhost" or normalized.endswith(".localhost"):
        return True
    try:
        return ipaddress.ip_address(normalized).is_loopback
    except ValueError:
        return False


def is_public_demo_mode(host: str, password: str | None, demo: bool) -> bool:
    return bool(demo and password is None and not is_loopback_host(host))


def resolve_database_location(
    db_argument: Path | None,
    environment_db: str | None,
    *,
    public_demo: bool,
) -> tuple[Path, Any | None]:
    if public_demo:
        if db_argument is not None or environment_db:
            raise ValueError(
                "unauthenticated public demo cannot use --db or TELEFLOW_DB"
            )
        temporary_directory = tempfile.TemporaryDirectory(prefix="teleflow-demo-")
        return Path(temporary_directory.name) / "teleflow.sqlite3", temporary_directory
    configured_db = db_argument or (Path(environment_db) if environment_db else None)
    return configured_db or BASE_DIR / "teleflow.sqlite3", None


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Run the Teleflow Telegram campaign web app"
    )
    parser.add_argument("--host", default=os.environ.get("TELEFLOW_HOST", "127.0.0.1"))
    parser.add_argument(
        "--port", type=int, default=int(os.environ.get("TELEFLOW_PORT", "3000"))
    )
    parser.add_argument("--db", type=Path, default=None)
    parser.add_argument(
        "--public-origin",
        default=os.environ.get("TELEFLOW_PUBLIC_ORIGIN"),
        help="canonical external origin, e.g. https://teleflow.example.com",
    )
    parser.add_argument(
        "--demo",
        action="store_true",
        default=os.environ.get("TELEFLOW_DEMO", "").casefold() in {"1", "true", "yes"},
        help="disable Telegram polling and all Telegram sends",
    )
    args = parser.parse_args(argv)
    password = os.environ.get("TELEFLOW_PASSWORD") or None
    account_api_id = None
    account_api_hash = None
    account_session_key = None
    if not args.demo:
        raw_api_id = os.environ.get("TELEFLOW_API_ID")
        if raw_api_id:
            try:
                account_api_id = int(raw_api_id)
            except ValueError:
                parser.error("TELEFLOW_API_ID must be a positive integer")
        account_api_hash = os.environ.get("TELEFLOW_API_HASH")
        account_session_key = os.environ.get("TELEFLOW_SESSION_KEY")
    public_demo = is_public_demo_mode(args.host, password, args.demo)
    if not is_loopback_host(args.host) and not public_demo and password is None:
        parser.error(
            "refusing non-loopback binding without TELEFLOW_PASSWORD; use --demo for an isolated public demo"
        )
    if not 0 <= args.port <= 65535:
        parser.error("--port must be between 0 and 65535")
    public_origin = None
    if args.public_origin:
        try:
            public_origin = normalize_public_origin(args.public_origin)
        except ValueError as error:
            parser.error(str(error))
    if not is_loopback_host(args.host) and not public_demo:
        if public_origin is None:
            parser.error(
                "non-loopback deployments require TELEFLOW_PUBLIC_ORIGIN or --public-origin"
            )
        if urllib.parse.urlsplit(public_origin).scheme != "https":
            parser.error("non-loopback TELEFLOW_PUBLIC_ORIGIN must use HTTPS")
    try:
        db_path, temporary_db = resolve_database_location(
            args.db,
            os.environ.get("TELEFLOW_DB"),
            public_demo=public_demo,
        )
    except ValueError as error:
        parser.error(str(error))

    logging.basicConfig(
        level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s"
    )
    service = None
    server = None
    worker = None
    try:
        service = TeleflowService(
            db_path,
            bot_token=None if public_demo else os.environ.get("TELEFLOW_BOT_TOKEN"),
            openai_api_key=None if public_demo else os.environ.get("OPENAI_API_KEY"),
            openai_model=os.environ.get("OPENAI_MODEL", "gpt-4o-mini"),
            password=password,
            demo=args.demo,
            public_origin=public_origin,
            public_demo=public_demo,
            account_api_id=account_api_id,
            account_api_hash=account_api_hash,
            account_session_key=account_session_key,
        )

        def handler(
            *handler_args: Any, **handler_kwargs: Any
        ) -> TeleflowRequestHandler:
            return TeleflowRequestHandler(
                *handler_args,
                service=service,
                static_root=BASE_DIR / "static",
                **handler_kwargs,
            )

        server_class = TeleflowHTTPServerV6 if ":" in args.host else TeleflowHTTPServer
        server = server_class((args.host, args.port), handler)
        server.teleflow_bind_host = args.host
        worker = BackgroundWorker(service)
        LOG.info(
            "Teleflow listening on %s:%s%s",
            args.host,
            server.server_port,
            " (isolated public demo; ephemeral DB, AI and Telegram disabled)"
            if public_demo
            else " (demo; Telegram sends disabled)"
            if args.demo
            else "",
        )
        worker.start()
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    except DatabaseInUseError as error:
        parser.error(str(error))
    except ValueError as error:
        parser.error(str(error))
    finally:
        if worker is not None:
            worker.stop()
        if server is not None:
            server.server_close()
        if service is not None:
            service.close()
        if temporary_db is not None:
            temporary_db.cleanup()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
