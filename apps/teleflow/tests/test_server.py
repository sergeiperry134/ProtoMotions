# SPDX-License-Identifier: Apache-2.0
import contextlib
import csv
import datetime as dt
import http.client
import io
import json
import os
import sqlite3
import sys
import tempfile
import threading
import unittest
import urllib.error
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from server import (
    APIError,
    BackgroundWorker,
    DatabaseInUseError,
    TelegramError,
    TeleflowRequestHandler,
    TeleflowService,
    TeleflowHTTPServer,
    csv_cell,
    is_public_demo_mode,
    main,
    placeholder_worst_case_length,
    render_placeholders,
    resolve_database_location,
)


class FakeTelegram:
    def __init__(self):
        self.updates = []
        self.calls = []
        self.sent = []
        self.admin_status = "administrator"
        self.fail_sends = False
        self.send_failures = []
        self.fail_poll = False
        self.next_message_id = 100
        self.lock = threading.Lock()
        self.sent_event = threading.Event()

    def call(self, method, params=None):
        params = params or {}
        with self.lock:
            self.calls.append((method, dict(params)))
            if method == "getMe":
                return {"id": 777, "username": "teleflow_test_bot"}
            if method == "getUpdates":
                if self.fail_poll:
                    raise TelegramError("poll temporarily unavailable", transient=True)
                offset = params.get("offset", 0)
                updates = [
                    update for update in self.updates if update["update_id"] >= offset
                ]
                self.updates = []
                return updates
            if method == "getChat":
                return {
                    "id": -100123456,
                    "title": "Test channel",
                    "username": "test_channel",
                    "type": "channel",
                }
            if method == "getChatMember":
                member = {
                    "status": self.admin_status,
                    "can_post_messages": self.admin_status == "administrator",
                }
                return member
            if method == "sendMessage":
                if self.send_failures:
                    raise self.send_failures.pop(0)
                if self.fail_sends:
                    raise TelegramError("message blocked")
                self.next_message_id += 1
                message = {
                    "message_id": self.next_message_id,
                    "chat": {"id": params["chat_id"]},
                    "text": params["text"],
                }
                self.sent.append(message)
                self.sent_event.set()
                return message
        raise AssertionError(f"Unexpected Telegram method {method}")


class FakeAI:
    def draft(self, prompt, tone, kind, context):
        return f"{tone}: {prompt}"


class MutableClock:
    def __init__(self):
        self.value = dt.datetime(2026, 1, 2, 12, 0, tzinfo=dt.timezone.utc)

    def __call__(self):
        return self.value

    def advance(self, seconds):
        self.value += dt.timedelta(seconds=seconds)


def private_update(update_id, text, user_id=42, **from_fields):
    sender = {"id": user_id, "is_bot": False, "first_name": "Ada", **from_fields}
    return {
        "update_id": update_id,
        "message": {
            "message_id": update_id,
            "date": 1767355200,
            "chat": {"id": user_id, "type": "private"},
            "from": sender,
            "text": text,
        },
    }


def http_call(host, port, method, path, payload=None, headers=None, same_origin=True):
    connection = http.client.HTTPConnection(host, port, timeout=3)
    body = None if payload is None else json.dumps(payload)
    request_headers = dict(headers or {})
    if method in {"POST", "PUT", "PATCH", "DELETE"} and same_origin:
        request_headers.setdefault("Origin", f"http://{host}:{port}")
    if body is not None:
        request_headers["Content-Type"] = "application/json"
        request_headers["Content-Length"] = str(len(body.encode("utf-8")))
    connection.request(method, path, body=body, headers=request_headers)
    response = connection.getresponse()
    raw = response.read()
    parsed = (
        json.loads(raw.decode("utf-8"))
        if raw and response.getheader("Content-Type", "").startswith("application/json")
        else raw
    )
    result = (
        response.status,
        parsed,
        {key.lower(): value for key, value in response.getheaders()},
    )
    connection.close()
    return result


class ServerCase(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.bot = FakeTelegram()
        self.service = TeleflowService(
            self.root / "db.sqlite3",
            telegram=self.bot,
            send_interval=0,
            clock=lambda: dt.datetime(2026, 1, 2, 12, 0, tzinfo=dt.timezone.utc),
        )
        self.addCleanup(self.service.close)
        self.static = self.root / "static"
        self.static.mkdir()
        self.handler = lambda *args, **kwargs: TeleflowRequestHandler(
            *args, service=self.service, static_root=self.static, **kwargs
        )
        self.server = TeleflowHTTPServer(("127.0.0.1", 0), self.handler)
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()
        self.addCleanup(self.close_server)
        self.host, self.port = self.server.server_address

    def close_server(self):
        self.server.shutdown()
        self.server.server_close()
        self.thread.join(timeout=2)

    def serve(self, service):
        def handler(*args, **kwargs):
            return TeleflowRequestHandler(
                *args, service=service, static_root=self.static, **kwargs
            )

        server = TeleflowHTTPServer(("127.0.0.1", 0), handler)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()

        def cleanup():
            server.shutdown()
            server.server_close()
            thread.join(timeout=2)

        self.addCleanup(cleanup)
        return server.server_address

    def request(self, method, path, payload=None, headers=None):
        connection = http.client.HTTPConnection(self.host, self.port, timeout=3)
        body = None if payload is None else json.dumps(payload)
        request_headers = dict(headers or {})
        if method in {"POST", "PUT", "PATCH", "DELETE"}:
            request_headers.setdefault("Origin", f"http://{self.host}:{self.port}")
        if payload is not None:
            request_headers.setdefault("Content-Type", "application/json")
            request_headers.setdefault("Content-Length", str(len(body.encode("utf-8"))))
        connection.request(method, path, body=body, headers=request_headers)
        response = connection.getresponse()
        raw = response.read()
        parsed = (
            json.loads(raw.decode("utf-8"))
            if raw
            and response.getheader("Content-Type", "").startswith("application/json")
            else raw
        )
        result = response.status, parsed, dict(response.getheaders())
        connection.close()
        return result

    def push_update(self, update_id, text, user_id=42, **from_fields):
        self.bot.updates.append(private_update(update_id, text, user_id, **from_fields))


class HTTPContractTests(ServerCase):
    def test_health_status_and_empty_database_analytics(self):
        status, health, _ = self.request("GET", "/api/health")
        self.assertEqual(status, 200)
        self.assertEqual(health, {"ok": True})
        status, data, _ = self.request("GET", "/api/status")
        self.assertEqual(status, 200)
        self.assertEqual(
            data,
            {
                "telegram": {
                    "connected": True,
                    "username": "teleflow_test_bot",
                    "error": None,
                },
                "ai": {"configured": False},
                "demo": False,
                "public_demo": False,
                "accounts": {"enabled": False},
                "auth_required": False,
            },
        )
        status, analytics, _ = self.request("GET", "/api/analytics")
        self.assertEqual(status, 200)
        self.assertEqual(
            analytics["totals"],
            {"sent": 0, "failed": 0, "subscribers": 0, "campaigns": 0},
        )
        self.assertEqual(len(analytics["daily"]), 30)
        self.assertEqual(sum(item["sent"] for item in analytics["daily"]), 0)

    def test_host_header_rebinding_and_forged_origin_are_rejected(self):
        attacker_origin = f"http://attacker.example:{self.port}"
        forged_headers = {
            "Host": f"attacker.example:{self.port}",
            "Origin": attacker_origin,
        }
        status, data, _ = self.request("GET", "/api/status", headers=forged_headers)
        self.assertEqual(status, 403)
        self.assertEqual(data["error"], "Untrusted Host header")

        status, data, _ = self.request(
            "POST",
            "/api/rules",
            {"keyword": "price", "reply": "Details"},
            forged_headers,
        )
        self.assertEqual(status, 403)
        self.assertEqual(self.service.list_rules(), [])

    def test_configured_public_origin_is_the_only_accepted_host_and_origin(self):
        self.service.public_origin = "https://teleflow.example"
        trusted_headers = {
            "Host": "teleflow.example",
            "Origin": "https://teleflow.example",
        }
        status, result, _ = self.request(
            "POST",
            "/api/campaigns",
            {"title": "Trusted", "body": "Draft", "target_type": "subscribers"},
            trusted_headers,
        )
        self.assertEqual(status, 201)
        self.assertEqual(result["title"], "Trusted")

        forged_headers = {
            "Host": "attacker.example",
            "Origin": "https://attacker.example",
        }
        status, data, _ = self.request(
            "POST",
            "/api/campaigns",
            {"title": "Forged", "body": "No", "target_type": "subscribers"},
            forged_headers,
        )
        self.assertEqual(status, 403)
        self.assertEqual(data["error"], "Untrusted Host header")

        status, data, _ = self.request(
            "POST",
            "/api/campaigns",
            {"title": "Cross-site", "body": "No", "target_type": "subscribers"},
            {
                **trusted_headers,
                "Sec-Fetch-Site": "cross-site",
            },
        )
        self.assertEqual(status, 403)
        self.assertEqual(data["error"], "Cross-site request rejected")

    def test_mutating_api_requires_a_same_origin_header(self):
        status, data, _ = self.request(
            "POST",
            "/api/rules",
            {"keyword": "price", "reply": "Details"},
            {"Origin": ""},
        )
        self.assertEqual(status, 403)
        self.assertEqual(data["error"], "Cross-site request rejected")

    def test_login_lockout_blocks_brute_force_and_recovers(self):
        clock = MutableClock()
        auth_service = TeleflowService(
            self.root / "auth.sqlite3",
            telegram=FakeTelegram(),
            password="correct-password",
            clock=clock,
        )
        self.addCleanup(auth_service.close)
        host, port = self.serve(auth_service)

        def auth_request(password):
            return http_call(host, port, "POST", "/api/login", {"password": password})

        for _ in range(5):
            status, data, headers = auth_request("wrong-password")
            self.assertEqual(status, 401)
            self.assertEqual(data["error"], "Invalid password")
            self.assertNotIn("set-cookie", headers)

        status, data, headers = auth_request("correct-password")
        self.assertEqual(status, 429)
        self.assertIn("Too many failed login attempts", data["error"])
        self.assertEqual(headers.get("retry-after"), "900")
        self.assertNotIn("set-cookie", headers)

        clock.advance(901)
        status, data, headers = auth_request("correct-password")
        self.assertEqual(status, 200)
        self.assertIn("set-cookie", headers)

        for _ in range(5):
            auth_service.record_login_failure("198.51.100.7")
        self.assertIsNone(auth_service.login_retry_after("203.0.113.9"))
        self.assertEqual(auth_service.login_retry_after("198.51.100.7"), 900)
        auth_service.record_login_success("198.51.100.7")
        self.assertIsNone(auth_service.login_retry_after("198.51.100.7"))

    def test_new_data_routes_require_login_and_same_origin(self):
        protected = TeleflowService(
            self.root / "protected.sqlite3",
            telegram=FakeTelegram(),
            password="correct-password",
        )
        self.addCleanup(protected.close)
        host, port = self.serve(protected)
        pause = {"enabled": False, "steps": []}

        for method, path, payload in (
            ("GET", "/api/sequence", None),
            ("PUT", "/api/sequence", pause),
            ("GET", "/api/subscribers/export", None),
            ("DELETE", "/api/subscribers/42", None),
            ("GET", "/api/campaigns/1/deliveries", None),
        ):
            with self.subTest(method=method, path=path):
                status, response, _ = http_call(host, port, method, path, payload)
                self.assertEqual(
                    (status, response["error"]), (401, "Authentication required")
                )
        _, _, login = http_call(
            host, port, "POST", "/api/login", {"password": "correct-password"}
        )
        cookie = login["set-cookie"].split(";", 1)[0]
        status, response, _ = http_call(
            host,
            port,
            "PUT",
            "/api/sequence",
            pause,
            headers={"Cookie": cookie, "Origin": "http://attacker.invalid"},
            same_origin=False,
        )
        self.assertEqual(
            (status, response["error"]), (403, "Cross-site request rejected")
        )
        status, _, _ = http_call(
            host, port, "GET", "/api/sequence", headers={"Cookie": cookie}
        )
        self.assertEqual(status, 200)

    def test_cancel_scheduled_campaign_returns_it_to_draft(self):
        status, created, _ = self.request(
            "POST",
            "/api/campaigns",
            {"title": "Planned", "body": "Hello", "target_type": "subscribers"},
        )
        self.assertEqual(status, 201)
        campaign_id = created["id"]
        status, scheduled, _ = self.request(
            "POST",
            f"/api/campaigns/{campaign_id}/schedule",
            {"scheduled_at": "2026-01-03T12:00:00Z"},
        )
        self.assertEqual(status, 200)
        self.assertEqual(scheduled["status"], "scheduled")

        status, cancelled, _ = self.request(
            "POST", f"/api/campaigns/{campaign_id}/cancel"
        )
        self.assertEqual(status, 200)
        self.assertEqual(cancelled["status"], "draft")
        self.assertIsNone(cancelled["scheduled_at"])

        self.service.dispatch_pending()
        listed = self.request("GET", "/api/campaigns")[1]["items"][0]
        self.assertEqual(listed["status"], "draft")
        self.assertEqual(listed["sent_count"], 0)
        self.assertEqual(self.bot.sent, [])

        status, response, _ = self.request(
            "POST", f"/api/campaigns/{campaign_id}/cancel"
        )
        self.assertEqual(status, 409)
        self.assertEqual(response["error"], "Only scheduled campaigns can be cancelled")
        status, response, _ = self.request("POST", "/api/campaigns/999/cancel")
        self.assertEqual(status, 404)
        self.assertEqual(response["error"], "Campaign not found")

    def test_sequence_api_validates_and_round_trips_steps(self):
        status, empty, _ = self.request("GET", "/api/sequence")
        self.assertEqual(status, 200)
        self.assertEqual(
            empty,
            {
                "enabled": False,
                "steps": [],
                "stats": {"active": 0, "completed": 0, "stopped": 0, "failed": 0},
            },
        )
        step = {"delay_minutes": 0, "body": "x"}
        invalid = [
            (
                {"enabled": True, "steps": []},
                "Add at least one step before enabling the sequence",
            ),
            ({"enabled": "yes", "steps": []}, "enabled must be a boolean"),
            ({"enabled": False}, "Sequence needs exactly enabled and steps"),
            (
                {"enabled": False, "steps": [], "extra": 1},
                "Sequence needs exactly enabled and steps",
            ),
            (
                {"enabled": False, "steps": [step] * 11},
                "steps must be a list of at most 10 items",
            ),
            (
                {"enabled": False, "steps": [{"delay_minutes": -1, "body": "x"}]},
                "Step 1 delay must be 0-43200 minutes",
            ),
            (
                {"enabled": False, "steps": [{"delay_minutes": True, "body": "x"}]},
                "Step 1 delay must be 0-43200 minutes",
            ),
            (
                {
                    "enabled": False,
                    "steps": [step, {"delay_minutes": 43201, "body": "x"}],
                },
                "Step 2 delay must be 0-43200 minutes",
            ),
            (
                {"enabled": False, "steps": [{"delay_minutes": 0, "body": "   "}]},
                "Step 1 body is required",
            ),
            (
                {"enabled": False, "steps": [{"delay_minutes": 0}]},
                "Step 1 needs delay_minutes and body",
            ),
            (
                {
                    "enabled": False,
                    "steps": [{"delay_minutes": 0, "body": "Hi {first_name}" * 70}],
                },
                "With placeholders the message may exceed 4096 characters",
            ),
            (
                {
                    "enabled": False,
                    "steps": [{"delay_minutes": 0, "body": " {username} "}],
                },
                "Message needs text besides placeholders",
            ),
        ]
        for payload, message in invalid:
            with self.subTest(message=message):
                status, response, _ = self.request("PUT", "/api/sequence", payload)
                self.assertEqual((status, response["error"]), (400, message))

        payload = {
            "enabled": True,
            "steps": [
                {"delay_minutes": 0, "body": "Привет, {first_name}"},
                {"delay_minutes": 1440, "body": "Завтра"},
            ],
        }
        status, saved, _ = self.request("PUT", "/api/sequence", payload)
        self.assertEqual(status, 200)
        self.assertEqual((saved["enabled"], saved["steps"]), (True, payload["steps"]))
        self.assertEqual(
            self.request("GET", "/api/sequence")[1]["steps"], payload["steps"]
        )

    def test_campaign_placeholders_render_per_subscriber(self):
        self.push_update(10, "/start", username="ada")
        self.push_update(11, "/start", user_id=43, first_name="Bob")
        self.request("POST", "/api/sync")
        status, campaign, _ = self.request(
            "POST",
            "/api/campaigns",
            {
                "title": "Hi",
                "body": "Привет, {first_name}! @{username}",
                "target_type": "subscribers",
            },
        )
        self.assertEqual(status, 201)
        self.request("POST", f"/api/campaigns/{campaign['id']}/send")
        self.service.dispatch_pending()

        self.assertEqual(
            sorted(message["text"] for message in self.bot.sent),
            ["Привет, Ada! @ada", "Привет, Bob! @"],
        )
        conversation = self.request("GET", "/api/inbox/42")[1]
        self.assertEqual(conversation["items"][-1]["body"], "Привет, Ada! @ada")
        status, response, _ = self.request(
            "POST",
            "/api/campaigns",
            {
                "title": "Long",
                "body": "Hi {first_name}" * 70,
                "target_type": "subscribers",
            },
        )
        self.assertEqual(
            (status, response["error"]),
            (400, "With placeholders the message may exceed 4096 characters"),
        )
        status, response, _ = self.request(
            "POST",
            "/api/campaigns",
            {"title": "Only", "body": "{first_name}", "target_type": "subscribers"},
        )
        self.assertEqual(
            (status, response["error"]),
            (400, "Message needs text besides placeholders"),
        )
        self.request("POST", "/api/chats", {"chat_id": chr(64) + "test_channel"})
        status, response, _ = self.request(
            "POST",
            "/api/campaigns",
            {
                "title": "Channel",
                "body": "Hi {first_name}",
                "target_type": "chat",
                "chat_id": "-100123456",
            },
        )
        self.assertEqual(
            (status, response["error"]),
            (400, "Placeholders are only available for bot subscribers"),
        )

    def test_campaign_delivery_report_lists_failures_first(self):
        self.push_update(10, "/start", username="ada")
        self.push_update(11, "/start", user_id=43, first_name="Bob")
        self.request("POST", "/api/sync")
        _, campaign, _ = self.request(
            "POST",
            "/api/campaigns",
            {"title": "News", "body": "Update", "target_type": "subscribers"},
        )
        self.request("POST", f"/api/campaigns/{campaign['id']}/send")
        self.bot.send_failures.append(
            TelegramError("Forbidden: bot was blocked by the user")
        )
        self.service.dispatch_pending()

        base = f"/api/campaigns/{campaign['id']}/deliveries"
        status, report, _ = self.request("GET", base)
        self.assertEqual(status, 200)
        self.assertEqual(
            report["counts"],
            {"queued": 0, "sending": 0, "sent": 1, "failed": 1, "skipped": 0},
        )
        self.assertEqual(report["total"], 2)
        first = report["items"][0]
        self.assertEqual(
            (first["status"], first["error"], first["attempt_count"]),
            ("failed", "Forbidden: bot was blocked by the user", 1),
        )
        self.assertIn(first["name"], {"Ada", "Bob"})
        self.assertFalse(first["erased"])
        _, failed_only, _ = self.request("GET", base + "?status=failed&limit=10")
        self.assertEqual((failed_only["total"], len(failed_only["items"])), (1, 1))
        _, page, _ = self.request("GET", base + "?status=all&limit=1&offset=1")
        self.assertEqual(
            (page["total"], [item["status"] for item in page["items"]]),
            (2, ["sent"]),
        )
        for query, message in (
            ("?status=bogus", "Unknown delivery status filter"),
            ("?limit=0", "limit must be 1-200 and offset non-negative"),
            ("?offset=-1", "offset must be a non-negative integer"),
            ("?limit=abc", "limit must be a non-negative integer"),
            ("?status=sent&status=failed", "Duplicate query parameter"),
        ):
            with self.subTest(query=query):
                status, response, _ = self.request("GET", base + query)
                self.assertEqual((status, response["error"]), (400, message))
        status, response, _ = self.request("GET", "/api/campaigns/999/deliveries")
        self.assertEqual((status, response["error"]), (404, "Campaign not found"))

    def test_subscriber_export_is_spreadsheet_safe(self):
        self.push_update(
            10, "/start", first_name='=HYPERLINK("http://x")', username="ada"
        )
        self.push_update(11, "/start", user_id=43, first_name="Боб")
        self.push_update(12, "/stop", user_id=43, first_name="Боб")
        self.request("POST", "/api/sync")

        status, body, headers = self.request("GET", "/api/subscribers/export")

        self.assertEqual(status, 200)
        self.assertEqual(headers["Content-Type"], "text/csv; charset=utf-8")
        self.assertEqual(
            headers["Content-Disposition"],
            'attachment; filename="teleflow-subscribers-20260102.csv"',
        )
        self.assertEqual(headers["Cache-Control"], "no-store")
        text = body.decode("utf-8")
        self.assertTrue(text.startswith("\ufeff"))
        rows = list(csv.reader(io.StringIO(text[1:])))
        self.assertEqual(
            rows[0], ["chat_id", "first_name", "username", "status", "joined_at"]
        )
        by_id = {row[0]: row for row in rows[1:]}
        self.assertEqual(
            by_id["42"][1:4], ['\'=HYPERLINK("http://x")', "ada", "subscribed"]
        )
        self.assertEqual(by_id["43"][1:4], ["Боб", "", "unsubscribed"])
        self.assertEqual(self.request("POST", "/api/subscribers/export")[0], 405)

    def test_erasing_a_subscriber_removes_data_but_keeps_campaign_totals(self):
        self.push_update(10, "/start", username="ada")
        self.push_update(11, "/start", user_id=43, first_name="Bob")
        self.request("POST", "/api/sync")
        _, first, _ = self.request(
            "POST",
            "/api/campaigns",
            {"title": "Sent", "body": "One", "target_type": "subscribers"},
        )
        self.request("POST", f"/api/campaigns/{first['id']}/send")
        self.service.dispatch_pending()
        _, second, _ = self.request(
            "POST",
            "/api/campaigns",
            {"title": "Queued", "body": "Two", "target_type": "subscribers"},
        )
        self.request("POST", f"/api/campaigns/{second['id']}/send")

        status, response, _ = self.request("DELETE", "/api/subscribers/42")

        self.assertEqual((status, response), (200, {"ok": True, "erased": True}))
        self.assertEqual(
            [
                item["chat_id"]
                for item in self.request("GET", "/api/subscribers")[1]["items"]
            ],
            [43],
        )
        self.assertEqual(self.request("GET", "/api/inbox/42")[0], 404)
        with self.service._connection() as connection:
            for table in ("messages", "campaign_deliveries"):
                self.assertEqual(
                    connection.execute(
                        f"SELECT COUNT(*) FROM {table} WHERE chat_id='42'"
                    ).fetchone()[0],
                    0,
                )
        report = self.request("GET", f"/api/campaigns/{first['id']}/deliveries")[1]
        self.assertEqual(report["counts"]["sent"], 2)
        erased = [item for item in report["items"] if item["erased"]]
        self.assertEqual(len(erased), 1)
        self.assertIsNone(erased[0]["chat_id"])
        self.assertIsNone(erased[0]["name"])
        campaigns = {
            item["id"]: item
            for item in self.request("GET", "/api/campaigns")[1]["items"]
        }
        self.assertEqual(campaigns[first["id"]]["sent_count"], 2)
        self.assertEqual(campaigns[second["id"]]["recipient_count"], 1)

        before = len(self.bot.sent)
        self.service.dispatch_pending()
        self.assertEqual(
            [str(message["chat"]["id"]) for message in self.bot.sent[before:]], ["43"]
        )
        self.assertEqual(self.service.get_campaign(second["id"])["status"], "completed")
        self.assertEqual(self.request("DELETE", "/api/subscribers/42")[0], 404)
        self.assertEqual(self.request("DELETE", "/api/subscribers/0")[0], 404)

    def test_retry_skips_deliveries_of_erased_subscribers(self):
        self.push_update(10, "/start")
        self.push_update(11, "/start", user_id=43, first_name="Bob")
        self.request("POST", "/api/sync")
        _, campaign, _ = self.request(
            "POST",
            "/api/campaigns",
            {"title": "News", "body": "Update", "target_type": "subscribers"},
        )
        self.request("POST", f"/api/campaigns/{campaign['id']}/send")
        self.bot.send_failures.append(
            TelegramError("Forbidden: bot was blocked by the user")
        )
        self.service.dispatch_pending()
        failed = self.request(
            "GET", f"/api/campaigns/{campaign['id']}/deliveries?status=failed"
        )[1]["items"][0]

        self.assertEqual(
            self.request("DELETE", f"/api/subscribers/{failed['chat_id']}")[0], 200
        )
        status, response, _ = self.request(
            "POST", f"/api/campaigns/{campaign['id']}/retry"
        )

        self.assertEqual(
            (status, response["error"]),
            (409, "This campaign has no failed deliveries to retry"),
        )
        after = self.service.get_campaign(campaign["id"])
        self.assertEqual(
            (after["status"], after["sent_count"], after["failed_count"]),
            ("partial", 1, 1),
        )

    def test_history_pruning_keeps_updates_with_pending_replies(self):
        old, recent = "2025-12-20T00:00:00Z", "2026-01-01T00:00:00Z"
        with self.service._transaction() as connection:
            connection.executemany(
                "INSERT INTO processed_updates(update_id, processed_at) VALUES (?, ?)",
                [(1, old), (2, old), (3, old), (4, recent)],
            )
            connection.executemany(
                """INSERT INTO reply_queue(update_id, chat_id, body, status, created_at)
                   VALUES (?, 42, 'Reply', ?, ?)""",
                [(2, "pending", old), (3, "sent", old)],
            )

        self.assertEqual(
            self.service.prune_history(),
            {"processed_updates": 2, "account_outbox": 0},
        )
        with self.service._connection() as connection:
            self.assertEqual(
                [
                    row[0]
                    for row in connection.execute(
                        "SELECT update_id FROM processed_updates ORDER BY update_id"
                    )
                ],
                [2, 4],
            )
            self.assertEqual(
                [
                    row[0]
                    for row in connection.execute("SELECT update_id FROM reply_queue")
                ],
                [2],
            )

    def test_worker_prunes_history_when_it_starts(self):
        pruned = threading.Event()

        def record_prune():
            pruned.set()
            return {}

        with patch.object(self.service, "prune_history", side_effect=record_prune):
            worker = BackgroundWorker(self.service, interval=0.25)
            worker.start()
            try:
                self.assertTrue(pruned.wait(3))
            finally:
                worker.stop()

    def test_operator_opt_out_waits_for_in_flight_consent_checks(self):
        self.push_update(10, "/start")
        self.request("POST", "/api/sync")
        holding, release = threading.Event(), threading.Event()

        def hold_consent_lock():
            with self.service._consent_lock:
                holding.set()
                release.wait(5)

        holder = threading.Thread(target=hold_consent_lock)
        holder.start()
        self.assertTrue(holding.wait(2))
        opt_out = threading.Thread(target=self.service.opt_out_subscriber, args=(42,))
        opt_out.start()
        opt_out.join(0.3)
        self.assertTrue(opt_out.is_alive())
        self.assertTrue(self.service.list_subscribers()[0]["opted_in"])

        release.set()
        opt_out.join(2)
        holder.join(2)
        self.assertFalse(opt_out.is_alive())
        self.assertFalse(self.service.list_subscribers()[0]["opted_in"])

    def test_operator_opt_out_skips_pending_sends_and_cancels_replies(self):
        self.request(
            "POST", "/api/rules", {"keyword": "price", "reply": "Pricing details"}
        )
        self.push_update(10, "/start")
        self.request("POST", "/api/sync")
        self.push_update(11, "What is the PRICE?")
        self.service.poll_updates()

        status, created, _ = self.request(
            "POST",
            "/api/campaigns",
            {"title": "News", "body": "Update", "target_type": "subscribers"},
        )
        self.assertEqual(status, 201)
        status, _, _ = self.request("POST", f"/api/campaigns/{created['id']}/send")
        self.assertEqual(status, 202)

        status, response, _ = self.request(
            "PATCH", "/api/subscribers/42", {"opted_in": False}
        )
        self.assertEqual(status, 200)
        self.assertFalse(response["item"]["opted_in"])
        self.assertEqual(response["item"]["chat_id"], 42)
        self.assertFalse(
            self.request("GET", "/api/subscribers")[1]["items"][0]["opted_in"]
        )

        self.service.dispatch_pending()
        finished = self.request("GET", "/api/campaigns")[1]["items"][0]
        self.assertEqual(finished["status"], "completed")
        self.assertEqual(finished["sent_count"], 0)
        self.assertEqual(self.bot.sent, [])
        with self.service._connection() as connection:
            reply_states = [
                row["status"]
                for row in connection.execute(
                    "SELECT status FROM reply_queue WHERE chat_id=42"
                ).fetchall()
            ]
        self.assertEqual(reply_states, ["cancelled"])

        status, response, _ = self.request(
            "PATCH", "/api/subscribers/42", {"opted_in": True}
        )
        self.assertEqual(status, 400)
        self.assertEqual(
            response["error"],
            "Only the subscriber can restore consent by sending /start",
        )
        status, response, _ = self.request(
            "PATCH", "/api/subscribers/42", {"unsubscribe": True}
        )
        self.assertEqual(status, 400)
        self.assertEqual(
            response["error"], "PATCH subscriber accepts only opted_in boolean"
        )
        status, response, _ = self.request(
            "PATCH", "/api/subscribers/777", {"opted_in": False}
        )
        self.assertEqual(status, 404)
        self.assertEqual(response["error"], "Subscriber not found")

    def test_opt_in_stop_campaign_send_and_inbox(self):
        self.push_update(10, "/start", username="ada")
        status, result, _ = self.request("POST", "/api/sync")
        self.assertEqual((status, result), (200, {"processed": 1}))
        subscribers = self.request("GET", "/api/subscribers")[1]["items"]
        self.assertEqual(len(subscribers), 1)
        self.assertTrue(subscribers[0]["opted_in"])
        self.assertEqual(subscribers[0]["chat_id"], 42)

        status, campaign, _ = self.request(
            "POST",
            "/api/campaigns",
            {
                "title": "Welcome",
                "body": "Hello there",
                "target_type": "subscribers",
            },
        )
        self.assertEqual(status, 201)
        self.assertEqual(campaign["status"], "draft")
        status, queued, _ = self.request(
            "POST", f"/api/campaigns/{campaign['id']}/send"
        )
        self.assertEqual(status, 202)
        self.assertEqual(queued["status"], "sending")
        self.service.dispatch_pending()
        finished = self.request("GET", "/api/campaigns")[1]["items"][0]
        self.assertEqual(
            (finished["status"], finished["sent_count"], finished["recipient_count"]),
            ("completed", 1, 1),
        )
        self.assertEqual(self.bot.sent[-1]["text"], "Hello there")

        status, conversation, _ = self.request("GET", "/api/inbox/42")
        self.assertEqual(status, 200)
        self.assertEqual(conversation["contact"]["username"], "ada")
        self.assertEqual(
            [item["direction"] for item in conversation["items"]], ["in", "out"]
        )
        inbox = self.request("GET", "/api/inbox")[1]["items"]
        self.assertEqual(inbox[0]["last_text"], "Hello there")

        self.push_update(11, "/stop")
        self.request("POST", "/api/sync")
        self.assertFalse(
            self.request("GET", "/api/subscribers")[1]["items"][0]["opted_in"]
        )
        before = len(self.bot.sent)
        status, response, _ = self.request(
            "POST", "/api/inbox/42/reply", {"body": "Still there?"}
        )
        self.assertEqual(status, 403)
        self.assertEqual(response["error"], "This contact has not opted in")
        self.assertEqual(len(self.bot.sent), before)

    def test_chat_verification_and_rules_crud(self):
        status, created, _ = self.request(
            "POST", "/api/chats", {"chat_id": chr(64) + "test_channel"}
        )
        self.assertEqual(status, 201)
        self.assertEqual(created["item"]["id"], "-100123456")
        self.assertEqual(
            self.request("GET", "/api/chats")[1]["items"][0]["type"], "channel"
        )
        self.bot.admin_status = "member"
        status, response, _ = self.request(
            "POST", "/api/chats", {"chat_id": chr(64) + "test_channel"}
        )
        self.assertEqual(status, 403)
        self.assertIn("administrator", response["error"])
        self.bot.admin_status = "administrator"

        status, created, _ = self.request(
            "POST", "/api/rules", {"keyword": "price", "reply": "See our page"}
        )
        self.assertEqual(status, 201)
        rule = created["item"]
        self.assertEqual(rule["hits"], 0)
        status, patched, _ = self.request(
            "PATCH", f"/api/rules/{rule['id']}", {"enabled": False}
        )
        self.assertEqual(status, 200)
        self.assertFalse(patched["item"]["enabled"])
        status, _, _ = self.request("DELETE", f"/api/rules/{rule['id']}")
        self.assertEqual(status, 200)

    def test_auto_reply_only_to_opted_in_users_and_deduplicates_updates(self):
        self.service.create_rule({"keyword": "price", "reply": "Pricing details"})
        self.push_update(1, "/start")
        self.assertEqual(self.service.poll_updates(), 1)
        self.push_update(2, "What is the PRICE?")
        self.assertEqual(self.service.poll_updates(), 1)
        self.assertEqual(self.service.dispatch_pending(), 1)
        self.assertEqual(self.bot.sent[-1]["text"], "Pricing details")
        self.assertEqual(self.service.list_rules()[0]["hits"], 1)
        self.push_update(3, "/stop")
        self.service.poll_updates()
        self.push_update(4, "price after stop")
        self.service.poll_updates()
        self.assertEqual(self.service.dispatch_pending(), 0)
        self.assertEqual(len(self.bot.sent), 1)
        self.assertEqual(self.service.poll_updates(), 0)

    def test_channel_campaign_scheduling_uses_utc_and_admin_verification(self):
        self.request("POST", "/api/chats", {"chat_id": chr(64) + "test_channel"})
        status, campaign, _ = self.request(
            "POST",
            "/api/campaigns",
            {
                "title": "Update",
                "body": "Channel note",
                "target_type": "chat",
                "chat_id": "-100123456",
            },
        )
        self.assertEqual(status, 201)
        status, _, _ = self.request(
            "POST",
            f"/api/campaigns/{campaign['id']}/schedule",
            {
                "scheduled_at": "2026-01-02T13:00:00+02:00",
            },
        )
        self.assertEqual(status, 400)
        status, scheduled, _ = self.request(
            "POST",
            f"/api/campaigns/{campaign['id']}/schedule",
            {
                "scheduled_at": "2026-01-02T13:00:00Z",
            },
        )
        self.assertEqual(status, 200)
        self.assertEqual(scheduled["scheduled_at"], "2026-01-02T13:00:00Z")
        with self.service._transaction() as connection:
            connection.execute(
                "UPDATE campaigns SET scheduled_at='2026-01-02T11:59:00Z' WHERE id=?",
                (campaign["id"],),
            )
        self.service.dispatch_pending()
        result = self.service.get_campaign(campaign["id"])
        self.assertEqual(result["status"], "completed")
        self.assertEqual(self.bot.sent[-1]["chat"]["id"], "-100123456")

    def test_failed_delivery_is_counted_and_campaign_finishes_failed(self):
        self.push_update(1, "/start")
        self.service.poll_updates()
        campaign = self.service.create_campaign(
            {"title": "Failure", "body": "Test", "target_type": "subscribers"}
        )
        self.service.send_campaign(campaign["id"])
        self.bot.fail_sends = True
        self.service.dispatch_pending()
        result = self.service.get_campaign(campaign["id"])
        self.assertEqual(
            (result["status"], result["failed_count"], result["sent_count"]),
            ("failed", 1, 0),
        )
        self.assertEqual(self.service.analytics()["totals"]["failed"], 1)

    def test_transient_429_and_timeout_are_persistently_retried(self):
        self.push_update(1, "/start", user_id=42)
        self.push_update(2, "/start", user_id=43)
        self.assertEqual(self.service.poll_updates(), 2)
        campaign = self.service.create_campaign(
            {"title": "Retry", "body": "Try again", "target_type": "subscribers"}
        )
        self.service.send_campaign(campaign["id"])
        self.bot.send_failures = [
            TelegramError("rate limited", retry_after=30, transient=True),
            TelegramError("request timed out", transient=True),
        ]

        self.assertEqual(self.service.dispatch_pending(), 0)
        with self.service._connection() as connection:
            deliveries = connection.execute(
                """SELECT status, attempt_count, next_attempt_at, failed_at
                   FROM campaign_deliveries WHERE campaign_id=? ORDER BY id""",
                (campaign["id"],),
            ).fetchall()
        self.assertEqual([row["status"] for row in deliveries], ["queued", "queued"])
        self.assertEqual([row["attempt_count"] for row in deliveries], [1, 1])
        self.assertEqual(
            [row["next_attempt_at"] for row in deliveries],
            ["2026-01-02T12:00:30Z", "2026-01-02T12:00:01Z"],
        )
        self.assertEqual([row["failed_at"] for row in deliveries], [None, None])
        self.assertEqual(self.service.get_campaign(campaign["id"])["failed_count"], 0)

        with self.service._transaction() as connection:
            connection.execute(
                "UPDATE campaign_deliveries SET next_attempt_at='2026-01-02T11:59:00Z' WHERE campaign_id=?",
                (campaign["id"],),
            )
        self.assertEqual(self.service.dispatch_pending(), 2)
        result = self.service.get_campaign(campaign["id"])
        self.assertEqual(
            (result["status"], result["sent_count"], result["failed_count"]),
            ("completed", 2, 0),
        )

    def test_operator_retry_only_requeues_failed_recipients(self):
        for update_id, user_id in enumerate((42, 43, 44), start=1):
            self.push_update(update_id, "/start", user_id=user_id)
        self.service.poll_updates()
        campaign = self.service.create_campaign(
            {"title": "Retry", "body": "Message", "target_type": "subscribers"}
        )
        self.service.send_campaign(campaign["id"])
        self.bot.send_failures = [
            TelegramError("HTTP 503", transient=True),
            TelegramError("blocked"),
            TelegramError("blocked"),
        ]
        self.assertEqual(self.service.dispatch_pending(), 0)
        with self.service._transaction() as connection:
            connection.execute(
                """UPDATE campaign_deliveries SET next_attempt_at='2026-01-02T11:59:00Z'
                   WHERE campaign_id=? AND chat_id='42'""",
                (campaign["id"],),
            )
        self.assertEqual(self.service.dispatch_pending(), 1)
        self.assertEqual(
            self.service.get_campaign(campaign["id"])["status"],
            "partial",
        )

        self.push_update(4, "/stop", user_id=44)
        self.service.poll_updates()
        status, result, _ = self.request(
            "POST", f"/api/campaigns/{campaign['id']}/retry", {}
        )
        self.assertEqual(status, 202)
        self.assertEqual(
            (result["status"], result["sent_count"], result["failed_count"]),
            ("sending", 1, 0),
        )
        status, _, _ = self.request(
            "POST", f"/api/campaigns/{campaign['id']}/retry", {}
        )
        self.assertEqual(status, 409)
        self.assertEqual(self.service.dispatch_pending(), 1)
        self.assertEqual([int(item["chat"]["id"]) for item in self.bot.sent], [42, 43])
        result = self.service.get_campaign(campaign["id"])
        self.assertEqual(
            (
                result["status"],
                result["sent_count"],
                result["failed_count"],
                result["recipient_count"],
            ),
            ("completed", 2, 0, 2),
        )

    def test_retry_after_exhaustion_resets_attempts_only_on_operator_action(self):
        self.push_update(1, "/start")
        self.service.poll_updates()
        campaign = self.service.create_campaign(
            {"title": "Outage", "body": "Retry", "target_type": "subscribers"}
        )
        self.service.send_campaign(campaign["id"])
        self.bot.send_failures = [TelegramError("HTTP 503", transient=True)] * 8
        for attempt in range(8):
            self.assertEqual(self.service.dispatch_pending(), 0)
            result = self.service.get_campaign(campaign["id"])
            self.assertEqual(result["status"], "sending" if attempt < 7 else "failed")
            if attempt < 7:
                with self.service._transaction() as connection:
                    connection.execute(
                        """UPDATE campaign_deliveries SET next_attempt_at='2026-01-02T11:59:00Z'
                           WHERE campaign_id=?""",
                        (campaign["id"],),
                    )
        with self.service._connection() as connection:
            row = connection.execute(
                """SELECT status, attempt_count, next_attempt_at
                   FROM campaign_deliveries WHERE campaign_id=?""",
                (campaign["id"],),
            ).fetchone()
        self.assertEqual(
            (row["status"], row["attempt_count"], row["next_attempt_at"]),
            ("failed", 8, None),
        )
        status, result, _ = self.request(
            "POST", f"/api/campaigns/{campaign['id']}/retry", {}
        )
        self.assertEqual((status, result["status"]), (202, "sending"))
        with self.service._connection() as connection:
            row = connection.execute(
                """SELECT status, attempt_count FROM campaign_deliveries
                   WHERE campaign_id=?""",
                (campaign["id"],),
            ).fetchone()
        self.assertEqual((row["status"], row["attempt_count"]), ("queued", 0))
        self.assertEqual(self.service.dispatch_pending(), 1)
        self.assertEqual(
            self.service.get_campaign(campaign["id"])["status"], "completed"
        )

    def test_telegram_retry_after_is_not_shortened_to_one_day(self):
        self.push_update(1, "/start")
        self.service.poll_updates()
        campaign = self.service.create_campaign(
            {"title": "Long delay", "body": "Retry later", "target_type": "subscribers"}
        )
        self.service.send_campaign(campaign["id"])
        self.bot.send_failures = [
            TelegramError("rate limited", retry_after=90_000, transient=True)
        ]
        self.assertEqual(self.service.dispatch_pending(), 0)
        with self.service._connection() as connection:
            row = connection.execute(
                """SELECT status, next_attempt_at FROM campaign_deliveries
                   WHERE campaign_id=?""",
                (campaign["id"],),
            ).fetchone()
        self.assertEqual(
            (row["status"], row["next_attempt_at"]), ("queued", "2026-01-03T13:00:00Z")
        )
        self.assertEqual(self.service.dispatch_pending(), 0)
        self.assertEqual(self.bot.sent, [])
        self.assertTrue(
            self.service._retry_at(
                TelegramError("rate limited", retry_after=10**20, transient=True), 1
            ).startswith("9999-12-31T23:59:59")
        )

    def test_empty_scheduled_audience_returns_to_editable_draft(self):
        campaign = self.service.create_campaign(
            {"title": "No audience", "body": "Later", "target_type": "subscribers"}
        )
        self.service.schedule_campaign(campaign["id"], "2026-01-02T12:00:01Z")
        self.service._clock = lambda: dt.datetime(
            2026, 1, 2, 12, 0, 2, tzinfo=dt.timezone.utc
        )
        self.assertEqual(self.service.dispatch_pending(), 0)
        result = self.service.get_campaign(campaign["id"])
        self.assertEqual((result["status"], result["failed_count"]), ("draft", 0))
        self.service.update_campaign(campaign["id"], {"title": "Editable"})

    def test_manual_reply_returns_retry_after_for_transient_telegram_errors(self):
        self.push_update(1, "/start")
        self.service.poll_updates()
        self.bot.send_failures = [
            TelegramError("rate limited", retry_after=30, transient=True)
        ]
        status, data, headers = self.request(
            "POST", "/api/inbox/42/reply", {"body": "A reply"}
        )
        self.assertEqual(status, 503)
        self.assertEqual(data["error"], "rate limited")
        self.assertEqual(headers["Retry-After"], "30")
        self.assertEqual(self.bot.sent, [])

    def test_opt_out_committed_before_claimed_broadcast_is_not_sent(self):
        self.push_update(1, "/start")
        self.service.poll_updates()
        campaign = self.service.create_campaign(
            {
                "title": "Consent",
                "body": "Only to opted-in users",
                "target_type": "subscribers",
            }
        )
        self.service.send_campaign(campaign["id"])

        claimed = threading.Event()
        resume_delivery = threading.Event()
        send_errors = []
        deliver = self.service._deliver_campaign_delivery

        def pause_before_consent_check(delivery):
            claimed.set()
            if not resume_delivery.wait(timeout=3):
                raise TimeoutError("test did not release claimed delivery")
            return deliver(delivery)

        self.service._deliver_campaign_delivery = pause_before_consent_check

        def dispatch():
            try:
                self.service.dispatch_pending()
            except Exception as error:
                send_errors.append(error)

        thread = threading.Thread(target=dispatch)
        thread.start()
        self.assertTrue(claimed.wait(timeout=3), "dispatch did not claim a delivery")
        self.push_update(2, "/stop")
        self.assertEqual(self.service.poll_updates(), 1)
        self.assertFalse(self.service.list_subscribers()[0]["opted_in"])

        resume_delivery.set()
        thread.join(timeout=3)
        self.assertFalse(thread.is_alive())
        self.assertEqual(send_errors, [])
        self.assertEqual(self.bot.sent, [])
        result = self.service.get_campaign(campaign["id"])
        self.assertEqual((result["sent_count"], result["failed_count"]), (0, 0))

    def test_campaign_can_resume_queued_work_after_service_restart(self):
        self.push_update(1, "/start")
        self.service.poll_updates()
        campaign = self.service.create_campaign(
            {"title": "Recovery", "body": "Retry", "target_type": "subscribers"}
        )
        self.service.send_campaign(campaign["id"])
        with self.service._transaction() as connection:
            connection.execute(
                "UPDATE campaign_deliveries SET status='sending' WHERE campaign_id=?",
                (campaign["id"],),
            )
        self.service.close()
        restarted = TeleflowService(
            self.root / "db.sqlite3", telegram=self.bot, send_interval=0
        )
        self.addCleanup(restarted.close)
        self.assertEqual(restarted.dispatch_pending(), 1)
        self.assertEqual(restarted.get_campaign(campaign["id"])["status"], "completed")

    def test_demo_rejects_send_without_creating_success_stats(self):
        demo_bot = FakeTelegram()
        demo = TeleflowService(
            self.root / "demo.sqlite3", telegram=demo_bot, demo=True, send_interval=0
        )
        self.addCleanup(demo.close)
        campaign = demo.create_campaign(
            {"title": "Demo", "body": "Preview", "target_type": "subscribers"}
        )
        with self.assertRaises(APIError) as caught:
            demo.send_campaign(campaign["id"])
        self.assertEqual(caught.exception.status, 403)
        self.assertEqual(
            demo.analytics()["totals"],
            {"sent": 0, "failed": 0, "subscribers": 0, "campaigns": 1},
        )
        self.assertFalse(any(method == "sendMessage" for method, _ in demo_bot.calls))

    def test_unauthenticated_public_demo_uses_isolated_db_and_disables_providers(self):
        self.assertTrue(is_public_demo_mode("0.0.0.0", None, True))
        self.assertFalse(is_public_demo_mode("127.0.0.1", None, True))
        self.assertFalse(is_public_demo_mode("0.0.0.0", "password", True))

        shared_db = self.root / "real.sqlite3"
        real_service = TeleflowService(shared_db, telegram=FakeTelegram())
        real_service._process_update(
            {
                "update_id": 1,
                "message": {
                    "chat": {"id": 99, "type": "private"},
                    "from": {"id": 99, "first_name": "Existing"},
                    "text": "/start",
                },
            }
        )
        real_service.close()

        with self.assertRaisesRegex(ValueError, "cannot use --db or TELEFLOW_DB"):
            resolve_database_location(shared_db, None, public_demo=True)
        with self.assertRaisesRegex(ValueError, "cannot use --db or TELEFLOW_DB"):
            resolve_database_location(None, str(shared_db), public_demo=True)

        isolated_db, temporary_db = resolve_database_location(
            None, None, public_demo=True
        )
        self.addCleanup(temporary_db.cleanup)
        bot = FakeTelegram()
        public_demo = TeleflowService(
            isolated_db,
            bot_token="must-not-be-used",
            openai_api_key="must-not-be-used",
            telegram=bot,
            ai_client=FakeAI(),
            demo=True,
            public_demo=True,
        )
        self.addCleanup(public_demo.close)
        self.assertEqual(public_demo.list_subscribers(), [])
        self.assertTrue(public_demo.status()["public_demo"])
        self.assertFalse(public_demo.status()["ai"]["configured"])
        self.assertFalse(public_demo.status()["telegram"]["connected"])
        with self.assertRaises(APIError) as caught:
            public_demo.draft_with_ai({"prompt": "Write a message"})
        self.assertEqual(caught.exception.status, 503)
        self.assertEqual(public_demo.poll_updates(), 0)
        self.assertEqual(bot.calls, [])

    def test_isolated_public_demo_remains_reachable_through_preview_host(self):
        public_service = TeleflowService(
            self.root / "public-demo.sqlite3",
            demo=True,
            public_demo=True,
        )
        self.addCleanup(public_service.close)

        def public_handler(*args, **kwargs):
            return TeleflowRequestHandler(
                *args, service=public_service, static_root=self.static, **kwargs
            )

        public_server = TeleflowHTTPServer(("0.0.0.0", 0), public_handler)
        public_thread = threading.Thread(
            target=public_server.serve_forever, daemon=True
        )
        public_thread.start()

        def close_public_server():
            public_server.shutdown()
            public_server.server_close()
            public_thread.join(timeout=2)

        self.addCleanup(close_public_server)
        old_host, old_port = self.host, self.port
        self.host, self.port = "127.0.0.1", public_server.server_port
        preview_host = f"preview.example:{self.port}"
        headers = {
            "Host": preview_host,
            "Origin": f"http://{preview_host}",
        }
        status, data, _ = self.request("GET", "/api/status", headers=headers)
        self.assertEqual(status, 200)
        self.assertTrue(data["demo"])
        self.assertTrue(data["public_demo"])
        status, campaign, _ = self.request(
            "POST",
            "/api/campaigns",
            {"title": "Preview", "body": "Draft only", "target_type": "subscribers"},
            headers,
        )
        self.assertEqual(status, 201)
        self.assertEqual(campaign["title"], "Preview")
        self.host, self.port = old_host, old_port

    def test_database_is_exclusively_owned_by_one_service(self):
        with self.assertRaises(DatabaseInUseError):
            TeleflowService(self.root / "db.sqlite3")
        self.service.close()
        replacement = TeleflowService(self.root / "db.sqlite3")
        self.addCleanup(replacement.close)
        self.assertEqual(replacement.list_campaigns(), [])

    def test_database_migrates_existing_delivery_queue_columns(self):
        legacy_db = self.root / "legacy.sqlite3"
        with sqlite3.connect(legacy_db) as connection:
            connection.executescript(
                """
                CREATE TABLE campaign_deliveries (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    campaign_id INTEGER NOT NULL,
                    chat_id TEXT NOT NULL,
                    status TEXT NOT NULL,
                    message_id INTEGER,
                    error TEXT,
                    created_at TEXT NOT NULL,
                    sent_at TEXT,
                    failed_at TEXT,
                    UNIQUE(campaign_id, chat_id)
                );
                CREATE TABLE processed_updates (
                    update_id INTEGER PRIMARY KEY,
                    processed_at TEXT NOT NULL
                );
                CREATE TABLE reply_queue (
                    update_id INTEGER PRIMARY KEY REFERENCES processed_updates(update_id) ON DELETE CASCADE,
                    chat_id INTEGER NOT NULL,
                    body TEXT NOT NULL,
                    status TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    error TEXT
                );
                """
            )
        migrated = TeleflowService(legacy_db)
        self.addCleanup(migrated.close)
        with migrated._connection() as connection:
            delivery_columns = {
                row["name"]
                for row in connection.execute("PRAGMA table_info(campaign_deliveries)")
            }
            reply_columns = {
                row["name"]
                for row in connection.execute("PRAGMA table_info(reply_queue)")
            }
        self.assertTrue({"next_attempt_at", "attempt_count"} <= delivery_columns)
        self.assertTrue({"next_attempt_at", "attempt_count"} <= reply_columns)

    def test_worker_dispatches_due_sends_even_when_update_polling_fails(self):
        self.push_update(1, "/start")
        self.service.poll_updates()
        campaign = self.service.create_campaign(
            {"title": "Worker", "body": "Still sends", "target_type": "subscribers"}
        )
        self.service.send_campaign(campaign["id"])
        self.bot.fail_poll = True
        worker = BackgroundWorker(self.service, interval=0.25)
        worker.start()
        self.assertTrue(self.bot.sent_event.wait(2))
        worker.stop()
        self.assertEqual(
            self.service.get_campaign(campaign["id"])["status"], "completed"
        )

    def test_password_session_and_csrf_protection(self):
        auth_service = TeleflowService(
            self.root / "auth.sqlite3", password="a-long-test-password"
        )
        self.addCleanup(auth_service.close)
        auth_server = TeleflowHTTPServer(
            ("127.0.0.1", 0),
            lambda *args, **kwargs: TeleflowRequestHandler(
                *args, service=auth_service, static_root=self.static, **kwargs
            ),
        )
        auth_thread = threading.Thread(target=auth_server.serve_forever, daemon=True)
        auth_thread.start()
        self.addCleanup(
            lambda: (
                auth_server.shutdown(),
                auth_server.server_close(),
                auth_thread.join(timeout=2),
            )
        )
        old = self.host, self.port
        self.host, self.port = auth_server.server_address
        status, _, _ = self.request("GET", "/api/subscribers")
        self.assertEqual(status, 401)
        status, _, _ = self.request(
            "POST",
            "/api/campaigns",
            {"title": "No", "body": "No", "target_type": "subscribers"},
        )
        self.assertEqual(status, 401)
        status, _, headers = self.request(
            "POST", "/api/login", {"password": "a-long-test-password"}
        )
        self.assertEqual(status, 200)
        cookie = headers["Set-Cookie"].split(";", 1)[0]
        self.assertIn("HttpOnly", headers["Set-Cookie"])
        self.assertIn("SameSite=Strict", headers["Set-Cookie"])
        status, _, _ = self.request(
            "POST",
            "/api/campaigns",
            {"title": "Cross", "body": "No", "target_type": "subscribers"},
            {
                "Cookie": cookie,
                "Origin": "https://evil.example",
                "X-Forwarded-Proto": "http",
            },
        )
        self.assertEqual(status, 403)
        status, created, _ = self.request(
            "POST",
            "/api/campaigns",
            {"title": "Authorized", "body": "Yes", "target_type": "subscribers"},
            {"Cookie": cookie},
        )
        self.assertEqual(status, 201)
        self.assertEqual(created["title"], "Authorized")
        self.host, self.port = old

    def test_static_root_serves_files_without_path_traversal(self):
        (self.static / "index.html").write_text("<h1>Teleflow</h1>", encoding="utf-8")
        status, body, headers = self.request("GET", "/")
        self.assertEqual(status, 200)
        self.assertIn(b"Teleflow", body)
        self.assertEqual(headers["Content-Type"], "text/html")
        status, _, _ = self.request("GET", "/%2e%2e/server.py")
        self.assertEqual(status, 404)
        outside = self.root / "secret.txt"
        outside.write_text("private", encoding="utf-8")
        (self.static / "leak.txt").symlink_to(outside)
        status, _, _ = self.request("GET", "/leak.txt")
        self.assertEqual(status, 404)

    def test_ai_endpoint_contract(self):
        self.service.ai_client = FakeAI()
        self.service._ai_configured = True
        status, data, _ = self.request(
            "POST",
            "/api/ai/draft",
            {
                "prompt": "Announce our opening",
                "tone": "warm",
                "kind": "launch",
                "context": "Monday",
            },
        )
        self.assertEqual((status, data), (200, {"text": "warm: Announce our opening"}))
        self.service.ai_client = None
        self.service._ai_configured = False
        status, data, _ = self.request(
            "POST", "/api/ai/draft", {"prompt": "Write something"}
        )
        self.assertEqual(status, 503)
        self.assertIn("OPENAI_API_KEY", data["error"])


class WelcomeSequenceTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.clock = MutableClock()
        self.bot = FakeTelegram()
        self.service = TeleflowService(
            Path(self.temp.name) / "sequence.sqlite3",
            telegram=self.bot,
            send_interval=0,
            clock=self.clock,
        )
        self.addCleanup(self.service.close)

    def receive(self, update_id, text, user_id=42, **from_fields):
        self.bot.updates.append(private_update(update_id, text, user_id, **from_fields))
        self.assertEqual(self.service.poll_updates(), 1)

    def sent_texts(self):
        return [message["text"] for message in self.bot.sent]

    def run_state(self, chat_id=42):
        with self.service._connection() as connection:
            return connection.execute(
                "SELECT * FROM sequence_runs WHERE chat_id=?", (chat_id,)
            ).fetchone()

    def test_steps_are_personalized_and_follow_their_delays(self):
        self.service.save_sequence(
            {
                "enabled": True,
                "steps": [
                    {"delay_minutes": 0, "body": "Привет, {first_name}!"},
                    {"delay_minutes": 60, "body": "Шаг 2 для @{username}"},
                ],
            }
        )
        self.receive(1, "/start", username="ada")
        self.assertEqual(self.service.get_sequence()["stats"]["active"], 1)

        self.assertEqual(self.service.dispatch_pending(), 1)
        self.assertEqual(self.sent_texts(), ["Привет, Ada!"])
        self.clock.advance(3599)
        self.assertEqual(self.service.dispatch_pending(), 0)
        self.clock.advance(1)
        self.assertEqual(self.service.dispatch_pending(), 1)
        self.assertEqual(self.sent_texts(), ["Привет, Ada!", "Шаг 2 для @ada"])
        self.assertEqual(
            self.service.get_sequence()["stats"],
            {"active": 0, "completed": 1, "stopped": 0, "failed": 0},
        )
        history = self.service.get_conversation(42)["items"]
        self.assertEqual(
            [item["body"] for item in history if item["direction"] == "out"],
            ["Привет, Ada!", "Шаг 2 для @ada"],
        )

        self.receive(2, "/start")
        self.clock.advance(3600)
        self.assertEqual(self.service.dispatch_pending(), 0)
        self.assertEqual(len(self.bot.sent), 2)

    def test_stop_or_operator_opt_out_halts_and_new_start_restarts(self):
        self.service.save_sequence(
            {
                "enabled": True,
                "steps": [
                    {"delay_minutes": 0, "body": "A"},
                    {"delay_minutes": 60, "body": "B"},
                ],
            }
        )
        self.receive(1, "/start")
        self.service.dispatch_pending()
        self.receive(2, "/stop")
        self.assertEqual(self.run_state()["status"], "stopped")
        self.clock.advance(7200)
        self.assertEqual(self.service.dispatch_pending(), 0)

        self.receive(3, "/start")
        run = self.run_state()
        self.assertEqual((run["status"], run["step_index"]), ("active", 0))
        self.service.dispatch_pending()
        self.assertEqual(self.sent_texts(), ["A", "A"])

        self.receive(4, "/start", user_id=43, first_name="Bob")
        self.service.opt_out_subscriber(43)
        self.assertEqual(self.run_state(43)["status"], "stopped")
        self.assertEqual(self.service.dispatch_pending(), 0)
        self.assertEqual(self.sent_texts(), ["A", "A"])

    def test_disabling_pauses_and_failures_retry_or_stop(self):
        steps = [
            {"delay_minutes": 0, "body": "A"},
            {"delay_minutes": 5, "body": "B"},
        ]
        self.service.save_sequence({"enabled": True, "steps": steps})
        self.receive(1, "/start")
        self.bot.send_failures.append(
            TelegramError("Too Many Requests", retry_after=30, transient=True)
        )
        self.assertEqual(self.service.dispatch_pending(), 0)
        run = self.run_state()
        self.assertEqual(
            (run["status"], run["next_at"], run["error"]),
            ("active", "2026-01-02T12:00:30Z", "Too Many Requests"),
        )
        self.clock.advance(30)
        self.assertEqual(self.service.dispatch_pending(), 1)

        self.service.save_sequence({"enabled": False, "steps": steps})
        self.clock.advance(600)
        self.assertEqual(self.service.dispatch_pending(), 0)
        self.service.save_sequence({"enabled": True, "steps": steps})
        self.assertEqual(self.service.dispatch_pending(), 1)
        self.assertEqual(self.sent_texts(), ["A", "B"])

        self.receive(2, "/start", user_id=43)
        self.bot.send_failures.append(
            TelegramError("Forbidden: bot was blocked by the user")
        )
        self.assertEqual(self.service.dispatch_pending(), 0)
        self.assertEqual(self.run_state(43)["status"], "failed")
        self.assertEqual(self.service.get_sequence()["stats"]["failed"], 1)

    def test_shortening_the_funnel_completes_runs_past_the_new_end(self):
        self.service.save_sequence(
            {
                "enabled": True,
                "steps": [
                    {"delay_minutes": 0, "body": "A"},
                    {"delay_minutes": 60, "body": "B"},
                ],
            }
        )
        self.receive(1, "/start")
        self.service.dispatch_pending()
        self.assertEqual(self.run_state()["step_index"], 1)

        self.service.save_sequence(
            {"enabled": True, "steps": [{"delay_minutes": 0, "body": "A"}]}
        )

        self.assertEqual(self.run_state()["status"], "completed")
        self.clock.advance(3600)
        self.assertEqual(self.service.dispatch_pending(), 0)

    def test_restart_requeues_an_in_flight_step(self):
        self.service.save_sequence(
            {"enabled": True, "steps": [{"delay_minutes": 0, "body": "A"}]}
        )
        self.receive(1, "/start")
        with self.service._transaction() as connection:
            connection.execute("UPDATE sequence_runs SET status='sending'")
        self.service.close()

        reopened = TeleflowService(
            self.service.db_path, telegram=self.bot, send_interval=0, clock=self.clock
        )
        self.addCleanup(reopened.close)

        with reopened._connection() as connection:
            self.assertEqual(
                connection.execute("SELECT status FROM sequence_runs").fetchone()[0],
                "active",
            )
        self.assertEqual(reopened.dispatch_pending(), 1)
        self.assertEqual(self.sent_texts(), ["A"])

    def test_a_run_reset_after_claim_does_not_send_the_stale_step(self):
        self.service.save_sequence(
            {
                "enabled": True,
                "steps": [
                    {"delay_minutes": 0, "body": "STEP0"},
                    {"delay_minutes": 60, "body": "STEP1"},
                ],
            }
        )
        self.receive(1, "/start")
        self.service.dispatch_pending()
        self.clock.advance(3600)
        stale = self.service._claim_sequence_run()
        self.assertEqual(stale["step_index"], 1)

        self.receive(2, "/stop")
        self.receive(3, "/start")

        self.assertFalse(self.service._deliver_sequence_run(stale))
        self.assertEqual(self.sent_texts(), ["STEP0"])
        self.assertEqual(self.service.dispatch_pending(), 1)
        self.assertEqual(self.sent_texts(), ["STEP0", "STEP0"])


class ValidationTests(unittest.TestCase):
    def test_placeholder_helpers_and_csv_cells_are_injection_safe(self):
        self.assertEqual(
            render_placeholders("Hi {first_name} @{username}", "{username}", None),
            "Hi {username} @",
        )
        self.assertEqual(placeholder_worst_case_length("Hi {first_name}"), 67)
        for value in ("=1+1", "+1", "-1", "@cmd", "\tx", "\rx"):
            with self.subTest(value=value):
                self.assertEqual(csv_cell(value), "'" + value)
        self.assertEqual(csv_cell("Ада"), "Ада")
        self.assertEqual(csv_cell(None), "")
        self.assertEqual(csv_cell(42), "42")

    def test_non_loopback_bind_requires_auth_or_demo(self):
        from server import is_loopback_host

        self.assertTrue(is_loopback_host("127.0.0.1"))
        self.assertTrue(is_loopback_host("::1"))
        self.assertTrue(is_loopback_host("localhost"))
        self.assertFalse(is_loopback_host("0.0.0.0"))
        self.assertFalse(is_loopback_host("example.com"))

    def test_real_non_loopback_start_requires_https_canonical_origin(self):
        configurations = [
            (
                {"TELEFLOW_PASSWORD": "local-test-password"},
                "TELEFLOW_PUBLIC_ORIGIN",
            ),
            (
                {
                    "TELEFLOW_PASSWORD": "local-test-password",
                    "TELEFLOW_PUBLIC_ORIGIN": "http://teleflow.example",
                },
                "must use HTTPS",
            ),
        ]
        for environment, expected_error in configurations:
            with self.subTest(expected_error=expected_error):
                stderr = io.StringIO()
                with patch.dict(os.environ, environment, clear=True):
                    with contextlib.redirect_stderr(stderr):
                        with self.assertRaises(SystemExit) as caught:
                            main(["--host", "0.0.0.0", "--port", "0"])
                self.assertEqual(caught.exception.code, 2)
                self.assertIn(expected_error, stderr.getvalue())

    def test_bot_transport_redacts_token_in_api_errors(self):
        import server

        token = "123456:secret-token"
        client = server.TelegramClient(token)
        body = json.dumps({"ok": False, "description": f"Bad token {token}"}).encode()

        class Response:
            def __enter__(self):
                return self

            def __exit__(self, *_args):
                return False

            def read(self):
                return body

        original = server.urllib.request.urlopen
        server.urllib.request.urlopen = lambda *_args, **_kwargs: Response()
        try:
            with self.assertRaises(server.TelegramError) as caught:
                client.call("getMe")
        finally:
            server.urllib.request.urlopen = original
        self.assertNotIn(token, caught.exception.message)

    def test_bot_transport_marks_rate_limits_and_network_failures_transient(self):
        import server

        client = server.TelegramClient("123456:secret-token")
        payload = json.dumps(
            {
                "ok": False,
                "error_code": 429,
                "description": "Too Many Requests",
                "parameters": {"retry_after": 30},
            }
        ).encode()
        http_error = urllib.error.HTTPError(
            "https://api.telegram.org/",
            429,
            "Too Many Requests",
            {},
            io.BytesIO(payload),
        )
        with patch("server.urllib.request.urlopen", side_effect=http_error):
            with self.assertRaises(server.TelegramError) as caught:
                client.call("sendMessage", {"chat_id": 42, "text": "hello"})
        self.assertTrue(caught.exception.transient)
        self.assertEqual(caught.exception.retry_after, 30)

        server_error = urllib.error.HTTPError(
            "https://api.telegram.org/",
            503,
            "Service Unavailable",
            {},
            io.BytesIO(json.dumps({"ok": False, "error_code": 503}).encode()),
        )
        with patch("server.urllib.request.urlopen", side_effect=server_error):
            with self.assertRaises(server.TelegramError) as caught:
                client.call("sendMessage", {"chat_id": 42, "text": "hello"})
        self.assertTrue(caught.exception.transient)
        self.assertIsNone(caught.exception.retry_after)

        with patch(
            "server.urllib.request.urlopen",
            side_effect=urllib.error.URLError("temporary network failure"),
        ):
            with self.assertRaises(server.TelegramError) as caught:
                client.call("sendMessage", {"chat_id": 42, "text": "hello"})
        self.assertTrue(caught.exception.transient)


if __name__ == "__main__":
    unittest.main()
