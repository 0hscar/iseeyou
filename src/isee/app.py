from fastapi import FastAPI

from isee import __version__
from isee.api.health import router as health_router
from isee.config import Settings, load_settings
from isee.logging_config import configure_logging


def create_app(settings: Settings | None = None) -> FastAPI:
    active_settings = settings or load_settings()
    configure_logging(active_settings.logging.level)

    application = FastAPI(title="iSeeYou", version=__version__)
    application.state.settings = active_settings
    application.include_router(health_router)
    return application


app = create_app()
