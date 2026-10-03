import logging

from app.core.config import get_settings


def configure_logging() -> None:
    level = logging.INFO if get_settings().env == "production" else logging.DEBUG
    logging.basicConfig(
        level=level,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )
    # Third-party loggers are noisy at DEBUG.
    for name in ("httpx", "httpcore", "asyncio", "watchfiles"):
        logging.getLogger(name).setLevel(logging.WARNING)
    # The arq CLI installs its own handler; don't print its lines a second time via the root logger.
    logging.getLogger("arq").propagate = False
