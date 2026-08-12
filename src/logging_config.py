"""
logging_config.py — configure structlog once at process startup.

Import this module early (done in dependencies.py) so every subsequent
`structlog.get_logger()` call gets the shared processor pipeline.

Pipeline:
  - Adds log level, logger name, and timestamp to every event dict
  - stdout: coloured, aligned console output in dev (LOG_FORMAT=pretty or unset);
            newline-delimited JSON in production (LOG_FORMAT=json)
  - file:   always newline-delimited JSON, written to AUDIT_LOG_PATH so audit
            events are durably recorded regardless of LOG_FORMAT
"""

import logging
import os
import sys
from pathlib import Path

import structlog


def configure(audit_log_path: Path | None = None) -> None:
    """Wire stdlib logging → structlog and set the shared processor chain.

    Args:
        audit_log_path: If provided, a JSON FileHandler is added that writes
                        every log record to this file in addition to stdout.
                        The parent directory is created if it does not exist.
    """

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
        stdout_renderer = structlog.processors.JSONRenderer()
    else:
        stdout_renderer = structlog.dev.ConsoleRenderer(colors=sys.stderr.isatty())

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

    # --- stdout handler (pretty in dev, JSON in prod) ---
    stdout_formatter = structlog.stdlib.ProcessorFormatter(
        foreign_pre_chain=shared_processors,
        processors=[
            structlog.stdlib.ProcessorFormatter.remove_processors_meta,
            stdout_renderer,
        ],
    )
    stdout_handler = logging.StreamHandler(sys.stdout)
    stdout_handler.setFormatter(stdout_formatter)

    root_logger = logging.getLogger()
    # Remove any handlers uvicorn/other libs added before us
    root_logger.handlers.clear()
    root_logger.addHandler(stdout_handler)

    # --- file handler (always JSON) ---
    if audit_log_path is not None:
        audit_log_path.parent.mkdir(parents=True, exist_ok=True)
        file_formatter = structlog.stdlib.ProcessorFormatter(
            foreign_pre_chain=shared_processors,
            processors=[
                structlog.stdlib.ProcessorFormatter.remove_processors_meta,
                structlog.processors.JSONRenderer(),
            ],
        )
        file_handler = logging.FileHandler(audit_log_path, encoding="utf-8")
        file_handler.setFormatter(file_formatter)
        root_logger.addHandler(file_handler)

    root_logger.setLevel(log_level)
