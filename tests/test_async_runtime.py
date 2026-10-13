import asyncio
import importlib.util
import threading
import time

import pytest


def worker_class():
    spec = importlib.util.find_spec("services.io_worker")
    assert spec is not None, "Dedicated Google IO worker is missing"
    from services.io_worker import IOWorker

    return IOWorker


@pytest.mark.asyncio
async def test_slow_io_does_not_block_event_loop():
    worker = worker_class()(timeout_seconds=1)
    task = asyncio.create_task(worker.call(time.sleep, 0.05))
    await asyncio.sleep(0.005)
    assert not task.done()
    await task
    await worker.close()


@pytest.mark.asyncio
async def test_google_calls_are_serialized_on_the_same_thread():
    worker = worker_class()(timeout_seconds=1)
    threads = []
    active = 0
    max_active = 0

    def operation():
        nonlocal active, max_active
        active += 1
        max_active = max(max_active, active)
        threads.append(threading.get_ident())
        time.sleep(0.01)
        active -= 1

    await asyncio.gather(*(worker.call(operation) for _ in range(5)))
    await worker.close()
    assert max_active == 1
    assert len(set(threads)) == 1


@pytest.mark.asyncio
async def test_timeout_does_not_cancel_submitted_write():
    worker = worker_class()(timeout_seconds=0.01, max_pending=1)
    committed = []

    def write():
        time.sleep(0.05)
        committed.append(True)

    with pytest.raises(TimeoutError):
        await worker.call(write)
    await worker.close()
    assert committed == [True]


@pytest.mark.asyncio
async def test_queue_limit_does_not_submit_extra_work():
    from services.io_worker import WorkerBusyError

    worker = worker_class()(timeout_seconds=1, max_pending=1)
    task = asyncio.create_task(worker.call(time.sleep, 0.03))
    await asyncio.sleep(0.001)
    with pytest.raises(WorkerBusyError):
        await worker.call(lambda: None)
    await task
    await worker.close()


@pytest.mark.asyncio
async def test_drain_waits_for_queued_write_and_keeps_worker_open():
    worker = worker_class()(timeout_seconds=1)
    committed = []
    task = asyncio.create_task(
        worker.call(lambda: (time.sleep(0.02), committed.append(True)))
    )
    await asyncio.sleep(0)
    drain = getattr(worker, "drain", None)
    assert callable(drain), "Service cleanup must wait for the existing IO queue"
    await drain()
    assert committed == [True]
    assert await worker.call(lambda: "still-open") == "still-open"
    await task
    await worker.close()


@pytest.mark.asyncio
async def test_two_staff_confirming_the_same_phone_produce_one_sale_and_one_kpi(
    tmp_path,
):
    from uuid import uuid4
    from services.errors import BusinessRuleError
    from services.google_sheets import GoogleSheetsService
    from tests.storage_fakes import FakeSpreadsheet, add_phone

    worker = worker_class()(timeout_seconds=2)
    sheet = FakeSpreadsheet()
    add_phone(sheet)
    sheet.add_record(
        "Xodimlar",
        {
            "Telegram ID": "2",
            "F.I.Sh": "Ali",
            "Roli": "Sotuvchi",
            "Holati": "Faol",
            "Jami KPI ($)": 0,
            "To'langan KPI ($)": 0,
            "Qoldiq KPI ($)": 0,
        },
    )
    service = GoogleSheetsService(
        spreadsheet=sheet, journal_path=tmp_path / "operations.sqlite"
    )
    try:
        await worker.call(service.initialize)
        sale = {"sell_price": "150", "seller_kpi": "10", "seller_id": 2}
        results = await asyncio.gather(
            *(
                worker.call(
                    service.record_sale,
                    "phone-1",
                    sale,
                    operation_id=str(uuid4()),
                    actor_id=actor,
                )
                for actor in (1, 2)
            ),
            return_exceptions=True,
        )
        assert sum(isinstance(result, tuple) and result[0] for result in results) == 1
        assert sum(isinstance(result, BusinessRuleError) for result in results) == 1
        assert len(sheet.calls) == 1
        assert sheet.records("Telefonlar")[0]["Holati"] == "Sotildi"
        assert sheet.records("Xodimlar")[-1]["Jami KPI ($)"] == 10
        assert len(sheet.records("Amallar")) == 1
    finally:
        await worker.call(service.close)
        await worker.close()
