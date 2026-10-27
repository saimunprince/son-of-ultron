import os
import sys
from datetime import datetime

from loguru import logger as _logger

from app.config import PROJECT_ROOT


_print_level = "INFO"


def _testing() -> bool:
    """A pytest process, or a process a test started (PYTEST_CURRENT_TEST is inherited)."""
    return "pytest" in sys.modules or bool(os.environ.get("PYTEST_CURRENT_TEST"))


def define_log_level(print_level="INFO", logfile_level="DEBUG", name: str = None):
    """Adjust the log level to above level"""
    global _print_level
    _print_level = print_level

    current_date = datetime.now()
    formatted_date = current_date.strftime("%Y%m%d%H%M%S")
    log_name = (
        f"{name}_{formatted_date}" if name else formatted_date
    )  # name a log with prefix name

    _logger.remove()
    _logger.add(sys.stderr, level=print_level)
    # Not from tests: every pytest process left a logs/<timestamp>.log in the production backend/logs (2,699
    # files, most of them empty), and fake-brain tracebacks there read like production failures. The server's
    # file is created on its first line (delay), so a process that logs nothing leaves no empty file.
    if not _testing():
        _logger.add(PROJECT_ROOT / f"logs/{log_name}.log", level=logfile_level, delay=True)
    return _logger


logger = define_log_level()


if __name__ == "__main__":
    logger.info("Starting application")
    logger.debug("Debug message")
    logger.warning("Warning message")
    logger.error("Error message")
    logger.critical("Critical message")

    try:
        raise ValueError("Test error")
    except Exception as e:
        logger.exception(f"An error occurred: {e}")
