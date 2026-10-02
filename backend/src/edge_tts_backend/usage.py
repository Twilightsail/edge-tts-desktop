"""Azure 免费额度的本机用量估算。

计费规则（来自 Azure 文档）：按每个成功请求的字符数计费；每个汉字（含日文汉字、韩文汉字）
算 2 个字符，其余每个 Unicode 码位算 1 个（含空格、标点）；SSML 中除 <speak>、<voice> 外的
标记也计费。
这里只统计“通过本应用成功发出的请求”，同一密钥在别处的用量不在内，准确数字以 Azure 门户的
Synthesized Characters 指标为准，因此提供校准接口。免费额度按自然月（UTC）重置。
"""

import threading
from datetime import UTC, datetime

DEFAULT_LIMIT = 500_000  # 官方定价页：神经语音免费档每月 50 万字符
_KEY = "azure_usage"


def is_han(char: str) -> bool:
    code = ord(char)
    return (
        0x3400 <= code <= 0x4DBF
        or 0x4E00 <= code <= 0x9FFF
        or 0xF900 <= code <= 0xFAFF
        or 0x20000 <= code <= 0x323AF
    )


def billable_chars(text: str) -> int:
    return sum(2 if is_han(char) else 1 for char in text)


class AzureUsage:
    def __init__(self, store, clock=None):
        self.store = store
        self.lock = threading.Lock()
        self.clock = clock or (lambda: datetime.now(UTC))

    def _load(self) -> dict:
        month = self.clock().strftime("%Y-%m")
        saved = self.store.get_cache(_KEY) or {}
        if saved.get("month") != month:  # 跨月自动清零，上限保持
            saved = {"month": month, "chars": 0, "limit": saved.get("limit", DEFAULT_LIMIT)}
        saved.setdefault("limit", DEFAULT_LIMIT)
        return saved

    def get(self) -> dict:
        with self.lock:
            return self._load()

    def add(self, chars: int) -> None:
        with self.lock:
            usage = self._load()
            usage["chars"] += chars
            self.store.put_cache(_KEY, usage)

    def set(self, chars: int | None = None, limit: int | None = None) -> dict:
        with self.lock:
            usage = self._load()
            if chars is not None:
                usage["chars"] = chars
            if limit is not None:
                usage["limit"] = limit
            self.store.put_cache(_KEY, usage)
            return usage
