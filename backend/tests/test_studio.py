import asyncio
import io
import json
import shutil
import subprocess
import wave
import zipfile

import imageio_ffmpeg
import pytest
from fastapi.testclient import TestClient
from test_backend import AUTH, FakeEngine, submit, wait_for

from edge_tts_backend.app import create_app
from edge_tts_backend.config import Settings
from edge_tts_backend.documents import MAX_UPLOAD, read_document
from edge_tts_backend.models import SegmentRequest, Status, SynthesisRequest
from edge_tts_backend.segments import resolved_segments, split_text
from edge_tts_backend.store import Store
from edge_tts_backend.subtitles import optimize, parse_srt


@pytest.fixture(scope="module")
def sample_audio(tmp_path_factory):
    root = tmp_path_factory.mktemp("media")
    wav, mp3 = root / "source.wav", root / "source.mp3"
    with wave.open(str(wav), "wb") as output:
        output.setparams((1, 2, 24000, 0, "NONE", "not compressed"))
        output.writeframes(b"\x00\x00" * 24000)
    subprocess.run(
        [
            imageio_ffmpeg.get_ffmpeg_exe(),
            "-hide_banner",
            "-loglevel",
            "error",
            "-i",
            str(wav),
            "-c:a",
            "libmp3lame",
            "-b:a",
            "48k",
            str(mp3),
        ],
        check=True,
        creationflags=subprocess.CREATE_NO_WINDOW,
    )
    return mp3


class MediaEngine:
    def __init__(self, sample, fail_text=None, delay=0):
        self.sample, self.fail_text, self.delay = sample, fail_text, delay
        self.calls = []

    async def voices(self):
        return await FakeEngine().voices()

    async def synthesize(self, request, audio, subtitle, progress):
        self.calls.append((request.text, request.voice))
        if request.text == self.fail_text:
            raise ValueError("synthetic failure")
        await asyncio.sleep(self.delay)
        await asyncio.to_thread(shutil.copyfile, self.sample, audio)
        if request.subtitles:
            subtitle.write_text(
                f"1\n00:00:00,000 --> 00:00:00,900\n{request.text}\n", encoding="utf-8"
            )
        progress(audio.stat().st_size)


def test_presets_and_favorites_persist(tmp_path):
    settings = Settings(data_dir=tmp_path, token="test-secret")
    with TestClient(create_app(settings, FakeEngine())) as client:
        result = client.put(
            "/api/favorites",
            headers=AUTH,
            json={"voices": ["zh-CN-XiaoxiaoNeural", "zh-CN-XiaoxiaoNeural"]},
        )
        assert result.json()["voices"] == ["zh-CN-XiaoxiaoNeural"]
        assert (
            client.put("/api/favorites", headers=AUTH, json={"voices": ["<voice>"]}).status_code
            == 422
        )
        preset = client.post(
            "/api/presets", headers=AUTH, json={"name": "旁白", "settings": {"rate": -10}}
        ).json()
        preset_id = preset["id"]
        assert (
            client.put(
                f"/api/presets/{preset_id}",
                headers=AUTH,
                json={"name": "慢读", "settings": {"rate": -20}},
            ).status_code
            == 200
        )
    with TestClient(create_app(settings, FakeEngine())) as client:
        assert client.get("/api/favorites", headers=AUTH).json()["voices"] == [
            "zh-CN-XiaoxiaoNeural"
        ]
        assert client.get("/api/presets", headers=AUTH).json()[0]["settings"]["rate"] == -20
        assert client.delete(f"/api/presets/{preset_id}", headers=AUTH).status_code == 204
        assert client.get("/api/presets", headers=AUTH).json() == []
        assert client.delete(f"/api/presets/{preset_id}", headers=AUTH).status_code == 404


@pytest.mark.parametrize("encoding", ["utf-8-sig", "gb18030", "utf-16"])
def test_import_encoding_and_no_truncation(tmp_path, encoding):
    text = "中文正文。\n\n第二段。" * 10000
    with TestClient(
        create_app(Settings(data_dir=tmp_path, token="test-secret"), FakeEngine())
    ) as client:
        response = client.post(
            "/api/documents/import",
            headers=AUTH,
            files={"file": ("文章.txt", text.encode(encoding), "text/plain")},
        )
        assert response.status_code == 200
        assert response.json()["text"] == text
        assert response.json()["requires_split"] is True


def test_docx_and_invalid_uploads(tmp_path):
    archive = io.BytesIO()
    with zipfile.ZipFile(archive, "w") as docx:
        docx.writestr(
            "word/document.xml",
            '<w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main"><w:body><w:p><w:r><w:t>第一段</w:t></w:r></w:p><w:tbl><w:tr><w:tc><w:p><w:r><w:t>表格正文</w:t></w:r></w:p></w:tc></w:tr></w:tbl></w:body></w:document>',
        )
    assert read_document("test.docx", archive.getvalue())["text"] == "第一段\n\n表格正文"
    with TestClient(
        create_app(Settings(data_dir=tmp_path, token="test-secret"), FakeEngine())
    ) as client:
        for name, content in [
            ("bad.docx", b"not-a-zip"),
            ("bad.pdf", b"pdf"),
            ("bad.txt", b"\x00binary"),
            ("empty.txt", b""),
            ("huge.txt", b"x" * (MAX_UPLOAD + 1)),
        ]:
            response = client.post(
                "/api/documents/import", headers=AUTH, files={"file": (name, content)}
            )
            assert response.status_code == 400


def test_history_search_beyond_200(tmp_path):
    store = Store(tmp_path / "history.sqlite3")
    tasks = store.create([SynthesisRequest(text="the earliest unique 中文", title="old 100%_")])
    tasks += store.create([SynthesisRequest(text=f"later {i}") for i in range(240)])
    for task in tasks:
        store.update(task.id, status=Status.succeeded)
    store.close()
    with TestClient(
        create_app(Settings(data_dir=tmp_path, token="test-secret"), FakeEngine())
    ) as client:
        page = client.get("/api/tasks?search=unique", headers=AUTH).json()
        assert page["total"] == 1 and page["items"][0]["id"] == tasks[0].id
        assert client.get("/api/tasks?search=100%25_", headers=AUTH).json()["total"] == 1
        assert client.get("/api/tasks?offset=200&limit=50", headers=AUTH).json()["total"] == 241
        assert (
            client.put(
                f"/api/tasks/{tasks[0].id}/title", headers=AUTH, json={"title": "renamed"}
            ).status_code
            == 200
        )
        assert client.get("/api/tasks?search=renamed", headers=AUTH).json()["total"] == 1


def test_zip_safe_filenames_bulk_delete_and_vtt(tmp_path):
    with TestClient(
        create_app(Settings(data_dir=tmp_path / "data", token="test-secret"), FakeEngine())
    ) as client:
        ids = [submit(client, title="../unsafe:名字", text="测试") for _ in range(2)]
        for task_id in ids:
            task = wait_for(client, task_id)
            assert client.get(task["vtt_url"], headers=AUTH).text.startswith("WEBVTT")
        response = client.post("/api/tasks/export-zip", headers=AUTH, json={"ids": ids})
        assert response.status_code == 200
        with zipfile.ZipFile(io.BytesIO(response.content)) as archive:
            assert len(archive.namelist()) == 7
            assert all("/" not in name and "\\" not in name for name in archive.namelist())
            assert len(json.loads(archive.read("manifest.json"))) == 2
        destination = tmp_path / "导出.zip"
        body = {"ids": ids, "destination": str(destination)}
        assert client.post("/api/tasks/export-zip", headers=AUTH, json=body).status_code == 200
        assert client.post("/api/tasks/export-zip", headers=AUTH, json=body).status_code == 409
        assert destination.exists()
        result = client.post(
            "/api/tasks/delete-many", headers=AUTH, json={"ids": [*ids, "missing"]}
        ).json()
        assert result["deleted"] == ids and len(result["errors"]) == 1
        assert destination.exists()


def test_segment_recovery_reuse_edit_and_multi_voice(tmp_path, sample_audio):
    engine = MediaEngine(sample_audio, fail_text="bad")
    settings = Settings(data_dir=tmp_path, token="test-secret", attempts=1, concurrency=1)
    body = {
        "segments": [
            {"text": "first", "title": "甲", "voice": "zh-CN-XiaoxiaoNeural"},
            {"text": "bad", "title": "乙", "voice": "zh-CN-YunxiNeural"},
        ]
    }
    with TestClient(create_app(settings, engine)) as client:
        first = client.post("/api/tasks", headers=AUTH, json=body).json()["id"]
        failed = wait_for(client, first)
        assert failed["status"] == "failed" and failed["segment_completed"] == 1
        assert client.delete("/api/storage/segment-cache", headers=AUTH).status_code == 200
        # Rebuild a checkpoint and preserve it across a backend restart.
        first = client.post("/api/tasks", headers=AUTH, json=body).json()["id"]
        wait_for(client, first)
    engine.fail_text = None
    calls = len(engine.calls)
    with TestClient(create_app(settings, engine)) as client:
        retry = client.post(f"/api/tasks/{first}/retry", headers=AUTH).json()["id"]
        completed = wait_for(client, retry)
        assert completed["status"] == "succeeded"
        assert completed["segment_completed"] == 2
        assert completed["chapters"][0]["cached"] is True
        assert completed["chapters"][1]["voice"] == "zh-CN-YunxiNeural"
        assert len(engine.calls) == calls + 1
        assert 1.8 < completed["duration_seconds"] < 2.3
        cues = parse_srt(client.get(completed["subtitles_url"], headers=AUTH).text)
        assert len(cues) == 2 and cues[1][0] >= 0.95
        assert cues[-1][1] <= completed["duration_seconds"]
        body["segments"][1]["text"] = "edited"
        edited = client.post("/api/tasks", headers=AUTH, json=body).json()["id"]
        result = wait_for(client, edited)
        assert result["status"] == "succeeded" and result["chapters"][0]["cached"] is True
        assert len(engine.calls) == calls + 2
        info = client.get("/api/storage", headers=AUTH).json()
        assert info["cache_bytes"] > 0 and info["task_bytes"] > 0


def test_segment_cancellation_busy_cache_and_no_subtitles(tmp_path, sample_audio):
    engine = MediaEngine(sample_audio, delay=1)
    with TestClient(create_app(Settings(data_dir=tmp_path, token="test-secret"), engine)) as client:
        task_id = submit(client, segments=[{"text": "slow"}], subtitles=False)
        wait_for(client, task_id, ("running",))
        assert client.delete("/api/storage/segment-cache", headers=AUTH).status_code == 409
        assert (
            client.post(f"/api/tasks/{task_id}/cancel", headers=AUTH).json()["status"]
            == "cancelled"
        )
        assert not list((tmp_path / "segment-cache").glob("*/*.part"))
        engine.delay = 0
        task_id = submit(client, segments=[{"text": "done"}], subtitles=False)
        result = wait_for(client, task_id)
        assert result["status"] == "succeeded" and result["vtt_url"] is None


def test_split_and_subtitle_options():
    text = "第一句。第二句！\n第三句？" * 100
    parts = split_text(text, 100)
    assert all(len(part) <= 100 for part in parts)
    assert "".join(parts).replace("\n", "") == text.replace("\n", "")
    request = SynthesisRequest(
        voice="zh-CN-XiaoxiaoNeural",
        rate=10,
        segments=[SegmentRequest(text="hello", voice="en-US-GuyNeural")],
    )
    assert resolved_segments(request)[0][1].rate == 10
    assert resolved_segments(request)[0][1].voice == "en-US-GuyNeural"
    cues = optimize([(0, 2, "中文" * 30), (1.9, 3, "结束")], 8, -100)
    assert all(len(line) <= 8 for _, _, content in cues for line in content.splitlines())
    assert all(cues[i][1] <= cues[i + 1][0] for i in range(len(cues) - 1))
    assert cues[0][0] == 0
