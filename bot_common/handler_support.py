"""Preserve FSM input on failures and carry the same operation ID on retry."""

import asyncio
import logging
from contextlib import asynccontextmanager
from functools import wraps
from uuid import uuid4

from aiogram import types
from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup

from bot_common.callbacks import callback_key

from services.errors import (
    AmbiguousPhone,
    BusinessRuleError,
    OutcomeUnknown,
    PhotoUploadError,
    ServiceError,
    StorageWriteError,
)
from services.io_worker import WorkerBusyError, io_worker
from utils.formatters import safe_html
from utils.money import InvalidAmount, parse_money

logger = logging.getLogger(__name__)


async def operation_id(state):
    data = await state.get_data()
    identifier = data.get("operation_id")
    if not identifier:
        identifier = str(uuid4())
        await state.update_data(operation_id=identifier)
    return identifier


async def begin_flow(state, actor_id):
    from services.google_sheets import sheets_service

    pending = await io_worker.call(
        sheets_service.get_actor_pending_operations, actor_id
    )
    if pending:
        identifier = pending[0]["operation_id"]
        raise BusinessRuleError(
            f"Yakunlanmagan amal mavjud. Avval /amal {identifier} orqali tekshiring."
        )
    await state.clear()
    await operation_id(state)


async def commit(state, actor_id, function, *args, **kwargs):
    identifier = await operation_id(state)
    result = await io_worker.call(
        function,
        *args,
        operation_id=identifier,
        actor_id=actor_id,
        **kwargs,
    )
    saved = result[0] if isinstance(result, tuple) else result
    if not saved:
        raise StorageWriteError("Saqlash tasdiqlanmadi")
    if kwargs.get("notifications"):
        from services.notification_queue import wake_delivery

        wake_delivery()
    return result


async def find_phone(query, state):
    from services.google_sheets import sheets_service

    data = await state.get_data()
    selected = data.get("selected_phone_id")
    if selected:
        phone = await io_worker.call(
            sheets_service.get_phone_by_id, selected, fresh=True
        )
        await state.update_data(selected_phone_id=None, phone_choices={})
        return phone
    return await io_worker.call(sheets_service.get_phone_by_imei, query, fresh=True)


def clean_currency(text, *, allow_zero=False):
    return str(parse_money(text, allow_zero=allow_zero))


def safe_handler(function):
    """Only handle expected input/service failures; programming errors stay visible."""

    @wraps(function)
    async def wrapped(*args, **kwargs):
        target = args[0] if args else kwargs.get("message", kwargs.get("call"))
        state = args[1] if len(args) > 1 else kwargs.get("state")
        message = target.message if isinstance(target, types.CallbackQuery) else target
        try:
            return await function(*args, **kwargs)
        except AmbiguousPhone as exc:
            choices = {}
            rows = []
            for phone in exc.matches:
                phone_id = str(phone.get("Telefon ID", ""))
                if not phone_id:
                    continue
                key = callback_key(phone_id)
                choices[key] = phone_id
                label = f"{phone.get('Model', 'Qurilma')} · {phone.get('IMEI', '')} · {phone.get('Holati', '')}"
                rows.append(
                    [
                        InlineKeyboardButton(
                            text=label[:120], callback_data=f"phone:{key}"
                        )
                    ]
                )
            if state and rows:
                await state.update_data(phone_choices=choices)
                await message.answer(
                    "Bir nechta qurilma topildi. Keraklisini tanlang:",
                    reply_markup=InlineKeyboardMarkup(inline_keyboard=rows),
                )
            else:
                await message.answer(
                    "Bir nechta qurilma topildi. To‘liq IMEI kiriting."
                )
        except InvalidAmount as exc:
            await message.answer(f"⚠️ {safe_html(exc)}. Masalan: 10,50 yoki 1 000,50.")
        except OutcomeUnknown as exc:
            await message.answer(
                "⚠️ Amal natijasi hali tasdiqlanmadi. Hisobchi tekshirmaguncha yangi amal boshlamang.\n"
                f"Amal ID: <code>{safe_html(exc.operation_id)}</code>\n"
                f"Holat: /amal {safe_html(exc.operation_id)}",
            )
        except BusinessRuleError as exc:
            await message.answer(f"⚠️ {safe_html(exc)}")
        except PhotoUploadError:
            logger.warning("Handler operational failure: PhotoUploadError")
            await message.answer(
                "⚠️ <b>Rasm Google Drive'ga yuklanmadi</b> — Google bilan aloqa sekin.\n"
                "Hech narsa saqlanmadi. Kiritganlaringiz esda: oxirgi javobingizni "
                "(masalan, narxni) qayta yuboring."
            )
        except (ServiceError, WorkerBusyError) as exc:
            # Nothing was written: reads failed, or the write was refused before
            # it applied. An uncertain write is OutcomeUnknown, handled above.
            logger.warning("Handler operational failure: %s", type(exc).__name__)
            await message.answer(
                "⚠️ <b>Google Sheets bilan aloqa bo'lmadi.</b>\n"
                "Hech narsa saqlanmadi. Kiritganlaringiz esda: oxirgi javobingizni "
                "bir necha soniyadan keyin qayta yuboring."
            )
        except asyncio.TimeoutError:
            identifier = (
                (await state.get_data()).get("operation_id", "") if state else ""
            )
            await message.answer(
                "⚠️ Xizmat javobi kechikmoqda. Amal holatini tekshiring; yangi amal boshlamang.\n"
                f"Amal ID: <code>{safe_html(identifier)}</code>",
            )

    return wrapped


def _pressed_label(call):
    markup = getattr(call.message, "reply_markup", None)
    for row in getattr(markup, "inline_keyboard", None) or ():
        for button in row:
            if button.callback_data == call.data:
                return button.text
    return ""


async def close_prompt(call, answer=None):
    """Keep an answered inline question in the chat: drop its buttons, show the answer.

    Every inline step ends this way, so the chat reads like the typed steps
    (question, then answer) and stale buttons cannot be pressed again.
    """
    message = call.message
    answer = answer or _pressed_label(call)
    try:
        if getattr(message, "text", None) and answer:
            await message.edit_text(
                f"{message.html_text}\n✅ <b>{safe_html(answer)}</b>", reply_markup=None
            )
        else:
            await message.edit_reply_markup(reply_markup=None)
    except Exception as exc:  # an old or unchanged message cannot be edited
        logger.debug("Prompt was not closed: %s", type(exc).__name__)


@asynccontextmanager
async def progress(message, text):
    """Show a temporary "please wait" notice while slow storage work runs."""
    notice = await message.answer(f"⏳ <i>{safe_html(text)}</i>")
    try:
        yield notice
    finally:
        try:
            await notice.delete()
        except Exception as exc:
            logger.debug("Progress notice was not deleted: %s", type(exc).__name__)


async def wait_for_delivery(operation_id, index=0, *, timeout=25.0, interval=0.5):
    """Wait briefly for the outbox worker; ``None`` means it is still queued."""
    from services.google_sheets import sheets_service
    from services.notification_queue import delivery_active

    if not delivery_active():
        return None
    loop = asyncio.get_running_loop()
    deadline = loop.time() + timeout
    while loop.time() < deadline:
        try:
            status = await io_worker.call(
                sheets_service.notification_status, operation_id, index
            )
        except (ServiceError, WorkerBusyError, asyncio.TimeoutError):
            return None
        if status and status["state"] in {"sent", "unknown"}:
            return status
        await asyncio.sleep(interval)
    return None


async def answer_preview(message, text, *, photo=None, reply_markup=None):
    from utils.formatters import prepare_telegram_text

    prepared, mode = prepare_telegram_text(text, 1024 if photo else 4096)
    if photo:
        await message.answer_photo(
            photo=photo, caption=prepared, parse_mode=mode, reply_markup=reply_markup
        )
    else:
        await message.answer(prepared, parse_mode=mode, reply_markup=reply_markup)
