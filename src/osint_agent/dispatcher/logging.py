import logging
import os
import sys
from pathlib import Path

_LOG_CONFIGURED = False


def get_log_dir() -> Path:
    return Path("~/.osint-agent").expanduser()


def setup_logging(verbose: bool = False, log_file: bool = True):
    global _LOG_CONFIGURED
    if _LOG_CONFIGURED:
        return

    level = logging.DEBUG if verbose else logging.INFO

    root = logging.getLogger("osint_agent")
    root.setLevel(level)

    fmt = logging.Formatter(
        "[%(asctime)s] %(levelname)-5s %(name)s: %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )

    handler = logging.StreamHandler(sys.stdout)
    handler.setLevel(level)
    handler.setFormatter(fmt)
    root.addHandler(handler)

    if log_file:
        log_dir = get_log_dir()
        log_dir.mkdir(parents=True, exist_ok=True)
        file_handler = logging.FileHandler(
            str(log_dir / "osint-agent.log"),
            encoding="utf-8",
        )
        file_handler.setLevel(logging.DEBUG)
        file_handler.setFormatter(fmt)
        root.addHandler(file_handler)

    _LOG_CONFIGURED = True


def get_logger(name: str) -> logging.Logger:
    return logging.getLogger("osint_agent.%s" % name)
