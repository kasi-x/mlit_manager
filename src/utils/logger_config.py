"""logger_config.py: This module configures the logging.
This module uses structlog to configure logging.
"""

import logging
import sys
from enum import IntEnum

import structlog
from structlog.dev import ConsoleRenderer
from structlog.processors import JSONRenderer


class LEVEL(IntEnum):
    DEBUG = logging.DEBUG
    INFO = logging.INFO
    WARNING = logging.WARNING
    ERROR = logging.ERROR
    CRITICAL = logging.CRITICAL
    FATAL = logging.FATAL


def configure_logger(
    logging_level: int | LEVEL = logging.WARNING,
) -> None:
    root_logger = logging.getLogger()
    root_logger.setLevel(logging_level)

    structlog.configure(
        processors=[
            structlog.stdlib.add_log_level,
            structlog.stdlib.add_logger_name,
            structlog.stdlib.PositionalArgumentsFormatter(),
            structlog.processors.TimeStamper(fmt="%Y-%m-%d %H:%M.%S", utc=False),
            structlog.processors.StackInfoRenderer(),
            structlog.processors.UnicodeDecoder(),
            structlog.stdlib.ProcessorFormatter.wrap_for_formatter,
        ],
        logger_factory=structlog.stdlib.LoggerFactory(),
        wrapper_class=structlog.stdlib.BoundLogger,
        cache_logger_on_first_use=True,
    )
    handler_stdout = logging.StreamHandler(sys.stdout)
    handler_stdout.setFormatter(structlog.stdlib.ProcessorFormatter(processor=ConsoleRenderer()))

    handler_file = logging.FileHandler("application.log")
    handler_file.setFormatter(structlog.stdlib.ProcessorFormatter(processor=JSONRenderer()))

    root_logger = logging.getLogger()
    root_logger.addHandler(handler_stdout)
    root_logger.addHandler(handler_file)
