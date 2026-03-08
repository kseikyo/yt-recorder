from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from yt_recorder import constants
from yt_recorder.adapters.youtube import YouTubeBrowserAdapter
from yt_recorder.domain.exceptions import DailyLimitError, VideoTooLongError
from yt_recorder.domain.models import UploadResult, YouTubeAccount
from yt_recorder.domain.protocols import VideoUploader


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


def build_upload_page(wait_result: dict[str, object]) -> tuple[MagicMock, MagicMock, MagicMock]:
    mock_page = MagicMock()
    mock_page.url = "https://www.youtube.com/upload"

    mock_file_input = MagicMock()
    mock_title_input = MagicMock()
    mock_description_box = MagicMock()
    mock_not_for_kids = MagicMock()
    mock_next_btn = MagicMock()
    mock_private_radio = MagicMock()
    mock_video_url_elem = MagicMock()
    mock_done_btn = MagicMock()
    mock_handle = MagicMock()

    mock_video_url_elem.get_attribute.return_value = "https://youtu.be/abc123"
    mock_handle.json_value.return_value = wait_result

    def query_selector_side_effect(selector: str) -> MagicMock | None:
        if selector == constants.CAPTCHA_INDICATOR:
            return None
        if selector == constants.TITLE_INPUT:
            return mock_title_input
        if selector == constants.DONE_BUTTON:
            return mock_done_btn
        return None

    def wait_for_selector_side_effect(selector: str, **_: object) -> MagicMock | None:
        if selector == "ytcp-uploads-file-picker":
            return MagicMock()
        if selector == constants.FILE_INPUT:
            return mock_file_input
        if selector == constants.TITLE_INPUT:
            return mock_title_input
        if selector == constants.NOT_MADE_FOR_KIDS:
            return mock_not_for_kids
        if selector == constants.NEXT_BUTTON:
            return mock_next_btn
        if selector == constants.PRIVATE_RADIO:
            return mock_private_radio
        if selector == constants.VIDEO_URL_ELEMENT:
            return mock_video_url_elem
        if selector == constants.DIALOG_SCRIM:
            return None
        return None

    mock_page.query_selector.side_effect = query_selector_side_effect
    mock_page.wait_for_selector.side_effect = wait_for_selector_side_effect
    mock_page.wait_for_function.return_value = mock_handle
    mock_page.locator.return_value = mock_description_box

    return mock_page, mock_description_box, mock_done_btn


class TestUploadV2:
    def test_upload_wait_for_function_done_result_succeeds(
        self, adapter: YouTubeBrowserAdapter
    ) -> None:
        mock_context = MagicMock()
        mock_page, _, _ = build_upload_page({"done": True})
        mock_context.new_page.return_value = mock_page
        adapter.context = mock_context

        with patch.object(adapter, "_random_delay"):
            result = adapter.upload(Path("/tmp/video.mp4"), "Test Video")

        assert isinstance(result, UploadResult)
        assert result.video_id == "abc123"
        assert result.url == "https://youtu.be/abc123"
        assert result.title == "Test Video"
        script = mock_page.wait_for_function.call_args.args[0]
        assert "too long" in script
        assert "upload limit" in script
        assert "#done-button" in script

    def test_upload_raises_video_too_long_error(self, adapter: YouTubeBrowserAdapter) -> None:
        mock_context = MagicMock()
        mock_page, _, mock_done_btn = build_upload_page({"error": "too_long"})
        mock_context.new_page.return_value = mock_page
        adapter.context = mock_context

        with patch.object(adapter, "_random_delay"):
            with pytest.raises(VideoTooLongError, match="too long"):
                adapter.upload(Path("/tmp/video.mp4"), "Test Video")

        mock_done_btn.click.assert_not_called()

    def test_upload_raises_daily_limit_error(self, adapter: YouTubeBrowserAdapter) -> None:
        mock_context = MagicMock()
        mock_page, _, mock_done_btn = build_upload_page({"error": "daily_limit"})
        mock_context.new_page.return_value = mock_page
        adapter.context = mock_context

        with patch.object(adapter, "_random_delay"):
            with pytest.raises(DailyLimitError, match="daily upload limit"):
                adapter.upload(Path("/tmp/video.mp4"), "Test Video")

        mock_done_btn.click.assert_not_called()

    def test_upload_fills_description_when_non_empty(
        self, adapter: YouTubeBrowserAdapter
    ) -> None:
        mock_context = MagicMock()
        mock_page, mock_description_box, _ = build_upload_page({"done": True})
        mock_context.new_page.return_value = mock_page
        adapter.context = mock_context

        with patch.object(adapter, "_random_delay"):
            adapter.upload(Path("/tmp/video.mp4"), "Test Video", description="[Part 1/3]")

        mock_page.locator.assert_called_once_with(constants.DESCRIPTION_TEXTAREA)
        mock_description_box.fill.assert_called_once_with("[Part 1/3]")

    def test_upload_skips_description_when_empty(self, adapter: YouTubeBrowserAdapter) -> None:
        mock_context = MagicMock()
        mock_page, mock_description_box, _ = build_upload_page({"done": True})
        mock_context.new_page.return_value = mock_page
        adapter.context = mock_context

        with patch.object(adapter, "_random_delay"):
            adapter.upload(Path("/tmp/video.mp4"), "Test Video", description="")

        mock_page.locator.assert_not_called()
        mock_description_box.fill.assert_not_called()


class StubUploader:
    def __init__(self) -> None:
        self.last_description = ""

    def open(self) -> None:
        return None

    def close(self) -> None:
        return None

    def upload(self, path: Path, title: str, description: str = "") -> UploadResult:
        self.last_description = description
        return UploadResult(
            video_id="abc123",
            url="https://youtu.be/abc123",
            title=title,
            account_name="primary",
        )

    def assign_playlist(self, video_id: str, playlist_name: str) -> bool:
        return True


def upload_with_description(uploader: VideoUploader) -> UploadResult:
    return uploader.upload(Path("/tmp/video.mp4"), "Test Video", description="[Part 1/3]")


def test_video_uploader_protocol_accepts_description_kwarg() -> None:
    uploader = StubUploader()

    result = upload_with_description(uploader)

    assert isinstance(uploader, VideoUploader)
    assert isinstance(result, UploadResult)
    assert uploader.last_description == "[Part 1/3]"
