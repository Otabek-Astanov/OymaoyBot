"""Durable, bounded Telegram outbox delivery independent of financial writes.

A process interrupted between Telegram delivery and journal acknowledgement may
have delivered the message. Such entries become ``unknown`` on journal startup;
only explicit reconciliation can make them pending again.
"""

import asyncio
import logging
import time
from dataclasses import dataclass
from typing import Any
from uuid import UUID, uuid5

from aiogram.types import BufferedInputFile

from services.telegram_poster import NotificationDeliveryError, TelegramPosterService

logger = logging.getLogger(__name__)
_running_workers = 0
_wake: asyncio.Event | None = None


def delivery_active() -> bool:
    """True while a worker loop runs; handlers wait for delivery only then."""
    return _running_workers > 0


def wake_delivery() -> None:
    """Start the next delivery round now instead of after the poll interval."""
    if _wake is not None:
        _wake.set()


@dataclass(frozen=True)
class DeliveryAcknowledgement:
    reason: str = ""


class NotificationWorker:
    def __init__(
        self,
        io_worker,
        sheets_service,
        bots_by_id: dict[int, Any],
        *,
        poll_interval: float = 1.0,
        max_attempts: int = 3,
        drive_service=None,
    ):
        self.io_worker = io_worker
        self.sheets_service = sheets_service
        self.bots_by_id = bots_by_id
        self.poll_interval = max(0.1, poll_interval)
        self.max_attempts = max_attempts
        self.drive_service = drive_service
        self.poster = TelegramPosterService()
        self.poster.configure(io_worker, sheets_service, bots_by_id=bots_by_id)
        self._next_attempt: dict[tuple[str, int], float] = {}

    async def _mark(self, row: dict[str, Any], status: str, error: str = "") -> None:
        await self.io_worker.call(
            self.sheets_service.mark_notification,
            row["operation_id"],
            row["index"],
            status,
            error=error,
        )

    @staticmethod
    def _post_id(value) -> int:
        if isinstance(value, bool):
            raise NotificationDeliveryError("Invalid recorded channel post ID")
        if value in (None, "", 0):
            return 0
        if isinstance(value, float) and value.is_integer():
            result = int(value)
        elif str(value).isascii() and str(value).isdigit():
            result = int(value)
        else:
            raise NotificationDeliveryError("Invalid recorded channel post ID")
        if result < 0:
            raise NotificationDeliveryError("Invalid recorded channel post ID")
        return result

    async def _fresh_phone(self, phone_id: str) -> dict[str, Any]:
        try:
            phone = await self.io_worker.call(
                self.sheets_service.get_phone_by_id, phone_id, fresh=True
            )
        except Exception as exc:
            raise NotificationDeliveryError(
                "Current phone record could not be read", retryable=True
            ) from exc
        if not isinstance(phone, dict):
            raise NotificationDeliveryError(
                "Channel notification phone record is missing"
            )
        return phone

    async def _publish_channel(
        self, row: dict[str, Any], bot, data: dict[str, Any], photo
    ):
        payload = row["payload"]
        try:
            phone_id = payload["phone_id"]
            if not isinstance(phone_id, str) or not phone_id.strip():
                raise ValueError
            actor_id = int(payload["actor_id"])
            metadata_operation_id = str(
                uuid5(UUID(str(row["operation_id"])), f"channel-post:{row['index']}")
            )
        except (KeyError, ValueError, TypeError) as exc:
            raise NotificationDeliveryError(
                "Invalid channel publication identity"
            ) from exc
        phone = await self._fresh_phone(phone_id)
        if phone.get("Holati") != "Sotuvda":
            return DeliveryAcknowledgement(
                "Channel publication skipped: phone is no longer Sotuvda"
            )
        try:
            await self.io_worker.call(
                self.sheets_service.authorize_channel_publication, actor_id
            )
        except Exception as exc:
            raise NotificationDeliveryError(
                "Channel publication requires current user access"
            ) from exc
        existing_post_id = self._post_id(phone.get("Kanal post ID"))
        if existing_post_id:
            post_id = await self.poster.edit_channel_post(
                bot, existing_post_id, data, photo, raise_errors=True
            )
        else:
            post_id = await self.poster.post_to_channel(
                bot, data, photo, raise_errors=True
            )
        if isinstance(post_id, bool) or not isinstance(post_id, int) or post_id <= 0:
            raise NotificationDeliveryError(
                "Telegram returned no channel post acknowledgement"
            )
        # From this point, even a retryable storage/template error must NEVER
        # repeat publication. The operator can reconcile using this safe ID.
        acknowledgement = f"post_id={post_id}"
        try:
            recorded = await self.io_worker.call(
                self.sheets_service.record_channel_post,
                phone_id,
                post_id,
                operation_id=metadata_operation_id,
                actor_id=actor_id,
            )
            if not recorded:
                raise NotificationDeliveryError(
                    "Channel post metadata was not acknowledged"
                )
            fresh_phone = await self._fresh_phone(phone_id)
            if fresh_phone.get("Holati") == "Sotildi":
                sold_data = {**fresh_phone, **data}
                sold = await self.poster.mark_as_sold_on_channel(
                    bot, post_id, sold_data, raise_errors=True
                )
                if not sold:
                    raise NotificationDeliveryError(
                        "Sold channel post edit was not acknowledged"
                    )
            return DeliveryAcknowledgement(acknowledgement)
        except asyncio.CancelledError:
            await asyncio.shield(
                self._mark(
                    row, "unknown", f"Channel delivery interrupted; {acknowledgement}"
                )
            )
            raise
        except Exception as exc:
            raise NotificationDeliveryError(
                f"Channel delivery requires reconciliation; {acknowledgement}; {type(exc).__name__}",
            ) from exc

    async def _stored_photo(self, phone_id: str):
        """The purchase photo from Drive as an upload; None keeps the text-only post.

        A Telegram file_id belongs to the bot that received it, so the sales bot
        cannot reuse the purchase bot's ids; it sends the stored bytes instead.
        """
        if self.drive_service is None:
            return None
        try:
            drive_id = await self.io_worker.call(
                self.sheets_service.phone_photo_drive_id, phone_id
            )
            if not drive_id:
                return None
            content = await self.io_worker.call(
                self.drive_service.download_photo, drive_id
            )
        except Exception as exc:
            logger.warning("Sotuv rasmi olinmadi (%s); matn yuboriladi", type(exc).__name__)
            return None
        return BufferedInputFile(content, filename="telefon.jpg")

    async def _deliver(self, row: dict[str, Any]):
        payload = row["payload"]
        try:
            bot = self.bots_by_id[int(payload["bot_id"])]
        except (KeyError, TypeError, ValueError) as exc:
            raise NotificationDeliveryError("Notification bot is unavailable") from exc
        data = payload.get("data", {})
        if not isinstance(data, dict):
            raise NotificationDeliveryError("Invalid notification record")
        photo = payload.get("photo")
        if payload.get("kind") == "sell_group":
            photo = photo or data.get("phone_photo_file_id")
        # Journal payloads must survive restarts. Temporary paths and Drive URLs
        # are not durable Telegram file_ids and are never auto-fetched here.
        if photo and (not isinstance(photo, str) or "/" in photo or ":" in photo):
            raise NotificationDeliveryError(
                "Notification requires a Telegram photo file_id"
            )
        kind = payload.get("kind")
        if kind == "buy_group":
            return await self.poster.post_to_buy_group(
                bot, data, photo, raise_errors=True
            )
        if kind == "sell_group":
            if not photo and payload.get("phone_id"):
                photo = await self._stored_photo(str(payload["phone_id"]))
            return await self.poster.post_to_sell_group(
                bot, data, photo=photo, raise_errors=True
            )
        if kind == "publish_channel":
            return await self._publish_channel(row, bot, data, photo)
        if kind == "sold_channel":
            post_id = self._post_id(payload.get("post_id", 0))
            if payload.get("phone_id"):
                phone = await self._fresh_phone(str(payload["phone_id"]))
                post_id = self._post_id(phone.get("Kanal post ID"))
                data = {**phone, **data}
                if not post_id:
                    return DeliveryAcknowledgement(
                        "Sold channel edit skipped: no tracked listing"
                    )
            return await self.poster.mark_as_sold_on_channel(
                bot, int(post_id), data, raise_errors=True
            )
        raise NotificationDeliveryError("Unknown notification kind")

    async def process_once(self) -> int:
        """Deliver a bounded batch; every journal mutation uses the shared worker."""
        pending = await self.io_worker.call(self.sheets_service.pending_notifications)
        delivered = 0
        for row in pending[:20]:
            key = (row["operation_id"], row["index"])
            if self._next_attempt.get(key, 0) > time.monotonic():
                continue
            attempts = int(row.get("attempts", 0))
            if attempts >= self.max_attempts:
                await self._mark(row, "unknown", "Notification retry limit reached")
                self._next_attempt.pop(key, None)
                continue
            # This durable marker is required BEFORE calling Telegram. A journal
            # write error therefore prevents any untracked delivery attempt.
            await self._mark(row, "sending")
            try:
                acknowledged = await self._deliver(row)
                if not acknowledged:
                    raise NotificationDeliveryError(
                        "Telegram returned no delivery acknowledgement"
                    )
            except NotificationDeliveryError as exc:
                if exc.retryable and attempts + 1 < self.max_attempts:
                    await self._mark(row, "pending", str(exc))
                    self._next_attempt[key] = time.monotonic() + max(
                        exc.retry_after, 2**attempts
                    )
                else:
                    await self._mark(row, "unknown", str(exc))
                    self._next_attempt.pop(key, None)
            except Exception as exc:
                # Do not store raw exception strings containing bot tokens/URLs.
                await self._mark(row, "unknown", type(exc).__name__)
                self._next_attempt.pop(key, None)
            else:
                # If this persistence fails, sending remains durable. Restart
                # quarantines it; repeating Telegram here would risk duplicates.
                # Group posts return their Telegram message id; keeping it lets a
                # wrong post be deleted or corrected later.
                reason = (
                    acknowledged.reason
                    if isinstance(acknowledged, DeliveryAcknowledgement)
                    else f"message_id={acknowledged}"
                    if isinstance(acknowledged, int) and not isinstance(acknowledged, bool)
                    else ""
                )
                await self._mark(row, "sent", reason)
                self._next_attempt.pop(key, None)
                delivered += 1
            await asyncio.sleep(0)
        return delivered

    async def run(self) -> None:
        global _running_workers, _wake
        _running_workers += 1
        _wake = asyncio.Event()
        try:
            while True:
                try:
                    await self.process_once()
                except Exception as exc:
                    logger.warning(
                        "Notification queue unavailable (%s)", type(exc).__name__
                    )
                try:
                    await asyncio.wait_for(_wake.wait(), timeout=self.poll_interval)
                except asyncio.TimeoutError:
                    pass
                _wake.clear()
        finally:
            _running_workers -= 1
