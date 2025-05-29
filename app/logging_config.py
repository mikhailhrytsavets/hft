import logging
import os
from logging.handlers import RotatingFileHandler


def setup_logging(level: str | None = None) -> None:
    level = level or os.getenv("LOG_LEVEL", "INFO")
    logger = logging.getLogger()
    logger.setLevel(level)
    formatter = logging.Formatter(
        "%(asctime)s | %(levelname)s | %(name)s | %(message)s"
    )
    console = logging.StreamHandler()
    console.setFormatter(formatter)
    file_handler = RotatingFileHandler(
        "app.log", maxBytes=10_485_760, backupCount=5
    )
    file_handler.setFormatter(formatter)
    logger.handlers.clear()
    logger.addHandler(console)
    logger.addHandler(file_handler)
