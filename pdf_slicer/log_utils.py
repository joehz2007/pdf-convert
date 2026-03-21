from __future__ import annotations

import logging
from contextlib import contextmanager
from time import perf_counter


DEFAULT_LOG_FORMAT = "%(asctime)s %(levelname)s %(name)s %(message)s"


def configure_logging(level: str = "INFO") -> None:
    numeric_level = getattr(logging, level.upper(), logging.INFO)
    root_logger = logging.getLogger()
    if not root_logger.handlers:
        logging.basicConfig(level=numeric_level, format=DEFAULT_LOG_FORMAT)
    else:
        root_logger.setLevel(numeric_level)


@contextmanager
def measure_stage(metrics: dict[str, int], key: str):
    start = perf_counter()
    try:
        yield
    finally:
        metrics[key] = int((perf_counter() - start) * 1000)
