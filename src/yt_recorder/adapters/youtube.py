from __future__ import annotations

import logging
import os
import random
import time
from pathlib import Path

from playwright.sync_api import (
    Browser,
    BrowserContext,
    Page,
)
from playwright.sync_api import (
    TimeoutError as PlaywrightTimeoutError,
)

from yt_recorder import constants
from yt_recorder.domain.exceptions import (
    BotDetectionError,
    DailyLimitError,
    SelectorChangedError,
    SessionExpiredError,
    UnsupportedBrowserError,
    UploadTimeoutError,
    VerificationRequiredError,
    VideoTooLongError,
)
from yt_recorder.domain.models import UploadResult, YouTubeAccount

logger = logging.getLogger(__name__)


class YouTubeBrowserAdapter:
    def __init__(
        self,
        account: YouTubeAccount,
        browser: Browser,
        delays: dict[str, tuple[float, float]],
    ) -> None:
        self.account = account
        self.browser = browser
        self.delays = delays
        self.context: BrowserContext | None = None

    def _random_delay(self, action_type: str) -> None:
        if action_type not in self.delays:
            return
        min_delay, max_delay = self.delays[action_type]
        delay = random.uniform(min_delay, max_delay)
        time.sleep(delay)

    def _check_bot_detection(self, page: Page) -> None:
        captcha_elem = page.query_selector(constants.CAPTCHA_INDICATOR)
        if captcha_elem:
            raise BotDetectionError("CAPTCHA or challenge page detected")

    def _check_unsupported_browser(self, page: Page) -> None:
        indicator = page.query_selector(constants.UNSUPPORTED_BROWSER_INDICATOR)
        if indicator:
            raise UnsupportedBrowserError(
                "YouTube rejected browser as unsupported. Run: playwright install chromium"
            )

    def _check_verification_required(self, page: Page) -> None:
        if page.query_selector('text="Verify it\'s you"'):
            raise VerificationRequiredError(
                "Google requires identity verification. Run: yt-recorder setup --account <name>"
            )

    def _check_session_expired(self, page: Page) -> None:
        if "accounts.google.com" in page.url:
            raise SessionExpiredError("Session expired, redirected to login")

    def _wait_for_scrim_dismissed(self, page: Page, timeout: int = 10000) -> None:
        try:
            page.wait_for_selector(constants.DIALOG_SCRIM, state="hidden", timeout=timeout)
        except PlaywrightTimeoutError:
            self._check_verification_required(page)

    def open(self) -> None:
        self.context = self.browser.new_context(storage_state=str(self.account.storage_state))

    def close(self) -> None:
        if self.context:
            self.context.storage_state(path=str(self.account.storage_state))
            os.chmod(str(self.account.storage_state), 0o600)
            self.context.close()

    def upload(self, path: Path, title: str, description: str = "") -> UploadResult:
        if not self.context:
            raise RuntimeError("Browser not opened. Call open() first.")

        page = self.context.new_page()
        try:
            page.goto(constants.UPLOAD_URL, wait_until="domcontentloaded")
            self._check_session_expired(page)
            self._check_bot_detection(page)
            self._check_unsupported_browser(page)
            self._check_verification_required(page)

            self._random_delay("nav")

            try:
                page.wait_for_selector(constants.UPLOAD_FILE_PICKER, timeout=15000)
                file_input = page.wait_for_selector(
                    constants.FILE_INPUT, state="attached", timeout=5000
                )
            except PlaywrightTimeoutError as e:
                raise SelectorChangedError("File input selector not found") from e
            if not file_input:
                raise SelectorChangedError("File input selector not found")
            file_input.set_input_files(str(path))

            self._random_delay("field")

            page.wait_for_selector(constants.TITLE_INPUT, timeout=10000)
            title_input = page.query_selector(constants.TITLE_INPUT)
            if not title_input:
                raise SelectorChangedError("Title input selector not found")
            title_input.fill(title)

            if description:
                desc_box = page.locator(constants.DESCRIPTION_TEXTAREA)
                desc_box.fill(description)

            self._random_delay("field")

            not_for_kids = page.wait_for_selector(constants.NOT_MADE_FOR_KIDS, timeout=10000)
            if not not_for_kids:
                raise SelectorChangedError("Not made for kids selector not found")
            self._wait_for_scrim_dismissed(page)
            not_for_kids.click()

            self._random_delay("nav")

            self._wait_for_scrim_dismissed(page)
            for _ in range(3):
                next_btn = page.wait_for_selector(constants.NEXT_BUTTON, timeout=10000)
                if not next_btn:
                    raise SelectorChangedError("Next button selector not found")
                next_btn.click()
                self._random_delay("nav")

            self._wait_for_scrim_dismissed(page)
            private_radio = page.wait_for_selector(constants.PRIVATE_RADIO, timeout=10000)
            if not private_radio:
                raise SelectorChangedError("Private radio selector not found")
            private_radio.click()

            self._random_delay("field")

            video_url_elem = page.wait_for_selector(constants.VIDEO_URL_ELEMENT, timeout=10000)
            if not video_url_elem:
                raise SelectorChangedError("Video URL element not found")
            video_url = video_url_elem.get_attribute("href")
            if not video_url:
                raise SelectorChangedError("Video URL attribute not found")

            video_id = video_url.split("/")[-1].split("?")[0]

            # Wait for file upload to finish (Done button becomes enabled)
            try:
                handle = page.wait_for_function(
                    """() => {
                        const body = document.body;
                        if (!body) return null;
                        const text = body.innerText || '';
                        if (text.includes('Video is too long') || text.includes('video is too long')) {
                            return { error: 'too_long' };
                        }
                        if (text.includes('upload limit') || text.includes('daily upload') || text.includes('daily limit')) {
                            return { error: 'daily_limit' };
                        }
                        const done = document.querySelector('#done-button');
                        if (done && done.getAttribute('aria-disabled') !== 'true') {
                            return { done: true };
                        }
                        return null;
                    }""",
                    timeout=constants.UPLOAD_TIMEOUT_SECONDS * 1000,
                )
                result: object = handle.json_value() if handle is not None else None
            except PlaywrightTimeoutError as e:
                raise UploadTimeoutError(
                    f"Upload exceeded {constants.UPLOAD_TIMEOUT_SECONDS}s timeout"
                ) from e

            if isinstance(result, dict):
                if result.get("error") == "too_long":
                    raise VideoTooLongError("YouTube rejected video: too long for this account")
                if result.get("error") == "daily_limit":
                    raise DailyLimitError("YouTube daily upload limit reached")

            done_btn = page.query_selector(constants.DONE_BUTTON)
            if not done_btn:
                raise SelectorChangedError("Done button selector not found")
            done_btn.click()

            self._random_delay("post")

            # Wait for upload dialog to close after publishing
            try:
                page.wait_for_selector(constants.UPLOAD_DIALOG, state="hidden", timeout=60000)
            except PlaywrightTimeoutError:
                logger.warning("Upload dialog did not close, but video was published")

            return UploadResult(
                video_id=video_id,
                url=video_url,
                title=title,
                account_name=self.account.name,
            )
        except Exception:
            page.screenshot(path=f"/tmp/yt-recorder-debug-upload-{int(time.time())}.png")
            raise
        finally:
            page.close()

    def assign_playlist(self, video_id: str, playlist_name: str) -> bool:
        if not self.context:
            raise RuntimeError("Browser not opened. Call open() first.")

        page = self.context.new_page()
        try:
            edit_url = constants.STUDIO_EDIT_URL.format(video_id=video_id)
            page.goto(edit_url, wait_until="domcontentloaded")
            self._check_session_expired(page)
            self._check_bot_detection(page)
            self._check_unsupported_browser(page)
            self._check_verification_required(page)

            self._random_delay("nav")

            # Wait for page to fully load, click playlist trigger
            try:
                trigger = page.wait_for_selector(constants.PLAYLIST_TRIGGER, timeout=15000)
            except PlaywrightTimeoutError as e:
                raise SelectorChangedError("Playlist trigger not found") from e
            if not trigger:
                raise SelectorChangedError("Playlist trigger not found")
            trigger.click()
            self._random_delay("field")

            # Wait for playlist dialog to open
            try:
                search_input = page.wait_for_selector(
                    constants.PLAYLIST_SEARCH_INPUT, state="attached", timeout=5000
                )
            except PlaywrightTimeoutError as e:
                raise SelectorChangedError("Playlist dialog did not open") from e
            if not search_input:
                raise SelectorChangedError("Playlist search input not found")
            if not search_input.is_visible():
                logger.warning(
                    "Playlist search input hidden (account has no playlists) for video %s",
                    video_id,
                )
                return False

            # Type playlist name into search (handles special chars safely)
            search_input.fill(playlist_name)
            self._random_delay("field")

            # Wait for matching playlist item
            item_selector = constants.PLAYLIST_ITEM_TEMPLATE.format(name=playlist_name)
            try:
                playlist_item = page.wait_for_selector(item_selector, timeout=5000)
            except PlaywrightTimeoutError:
                logger.warning(
                    "Playlist '%s' not found for video %s",
                    playlist_name,
                    video_id,
                )
                return False
            if not playlist_item:
                logger.warning(
                    "Playlist '%s' not found for video %s",
                    playlist_name,
                    video_id,
                )
                return False
            playlist_item.click()
            self._random_delay("field")

            # Click done to close playlist dialog
            try:
                done_btn = page.wait_for_selector(constants.PLAYLIST_DONE, timeout=5000)
            except PlaywrightTimeoutError as e:
                raise SelectorChangedError("Playlist done button not found") from e
            if not done_btn:
                raise SelectorChangedError("Playlist done button not found")
            done_btn.click()
            self._random_delay("field")

            # Page-level save (required after dialog closes)
            try:
                save_btn = page.wait_for_selector(constants.PLAYLIST_PAGE_SAVE, timeout=5000)
            except PlaywrightTimeoutError as e:
                raise SelectorChangedError("Page save button not found") from e
            if not save_btn:
                raise SelectorChangedError("Page save button not found")
            save_btn.click()

            # Wait for save to complete (button becomes disabled)
            page.wait_for_function(
                """() => {
                    const btn = document.querySelector('ytcp-button#save');
                    if (!btn) return false;
                    return btn.getAttribute('aria-disabled') === 'true';
                }""",
                timeout=10000,
            )

            self._random_delay("post")
            return True
        except Exception:
            page.screenshot(path=f"/tmp/yt-recorder-debug-playlist-{video_id}.png")
            raise
        finally:
            page.close()
