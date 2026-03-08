from __future__ import annotations

from pathlib import Path

from yt_recorder.config import load_config, save_detected_limit
from yt_recorder.domain.models import YouTubeAccount

try:
    import tomllib  # type: ignore[import-not-found]
except ImportError:
    import tomli as tomllib


def write_config(tmp_path: Path, content: str) -> Path:
    config_path = tmp_path / "config.toml"
    config_path.write_text(content, encoding="utf-8")
    return config_path


def test_load_config_flat_accounts_default_limit_none(tmp_path: Path) -> None:
    config_path = write_config(
        tmp_path,
        """
[accounts]
primary = "/tmp/primary.json"
mirror = "/tmp/mirror.json"
""".strip(),
    )

    config = load_config(config_path)

    assert [account.name for account in config.accounts] == ["primary", "mirror"]
    assert config.accounts[0].role == "primary"
    assert config.accounts[0].upload_limit_secs is None
    assert config.accounts[1].role == "mirror"
    assert config.accounts[1].upload_limit_secs is None


def test_load_config_nested_accounts_reads_limit(tmp_path: Path) -> None:
    config_path = write_config(
        tmp_path,
        """
[accounts.primary]
path = "/tmp/primary.json"
upload_limit_secs = 3300.0

[accounts.mirror]
path = "/tmp/mirror.json"
upload_limit_secs = 1800
""".strip(),
    )

    config = load_config(config_path)

    assert config.accounts[0].name == "primary"
    assert config.accounts[0].upload_limit_secs == 3300.0
    assert config.accounts[1].name == "mirror"
    assert config.accounts[1].upload_limit_secs == 1800.0


def test_load_config_mixed_account_formats(tmp_path: Path) -> None:
    config_path = write_config(
        tmp_path,
        """
[accounts]
primary = "/tmp/primary.json"

[accounts.mirror]
path = "/tmp/mirror.json"
upload_limit_secs = 3300
""".strip(),
    )

    config = load_config(config_path)

    assert [account.name for account in config.accounts] == ["primary", "mirror"]
    assert config.accounts[0].upload_limit_secs is None
    assert config.accounts[1].upload_limit_secs == 3300.0


def test_save_detected_limit_migrates_flat_entry_round_trip(tmp_path: Path) -> None:
    config_path = write_config(
        tmp_path,
        """
[accounts]
primary = "/tmp/primary.json"
""".strip(),
    )

    save_detected_limit(config_path, "primary", 3300.0)

    with config_path.open("rb") as handle:
        data = tomllib.load(handle)

    assert data["accounts"]["primary"]["path"] == "/tmp/primary.json"
    assert data["accounts"]["primary"]["upload_limit_secs"] == 3300.0

    config = load_config(config_path)
    assert config.accounts[0].upload_limit_secs == 3300.0


def test_save_detected_limit_updates_existing_nested_entry(tmp_path: Path) -> None:
    config_path = write_config(
        tmp_path,
        """
[accounts.primary]
path = "/tmp/primary.json"
upload_limit_secs = 1200.0
""".strip(),
    )

    save_detected_limit(config_path, "primary", 3300.0)

    with config_path.open("rb") as handle:
        data = tomllib.load(handle)

    assert data["accounts"]["primary"]["path"] == "/tmp/primary.json"
    assert data["accounts"]["primary"]["upload_limit_secs"] == 3300.0


def test_save_detected_limit_preserves_comments(tmp_path: Path) -> None:
    config_path = write_config(
        tmp_path,
        """
# my comment
[accounts]
primary = "/tmp/primary.json"
""".strip(),
    )

    save_detected_limit(config_path, "primary", 3300.0)

    content = config_path.read_text(encoding="utf-8")

    assert "# my comment" in content


def test_youtube_account_upload_limit_default_and_kwarg() -> None:
    default_account = YouTubeAccount(
        name="primary",
        storage_state=Path("/tmp/primary.json"),
        cookies_path=Path("/tmp/primary_cookies.txt"),
        role="primary",
    )
    limited_account = YouTubeAccount(
        name="mirror",
        storage_state=Path("/tmp/mirror.json"),
        cookies_path=Path("/tmp/mirror_cookies.txt"),
        role="mirror",
        upload_limit_secs=3300.0,
    )

    assert default_account.upload_limit_secs is None
    assert limited_account.upload_limit_secs == 3300.0
