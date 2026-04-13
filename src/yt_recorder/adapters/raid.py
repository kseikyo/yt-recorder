from __future__ import annotations

import logging
import time
from pathlib import Path
from typing import Callable, TypeVar

from playwright.sync_api import Browser, Playwright, sync_playwright
from playwright.sync_api import TimeoutError as PlaywrightTimeoutError

from yt_recorder.adapters.youtube import YouTubeBrowserAdapter
from yt_recorder.domain.exceptions import (
    BotDetectionError,
    ChannelCreationRequiredError,
    DailyLimitError,
    PhoneVerificationRequiredError,
    UploadTimeoutError,
    VideoTooLongError,
)
from yt_recorder.domain.models import UploadResult, YouTubeAccount
from yt_recorder.log import log_context
from yt_recorder.utils import find_chrome

logger = logging.getLogger(__name__)

_T = TypeVar("_T")

# Backoff schedule for transient failures. Total worst-case added latency: ~5s.
_RETRY_BACKOFFS_SECS: tuple[float, ...] = (1.0, 4.0)

# Exceptions considered transient (retry worthwhile). Anything else propagates.
_TRANSIENT_EXCEPTIONS: tuple[type[Exception], ...] = (
    PlaywrightTimeoutError,
    UploadTimeoutError,
)


def _retry_transient(op: str, fn: Callable[[], _T]) -> _T:
    """Call ``fn`` with transient-failure retries.

    Retries on ``_TRANSIENT_EXCEPTIONS``. Business/account exceptions
    (phone verification, daily limit, bot detection, channel creation,
    selector changes, etc.) are NOT retried — they propagate on first raise.
    """
    last_exc: Exception | None = None
    for attempt_idx, backoff in enumerate((0.0, *_RETRY_BACKOFFS_SECS)):
        if backoff > 0.0:
            logger.warning(
                "retrying transient failure",
                extra={
                    "event": "retry_transient",
                    "op": op,
                    "attempt": attempt_idx + 1,
                    "backoff_secs": backoff,
                },
            )
            time.sleep(backoff)
        try:
            return fn()
        except _TRANSIENT_EXCEPTIONS as exc:
            last_exc = exc
            continue
    assert last_exc is not None
    raise last_exc


class RaidAdapter:
    """Multi-account multiplexer. Primary-first, mirrors best-effort.

    Uses sync Playwright API. Browser contexts opened/closed at session level.
    NOTE: File deletion is NOT this adapter's concern — pipeline handles it.
    """

    def __init__(
        self,
        accounts: list[YouTubeAccount],
        headless: bool,
        delays: dict[str, tuple[float, float]],
        adapter_factory: Callable[[YouTubeAccount, Browser], YouTubeBrowserAdapter] | None = None,
    ):
        if not accounts:
            raise ValueError("No accounts configured. Run: yt-recorder setup --account <name>")
        primary = [a for a in accounts if a.role == "primary"]
        if not primary:
            raise ValueError(
                "No primary account found. The first configured account is used as primary."
            )
        self.primary = primary[0]
        self.mirrors = [a for a in accounts if a.role == "mirror"]
        self.headless = headless
        self.delays = delays
        self._factory = adapter_factory or (
            lambda acct, browser: YouTubeBrowserAdapter(acct, browser, delays)
        )
        self._adapters: dict[str, YouTubeBrowserAdapter] = {}
        self._playwright: Playwright | None = None
        self._browser: Browser | None = None

    def open(self) -> None:
        """Launch browsers for all accounts once."""
        self._playwright = sync_playwright().start()
        chrome_path = find_chrome()
        self._browser = self._playwright.chromium.launch(
            headless=self.headless, executable_path=chrome_path
        )
        for acct in [self.primary, *self.mirrors]:
            adapter = self._factory(acct, self._browser)
            adapter.open()
            self._adapters[acct.name] = adapter

    def close(self) -> None:
        """Close all browsers, refresh cookies."""
        for adapter in self._adapters.values():
            adapter.close()
        self._adapters.clear()
        if self._browser:
            self._browser.close()
        if self._playwright:
            self._playwright.stop()

    def get_adapter(self, account_name: str) -> YouTubeBrowserAdapter:
        """Get adapter for specific account.

        Args:
            account_name: Name of the account

        Returns:
            YouTubeBrowserAdapter for the account

        Raises:
            ValueError: If account not found
        """
        adapter = self._adapters.get(account_name)
        if not adapter:
            available = list(self._adapters.keys())
            raise ValueError(f"Account '{account_name}' not found. Available: {available}")
        return adapter

    def upload(
        self, path: Path, title: str, playlist: str, description: str = ""
    ) -> tuple[dict[str, UploadResult | None], int]:
        """Upload to all accounts.

        Primary first (must succeed). Mirrors best-effort (failures logged as None).
        DailyLimitError from mirrors is caught and logged; from primary it propagates.
        VideoTooLongError propagates for both primary and mirrors.

        Args:
            path: Path to video file
            title: Video title
            playlist: Playlist name to assign
            description: Optional video description

        Returns:
            Tuple of (account results dict, playlist_failures count).
        """
        results: dict[str, UploadResult | None] = {}
        playlist_failures = 0

        with log_context(raid_op="upload", account=self.primary.name):
            primary_adapter = self._adapters[self.primary.name]
            primary_result = _retry_transient(
                "primary_upload",
                lambda: primary_adapter.upload(path, title, description=description),
            )
            results[self.primary.name] = primary_result
            playlist_ok = _retry_transient(
                "primary_assign_playlist",
                lambda: primary_adapter.assign_playlist(primary_result.video_id, playlist),
            )
            if not playlist_ok:
                logger.warning(
                    "playlist assign failed",
                    extra={"event": "playlist_assign_failed", "playlist": playlist},
                )
                playlist_failures += 1

        for mirror in self.mirrors:
            with log_context(raid_op="upload", account=mirror.name, mirror=True):
                try:
                    mirror_adapter = self._adapters[mirror.name]

                    def _do_mirror_upload(
                        a: YouTubeBrowserAdapter = mirror_adapter,
                    ) -> UploadResult:
                        return a.upload(path, title, description=description)

                    mirror_result = _retry_transient("mirror_upload", _do_mirror_upload)
                    results[mirror.name] = mirror_result

                    def _do_mirror_playlist(
                        a: YouTubeBrowserAdapter = mirror_adapter,
                        v: str = mirror_result.video_id,
                    ) -> bool:
                        return a.assign_playlist(v, playlist)

                    playlist_ok = _retry_transient(
                        "mirror_assign_playlist", _do_mirror_playlist
                    )
                    if not playlist_ok:
                        logger.warning(
                            "playlist assign failed",
                            extra={"event": "playlist_assign_failed", "playlist": playlist},
                        )
                        playlist_failures += 1
                except DailyLimitError:
                    logger.warning(
                        "mirror daily limit reached",
                        extra={"event": "mirror_daily_limit"},
                    )
                    results[mirror.name] = None
                except VideoTooLongError:
                    raise
                except (
                    PlaywrightTimeoutError,
                    UploadTimeoutError,
                    PhoneVerificationRequiredError,
                    ChannelCreationRequiredError,
                    BotDetectionError,
                ):
                    logger.warning(
                        "mirror upload failed (transient/account-specific)",
                        exc_info=True,
                        extra={"event": "mirror_upload_failed"},
                    )
                    results[mirror.name] = None

        return results, playlist_failures

    def upload_to_account(
        self, account_name: str, path: Path, title: str, description: str = ""
    ) -> UploadResult:
        """Upload to a specific account. Used by pipeline for per-account split parts.

        Args:
            account_name: Name of the account to upload to
            path: Path to video file
            title: Video title
            description: Optional video description

        Returns:
            UploadResult for the uploaded video

        Raises:
            VideoTooLongError: If video exceeds account's duration limit
            DailyLimitError: If daily upload limit reached
            ValueError: If account not found
        """
        with log_context(raid_op="upload_to_account", account=account_name):
            adapter = self._adapters[account_name]
            return _retry_transient(
                "upload_to_account",
                lambda: adapter.upload(path, title, description=description),
            )

    def assign_playlist_to_account(self, account_name: str, video_id: str, playlist: str) -> bool:
        """Assign playlist on specific account.

        Args:
            account_name: Name of the account
            video_id: YouTube video ID
            playlist: Playlist name to assign

        Returns:
            True if assignment succeeded, False otherwise

        Raises:
            ValueError: If account not found
        """
        adapter = self._adapters[account_name]
        return adapter.assign_playlist(video_id, playlist)
