import logging as stdlib_logging
import os
import sys

from loguru import logger


class InterceptHandler(stdlib_logging.Handler):

    def emit(self, record: stdlib_logging.LogRecord) -> None:
        try:
            level = logger.level(record.levelname).name
        except ValueError:
            level = record.levelno

        frame, depth = stdlib_logging.currentframe(), 2
        while frame and frame.f_code.co_filename == stdlib_logging.__file__:
            frame = frame.f_back
            depth += 1

        logger.opt(depth=depth, exception=record.exc_info).log(level, record.getMessage())


def configure_logging() -> None:

    log_dir = os.getenv("LOG_DIR", "logs")
    os.makedirs(log_dir, exist_ok=True)

    intercept_handler = InterceptHandler()
    stdlib_logging.basicConfig(handlers=[intercept_handler], level=stdlib_logging.INFO, force=True)

    for uvicorn_logger_name in ("uvicorn", "uvicorn.error", "uvicorn.access"):
        uvicorn_logger = stdlib_logging.getLogger(uvicorn_logger_name)
        uvicorn_logger.handlers = [intercept_handler]
        uvicorn_logger.propagate = False

    logger.remove()
    logger.add(sys.stderr, level="INFO", format="{time:YYYY-MM-DD HH:mm:ss} [{level}] {message}")
    logger.add(
        os.path.join(log_dir, "api.log"),
        level="INFO",
        rotation="5 MB",
        retention=3,
        format="{time:YYYY-MM-DD HH:mm:ss} [{level}] {message}",
    )


def log_request(method: str, path: str, status_code: int, duration_ms: float) -> None:
    logger.info(f"{method} {path} -> {status_code} ({duration_ms:.2f} ms)")
