import asyncio
import contextlib
import json
import logging
import os
import shutil
import tempfile
import time
from pathlib import Path

from .config import Settings
from .engine import EdgeEngine, classify_error
from .engine_azure import AzureEngine
from .models import ExportRequest, Status, SynthesisRequest, TaskError, TaskView
from .secrets_store import AzureCredentials
from .segments import SegmentPipeline, audio_duration
from .store import Store
from .subtitles import format_cues, optimize, parse_srt
from .usage import AzureUsage

logger = logging.getLogger(__name__)
TERMINAL = {Status.succeeded, Status.failed, Status.cancelled}


class ServiceError(Exception):
    def __init__(self, status: int, code: str, message: str):
        self.status, self.code, self.message = status, code, message


class Events:
    def __init__(self):
        self.subscribers: set[asyncio.Queue] = set()

    def publish(self, event: str, data):
        item = {"event": event, "data": data}
        for queue in tuple(self.subscribers):
            if queue.full():
                while not queue.empty():
                    queue.get_nowait()
                queue.put_nowait({"event": "resync", "data": {"reason": "slow_consumer"}})
            if not queue.full():
                queue.put_nowait(item)

    async def stream(self, store: Store):
        queue: asyncio.Queue = asyncio.Queue(maxsize=128)
        self.subscribers.add(queue)
        try:
            page = store.page(None, 0, 100)
            yield self.encode(
                "snapshot",
                {
                    "items": [task_event(task) for task in page.items],
                    "total": page.total,
                    "offset": page.offset,
                    "limit": page.limit,
                },
            )
            while True:
                try:
                    item = await asyncio.wait_for(queue.get(), timeout=15)
                    yield self.encode(item["event"], item["data"])
                except TimeoutError:
                    yield ": heartbeat\n\n"
        finally:
            self.subscribers.discard(queue)

    @staticmethod
    def encode(event: str, data) -> str:
        return f"event: {event}\ndata: {json.dumps(data, ensure_ascii=False)}\n\n"


def task_event(task: TaskView) -> dict:
    # Text is available from GET /api/tasks/{id}; avoid broadcasting it on every audio chunk.
    return task.model_dump(mode="json", exclude={"request"})


class EngineHub:
    """按名称取得合成引擎。两个引擎的音色名可能相同，所以必须带引擎名选择。"""

    def __init__(self, edge, azure):
        self.engines = {"edge": edge, "azure": azure}

    def get(self, name: str):
        return self.engines[name]


class TaskService:
    def __init__(self, settings: Settings, store: Store, engine=None, azure=None):
        self.settings, self.store = settings, store
        self.engine = engine if engine is not None else EdgeEngine(settings.proxy)
        self.credentials = AzureCredentials(store)
        self.usage = AzureUsage(store)
        self.azure = (
            azure
            if azure is not None
            else AzureEngine(self.credentials, settings.proxy, settings.azure_base_url, self.usage)
        )
        self.engines = EngineHub(self.engine, self.azure)
        self.events = Events()
        self.queue: asyncio.Queue[str] = asyncio.Queue()
        self.running: dict[str, asyncio.Task] = {}
        self.workers: list[asyncio.Task] = []
        self.lock = asyncio.Lock()
        self.voice_lock = asyncio.Lock()
        self.stopping = False
        self.files = settings.data_dir / "tasks"
        self.files.mkdir(parents=True, exist_ok=True)
        self.pipeline = SegmentPipeline(settings.data_dir / "segment-cache", self.engines)

    async def start(self):
        for task in self.store.recover():
            self.queue.put_nowait(task.id)
        # A crash can leave partial files; never present them as completed results.
        await asyncio.to_thread(self.clean_partial_files)
        self.workers = [
            asyncio.create_task(self.worker()) for _ in range(self.settings.concurrency)
        ]

    def clean_partial_files(self):
        for path in list(self.files.glob("*/*.part")) + list(self.pipeline.cache.glob("*/*.part")):
            path.unlink(missing_ok=True)

    async def stop(self):
        self.stopping = True
        for worker in self.workers:
            worker.cancel()
        await asyncio.gather(*self.workers, return_exceptions=True)
        self.workers.clear()

    def require(self, task_id: str) -> TaskView:
        task = self.store.get(task_id)
        if task is None:
            raise ServiceError(404, "task_not_found", "任务不存在")
        return task

    def change(self, task_id: str, **changes) -> TaskView:
        task = self.store.update(task_id, **changes)
        self.events.publish("task.updated", task_event(task))
        return task

    def require_engine(self, name: str):
        if name == "azure" and self.credentials.get() is None:
            raise ServiceError(
                409, "engine_not_configured", "尚未配置 Azure 密钥和区域，请先在设置中填写"
            )

    async def submit(self, requests: list[SynthesisRequest]) -> list[TaskView]:
        for request in requests:
            self.require_engine(request.engine)
        async with self.lock:
            pending = sum(
                self.store.page(status, 0, 1).total for status in (Status.queued, Status.running)
            )
            if pending + len(requests) > self.settings.max_pending:
                raise ServiceError(429, "queue_full", "待处理任务已达到上限，请稍后再试")
            tasks = self.store.create(requests)
            for task in tasks:
                self.events.publish("task.created", task_event(task))
                self.queue.put_nowait(task.id)
            return tasks

    async def worker(self):
        while True:
            task_id = await self.queue.get()
            try:
                task = self.store.get(task_id)
                if task is None or task.status != Status.queued:
                    continue
                runner = asyncio.create_task(self.run(task))
                self.running[task_id] = runner
                try:
                    await runner
                except asyncio.CancelledError:
                    if self.stopping:
                        raise
            finally:
                self.running.pop(task_id, None)
                self.queue.task_done()

    async def run(self, task: TaskView):
        directory = self.files / task.id
        audio = directory / "audio.mp3.part"
        subtitle = directory / "subtitles.srt.part"
        try:
            directory.mkdir(exist_ok=True)
            self.change(task.id, status=Status.running, stage="synthesizing", error=None)
            for attempt in range(1, self.settings.attempts + 1):
                audio.unlink(missing_ok=True)
                subtitle.unlink(missing_ok=True)
                self.change(task.id, attempt=attempt, audio_bytes=0, stage="synthesizing")
                try:
                    async with asyncio.timeout(self.settings.task_timeout):

                        def progress(size):
                            self.change(task.id, audio_bytes=size)

                        if (
                            task.request.segments
                            or len(task.request.text) > task.request.segment_chars
                        ):

                            def chapter_progress(chapters):
                                self.change(
                                    task.id,
                                    chapters=chapters,
                                    segment_total=len(chapters),
                                    segment_completed=sum(
                                        c["status"] == "succeeded" for c in chapters
                                    ),
                                )

                            await self.pipeline.synthesize(
                                task.request, audio, subtitle, progress, chapter_progress
                            )
                        else:
                            await self.engines.get(task.request.engine).synthesize(
                                task.request, audio, subtitle, progress
                            )
                            self.change(task.id, segment_total=1, segment_completed=1)
                    if not audio.exists() or audio.stat().st_size == 0:
                        raise RuntimeError("Missing audio output")
                    if task.request.subtitles and not subtitle.exists():
                        raise RuntimeError("Missing subtitle output")
                    self.change(task.id, stage="finalizing")
                    if task.request.subtitles:
                        raw = await asyncio.to_thread(subtitle.read_text, encoding="utf-8")
                        cues = optimize(
                            parse_srt(raw),
                            task.request.subtitle_max_chars,
                            task.request.subtitle_offset_ms,
                        )
                        await asyncio.to_thread(
                            subtitle.write_text, format_cues(cues), encoding="utf-8"
                        )
                        await asyncio.to_thread(
                            (directory / "subtitles.vtt").write_text,
                            format_cues(cues, vtt=True),
                            encoding="utf-8",
                        )
                    audio.replace(directory / "audio.mp3")
                    if task.request.subtitles:
                        subtitle.replace(directory / "subtitles.srt")
                    self.change(
                        task.id,
                        status=Status.succeeded,
                        stage="completed",
                        error=None,
                        audio_bytes=(directory / "audio.mp3").stat().st_size,
                        audio_url=f"/api/tasks/{task.id}/audio",
                        subtitles_url=(
                            f"/api/tasks/{task.id}/subtitles" if task.request.subtitles else None
                        ),
                        vtt_url=f"/api/tasks/{task.id}/vtt" if task.request.subtitles else None,
                        duration_seconds=await asyncio.to_thread(
                            audio_duration, directory / "audio.mp3"
                        ),
                    )
                    return
                except Exception as exc:
                    error = classify_error(exc)
                    # Do not log user text or raw upstream payloads.
                    logger.warning(
                        "Task %s attempt %s failed: %s (%s)",
                        task.id,
                        attempt,
                        error.code,
                        type(exc).__name__,
                    )
                    if not error.retryable or attempt == self.settings.attempts:
                        self.change(task.id, status=Status.failed, stage="failed", error=error)
                        return
                    self.change(task.id, stage="retry_wait", error=error)
                    await asyncio.sleep(min(2**attempt, 8))
        except asyncio.CancelledError:
            if self.stopping:
                self.change(
                    task.id,
                    status=Status.failed,
                    stage="interrupted",
                    error=TaskError(
                        code="interrupted",
                        message="后端关闭，合成任务中断，请重试",
                        retryable=True,
                    ),
                )
            else:
                self.change(task.id, status=Status.cancelled, stage="cancelled", error=None)
            raise
        except Exception as exc:
            self.change(task.id, status=Status.failed, stage="failed", error=classify_error(exc))
        finally:
            try:
                audio.unlink(missing_ok=True)
                subtitle.unlink(missing_ok=True)
                current = self.store.get(task.id)
                if current and current.status != Status.succeeded:
                    for path in directory.glob("*"):
                        path.unlink(missing_ok=True)
            except OSError:
                logger.warning(
                    "Could not clean task %s artifacts; check directory permissions", task.id
                )

    async def cancel(self, task_id: str) -> TaskView:
        async with self.lock:
            task = self.require(task_id)
            if task.status in TERMINAL:
                return task
            runner = self.running.get(task_id)
            if runner:
                runner.cancel()
                with contextlib.suppress(asyncio.CancelledError):
                    await runner
            # Also covers a runner cancelled before its first instruction executes.
            return self.change(task_id, status=Status.cancelled, stage="cancelled", error=None)

    async def retry(self, task_id: str) -> TaskView:
        task = self.require(task_id)
        if task.status not in {Status.failed, Status.cancelled}:
            raise ServiceError(409, "invalid_state", "仅失败或取消的任务可以重试")
        return (await self.submit([task.request]))[0]

    async def delete(self, task_id: str):
        async with self.lock:
            task = self.require(task_id)
            if task.status not in TERMINAL:
                raise ServiceError(409, "task_active", "请先取消任务再删除")
            directory = self.files / task_id
            if directory.exists():
                try:
                    await asyncio.to_thread(shutil.rmtree, directory)
                except OSError as exc:
                    raise ServiceError(
                        409, "delete_failed", "文件删除失败，请检查是否被占用"
                    ) from exc
            self.store.delete(task_id)
            self.events.publish("task.deleted", {"id": task_id})

    def artifact(self, task_id: str, kind: str) -> Path:
        task = self.require(task_id)
        if task.status != Status.succeeded:
            raise ServiceError(409, "task_not_ready", "任务尚未成功完成")
        filename = {"audio": "audio.mp3", "subtitles": "subtitles.srt", "vtt": "subtitles.vtt"}[
            kind
        ]
        path = self.files / task_id / filename
        if not path.is_file():
            raise ServiceError(404, "artifact_not_found", "输出文件不存在")
        return path

    async def export(self, task_id: str, request: ExportRequest) -> dict:
        async with self.lock:
            source = self.artifact(task_id, request.kind)
            target = await asyncio.to_thread(Path(request.destination).resolve)
            if target == self.settings.data_dir.resolve() or target.is_relative_to(
                self.settings.data_dir.resolve()
            ):
                raise ServiceError(400, "internal_destination", "请导出到应用数据目录之外")
            suffix = {"audio": ".mp3", "subtitles": ".srt", "vtt": ".vtt"}[request.kind]
            if target.suffix.lower() != suffix:
                raise ServiceError(400, "invalid_extension", f"导出文件扩展名必须为 {suffix}")
            if not target.parent.is_dir():
                raise ServiceError(400, "directory_not_found", "导出目录不存在")
            try:
                await asyncio.to_thread(self.copy_export, source, target, request.overwrite)
            except FileExistsError as exc:
                raise ServiceError(409, "file_exists", "目标文件已存在") from exc
            except OSError as exc:
                raise ServiceError(
                    400, "export_failed", "导出失败，请检查目录权限和磁盘空间"
                ) from exc
            return {"destination": str(target), "bytes": source.stat().st_size}

    @staticmethod
    def copy_export(source: Path, target: Path, overwrite: bool):
        # Same-directory temporary file makes replacement atomic.
        fd, name = tempfile.mkstemp(prefix=".edge-tts-", suffix=".tmp", dir=target.parent)
        temporary = Path(name)
        try:
            with os.fdopen(fd, "wb") as output, source.open("rb") as input_file:
                shutil.copyfileobj(input_file, output)
                output.flush()
                os.fsync(output.fileno())
            if overwrite:
                os.replace(temporary, target)
            elif os.name == "nt":
                os.rename(temporary, target)
            else:
                # A hard link atomically refuses existing files, including concurrent writes.
                os.link(temporary, target)
        finally:
            temporary.unlink(missing_ok=True)

    async def voices(
        self, refresh: bool = False, engine: str = "edge", allow_stale: bool = True
    ) -> dict:
        self.require_engine(engine)
        key = "voices" if engine == "edge" else f"voices:{engine}"
        async with self.voice_lock:
            cache = self.store.get_cache(key)
            if (
                not refresh
                and cache
                and time.time() - cache["timestamp"] < (self.settings.voice_cache_seconds)
            ):
                return {**cache, "cached": True, "stale": False}
            try:
                voices = await self.engines.get(engine).voices()
                if not voices:
                    raise RuntimeError("Empty voice list")
            except Exception as exc:
                if cache and allow_stale:
                    return {**cache, "cached": True, "stale": True}
                error = classify_error(exc)
                raise ServiceError(503, "voices_unavailable", error.message) from exc
            cache = {"items": voices, "timestamp": time.time()}
            self.store.put_cache(key, cache)
            return {**cache, "cached": False, "stale": False}
