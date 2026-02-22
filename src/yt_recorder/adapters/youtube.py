from __future__ import annotations

import logging
import os
import platform
import random
import shutil
import time
from pathlib import Path

from playwright.sync_api import Browser, BrowserContext, Page, Playwright, sync_playwright

from yt_recorder import constants
from yt_recorder.domain.exceptions import (
    BotDetectionError,
    SelectorChangedError,
    SessionExpiredError,
    UploadTimeoutError,
)
from yt_recorder.domain.models import UploadResult, YouTubeAccount
from yt_recorder.utils import find_chrome

logger = logging.getLogger(__name__)


class YouTubeBrowserAdapter:
    def __init__(
        self,
        account: YouTubeAccount,
        headless: bool,
        delays: dict[str, tuple[float, float]],
    ) -> None:
        self.account = account
        self.headless = headless
        self.delays = delays
        self.browser: Browser | None = None
        self.context: BrowserContext | None = None
        self._playwright: Playwright | None = None

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

    def _check_session_expired(self, page: Page) -> None:
        if "accounts.google.com" in page.url:
            raise SessionExpiredError("Session expired, redirected to login")

    def open(self) -> None:
        chrome_path = find_chrome()
        self._playwright = sync_playwright().start()
        self.browser = self._playwright.chromium.launch(
            headless=self.headless,
            executable_path=chrome_path,
        )
        self.context = self.browser.new_context(storage_state=str(self.account.storage_state))

    def close(self) -> None:
        if self.context:
            self.context.storage_state(path=str(self.account.storage_state))
            os.chmod(str(self.account.storage_state), 0o600)
            self.context.close()
        if self.browser:
            self.browser.close()
        if self._playwright:
            self._playwright.stop()

    def upload(self, path: Path, title: str) -> UploadResult:
        if not self.context:
            raise RuntimeError("Browser not opened. Call open() first.")

        page = self.context.new_page()
        try:
            page.goto(constants.UPLOAD_URL, wait_until="domcontentloaded")
            self._check_session_expired(page)
            self._check_bot_detection(page)

            self._random_delay("nav")

            try:
                page.wait_for_selector("ytcp-uploads-file-picker", timeout=15000)
                file_input = page.wait_for_selector(
                    constants.FILE_INPUT, state="attached", timeout=5000
                )
            except TimeoutError as e:
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

            self._random_delay("field")

            not_for_kids = page.query_selector(constants.NOT_MADE_FOR_KIDS)
            if not not_for_kids:
                raise SelectorChangedError("Not made for kids selector not found")
            not_for_kids.click()

            self._random_delay("nav")

            for _ in range(3):
                next_btn = page.query_selector(constants.NEXT_BUTTON)
                if not next_btn:
                    raise SelectorChangedError("Next button selector not found")
                next_btn.click()
                self._random_delay("nav")

            private_radio = page.query_selector(constants.PRIVATE_RADIO)
            if not private_radio:
                raise SelectorChangedError("Private radio selector not found")
            private_radio.click()

            self._random_delay("field")

            video_url_elem = page.query_selector(constants.VIDEO_URL_ELEMENT)
            if not video_url_elem:
                raise SelectorChangedError("Video URL element not found")
            video_url = video_url_elem.get_attribute("href")
            if not video_url:
                raise SelectorChangedError("Video URL attribute not found")

            video_id = video_url.split("/")[-1].split("?")[0]

            # Wait for file upload to finish (Done button becomes enabled)
            try:
                page.wait_for_function(
                    """() => {
                        const done = document.querySelector('#done-button');
                        if (!done) return false;
                        return done.getAttribute('aria-disabled') !== 'true';
                    }""",
                    timeout=constants.UPLOAD_TIMEOUT_SECONDS * 1000,
                )
            except TimeoutError as e:
                raise UploadTimeoutError(
                    f"Upload exceeded {constants.UPLOAD_TIMEOUT_SECONDS}s timeout"
                ) from e

            done_btn = page.query_selector(constants.DONE_BUTTON)
            if not done_btn:
                raise SelectorChangedError("Done button selector not found")
            done_btn.click()

            self._random_delay("post")

            # Wait for upload dialog to close after publishing
            try:
                page.wait_for_selector("ytcp-uploads-dialog", state="hidden", timeout=60000)
            except TimeoutError:
                logger.warning("Upload dialog did not close, but video was published")

            return UploadResult(
                video_id=video_id,
                url=video_url,
                title=title,
                account_name=self.account.name,
            )
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

            self._random_delay("nav")

            playlist_dropdown = page.query_selector(constants.PLAYLIST_DROPDOWN)
            if not playlist_dropdown:
                logger.warning("Playlist dropdown not found for video %s", video_id)
                return False

            playlist_dropdown.click()
            self._random_delay("field")

            playlist_option = page.query_selector(
                constants.PLAYLIST_OPTION_TEMPLATE.format(name=playlist_name)
            )
            if not playlist_option:
                logger.warning("Playlist '%s' not found for video %s", playlist_name, video_id)
                return False

            playlist_option.click()
            self._random_delay("field")

            save_btn = page.query_selector(constants.PLAYLIST_SAVE)
            if not save_btn:
                logger.warning("Save button not found for video %s", video_id)
                return False

            save_btn.click()
            self._random_delay("post")
            return True
        finally:
            page.close()
