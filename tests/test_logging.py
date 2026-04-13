"""Tests for yt_recorder.log — context binding + JSONL sink."""

from __future__ import annotations

import json
import logging
from pathlib import Path

import pytest
import structlog
from structlog.contextvars import clear_contextvars

from yt_recorder import log as yt_log


@pytest.fixture(autouse=True)
def _reset_contextvars() -> None:
    clear_contextvars()
    yield
    clear_contextvars()


@pytest.fixture
def configured(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    monkeypatch.setattr(yt_log, "default_log_dir", lambda: tmp_path)
    log_file = yt_log.configure_logging(verbose=True)
    yield log_file
    # Detach handlers to avoid leaking into other tests
    root = logging.getLogger()
    for h in list(root.handlers):
        root.removeHandler(h)
        h.close()


def _read_jsonl(path: Path) -> list[dict[str, object]]:
    return [json.loads(line) for line in path.read_text().splitlines() if line.strip()]


class TestLogContext:
    def test_bound_field_appears_on_stdlib_record(self, configured: Path) -> None:
        log = logging.getLogger("test.stdlib")
        with yt_log.log_context(filepath="a.mp4"):
            log.info("hello", extra={"event": "t"})

        records = _read_jsonl(configured)
        assert len(records) == 1
        assert records[0]["filepath"] == "a.mp4"
        assert records[0]["event"] == "hello"  # structlog maps message to event

    def test_nested_contexts_merge(self, configured: Path) -> None:
        log = logging.getLogger("test.nested")
        with yt_log.log_context(filepath="a.mp4"):
            with yt_log.log_context(account="primary"):
                log.info("nested")

        records = _read_jsonl(configured)
        assert records[-1]["filepath"] == "a.mp4"
        assert records[-1]["account"] == "primary"

    def test_context_pops_on_exit(self, configured: Path) -> None:
        log = logging.getLogger("test.pop")
        with yt_log.log_context(filepath="a.mp4"):
            log.info("inside")
        log.info("outside")

        records = _read_jsonl(configured)
        assert records[0].get("filepath") == "a.mp4"
        assert "filepath" not in records[1]

    def test_bind_unbind_outside_with(self, configured: Path) -> None:
        log = logging.getLogger("test.manual")
        yt_log.bind_contextvars(file_index=3)
        log.info("mid")
        yt_log.unbind_contextvars("file_index")
        log.info("after")

        records = _read_jsonl(configured)
        assert records[0]["file_index"] == 3
        assert "file_index" not in records[1]


class TestJsonlSink:
    def test_file_created(self, configured: Path) -> None:
        assert configured.exists()
        assert configured.name == "yt-recorder.jsonl"

    def test_record_shape(self, configured: Path) -> None:
        log = logging.getLogger("test.shape")
        log.warning("something happened")

        records = _read_jsonl(configured)
        rec = records[0]
        assert "timestamp" in rec
        assert rec["level"] == "warning"
        assert rec["logger"] == "test.shape"
        assert rec["event"] == "something happened"

    def test_exception_serialized(self, configured: Path) -> None:
        log = logging.getLogger("test.exc")
        with yt_log.log_context(filepath="bad.mp4"):
            try:
                raise ValueError("boom")
            except ValueError:
                log.exception("caught")

        records = _read_jsonl(configured)
        rec = records[0]
        assert rec["filepath"] == "bad.mp4"
        assert rec["level"] == "error"
        # dict_tracebacks renders exceptions under the "exception" key as a list of frames
        assert "exception" in rec

    def test_structlog_native_logger_also_carries_context(self, configured: Path) -> None:
        slog = structlog.get_logger("test.native")
        with yt_log.log_context(filepath="native.mp4"):
            slog.info("native_event", extra_field=42)

        records = _read_jsonl(configured)
        rec = records[0]
        assert rec["filepath"] == "native.mp4"
        assert rec["extra_field"] == 42
