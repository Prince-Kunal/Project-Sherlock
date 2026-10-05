from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api.routes import admin, auth, health, jobs, preferences, resume, settings
from app.core.config import get_settings
from app.core.db import get_engine
from app.core.logging import configure_logging
from app.core.redis import get_redis


@asynccontextmanager
async def lifespan(_: FastAPI) -> AsyncIterator[None]:
    yield
    await get_engine().dispose()
    await get_redis().aclose()


def create_app() -> FastAPI:
    configure_logging()
    config = get_settings()
    app = FastAPI(title="Sherlock", lifespan=lifespan)
    app.add_middleware(
        CORSMiddleware,
        allow_origins=config.cors_origins,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )
    app.include_router(health.router)
    app.include_router(auth.router)
    app.include_router(resume.router)
    app.include_router(preferences.router)
    app.include_router(settings.router)
    app.include_router(jobs.router)
    app.include_router(admin.router)
    return app


app = create_app()
