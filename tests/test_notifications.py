import asyncio
import importlib
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch
from uuid import UUID, uuid4, uuid5

import pytest
from aiogram.exceptions import TelegramBadRequest, TelegramRetryAfter
from aiogram.methods import SendMessage

from services.telegram_poster import TelegramPosterService


class FakeIOWorker:
    async def call(self, function, *args, **kwargs):
        return function(*args, **kwargs)


class FakeOutbox:
    def __init__(self, payload):
        self.row = {
            "operation_id": "operation-1",
            "index": 0,
            "payload": payload,
            "attempts": 0,
        }
        self.status = "pending"
        self.history = []
        self.error = ""

    def pending_notifications(self):
        return [dict(self.row)] if self.status == "pending" else []

    def mark_notification(self, operation_id, index, status, error=""):
        self.history.append(status)
        self.status = status
        self.error = error
        if status == "sending":
            self.row["attempts"] += 1


def fake_bot():
    return SimpleNamespace(
        id=123,
        token="123:example",
        send_message=AsyncMock(return_value=SimpleNamespace(message_id=99)),
        send_photo=AsyncMock(return_value=SimpleNamespace(message_id=100)),
        edit_message_caption=AsyncMock(return_value=True),
        edit_message_text=AsyncMock(return_value=True),
        edit_message_media=AsyncMock(return_value=True),
    )


def bad_request(message):
    return TelegramBadRequest(method=SendMessage(chat_id=1, text="x"), message=message)


PHONE_ID = "3234fb8b-0d11-4f25-a2f0-5384cbe5ab89"
PUBLISH_OPERATION = "7dd3f4fa-91e4-40f3-a2c5-c1369c1b566e"


class ListingOutbox(FakeOutbox):
    def __init__(self, *, status="Sotuvda", post_id=0, kind="publish_channel"):
        super().__init__(
            {
                "kind": kind,
                "bot_id": 123,
                "actor_id": 10,
                "phone_id": PHONE_ID,
                "post_id": 7,
                "data": {"model": "Phone", "sell_price": "150"},
            }
        )
        self.row["operation_id"] = PUBLISH_OPERATION
        self.phone = {
            "Telefon ID": PHONE_ID,
            "Holati": status,
            "Kanal post ID": post_id,
            "Model": "Phone",
        }
        self.recorded_posts = []
        self.record_result = True

    def get_template(self, template):
        return "<b>{model}</b> {price}$"

    def authorize_channel_publication(self, actor_id):
        assert actor_id == 10
        return True

    def get_phone_by_id(self, phone_id, *, fresh=False):
        assert phone_id == PHONE_ID
        assert fresh, "Channel worker must read the current phone record"
        return dict(self.phone)

    def record_channel_post(self, phone_id, post_id, *, operation_id, actor_id):
        self.recorded_posts.append((phone_id, post_id, operation_id, actor_id))
        if self.record_result:
            self.phone["Kanal post ID"] = post_id
        return self.record_result


class PosterTests(unittest.IsolatedAsyncioTestCase):
    async def test_channel_photo_update_edits_existing_media_without_new_message(self):
        outbox = ListingOutbox(post_id=77)
        bot = fake_bot()
        poster = TelegramPosterService()
        poster.configure(FakeIOWorker(), outbox, bots_by_id={123: bot})
        self.assertTrue(
            hasattr(poster, "edit_channel_post"), "Channel edit API is missing"
        )
        with patch("config.CHANNEL_ID", "-123"):
            result = await poster.edit_channel_post(
                bot,
                77,
                {"model": "Fresh model", "sell_price": "155"},
                "product-file-id",
                raise_errors=True,
            )
        self.assertEqual(result, 77)
        self.assertEqual(bot.edit_message_media.call_args.kwargs["message_id"], 77)
        media = bot.edit_message_media.call_args.kwargs["media"]
        self.assertEqual(media.media, "product-file-id")
        self.assertIn("Fresh model", media.caption)
        bot.send_message.assert_not_called()
        bot.send_photo.assert_not_called()

    async def test_channel_edit_network_failure_does_not_fall_through_to_another_request(
        self,
    ):
        from services.telegram_poster import NotificationDeliveryError

        outbox = ListingOutbox(post_id=77)
        bot = fake_bot()
        bot.edit_message_caption.side_effect = TimeoutError("Unknown edit result")
        poster = TelegramPosterService()
        poster.configure(FakeIOWorker(), outbox, bots_by_id={123: bot})
        self.assertTrue(
            hasattr(poster, "edit_channel_post"), "Channel edit API is missing"
        )
        with (
            patch("config.CHANNEL_ID", "-123"),
            self.assertRaises(NotificationDeliveryError),
        ):
            await poster.edit_channel_post(
                bot, 77, {"model": "Fresh model"}, raise_errors=True
            )
        bot.edit_message_text.assert_not_called()

    async def test_sale_report_escapes_names_and_never_fetches_private_imei_photo(self):
        bot = fake_bot()
        data = {
            "model": "<i>Model</i>",
            "buyer_name": "A&B",
            "imei_photo_url": "https://drive.google.com/file/d/" + "x" * 30 + "/view",
        }
        with patch("config.GROUP_SOTUV_ID", "-123"):
            await TelegramPosterService().post_to_sell_group(bot, data)
        bot.send_photo.assert_not_called()
        self.assertIn(
            "&lt;i&gt;Model&lt;/i&gt;", bot.send_message.call_args.kwargs["text"]
        )
        self.assertIn("A&amp;B", bot.send_message.call_args.kwargs["text"])

    async def test_oversized_caption_uses_safe_plain_text_within_telegram_limit(self):
        bot = fake_bot()
        data = {"model": "<b>" + "📱" * 2000 + "</b>"}
        with patch("config.GROUP_HARID_ID", "-123"):
            await TelegramPosterService().post_to_buy_group(
                bot, data, "telegram-file-id"
            )
        kwargs = bot.send_photo.call_args.kwargs
        self.assertLessEqual(len(kwargs["caption"].encode("utf-16-le")) // 2, 1024)
        self.assertIsNone(kwargs["parse_mode"])
        self.assertTrue(kwargs["caption"].endswith("…"))


class WorkerTests(unittest.IsolatedAsyncioTestCase):
    def worker_class(self):
        self.assertTrue(
            Path("services/notification_queue.py").is_file(),
            "Durable notification worker is missing",
        )
        return importlib.import_module("services.notification_queue").NotificationWorker

    async def test_publishing_is_durable_and_post_metadata_uses_deterministic_operation_id(
        self,
    ):
        outbox = ListingOutbox()
        bot = fake_bot()
        worker = self.worker_class()(FakeIOWorker(), outbox, {123: bot})
        with patch("config.CHANNEL_ID", "-123"):
            await worker.process_once()
            await worker.process_once()
        self.assertEqual(outbox.status, "sent")
        self.assertEqual(bot.send_message.await_count, 1)
        expected_operation = str(uuid5(UUID(PUBLISH_OPERATION), "channel-post:0"))
        self.assertEqual(
            outbox.recorded_posts, [(PHONE_ID, 99, expected_operation, 10)]
        )

    async def test_fractional_or_negative_recorded_post_id_never_targets_another_message(
        self,
    ):
        for post_id in (77.5, -77, True):
            with self.subTest(post_id=post_id):
                outbox = ListingOutbox(post_id=post_id)
                bot = fake_bot()
                worker = self.worker_class()(FakeIOWorker(), outbox, {123: bot})
                with patch("config.CHANNEL_ID", "-123"):
                    await worker.process_once()
                self.assertEqual(outbox.status, "unknown")
                bot.edit_message_caption.assert_not_called()
                bot.send_message.assert_not_called()

    async def test_phone_sold_before_delivery_skips_channel_publication(self):
        outbox = ListingOutbox(status="Sotildi")
        bot = fake_bot()
        worker = self.worker_class()(FakeIOWorker(), outbox, {123: bot})
        with patch("config.CHANNEL_ID", "-123"):
            await worker.process_once()
        self.assertEqual(outbox.status, "sent")
        self.assertIn("skipped", outbox.error.lower())
        bot.send_message.assert_not_called()
        self.assertEqual(outbox.recorded_posts, [])

    async def test_sale_during_publication_marks_new_post_sold_after_recording_acknowledgement(
        self,
    ):
        outbox = ListingOutbox()
        bot = fake_bot()

        async def receive(**kwargs):
            outbox.phone["Holati"] = "Sotildi"
            return SimpleNamespace(message_id=99)

        bot.send_message.side_effect = receive

        async def mark_sold(**kwargs):
            self.assertEqual(outbox.phone["Kanal post ID"], 99)
            self.assertEqual(outbox.phone["Holati"], "Sotildi")
            self.assertIn("SOTILDI", kwargs["caption"])
            return True

        bot.edit_message_caption.side_effect = mark_sold
        worker = self.worker_class()(FakeIOWorker(), outbox, {123: bot})
        with patch("config.CHANNEL_ID", "-123"):
            await worker.process_once()
        self.assertEqual(outbox.status, "sent")
        self.assertEqual(bot.edit_message_caption.await_count, 1)
        self.assertEqual(outbox.phone["Holati"], "Sotildi")

    async def test_post_acknowledgement_metadata_failure_never_reposts(self):
        outbox = ListingOutbox()
        outbox.record_result = False
        bot = fake_bot()
        worker = self.worker_class()(FakeIOWorker(), outbox, {123: bot})
        with patch("config.CHANNEL_ID", "-123"):
            await worker.process_once()
            await worker.process_once()
        self.assertEqual(outbox.status, "unknown")
        self.assertIn("post_id=99", outbox.error)
        self.assertEqual(bot.send_message.await_count, 1)

    async def test_cancellation_after_publication_preserves_post_id_for_manual_reconciliation(
        self,
    ):
        outbox = ListingOutbox()

        def interrupted(*args, **kwargs):
            raise asyncio.CancelledError()

        outbox.record_channel_post = interrupted
        bot = fake_bot()
        worker = self.worker_class()(FakeIOWorker(), outbox, {123: bot})
        with (
            patch("config.CHANNEL_ID", "-123"),
            self.assertRaises(asyncio.CancelledError),
        ):
            await worker.process_once()
        self.assertEqual(outbox.status, "unknown")
        self.assertIn("post_id=99", outbox.error)
        await worker.process_once()
        self.assertEqual(bot.send_message.await_count, 1)

    async def test_sold_edit_failure_after_publication_cannot_retry_publication(self):
        from services.telegram_poster import NotificationDeliveryError

        outbox = ListingOutbox()
        bot = fake_bot()

        async def receive(**kwargs):
            outbox.phone["Holati"] = "Sotildi"
            return SimpleNamespace(message_id=99)

        bot.send_message.side_effect = receive
        worker = self.worker_class()(FakeIOWorker(), outbox, {123: bot})
        worker.poster.mark_as_sold_on_channel = AsyncMock(
            side_effect=NotificationDeliveryError(
                "Template unavailable", retryable=True
            )
        )
        with patch("config.CHANNEL_ID", "-123"):
            await worker.process_once()
            await worker.process_once()
        self.assertEqual(outbox.status, "unknown")
        self.assertIn("post_id=99", outbox.error)
        self.assertEqual(bot.send_message.await_count, 1)

    async def test_channel_edit_without_acknowledgement_is_quarantined_without_new_post(
        self,
    ):
        outbox = ListingOutbox(post_id=77)
        bot = fake_bot()
        bot.edit_message_caption.return_value = False
        worker = self.worker_class()(FakeIOWorker(), outbox, {123: bot})
        with patch("config.CHANNEL_ID", "-123"):
            await worker.process_once()
        self.assertEqual(outbox.status, "unknown")
        bot.send_message.assert_not_called()
        bot.edit_message_text.assert_not_called()
        self.assertEqual(outbox.recorded_posts, [])

    async def test_real_storage_sale_during_publish_keeps_finances_and_tracked_post_consistent(
        self,
    ):
        from services.google_sheets import GoogleSheetsService
        from tests.storage_fakes import FakeSpreadsheet, add_phone

        with tempfile.TemporaryDirectory() as temporary:
            spreadsheet = FakeSpreadsheet()
            add_phone(spreadsheet, phone_id=PHONE_ID, cost=100)
            sheets = GoogleSheetsService(
                spreadsheet=spreadsheet,
                journal_path=Path(temporary) / "operations.sqlite",
            )
            sheets.initialize()
            payload = {
                "kind": "publish_channel",
                "phone_id": PHONE_ID,
                "actor_id": 1,
                "bot_id": 123,
                "data": {"model": "iPhone 14", "sell_price": "150"},
            }
            sheets.update_phone(
                PHONE_ID,
                {"Elon narxi ($)": "150"},
                operation_id=PUBLISH_OPERATION,
                actor_id=1,
                notifications=[payload],
            )
            bot = fake_bot()

            async def publish(**kwargs):
                sheets.record_sale(
                    PHONE_ID,
                    {"sell_price": "150", "payment_type": "Naqd"},
                    operation_id=str(uuid4()),
                    actor_id=1,
                    notifications=[
                        {
                            "kind": "sold_channel",
                            "phone_id": PHONE_ID,
                            "bot_id": 123,
                            "data": payload["data"],
                        }
                    ],
                )
                return SimpleNamespace(message_id=99)

            bot.send_message.side_effect = publish
            worker = self.worker_class()(FakeIOWorker(), sheets, {123: bot})
            with patch("config.CHANNEL_ID", "-123"):
                await worker.process_once()
                await worker.process_once()
            phone = sheets.get_phone_by_id(PHONE_ID, fresh=True)
            self.assertEqual(phone["Holati"], "Sotildi")
            self.assertEqual(phone["Kanal post ID"], 99)
            self.assertEqual(phone["Sotuv narxi ($)"], 150)
            self.assertEqual(phone["Sof foyda ($)"], 50)
            operations = spreadsheet.records("Amallar")
            self.assertEqual(sum(row["Amal turi"] == "sale" for row in operations), 1)
            self.assertEqual(bot.send_message.await_count, 1)
            self.assertGreaterEqual(bot.edit_message_caption.await_count, 1)
            self.assertEqual(sheets.pending_notifications(), [])
            sheets.close()

    async def test_existing_channel_post_is_edited_instead_of_creating_stale_duplicate(
        self,
    ):
        outbox = ListingOutbox(post_id=77)
        bot = fake_bot()
        worker = self.worker_class()(FakeIOWorker(), outbox, {123: bot})
        with patch("config.CHANNEL_ID", "-123"):
            await worker.process_once()
        self.assertEqual(outbox.status, "sent")
        bot.send_message.assert_not_called()
        self.assertEqual(bot.edit_message_caption.call_args.kwargs["message_id"], 77)
        self.assertEqual(outbox.recorded_posts[0][1], 77)

    async def test_post_deleted_in_channel_is_replaced_by_a_new_tracked_post(self):
        outbox = ListingOutbox(post_id=77)
        bot = fake_bot()
        bot.edit_message_caption.side_effect = bad_request(
            "Bad Request: message to edit not found"
        )
        bot.edit_message_text.side_effect = bad_request(
            "Bad Request: message to edit not found"
        )
        worker = self.worker_class()(FakeIOWorker(), outbox, {123: bot})
        with patch("config.CHANNEL_ID", "-123"):
            await worker.process_once()
        self.assertEqual(outbox.status, "sent")
        self.assertEqual(bot.send_message.await_count, 1)
        self.assertEqual(outbox.recorded_posts[0][1], 99)
        self.assertIn("replaced deleted post 77", outbox.error)

    async def test_other_edit_refusal_never_creates_a_second_post(self):
        outbox = ListingOutbox(post_id=77)
        bot = fake_bot()
        bot.edit_message_caption.side_effect = bad_request(
            "Bad Request: message can't be edited"
        )
        bot.edit_message_text.side_effect = bad_request(
            "Bad Request: message can't be edited"
        )
        worker = self.worker_class()(FakeIOWorker(), outbox, {123: bot})
        with patch("config.CHANNEL_ID", "-123"):
            await worker.process_once()
        self.assertEqual(outbox.status, "unknown")
        self.assertIn("message can't be edited", outbox.error)
        bot.send_message.assert_not_called()
        self.assertEqual(outbox.recorded_posts, [])

    async def test_sold_mark_on_deleted_post_is_skipped_not_quarantined(self):
        outbox = ListingOutbox(status="Sotildi", post_id=88, kind="sold_channel")
        bot = fake_bot()
        bot.edit_message_caption.side_effect = bad_request(
            "Bad Request: message to edit not found"
        )
        bot.edit_message_text.side_effect = bad_request(
            "Bad Request: message to edit not found"
        )
        worker = self.worker_class()(FakeIOWorker(), outbox, {123: bot})
        with patch("config.CHANNEL_ID", "-123"):
            await worker.process_once()
        self.assertEqual(outbox.status, "sent")
        self.assertIn("post 88 was deleted", outbox.error)
        bot.send_message.assert_not_called()

    async def test_sale_notification_resolves_fresh_channel_post_id(self):
        outbox = ListingOutbox(status="Sotildi", post_id=88, kind="sold_channel")
        bot = fake_bot()
        worker = self.worker_class()(FakeIOWorker(), outbox, {123: bot})
        with patch("config.CHANNEL_ID", "-123"):
            await worker.process_once()
        self.assertEqual(outbox.status, "sent")
        self.assertEqual(bot.edit_message_caption.call_args.kwargs["message_id"], 88)

    async def test_worker_persists_sending_before_delivery_and_sent_after_acknowledgement(
        self,
    ):
        outbox = FakeOutbox(
            {
                "kind": "buy_group",
                "bot_id": 123,
                "data": {"model": "Phone"},
                "photo": "telegram-file-id",
            }
        )
        bot = fake_bot()

        async def receive(**kwargs):
            self.assertEqual(outbox.status, "sending")
            return SimpleNamespace(message_id=99)

        bot.send_photo.side_effect = receive
        worker = self.worker_class()(FakeIOWorker(), outbox, {123: bot})
        with patch("config.GROUP_HARID_ID", "-123"):
            await worker.process_once()
        self.assertEqual(outbox.history, ["sending", "sent"])
        await worker.process_once()
        self.assertEqual(bot.send_photo.await_count, 1)

    async def test_ambiguous_delivery_is_quarantined_and_never_blindly_retried(self):
        outbox = FakeOutbox(
            {"kind": "sell_group", "bot_id": 123, "data": {"model": "Phone"}}
        )
        bot = fake_bot()
        bot.send_message.side_effect = TimeoutError("Unknown delivery outcome")
        worker = self.worker_class()(FakeIOWorker(), outbox, {123: bot})
        with patch("config.GROUP_SOTUV_ID", "-123"):
            await worker.process_once()
            await worker.process_once()
        self.assertEqual(outbox.status, "unknown")
        self.assertEqual(bot.send_message.await_count, 1)

    async def test_rate_limit_retries_are_bounded_without_financial_rewrites(self):
        outbox = FakeOutbox(
            {"kind": "sell_group", "bot_id": 123, "data": {"model": "Phone"}}
        )
        bot = fake_bot()
        bot.send_message.side_effect = TelegramRetryAfter(
            method=SendMessage(chat_id=-123, text="Report"),
            message="Rate limited",
            retry_after=1,
        )
        worker = self.worker_class()(FakeIOWorker(), outbox, {123: bot})
        clock = SimpleNamespace(monotonic=lambda: clock.now, now=0)
        with (
            patch("config.GROUP_SOTUV_ID", "-123"),
            patch("services.notification_queue.time", clock),
        ):
            for _ in range(3):
                await worker.process_once()
                clock.now += 10
        self.assertEqual(outbox.status, "unknown")
        self.assertEqual(bot.send_message.await_count, 3)
        self.assertEqual(outbox.row["attempts"], 3)
        await worker.process_once()
        self.assertEqual(bot.send_message.await_count, 3)

    async def test_journal_failure_before_sending_prevents_any_delivery(self):
        outbox = FakeOutbox(
            {"kind": "buy_group", "bot_id": 123, "data": {"model": "Phone"}}
        )
        outbox.mark_notification = lambda *args, **kwargs: (_ for _ in ()).throw(
            OSError("Disk full")
        )
        bot = fake_bot()
        worker = self.worker_class()(FakeIOWorker(), outbox, {123: bot})
        with self.assertRaises(OSError):
            await worker.process_once()
        bot.send_message.assert_not_called()

    async def test_interruption_during_delivery_is_unknown_after_real_journal_restart(
        self,
    ):
        from services.operation_journal import OperationJournal, payload_hash

        payload = {"kind": "buy_group", "bot_id": 123, "data": {"model": "Phone"}}
        bot = fake_bot()
        bot.send_message.side_effect = asyncio.CancelledError()
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / "outbox.sqlite"
            journal = OperationJournal(path)
            journal.prepare(
                "operation-1", "purchase", 10, {}, payload_hash({}), {}, {}, [payload]
            )
            journal.transition("operation-1", "committed")
            worker = self.worker_class()(FakeIOWorker(), journal, {123: bot})
            with (
                patch("config.GROUP_HARID_ID", "-123"),
                self.assertRaises(asyncio.CancelledError),
            ):
                await worker.process_once()
            journal.close()
            restored = OperationJournal(path)
            self.assertEqual(restored.pending_notifications(), [])
            status = restored.connection.execute(
                "SELECT state FROM notifications"
            ).fetchone()[0]
            self.assertEqual(status, "unknown")
            worker = self.worker_class()(FakeIOWorker(), restored, {123: bot})
            await worker.process_once()
            self.assertEqual(bot.send_message.await_count, 1)
            restored.close()

    async def test_data_photo_fallback_cannot_bypass_durable_file_id_validation(self):
        outbox = FakeOutbox(
            {
                "kind": "sell_group",
                "bot_id": 123,
                "data": {
                    "model": "Phone",
                    "phone_photo_file_id": "/private/tmp/ephemeral.jpg",
                },
            }
        )
        bot = fake_bot()
        worker = self.worker_class()(FakeIOWorker(), outbox, {123: bot})
        with patch("config.GROUP_SOTUV_ID", "-123"):
            await worker.process_once()
        self.assertEqual(outbox.status, "unknown")
        bot.send_photo.assert_not_called()

    async def test_unavailable_bot_is_reported_without_delivery(self):
        outbox = FakeOutbox(
            {"kind": "buy_group", "bot_id": 777, "data": {"model": "Phone"}}
        )
        worker = self.worker_class()(FakeIOWorker(), outbox, {})
        await worker.process_once()
        self.assertEqual(outbox.status, "unknown")


if __name__ == "__main__":
    unittest.main()


@pytest.mark.asyncio
async def test_wake_delivery_starts_the_next_round_without_waiting():
    from services import notification_queue

    rounds = []

    class Worker(notification_queue.NotificationWorker):
        def __init__(self):
            self.poll_interval = 30

        async def process_once(self):
            rounds.append(1)
            return 0

    task = asyncio.create_task(Worker().run())
    try:
        for _ in range(50):
            if rounds:
                break
            await asyncio.sleep(0)
        assert notification_queue.delivery_active()
        notification_queue.wake_delivery()
        await asyncio.wait_for(_until(lambda: len(rounds) >= 2), timeout=1)
    finally:
        task.cancel()
        await asyncio.gather(task, return_exceptions=True)
    assert not notification_queue.delivery_active()


async def _until(condition):
    while not condition():
        await asyncio.sleep(0)
