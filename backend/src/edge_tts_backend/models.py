from enum import StrEnum
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


EngineName = Literal["edge", "azure"]
STYLE_PATTERN = r"^[A-Za-z0-9-]{0,40}$"  # Azure 说话风格，如 cheerful；空表示默认


class Status(StrEnum):
    queued = "queued"
    running = "running"
    succeeded = "succeeded"
    failed = "failed"
    cancelled = "cancelled"


class SegmentRequest(StrictModel):
    text: str = Field(min_length=1, max_length=100_000)
    title: str = Field(default="", max_length=120)
    voice: str | None = Field(default=None, pattern=r"^[A-Za-z0-9-]{1,120}$")
    rate: int | None = Field(default=None, ge=-90, le=100)
    volume: int | None = Field(default=None, ge=-100, le=100)
    pitch: int | None = Field(default=None, ge=-100, le=100)
    style: str | None = Field(default=None, pattern=STYLE_PATTERN)

    @field_validator("text")
    @classmethod
    def nonempty(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("段落文本不能为空")
        return value.strip()


class SynthesisRequest(StrictModel):
    engine: EngineName = "edge"
    style: str = Field(default="", pattern=STYLE_PATTERN)
    text: str = Field(default="", max_length=100_000)
    voice: str = Field(default="zh-CN-XiaoxiaoNeural", pattern=r"^[A-Za-z0-9-]{1,120}$")
    rate: int = Field(default=0, ge=-90, le=100)
    volume: int = Field(default=0, ge=-100, le=100)
    pitch: int = Field(default=0, ge=-100, le=100)
    subtitles: bool = True
    title: str = Field(default="", max_length=120)
    segments: list[SegmentRequest] = Field(default_factory=list, max_length=200)
    segment_chars: int = Field(default=2000, ge=100, le=5000)
    subtitle_max_chars: int = Field(default=24, ge=8, le=80)
    subtitle_offset_ms: int = Field(default=0, ge=-60000, le=60000)

    @field_validator("text")
    @classmethod
    def valid_text(cls, value: str) -> str:
        value = value.strip()
        if value and not any(c.isprintable() and not c.isspace() for c in value):
            raise ValueError("请输入有效文本")
        return value

    @model_validator(mode="after")
    def effective_text(self):
        if self.segments:
            self.text = "\n\n".join(s.text for s in self.segments)
        if not self.text.strip() or len(self.text) > 100_000:
            raise ValueError("任务文本须为 1～100000 字符，超长文档请拆为多个任务")
        return self


class BatchRequest(StrictModel):
    items: list[SynthesisRequest] = Field(min_length=1, max_length=50)


class TaskError(BaseModel):
    code: str
    message: str
    retryable: bool = False


class TaskView(BaseModel):
    id: str
    status: Status
    request: SynthesisRequest
    created_at: str
    updated_at: str
    stage: str
    attempt: int = 0
    audio_bytes: int = 0
    error: TaskError | None = None
    audio_url: str | None = None
    subtitles_url: str | None = None
    vtt_url: str | None = None
    duration_seconds: float = 0
    segment_total: int = 1
    segment_completed: int = 0
    chapters: list[dict] = Field(default_factory=list)


class TaskPage(BaseModel):
    items: list[TaskView]
    total: int
    offset: int
    limit: int


class ExportRequest(StrictModel):
    destination: str = Field(min_length=1, max_length=4096)
    kind: str = Field(default="audio", pattern=r"^(audio|subtitles|vtt)$")
    overwrite: bool = False

    @field_validator("destination")
    @classmethod
    def absolute_destination(cls, value: str) -> str:
        if "\x00" in value or not Path(value).is_absolute():
            raise ValueError("导出路径必须为绝对路径")
        return value


class Preferences(StrictModel):
    engine: EngineName = "edge"
    style: str = Field(default="", pattern=STYLE_PATTERN)
    voice: str = Field(default="zh-CN-XiaoxiaoNeural", pattern=r"^[A-Za-z0-9-]{1,120}$")
    rate: int = Field(default=0, ge=-90, le=100)
    volume: int = Field(default=0, ge=-100, le=100)
    pitch: int = Field(default=0, ge=-100, le=100)
    subtitles: bool = True
    subtitle_max_chars: int = Field(default=24, ge=8, le=80)
    subtitle_offset_ms: int = Field(default=0, ge=-60000, le=60000)


class PresetRequest(StrictModel):
    name: str = Field(min_length=1, max_length=60)
    settings: Preferences


class FavoriteRequest(StrictModel):
    voices: list[str] = Field(max_length=200)

    @field_validator("voices")
    @classmethod
    def valid_voices(cls, values):
        import re

        if any(not re.fullmatch(r"(azure:)?[A-Za-z0-9-]{1,120}", v) for v in values):
            raise ValueError("音色标识不正确")
        return list(dict.fromkeys(values))


class RenameRequest(StrictModel):
    title: str = Field(max_length=120)


class BulkRequest(StrictModel):
    ids: list[str] = Field(min_length=1, max_length=200)


class ZipRequest(BulkRequest):
    destination: str | None = None
    overwrite: bool = False
    include_subtitles: bool = True

    @field_validator("destination")
    @classmethod
    def absolute_path(cls, value):
        return ExportRequest.absolute_destination(value) if value else value


class AzureUsageRequest(StrictModel):
    chars: int | None = Field(default=None, ge=0, le=1_000_000_000)
    limit: int | None = Field(default=None, ge=1, le=1_000_000_000)


class AzureConfigRequest(StrictModel):
    region: str = Field(pattern=r"^[a-z0-9]{3,30}$")
    # 省略表示沿用已保存的密钥，只更新区域；密钥只写不读，接口不会返回它
    key: str | None = Field(default=None, pattern=r"^[A-Za-z0-9]{16,128}$")


class LogExportRequest(StrictModel):
    destination: str = Field(min_length=1, max_length=4096)
    overwrite: bool = False

    @field_validator("destination")
    @classmethod
    def absolute_destination(cls, value: str) -> str:
        if "\x00" in value or not Path(value).is_absolute():
            raise ValueError("导出路径必须为绝对路径")
        return value
