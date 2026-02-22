from __future__ import annotations

from pathlib import Path
from unittest.mock import Mock, patch

import pytest

from yt_recorder.adapters.youtube import YouTubeBrowserAdapter
from yt_recorder.domain.exceptions import (
    BotDetectionError,
    SelectorChangedError,
    SessionExpiredError,
)
from yt_recorder.domain.models import UploadResult, YouTubeAccount


@pytest.fixture
def youtube_account() -> YouTubeAccount:
    return YouTubeAccount(
        name="primary",
        storage_state=Path("/tmp/storage_state.json"),
        cookies_path=Path("/tmp/cookies.txt"),
        role="primary",
    )


@pytest.fixture
def adapter(youtube_account: YouTubeAccount) -> YouTubeBrowserAdapter:
    delays = {
        "field": (0.1, 0.2),
        "nav": (0.1, 0.2),
        "post": (0.1, 0.2),
    }
    return YouTubeBrowserAdapter(youtube_account, headless=True, delays=delays)


class TestYouTubeBrowserAdapterInit:
    def test_init_stores_account(
        self, adapter: YouTubeBrowserAdapter, youtube_account: YouTubeAccount
    ) -> None:
        assert adapter.account == youtube_account

    def test_init_stores_headless(self, adapter: YouTubeBrowserAdapter) -> None:
        assert adapter.headless is True

    def test_init_stores_delays(self, adapter: YouTubeBrowserAdapter) -> None:
        assert "field" in adapter.delays
        assert "nav" in adapter.delays
        assert "post" in adapter.delays

    def test_init_browser_none(self, adapter: YouTubeBrowserAdapter) -> None:
        assert adapter.browser is None

    def test_init_context_none(self, adapter: YouTubeBrowserAdapter) -> None:
        assert adapter.context is None


class TestRandomDelay:
    def test_random_delay_applies_delay(self, adapter: YouTubeBrowserAdapter) -> None:
        with patch("time.sleep") as mock_sleep:
            adapter._random_delay("field")
            mock_sleep.assert_called_once()
            call_args = mock_sleep.call_args[0][0]
            assert 0.1 <= call_args <= 0.2

    def test_random_delay_unknown_action_type(self, adapter: YouTubeBrowserAdapter) -> None:
        with patch("time.sleep") as mock_sleep:
            adapter._random_delay("unknown")
            mock_sleep.assert_not_called()


class TestCheckBotDetection:
    def test_check_bot_detection_no_captcha(self, adapter: YouTubeBrowserAdapter) -> None:
        mock_page = Mock()
        mock_page.query_selector.return_value = None
        adapter._check_bot_detection(mock_page)

    def test_check_bot_detection_captcha_found(self, adapter: YouTubeBrowserAdapter) -> None:
        mock_page = Mock()
        mock_page.query_selector.return_value = Mock()
        with pytest.raises(BotDetectionError):
            adapter._check_bot_detection(mock_page)


class TestCheckSessionExpired:
    def test_check_session_expired_normal_url(self, adapter: YouTubeBrowserAdapter) -> None:
        mock_page = Mock()
        mock_page.url = "https://www.youtube.com/upload"
        adapter._check_session_expired(mock_page)

    def test_check_session_expired_google_accounts_url(
        self, adapter: YouTubeBrowserAdapter
    ) -> None:
        mock_page = Mock()
        mock_page.url = "https://accounts.google.com/signin"
        with pytest.raises(SessionExpiredError):
            adapter._check_session_expired(mock_page)


class TestOpen:
    @patch("yt_recorder.adapters.youtube._find_chrome")
    @patch("yt_recorder.adapters.youtube.sync_playwright")
    def test_open_launches_browser(
        self, mock_sync_playwright: Mock, mock_find_chrome: Mock, adapter: YouTubeBrowserAdapter
    ) -> None:
        mock_playwright = Mock()
        mock_browser = Mock()
        mock_context = Mock()
        mock_chrome_path = "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome"

        mock_find_chrome.return_value = mock_chrome_path
        mock_sync_playwright.return_value.start.return_value = mock_playwright
        mock_playwright.chromium.launch.return_value = mock_browser
        mock_browser.new_context.return_value = mock_context

        adapter.open()

        assert adapter.browser == mock_browser
        assert adapter.context == mock_context
        assert adapter._playwright == mock_playwright
        mock_playwright.chromium.launch.assert_called_once_with(
            headless=True, executable_path=mock_chrome_path
        )


class TestClose:
    def test_close_saves_storage_state(self, adapter: YouTubeBrowserAdapter) -> None:
        mock_context = Mock()
        mock_browser = Mock()
        mock_playwright = Mock()

        adapter.context = mock_context
        adapter.browser = mock_browser
        adapter._playwright = mock_playwright

        with patch("os.chmod"):
            adapter.close()

        mock_context.storage_state.assert_called_once()
        mock_context.close.assert_called_once()
        mock_browser.close.assert_called_once()
        mock_playwright.stop.assert_called_once()

    def test_close_no_context(self, adapter: YouTubeBrowserAdapter) -> None:
        adapter.context = None
        adapter.browser = Mock()
        mock_playwright = Mock()
        adapter._playwright = mock_playwright
        adapter.close()
        adapter.browser.close.assert_called_once()
        mock_playwright.stop.assert_called_once()

    def test_close_no_playwright(self, adapter: YouTubeBrowserAdapter) -> None:
        adapter.context = Mock()
        adapter.browser = Mock()
        adapter._playwright = None
        with patch("os.chmod"):
            adapter.close()
        adapter.context.storage_state.assert_called_once()
        adapter.context.close.assert_called_once()
        adapter.browser.close.assert_called_once()


class TestUpload:
    def test_upload_no_context_raises_error(self, adapter: YouTubeBrowserAdapter) -> None:
        with pytest.raises(RuntimeError, match="Browser not opened"):
            adapter.upload(Path("/tmp/video.mp4"), "Test Video")

    def test_upload_session_expired(self, adapter: YouTubeBrowserAdapter) -> None:
        mock_context = Mock()
        mock_page = Mock()
        mock_page.url = "https://accounts.google.com/signin"

        mock_context.new_page.return_value = mock_page

        adapter.context = mock_context

        with pytest.raises(SessionExpiredError):
            adapter.upload(Path("/tmp/video.mp4"), "Test Video")

    def test_upload_bot_detection(self, adapter: YouTubeBrowserAdapter) -> None:
        mock_context = Mock()
        mock_page = Mock()
        mock_page.url = "https://www.youtube.com/upload"

        def query_selector_side_effect(selector: str) -> Mock | None:
            if selector == "iframe[src*='recaptcha'], div#captcha-container":
                return Mock()
            return None

        mock_page.query_selector.side_effect = query_selector_side_effect
        mock_context.new_page.return_value = mock_page

        adapter.context = mock_context

        with pytest.raises(BotDetectionError):
            adapter.upload(Path("/tmp/video.mp4"), "Test Video")

    def test_upload_file_input_not_found(self, adapter: YouTubeBrowserAdapter) -> None:
        mock_context = Mock()
        mock_page = Mock()
        mock_page.url = "https://www.youtube.com/upload"

        def query_selector_side_effect(selector: str) -> Mock | None:
            if selector == "iframe[src*='recaptcha'], div#captcha-container":
                return None
            return None

        mock_page.query_selector.side_effect = query_selector_side_effect
        mock_page.wait_for_selector.side_effect = TimeoutError("Selector not found")
        mock_context.new_page.return_value = mock_page

        adapter.context = mock_context

        with pytest.raises(SelectorChangedError, match="File input selector"):
            adapter.upload(Path("/tmp/video.mp4"), "Test Video")

    def test_upload_success(self, adapter: YouTubeBrowserAdapter) -> None:
        mock_context = Mock()
        mock_page = Mock()
        mock_page.url = "https://www.youtube.com/upload"

        mock_file_input = Mock()
        mock_title_input = Mock()
        mock_not_for_kids = Mock()
        mock_next_btn = Mock()
        mock_private_radio = Mock()
        mock_video_url_elem = Mock()
        mock_done_btn = Mock()

        mock_video_url_elem.get_attribute.return_value = "https://youtu.be/abc123"

        def query_selector_side_effect(selector: str) -> Mock | None:
            if selector == "#title-textarea #textbox":
                return mock_title_input
            elif selector == 'tp-yt-paper-radio-button[name="VIDEO_MADE_FOR_KIDS_NOT_MFK"]':
                return mock_not_for_kids
            elif selector == "#next-button":
                return mock_next_btn
            elif selector == 'tp-yt-paper-radio-button[name="PRIVATE"]':
                return mock_private_radio
            elif selector == "span.video-url-fadeable a":
                return mock_video_url_elem
            elif selector == "#done-button":
                return mock_done_btn
            elif selector == "iframe[src*='recaptcha'], div#captcha-container":
                return None
            return None

        def wait_for_selector_side_effect(selector: str, **kwargs: object) -> Mock | None:
            if selector == "ytcp-uploads-file-picker":
                return Mock()
            elif selector == 'input[type="file"]':
                return mock_file_input
            return None

        mock_page.query_selector.side_effect = query_selector_side_effect
        mock_page.wait_for_selector.side_effect = wait_for_selector_side_effect
        mock_context.new_page.return_value = mock_page

        adapter.context = mock_context

        result = adapter.upload(Path("/tmp/video.mp4"), "Test Video")

        assert isinstance(result, UploadResult)
        assert result.video_id == "abc123"
        assert result.url == "https://youtu.be/abc123"
        assert result.title == "Test Video"
        assert result.account_name == "primary"


class TestAssignPlaylist:
    def test_assign_playlist_no_context_raises_error(self, adapter: YouTubeBrowserAdapter) -> None:
        with pytest.raises(RuntimeError, match="Browser not opened"):
            adapter.assign_playlist("abc123", "my-playlist")

    def test_assign_playlist_session_expired(self, adapter: YouTubeBrowserAdapter) -> None:
        mock_context = Mock()
        mock_page = Mock()
        mock_page.url = "https://accounts.google.com/signin"

        mock_context.new_page.return_value = mock_page

        adapter.context = mock_context

        with pytest.raises(SessionExpiredError):
            adapter.assign_playlist("abc123", "my-playlist")

    def test_assign_playlist_success(self, adapter: YouTubeBrowserAdapter) -> None:
        mock_context = Mock()
        mock_page = Mock()
        mock_page.url = "https://studio.youtube.com/video/abc123/edit"

        mock_playlist_dropdown = Mock()
        mock_playlist_option = Mock()
        mock_save_btn = Mock()

        def query_selector_side_effect(selector: str) -> Mock | None:
            if "Playlist" in selector:
                return mock_playlist_dropdown
            elif "my-playlist" in selector:
                return mock_playlist_option
            elif "Save" in selector:
                return mock_save_btn
            elif selector == "iframe[src*='recaptcha'], div#captcha-container":
                return None
            return None

        mock_page.query_selector.side_effect = query_selector_side_effect
        mock_context.new_page.return_value = mock_page

        adapter.context = mock_context

        adapter.assign_playlist("abc123", "my-playlist")

        mock_page.goto.assert_called_once()
        mock_playlist_dropdown.click.assert_called_once()
        mock_playlist_option.click.assert_called_once()
        mock_save_btn.click.assert_called_once()
