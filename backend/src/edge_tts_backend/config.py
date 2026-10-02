import os
import secrets
from dataclasses import dataclass, field
from pathlib import Path


def default_data_dir() -> Path:
    base = Path(os.environ.get("LOCALAPPDATA", Path.home() / ".local" / "share"))
    return base / "EdgeTTSDesktop"


@dataclass(frozen=True)
class Settings:
    data_dir: Path = field(default_factory=default_data_dir)
    token: str = field(default_factory=lambda: secrets.token_urlsafe(32))
    concurrency: int = 2
    max_pending: int = 100
    attempts: int = 3
    task_timeout: float = 1800
    voice_cache_seconds: int = 86400
    proxy: str | None = None
    azure_base_url: str | None = None  # 仅测试或自建代理时使用，默认按区域生成官方地址
    origins: tuple[str, ...] = (
        "http://localhost:5173",
        "http://127.0.0.1:5173",
        "http://tauri.localhost",
        "https://tauri.localhost",
        "tauri://localhost",
    )

    def __post_init__(self):
        if not self.token or self.concurrency < 1 or self.max_pending < 1:
            raise ValueError("token, concurrency and max_pending must be valid")
        if self.attempts < 1 or self.task_timeout <= 0:
            raise ValueError("attempts and task_timeout must be positive")
