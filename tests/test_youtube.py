from __future__ import annotations

from pathlib import Path
from unittest.mock import Mock, patch

import pytest
from playwright.sync_api import TimeoutError as PlaywrightTimeoutError

from yt_recorder import constants
from yt_recorder.adapters.youtube import YouTubeBrowserAdapter
from yt_recorder.domain.exceptions import (
    BotDetectionError,
    SelectorChangedError,
    SessionExpiredError,
    UnsupportedBrowserError,
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
    mock_browser = Mock()
    return YouTubeBrowserAdapter(youtube_account, browser=mock_browser, delays=delays)


class TestYouTubeBrowserAdapterInit:
    def test_init_stores_account(
        self, adapter: YouTubeBrowserAdapter, youtube_account: YouTubeAccount
    ) -> None:
        assert adapter.account == youtube_account

    def test_init_stores_delays(self, adapter: YouTubeBrowserAdapter) -> None:
        assert "field" in adapter.delays
        assert "nav" in adapter.delays
        assert "post" in adapter.delays

    def test_init_stores_browser(self, adapter: YouTubeBrowserAdapter) -> None:
        assert adapter.browser is not None

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
    def test_open_creates_context(self, adapter: YouTubeBrowserAdapter) -> None:
        mock_context = Mock()
        adapter.browser.new_context.return_value = mock_context
        adapter.open()
        assert adapter.context == mock_context
        adapter.browser.new_context.assert_called_once_with(
            storage_state=str(adapter.account.storage_state)
        )


class TestClose:
    def test_close_saves_storage_state(self, adapter: YouTubeBrowserAdapter) -> None:
        mock_context = Mock()
        adapter.context = mock_context
        with patch("os.chmod"):
            adapter.close()
        mock_context.storage_state.assert_called_once()
        mock_context.close.assert_called_once()
        # Should NOT call browser.close() — RaidAdapter owns browser
        adapter.browser.close.assert_not_called()

    def test_close_no_context(self, adapter: YouTubeBrowserAdapter) -> None:
        adapter.context = None
        adapter.close()  # should not raise


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
        mock_page.wait_for_selector.side_effect = PlaywrightTimeoutError("Selector not found")
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
            if selector == "iframe[src*='recaptcha'], div#captcha-container":
                return None
            elif selector == "#title-textarea #textbox":
                return mock_title_input
            elif selector == "#done-button":
                return mock_done_btn
            return None

        def wait_for_selector_side_effect(selector: str, **kwargs: object) -> Mock | None:
            if selector == constants.UPLOAD_FILE_PICKER:
                return Mock()
            elif selector == 'input[type="file"]':
                return mock_file_input
            elif selector == "#title-textarea #textbox":
                return mock_title_input
            elif selector == 'tp-yt-paper-radio-button[name="VIDEO_MADE_FOR_KIDS_NOT_MFK"]':
                return mock_not_for_kids
            elif selector == "#next-button":
                return mock_next_btn
            elif selector == 'tp-yt-paper-radio-button[name="PRIVATE"]':
                return mock_private_radio
            elif selector == "span.video-url-fadeable a":
                return mock_video_url_elem
            elif selector == "tp-yt-iron-overlay-backdrop":
                return None
            return None

        mock_page.query_selector.side_effect = query_selector_side_effect
        mock_page.wait_for_selector.side_effect = wait_for_selector_side_effect
        mock_page.wait_for_function.return_value = None
        mock_context.new_page.return_value = mock_page

        adapter.context = mock_context

        result = adapter.upload(Path("/tmp/video.mp4"), "Test Video")

        assert isinstance(result, UploadResult)
        assert result.video_id == "abc123"
        assert result.url == "https://youtu.be/abc123"
        assert result.title == "Test Video"
        assert result.account_name == "primary"

    def test_upload_unsupported_browser_raises_error(self, adapter: YouTubeBrowserAdapter) -> None:
        mock_context = Mock()
        mock_page = Mock()
        mock_page.url = "https://www.youtube.com/upload"

        def query_selector_side_effect(selector: str) -> Mock | None:
            if selector == constants.CAPTCHA_INDICATOR:
                return None
            if selector == constants.UNSUPPORTED_BROWSER_INDICATOR:
                return Mock()  # truthy — interstitial detected
            return None

        mock_page.query_selector.side_effect = query_selector_side_effect
        mock_context.new_page.return_value = mock_page
        adapter.context = mock_context

        with pytest.raises(UnsupportedBrowserError):
            adapter.upload(Path("/tmp/test.mp4"), "Test Title")


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

        mock_playlist_trigger = Mock()
        mock_search_input = Mock()
        mock_playlist_item = Mock()
        mock_done_btn = Mock()
        mock_page_save_btn = Mock()

        def wait_for_selector_side_effect(selector: str, **kwargs: object) -> Mock | None:
            if (
                selector
                == 'ytcp-video-metadata-playlists ytcp-dropdown-trigger[aria-label="Select playlists"]'
            ):
                return mock_playlist_trigger
            elif selector == "ytcp-playlist-dialog input#search-input":
                return mock_search_input
            elif selector == '#items tp-yt-paper-checkbox:has-text("my-playlist")':
                return mock_playlist_item
            elif selector == "ytcp-button.done-button":
                return mock_done_btn
            elif selector == "ytcp-button#save":
                return mock_page_save_btn
            elif selector == "iframe[src*='recaptcha'], div#captcha-container":
                return None
            return None

        def query_selector_side_effect(selector: str) -> Mock | None:
            if selector == "iframe[src*='recaptcha'], div#captcha-container":
                return None
            return None

        mock_page.wait_for_selector.side_effect = wait_for_selector_side_effect
        mock_page.query_selector.side_effect = query_selector_side_effect
        mock_page.wait_for_function.return_value = None
        mock_context.new_page.return_value = mock_page

        adapter.context = mock_context

        result = adapter.assign_playlist("abc123", "my-playlist")

        assert result is True
        mock_page.goto.assert_called_once()
        mock_playlist_trigger.click.assert_called_once()
        mock_search_input.fill.assert_called_once_with("my-playlist")
        mock_playlist_item.click.assert_called_once()
        mock_done_btn.click.assert_called_once()
        mock_page_save_btn.click.assert_called_once()
