from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import Depends, FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api.middleware import RequestContextMiddleware, bind_path_ids
from app.api.routes import (
    admin,
    auth,
    companies,
    connections,
    health,
    jobs,
    matches,
    onboarding,
    outreach,
    preferences,
    prospects,
    resume,
    settings,
)
from app.core.config import get_settings
from app.core.db import get_engine
from app.core.logging import configure_logging
from app.core.redis import get_redis
from app.core.sentry import init_sentry


@asynccontextmanager
async def lifespan(_: FastAPI) -> AsyncIterator[None]:
    yield
    await get_engine().dispose()
    await get_redis().aclose()


def create_app() -> FastAPI:
    configure_logging()
    init_sentry("api")
    config = get_settings()
    app = FastAPI(title="Sherlock", lifespan=lifespan, dependencies=[Depends(bind_path_ids)])
    app.add_middleware(RequestContextMiddleware)  # inside CORS, so a 429 still gets CORS headers
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
    app.include_router(matches.router)
    app.include_router(companies.router)
    app.include_router(outreach.router)
    app.include_router(prospects.router)
    app.include_router(onboarding.router)
    app.include_router(connections.router)
    app.include_router(admin.router)
    return app


app = create_app()
