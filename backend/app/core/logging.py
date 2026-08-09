"""Structured logging.

Every log line carries the request_id of the request that produced it. When we
get to debugging a bad answer in a week's time, the ability to pull every line
for one request_id - query, rewritten query, candidate chunk ids, rerank
scores, grounding verdict - is the difference between a five-minute fix and an
afternoon of guessing.
"""

from __future__ import annotations

import logging
import sys
from contextvars import ContextVar

import structlog
from structlog.typing import EventDict, Processor, WrappedLogger

# Set by the request-id middleware, read by the structlog processor below.
# A ContextVar (not a global) so concurrent requests never bleed into each
# other's log lines.
request_id_var: ContextVar[str | None] = ContextVar("request_id", default=None)


def _add_request_id(_logger: WrappedLogger, _method_name: str, event_dict: EventDict) -> EventDict:
    request_id = request_id_var.get()
    if request_id is not None:
        event_dict["request_id"] = request_id
    return event_dict


def configure_logging(level: str = "INFO", fmt: str = "console") -> None:
    """Configure structlog + stdlib logging.

    fmt="console" -> colourised, human-readable (local dev)
    fmt="json"    -> one JSON object per line (production / CI / log shipping)
    """
    numeric_level = getattr(logging, level.upper(), logging.INFO)

    logging.basicConfig(
        format="%(message)s",
        stream=sys.stdout,
        level=numeric_level,
        force=True,
    )

    # uvicorn installs its own handlers; let them propagate to root so that
    # access logs get the same treatment as ours.
    for noisy in ("uvicorn", "uvicorn.error", "uvicorn.access"):
        logging.getLogger(noisy).handlers.clear()
        logging.getLogger(noisy).propagate = True

    # SQLAlchemy is extremely chatty at INFO when echo is on.
    logging.getLogger("sqlalchemy.engine").setLevel(logging.WARNING)

    shared_processors: list[Processor] = [
        structlog.contextvars.merge_contextvars,
        _add_request_id,
        structlog.processors.add_log_level,
        structlog.processors.TimeStamper(fmt="iso", utc=True),
        structlog.processors.StackInfoRenderer(),
        structlog.processors.format_exc_info,
    ]

    renderer: Processor
    if fmt == "json":
        renderer = structlog.processors.JSONRenderer()
    else:
        renderer = structlog.dev.ConsoleRenderer(colors=sys.stdout.isatty())

    structlog.configure(
        processors=[*shared_processors, renderer],
        wrapper_class=structlog.make_filtering_bound_logger(numeric_level),
        logger_factory=structlog.PrintLoggerFactory(),
        cache_logger_on_first_use=True,
    )


def get_logger(name: str | None = None) -> structlog.stdlib.BoundLogger:
    """Return a bound structlog logger."""
    return structlog.get_logger(name)
