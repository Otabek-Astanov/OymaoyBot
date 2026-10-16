"""One lifecycle for grouped Telegram tokens, Redis FSM, and the Google writer."""

import asyncio
import fcntl
import logging
import signal
from collections.abc import Coroutine, Mapping, Sequence
from pathlib import Path

from aiogram import Bot, Dispatcher
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode
from aiogram.fsm.storage.base import DefaultKeyBuilder
from aiogram.fsm.storage.redis import RedisStorage
from redis.asyncio import Redis

import config
from services.io_worker import io_worker
from services.errors import ServiceError

logger = logging.getLogger(__name__)


class RuntimeStartupError(RuntimeError):
    pass


class ManagedDispatcher(Dispatcher):
    """Own update tasks so shutdown completes before FSM/HTTP sessions close."""

    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self._active_updates: set[asyncio.Task] = set()

    async def feed_update(self, bot, update, **kwargs):
        task = asyncio.current_task()
        if task is not None:
            self._active_updates.add(task)
        try:
            return await super().feed_update(bot, update, **kwargs)
        finally:
            self._active_updates.discard(task)

    async def emit_shutdown(self, *args, **kwargs):
        current = asyncio.current_task()
        tasks = [task for task in self._active_updates if task is not current]
        for task in tasks:
            task.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)
        await super().emit_shutdown(*args, **kwargs)


class WriterProcessLock:
    """Reject a second writer using this persistent data directory."""

    def __init__(self, path: str | Path):
        self.path = Path(path)
        self._file = None

    def acquire(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        lock_file = self.path.open("a")
        try:
            fcntl.flock(lock_file.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            lock_file.close()
            raise RuntimeStartupError(
                "Another writer runtime is already running"
            ) from None
        self._file = lock_file

    def release(self) -> None:
        if self._file is not None:
            fcntl.flock(self._file.fileno(), fcntl.LOCK_UN)
            self._file.close()
            self._file = None

    def __enter__(self):
        self.acquire()
        return self

    def __exit__(self, *_):
        self.release()


def group_tokens(tokens: Mapping[str, str]) -> dict[str, tuple[str, ...]]:
    grouped: dict[str, list[str]] = {}
    for feature, token in tokens.items():
        if token:
            grouped.setdefault(token, []).append(feature)
    if not grouped:
        raise config.ConfigurationError(
            "BOT_TOKEN yoki alohida bot tokenlari kiritilmagan"
        )
    return {token: tuple(features) for token, features in grouped.items()}


def create_fsm_storage(redis, *, ttl_seconds: int) -> RedisStorage:
    return RedisStorage(
        redis=redis,
        key_builder=DefaultKeyBuilder(with_bot_id=True),
        state_ttl=ttl_seconds,
        data_ttl=ttl_seconds,
    )


def create_dispatcher(features: tuple[str, ...], redis: Redis | None) -> Dispatcher:
    # Handler modules and Google services have no import-time IO. Import only
    # after configuration validation so they see refreshed runtime settings.
    from bot_common.access import AccessMiddleware
    from bot_common.navigation import create_navigation_router

    if redis is None:
        from aiogram.fsm.storage.memory import MemoryStorage, SimpleEventIsolation

        storage = MemoryStorage()
        dispatcher = ManagedDispatcher(
            storage=storage,
            events_isolation=SimpleEventIsolation(),
        )
    else:
        storage = create_fsm_storage(redis, ttl_seconds=config.FSM_TTL_SECONDS)
        dispatcher = ManagedDispatcher(
            storage=storage,
            events_isolation=storage.create_isolation(lock_kwargs={"timeout": 300}),
        )
    dispatcher.update.outer_middleware(AccessMiddleware(features))
    dispatcher.include_router(create_navigation_router(features))
    for feature in features:
        if feature == "harid":
            from bot_harid.handlers.harid_flow import router
        elif feature == "sotuv":
            from bot_sotuv.handlers.sotuv_flow import router
        else:
            from bot_harajat.handlers.harajat_flow import router
        dispatcher.include_router(router)
    return dispatcher


async def identify_bot(bot: Bot):
    try:
        return await asyncio.wait_for(bot.get_me(), timeout=15)
    except BaseException:
        await bot.session.close()
        raise


async def supervise(
    coroutines: Sequence[Coroutine], stop: asyncio.Event, *, shutdown=None
) -> None:
    tasks = [asyncio.create_task(item) for item in coroutines]
    signal_task = asyncio.create_task(stop.wait())
    try:
        done, _ = await asyncio.wait(
            [*tasks, signal_task], return_when=asyncio.FIRST_COMPLETED
        )
        if signal_task in done:
            return
        for task in tasks:
            if task in done:
                task.result()  # propagate the original critical error
        raise RuntimeStartupError(
            "A polling or notification worker stopped unexpectedly"
        )
    finally:
        try:
            if shutdown is not None:
                await shutdown()
        finally:
            for task in [*tasks, signal_task]:
                if not task.done():
                    task.cancel()
            await asyncio.gather(*tasks, signal_task, return_exceptions=True)


async def stop_dispatchers(dispatchers: Sequence[Dispatcher]) -> None:
    # Public stop_polling cancels aiogram's internal polling tasks. Canceling
    # only start_polling itself can leave those tasks running.
    await asyncio.gather(
        *(dispatcher.stop_polling() for dispatcher in dispatchers),
        return_exceptions=True,
    )


async def run(features: tuple[str, ...] | None = None) -> None:
    config.load_runtime_config()
    enabled = config.FEATURES if features is None else features
    config.validate_runtime_config(enabled)
    tokens = {
        feature: getattr(config, feature.upper() + "_BOT_TOKEN") for feature in enabled
    }
    grouped = group_tokens(tokens)
    io_worker.max_pending = config.IO_MAX_PENDING
    io_worker.timeout_seconds = config.IO_TIMEOUT_SECONDS
    stop = asyncio.Event()
    loop = asyncio.get_running_loop()
    signals = []
    for item in (signal.SIGINT, signal.SIGTERM):
        try:
            loop.add_signal_handler(item, stop.set)
            signals.append(item)
        except (NotImplementedError, RuntimeError):
            pass
    bots: list[Bot] = []
    dispatchers: list[Dispatcher] = []
    redis_clients: list[Redis] = []
    initialized_services = []
    lock = WriterProcessLock(str(config.OPERATION_DB_PATH) + ".lock")
    try:
        lock.acquire()
        # Redis must be reachable before polling starts. A volatile FSM is used
        # only when FSM_STORAGE_URL explicitly says memory:// (local testing).
        use_memory = config.fsm_uses_memory()
        if use_memory:
            logger.warning(
                "FSM_STORAGE_URL=memory://: bot holatlari xotirada, restartda yo'qoladi"
            )
        for _ in grouped:
            if use_memory:
                redis_clients.append(None)
                continue
            client = Redis.from_url(
                config.FSM_STORAGE_URL, socket_connect_timeout=5, socket_timeout=10
            )
            redis_clients.append(client)
            try:
                await asyncio.wait_for(client.ping(), timeout=10)
            except Exception as exc:
                raise RuntimeStartupError(
                    f"Redis ulanmadi ({type(exc).__name__}); FSM_STORAGE_URL ni tekshiring"
                ) from None

        from services.google_drive import drive_service
        from services.google_sheets import sheets_service
        from services.notification_queue import NotificationWorker

        initialized_services.extend([sheets_service, drive_service])

        initialized = await io_worker.call(sheets_service.initialize)
        ready = await io_worker.call(sheets_service.readiness)
        if initialized is False or ready is False:
            raise RuntimeStartupError("Google Sheets readiness failed")
        recovered = await io_worker.call(sheets_service.recover_pending_operations)
        if recovered and recovered.get("quarantined"):
            logger.warning(
                "Startup operation reconciliation requires attention: %s",
                len(recovered["quarantined"]),
            )
        if config.DRIVE_FOLDER_ID:
            initialized = await io_worker.call(drive_service.initialize)
            ready = await io_worker.call(drive_service.readiness)
            if initialized is False or ready is False:
                raise RuntimeStartupError("Google Drive folder readiness failed")

        for (token, token_features), redis in zip(
            grouped.items(), redis_clients, strict=True
        ):
            bot = Bot(
                token=token, default=DefaultBotProperties(parse_mode=ParseMode.HTML)
            )
            bots.append(bot)
            me = await identify_bot(bot)
            logger.info(
                "Bot ready: ID=%s; features=%s", me.id, ",".join(token_features)
            )
            dispatcher = create_dispatcher(token_features, redis)
            dispatchers.append(dispatcher)
            await bot.delete_webhook(drop_pending_updates=config.DROP_PENDING_UPDATES)
        bots_by_id = {bot.id: bot for bot in bots}
        from services.telegram_poster import poster_service
        from services.health_check import health_checker

        poster_service.configure(io_worker, sheets_service, bots_by_id=bots_by_id)
        health_checker.configure(bots_by_id=bots_by_id)
        polling = [
            dispatcher.start_polling(
                bot,
                handle_signals=False,
                close_bot_session=False,
                tasks_concurrency_limit=64,
            )
            for dispatcher, bot in zip(dispatchers, bots, strict=True)
        ]
        notifications = NotificationWorker(io_worker, sheets_service, bots_by_id)
        await supervise(
            [*polling, notifications.run()],
            stop,
            shutdown=lambda: stop_dispatchers(dispatchers),
        )
    finally:
        await asyncio.gather(
            *(dispatcher.fsm.close() for dispatcher in dispatchers),
            *(bot.session.close() for bot in bots),
            *(redis.aclose() for redis in redis_clients if redis is not None),
            return_exceptions=True,
        )
        # Finish any submitted write before releasing the single-writer lock.
        try:
            drain = getattr(io_worker, "drain", None)
            if drain is not None:
                await drain()
            for service in initialized_services:
                close = getattr(service, "close", None)
                if close is None:
                    close = getattr(getattr(service, "service", None), "close", None)
                if close is not None:
                    try:
                        await io_worker.call(close)
                    except Exception as exc:
                        logger.warning("Service close failed: %s", type(exc).__name__)
            await io_worker.close()
        finally:
            lock.release()
            for item in signals:
                loop.remove_signal_handler(item)


def entrypoint(features: tuple[str, ...] | None = None) -> None:
    logging.basicConfig(
        level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s"
    )
    try:
        asyncio.run(run(features))
    except (config.ConfigurationError, RuntimeStartupError, ServiceError) as exc:
        logger.error("Startup refused: %s", exc)
        raise SystemExit(1) from None
    except KeyboardInterrupt:
        pass
    except Exception as exc:
        # The exception type is enough for normal logs. Google/Telegram errors
        # may contain URLs and credentials, so do not echo their raw messages.
        logger.error("Runtime stopped: %s", type(exc).__name__)
        raise SystemExit(1) from None
