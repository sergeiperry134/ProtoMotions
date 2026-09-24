# SPDX-License-Identifier: Apache-2.0
"""Encrypted, account-scoped storage for explicitly connected Telegram users."""

from __future__ import annotations

import datetime as dt
import hashlib
import math
import re
import sqlite3
import threading
from typing import Any


MIN_SEND_INTERVAL = 5
MAX_SENDS_PER_HOUR = 30
MAX_SESSION_LENGTH = 8192
MAX_MESSAGE_LENGTH = 4096
ACCOUNT_HEALTH = ("ok", "restricted", "unauthorized")
USERNAME_PATTERN = re.compile(r"[A-Za-z][A-Za-z0-9_]{4,31}")
MAX_NAME_LENGTH = 64
MAX_BIO_LENGTH = 140
_KEEP = object()


class AccountError(Exception):
    def __init__(self, status: int, message: str, retry_after: int | None = None):
        super().__init__(message)
        self.status = status
        self.message = message
        self.retry_after = retry_after


class AccountManager:
    def __init__(self, service: Any, key: str, gateway: Any):
        try:
            from cryptography.fernet import Fernet

            self._cipher = Fernet(key.encode("ascii"))
        except (ImportError, ValueError, TypeError, UnicodeError) as error:
            raise ValueError(
                "A valid TELEFLOW_SESSION_KEY and cryptography are required"
            ) from error
        self._service = service
        self._gateway = gateway
        self._locks_guard = threading.Lock()
        self._locks: dict[int, threading.RLock] = {}
        with self._service._connection() as connection:
            connection.executescript(
                """
                CREATE TABLE IF NOT EXISTS user_accounts (
                    id INTEGER PRIMARY KEY,
                    display_name TEXT NOT NULL,
                    username TEXT,
                    session_ciphertext BLOB NOT NULL,
                    created_at TEXT NOT NULL,
                    next_send_at TEXT
                );
                CREATE TABLE IF NOT EXISTS user_account_outbox (
                    request_id TEXT PRIMARY KEY,
                    account_id INTEGER NOT NULL REFERENCES user_accounts(id) ON DELETE CASCADE,
                    dialog_id INTEGER NOT NULL,
                    body_hash TEXT NOT NULL,
                    state TEXT NOT NULL CHECK(state IN ('pending', 'sent', 'rejected', 'unknown')),
                    message_id INTEGER,
                    created_at TEXT NOT NULL,
                    reviewed_at TEXT
                );
                CREATE INDEX IF NOT EXISTS user_account_outbox_rate_idx
                    ON user_account_outbox(account_id, created_at, state);
                """
            )
            columns = {
                row["name"]
                for row in connection.execute("PRAGMA table_info(user_account_outbox)")
            }
            if "reviewed_at" not in columns:
                connection.execute(
                    "ALTER TABLE user_account_outbox ADD COLUMN reviewed_at TEXT"
                )
            connection.execute(
                """CREATE INDEX IF NOT EXISTS user_account_outbox_unresolved_idx
                   ON user_account_outbox(account_id, dialog_id, state, reviewed_at)"""
            )
            account_columns = {
                row["name"]
                for row in connection.execute("PRAGMA table_info(user_accounts)")
            }
            for column in ("health", "health_detail", "checked_at"):
                if column not in account_columns:
                    connection.execute(
                        f"ALTER TABLE user_accounts ADD COLUMN {column} TEXT"
                    )
            row = connection.execute(
                "SELECT session_ciphertext FROM user_accounts LIMIT 1"
            ).fetchone()
            if row is not None:
                from cryptography.fernet import InvalidToken

                try:
                    self._cipher.decrypt(row["session_ciphertext"])
                except InvalidToken:
                    raise ValueError(
                        "TELEFLOW_SESSION_KEY cannot decrypt stored account sessions"
                    ) from None
            connection.execute(
                "UPDATE user_account_outbox SET state='unknown' WHERE state='pending'"
            )
            connection.commit()

    def close(self) -> None:
        self._gateway.close()

    def _lock(self, account_id: int) -> threading.RLock:
        with self._locks_guard:
            return self._locks.setdefault(account_id, threading.RLock())

    @staticmethod
    def _id(value: Any) -> int:
        if (
            isinstance(value, bool)
            or not isinstance(value, int)
            or not 0 < value < 2**63
        ):
            raise AccountError(400, "Invalid account ID")
        return value

    @staticmethod
    def _dialog_id(value: Any) -> int:
        if (
            isinstance(value, bool)
            or not isinstance(value, int)
            or not -(2**63) < value < 2**63
        ):
            raise AccountError(400, "Invalid dialog ID")
        return value

    @staticmethod
    def _account(row: sqlite3.Row) -> dict[str, Any]:
        health = row["health"] if row["health"] in ACCOUNT_HEALTH else "unknown"
        return {
            "id": str(row["id"]),
            "display_name": row["display_name"],
            "username": row["username"],
            "created_at": row["created_at"],
            "health": health,
            "health_detail": row["health_detail"],
            "checked_at": row["checked_at"],
        }

    def list_accounts(self) -> list[dict[str, Any]]:
        with self._service._connection() as connection:
            rows = connection.execute(
                """SELECT id, display_name, username, created_at, health, health_detail,
                          checked_at
                   FROM user_accounts ORDER BY created_at, id"""
            ).fetchall()
        return [self._account(row) for row in rows]

    def _account_by_id(self, account_id: int) -> dict[str, Any]:
        with self._service._connection() as connection:
            row = connection.execute(
                """SELECT id, display_name, username, created_at, health, health_detail,
                          checked_at
                   FROM user_accounts WHERE id=?""",
                (account_id,),
            ).fetchone()
        if row is None:
            raise AccountError(404, "Account not found")
        return self._account(row)

    def _set_health(
        self,
        account_id: int,
        health: str,
        detail: str | None,
        username: Any = _KEEP,
    ) -> None:
        assignments = "health=?, health_detail=?, checked_at=?"
        params: list[Any] = [health, detail, self._service._now_iso()]
        if username is not _KEEP:
            assignments += ", username=?"
            params.append(username)
        with self._service._transaction() as connection:
            connection.execute(
                f"UPDATE user_accounts SET {assignments} WHERE id=?",
                (*params, account_id),
            )

    def _note_unauthorized(self, account_id: int, error: AccountError) -> None:
        # 409 from the gateway means Telegram no longer accepts this session.
        if error.status == 409:
            self._set_health(account_id, "unauthorized", error.message)

    def check_account(self, account_id: int) -> dict[str, Any]:
        account_id = self._id(account_id)
        with self._lock(account_id):
            session = self._session(account_id)
            try:
                profile, updated = self._gateway.check(account_id, session)
            except AccountError as error:
                if error.status != 409:
                    raise
                self._note_unauthorized(account_id, error)
            else:
                self._save_session(account_id, session, updated)
                restricted = bool(profile.get("restricted"))
                username = profile.get("username")
                self._set_health(
                    account_id,
                    "restricted" if restricted else "ok",
                    profile.get("restriction") if restricted else None,
                    username
                    if isinstance(username, str) and len(username) <= 64
                    else None,
                )
            return self._account_by_id(account_id)

    def rename_account(self, account_id: int, label: Any) -> dict[str, Any]:
        account_id = self._id(account_id)
        if not isinstance(label, str) or not label.strip() or len(label.strip()) > 80:
            raise AccountError(400, "Account label must be 1-80 characters")
        with self._lock(account_id), self._service._transaction() as connection:
            if not connection.execute(
                "UPDATE user_accounts SET display_name=? WHERE id=?",
                (label.strip(), account_id),
            ).rowcount:
                raise AccountError(404, "Account not found")
        return self._account_by_id(account_id)

    def _validate_profile(self, data: dict[str, Any]) -> tuple[str, str, str, str]:
        allowed = {"first_name", "last_name", "username", "about"}
        if set(data) - allowed:
            raise AccountError(
                400, "Profile accepts first_name, last_name, username and about"
            )
        first_name = data.get("first_name")
        if (
            not isinstance(first_name, str)
            or not first_name.strip()
            or len(first_name.strip()) > MAX_NAME_LENGTH
        ):
            raise AccountError(400, "first_name must contain 1-64 characters")
        last_name = data.get("last_name")
        if last_name is None:
            last_name = ""
        if not isinstance(last_name, str) or len(last_name.strip()) > MAX_NAME_LENGTH:
            raise AccountError(400, "last_name must be at most 64 characters")
        username = data.get("username")
        if username is None:
            username = ""
        if not isinstance(username, str):
            raise AccountError(400, "username must be text")
        username = username.strip().lstrip("@")
        if username and not USERNAME_PATTERN.fullmatch(username):
            raise AccountError(
                400,
                "username must be 5-32 latin letters, digits or underscores, "
                "starting with a letter",
            )
        about = data.get("about")
        if about is None:
            about = ""
        if not isinstance(about, str) or len(about.strip()) > MAX_BIO_LENGTH:
            raise AccountError(
                400, f"about must be at most {MAX_BIO_LENGTH} characters"
            )
        return (
            first_name.strip(),
            last_name.strip(),
            username,
            about.strip(),
        )

    def _store_username(self, account_id: int, username: str | None) -> None:
        with self._service._transaction() as connection:
            connection.execute(
                "UPDATE user_accounts SET username=? WHERE id=?",
                (username, account_id),
            )

    def get_profile(self, account_id: int) -> dict[str, Any]:
        account_id = self._id(account_id)
        with self._lock(account_id):
            session = self._session(account_id)
            try:
                profile, updated = self._gateway.profile(account_id, session)
            except AccountError as error:
                self._note_unauthorized(account_id, error)
                raise
            self._save_session(account_id, session, updated)
            return profile

    def save_profile(self, account_id: int, data: Any) -> dict[str, Any]:
        account_id = self._id(account_id)
        if not isinstance(data, dict):
            raise AccountError(400, "Profile must be a JSON object")
        first_name, last_name, username, about = self._validate_profile(data)
        with self._lock(account_id):
            session = self._session(account_id)
            try:
                profile, updated = self._gateway.update_profile(
                    account_id, session, first_name, last_name, username, about
                )
            except AccountError as error:
                self._note_unauthorized(account_id, error)
                raise
            self._save_session(account_id, session, updated)
            self._store_username(account_id, profile.get("username") or None)
            return profile

    def prune_outbox(self, before: dt.datetime) -> int:
        cutoff = before.astimezone(dt.timezone.utc).replace(microsecond=0)
        with self._service._transaction() as connection:
            return connection.execute(
                """DELETE FROM user_account_outbox WHERE created_at<?
                   AND (state IN ('sent', 'rejected')
                        OR (state='unknown' AND reviewed_at IS NOT NULL))""",
                (cutoff.isoformat().replace("+00:00", "Z"),),
            ).rowcount

    def _session(self, account_id: int) -> str:
        with self._service._connection() as connection:
            row = connection.execute(
                "SELECT session_ciphertext FROM user_accounts WHERE id=?", (account_id,)
            ).fetchone()
        if row is None:
            raise AccountError(404, "Account not found")
        from cryptography.fernet import InvalidToken

        try:
            return self._cipher.decrypt(row["session_ciphertext"]).decode("ascii")
        except (InvalidToken, UnicodeDecodeError):
            raise AccountError(503, "Cannot decrypt the account session") from None

    def _save_session(self, account_id: int, old: str, new: str) -> None:
        if new and new != old:
            with self._service._transaction() as connection:
                connection.execute(
                    "UPDATE user_accounts SET session_ciphertext=? WHERE id=?",
                    (self._cipher.encrypt(new.encode("ascii")), account_id),
                )

    def import_session(self, raw_session: Any, label: Any = None) -> dict[str, Any]:
        if not isinstance(raw_session, str):
            raise AccountError(400, "An authorized StringSession is required")
        session = raw_session.strip()
        if not session or len(session) > MAX_SESSION_LENGTH or not session.isascii():
            raise AccountError(400, "Invalid StringSession")
        if label is not None and (
            not isinstance(label, str) or len(label.strip()) > 80
        ):
            raise AccountError(400, "Account label must be at most 80 characters")
        profile, updated_session = self._gateway.inspect(session)
        account_id = self._id(profile.get("id"))
        name = (
            (label or "").strip()
            or profile.get("display_name")
            or f"Account {account_id}"
        )
        if not isinstance(name, str) or len(name) > 80:
            name = f"Account {account_id}"
        username = profile.get("username")
        if not isinstance(username, str) or len(username) > 64:
            username = None
        restricted = bool(profile.get("restricted"))
        detail = profile.get("restriction") if restricted else None
        with self._lock(account_id):
            with self._service._transaction() as connection:
                if connection.execute(
                    "SELECT 1 FROM user_accounts WHERE id=?", (account_id,)
                ).fetchone():
                    raise AccountError(409, "This account is already connected")
                connection.execute(
                    """INSERT INTO user_accounts
                       (id, display_name, username, session_ciphertext, created_at,
                        health, health_detail, checked_at)
                       VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
                    (
                        account_id,
                        name,
                        username,
                        self._cipher.encrypt(updated_session.encode("ascii")),
                        self._service._now_iso(),
                        "restricted" if restricted else "ok",
                        detail if isinstance(detail, str) else None,
                        self._service._now_iso(),
                    ),
                )
        return self._account_by_id(account_id)

    def list_dialogs(self, account_id: int) -> dict[str, Any]:
        account_id = self._id(account_id)
        with self._lock(account_id):
            session = self._session(account_id)
            try:
                result, updated = self._gateway.dialogs(account_id, session)
            except AccountError as error:
                self._note_unauthorized(account_id, error)
                raise
            self._save_session(account_id, session, updated)
            return result

    def conversation(self, account_id: int, dialog_id: int) -> dict[str, Any]:
        account_id = self._id(account_id)
        dialog_id = self._dialog_id(dialog_id)
        with self._lock(account_id):
            session = self._session(account_id)
            try:
                result, updated = self._gateway.conversation(
                    account_id, session, dialog_id
                )
            except AccountError as error:
                self._note_unauthorized(account_id, error)
                raise
            self._save_session(account_id, session, updated)
            with self._service._connection() as connection:
                unresolved = connection.execute(
                    """SELECT request_id, state, created_at FROM user_account_outbox
                       WHERE account_id=? AND dialog_id=? AND state IN ('pending', 'unknown')
                       AND reviewed_at IS NULL ORDER BY created_at, request_id""",
                    (account_id, dialog_id),
                ).fetchall()
            result["unresolved"] = [
                {
                    "request_id": row["request_id"],
                    "state": row["state"],
                    "created_at": row["created_at"],
                }
                for row in unresolved
            ]
            result["can_send"] = bool(result["can_send"] and not unresolved)
            return result

    def reply_status(
        self, account_id: int, dialog_id: int, request_id: Any
    ) -> dict[str, Any]:
        account_id = self._id(account_id)
        dialog_id = self._dialog_id(dialog_id)
        request_id = self._request_id(request_id)
        with self._service._connection() as connection:
            row = connection.execute(
                """SELECT state, reviewed_at FROM user_account_outbox
                   WHERE account_id=? AND dialog_id=? AND request_id=?""",
                (account_id, dialog_id, request_id),
            ).fetchone()
        if row is None:
            raise AccountError(404, "Reply attempt not found")
        return {"state": row["state"], "reviewed": row["reviewed_at"] is not None}

    def acknowledge_unknown(
        self, account_id: int, dialog_id: int, request_id: Any, confirmation: Any
    ) -> None:
        account_id = self._id(account_id)
        dialog_id = self._dialog_id(dialog_id)
        request_id = self._request_id(request_id)
        if confirmation != "checked_in_telegram":
            raise AccountError(400, "Confirm that you checked this dialog in Telegram")
        with self._lock(account_id):
            with self._service._transaction() as connection:
                result = connection.execute(
                    """UPDATE user_account_outbox SET reviewed_at=?
                       WHERE account_id=? AND dialog_id=? AND request_id=?
                       AND state='unknown' AND reviewed_at IS NULL""",
                    (self._service._now_iso(), account_id, dialog_id, request_id),
                )
                if result.rowcount != 1:
                    raise AccountError(404, "Unreviewed send outcome not found")

    @staticmethod
    def _request_id(value: Any) -> str:
        if not isinstance(value, str) or not re.fullmatch(
            r"[0-9a-f]{8}(?:-[0-9a-f]{4}){3}-[0-9a-f]{12}", value
        ):
            raise AccountError(400, "A canonical request_id is required")
        return value

    def send_reply(
        self, account_id: int, dialog_id: int, body: Any, request_id: Any
    ) -> dict[str, Any]:
        account_id = self._id(account_id)
        dialog_id = self._dialog_id(dialog_id)
        if (
            not isinstance(body, str)
            or not body.strip()
            or len(body) > MAX_MESSAGE_LENGTH
        ):
            raise AccountError(400, "Message must contain 1–4096 characters")
        request_id = self._request_id(request_id)
        digest = hashlib.sha256(body.encode("utf-8")).hexdigest()
        with self._lock(account_id):
            session = self._session(account_id)
            now = self._service._now()
            with self._service._transaction() as connection:
                existing = connection.execute(
                    "SELECT * FROM user_account_outbox WHERE request_id=?",
                    (request_id,),
                ).fetchone()
                if existing:
                    if (
                        existing["account_id"],
                        existing["dialog_id"],
                        existing["body_hash"],
                    ) != (
                        account_id,
                        dialog_id,
                        digest,
                    ):
                        raise AccountError(
                            409, "request_id was used for another message"
                        )
                    if existing["state"] == "sent":
                        return {"id": existing["message_id"], "already_sent": True}
                    raise AccountError(
                        409, "Check Telegram before attempting this message again"
                    )
                unresolved = connection.execute(
                    """SELECT 1 FROM user_account_outbox
                       WHERE account_id=? AND dialog_id=? AND state IN ('pending', 'unknown')
                       AND reviewed_at IS NULL LIMIT 1""",
                    (account_id, dialog_id),
                ).fetchone()
                if unresolved:
                    raise AccountError(
                        409, "Review the previous send in Telegram before sending again"
                    )
                row = connection.execute(
                    "SELECT next_send_at FROM user_accounts WHERE id=?", (account_id,)
                ).fetchone()
                if row and row["next_send_at"]:
                    until = dt.datetime.fromisoformat(
                        row["next_send_at"].replace("Z", "+00:00")
                    )
                    if until > now:
                        raise AccountError(
                            429,
                            "Account send cooldown is active",
                            math.ceil((until - now).total_seconds()),
                        )
                recent = connection.execute(
                    """SELECT COUNT(*) FROM user_account_outbox WHERE account_id=?
                       AND created_at>=? AND state IN ('pending', 'sent', 'unknown')""",
                    (
                        account_id,
                        (now - dt.timedelta(hours=1))
                        .isoformat()
                        .replace("+00:00", "Z"),
                    ),
                ).fetchone()[0]
                if recent >= MAX_SENDS_PER_HOUR:
                    raise AccountError(429, "Hourly manual-send limit reached", 3600)
                connection.execute(
                    """INSERT INTO user_account_outbox
                       (request_id, account_id, dialog_id, body_hash, state, created_at)
                       VALUES (?, ?, ?, ?, 'pending', ?)""",
                    (
                        request_id,
                        account_id,
                        dialog_id,
                        digest,
                        self._service._now_iso(),
                    ),
                )
                connection.execute(
                    "UPDATE user_accounts SET next_send_at=? WHERE id=?",
                    (
                        (now + dt.timedelta(seconds=MIN_SEND_INTERVAL))
                        .isoformat()
                        .replace("+00:00", "Z"),
                        account_id,
                    ),
                )
            try:
                result, updated = self._gateway.send(
                    account_id, session, dialog_id, body
                )
            except AccountError as error:
                with self._service._transaction() as connection:
                    # The gateway raises 409 only before sending, so it is a safe rejection.
                    connection.execute(
                        "UPDATE user_account_outbox SET state=? WHERE request_id=?",
                        (
                            "rejected"
                            if error.status in {400, 403, 404, 409, 429}
                            else "unknown",
                            request_id,
                        ),
                    )
                    if error.retry_after is not None:
                        now = self._service._now()
                        remaining = (
                            dt.datetime.max.replace(tzinfo=dt.timezone.utc) - now
                        )
                        max_seconds = remaining.days * 86_400 + remaining.seconds
                        until = now + dt.timedelta(
                            seconds=min(error.retry_after, max_seconds)
                        )
                        connection.execute(
                            "UPDATE user_accounts SET next_send_at=? WHERE id=?",
                            (
                                until.replace(microsecond=0)
                                .isoformat()
                                .replace("+00:00", "Z"),
                                account_id,
                            ),
                        )
                self._note_unauthorized(account_id, error)
                raise
            except Exception:
                with self._service._transaction() as connection:
                    connection.execute(
                        "UPDATE user_account_outbox SET state='unknown' WHERE request_id=?",
                        (request_id,),
                    )
                raise AccountError(
                    502, "Send outcome unknown; check Telegram before retrying"
                ) from None
            with self._service._transaction() as connection:
                connection.execute(
                    """UPDATE user_account_outbox SET state='sent', message_id=?
                       WHERE request_id=? AND state='pending'""",
                    (result["id"], request_id),
                )
            self._save_session(account_id, session, updated)
            return {"id": result["id"], "already_sent": False}

    def remove(self, account_id: int, *, revoke: bool = True) -> None:
        account_id = self._id(account_id)
        with self._lock(account_id):
            session = self._session(account_id)
            if revoke:
                self._gateway.revoke_session(account_id, session)
            else:
                self._gateway.forget(account_id)
            with self._service._transaction() as connection:
                connection.execute(
                    "DELETE FROM user_accounts WHERE id=?", (account_id,)
                )
