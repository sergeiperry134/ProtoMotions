# SPDX-License-Identifier: Apache-2.0
"""Telethon user-account transport; all clients live on one private event loop."""

from __future__ import annotations

import asyncio
import binascii
import concurrent.futures
import datetime as dt
import struct
import threading
from typing import Any

from accounts import AccountError


class TelethonGateway:
    def __init__(self, api_id: int, api_hash: str):
        try:
            from telethon import TelegramClient
            from telethon.errors import FloodWaitError, RPCError
            from telethon.sessions import StringSession
        except ImportError as error:
            raise ValueError(
                "Install the optional Telethon account dependencies"
            ) from error
        self._client_type = TelegramClient
        self._session_type = StringSession
        self._flood_error = FloodWaitError
        self._rpc_error = RPCError
        self._api_id = api_id
        self._api_hash = api_hash
        self._clients: dict[int, Any] = {}
        self._locks: dict[int, asyncio.Lock] = {}
        self._loop = asyncio.new_event_loop()
        self._thread = threading.Thread(
            target=self._run_loop, name="teleflow-accounts", daemon=True
        )
        self._thread.start()

    def _run_loop(self) -> None:
        asyncio.set_event_loop(self._loop)
        self._loop.run_forever()
        self._loop.close()

    def _submit(self, operation: Any) -> Any:
        if not self._thread.is_alive():
            operation.close()
            raise AccountError(503, "Account connection is unavailable")
        future = asyncio.run_coroutine_threadsafe(operation, self._loop)
        try:
            return future.result(timeout=30)
        except concurrent.futures.TimeoutError:
            future.cancel()
            raise AccountError(
                504, "Account request timed out; check Telegram before retrying"
            ) from None
        except self._flood_error as error:
            seconds = max(1, int(error.seconds))
            raise AccountError(
                429, "Telegram requires a pause before another request", seconds
            ) from None
        except self._rpc_error:
            raise AccountError(502, "Telegram rejected the account request") from None
        except (ConnectionError, OSError, asyncio.TimeoutError):
            raise AccountError(503, "Could not reach Telegram") from None

    def _make_client(self, session: str) -> Any:
        try:
            stored_session = self._session_type(session)
        except (
            ValueError,
            TypeError,
            UnicodeError,
            IndexError,
            binascii.Error,
            struct.error,
        ):
            raise AccountError(400, "Invalid StringSession") from None
        stored_session.save_entities = False
        return self._client_type(
            stored_session,
            self._api_id,
            self._api_hash,
            receive_updates=False,
            request_retries=0,
            connection_retries=0,
            flood_sleep_threshold=0,
            timeout=10,
        )

    @staticmethod
    async def _identity(client: Any) -> dict[str, Any]:
        if not await client.is_user_authorized():
            raise AccountError(409, "This account session is no longer authorized")
        me = await client.get_me()
        if me is None or not isinstance(me.id, int):
            raise AccountError(409, "Account identity is unavailable")
        if getattr(me, "bot", False):
            raise AccountError(400, "Bot sessions cannot be imported as user accounts")
        return {
            "id": me.id,
            "display_name": " ".join(filter(None, (me.first_name, me.last_name)))[:80]
            or f"Account {me.id}",
            "username": me.username,
        }

    def inspect(self, session: str) -> tuple[dict[str, Any], str]:
        async def operation() -> tuple[dict[str, Any], str]:
            client = self._make_client(session)
            try:
                await client.connect()
                profile = await self._identity(client)
                return profile, self._session_type.save(client.session)
            finally:
                await client.disconnect()

        return self._submit(operation())

    async def _client(self, account_id: int, session: str) -> Any:
        client = self._clients.get(account_id)
        if client is not None and (
            client.session is None or self._session_type.save(client.session) != session
        ):
            self._clients.pop(account_id)
            await client.disconnect()
            client = None
        if client is None:
            client = self._make_client(session)
            try:
                await client.connect()
                profile = await self._identity(client)
                if profile["id"] != account_id:
                    raise AccountError(
                        403, "The session belongs to a different account"
                    )
            except BaseException:
                await client.disconnect()
                raise
            self._clients[account_id] = client
        elif not client.is_connected():
            await client.connect()
        profile = await self._identity(client)
        if profile["id"] != account_id:
            raise AccountError(403, "The session belongs to a different account")
        return client

    def _with_account(
        self, account_id: int, session: str, action: Any, *, save_session: bool = True
    ) -> Any:
        async def operation() -> Any:
            async with self._locks.setdefault(account_id, asyncio.Lock()):
                client = await self._client(account_id, session)
                result = await action(client)
                return result, self._session_type.save(
                    client.session
                ) if save_session else session

        return self._submit(operation())

    @staticmethod
    def _eligible(dialog: Any) -> str | None:
        entity = dialog.entity
        if (
            dialog.is_user
            and not getattr(entity, "bot", False)
            and not getattr(entity, "deleted", False)
        ):
            return "private"
        if (
            dialog.is_channel
            and getattr(entity, "broadcast", False)
            and (
                getattr(entity, "creator", False)
                or getattr(
                    getattr(entity, "admin_rights", None), "post_messages", False
                )
            )
        ):
            return "channel"
        if dialog.is_group and getattr(entity, "creator", False):
            return "group"
        return None

    async def _dialogs(self, client: Any) -> tuple[list[dict[str, Any]], bool]:
        dialogs = await client.get_dialogs(limit=101)
        items = []
        for dialog in dialogs[:100]:
            kind = self._eligible(dialog)
            if kind:
                items.append(
                    {"id": str(dialog.id), "name": dialog.name[:160], "kind": kind}
                )
        return items, len(dialogs) > 100

    def dialogs(self, account_id: int, session: str) -> tuple[dict[str, Any], str]:
        async def action(client: Any) -> dict[str, Any]:
            items, truncated = await self._dialogs(client)
            return {"items": items, "truncated": truncated}

        return self._with_account(account_id, session, action)

    async def _find_dialog(self, client: Any, dialog_id: int) -> tuple[Any, str]:
        dialogs = await client.get_dialogs(limit=100)
        for dialog in dialogs:
            if dialog.id == dialog_id:
                kind = self._eligible(dialog)
                if kind is not None:
                    return dialog, kind
                break
        raise AccountError(404, "Dialog is not an existing conversation or owned chat")

    async def _messages(
        self, client: Any, dialog: Any
    ) -> tuple[list[dict[str, Any]], bool]:
        messages = await client.get_messages(dialog.input_entity, limit=100)
        incoming = any(
            not message.out and message.sender_id == dialog.entity.id
            for message in messages
        )
        visible = []
        for message in reversed(messages[:40]):
            timestamp = message.date or dt.datetime.now(dt.timezone.utc)
            if timestamp.tzinfo is None:
                timestamp = timestamp.replace(tzinfo=dt.timezone.utc)
            visible.append(
                {
                    "id": message.id,
                    "body": (
                        message.raw_text
                        or ("[Медиа]" if getattr(message, "media", None) else "")
                    )[:4096],
                    "out": bool(message.out),
                    "created_at": timestamp.astimezone(dt.timezone.utc).isoformat(),
                }
            )
        return visible, incoming

    def conversation(
        self, account_id: int, session: str, dialog_id: int
    ) -> tuple[dict[str, Any], str]:
        async def action(client: Any) -> dict[str, Any]:
            dialog, kind = await self._find_dialog(client, dialog_id)
            messages, incoming = await self._messages(client, dialog)
            return {
                "dialog": {
                    "id": str(dialog.id),
                    "name": dialog.name[:160],
                    "kind": kind,
                },
                "items": messages,
                "can_send": kind != "private" or incoming,
            }

        return self._with_account(account_id, session, action)

    def send(
        self, account_id: int, session: str, dialog_id: int, body: str
    ) -> tuple[dict[str, Any], str]:
        async def action(client: Any) -> dict[str, Any]:
            dialog, kind = await self._find_dialog(client, dialog_id)
            if kind == "private":
                _, incoming = await self._messages(client, dialog)
                if not incoming:
                    raise AccountError(
                        403, "Manual replies require a prior incoming message"
                    )
            sent = await client.send_message(
                dialog.input_entity, body, parse_mode=None, link_preview=False
            )
            return {"id": sent.id}

        return self._with_account(account_id, session, action)

    def revoke_session(self, account_id: int, session: str) -> None:
        async def action(client: Any) -> None:
            revoked = await client.log_out()
            if revoked is False:
                raise AccountError(502, "Telegram did not confirm session revocation")
            self._clients.pop(account_id, None)

        self._with_account(account_id, session, action, save_session=False)

    def forget(self, account_id: int) -> None:
        async def operation() -> None:
            async with self._locks.setdefault(account_id, asyncio.Lock()):
                client = self._clients.pop(account_id, None)
                if client is not None:
                    await client.disconnect()

        self._submit(operation())

    def close(self) -> None:
        async def disconnect_all() -> None:
            clients = list(self._clients.values())
            self._clients.clear()
            await asyncio.gather(
                *(client.disconnect() for client in clients), return_exceptions=True
            )

        if self._thread.is_alive():
            try:
                self._submit(disconnect_all())
            finally:
                self._loop.call_soon_threadsafe(self._loop.stop)
                self._thread.join(timeout=10)
