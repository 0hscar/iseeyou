import asyncio
import logging
import os
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI

from isee import __version__
from isee.api.health import router as health_router
from isee.config import Settings, load_settings
from isee.logging_config import configure_logging
from isee_network.collector import CollectorHealth, NetworkCollector
from isee_network.storage import SQLiteStore

LOGGER = logging.getLogger(__name__)


def create_app(settings: Settings | None = None) -> FastAPI:
    active_settings = settings or load_settings()
    configure_logging(active_settings.logging.level)

    collector_health = CollectorHealth(
        status="starting" if active_settings.router is not None else "not_configured"
    )

    @asynccontextmanager
    async def lifespan(_: FastAPI) -> AsyncIterator[None]:
        task: asyncio.Task[None] | None = None
        stop_event = asyncio.Event()
        if active_settings.router is not None:
            password = os.environ.get("ISEE_ROUTER_PASSWORD")
            if not password:
                raise RuntimeError(
                    "Set ISEE_ROUTER_PASSWORD before starting collection with a configured router"
                )
            store = SQLiteStore(active_settings.collection.database_path)
            collector = NetworkCollector(
                active_settings.router,
                active_settings.collection,
                password,
                store,
                collector_health,
            )
            task = asyncio.create_task(
                collector.run(stop_event),
                name="isee-network-collector",
            )
            task.add_done_callback(
                lambda completed: _record_collector_exit(completed, collector_health)
            )
        try:
            yield
        finally:
            if task is not None:
                stop_event.set()
                await task

    application = FastAPI(title="iSeeYou", version=__version__, lifespan=lifespan)
    application.state.settings = active_settings
    application.state.collector_health = collector_health
    application.include_router(health_router)
    return application


def _record_collector_exit(
    task: asyncio.Task[None],
    health: CollectorHealth,
) -> None:
    if task.cancelled():
        return
    error = task.exception()
    if error is None:
        return
    health.status = "error"
    health.last_error = f"Collector stopped unexpectedly: {error}"
    LOGGER.error(
        "Network collector stopped unexpectedly",
        exc_info=(type(error), error, error.__traceback__),
    )


app = create_app()
