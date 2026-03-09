from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from yt_recorder.domain.models import YouTubeAccount


@dataclass
class Config:
    """Application configuration."""

    accounts: list[YouTubeAccount] = field(default_factory=list)
    extensions: tuple[str, ...] = (".mp4", ".mkv", ".mov", ".webm", ".avi")
    exclude_dirs: frozenset[str] = frozenset({"transcripts"})
    max_depth: int = 1
    delays: dict[str, tuple[float, float]] = field(
        default_factory=lambda: {
            "field": (0.3, 0.8),
            "nav": (1.0, 3.0),
            "post": (2.0, 5.0),
        }
    )
    headless: bool = False
    transcript_language: str = "en"
    transcript_delay: float = 1.0
    split_threshold_secs: float = 3420.0

    @staticmethod
    def default_config_dir() -> Path:
        """XDG-compliant config directory."""
        import platform

        if platform.system() == "Darwin":
            return Path.home() / "Library" / "Application Support" / "yt-recorder"
        elif platform.system() == "Windows":
            return Path.home() / "AppData" / "Roaming" / "yt-recorder"
        else:
            import os

            return Path(os.environ.get("XDG_CONFIG_HOME", Path.home() / ".config")) / "yt-recorder"


def load_config(config_path: Path | None = None) -> Config:
    """Load configuration from TOML file.

    Args:
        config_path: Path to config file. If None, uses default location.

    Returns:
        Config instance with values from file (or defaults if file doesn't exist).
    """
    if config_path is None:
        config_path = Config.default_config_dir() / "config.toml"

    # Start with defaults
    config = Config()

    if not config_path.exists():
        return config

    # Parse TOML
    try:
        import tomllib  # type: ignore[import-not-found]
    except ImportError:
        import tomli as tomllib

    with open(config_path, "rb") as f:
        data = tomllib.load(f)

    # Update from file
    if "accounts" in data:
        from yt_recorder.domain.models import YouTubeAccount

        accounts = []
        for i, (name, value) in enumerate(data["accounts"].items()):
            role = "primary" if i == 0 else "mirror"
            if isinstance(value, str):
                account = YouTubeAccount(
                    name=name,
                    storage_state=Path(value),
                    cookies_path=Path(value).parent / f"{name}_cookies.txt",
                    role=role,
                )
            elif isinstance(value, dict):
                path_str = str(value["path"])
                limit_value = value.get("upload_limit_secs")
                account = YouTubeAccount(
                    name=name,
                    storage_state=Path(path_str),
                    cookies_path=Path(path_str).parent / f"{name}_cookies.txt",
                    role=role,
                    upload_limit_secs=float(limit_value) if limit_value is not None else None,
                )
            else:
                continue
            accounts.append(account)

        config.accounts = accounts

    if "scanner" in data:
        scanner = data["scanner"]
        if "extensions" in scanner:
            config.extensions = tuple(scanner["extensions"])
        if "exclude_dirs" in scanner:
            config.exclude_dirs = frozenset(scanner["exclude_dirs"])
        if "max_depth" in scanner:
            config.max_depth = scanner["max_depth"]

    if "upload" in data:
        upload = data["upload"]
        if "delay_min" in upload and "delay_max" in upload:
            config.delays["field"] = (upload["delay_min"], upload["delay_max"])
            config.delays["nav"] = (upload["delay_min"], upload["delay_max"])
        if "headless" in upload:
            config.headless = upload["headless"]
        if "split_threshold_secs" in upload:
            config.split_threshold_secs = float(upload["split_threshold_secs"])

    if "transcript" in data:
        transcript = data["transcript"]
        if "language" in transcript:
            config.transcript_language = transcript["language"]
        if "delay" in transcript:
            config.transcript_delay = transcript["delay"]

    return config


def save_config_template(config_path: Path | None = None) -> None:
    """Create a config.toml template file."""
    if config_path is None:
        config_path = Config.default_config_dir() / "config.toml"

    config_path.parent.mkdir(parents=True, exist_ok=True)

    template = f"""# yt-recorder configuration
# Place this file at: {config_path}

[accounts]
# Add your YouTube accounts here
# primary = "/path/to/primary/storage_state.json"
# backup = "/path/to/backup/storage_state.json"

[scanner]
extensions = [".mp4", ".mkv", ".mov", ".webm", ".avi"]
exclude_dirs = ["transcripts"]
max_depth = 1

[upload]
limit = 5
delay_min = 1.0
delay_max = 3.0
headless = false
# split_threshold_secs = 3420  # 57 minutes — adjust if your account has a different limit

[transcript]
language = "en"
delay = 1.0
"""

    config_path.write_text(template)


def save_detected_limit(config_path: Path, account_name: str, limit_secs: float) -> None:
    """Persist a detected upload limit for an account to config.toml."""
    import tomlkit

    content = config_path.read_text(encoding="utf-8")
    doc = tomlkit.parse(content)
    account_value = doc["accounts"][account_name]  # type: ignore[index]

    if isinstance(account_value, str):
        table = tomlkit.table()
        table["path"] = account_value
        table["upload_limit_secs"] = limit_secs
        doc["accounts"][account_name] = table  # type: ignore[index]
    else:
        doc["accounts"][account_name]["upload_limit_secs"] = limit_secs  # type: ignore[index]

    config_path.write_text(tomlkit.dumps(doc), encoding="utf-8")
