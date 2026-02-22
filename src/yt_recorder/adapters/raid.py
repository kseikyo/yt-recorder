from __future__ import annotations

import logging
from pathlib import Path
from typing import Callable

from yt_recorder.adapters.youtube import YouTubeBrowserAdapter
from yt_recorder.domain.models import UploadResult, YouTubeAccount

logger = logging.getLogger(__name__)


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
        adapter_factory: Callable[[YouTubeAccount], YouTubeBrowserAdapter] | None = None,
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
            lambda acct: YouTubeBrowserAdapter(acct, headless, delays)
        )
        self._adapters: dict[str, YouTubeBrowserAdapter] = {}

    def open(self) -> None:
        """Launch browsers for all accounts once."""
        for acct in [self.primary, *self.mirrors]:
            adapter = self._factory(acct)
            adapter.open()
            self._adapters[acct.name] = adapter

    def close(self) -> None:
        """Close all browsers, refresh cookies."""
        for adapter in self._adapters.values():
            adapter.close()
        self._adapters.clear()

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
        self, path: Path, title: str, playlist: str
    ) -> tuple[dict[str, UploadResult | None], int]:
        """Upload to all accounts.

        Primary first (must succeed). Mirrors best-effort (failures logged as None).

        Args:
            path: Path to video file
            title: Video title
            playlist: Playlist name to assign

        Returns:
            Tuple of (account results dict, playlist_failures count).
        """
        results: dict[str, UploadResult | None] = {}
        playlist_failures = 0

        primary_adapter = self._adapters[self.primary.name]
        primary_result = primary_adapter.upload(path, title)
        results[self.primary.name] = primary_result
        playlist_ok = primary_adapter.assign_playlist(primary_result.video_id, playlist)
        if not playlist_ok:
            logger.warning("Playlist assignment failed for %s on %s", playlist, self.primary.name)
            playlist_failures += 1

        for mirror in self.mirrors:
            try:
                mirror_adapter = self._adapters[mirror.name]
                mirror_result = mirror_adapter.upload(path, title)
                results[mirror.name] = mirror_result
                playlist_ok = mirror_adapter.assign_playlist(mirror_result.video_id, playlist)
                if not playlist_ok:
                    logger.warning("Playlist assignment failed for %s on %s", playlist, mirror.name)
                    playlist_failures += 1
            except Exception as e:
                logger.warning("Mirror %s failed: %s", mirror.name, e)
                results[mirror.name] = None

        return results, playlist_failures
