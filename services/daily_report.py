"""Daily report of in-stock phones not yet announced in the channel.

Lists phones that are "Sotuvda" but have no "Kanal post ID", so staff know
which ones still need a channel post. 
Sent once per day at DAILY_REPORT_TIME (Tashkent). A bot that was down at that
time still sends within CATCH_UP; the sent date is persisted so a restart never
repeats the day's report.
"""

import asyncio
import json
import logging
from collections import Counter
from datetime import datetime, timedelta
from decimal import Decimal, InvalidOperation
from pathlib import Path
from zoneinfo import ZoneInfo

from utils.formatters import safe_html

logger = logging.getLogger(__name__)

TASHKENT = ZoneInfo("Asia/Tashkent")
CATCH_UP = timedelta(hours=3)
RETRY_SECONDS = 300
# Telegram allows 4096 characters; HTML tags count here, so stay well below.
MESSAGE_LIMIT = 3800


def spaced_imei(imei) -> str:
    return " ".join(str(imei).strip().lstrip("'"))


def _amount(value) -> Decimal:
    try:
        return Decimal(str(value or 0))
    except InvalidOperation:
        return Decimal(0)


def build_stock_report(phones, today) -> list[str]:
    """Summary on top, then IMEI — model lines of unlisted phones, collapsed."""
    in_stock = [p for p in phones if p.get("Holati") == "Sotuvda"]
    stock = sorted(
        (p for p in in_stock if not str(p.get("Kanal post ID") or "").strip()),
        key=lambda p: (str(p.get("Model", "")).casefold(), str(p.get("IMEI", ""))),
    )
    title = f"📢 <b>Kanalga e'lon qilinmagan telefonlar — {today:%d.%m.%Y}</b>"
    if not stock:
        return [
            f"{title}\n\n✅ Sotuvdagi barcha telefonlar ({len(in_stock)} ta) "
            "kanalga e'lon qilingan."
        ]
    brands = Counter(
        "iPhone"
        if str(p.get("Brend", "")).casefold() == "iphone"
        else str(p.get("Brend") or "Boshqa")
        for p in stock
    )
    cost = sum(_amount(p.get("Jami tannarx ($)")) for p in stock)
    summary = [
        title,
        "",
        f"📱 E'lon qilinmagan: <b>{len(stock)} ta</b> (sotuvdagi {len(in_stock)} tadan)",
        "🏷 " + " · ".join(f"{name}: {count}" for name, count in brands.most_common()),
        f"💵 Tannarx jami: <b>{cost:,.0f}$</b>".replace(",", " "),
        "",
        "<i>Ro'yxatni ko'rish uchun pastdagi blokni oching.</i>",
    ]
    lines = [
        f"<code>{safe_html(spaced_imei(p.get('IMEI', '')))}</code> — "
        f"{safe_html(p.get('Model') or 'Qurilma')}"
        for p in stock
    ]
    messages, chunk = [], []
    head = "\n".join(summary)

    def flush():
        prefix = head if not messages else f"📢 <b>Davomi ({len(messages) + 1})</b>"
        messages.append(
            f"{prefix}\n<blockquote expandable>{chr(10).join(chunk)}</blockquote>"
        )

    for line in lines:
        prefix_len = len(head) if not messages else 40
        size = prefix_len + 40 + sum(len(x) + 1 for x in chunk) + len(line)
        if chunk and size > MESSAGE_LIMIT:
            flush()
            chunk = []
        chunk.append(line)
    flush()
    return messages


class DailyStockReport:
    def __init__(
        self,
        io_worker,
        sheets_service,
        bot,
        chat_id,
        at: str,
        state_path,
        *,
        now=lambda: datetime.now(TASHKENT),
        sleep=asyncio.sleep,
    ):
        hour, minute = (int(part) for part in at.split(":"))
        self.io_worker = io_worker
        self.sheets_service = sheets_service
        self.bot = bot
        self.chat_id = chat_id
        self.hour, self.minute = hour, minute
        self.state_path = Path(state_path)
        self.now = now
        self.sleep = sleep

    def _scheduled(self, now):
        return now.replace(hour=self.hour, minute=self.minute, second=0, microsecond=0)

    def _sent_on(self) -> str:
        try:
            return json.loads(self.state_path.read_text()).get("sent", "")
        except (OSError, ValueError):
            return ""

    def _mark_sent(self, day) -> None:
        self.state_path.write_text(json.dumps({"sent": day.isoformat()}))

    def due(self, now) -> bool:
        start = self._scheduled(now)
        return start <= now < start + CATCH_UP and self._sent_on() != now.date().isoformat()

    def seconds_until_next(self, now) -> float:
        target = self._scheduled(now)
        if now >= target:
            target += timedelta(days=1)
        return max(1.0, (target - now).total_seconds())

    async def send_once(self, now) -> int:
        phones = await self.io_worker.call(self.sheets_service.get_stock_phones)
        messages = build_stock_report(phones, now.date())
        for text in messages:
            await self.bot.send_message(chat_id=self.chat_id, text=text, parse_mode="HTML")
        self._mark_sent(now.date())
        return len(messages)

    async def run(self) -> None:
        # Never returns: the runtime treats a finished worker as a failure.
        while True:
            now = self.now()
            if self.due(now):
                try:
                    sent = await self.send_once(now)
                    logger.info("Kunlik ombor hisoboti yuborildi (%s xabar)", sent)
                except Exception as exc:
                    logger.warning(
                        "Kunlik hisobot yuborilmadi (%s); %ss dan keyin qayta",
                        type(exc).__name__,
                        RETRY_SECONDS,
                    )
                    await self.sleep(RETRY_SECONDS)
                    continue
            await self.sleep(self.seconds_until_next(self.now()))
