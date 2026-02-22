from __future__ import annotations

from pathlib import Path
from unittest.mock import Mock

import pytest

from yt_recorder.adapters.raid import RaidAdapter
from yt_recorder.domain.models import UploadResult, YouTubeAccount


class TestRaidAdapter:
    """Test suite for RaidAdapter."""

    @pytest.fixture
    def accounts(self) -> list[YouTubeAccount]:
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
            YouTubeAccount(
                name="mirror-2",
                storage_state=Path("/tmp/mirror2.json"),
                cookies_path=Path("/tmp/mirror2.txt"),
                role="mirror",
            ),
        ]

    @pytest.fixture
    def mock_adapter(self) -> Mock:
        adapter = Mock()
        adapter.open = Mock()
        adapter.close = Mock()
        adapter.upload = Mock(
            return_value=UploadResult(
                video_id="abc123",
                url="https://youtu.be/abc123",
                title="Test Video",
                account_name="test",
            )
        )
        adapter.assign_playlist = Mock()
        return adapter

    def test_open_launches_all_browsers(
        self, accounts: list[YouTubeAccount], mock_adapter: Mock
    ) -> None:
        raid = RaidAdapter(
            accounts, headless=True, delays={}, adapter_factory=lambda x: mock_adapter
        )
        raid.open()

        assert mock_adapter.open.call_count == 3

    def test_close_closes_all_browsers(
        self, accounts: list[YouTubeAccount], mock_adapter: Mock
    ) -> None:
        raid = RaidAdapter(
            accounts, headless=True, delays={}, adapter_factory=lambda x: mock_adapter
        )
        raid.open()
        raid.close()

        assert mock_adapter.close.call_count == 3

    def test_upload_returns_all_results(
        self, accounts: list[YouTubeAccount], mock_adapter: Mock
    ) -> None:
        raid = RaidAdapter(
            accounts, headless=True, delays={}, adapter_factory=lambda x: mock_adapter
        )
        raid.open()
        results = raid.upload(Path("/tmp/test.mp4"), "Test Title", "test-playlist")
        raid.close()

        assert "primary" in results
        assert "mirror-1" in results
        assert "mirror-2" in results
        assert all(r is not None for r in results.values())

    def test_upload_calls_assign_playlist(
        self, accounts: list[YouTubeAccount], mock_adapter: Mock
    ) -> None:
        raid = RaidAdapter(
            accounts, headless=True, delays={}, adapter_factory=lambda x: mock_adapter
        )
        raid.open()
        raid.upload(Path("/tmp/test.mp4"), "Test Title", "test-playlist")
        raid.close()

        assert mock_adapter.assign_playlist.call_count == 3

    def test_mirror_failure_returns_none(self, accounts: list[YouTubeAccount]) -> None:
        def factory(acct: YouTubeAccount) -> Mock:
            adapter = Mock()
            adapter.open = Mock()
            adapter.close = Mock()
            if acct.role == "mirror":
                adapter.upload = Mock(side_effect=Exception("Upload failed"))
            else:
                adapter.upload = Mock(
                    return_value=UploadResult(
                        video_id="abc123",
                        url="https://youtu.be/abc123",
                        title="Test Video",
                        account_name=acct.name,
                    )
                )
            adapter.assign_playlist = Mock()
            return adapter

        raid = RaidAdapter(accounts, headless=True, delays={}, adapter_factory=factory)
        raid.open()
        results = raid.upload(Path("/tmp/test.mp4"), "Test Title", "test-playlist")
        raid.close()

        assert results["primary"] is not None
        assert results["mirror-1"] is None
        assert results["mirror-2"] is None

    def test_uploads_to_primary_first(self, accounts: list[YouTubeAccount]) -> None:
        call_order = []

        def factory(acct: YouTubeAccount) -> Mock:
            adapter = Mock()
            adapter.open = Mock()
            adapter.close = Mock()
            adapter.assign_playlist = Mock()

            def upload(*args, **kwargs) -> UploadResult:
                call_order.append(acct.name)
                return UploadResult(
                    video_id="abc123",
                    url="https://youtu.be/abc123",
                    title="Test Video",
                    account_name=acct.name,
                )

            adapter.upload = Mock(side_effect=upload)
            return adapter

        raid = RaidAdapter(accounts, headless=True, delays={}, adapter_factory=factory)
        raid.open()
        raid.upload(Path("/tmp/test.mp4"), "Test Title", "test-playlist")
        raid.close()

        assert call_order[0] == "primary"

    def test_empty_accounts_raises_error(self) -> None:
        with pytest.raises(ValueError, match="No accounts configured"):
            RaidAdapter([], headless=True, delays={})

    def test_no_primary_account_raises_error(self) -> None:
        accounts = [
            YouTubeAccount(
                name="mirror-1",
                storage_state=Path("/tmp/mirror1.json"),
                cookies_path=Path("/tmp/mirror1.txt"),
                role="mirror",
            ),
        ]
        with pytest.raises(ValueError, match="No primary account found"):
            RaidAdapter(accounts, headless=True, delays={})
