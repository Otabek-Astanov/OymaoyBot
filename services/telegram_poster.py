"""Telegram delivery only; monetary operations are never retried here."""

import logging
from pathlib import Path
from typing import Any

from aiogram import Bot
from aiogram.exceptions import TelegramBadRequest, TelegramRetryAfter
from aiogram.types import FSInputFile, InputMediaPhoto

import config
from utils.formatters import (
    build_buy_group_caption,
    build_channel_caption,
    build_sell_group_caption,
    extract_drive_file_id as extract_drive_file_id,
    prepare_telegram_text,
)

logger = logging.getLogger(__name__)


class NotificationDeliveryError(RuntimeError):
    def __init__(self, reason: str, *, retryable: bool = False, retry_after: float = 0):
        super().__init__(reason)
        self.retryable = retryable
        self.retry_after = retry_after


class TelegramPosterService:
    def __init__(self):
        self._io_worker = None
        self._sheets_service = None
        self._bots_by_id: dict[int, Bot] = {}

    def configure(
        self, io_worker, sheets_service, *, bots_by_id: dict[int, Bot] | None = None
    ) -> None:
        self._io_worker = io_worker
        self._sheets_service = sheets_service
        self._bots_by_id = dict(bots_by_id or {})

    async def _channel_caption(
        self, data: dict[str, Any], *, sold: bool = False
    ) -> str:
        if self._io_worker is None or self._sheets_service is None:
            raise NotificationDeliveryError(
                "Telegram poster is not configured", retryable=True
            )
        try:
            template = await self._io_worker.call(
                self._sheets_service.get_template, "Elon"
            )
            sold_template = None
            if sold:
                sold_template = await self._io_worker.call(
                    self._sheets_service.get_template, "Sotildi"
                )
            return build_channel_caption(
                data, sold, template=template, sold_template=sold_template
            )
        except NotificationDeliveryError:
            raise
        except Exception as exc:
            raise NotificationDeliveryError(
                "Channel template could not be read", retryable=True
            ) from exc

    @staticmethod
    def _photo(photo: str | FSInputFile):
        if isinstance(photo, str) and len(photo) < 255 and Path(photo).is_file():
            return FSInputFile(photo)
        return photo

    @staticmethod
    def _failure(exc: Exception, *, raise_errors: bool):
        logger.warning("Telegram delivery failed (%s)", type(exc).__name__)
        if raise_errors:
            if isinstance(exc, NotificationDeliveryError):
                raise exc
            if isinstance(exc, TelegramRetryAfter):
                # Telegram's 429 response definitively rejected this request.
                raise NotificationDeliveryError(
                    "Telegram rate limit",
                    retryable=True,
                    retry_after=exc.retry_after,
                ) from exc
            raise NotificationDeliveryError(type(exc).__name__) from exc
        return None

    async def _send(
        self,
        bot: Bot,
        chat_id: str | int,
        caption: str,
        photo=None,
        *,
        raise_errors: bool = False,
    ) -> int | None:
        if not chat_id:
            return self._failure(
                NotificationDeliveryError("Destination chat is not configured"),
                raise_errors=raise_errors,
            )
        try:
            text, parse_mode = prepare_telegram_text(caption, 1024 if photo else 4096)
            if photo:
                message = await bot.send_photo(
                    chat_id=chat_id,
                    photo=self._photo(photo),
                    caption=text,
                    parse_mode=parse_mode,
                )
            else:
                message = await bot.send_message(
                    chat_id=chat_id, text=text, parse_mode=parse_mode
                )
            message_id = getattr(message, "message_id", None)
            if (
                isinstance(message_id, bool)
                or not isinstance(message_id, int)
                or message_id <= 0
            ):
                raise NotificationDeliveryError(
                    "Telegram returned no message acknowledgement"
                )
            return message_id
        except Exception as exc:
            return self._failure(exc, raise_errors=raise_errors)

    async def post_to_channel(
        self,
        bot: Bot,
        phone_data: dict[str, Any],
        photo_path=None,
        *,
        raise_errors: bool = False,
    ) -> int | None:
        try:
            caption = await self._channel_caption(phone_data)
        except Exception as exc:
            return self._failure(exc, raise_errors=raise_errors)
        return await self._send(
            bot, config.CHANNEL_ID, caption, photo_path, raise_errors=raise_errors
        )

    async def post_to_buy_group(
        self,
        bot: Bot,
        phone_data: dict[str, Any],
        imei_photo_path=None,
        *,
        raise_errors: bool = False,
    ) -> int | None:
        return await self._send(
            bot,
            config.GROUP_HARID_ID,
            build_buy_group_caption(phone_data),
            imei_photo_path,
            raise_errors=raise_errors,
        )

    async def post_to_sell_group(
        self,
        bot: Bot,
        sale_data: dict[str, Any],
        *,
        photo=None,
        raise_errors: bool = False,
    ) -> int | None:
        # The worker passes the stored phone (or IMEI) photo for this internal
        # staff group; a raw Drive URL is never sent for Telegram to fetch.
        photo = photo or sale_data.get("phone_photo_file_id")
        return await self._send(
            bot,
            config.GROUP_SOTUV_ID,
            build_sell_group_caption(sale_data),
            photo,
            raise_errors=raise_errors,
        )

    def _channel_bots(self, bot: Bot) -> list[Bot]:
        candidates = [bot]
        for candidate in self._bots_by_id.values():
            if (
                getattr(candidate, "token", None) == config.HARID_BOT_TOKEN
                and candidate is not bot
            ):
                candidates.append(candidate)
        return candidates

    async def _edit_channel(
        self, bot: Bot, post_id: int, caption: str, photo=None
    ) -> int:
        caption_text, caption_mode = prepare_telegram_text(caption, 1024)
        message_text, message_mode = prepare_telegram_text(caption, 4096)
        last_error = None
        for candidate in self._channel_bots(bot):
            try:
                if photo:
                    result = await candidate.edit_message_media(
                        chat_id=config.CHANNEL_ID,
                        message_id=post_id,
                        media=InputMediaPhoto(
                            media=self._photo(photo),
                            caption=caption_text,
                            parse_mode=caption_mode,
                        ),
                    )
                else:
                    result = await candidate.edit_message_caption(
                        chat_id=config.CHANNEL_ID,
                        message_id=post_id,
                        caption=caption_text,
                        parse_mode=caption_mode,
                    )
                if result:
                    return post_id
                raise NotificationDeliveryError(
                    "Telegram returned no edit acknowledgement"
                )
            except TelegramBadRequest as exc:
                if "message is not modified" in exc.message.lower():
                    return post_id
                last_error = exc
                if photo:
                    continue
            # Only a definitive caption rejection permits trying a text edit.
            # A transport failure may already have succeeded and propagates.
            try:
                result = await candidate.edit_message_text(
                    chat_id=config.CHANNEL_ID,
                    message_id=post_id,
                    text=message_text,
                    parse_mode=message_mode,
                )
                if result:
                    return post_id
                raise NotificationDeliveryError(
                    "Telegram returned no edit acknowledgement"
                )
            except TelegramBadRequest as exc:
                if "message is not modified" in exc.message.lower():
                    return post_id
                last_error = exc
        raise last_error or NotificationDeliveryError(
            "Channel post could not be edited"
        )

    async def edit_channel_post(
        self,
        bot: Bot,
        post_id: int,
        phone_data: dict[str, Any],
        photo=None,
        *,
        raise_errors: bool = False,
    ) -> int | None:
        """Update the tracked listing; never create another untracked old post."""
        if not config.CHANNEL_ID or not post_id:
            return self._failure(
                NotificationDeliveryError("Channel post is not configured"),
                raise_errors=raise_errors,
            )
        try:
            caption = await self._channel_caption(phone_data)
            return await self._edit_channel(bot, post_id, caption, photo)
        except Exception as exc:
            return self._failure(exc, raise_errors=raise_errors)

    async def mark_as_sold_on_channel(
        self,
        bot: Bot,
        channel_post_id: int,
        phone_data: dict[str, Any] | None = None,
        *,
        raise_errors: bool = False,
    ) -> bool:
        if not config.CHANNEL_ID or not channel_post_id:
            self._failure(
                NotificationDeliveryError("Channel post is not configured"),
                raise_errors=raise_errors,
            )
            return False
        try:
            caption = await self._channel_caption(phone_data or {}, sold=True)
            return bool(await self._edit_channel(bot, channel_post_id, caption))
        except Exception as exc:
            self._failure(exc, raise_errors=raise_errors)
            return False


poster_service = TelegramPosterService()
