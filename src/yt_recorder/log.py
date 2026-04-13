"""Logging setup for yt-recorder.

Thin wrapper around structlog. Keeps all structlog imports in one place so the
call-site contract (stdlib ``logging.getLogger(__name__)`` + ``log_context``)
stays stable if we ever swap the backing library.
"""

from __future__ import annotations

import logging
import logging.handlers
import os
import stat
from pathlib import Path
from typing import Any

import structlog
from structlog.contextvars import (
    bind_contextvars,
    bound_contextvars,
    clear_contextvars,
    unbind_contextvars,
)
from structlog.stdlib import ProcessorFormatter

# Log records carry filepaths, video IDs, account names, and exception stacks
# (via dict_tracebacks). Treat the on-disk JSONL as sensitive: owner-only.
_LOG_FILE_MODE = 0o600
_LOG_DIR_MODE = 0o700
_LOG_MAX_BYTES = 10 * 1024 * 1024  # 10 MB per file
_LOG_BACKUP_COUNT = 5

__all__ = [
    "bind_contextvars",
    "clear_contextvars",
    "configure_logging",
    "default_log_dir",
    "log_context",
    "unbind_contextvars",
]

# Scope-level context binding. Usage: `with log_context(filepath=str(path)): ...`
# Every log record emitted inside the `with` block (from structlog or stdlib
# `logging.getLogger(...)` alike) inherits the bound fields via
# ``merge_contextvars`` in the processor chain.
log_context = bound_contextvars


class _OwnerOnlyRotatingFileHandler(logging.handlers.RotatingFileHandler):
    """RotatingFileHandler that chmods every (rotated) log file to 0o600.

    The base class creates rotated backups via ``os.rename``, inheriting
    whatever perms the original file had. We chmod after open and after
    every rollover so leaked rotated files don't downgrade to umask defaults.
    """

    def _open(self):  # type: ignore[no-untyped-def]
        stream = super()._open()
        try:
            os.chmod(self.baseFilename, _LOG_FILE_MODE)
        except OSError:
            pass
        return stream

    def doRollover(self) -> None:  # noqa: N802
        super().doRollover()
        for i in range(1, self.backupCount + 1):
            rotated = Path(f"{self.baseFilename}.{i}")
            if rotated.exists():
                try:
                    os.chmod(rotated, _LOG_FILE_MODE)
                except OSError:
                    pass


def _ensure_owner_only_dir(path: Path) -> None:
    """mkdir -p with 0o700, and chmod existing dirs that are looser."""
    path.mkdir(parents=True, exist_ok=True)
    try:
        current = stat.S_IMODE(path.stat().st_mode)
        if current != _LOG_DIR_MODE:
            os.chmod(path, _LOG_DIR_MODE)
    except OSError:
        pass


def default_log_dir() -> Path:
    """Log directory inside the platform-appropriate config dir.

    Reuses :func:`yt_recorder.config.Config.default_config_dir` so logs sit
    next to ``config.toml`` and the per-account credential files. On macOS
    that's ``~/Library/Application Support/yt-recorder/logs``; on Linux
    ``$XDG_CONFIG_HOME/yt-recorder/logs`` (or ``~/.config/yt-recorder/logs``).
    """
    from yt_recorder.config import Config

    return Config.default_config_dir() / "logs"


def configure_logging(verbose: bool) -> Path:
    """Install stderr (human) + JSONL file sink. Returns the log file path."""
    log_dir = default_log_dir()
    _ensure_owner_only_dir(log_dir)
    log_file = log_dir / "yt-recorder.jsonl"

    timestamper = structlog.processors.TimeStamper(fmt="iso", utc=True)

    # Shared pre-chain: applied to records originating from BOTH structlog
    # callers and plain stdlib ``logging.getLogger(...)`` callers.
    pre_chain: list[Any] = [
        structlog.contextvars.merge_contextvars,
        structlog.stdlib.add_log_level,
        structlog.stdlib.add_logger_name,
        timestamper,
    ]

    structlog.configure(
        processors=[
            *pre_chain,
            structlog.stdlib.filter_by_level,
            structlog.processors.StackInfoRenderer(),
            structlog.processors.format_exc_info,
            ProcessorFormatter.wrap_for_formatter,
        ],
        logger_factory=structlog.stdlib.LoggerFactory(),
        wrapper_class=structlog.stdlib.BoundLogger,
        cache_logger_on_first_use=True,
    )

    stderr = logging.StreamHandler()
    stderr.setLevel(logging.DEBUG if verbose else logging.WARNING)
    stderr.setFormatter(
        ProcessorFormatter(
            foreign_pre_chain=pre_chain,
            processors=[
                ProcessorFormatter.remove_processors_meta,
                structlog.dev.ConsoleRenderer(colors=True),
            ],
        )
    )

    json_handler = _OwnerOnlyRotatingFileHandler(
        log_file,
        maxBytes=_LOG_MAX_BYTES,
        backupCount=_LOG_BACKUP_COUNT,
        encoding="utf-8",
    )
    json_handler.setLevel(logging.DEBUG)
    json_handler.setFormatter(
        ProcessorFormatter(
            foreign_pre_chain=pre_chain,
            processors=[
                ProcessorFormatter.remove_processors_meta,
                structlog.processors.dict_tracebacks,
                structlog.processors.JSONRenderer(),
            ],
        )
    )

    root = logging.getLogger()
    root.handlers.clear()
    root.setLevel(logging.DEBUG)
    root.addHandler(stderr)
    root.addHandler(json_handler)
    return log_file
