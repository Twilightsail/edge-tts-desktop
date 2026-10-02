import asyncio
from pathlib import Path

import aiofiles
import aiohttp
import edge_tts

from .models import SynthesisRequest, TaskError


class EngineError(Exception):
    """引擎自己判定过的错误：code/message 可直接展示给用户（不得包含密钥）。"""

    def __init__(self, code: str, message: str, retryable: bool = False):
        super().__init__(message)
        self.code, self.message, self.retryable = code, message, retryable


def classify_error(exc: Exception) -> TaskError:
    if isinstance(exc, EngineError):
        return TaskError(code=exc.code, message=exc.message, retryable=exc.retryable)
    if isinstance(exc, aiohttp.ClientResponseError):
        retryable = exc.status == 429 or exc.status >= 500
        return TaskError(
            code="upstream_http",
            message=f"语音服务返回 HTTP {exc.status}",
            retryable=retryable,
        )
    if isinstance(exc, (TimeoutError, aiohttp.ClientConnectionError)):
        return TaskError(
            code="network", message="连接语音服务超时或中断，请检查网络", retryable=True
        )
    if isinstance(exc, edge_tts.exceptions.NoAudioReceived):
        return TaskError(
            code="no_audio", message="语音服务没有返回音频，请检查音色或稍后重试", retryable=True
        )
    if isinstance(exc, OSError):
        return TaskError(code="storage", message="文件读写失败，请检查磁盘空间和目录权限")
    return TaskError(code="synthesis_failed", message="语音合成失败，请查看后端日志或重试")


class EdgeEngine:
    def __init__(self, proxy: str | None = None):
        self.proxy = proxy

    async def voices(self) -> list[dict]:
        async with asyncio.timeout(30):
            return await edge_tts.list_voices(proxy=self.proxy)

    async def synthesize(self, request: SynthesisRequest, audio: Path, subtitles: Path, progress):
        # Communicate handles UTF-8 chunking and cumulative boundary offsets internally.
        communicate = edge_tts.Communicate(
            request.text,
            request.voice,
            rate=f"{request.rate:+d}%",
            volume=f"{request.volume:+d}%",
            pitch=f"{request.pitch:+d}Hz",
            boundary="SentenceBoundary",
            proxy=self.proxy,
            connect_timeout=15,
            receive_timeout=60,
        )
        maker = edge_tts.SubMaker()
        size, last_report = 0, 0.0
        async with aiofiles.open(audio, "wb") as stream:
            async for chunk in communicate.stream():
                if chunk["type"] == "audio":
                    await stream.write(chunk["data"])
                    size += len(chunk["data"])
                    current = asyncio.get_running_loop().time()
                    if current - last_report > 0.5:
                        progress(size)
                        last_report = current
                elif request.subtitles and chunk["type"] == "SentenceBoundary":
                    maker.feed(chunk)
        if size == 0:
            raise edge_tts.exceptions.NoAudioReceived("Empty synthesis result")
        if request.subtitles:
            if not maker.cues:
                raise RuntimeError("No subtitle boundaries received")
            async with aiofiles.open(subtitles, "w", encoding="utf-8") as stream:
                await stream.write(maker.get_srt())
        progress(size)
