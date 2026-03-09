from __future__ import annotations

from pathlib import Path
from typing import Any
from unittest.mock import Mock

import pytest

from yt_recorder.adapters.raid import RaidAdapter
from yt_recorder.domain.exceptions import DailyLimitError, VideoTooLongError
from yt_recorder.domain.models import UploadResult, YouTubeAccount


def make_result(account_name: str = "test") -> UploadResult:
    return UploadResult(
        video_id="vid123",
        url="https://youtu.be/vid123",
        title="Test",
        account_name=account_name,
    )


def make_accounts() -> list[YouTubeAccount]:
    return [
        YouTubeAccount(
            name="primary",
            storage_state=Path("/tmp/primary.json"),
            cookies_path=Path("/tmp/primary.txt"),
            role="primary",
        ),
        YouTubeAccount(
            name="mirror-1",
            storage_state=Path("/tmp/mirror1.json"),
            cookies_path=Path("/tmp/mirror1.txt"),
            role="mirror",
        ),
    ]


def make_mock_adapter(account_name: str = "test") -> Mock:
    adapter = Mock()
    adapter.open = Mock()
    adapter.close = Mock()
    adapter.upload = Mock(return_value=make_result(account_name))
    adapter.assign_playlist = Mock(return_value=True)
    return adapter


class TestDescriptionPassthrough:
    @pytest.fixture(autouse=True)
    def _mock_playwright(self, monkeypatch: pytest.MonkeyPatch) -> None:
        mock_pw = Mock()
        mock_playwright_inst = Mock()
        mock_browser = Mock()
        mock_pw.return_value.start.return_value = mock_playwright_inst
        mock_playwright_inst.chromium.launch.return_value = mock_browser
        monkeypatch.setattr("yt_recorder.adapters.raid.sync_playwright", mock_pw)

    def test_description_passed_to_primary(self) -> None:
        accounts = make_accounts()
        adapters: dict[str, Mock] = {}

        def factory(acct: YouTubeAccount, browser: Any) -> Mock:
            m = make_mock_adapter(acct.name)
            adapters[acct.name] = m
            return m

        raid = RaidAdapter(accounts, headless=True, delays={}, adapter_factory=factory)
        raid.open()
        raid.upload(Path("/tmp/test.mp4"), "Title", "playlist", description="my desc")

        adapters["primary"].upload.assert_called_once_with(
            Path("/tmp/test.mp4"), "Title", description="my desc"
        )

    def test_description_passed_to_mirrors(self) -> None:
        accounts = make_accounts()
        adapters: dict[str, Mock] = {}

        def factory(acct: YouTubeAccount, browser: Any) -> Mock:
            m = make_mock_adapter(acct.name)
            adapters[acct.name] = m
            return m

        raid = RaidAdapter(accounts, headless=True, delays={}, adapter_factory=factory)
        raid.open()
        raid.upload(Path("/tmp/test.mp4"), "Title", "playlist", description="mirror desc")

        adapters["mirror-1"].upload.assert_called_once_with(
            Path("/tmp/test.mp4"), "Title", description="mirror desc"
        )

    def test_empty_description_default(self) -> None:
        accounts = make_accounts()
        adapters: dict[str, Mock] = {}

        def factory(acct: YouTubeAccount, browser: Any) -> Mock:
            m = make_mock_adapter(acct.name)
            adapters[acct.name] = m
            return m

        raid = RaidAdapter(accounts, headless=True, delays={}, adapter_factory=factory)
        raid.open()
        raid.upload(Path("/tmp/test.mp4"), "Title", "playlist")

        adapters["primary"].upload.assert_called_once_with(
            Path("/tmp/test.mp4"), "Title", description=""
        )


class TestUploadToAccount:
    @pytest.fixture(autouse=True)
    def _mock_playwright(self, monkeypatch: pytest.MonkeyPatch) -> None:
        mock_pw = Mock()
        mock_playwright_inst = Mock()
        mock_browser = Mock()
        mock_pw.return_value.start.return_value = mock_playwright_inst
        mock_playwright_inst.chromium.launch.return_value = mock_browser
        monkeypatch.setattr("yt_recorder.adapters.raid.sync_playwright", mock_pw)

    def test_returns_upload_result(self) -> None:
        accounts = make_accounts()
        adapters: dict[str, Mock] = {}

        def factory(acct: YouTubeAccount, browser: Any) -> Mock:
            m = make_mock_adapter(acct.name)
            adapters[acct.name] = m
            return m

        raid = RaidAdapter(accounts, headless=True, delays={}, adapter_factory=factory)
        raid.open()

        result = raid.upload_to_account("primary", Path("/tmp/test.mp4"), "Title", description="d")

        assert result.account_name == "primary"
        adapters["primary"].upload.assert_called_once_with(
            Path("/tmp/test.mp4"), "Title", description="d"
        )

    def test_upload_to_mirror_account(self) -> None:
        accounts = make_accounts()
        adapters: dict[str, Mock] = {}

        def factory(acct: YouTubeAccount, browser: Any) -> Mock:
            m = make_mock_adapter(acct.name)
            adapters[acct.name] = m
            return m

        raid = RaidAdapter(accounts, headless=True, delays={}, adapter_factory=factory)
        raid.open()

        result = raid.upload_to_account("mirror-1", Path("/tmp/test.mp4"), "Title")

        assert result.account_name == "mirror-1"


class TestVideoTooLongError:
    @pytest.fixture(autouse=True)
    def _mock_playwright(self, monkeypatch: pytest.MonkeyPatch) -> None:
        mock_pw = Mock()
        mock_playwright_inst = Mock()
        mock_browser = Mock()
        mock_pw.return_value.start.return_value = mock_playwright_inst
        mock_playwright_inst.chromium.launch.return_value = mock_browser
        monkeypatch.setattr("yt_recorder.adapters.raid.sync_playwright", mock_pw)

    def test_propagates_from_primary(self) -> None:
        accounts = make_accounts()

        def factory(acct: YouTubeAccount, browser: Any) -> Mock:
            m = make_mock_adapter(acct.name)
            if acct.role == "primary":
                m.upload = Mock(side_effect=VideoTooLongError("too long"))
            return m

        raid = RaidAdapter(accounts, headless=True, delays={}, adapter_factory=factory)
        raid.open()

        with pytest.raises(VideoTooLongError):
            raid.upload(Path("/tmp/test.mp4"), "Title", "playlist")

    def test_propagates_from_mirror(self) -> None:
        accounts = make_accounts()

        def factory(acct: YouTubeAccount, browser: Any) -> Mock:
            m = make_mock_adapter(acct.name)
            if acct.role == "mirror":
                m.upload = Mock(side_effect=VideoTooLongError("too long"))
            return m

        raid = RaidAdapter(accounts, headless=True, delays={}, adapter_factory=factory)
        raid.open()

        with pytest.raises(VideoTooLongError):
            raid.upload(Path("/tmp/test.mp4"), "Title", "playlist")

    def test_propagates_from_upload_to_account(self) -> None:
        accounts = make_accounts()

        def factory(acct: YouTubeAccount, browser: Any) -> Mock:
            m = make_mock_adapter(acct.name)
            m.upload = Mock(side_effect=VideoTooLongError("too long"))
            return m

        raid = RaidAdapter(accounts, headless=True, delays={}, adapter_factory=factory)
        raid.open()

        with pytest.raises(VideoTooLongError):
            raid.upload_to_account("primary", Path("/tmp/test.mp4"), "Title")


class TestDailyLimitError:
    @pytest.fixture(autouse=True)
    def _mock_playwright(self, monkeypatch: pytest.MonkeyPatch) -> None:
        mock_pw = Mock()
        mock_playwright_inst = Mock()
        mock_browser = Mock()
        mock_pw.return_value.start.return_value = mock_playwright_inst
        mock_playwright_inst.chromium.launch.return_value = mock_browser
        monkeypatch.setattr("yt_recorder.adapters.raid.sync_playwright", mock_pw)

    def test_mirror_daily_limit_sets_none(self) -> None:
        accounts = make_accounts()

        def factory(acct: YouTubeAccount, browser: Any) -> Mock:
            m = make_mock_adapter(acct.name)
            if acct.role == "mirror":
                m.upload = Mock(side_effect=DailyLimitError("limit reached"))
            return m

        raid = RaidAdapter(accounts, headless=True, delays={}, adapter_factory=factory)
        raid.open()
        results, _ = raid.upload(Path("/tmp/test.mp4"), "Title", "playlist")

        assert results["primary"] is not None
        assert results["mirror-1"] is None

    def test_primary_daily_limit_propagates(self) -> None:
        accounts = make_accounts()

        def factory(acct: YouTubeAccount, browser: Any) -> Mock:
            m = make_mock_adapter(acct.name)
            if acct.role == "primary":
                m.upload = Mock(side_effect=DailyLimitError("limit reached"))
            return m

        raid = RaidAdapter(accounts, headless=True, delays={}, adapter_factory=factory)
        raid.open()

        with pytest.raises(DailyLimitError):
            raid.upload(Path("/tmp/test.mp4"), "Title", "playlist")

    def test_upload_to_account_daily_limit_propagates(self) -> None:
        accounts = make_accounts()

        def factory(acct: YouTubeAccount, browser: Any) -> Mock:
            m = make_mock_adapter(acct.name)
            m.upload = Mock(side_effect=DailyLimitError("limit reached"))
            return m

        raid = RaidAdapter(accounts, headless=True, delays={}, adapter_factory=factory)
        raid.open()

        with pytest.raises(DailyLimitError):
            raid.upload_to_account("primary", Path("/tmp/test.mp4"), "Title")


class TestAssignPlaylistToAccount:
    @pytest.fixture(autouse=True)
    def _mock_playwright(self, monkeypatch: pytest.MonkeyPatch) -> None:
        mock_pw = Mock()
        mock_playwright_inst = Mock()
        mock_browser = Mock()
        mock_pw.return_value.start.return_value = mock_playwright_inst
        mock_playwright_inst.chromium.launch.return_value = mock_browser
        monkeypatch.setattr("yt_recorder.adapters.raid.sync_playwright", mock_pw)

    def test_delegates_to_adapter(self) -> None:
        accounts = make_accounts()
        adapters: dict[str, Mock] = {}

        def factory(acct: YouTubeAccount, browser: Any) -> Mock:
            m = make_mock_adapter(acct.name)
            adapters[acct.name] = m
            return m

        raid = RaidAdapter(accounts, headless=True, delays={}, adapter_factory=factory)
        raid.open()

        result = raid.assign_playlist_to_account("primary", "vid123", "my-playlist")

        assert result is True
        adapters["primary"].assign_playlist.assert_called_once_with("vid123", "my-playlist")

    def test_returns_false_on_failure(self) -> None:
        accounts = make_accounts()

        def factory(acct: YouTubeAccount, browser: Any) -> Mock:
            m = make_mock_adapter(acct.name)
            m.assign_playlist = Mock(return_value=False)
            return m

        raid = RaidAdapter(accounts, headless=True, delays={}, adapter_factory=factory)
        raid.open()

        result = raid.assign_playlist_to_account("mirror-1", "vid123", "playlist")

        assert result is False
