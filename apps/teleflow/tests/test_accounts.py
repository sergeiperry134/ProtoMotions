# SPDX-License-Identifier: Apache-2.0
from __future__ import annotations

import asyncio
import concurrent.futures
import datetime as dt
import http.client
import http.cookies
import importlib
import importlib.util
import json
import os
import sys
import tempfile
import threading
import unittest
import uuid
from pathlib import Path
from types import SimpleNamespace
from typing import Any, ClassVar
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import account_transport
from account_transport import TelethonGateway
from accounts import MAX_SENDS_PER_HOUR, MIN_SEND_INTERVAL, AccountError
from server import (
    SESSION_COOKIE,
    TeleflowHTTPServer,
    TeleflowRequestHandler,
    TeleflowService,
)

try:
    from cryptography.fernet import Fernet
except ImportError:  # The account integration is optional for bot-only installs.
    Fernet = None

CRYPTOGRAPHY_AVAILABLE = Fernet is not None
TELETHON_AVAILABLE = importlib.util.find_spec("telethon") is not None
TEST_PASSWORD = "test-only-password"
TEST_API_HASH = "0" * 32
_DEFAULT_ORIGIN = object()


class MutableClock:
    def __init__(self):
        self.value = dt.datetime(2026, 1, 2, 12, 0, tzinfo=dt.timezone.utc)

    def __call__(self):
        return self.value

    def advance(self, seconds: int):
        self.value += dt.timedelta(seconds=seconds)


class FakeTelegram:
    def call(self, _method, _params=None):
        return {"ok": True, "result": {}}


class FakeGateway:
    """In-memory gateway that records which account owns each saved session."""

    def __init__(self):
        self.profiles = {}
        self.updated_sessions = {}
        self.session_owners = {}
        self.dialog_ids = {}
        self.inspect_calls = []
        self.dialog_calls = []
        self.conversation_calls = []
        self.send_calls = []
        self.send_errors = []
        self.revoke_calls = []
        self.forget_calls = []
        self.revoke_error = None
        self.check_calls = []
        self.check_result = None
        self.check_error = None
        self.next_message_id = 900
        self.closed = False

    def register_session(self, raw_session, account_id, dialog_ids=None):
        self.profiles[raw_session] = {
            "id": account_id,
            "display_name": f"Test Account {account_id}",
            "username": f"test_{account_id}",
        }
        updated = f"rotated-session-{account_id}-{len(self.updated_sessions) + 1}"
        self.updated_sessions[raw_session] = updated
        self.session_owners[updated] = account_id
        if dialog_ids is not None:
            self.dialog_ids[account_id] = set(dialog_ids)
        return updated

    def inspect(self, session):
        self.inspect_calls.append(session)
        if session not in self.profiles:
            raise AccountError(401, "Unknown fake session")
        return dict(self.profiles[session]), self.updated_sessions[session]

    def _check_session(self, account_id, session):
        if self.session_owners.get(session) != account_id:
            raise AccountError(403, "The session belongs to a different account")

    def _check_dialog(self, account_id, dialog_id):
        allowed = self.dialog_ids.get(account_id)
        if allowed is not None and dialog_id not in allowed:
            raise AccountError(404, "Dialog is outside this account's conversations")

    def dialogs(self, account_id, session):
        self._check_session(account_id, session)
        self.dialog_calls.append((account_id, session))
        ids = self.dialog_ids.get(account_id, set())
        return (
            {
                "items": [
                    {"id": dialog_id, "name": f"Dialog {dialog_id}", "kind": "private"}
                    for dialog_id in sorted(ids)
                ],
                "truncated": False,
            },
            session,
        )

    def conversation(self, account_id, session, dialog_id):
        self._check_session(account_id, session)
        self.conversation_calls.append((account_id, session, dialog_id))
        self._check_dialog(account_id, dialog_id)
        return (
            {
                "dialog": {
                    "id": dialog_id,
                    "name": f"Dialog {dialog_id}",
                    "kind": "private",
                },
                "items": [],
                "can_send": True,
            },
            session,
        )

    def send(self, account_id, session, dialog_id, body):
        self._check_session(account_id, session)
        self._check_dialog(account_id, dialog_id)
        self.send_calls.append((account_id, session, dialog_id, body))
        if self.send_errors:
            raise self.send_errors.pop(0)
        self.next_message_id += 1
        return {"id": self.next_message_id}, session

    def revoke_session(self, account_id, session):
        self._check_session(account_id, session)
        self.revoke_calls.append(account_id)
        if self.revoke_error is not None:
            raise self.revoke_error

    def check(self, account_id, session):
        self._check_session(account_id, session)
        self.check_calls.append(account_id)
        if self.check_error is not None:
            raise self.check_error
        profile = self.check_result or {
            "id": account_id,
            "restricted": False,
            "restriction": None,
            "username": f"test_{account_id}",
        }
        return dict(profile), session

    def forget(self, account_id):
        self.forget_calls.append(account_id)

    def close(self):
        self.closed = True


class LocalHTTPMixin:
    def start_http_server(self, service, root):
        static_root = root / "static"
        static_root.mkdir(exist_ok=True)

        def handler(*args, **kwargs):
            return TeleflowRequestHandler(
                *args, service=service, static_root=static_root, **kwargs
            )

        self.server = TeleflowHTTPServer(("127.0.0.1", 0), handler)
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()
        self.addCleanup(self.stop_http_server)
        self.host, self.port = self.server.server_address

    def stop_http_server(self):
        self.server.shutdown()
        self.server.server_close()
        self.thread.join(timeout=2)

    def request(
        self, method, path, payload=None, headers=None, *, origin=_DEFAULT_ORIGIN
    ):
        connection = http.client.HTTPConnection(self.host, self.port, timeout=3)
        body = (
            None
            if payload is None
            else json.dumps(payload, ensure_ascii=False).encode("utf-8")
        )
        request_headers = dict(headers or {})
        if method in {"POST", "PUT", "PATCH", "DELETE"}:
            if origin is _DEFAULT_ORIGIN:
                request_headers.setdefault("Origin", f"http://{self.host}:{self.port}")
            elif origin is None:
                request_headers.pop("Origin", None)
            else:
                request_headers["Origin"] = origin
        if payload is not None:
            request_headers.setdefault("Content-Type", "application/json")
            request_headers.setdefault("Content-Length", str(len(body)))
        connection.request(method, path, body=body, headers=request_headers)
        response = connection.getresponse()
        raw = response.read()
        parsed = (
            json.loads(raw.decode("utf-8"))
            if raw
            and response.getheader("Content-Type", "").startswith("application/json")
            else raw
        )
        response_headers = {key.lower(): value for key, value in response.getheaders()}
        result = response.status, parsed, response_headers
        connection.close()
        return result

    def login(self, password=TEST_PASSWORD):
        return self.request("POST", "/api/login", {"password": password})

    @staticmethod
    def cookie_header(set_cookie):
        cookie = http.cookies.SimpleCookie()
        cookie.load(set_cookie)
        return f"{SESSION_COOKIE}={cookie[SESSION_COOKIE].value}"


@unittest.skipUnless(
    CRYPTOGRAPHY_AVAILABLE, "cryptography is an optional account dependency"
)
class AccountManagerTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.clock = MutableClock()
        self.gateway = FakeGateway()
        self.session_key = Fernet.generate_key().decode("ascii")
        self.service = TeleflowService(
            self.root / "accounts.sqlite3",
            telegram=FakeTelegram(),
            password=TEST_PASSWORD,
            account_api_id=12345,
            account_api_hash=TEST_API_HASH,
            account_session_key=self.session_key,
            account_gateway=self.gateway,
            clock=self.clock,
        )
        self.addCleanup(self.service.close)
        self.manager = self.service.accounts
        self.assertIsNotNone(self.manager)

    def add_account(self, session, account_id=101, dialog_ids=None):
        self.gateway.register_session(session, account_id, dialog_ids)
        return self.manager.import_session(session)

    def outbox_row(self, request_id):
        with self.service._connection() as connection:
            return connection.execute(
                "SELECT * FROM user_account_outbox WHERE request_id=?", (request_id,)
            ).fetchone()

    def account_row(self, account_id):
        with self.service._connection() as connection:
            return connection.execute(
                "SELECT * FROM user_accounts WHERE id=?", (account_id,)
            ).fetchone()

    def test_database_lock_is_released_if_gateway_shutdown_fails(self):
        with patch.object(
            self.gateway, "close", side_effect=RuntimeError("test shutdown")
        ):
            with self.assertRaisesRegex(RuntimeError, "test shutdown"):
                self.service.close()

        reopened = TeleflowService(
            self.service.db_path,
            telegram=FakeTelegram(),
            password=TEST_PASSWORD,
            account_api_id=12345,
            account_api_hash=TEST_API_HASH,
            account_session_key=self.session_key,
            account_gateway=FakeGateway(),
        )
        reopened.close()

    def test_import_duplicate_is_rejected_without_replacing_saved_session(self):
        first = "first-session-for-duplicate-test"
        second = "another-authorized-session-for-same-id"
        self.add_account(first, account_id=101)
        self.gateway.register_session(second, 101)

        with self.assertRaises(AccountError) as raised:
            self.manager.import_session(second)

        self.assertEqual(raised.exception.status, 409)
        self.assertEqual(
            [str(item["id"]) for item in self.manager.list_accounts()], ["101"]
        )
        self.assertEqual(
            self.manager._session(101), self.gateway.updated_sessions[first]
        )

    def test_sessions_are_encrypted_and_scoped_to_the_imported_identity(self):
        self.add_account("session-for-account-a", 101, [1001])
        self.add_account("session-for-account-b", 202, [2002])

        account_a = self.manager.list_dialogs(101)
        account_b = self.manager.list_dialogs(202)

        self.assertEqual([str(item["id"]) for item in account_a["items"]], ["1001"])
        self.assertEqual([str(item["id"]) for item in account_b["items"]], ["2002"])
        self.assertEqual(
            self.gateway.dialog_calls,
            [
                (101, self.gateway.updated_sessions["session-for-account-a"]),
                (202, self.gateway.updated_sessions["session-for-account-b"]),
            ],
        )
        with self.assertRaises(AccountError) as raised:
            self.manager.conversation(101, 2002)
        self.assertEqual(raised.exception.status, 404)
        self.assertEqual(
            self.gateway.conversation_calls[-1],
            (101, self.gateway.updated_sessions["session-for-account-a"], 2002),
        )
        gateway_calls = len(self.gateway.dialog_calls)
        with self.assertRaises(AccountError) as missing:
            self.manager.list_dialogs(303)
        self.assertEqual(missing.exception.status, 404)
        self.assertEqual(len(self.gateway.dialog_calls), gateway_calls)

    def test_startup_rejects_a_valid_but_wrong_fernet_key(self):
        self.add_account("encrypted-session", 101, [1001])
        db_path = self.service.db_path
        different_key = Fernet.generate_key().decode("ascii")
        self.service.close()
        wrong_gateway = FakeGateway()
        with self.assertRaisesRegex(
            ValueError, "cannot decrypt stored account sessions"
        ):
            TeleflowService(
                db_path,
                telegram=FakeTelegram(),
                password=TEST_PASSWORD,
                account_api_id=12345,
                account_api_hash=TEST_API_HASH,
                account_session_key=different_key,
                account_gateway=wrong_gateway,
            )
        self.assertTrue(wrong_gateway.closed)

    def test_send_request_uuid_is_idempotent_and_bound_to_one_payload(self):
        self.add_account("send-session", 101)
        request_id = str(uuid.uuid4())

        first = self.manager.send_reply(101, 777, "A reply", request_id)
        retry = self.manager.send_reply(101, 777, "A reply", request_id)

        self.assertEqual(first, {"id": 901, "already_sent": False})
        self.assertEqual(retry, {"id": 901, "already_sent": True})
        self.assertEqual(len(self.gateway.send_calls), 1)
        for dialog_id, body in ((777, "different body"), (778, "A reply")):
            with self.subTest(dialog_id=dialog_id, body=body):
                with self.assertRaises(AccountError) as raised:
                    self.manager.send_reply(101, dialog_id, body, request_id)
                self.assertEqual(raised.exception.status, 409)
        self.assertEqual(len(self.gateway.send_calls), 1)

    def test_sent_reply_status_survives_a_lost_response_without_resending(self):
        self.add_account("sent-status-session", 101, [777, 778])
        request_id = str(uuid.uuid4())
        self.manager.send_reply(101, 777, "Delivered once", request_id)

        self.assertEqual(
            self.manager.reply_status(101, 777, request_id),
            {"state": "sent", "reviewed": False},
        )
        self.assertEqual(
            self.manager.send_reply(101, 777, "Delivered once", request_id),
            {"id": 901, "already_sent": True},
        )
        self.assertEqual(len(self.gateway.send_calls), 1)
        for account_id, dialog_id in [(101, 778), (102, 777)]:
            with self.subTest(account_id=account_id, dialog_id=dialog_id):
                with self.assertRaises(AccountError) as missing:
                    self.manager.reply_status(account_id, dialog_id, request_id)
                self.assertEqual(missing.exception.status, 404)

    def test_send_rejects_noncanonical_or_missing_request_uuids(self):
        self.add_account("uuid-session", 101)
        for request_id in (None, "", "not-a-uuid", str(uuid.uuid4()).upper()):
            with self.subTest(request_id=request_id):
                with self.assertRaises(AccountError) as raised:
                    self.manager.send_reply(101, 777, "A reply", request_id)
                self.assertEqual(raised.exception.status, 400)
        self.assertEqual(self.gateway.send_calls, [])

    def test_send_cooldown_and_hourly_limit_are_enforced(self):
        self.add_account("rate-session", 101)
        first_request = str(uuid.uuid4())
        self.manager.send_reply(101, 777, "first", first_request)

        with self.assertRaises(AccountError) as cooldown:
            self.manager.send_reply(101, 777, "too soon", str(uuid.uuid4()))
        self.assertEqual(cooldown.exception.status, 429)
        self.assertEqual(cooldown.exception.retry_after, MIN_SEND_INTERVAL)

        self.clock.advance(MIN_SEND_INTERVAL)
        for index in range(1, MAX_SENDS_PER_HOUR):
            self.manager.send_reply(101, 777, f"message {index}", str(uuid.uuid4()))
            self.clock.advance(MIN_SEND_INTERVAL)

        with self.assertRaises(AccountError) as hourly:
            self.manager.send_reply(
                101, 777, "over the hourly limit", str(uuid.uuid4())
            )
        self.assertEqual(hourly.exception.status, 429)
        self.assertEqual(hourly.exception.retry_after, 3600)
        self.assertEqual(len(self.gateway.send_calls), MAX_SENDS_PER_HOUR)

    def test_flood_wait_sets_retry_after_cooldown_and_rejected_idempotency_state(self):
        self.add_account("flood-session", 101)
        request_id = str(uuid.uuid4())
        self.gateway.send_errors.append(AccountError(429, "Pause", 17))

        with self.assertRaises(AccountError) as flood:
            self.manager.send_reply(101, 777, "first attempt", request_id)

        self.assertEqual(flood.exception.status, 429)
        self.assertEqual(flood.exception.retry_after, 17)
        self.assertEqual(self.outbox_row(request_id)["state"], "rejected")
        with self.assertRaises(AccountError) as duplicate:
            self.manager.send_reply(101, 777, "first attempt", request_id)
        self.assertEqual(duplicate.exception.status, 409)
        with self.assertRaises(AccountError) as cooldown:
            self.manager.send_reply(101, 777, "another request", str(uuid.uuid4()))
        self.assertEqual(cooldown.exception.retry_after, 17)

        self.clock.advance(17)
        result = self.manager.send_reply(101, 777, "after pause", str(uuid.uuid4()))
        self.assertFalse(result["already_sent"])
        self.assertEqual(len(self.gateway.send_calls), 2)

    def test_timeout_outcome_is_unknown_and_same_request_cannot_be_replayed(self):
        self.add_account("timeout-session", 101)
        request_id = str(uuid.uuid4())
        self.gateway.send_errors.append(AccountError(504, "Synthetic timeout"))

        with self.assertRaises(AccountError) as timed_out:
            self.manager.send_reply(101, 777, "possibly delivered", request_id)

        self.assertEqual(timed_out.exception.status, 504)
        self.assertEqual(self.outbox_row(request_id)["state"], "unknown")
        self.assertEqual(
            self.manager.reply_status(101, 777, request_id),
            {"state": "unknown", "reviewed": False},
        )
        with self.assertRaises(AccountError) as retry:
            self.manager.send_reply(101, 777, "possibly delivered", request_id)
        self.assertEqual(retry.exception.status, 409)
        self.assertIn("Check Telegram", retry.exception.message)
        self.assertEqual(len(self.gateway.send_calls), 1)

        self.manager.acknowledge_unknown(101, 777, request_id, "checked_in_telegram")
        self.assertEqual(
            self.manager.reply_status(101, 777, request_id),
            {"state": "unknown", "reviewed": True},
        )

    def test_unknown_send_blocks_new_request_after_restart_until_reviewed(self):
        raw_session = "durable-unknown-session"
        self.add_account(raw_session, 101, [777, 778])
        request_id = str(uuid.uuid4())
        self.gateway.send_errors.append(AccountError(504, "Synthetic timeout"))

        with self.assertRaises(AccountError) as timed_out:
            self.manager.send_reply(101, 777, "possibly delivered", request_id)
        self.assertEqual(timed_out.exception.status, 504)
        self.assertEqual(self.outbox_row(request_id)["state"], "unknown")

        db_path = self.service.db_path
        saved_session = self.gateway.updated_sessions[raw_session]
        self.service.close()
        restarted_gateway = FakeGateway()
        restarted_gateway.session_owners[saved_session] = 101
        restarted_gateway.dialog_ids[101] = {777, 778}
        restarted_service = TeleflowService(
            db_path,
            telegram=FakeTelegram(),
            password=TEST_PASSWORD,
            account_api_id=12345,
            account_api_hash=TEST_API_HASH,
            account_session_key=self.session_key,
            account_gateway=restarted_gateway,
            clock=self.clock,
        )
        self.addCleanup(restarted_service.close)
        self.service = restarted_service
        self.manager = restarted_service.accounts
        self.gateway = restarted_gateway

        conversation = self.manager.conversation(101, 777)
        self.assertFalse(conversation["can_send"])
        self.assertEqual(
            [item["request_id"] for item in conversation["unresolved"]], [request_id]
        )
        other_dialog = self.manager.conversation(101, 778)
        self.assertTrue(other_dialog["can_send"])
        self.assertEqual(other_dialog["unresolved"], [])

        with self.assertRaises(AccountError) as blocked:
            self.manager.send_reply(101, 777, "new request", str(uuid.uuid4()))
        self.assertEqual(blocked.exception.status, 409)
        self.assertIn("Review the previous send", blocked.exception.message)
        self.assertEqual(self.gateway.send_calls, [])

        self.clock.advance(MIN_SEND_INTERVAL)
        with self.assertRaises(AccountError) as still_blocked:
            self.manager.send_reply(101, 777, "new request", str(uuid.uuid4()))
        self.assertEqual(still_blocked.exception.status, 409)
        self.assertEqual(self.gateway.send_calls, [])

        self.manager.acknowledge_unknown(101, 777, request_id, "checked_in_telegram")
        reviewed_conversation = self.manager.conversation(101, 777)
        self.assertTrue(reviewed_conversation["can_send"])
        self.assertEqual(reviewed_conversation["unresolved"], [])
        reply = self.manager.send_reply(
            101, 777, "reviewed and ready", str(uuid.uuid4())
        )
        self.assertFalse(reply["already_sent"])
        self.assertEqual(len(self.gateway.send_calls), 1)

    def test_restart_marks_an_inflight_outbox_entry_unknown(self):
        raw_session = "inflight-send-session"
        self.add_account(raw_session, 101, [777])
        request_id = str(uuid.uuid4())
        with self.service._transaction() as connection:
            connection.execute(
                """INSERT INTO user_account_outbox
                   (request_id, account_id, dialog_id, body_hash, state, created_at)
                   VALUES (?, 101, 777, 'synthetic-hash', 'pending', ?)""",
                (request_id, self.service._now_iso()),
            )

        db_path = self.service.db_path
        saved_session = self.gateway.updated_sessions[raw_session]
        self.service.close()
        restarted_gateway = FakeGateway()
        restarted_gateway.session_owners[saved_session] = 101
        restarted_gateway.dialog_ids[101] = {777}
        restarted_service = TeleflowService(
            db_path,
            telegram=FakeTelegram(),
            password=TEST_PASSWORD,
            account_api_id=12345,
            account_api_hash=TEST_API_HASH,
            account_session_key=self.session_key,
            account_gateway=restarted_gateway,
            clock=self.clock,
        )
        self.addCleanup(restarted_service.close)
        self.service = restarted_service
        self.manager = restarted_service.accounts
        self.gateway = restarted_gateway

        self.assertEqual(self.outbox_row(request_id)["state"], "unknown")
        conversation = self.manager.conversation(101, 777)
        self.assertFalse(conversation["can_send"])
        self.assertEqual(
            [item["request_id"] for item in conversation["unresolved"]], [request_id]
        )

        self.manager.acknowledge_unknown(101, 777, request_id, "checked_in_telegram")
        reviewed = self.manager.conversation(101, 777)
        self.assertTrue(reviewed["can_send"])
        self.assertEqual(reviewed["unresolved"], [])

    def test_unexpected_send_exception_is_sanitized_and_marked_unknown(self):
        self.add_account("exception-session", 101)
        request_id = str(uuid.uuid4())
        self.gateway.send_errors.append(
            RuntimeError("synthetic private transport detail")
        )

        with self.assertRaises(AccountError) as failed:
            self.manager.send_reply(101, 777, "reply", request_id)

        self.assertEqual(failed.exception.status, 502)
        self.assertEqual(
            failed.exception.message,
            "Send outcome unknown; check Telegram before retrying",
        )
        self.assertNotIn("synthetic private transport detail", failed.exception.message)
        self.assertEqual(self.outbox_row(request_id)["state"], "unknown")

    def test_remote_revocation_failure_preserves_account_and_local_forget_removes_it(
        self,
    ):
        self.add_account("remove-session", 101)
        self.gateway.revoke_error = AccountError(502, "Synthetic revocation failure")

        with self.assertRaises(AccountError) as failed_revocation:
            self.manager.remove(101)

        self.assertEqual(failed_revocation.exception.status, 502)
        self.assertEqual(
            [str(item["id"]) for item in self.manager.list_accounts()], ["101"]
        )
        self.assertEqual(
            self.manager._session(101), self.gateway.updated_sessions["remove-session"]
        )

        self.manager.remove(101, revoke=False)
        self.assertEqual(self.manager.list_accounts(), [])
        self.assertEqual(self.gateway.revoke_calls, [101])
        self.assertEqual(self.gateway.forget_calls, [101])

    def test_account_check_records_restricted_and_revoked_sessions(self):
        imported = self.add_account("health-session", 101)
        self.assertEqual(imported["health"], "ok")
        self.assertEqual(imported["checked_at"], "2026-01-02T12:00:00Z")

        self.gateway.check_result = {
            "id": 101,
            "restricted": True,
            "restriction": "Spam reports",
            "username": "fresh_name",
        }
        self.clock.advance(60)
        checked = self.manager.check_account(101)
        self.assertEqual(
            (checked["health"], checked["health_detail"], checked["username"]),
            ("restricted", "Spam reports", "fresh_name"),
        )
        self.assertEqual(checked["checked_at"], "2026-01-02T12:01:00Z")

        self.gateway.check_error = AccountError(
            409, "This account session is no longer authorized"
        )
        revoked = self.manager.check_account(101)
        self.assertEqual(revoked["health"], "unauthorized")
        self.assertEqual(revoked["username"], "fresh_name")

        self.gateway.check_error = AccountError(503, "Could not reach Telegram")
        with self.assertRaises(AccountError) as unreachable:
            self.manager.check_account(101)
        self.assertEqual(unreachable.exception.status, 503)
        self.assertEqual(self.manager.list_accounts()[0]["health"], "unauthorized")

        self.gateway.check_error = None
        self.gateway.check_result = {
            "id": 101,
            "restricted": False,
            "restriction": None,
            "username": None,
        }
        cleared = self.manager.check_account(101)
        self.assertEqual((cleared["health"], cleared["username"]), ("ok", None))

    def test_revoked_session_send_is_rejected_and_does_not_block_dialog(self):
        self.add_account("revoked-send-session", 101)
        request_id = str(uuid.uuid4())
        self.gateway.send_errors.append(
            AccountError(409, "This account session is no longer authorized")
        )

        with self.assertRaises(AccountError) as raised:
            self.manager.send_reply(101, 777, "reply", request_id)

        self.assertEqual(raised.exception.status, 409)
        self.assertEqual(self.outbox_row(request_id)["state"], "rejected")
        self.assertEqual(self.manager.list_accounts()[0]["health"], "unauthorized")
        self.assertEqual(self.manager.conversation(101, 777)["unresolved"], [])

    def test_rename_account_validates_label(self):
        self.add_account("rename-session", 101)

        renamed = self.manager.rename_account(101, "  Основной  ")

        self.assertEqual(renamed["display_name"], "Основной")
        for label in ("", "   ", "x" * 81, None, 5):
            with self.subTest(label=label):
                with self.assertRaises(AccountError) as invalid:
                    self.manager.rename_account(101, label)
                self.assertEqual(invalid.exception.status, 400)
        with self.assertRaises(AccountError) as missing:
            self.manager.rename_account(202, "Other")
        self.assertEqual(missing.exception.status, 404)

    def test_history_pruning_keeps_unresolved_and_recent_outbox_rows(self):
        self.add_account("prune-session", 101)
        old = "2025-11-01T12:00:00Z"
        recent = "2026-01-01T12:00:00Z"
        with self.service._transaction() as connection:
            connection.executemany(
                """INSERT INTO user_account_outbox
                   (request_id, account_id, dialog_id, body_hash, state, created_at,
                    reviewed_at)
                   VALUES (?, 101, 777, 'hash', ?, ?, ?)""",
                [
                    ("sent-old", "sent", old, None),
                    ("rejected-old", "rejected", old, None),
                    ("reviewed-old", "unknown", old, "2025-11-02T00:00:00Z"),
                    ("unreviewed-old", "unknown", old, None),
                    ("sent-recent", "sent", recent, None),
                ],
            )

        self.assertEqual(
            self.service.prune_history(),
            {"processed_updates": 0, "account_outbox": 3},
        )
        with self.service._connection() as connection:
            remaining = sorted(
                row["request_id"]
                for row in connection.execute(
                    "SELECT request_id FROM user_account_outbox"
                )
            )
        self.assertEqual(remaining, ["sent-recent", "unreviewed-old"])


@unittest.skipUnless(
    CRYPTOGRAPHY_AVAILABLE, "cryptography is an optional account dependency"
)
class AccountHTTPTests(LocalHTTPMixin, unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.clock = MutableClock()
        self.gateway = FakeGateway()
        self.service = TeleflowService(
            self.root / "accounts.sqlite3",
            telegram=FakeTelegram(),
            password=TEST_PASSWORD,
            account_api_id=12345,
            account_api_hash=TEST_API_HASH,
            account_session_key=Fernet.generate_key().decode("ascii"),
            account_gateway=self.gateway,
            clock=self.clock,
        )
        self.addCleanup(self.service.close)
        self.start_http_server(self.service, self.root)

    def test_localhost_auth_cookie_signout_and_csrf_protection(self):
        status, response, _ = self.request("GET", "/api/accounts")
        self.assertEqual(status, 401)
        self.assertEqual(response["error"], "Authentication required")

        status, response, _ = self.request(
            "POST", "/api/accounts", {"session": "must-not-import"}, origin=None
        )
        self.assertEqual(status, 403)
        self.assertEqual(response["error"], "Cross-site request rejected")

        status, response, headers = self.login("wrong-password")
        self.assertEqual(status, 401)
        self.assertEqual(response["error"], "Invalid password")
        self.assertNotIn("set-cookie", headers)

        status, response, headers = self.login()
        self.assertEqual(status, 200)
        cookie = self.cookie_header(headers["set-cookie"])
        morsel = http.cookies.SimpleCookie(headers["set-cookie"])[SESSION_COOKIE]
        self.assertEqual(morsel["httponly"], True)
        self.assertEqual(morsel["samesite"], "Strict")
        self.assertEqual(morsel["max-age"], "43200")
        self.assertFalse(morsel["secure"])

        status, response, _ = self.request(
            "GET", "/api/accounts", headers={"Cookie": cookie}
        )
        self.assertEqual(status, 200)
        self.assertEqual(response, {"items": []})

        status, response, _ = self.request(
            "POST",
            "/api/accounts",
            {"session": "must-not-import"},
            headers={"Cookie": cookie},
            origin=f"http://attacker.invalid:{self.port}",
        )
        self.assertEqual(status, 403)
        self.assertEqual(response["error"], "Cross-site request rejected")
        self.assertEqual(self.gateway.inspect_calls, [])

        status, _, signout_headers = self.request(
            "POST", "/api/signout", {}, headers={"Cookie": cookie}
        )
        self.assertEqual(status, 200)
        self.assertIn("max-age=0", signout_headers["set-cookie"].lower())
        status, response, _ = self.request(
            "GET", "/api/accounts", headers={"Cookie": cookie}
        )
        self.assertEqual(status, 401)
        self.assertEqual(response["error"], "Authentication required")

    def test_session_string_is_absent_from_api_database_plaintext_and_logs(self):
        raw_session = "RAW-STRING-SESSION-secret-input-93a4d1"
        self.gateway.register_session(raw_session, 101, [1001])
        status, _, login_headers = self.login()
        self.assertEqual(status, 200)
        cookie = self.cookie_header(login_headers["set-cookie"])

        with self.assertLogs("teleflow", level="INFO") as captured:
            status, imported, _ = self.request(
                "POST",
                "/api/accounts",
                {"session": raw_session, "label": "Private test account"},
                headers={"Cookie": cookie},
            )

        self.assertEqual(status, 201)
        self.assertEqual(str(imported["item"]["id"]), "101")
        self.assertNotIn("session", imported["item"])
        updated_session = self.gateway.updated_sessions[raw_session]
        self.assertNotIn(raw_session, json.dumps(imported))
        self.assertNotIn(updated_session, json.dumps(imported))
        self.assertNotIn(raw_session, "\n".join(captured.output))
        self.assertNotIn(updated_session, "\n".join(captured.output))

        self.assertEqual(self.service.accounts._session(101), updated_session)
        with self.service._connection() as connection:
            stored = connection.execute(
                "SELECT session_ciphertext FROM user_accounts WHERE id=101"
            ).fetchone()["session_ciphertext"]
        self.assertNotIn(raw_session.encode("ascii"), stored)
        self.assertNotIn(updated_session.encode("ascii"), stored)
        database_files = [self.service.db_path]
        database_files.extend(
            self.service.db_path.parent.glob(self.service.db_path.name + "-*")
        )
        for database_file in database_files:
            if database_file.exists():
                contents = database_file.read_bytes()
                self.assertNotIn(raw_session.encode("ascii"), contents)
                self.assertNotIn(updated_session.encode("ascii"), contents)

        status, listed, _ = self.request(
            "GET", "/api/accounts", headers={"Cookie": cookie}
        )
        self.assertEqual(status, 200)
        self.assertNotIn(raw_session, json.dumps(listed))
        self.assertNotIn(updated_session, json.dumps(listed))

    def test_large_account_id_is_returned_as_an_exact_string(self):
        account_id = 2**53 + 1
        raw_session = "session-for-large-account-id"
        self.gateway.register_session(raw_session, account_id)
        status, _, login_headers = self.login()
        self.assertEqual(status, 200)
        cookie = self.cookie_header(login_headers["set-cookie"])

        status, imported, _ = self.request(
            "POST",
            "/api/accounts",
            {"session": raw_session},
            headers={"Cookie": cookie},
        )

        self.assertEqual(status, 201)
        self.assertIsInstance(imported["item"]["id"], str)
        self.assertEqual(imported["item"]["id"], str(account_id))

    def test_review_endpoint_requires_auth_and_same_origin(self):
        raw_session = "http-review-session"
        self.gateway.register_session(raw_session, 101, [777])
        self.gateway.send_errors.append(AccountError(504, "Synthetic timeout"))
        status, _, login_headers = self.login()
        self.assertEqual(status, 200)
        cookie = self.cookie_header(login_headers["set-cookie"])
        status, _, _ = self.request(
            "POST",
            "/api/accounts",
            {"session": raw_session},
            headers={"Cookie": cookie},
        )
        self.assertEqual(status, 201)

        request_id = str(uuid.uuid4())
        with self.assertRaises(AccountError) as timed_out:
            self.service.accounts.send_reply(101, 777, "possibly delivered", request_id)
        self.assertEqual(timed_out.exception.status, 504)

        review_path = "/api/accounts/101/dialogs/777/review"
        payload = {
            "request_id": request_id,
            "confirm": "checked_in_telegram",
        }
        status, response, _ = self.request("POST", review_path, payload)
        self.assertEqual(status, 401)
        self.assertEqual(response["error"], "Authentication required")

        status, response, _ = self.request(
            "POST", review_path, payload, headers={"Cookie": cookie}, origin=None
        )
        self.assertEqual(status, 403)
        self.assertEqual(response["error"], "Cross-site request rejected")

        status, response, _ = self.request(
            "POST",
            review_path,
            payload,
            headers={"Cookie": cookie},
            origin=f"http://attacker.invalid:{self.port}",
        )
        self.assertEqual(status, 403)
        self.assertEqual(response["error"], "Cross-site request rejected")

        status, conversation, _ = self.request(
            "GET", "/api/accounts/101/dialogs/777", headers={"Cookie": cookie}
        )
        self.assertEqual(status, 200)
        self.assertFalse(conversation["can_send"])
        self.assertEqual(
            [item["request_id"] for item in conversation["unresolved"]], [request_id]
        )
        self.assertEqual(conversation["unresolved"][0]["state"], "unknown")

        status, response, _ = self.request(
            "POST", review_path, payload, headers={"Cookie": cookie}
        )
        self.assertEqual(status, 200)
        self.assertEqual(response, {"ok": True})
        status, conversation, _ = self.request(
            "GET", "/api/accounts/101/dialogs/777", headers={"Cookie": cookie}
        )
        self.assertEqual(status, 200)
        self.assertTrue(conversation["can_send"])
        self.assertEqual(conversation["unresolved"], [])

    def test_http_reply_status_is_private_and_retrying_same_id_never_resends(self):
        raw_session = "http-sent-session"
        self.gateway.register_session(raw_session, 101, [777])
        status, _, login_headers = self.login()
        self.assertEqual(status, 200)
        cookie = self.cookie_header(login_headers["set-cookie"])
        status, _, _ = self.request(
            "POST",
            "/api/accounts",
            {"session": raw_session},
            headers={"Cookie": cookie},
        )
        self.assertEqual(status, 201)

        request_id = str(uuid.uuid4())
        reply_path = "/api/accounts/101/dialogs/777/reply"
        status_path = f"/api/accounts/101/dialogs/777/replies/{request_id}"
        status, _, _ = self.request(
            "POST",
            reply_path,
            {"body": "Delivered once", "request_id": request_id},
            headers={"Cookie": cookie},
        )
        self.assertEqual(status, 200)

        status, response, _ = self.request("GET", status_path)
        self.assertEqual(status, 401)
        self.assertEqual(response["error"], "Authentication required")
        status, response, _ = self.request(
            "GET", status_path, headers={"Cookie": cookie}
        )
        self.assertEqual(status, 200)
        self.assertEqual(response, {"state": "sent", "reviewed": False})
        status, response, _ = self.request(
            "GET",
            f"/api/accounts/101/dialogs/778/replies/{request_id}",
            headers={"Cookie": cookie},
        )
        self.assertEqual(status, 404)
        self.assertEqual(response["error"], "Reply attempt not found")
        status, response, _ = self.request(
            "POST",
            reply_path,
            {"body": "Delivered once", "request_id": request_id},
            headers={"Cookie": cookie},
        )
        self.assertEqual(status, 200)
        self.assertEqual(response["message"], {"id": 901, "already_sent": True})
        self.assertEqual(len(self.gateway.send_calls), 1)

    def test_account_check_and_rename_require_login_and_same_origin(self):
        self.gateway.register_session("http-health-session", 101)
        status, _, login_headers = self.login()
        self.assertEqual(status, 200)
        cookie = self.cookie_header(login_headers["set-cookie"])
        status, _, _ = self.request(
            "POST",
            "/api/accounts",
            {"session": "http-health-session"},
            headers={"Cookie": cookie},
        )
        self.assertEqual(status, 201)

        for method, path, payload in (
            ("POST", "/api/accounts/101/check", {}),
            ("PATCH", "/api/accounts/101", {"label": "Новый"}),
        ):
            with self.subTest(path=path):
                status, _, _ = self.request(method, path, payload)
                self.assertEqual(status, 401)
                status, _, _ = self.request(
                    method,
                    path,
                    payload,
                    headers={"Cookie": cookie},
                    origin=f"http://attacker.invalid:{self.port}",
                )
                self.assertEqual(status, 403)
        self.assertEqual(self.gateway.check_calls, [])

        status, checked, _ = self.request(
            "POST", "/api/accounts/101/check", {}, headers={"Cookie": cookie}
        )
        self.assertEqual(status, 200)
        self.assertEqual(checked["item"]["health"], "ok")
        self.assertEqual(self.gateway.check_calls, [101])
        self.assertNotIn("session", json.dumps(checked))
        status, renamed, _ = self.request(
            "PATCH",
            "/api/accounts/101",
            {"label": "Новый"},
            headers={"Cookie": cookie},
        )
        self.assertEqual((status, renamed["item"]["display_name"]), (200, "Новый"))
        status, response, _ = self.request(
            "PATCH",
            "/api/accounts/101",
            {"label": "Новый", "session": "must-not-be-accepted"},
            headers={"Cookie": cookie},
        )
        self.assertEqual(status, 400)
        self.assertEqual(response["error"], "PATCH account accepts only label")

    def test_flood_wait_returns_retry_after_header_and_enforces_cooldown(self):
        self.gateway.register_session("http-flood-session", 101)
        status, _, login_headers = self.login()
        self.assertEqual(status, 200)
        cookie = self.cookie_header(login_headers["set-cookie"])
        status, _, _ = self.request(
            "POST",
            "/api/accounts",
            {"session": "http-flood-session"},
            headers={"Cookie": cookie},
        )
        self.assertEqual(status, 201)
        path = "/api/accounts/101/dialogs/777/reply"
        self.gateway.send_errors.append(AccountError(429, "Telegram pause", 19))

        status, response, headers = self.request(
            "POST",
            path,
            {"body": "reply", "request_id": str(uuid.uuid4())},
            headers={"Cookie": cookie},
        )
        self.assertEqual(status, 429)
        self.assertEqual(response["error"], "Telegram pause")
        self.assertEqual(headers["retry-after"], "19")

        status, _, retry_headers = self.request(
            "POST",
            path,
            {"body": "another reply", "request_id": str(uuid.uuid4())},
            headers={"Cookie": cookie},
        )
        self.assertEqual(status, 429)
        self.assertEqual(retry_headers["retry-after"], "19")
        self.clock.advance(19)
        status, response, _ = self.request(
            "POST",
            path,
            {"body": "after pause", "request_id": str(uuid.uuid4())},
            headers={"Cookie": cookie},
        )
        self.assertEqual(status, 200)
        self.assertFalse(response["message"]["already_sent"])


class DemoModeAccountTests(LocalHTTPMixin, unittest.TestCase):
    def test_user_account_configuration_is_rejected_in_demo_mode(self):
        with tempfile.TemporaryDirectory() as directory:
            self.assertRaisesRegex(
                ValueError,
                "non-demo mode",
                TeleflowService,
                Path(directory) / "demo.sqlite3",
                telegram=FakeTelegram(),
                password=TEST_PASSWORD,
                demo=True,
                account_api_id=12345,
                account_api_hash=TEST_API_HASH,
                account_session_key="test-only-unused-key",
                account_gateway=FakeGateway(),
            )

    def test_demo_account_api_remains_disabled_after_login(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        root = Path(temp.name)
        service = TeleflowService(
            root / "demo.sqlite3",
            telegram=FakeTelegram(),
            password=TEST_PASSWORD,
            demo=True,
        )
        self.addCleanup(service.close)
        self.start_http_server(service, root)
        status, _, login_headers = self.login()
        self.assertEqual(status, 200)
        cookie = self.cookie_header(login_headers["set-cookie"])

        status, response, _ = self.request(
            "GET", "/api/accounts", headers={"Cookie": cookie}
        )

        self.assertEqual(status, 403)
        self.assertEqual(response["error"], "User-account integration is disabled")
        self.assertIsNone(service.accounts)


@unittest.skipUnless(
    CRYPTOGRAPHY_AVAILABLE and os.name == "posix",
    "cryptography and POSIX file permissions are required",
)
class AccountStoragePermissionTests(unittest.TestCase):
    @staticmethod
    def make_service(db_path):
        return TeleflowService(
            db_path,
            telegram=FakeTelegram(),
            password=TEST_PASSWORD,
            account_api_id=12345,
            account_api_hash=TEST_API_HASH,
            account_session_key=Fernet.generate_key().decode("ascii"),
            account_gateway=FakeGateway(),
        )

    def test_account_database_parent_rejects_group_or_other_write_access(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            for permissions in (0o720, 0o702):
                with self.subTest(permissions=oct(permissions)):
                    unsafe_parent = root / oct(permissions)
                    unsafe_parent.mkdir()
                    unsafe_parent.chmod(permissions)
                    with self.assertRaisesRegex(
                        ValueError,
                        "directory without group/other write access",
                    ):
                        self.make_service(unsafe_parent / "accounts.sqlite3")

    def test_account_database_must_be_a_private_regular_file(self):
        with tempfile.TemporaryDirectory() as directory:
            db_path = Path(directory) / "accounts.sqlite3"
            db_path.touch()
            db_path.chmod(0o640)

            with self.assertRaisesRegex(ValueError, "private SQLite database"):
                self.make_service(db_path)


class FakeFloodWaitError(Exception):
    def __init__(self, seconds):
        super().__init__("synthetic flood wait")
        self.seconds = seconds


class FakeRPCError(Exception):
    pass


class FakeStringSession:
    def __init__(self, serialized):
        if serialized == "invalid":
            raise ValueError("invalid fake session")
        self.serialized = serialized
        self.save_entities = True

    @staticmethod
    def save(session):
        return session.serialized


class FakeTelethonRuntime:
    account_ids: ClassVar[dict[str, int]] = {}
    unauthorized_sessions: ClassVar[set[str]] = set()
    restrictions: ClassVar[dict[str, list[Any]]] = {}
    dialogs: ClassVar[dict[str, list[Any]]] = {}
    messages: ClassVar[dict[str, list[Any]]] = {}
    fail_dialogs: ClassVar[dict[str, Exception]] = {}
    blocked_connects: ClassVar[set[str]] = set()
    clients: ClassVar[list[Any]] = []
    connect_started: ClassVar[threading.Event] = threading.Event()

    @classmethod
    def reset(cls):
        cls.account_ids = {}
        cls.unauthorized_sessions = set()
        cls.restrictions = {}
        cls.dialogs = {}
        cls.messages = {}
        cls.fail_dialogs = {}
        cls.blocked_connects = set()
        cls.clients = []
        cls.connect_started = threading.Event()


class FakeTelethonClient:
    def __init__(self, session, api_id, api_hash, **options):
        self.session = session
        self.api_id = api_id
        self.api_hash = api_hash
        self.options = options
        self.account_id = FakeTelethonRuntime.account_ids.get(session.serialized, 0)
        self.authorized = (
            session.serialized not in FakeTelethonRuntime.unauthorized_sessions
        )
        self.dialog_items = FakeTelethonRuntime.dialogs.get(session.serialized, [])
        self.message_items = FakeTelethonRuntime.messages.get(session.serialized, [])
        self.connected = False
        self.disconnected = False
        self.disconnect_complete = threading.Event()
        self.dialog_limits = []
        self.message_limits = []
        self.sent_messages = []
        self.block_connect = session.serialized in FakeTelethonRuntime.blocked_connects
        FakeTelethonRuntime.clients.append(self)

    async def connect(self):
        self.connected = True
        if self.block_connect:
            FakeTelethonRuntime.connect_started.set()
            await asyncio.Event().wait()

    async def disconnect(self):
        self.connected = False
        self.disconnected = True
        self.disconnect_complete.set()

    def is_connected(self):
        return self.connected

    async def is_user_authorized(self):
        return self.authorized

    async def get_me(self):
        reasons = FakeTelethonRuntime.restrictions.get(self.session.serialized, [])
        return SimpleNamespace(
            id=self.account_id,
            bot=False,
            first_name="Ada",
            last_name="Lovelace",
            username=f"user_{self.account_id}",
            restricted=bool(reasons),
            restriction_reason=reasons,
        )

    async def get_dialogs(self, *, limit):
        self.dialog_limits.append(limit)
        error = FakeTelethonRuntime.fail_dialogs.get(self.session.serialized)
        if error is not None:
            raise error
        return self.dialog_items[:limit]

    async def get_messages(self, _entity, *, limit):
        self.message_limits.append(limit)
        return self.message_items[:limit]

    async def send_message(self, entity, body, **options):
        self.sent_messages.append((entity, body, options))
        return SimpleNamespace(id=707)

    async def log_out(self):
        return True


def user_dialog(dialog_id, name=None, *, bot=False, deleted=False):
    entity = SimpleNamespace(id=dialog_id, bot=bot, deleted=deleted)
    return SimpleNamespace(
        id=dialog_id,
        name=name or f"User {dialog_id}",
        entity=entity,
        is_user=True,
        is_channel=False,
        is_group=False,
        input_entity=f"input:{dialog_id}",
    )


def channel_dialog(dialog_id, *, broadcast=True, creator=False, can_post=False):
    entity = SimpleNamespace(
        id=dialog_id,
        broadcast=broadcast,
        creator=creator,
        admin_rights=SimpleNamespace(post_messages=can_post),
    )
    return SimpleNamespace(
        id=dialog_id,
        name=f"Channel {dialog_id}",
        entity=entity,
        is_user=False,
        is_channel=True,
        is_group=False,
        input_entity=f"input:{dialog_id}",
    )


def group_dialog(dialog_id, *, creator):
    entity = SimpleNamespace(id=dialog_id, creator=creator)
    return SimpleNamespace(
        id=dialog_id,
        name=f"Group {dialog_id}",
        entity=entity,
        is_user=False,
        is_channel=False,
        is_group=True,
        input_entity=f"input:{dialog_id}",
    )


@unittest.skipUnless(TELETHON_AVAILABLE, "Telethon account transport is optional")
class TelethonGatewayTests(unittest.TestCase):
    def setUp(self):
        FakeTelethonRuntime.reset()
        telethon = importlib.import_module("telethon")
        sessions = importlib.import_module("telethon.sessions")
        errors = importlib.import_module("telethon.errors")
        for module, name, replacement in (
            (telethon, "TelegramClient", FakeTelethonClient),
            (sessions, "StringSession", FakeStringSession),
            (errors, "FloodWaitError", FakeFloodWaitError),
            (errors, "RPCError", FakeRPCError),
        ):
            patcher = patch.object(module, name, replacement)
            patcher.start()
            self.addCleanup(patcher.stop)
        self.gateway = TelethonGateway(12345, TEST_API_HASH)
        self.addCleanup(self.gateway.close)

    def test_inspect_returns_telegram_identity_and_disables_entity_caching(self):
        FakeTelethonRuntime.account_ids["source-session"] = 101

        profile, saved_session = self.gateway.inspect("source-session")

        self.assertEqual(
            profile,
            {
                "id": 101,
                "display_name": "Ada Lovelace",
                "username": "user_101",
                "restricted": False,
                "restriction": None,
            },
        )
        self.assertEqual(saved_session, "source-session")
        client = FakeTelethonRuntime.clients[-1]
        self.assertFalse(client.session.save_entities)
        self.assertTrue(client.disconnected)
        self.assertEqual(client.options["receive_updates"], False)
        self.assertEqual(client.options["request_retries"], 0)

    def test_unauthorized_session_is_reported_as_conflict(self):
        session = "unauthorized-session"
        FakeTelethonRuntime.account_ids[session] = 808
        FakeTelethonRuntime.unauthorized_sessions.add(session)

        with self.assertRaises(AccountError) as raised:
            self.gateway.inspect(session)

        self.assertEqual(raised.exception.status, 409)
        self.assertTrue(FakeTelethonRuntime.clients[-1].disconnected)

    def test_session_identity_and_dialog_lookups_cannot_cross_accounts(self):
        FakeTelethonRuntime.account_ids.update({"session-a": 101, "session-b": 202})
        dialog_a = user_dialog(1001)
        dialog_b = user_dialog(2002)
        FakeTelethonRuntime.dialogs.update(
            {"session-a": [dialog_a], "session-b": [dialog_b]}
        )

        with self.assertRaises(AccountError) as wrong_identity:
            self.gateway.dialogs(202, "session-a")
        self.assertEqual(wrong_identity.exception.status, 403)
        self.assertTrue(FakeTelethonRuntime.clients[-1].disconnected)
        self.assertNotIn(202, self.gateway._clients)

        result, _ = self.gateway.conversation(101, "session-a", 1001)
        self.assertEqual(str(result["dialog"]["id"]), "1001")
        with self.assertRaises(AccountError) as wrong_dialog:
            self.gateway.conversation(101, "session-a", 2002)
        self.assertEqual(wrong_dialog.exception.status, 404)

    def test_dialogs_are_filtered_and_limited_to_the_first_hundred(self):
        FakeTelethonRuntime.account_ids["dialogs-session"] = 303
        long_name = "N" * 200
        large_dialog_id = 2**53 + 1
        dialogs = [
            user_dialog(large_dialog_id, long_name),
            user_dialog(2, bot=True),
            user_dialog(3, deleted=True),
            channel_dialog(4, creator=False, can_post=False),
            channel_dialog(5, creator=True),
            channel_dialog(6, broadcast=False, creator=True),
            group_dialog(7, creator=True),
            group_dialog(8, creator=False),
        ]
        dialogs.extend(user_dialog(dialog_id) for dialog_id in range(9, 101))
        dialogs.append(user_dialog(101, "Outside first 100"))
        FakeTelethonRuntime.dialogs["dialogs-session"] = dialogs

        result, _ = self.gateway.dialogs(303, "dialogs-session")

        client = FakeTelethonRuntime.clients[-1]
        self.assertEqual(client.dialog_limits, [101])
        self.assertTrue(result["truncated"])
        item_ids = [str(item["id"]) for item in result["items"]]
        self.assertIn(str(large_dialog_id), item_ids)
        self.assertIn("5", item_ids)
        self.assertIn("7", item_ids)
        self.assertNotIn("2", item_ids)
        self.assertNotIn("3", item_ids)
        self.assertNotIn("4", item_ids)
        self.assertNotIn("6", item_ids)
        self.assertNotIn("8", item_ids)
        self.assertNotIn("101", item_ids)
        self.assertEqual(result["items"][0]["name"], long_name[:160])

    def test_conversation_uses_last_hundred_messages_and_only_displays_forty(self):
        FakeTelethonRuntime.account_ids["messages-session"] = 404
        dialog = user_dialog(44)
        FakeTelethonRuntime.dialogs["messages-session"] = [dialog]
        messages = [
            SimpleNamespace(
                id=message_id,
                out=False,
                sender_id=44 if message_id == 50 else 999,
                raw_text="x" * 5000 if message_id == 100 else f"message {message_id}",
                date=dt.datetime(2026, 1, 2, tzinfo=dt.timezone.utc),
            )
            for message_id in range(100, 0, -1)
        ]
        FakeTelethonRuntime.messages["messages-session"] = messages

        result, _ = self.gateway.conversation(404, "messages-session", 44)

        client = FakeTelethonRuntime.clients[-1]
        self.assertEqual(client.dialog_limits, [100])
        self.assertEqual(client.message_limits, [100])
        self.assertTrue(result["can_send"])
        self.assertEqual(len(result["items"]), 40)
        self.assertEqual([item["id"] for item in result["items"]], list(range(61, 101)))
        self.assertEqual(len(result["items"][-1]["body"]), 4096)

    def test_media_only_inbound_message_allows_manual_reply(self):
        session = "media-only-session"
        account_id = 909
        dialog_id = 99
        FakeTelethonRuntime.account_ids[session] = account_id
        FakeTelethonRuntime.dialogs[session] = [user_dialog(dialog_id)]
        FakeTelethonRuntime.messages[session] = [
            SimpleNamespace(
                id=505,
                out=False,
                sender_id=dialog_id,
                raw_text="",
                media=object(),
                date=dt.datetime(2026, 1, 2, tzinfo=dt.timezone.utc),
            )
        ]

        conversation, _ = self.gateway.conversation(account_id, session, dialog_id)
        result, _ = self.gateway.send(
            account_id, session, dialog_id, "Thanks for the photo"
        )

        self.assertTrue(conversation["can_send"])
        self.assertEqual(conversation["items"][0]["body"], "[Медиа]")
        self.assertEqual(result, {"id": 707})
        client = self.gateway._clients[account_id]
        self.assertEqual(
            client.sent_messages[0][0:2],
            (f"input:{dialog_id}", "Thanks for the photo"),
        )

    def test_flood_wait_is_translated_to_retryable_account_error(self):
        FakeTelethonRuntime.account_ids["flood-session"] = 505
        FakeTelethonRuntime.fail_dialogs["flood-session"] = FakeFloodWaitError(23)

        with self.assertRaises(AccountError) as raised:
            self.gateway.dialogs(505, "flood-session")

        self.assertEqual(raised.exception.status, 429)
        self.assertEqual(raised.exception.retry_after, 23)

    def test_submit_timeout_cancels_the_inflight_coroutine(self):
        FakeTelethonRuntime.account_ids["blocked-session"] = 606
        FakeTelethonRuntime.blocked_connects.add("blocked-session")
        real_submit = asyncio.run_coroutine_threadsafe
        original_result = concurrent.futures.Future.result
        futures = []

        def track_submit(coroutine, loop):
            future = real_submit(coroutine, loop)
            futures.append(future)
            return future

        def time_out_after_connect(future, timeout=None):
            if timeout == 30:
                if not FakeTelethonRuntime.connect_started.wait(2):
                    raise AssertionError("fake Telethon connect did not start")
                raise concurrent.futures.TimeoutError()
            return original_result(future, timeout)

        submit_patch = patch.object(
            account_transport.asyncio,
            "run_coroutine_threadsafe",
            side_effect=track_submit,
        )
        result_patch = patch.object(
            concurrent.futures.Future, "result", new=time_out_after_connect
        )
        with submit_patch, result_patch, self.assertRaises(AccountError) as raised:
            self.gateway.inspect("blocked-session")

        self.assertEqual(raised.exception.status, 504)
        self.assertTrue(futures[0].cancelled())
        client = FakeTelethonRuntime.clients[-1]
        self.assertTrue(client.disconnect_complete.wait(2))
        self.assertTrue(client.disconnected)

    def test_close_stops_the_private_event_loop_and_disconnects_cached_clients(self):
        FakeTelethonRuntime.account_ids["close-session"] = 707
        self.gateway.dialogs(707, "close-session")
        client = self.gateway._clients[707]
        self.assertTrue(self.gateway._thread.is_alive())

        self.gateway.close()

        self.assertFalse(self.gateway._thread.is_alive())
        self.assertTrue(client.disconnected)
        self.assertEqual(self.gateway._clients, {})

    def test_check_reports_restriction_details_for_the_owned_session(self):
        FakeTelethonRuntime.account_ids["restricted-session"] = 808
        FakeTelethonRuntime.restrictions["restricted-session"] = [
            SimpleNamespace(
                platform="all", reason="spam", text="Limited after spam reports"
            )
        ]

        profile, saved = self.gateway.check(808, "restricted-session")

        self.assertTrue(profile["restricted"])
        self.assertEqual(profile["restriction"], "Limited after spam reports")
        self.assertEqual(saved, "restricted-session")
        FakeTelethonRuntime.account_ids["revoked-session"] = 809
        FakeTelethonRuntime.unauthorized_sessions.add("revoked-session")
        with self.assertRaises(AccountError) as revoked:
            self.gateway.check(809, "revoked-session")
        self.assertEqual(revoked.exception.status, 409)


if __name__ == "__main__":
    unittest.main()
