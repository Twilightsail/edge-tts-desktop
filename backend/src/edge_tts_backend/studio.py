import asyncio
import json
import re
import tempfile
import zipfile
from pathlib import Path
from uuid import uuid4

from .models import PresetRequest, RenameRequest, ZipRequest
from .service import ServiceError, TaskService


class Studio:
    def __init__(self, service: TaskService):
        self.service, self.store = service, service.store

    def favorites(self):
        return self.store.get_cache("favorites") or []

    def presets(self):
        return self.store.get_cache("presets") or []

    def save_preset(self, body: PresetRequest, preset_id: str | None = None):
        with self.store.lock:
            presets = self.presets()
            if preset_id and not any(p["id"] == preset_id for p in presets):
                raise ServiceError(404, "preset_not_found", "预设不存在")
            if not preset_id and len(presets) >= 100:
                raise ServiceError(409, "preset_limit", "最多保存 100 个预设")
            preset = {"id": preset_id or uuid4().hex, **body.model_dump()}
            presets = [p for p in presets if p["id"] != preset["id"]] + [preset]
            self.store.put_cache("presets", presets)
            return preset

    def delete_preset(self, preset_id: str):
        with self.store.lock:
            presets = self.presets()
            if not any(p["id"] == preset_id for p in presets):
                raise ServiceError(404, "preset_not_found", "预设不存在")
            self.store.put_cache("presets", [p for p in presets if p["id"] != preset_id])

    async def rename(self, task_id: str, body: RenameRequest):
        async with self.service.lock:
            task = self.service.require(task_id)
            updated = task.request.model_copy(update={"title": body.title})
            return self.service.change(task_id, request=updated)

    async def delete_many(self, ids: list[str]):
        removed, errors = [], []
        for task_id in dict.fromkeys(ids):
            try:
                await self.service.delete(task_id)
                removed.append(task_id)
            except ServiceError as exc:
                errors.append({"id": task_id, "code": exc.code, "message": exc.message})
        return {"deleted": removed, "errors": errors}

    async def archive(self, request: ZipRequest):
        async with self.service.lock:
            tasks = [self.service.require(task_id) for task_id in dict.fromkeys(request.ids)]
            paths = [self.service.artifact(task.id, "audio") for task in tasks]
            root = self.service.settings.data_dir / "exports"
            root.mkdir(exist_ok=True)
            with tempfile.NamedTemporaryFile(dir=root, suffix=".zip", delete=False) as handle:
                output = Path(handle.name)
            try:
                await asyncio.to_thread(
                    self.build_zip, output, tasks, paths, request.include_subtitles
                )
                if request.destination:
                    target = await asyncio.to_thread(Path(request.destination).resolve)
                    data = self.service.settings.data_dir.resolve()
                    if (
                        target.is_relative_to(data)
                        or target.suffix.lower() != ".zip"
                        or not target.parent.is_dir()
                    ):
                        raise ServiceError(
                            400, "invalid_destination", "请选择应用数据目录外的 ZIP 绝对路径"
                        )
                    try:
                        await asyncio.to_thread(
                            self.service.copy_export, output, target, request.overwrite
                        )
                    except FileExistsError as exc:
                        raise ServiceError(409, "file_exists", "目标文件已存在") from exc
                    except OSError as exc:
                        raise ServiceError(
                            400, "export_failed", "ZIP 导出失败，请检查目录权限"
                        ) from exc
                    result = {
                        "destination": str(target),
                        "bytes": (await asyncio.to_thread(output.stat)).st_size,
                        "tasks": len(tasks),
                    }
                    await asyncio.to_thread(output.unlink, missing_ok=True)
                    return result
                return output
            except BaseException:
                await asyncio.to_thread(output.unlink, missing_ok=True)
                raise

    @staticmethod
    def build_zip(output, tasks, paths, include_subtitles):
        manifest = []
        with zipfile.ZipFile(
            output, "w", compression=zipfile.ZIP_STORED, allowZip64=True
        ) as archive:
            for index, (task, path) in enumerate(zip(tasks, paths, strict=True), 1):
                title = task.request.title or task.request.text[:30] or task.id
                title = re.sub(r'[<>:"/\\|?*\x00-\x1f]', "_", title).strip(". ")[:80]
                name = f"{index:03d}_{title or task.id}"
                archive.write(path, name + ".mp3")
                if include_subtitles:
                    for suffix in ("srt", "vtt"):
                        subtitle = path.parent / f"subtitles.{suffix}"
                        if subtitle.is_file():
                            archive.write(subtitle, name + "." + suffix)
                manifest.append(
                    {
                        "id": task.id,
                        "filename": name + ".mp3",
                        "title": task.request.title,
                        "duration_seconds": task.duration_seconds,
                    }
                )
            archive.writestr("manifest.json", json.dumps(manifest, ensure_ascii=False, indent=2))

    async def storage(self):
        def sizes():
            cache = sum(
                p.stat().st_size for p in self.service.pipeline.cache.rglob("*") if p.is_file()
            )
            audio = sum(p.stat().st_size for p in self.service.files.rglob("*") if p.is_file())
            return {
                "cache_bytes": cache,
                "task_bytes": audio,
                "tasks": self.store.page(None, 0, 1).total,
            }

        return await asyncio.to_thread(sizes)
