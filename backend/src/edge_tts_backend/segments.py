import asyncio
import hashlib
import json
import os
import re
import shutil
import subprocess
import wave
from pathlib import Path

import imageio_ffmpeg

from .models import SegmentRequest, SynthesisRequest
from .mp3 import mp3_file_duration
from .subtitles import format_cues, parse_srt


def split_text(text: str, limit: int) -> list[str]:
    result = []
    while len(text) > limit:
        candidates = [m.end() for m in re.finditer(r"[。！？.!?\n]\s*", text[:limit])]
        cut = candidates[-1] if candidates and candidates[-1] >= limit // 2 else limit
        if text[:cut].strip():
            result.append(text[:cut].strip())
        text = text[cut:]
    if text.strip():
        result.append(text.strip())
    return result


def resolved_segments(request: SynthesisRequest) -> list[tuple[str, SynthesisRequest]]:
    sources = request.segments or [SegmentRequest(text=request.text, title=request.title)]
    result = []
    for index, source in enumerate(sources):
        for part_index, part in enumerate(split_text(source.text, request.segment_chars)):
            options = {
                key: getattr(source, key)
                if getattr(source, key) is not None
                else getattr(request, key)
                for key in ("voice", "rate", "volume", "pitch", "style")
            }
            label = source.title or f"第 {index + 1} 段"
            if len(source.text) > request.segment_chars:
                label += f" · {part_index + 1}"
            result.append(
                (
                    label,
                    SynthesisRequest(text=part, subtitles=True, engine=request.engine, **options),
                )
            )
    if len(result) > 1000:
        raise ValueError("分段过多，请增加每段字符数")
    return result


def audio_duration(path: Path) -> float:
    try:
        return mp3_file_duration(path)
    except OSError:
        return 0.0


async def ffmpeg(*args):
    executable = imageio_ffmpeg.get_ffmpeg_exe()
    kwargs = {"creationflags": subprocess.CREATE_NO_WINDOW} if os.name == "nt" else {}
    process = await asyncio.create_subprocess_exec(
        executable,
        "-hide_banner",
        "-loglevel",
        "error",
        "-nostdin",
        "-y",
        *map(str, args),
        stdout=asyncio.subprocess.DEVNULL,
        stderr=asyncio.subprocess.PIPE,
        **kwargs,
    )
    try:
        async with asyncio.timeout(180):
            _, errors = await process.communicate()
        if process.returncode:
            raise RuntimeError("音频拼接或解码失败：" + errors.decode(errors="replace")[-200:])
    finally:
        if process.returncode is None:
            process.kill()
            await process.wait()


def join_waves(paths: list[Path], output: Path) -> list[float]:
    durations = []
    with wave.open(str(output), "wb") as dest:
        dest.setparams((1, 2, 24000, 0, "NONE", "not compressed"))
        for path in paths:
            with wave.open(str(path), "rb") as source:
                if (source.getnchannels(), source.getsampwidth(), source.getframerate()) != (
                    1,
                    2,
                    24000,
                ):
                    raise ValueError("Invalid cached segment format")
                durations.append(source.getnframes() / source.getframerate())
                while frames := source.readframes(65536):
                    dest.writeframesraw(frames)
    return durations


class SegmentPipeline:
    def __init__(self, cache: Path, engines):
        self.cache, self.engines = cache, engines
        self.cache.mkdir(parents=True, exist_ok=True)
        self.locks: dict[str, asyncio.Lock] = {}
        self.maintenance = asyncio.Lock()
        self.active = 0

    async def synthesize(self, request, audio, subtitle, progress, chapter_progress):
        async with self.maintenance:
            self.active += 1
        try:
            await self._synthesize(request, audio, subtitle, progress, chapter_progress)
        finally:
            async with self.maintenance:
                self.active -= 1

    async def _synthesize(self, request, audio, subtitle, progress, chapter_progress):
        plans = resolved_segments(request)
        chapters = [
            {
                "index": i,
                "title": title,
                "voice": part.voice,
                "status": "queued",
                "cached": False,
                "duration_seconds": 0,
            }
            for i, (title, part) in enumerate(plans)
        ]
        chapter_progress(chapters)
        paths, subtitles, bytes_received = [], [], 0
        for i, (_, part) in enumerate(plans):
            key = hashlib.sha256(
                json.dumps(
                    {
                        "text": part.text,
                        "voice": part.voice,
                        "rate": part.rate,
                        "volume": part.volume,
                        "pitch": part.pitch,
                        "cache_version": 1,
                        # 仅非默认引擎写入键，保持已有 Edge 缓存继续有效
                        **({"engine": part.engine} if part.engine != "edge" else {}),
                        **({"style": part.style} if part.style else {}),
                    },
                    ensure_ascii=False,
                    sort_keys=True,
                ).encode()
            ).hexdigest()
            folder = self.cache / key
            lock = self.locks.setdefault(key, asyncio.Lock())
            async with lock:
                cached = (folder / "complete.json").is_file()
                if cached:
                    try:
                        metadata = json.loads((folder / "complete.json").read_text())
                        cached = (folder / "audio.wav").is_file() and (folder / "raw.srt").is_file()
                    except (OSError, ValueError):
                        cached = False
                if not cached:
                    folder.mkdir(exist_ok=True)
                    raw = folder / "source.mp3.part"
                    raw_srt = folder / "raw.srt.part"
                    wav = folder / "audio.wav.part"
                    chapters[i]["status"] = "running"
                    chapter_progress(chapters)
                    try:
                        await self.engines.get(part.engine).synthesize(
                            part,
                            raw,
                            raw_srt,
                            lambda size, base=bytes_received: progress(base + size),
                        )
                        await ffmpeg("-i", raw, "-ac", "1", "-ar", "24000", "-f", "wav", wav)
                        duration = await asyncio.to_thread(self.wave_duration, wav)
                        metadata = {"duration": duration, "source_bytes": raw.stat().st_size}
                        wav.replace(folder / "audio.wav")
                        raw_srt.replace(folder / "raw.srt")
                        (folder / "complete.json.part").write_text(json.dumps(metadata))
                        (folder / "complete.json.part").replace(folder / "complete.json")
                    finally:
                        for partial in folder.glob("*.part"):
                            partial.unlink(missing_ok=True)
                paths.append(folder / "audio.wav")
                subtitles.append(parse_srt((folder / "raw.srt").read_text(encoding="utf-8")))
                bytes_received += metadata["source_bytes"]
                chapters[i].update(
                    status="succeeded", cached=cached, duration_seconds=metadata["duration"]
                )
                chapter_progress(chapters)
                progress(bytes_received)
        joined = audio.parent / "joined.wav.part"
        try:
            durations = await asyncio.to_thread(join_waves, paths, joined)
            await ffmpeg("-i", joined, "-c:a", "libmp3lame", "-b:a", "48k", "-f", "mp3", audio)
            combined, offset = [], 0.0
            for duration, cues in zip(durations, subtitles, strict=True):
                combined.extend(
                    (offset + max(0, a), offset + min(duration, b), text)
                    for a, b, text in cues
                    if a < duration
                )
                offset += duration
            if request.subtitles:
                await asyncio.to_thread(
                    subtitle.write_text, format_cues(combined), encoding="utf-8"
                )
        finally:
            joined.unlink(missing_ok=True)

    @staticmethod
    def wave_duration(path):
        with wave.open(str(path), "rb") as source:
            return source.getnframes() / source.getframerate()

    async def clear(self):
        async with self.maintenance:
            if self.active:
                return False
            await asyncio.to_thread(shutil.rmtree, self.cache)
            self.cache.mkdir(parents=True)
            self.locks.clear()
            return True
