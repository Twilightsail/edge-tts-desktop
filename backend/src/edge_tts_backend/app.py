import asyncio
import logging
import secrets
import tempfile
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Annotated

from fastapi import Depends, FastAPI, File, Query, Request, UploadFile
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse, PlainTextResponse, StreamingResponse
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from starlette.background import BackgroundTask
from starlette.exceptions import HTTPException

from . import __version__
from .config import Settings
from .diagnostics import about, read_logs
from .documents import MAX_UPLOAD, read_document
from .instance import InstanceLock
from .models import (
    AzureConfigRequest,
    AzureUsageRequest,
    BatchRequest,
    BulkRequest,
    EngineName,
    ExportRequest,
    FavoriteRequest,
    LogExportRequest,
    Preferences,
    PresetRequest,
    RenameRequest,
    SegmentRequest,
    Status,
    SynthesisRequest,
    TaskPage,
    TaskView,
    ZipRequest,
)
from .service import ServiceError, TaskService
from .store import Store
from .studio import Studio

PREVIEW_TEXT = {
    "zh": "你好，欢迎使用语音合成。这是一段音色试听。",
    "ja": "こんにちは。これは音声のサンプルです。",
    "ko": "안녕하세요. 음성 샘플입니다.",
    "fr": "Bonjour, voici un exemple de la voix sélectionnée.",
    "de": "Hallo, dies ist ein Beispiel der ausgewählten Stimme.",
    "es": "Hola, esta es una muestra de la voz seleccionada.",
    "ru": "Здравствуйте, это образец выбранного голоса.",
    "en": "Hello, welcome. This is a sample of the selected voice.",
}


def create_app(settings: Settings | None = None, engine=None, azure_engine=None) -> FastAPI:
    settings = settings or Settings()

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        settings.data_dir.mkdir(parents=True, exist_ok=True)
        with InstanceLock(settings.data_dir):
            store = Store(settings.data_dir / "history.sqlite3")
            try:
                service = TaskService(settings, store, engine, azure_engine)
                app.state.service = service
                try:
                    await service.start()
                    yield
                finally:
                    await service.stop()
            finally:
                store.close()

    bearer = HTTPBearer(auto_error=False)

    async def authenticate(
        credentials: Annotated[HTTPAuthorizationCredentials | None, Depends(bearer)],
    ):
        if credentials is None or not secrets.compare_digest(
            credentials.credentials.encode("utf-8"), settings.token.encode("utf-8")
        ):
            raise ServiceError(401, "unauthorized", "需要有效的会话令牌")

    app = FastAPI(
        title="Edge TTS Desktop Backend",
        version=__version__,
        lifespan=lifespan,
        dependencies=[Depends(authenticate)],
        docs_url=None,
        redoc_url=None,
        openapi_url=None,
    )
    app.add_middleware(
        CORSMiddleware,
        allow_origins=list(settings.origins),
        allow_methods=["GET", "POST", "PUT", "DELETE"],
        allow_headers=["Authorization", "Content-Type", "Range"],
        expose_headers=["Content-Range", "Accept-Ranges", "Content-Length"],
    )

    @app.exception_handler(ServiceError)
    async def service_error(request: Request, exc: ServiceError):
        return JSONResponse(
            status_code=exc.status,
            content={
                "error": {
                    "code": exc.code,
                    "message": exc.message,
                }
            },
            headers={"WWW-Authenticate": "Bearer"} if exc.status == 401 else None,
        )

    @app.exception_handler(RequestValidationError)
    async def validation_error(request: Request, exc: RequestValidationError):
        # Validation errors must not echo full input texts or filesystem paths.
        return JSONResponse(
            status_code=422,
            content={
                "error": {
                    "code": "validation_error",
                    "message": "请求参数不正确",
                    "details": [
                        {"field": ".".join(map(str, e["loc"])), "message": e["msg"]}
                        for e in exc.errors()
                    ],
                }
            },
        )

    @app.exception_handler(HTTPException)
    async def http_error(request: Request, exc: HTTPException):
        return JSONResponse(
            status_code=exc.status_code,
            content={
                "error": {
                    "code": "http_error",
                    "message": str(exc.detail),
                }
            },
        )

    @app.exception_handler(Exception)
    async def unexpected_error(request: Request, exc: Exception):
        logging.getLogger(__name__).error("Unexpected backend error: %s", type(exc).__name__)
        return JSONResponse(
            status_code=500,
            content={
                "error": {
                    "code": "internal_error",
                    "message": "后端内部错误，请查看日志并检查存储状态",
                }
            },
        )

    def service(request: Request) -> TaskService:
        return request.app.state.service

    def studio(request: Request) -> Studio:
        return Studio(service(request))

    @app.get("/api/health")
    async def health(request: Request):
        return {
            "status": "ready",
            "version": __version__,
            "concurrency": settings.concurrency,
            "pending": sum(
                service(request).store.page(s, 0, 1).total for s in (Status.queued, Status.running)
            ),
        }

    @app.get("/api/openapi.json", include_in_schema=False)
    async def schema():
        return app.openapi()

    @app.post("/api/shutdown", status_code=202)
    async def shutdown(request: Request):
        callback = getattr(request.app.state, "request_shutdown", None)
        if callback is None:
            raise ServiceError(409, "shutdown_unavailable", "当前宿主负责后端生命周期")
        callback()
        return {"status": "shutting_down"}

    @app.get("/api/voices")
    async def voices(
        request: Request,
        locale: str | None = None,
        gender: str | None = None,
        search: str = "",
        refresh: bool = False,
        engine: EngineName = "edge",
    ):
        result = await service(request).voices(refresh, engine)
        items = result["items"]
        if locale:
            items = [v for v in items if v.get("Locale", "").lower() == locale.lower()]
        if gender:
            items = [v for v in items if v.get("Gender", "").lower() == gender.lower()]
        if search:
            items = [
                v
                for v in items
                if search.lower()
                in " ".join(
                    str(v.get(k, "")) for k in ("ShortName", "FriendlyName", "Locale")
                ).lower()
            ]
        return {**result, "items": items, "total": len(items)}

    @app.post("/api/tasks", status_code=202, response_model=TaskView)
    async def create_task(body: SynthesisRequest, request: Request):
        return (await service(request).submit([body]))[0]

    @app.post("/api/tasks/batch", status_code=202, response_model=list[TaskView])
    async def batch(body: BatchRequest, request: Request):
        return await service(request).submit(body.items)

    @app.get("/api/tasks", response_model=TaskPage)
    async def tasks(
        request: Request,
        status: Status | None = None,
        offset: int = Query(0, ge=0),
        limit: int = Query(50, ge=1, le=200),
        search: str = Query("", max_length=300),
    ):
        return service(request).store.page(status, offset, limit, search)

    @app.post("/api/tasks/export-zip")
    async def archive(body: ZipRequest, request: Request):
        result = await studio(request).archive(body)
        if isinstance(result, dict):
            return result
        return FileResponse(
            result,
            media_type="application/zip",
            filename="edge-tts-export.zip",
            background=BackgroundTask(result.unlink, missing_ok=True),
        )

    @app.post("/api/tasks/delete-many")
    async def delete_many(body: BulkRequest, request: Request):
        return await studio(request).delete_many(body.ids)

    @app.put("/api/tasks/{task_id}/title", response_model=TaskView)
    async def rename(task_id: str, body: RenameRequest, request: Request):
        return await studio(request).rename(task_id, body)

    @app.get("/api/tasks/{task_id}", response_model=TaskView)
    async def task(task_id: str, request: Request):
        return service(request).require(task_id)

    @app.post("/api/tasks/{task_id}/cancel", response_model=TaskView)
    async def cancel(task_id: str, request: Request):
        return await service(request).cancel(task_id)

    @app.post("/api/tasks/{task_id}/retry", status_code=202, response_model=TaskView)
    async def retry(task_id: str, request: Request):
        return await service(request).retry(task_id)

    @app.delete("/api/tasks/{task_id}", status_code=204)
    async def delete(task_id: str, request: Request):
        await service(request).delete(task_id)

    @app.get("/api/tasks/{task_id}/audio")
    async def audio(task_id: str, request: Request):
        return FileResponse(service(request).artifact(task_id, "audio"), media_type="audio/mpeg")

    @app.get("/api/tasks/{task_id}/subtitles")
    async def subtitles(task_id: str, request: Request):
        return FileResponse(
            service(request).artifact(task_id, "subtitles"),
            media_type="application/x-subrip",
            filename=f"{task_id}.srt",
        )

    @app.get("/api/tasks/{task_id}/vtt")
    async def vtt(task_id: str, request: Request):
        return FileResponse(
            service(request).artifact(task_id, "vtt"),
            media_type="text/vtt",
            filename=f"{task_id}.vtt",
        )

    @app.post("/api/tasks/{task_id}/export")
    async def export(task_id: str, body: ExportRequest, request: Request):
        return await service(request).export(task_id, body)

    @app.get("/api/events")
    async def events(request: Request):
        instance = service(request)
        return StreamingResponse(
            instance.events.stream(instance.store),
            media_type="text/event-stream",
            headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
        )

    @app.get("/api/settings", response_model=Preferences)
    async def preferences(request: Request):
        return service(request).store.preferences()

    @app.put("/api/settings", response_model=Preferences)
    async def save_preferences(body: Preferences, request: Request):
        service(request).store.save_preferences(body)
        return body

    @app.get("/api/favorites")
    async def favorites(request: Request):
        return {"voices": studio(request).favorites()}

    @app.put("/api/favorites")
    async def save_favorites(body: FavoriteRequest, request: Request):
        service(request).store.put_cache("favorites", body.voices)
        return body

    @app.get("/api/presets")
    async def presets(request: Request):
        return studio(request).presets()

    @app.post("/api/presets", status_code=201)
    async def create_preset(body: PresetRequest, request: Request):
        return studio(request).save_preset(body)

    @app.put("/api/presets/{preset_id}")
    async def update_preset(preset_id: str, body: PresetRequest, request: Request):
        return studio(request).save_preset(body, preset_id)

    @app.delete("/api/presets/{preset_id}", status_code=204)
    async def delete_preset(preset_id: str, request: Request):
        studio(request).delete_preset(preset_id)

    @app.post("/api/voices/preview", status_code=202, response_model=TaskView)
    async def preview(body: Preferences, request: Request):
        text = PREVIEW_TEXT.get(body.voice.split("-")[0], PREVIEW_TEXT["en"])
        task = SynthesisRequest(
            **body.model_dump(), title="音色试听", segments=[SegmentRequest(text=text)]
        )
        return (await service(request).submit([task]))[0]

    @app.post("/api/documents/import")
    async def import_document(request: Request, file: Annotated[UploadFile, File()]):
        try:
            data = await file.read(MAX_UPLOAD + 1)
            return await asyncio.to_thread(read_document, file.filename or "document.txt", data)
        except Exception as exc:
            raise ServiceError(
                400,
                "document_invalid",
                str(exc) if isinstance(exc, ValueError) else "文档无法解析，请检查文件格式",
            ) from exc
        finally:
            await file.close()

    @app.get("/api/storage")
    async def storage(request: Request):
        return await studio(request).storage()

    @app.delete("/api/storage/segment-cache")
    async def clear_cache(request: Request):
        if not await service(request).pipeline.clear():
            raise ServiceError(409, "cache_busy", "分段合成正在运行，稍后再清理缓存")
        return {"cleared": True}

    @app.get("/api/engines")
    async def engines(request: Request):
        return {
            "engines": [
                {"id": "edge", "name": "Edge 在线语音", "configured": True},
                {
                    "id": "azure",
                    "name": "Azure AI Speech",
                    **service(request).credentials.info(),
                    "usage": service(request).usage.get(),
                },
            ]
        }

    @app.put("/api/engines/azure")
    async def save_azure(body: AzureConfigRequest, request: Request):
        instance = service(request)
        try:
            instance.credentials.save(body.region, body.key)
        except ValueError as exc:
            raise ServiceError(422, "key_required", str(exc)) from exc
        instance.store.put_cache("voices:azure", None)  # 换了密钥或区域，旧音色列表作废
        return instance.credentials.info()

    @app.delete("/api/engines/azure", status_code=204)
    async def delete_azure(request: Request):
        instance = service(request)
        instance.credentials.clear()
        instance.store.put_cache("voices:azure", None)

    @app.put("/api/engines/azure/usage")
    async def calibrate_usage(body: AzureUsageRequest, request: Request):
        """按 Azure 门户显示的数字校准本机估算的月用量或额度上限。"""
        if body.chars is None and body.limit is None:
            raise ServiceError(422, "usage_empty", "请至少提供 chars 或 limit")
        return service(request).usage.set(body.chars, body.limit)

    @app.post("/api/engines/azure/test")
    async def test_azure(request: Request):
        """用已保存的密钥拉一次音色列表：成功说明密钥与区域匹配。"""
        try:
            result = await service(request).voices(True, "azure", allow_stale=False)
        except ServiceError as exc:
            return {"ok": False, "code": exc.code, "message": exc.message}
        return {
            "ok": True,
            "voices": result["total"] if "total" in result else len(result["items"]),
        }

    @app.get("/api/about")
    async def about_info():
        return about(settings.data_dir)

    @app.get("/api/logs", response_class=PlainTextResponse)
    async def logs():
        return PlainTextResponse(await asyncio.to_thread(read_logs, settings.data_dir))

    @app.post("/api/logs/export")
    async def export_logs(body: LogExportRequest, request: Request):
        """把日志导出到应用数据目录之外的位置，便于发给开发者排查问题。"""
        text = await asyncio.to_thread(read_logs, settings.data_dir)
        target = await asyncio.to_thread(Path(body.destination).resolve)
        if (
            target.is_relative_to(settings.data_dir.resolve())
            or target.suffix.lower() not in (".log", ".txt")
            or not target.parent.is_dir()
        ):
            raise ServiceError(
                400, "invalid_destination", "请选择应用数据目录外的 .log 或 .txt 绝对路径"
            )
        with tempfile.NamedTemporaryFile(
            "w", suffix=".log", delete=False, encoding="utf-8"
        ) as handle:
            handle.write(text)
        source = Path(handle.name)
        try:
            await asyncio.to_thread(service(request).copy_export, source, target, body.overwrite)
        except FileExistsError as exc:
            raise ServiceError(409, "file_exists", "目标文件已存在") from exc
        except OSError as exc:
            raise ServiceError(400, "export_failed", "日志导出失败，请检查目录权限") from exc
        finally:
            await asyncio.to_thread(source.unlink, missing_ok=True)
        return {"destination": str(target), "bytes": len(text.encode("utf-8"))}

    return app
