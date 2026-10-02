"""Azure AI Speech（REST）合成引擎。

REST 接口只返回音频，不提供字边界/句边界时间点；字幕按“句子字数占比”在每个请求的真实时长内估算，
可能与语音有零点几秒偏差。需要精确字幕时请使用 Edge 引擎。
单次请求音频超过 10 分钟会被服务端静默截断，因此长文本在引擎内部按语速拆成多个请求再拼接。
"""

import asyncio
import re
from pathlib import Path
from xml.sax.saxutils import escape

import aiofiles
import aiohttp

from .engine import EngineError
from .models import SynthesisRequest
from .mp3 import mp3_duration
from .secrets_store import AzureCredentials
from .segments import split_text
from .subtitles import format_cues
from .usage import AzureUsage, billable_chars

OUTPUT_FORMAT = "audio-24khz-48kbitrate-mono-mp3"
USER_AGENT = "EdgeTTSDesktop"
MIN_RATE = -50  # Azure 的 rate 相对倍率下限约为 0.5 倍
CHINA_REGIONS = {"chinaeast2", "chinanorth2", "chinanorth3"}
_CONTROL = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f]")
_SENTENCE = re.compile(r"[^。！？!?；;\n]+[。！？!?；;]*|\n")


def endpoint(region: str) -> str:
    domain = "azure.cn" if region in CHINA_REGIONS else "microsoft.com"
    return f"https://{region}.tts.speech.{domain}"


def chunk_limit(rate: int) -> int:
    """按语速估算单请求的安全字符数：按约 5 分钟音频留足 10 分钟上限的余量。"""
    return max(100, min(3000, int(1500 * (100 + max(rate, MIN_RATE)) / 100)))


def ssml_body(text: str, rate: int, volume: int, pitch: int, style: str = "") -> str:
    """<voice> 内的内容，也就是 Azure 计费的部分。默认参数时不加 prosody，省掉约 60 个计费字符。"""
    body = escape(_CONTROL.sub("", text))
    rate = max(rate, MIN_RATE)
    if not (rate == 0 and volume == 0 and pitch == 0):
        attrs = f"rate='{rate:+d}%' pitch='{pitch:+d}Hz' volume='{volume:+d}%'"
        body = f"<prosody {attrs}>{body}</prosody>"
    if style:  # 风格名已由模型限定为字母数字和连字符，可安全放入属性
        body = f"<mstts:express-as style='{style}'>{body}</mstts:express-as>"
    return body


def build_ssml(text: str, voice: str, rate: int, volume: int, pitch: int, style: str = "") -> str:
    locale = "-".join(voice.split("-")[:2])
    return (
        f"<speak version='1.0' xmlns='http://www.w3.org/2001/10/synthesis' "
        f"xmlns:mstts='https://www.w3.org/2001/mstts' xml:lang='{locale}'>"
        f"<voice name='{voice}'>{ssml_body(text, rate, volume, pitch, style)}</voice></speak>"
    )


def estimate_cues(
    text: str, duration: float, offset: float = 0.0
) -> list[tuple[float, float, str]]:
    """把 duration 秒按句子权重分配给各句；权重 = 字数 + 标点停顿折算。"""
    sentences = [s.strip() for s in _SENTENCE.findall(text) if s.strip()]
    if not sentences or duration <= 0:
        return []

    def weight(sentence: str) -> float:
        letters = len(re.sub(r"\s", "", sentence))
        pauses = sum(sentence.count(c) for c in "，,、：:") * 2 + 4
        return letters + pauses

    weights = [weight(s) for s in sentences]
    total, cues, cursor = sum(weights), [], 0.0
    for sentence, w in zip(sentences, weights, strict=True):
        span = duration * w / total
        cues.append((offset + cursor, offset + cursor + span, sentence))
        cursor += span
    return cues


class AzureEngine:
    def __init__(
        self,
        credentials: AzureCredentials,
        proxy: str | None = None,
        base_url: str | None = None,
        usage: AzureUsage | None = None,
    ):
        self.credentials, self.proxy, self.base_url, self.usage = (
            credentials,
            proxy,
            base_url,
            usage,
        )

    def _setup(self) -> tuple[str, dict]:
        configured = self.credentials.get()
        if configured is None:
            raise EngineError(
                "engine_not_configured", "尚未配置 Azure 密钥和区域，请先在设置中填写"
            )
        region, key = configured
        base = self.base_url or endpoint(region)
        return base, {"Ocp-Apim-Subscription-Key": key, "User-Agent": USER_AGENT}

    @staticmethod
    async def _check(response: aiohttp.ClientResponse):
        status = response.status
        if status < 400:
            return
        if status == 401:
            raise EngineError("azure_auth", "Azure 密钥无效，或与所选区域不匹配，请在设置中检查")
        if status == 403:
            raise EngineError(
                "azure_forbidden", "Azure 拒绝了请求：可能已超出免费额度，或资源被停用"
            )
        if status == 429:
            raise EngineError(
                "azure_rate_limit", "Azure 请求过于频繁或额度已用尽，请稍后再试", True
            )
        if status == 400:
            detail = (await response.text())[:120].replace("\n", " ")
            raise EngineError(
                "azure_bad_request", f"Azure 不接受该请求（音色名或参数不被支持）：{detail}"
            )
        raise EngineError("upstream_http", f"Azure 服务返回 HTTP {status}", status >= 500)

    def _session(self) -> aiohttp.ClientSession:
        return aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=180, connect=15))

    async def voices(self) -> list[dict]:
        base, headers = self._setup()
        async with self._session() as session:
            async with session.get(
                f"{base}/cognitiveservices/voices/list", headers=headers, proxy=self.proxy
            ) as response:
                await self._check(response)
                items = await response.json(content_type=None)
        for item in items:
            # 与 Edge 的音色字段对齐，界面可统一展示；风格列表当作“性格标签”
            styles = item.get("StyleList") or []
            item.setdefault(
                "FriendlyName", f"{item.get('DisplayName', '')} - {item.get('LocaleName', '')}"
            )
            item["VoiceTag"] = {"VoicePersonalities": styles}
        return items

    async def synthesize(self, request: SynthesisRequest, audio: Path, subtitles: Path, progress):
        base, headers = self._setup()
        headers = {
            **headers,
            "Content-Type": "application/ssml+xml",
            "X-Microsoft-OutputFormat": OUTPUT_FORMAT,
        }
        cues, elapsed, size = [], 0.0, 0
        async with self._session() as session, aiofiles.open(audio, "wb") as stream:
            for chunk in split_text(request.text, chunk_limit(request.rate)):
                ssml = build_ssml(
                    chunk, request.voice, request.rate, request.volume, request.pitch, request.style
                )
                async with session.post(
                    f"{base}/cognitiveservices/v1",
                    data=ssml.encode("utf-8"),
                    headers=headers,
                    proxy=self.proxy,
                ) as response:
                    await self._check(response)
                    data = await response.read()
                if not data:
                    raise EngineError("no_audio", "Azure 没有返回音频，请检查音色或稍后重试", True)
                await stream.write(data)
                if self.usage is not None:  # 只统计成功的请求，与 Azure 计费一致
                    billed = ssml_body(
                        chunk, request.rate, request.volume, request.pitch, request.style
                    )
                    self.usage.add(billable_chars(billed))
                size += len(data)
                progress(size)
                length = mp3_duration(data)
                cues.extend(estimate_cues(chunk, length, elapsed))
                elapsed += length
        if request.subtitles:
            if not cues:
                raise RuntimeError("无法生成字幕时间")
            await asyncio.to_thread(subtitles.write_text, format_cues(cues), encoding="utf-8")
