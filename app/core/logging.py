"""
Structured JSON logging with correlation-id propagation.

Every log line emitted through `get_logger()` automatically includes the
current request's correlation id (sourced from the X-Correlation-ID header,
or generated if absent) via contextvars, so logs from a single request can
be grepped together across async tasks.
"""
from __future__ import annotations

import logging
import sys
from contextvars import ContextVar

import structlog

from app.core.config import get_settings

correlation_id_var: ContextVar[str] = ContextVar("correlation_id", default="-")


def _add_correlation_id(_, __, event_dict: dict) -> dict:
    event_dict["correlation_id"] = correlation_id_var.get()
    return event_dict


def configure_logging() -> None:
    settings = get_settings()
    level = getattr(logging, settings.LOG_LEVEL.upper(), logging.INFO)

    logging.basicConfig(
        format="%(message)s",
        stream=sys.stdout,
        level=level,
    )

    shared_processors = [
        structlog.contextvars.merge_contextvars,
        _add_correlation_id,
        structlog.processors.TimeStamper(fmt="iso"),
        structlog.processors.add_log_level,
        structlog.processors.StackInfoRenderer(),
    ]

    if settings.LOG_JSON:
        renderer = structlog.processors.JSONRenderer()
    else:
        renderer = structlog.dev.ConsoleRenderer()

    structlog.configure(
        processors=shared_processors + [renderer],
        wrapper_class=structlog.make_filtering_bound_logger(level),
        context_class=dict,
        logger_factory=structlog.PrintLoggerFactory(),
        cache_logger_on_first_use=True,
    )


def get_logger(name: str = "agno_runtime") -> structlog.BoundLogger:
    return structlog.get_logger(name)
