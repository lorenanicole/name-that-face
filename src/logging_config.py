"""
logging_config.py — configure structlog once at process startup.

Import this module early (done in dependencies.py) so every subsequent
`structlog.get_logger()` call gets the shared processor pipeline.

Pipeline:
  - Adds log level, logger name, and timestamp to every event dict
  - In development (LOG_FORMAT=pretty or unset): coloured, aligned console output
  - In production (LOG_FORMAT=json): newline-delimited JSON to stdout, suitable
    for Datadog / CloudWatch / any log aggregator
"""

import logging
import os
import sys

import structlog


def configure() -> None:
    """Wire stdlib logging → structlog and set the shared processor chain."""

    log_format = os.getenv("LOG_FORMAT", "pretty").lower()
    log_level_name = os.getenv("LOG_LEVEL", "INFO").upper()
    log_level = getattr(logging, log_level_name, logging.INFO)

    # Shared processors run on every log call regardless of renderer
    shared_processors: list = [
        structlog.contextvars.merge_contextvars,
        structlog.stdlib.add_log_level,
        structlog.stdlib.add_logger_name,
        structlog.processors.TimeStamper(fmt="iso", utc=True),
        structlog.stdlib.PositionalArgumentsFormatter(),
        structlog.processors.StackInfoRenderer(),
    ]

    if log_format == "json":
        renderer = structlog.processors.JSONRenderer()
    else:
        renderer = structlog.dev.ConsoleRenderer(colors=sys.stderr.isatty())

    structlog.configure(
        processors=shared_processors
        + [
            # Prepare the event dict for the final renderer
            structlog.stdlib.ProcessorFormatter.wrap_for_formatter,
        ],
        logger_factory=structlog.stdlib.LoggerFactory(),
        wrapper_class=structlog.stdlib.BoundLogger,
        cache_logger_on_first_use=True,
    )

    formatter = structlog.stdlib.ProcessorFormatter(
        # Processors that run only in the formatter (after stdlib hand-off)
        foreign_pre_chain=shared_processors,
        processors=[
            structlog.stdlib.ProcessorFormatter.remove_processors_meta,
            renderer,
        ],
    )

    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(formatter)

    root_logger = logging.getLogger()
    # Remove any handlers uvicorn/other libs added before us
    root_logger.handlers.clear()
    root_logger.addHandler(handler)
    root_logger.setLevel(log_level)
