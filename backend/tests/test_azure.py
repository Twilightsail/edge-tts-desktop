"""Azure 引擎测试：全部使用本地假服务器，不访问真实 Azure（真实服务需要用户自己的密钥）。"""

import asyncio
import os
import re
import subprocess
import threading
import time

import imageio_ffmpeg
import pytest
from aiohttp import web
from fastapi.testclient import TestClient

from edge_tts_backend.app import create_app
from edge_tts_backend.config import Settings
from edge_tts_backend.engine import EngineError, classify_error
from edge_tts_backend.engine_azure import (
    AzureEngine,
    build_ssml,
    chunk_limit,
    endpoint,
    estimate_cues,
)
from edge_tts_backend.models import SynthesisRequest
from edge_tts_backend.secrets_store import AzureCredentials, protect, unprotect

AUTH = {"Authorization": "Bearer test-secret"}
KEY = "A1b2C3d4E5f6G7h8I9j0K1l2M3n4O5p6"

VOICES = [
    {
        "Name": "Microsoft Server Speech Text to Speech Voice (zh-CN, XiaochenNeural)",
        "DisplayName": "Xiaochen",
        "LocalName": "晓辰",
        "ShortName": "zh-CN-XiaochenNeural",
        "Gender": "Female",
        "Locale": "zh-CN",
        "LocaleName": "Chinese (Mandarin, Simplified)",
        "StyleList": ["livecommercial"],
        "VoiceType": "Neural",
        "Status": "GA",
    },
    {
        "ShortName": "zh-CN-YunxiNeural",
        "DisplayName": "Yunxi",
        "LocalName": "云希",
        "Gender": "Male",
        "Locale": "zh-CN",
        "LocaleName": "Chinese (Mandarin, Simplified)",
    },
]


@pytest.fixture(scope="session")
def mp3_bytes(tmp_path_factory):
    """用 ffmpeg 生成 2 秒的真实 MP3，模拟 Azure 返回的音频。"""
    path = tmp_path_factory.mktemp("azure") / "silence.mp3"
    subprocess.run(
        [
            imageio_ffmpeg.get_ffmpeg_exe(),
            "-hide_banner",
            "-loglevel",
            "error",
            "-f",
            "lavfi",
            "-i",
            "anullsrc=r=24000:cl=mono",
            "-t",
            "2",
            "-b:a",
            "48k",
            "-f",
            "mp3",
            str(path),
        ],
        check=True,
    )
    return path.read_bytes()


class FakeAzure:
    def __init__(self, mp3: bytes):
        self.mp3, self.status, self.requests = mp3, 200, []

    async def _voices(self, request):
        self.requests.append(("voices", dict(request.headers), b""))
        if self.status != 200:
            return web.Response(status=self.status, text="denied")
        return web.json_response(VOICES)

    async def _speak(self, request):
        self.requests.append(("speak", dict(request.headers), await request.read()))
        if self.status != 200:
            return web.Response(status=self.status, text="denied")
        return web.Response(body=self.mp3, content_type="audio/mpeg")

    def start(self):
        ready = threading.Event()

        def run():
            self.loop = asyncio.new_event_loop()
            asyncio.set_event_loop(self.loop)
            app = web.Application()
            app.router.add_get("/cognitiveservices/voices/list", self._voices)
            app.router.add_post("/cognitiveservices/v1", self._speak)
            self.runner = web.AppRunner(app)
            self.loop.run_until_complete(self.runner.setup())
            site = web.TCPSite(self.runner, "127.0.0.1", 0)
            self.loop.run_until_complete(site.start())
            self.url = f"http://127.0.0.1:{site._server.sockets[0].getsockname()[1]}"
            ready.set()
            self.loop.run_forever()
            self.loop.run_until_complete(self.runner.cleanup())

        self.thread = threading.Thread(target=run, daemon=True)
        self.thread.start()
        assert ready.wait(10)
        return self

    def stop(self):
        self.loop.call_soon_threadsafe(self.loop.stop)
        self.thread.join(10)

    def speaks(self):
        return [r for r in self.requests if r[0] == "speak"]


@pytest.fixture
def azure(mp3_bytes):
    server = FakeAzure(mp3_bytes).start()
    yield server
    server.stop()


class DummyEdge:
    async def voices(self):
        return [{"ShortName": "zh-CN-XiaoxiaoNeural", "Locale": "zh-CN", "Gender": "Female"}]

    async def synthesize(self, request, audio, subtitles, progress):
        raise AssertionError("Edge 引擎不应被调用")


@pytest.fixture
def backend(tmp_path, azure):
    settings = Settings(
        data_dir=tmp_path / "data", token="test-secret", concurrency=1, azure_base_url=azure.url
    )
    with TestClient(create_app(settings, DummyEdge())) as client:
        yield client, azure, settings


def configure(client):
    response = client.put("/api/engines/azure", headers=AUTH, json={"region": "eastus", "key": KEY})
    assert response.status_code == 200, response.text
    return response.json()


def wait_for(client, task_id, timeout=15):
    end = time.monotonic() + timeout
    while time.monotonic() < end:
        task = client.get(f"/api/tasks/{task_id}", headers=AUTH).json()
        if task["status"] in ("succeeded", "failed", "cancelled"):
            return task
        time.sleep(0.02)
    raise AssertionError(f"任务未结束：{task}")


# ---- 密钥保存 ----


@pytest.mark.skipif(os.name != "nt", reason="DPAPI 仅 Windows 可用")
def test_dpapi_roundtrip_is_encrypted():
    token = protect(KEY)
    assert token.startswith("dpapi:") and KEY not in token
    assert unprotect(token) == KEY
    assert protect(KEY) != token  # DPAPI 每次加密结果不同


def test_key_never_stored_in_plaintext_or_returned(backend):
    client, _, settings = backend
    info = configure(client)
    assert info == {"configured": True, "region": "eastus", "key_hint": "····O5p6"}
    assert KEY not in client.get("/api/engines", headers=AUTH).text
    database = (settings.data_dir / "history.sqlite3").read_bytes()
    wal = settings.data_dir / "history.sqlite3-wal"
    assert KEY.encode() not in database + (wal.read_bytes() if wal.exists() else b"")


def test_region_update_keeps_key_and_requires_key_first(backend):
    client, azure, _ = backend
    first = client.put("/api/engines/azure", headers=AUTH, json={"region": "eastus"})
    assert first.status_code == 422 and first.json()["error"]["code"] == "key_required"
    configure(client)
    again = client.put("/api/engines/azure", headers=AUTH, json={"region": "westus2"})
    assert again.json()["region"] == "westus2" and again.json()["key_hint"] == "····O5p6"
    bad = client.put("/api/engines/azure", headers=AUTH, json={"region": "East US!", "key": KEY})
    assert bad.status_code == 422


# ---- 请求格式与完整流程 ----


def test_not_configured_is_rejected_up_front(backend):
    client, _, _ = backend
    task = client.post("/api/tasks", headers=AUTH, json={"text": "你好。", "engine": "azure"})
    assert task.status_code == 409 and task.json()["error"]["code"] == "engine_not_configured"
    voices = client.get("/api/voices?engine=azure", headers=AUTH)
    assert voices.status_code == 409
    engines = client.get("/api/engines", headers=AUTH).json()["engines"]
    assert [(e["id"], e["configured"]) for e in engines] == [("edge", True), ("azure", False)]


def test_voices_are_cached_per_engine(backend):
    client, azure, _ = backend
    configure(client)
    items = client.get("/api/voices?engine=azure", headers=AUTH).json()["items"]
    assert [v["ShortName"] for v in items] == ["zh-CN-XiaochenNeural", "zh-CN-YunxiNeural"]
    assert items[0]["VoiceTag"] == {"VoicePersonalities": ["livecommercial"]}
    assert items[0]["LocalName"] == "晓辰"
    edge = client.get("/api/voices", headers=AUTH).json()["items"]  # 默认 Edge，互不影响
    assert [v["ShortName"] for v in edge] == ["zh-CN-XiaoxiaoNeural"]
    headers = azure.requests[0][1]
    assert headers["Ocp-Apim-Subscription-Key"] == KEY
    calls = len(azure.requests)
    assert client.get("/api/voices?engine=azure", headers=AUTH).json()["cached"] is True
    assert len(azure.requests) == calls


def test_connection_test_endpoint(backend):
    client, azure, _ = backend
    configure(client)
    assert client.post("/api/engines/azure/test", headers=AUTH).json() == {"ok": True, "voices": 2}
    azure.status = 401
    result = client.post("/api/engines/azure/test", headers=AUTH).json()
    assert result["ok"] is False and "密钥" in result["message"]


def test_synthesis_request_format_and_subtitles(backend):
    client, azure, _ = backend
    configure(client)
    response = client.post(
        "/api/tasks",
        headers=AUTH,
        json={
            "text": "你好，世界。今天天气很好！",
            "engine": "azure",
            "voice": "zh-CN-XiaochenNeural",
            "rate": 10,
            "pitch": -5,
            "volume": 20,
        },
    )
    assert response.status_code == 202, response.text
    task = wait_for(client, response.json()["id"])
    assert task["status"] == "succeeded", task
    assert task["request"]["engine"] == "azure"

    ((_, headers, body),) = azure.speaks()
    assert headers["Ocp-Apim-Subscription-Key"] == KEY
    assert headers["Content-Type"] == "application/ssml+xml"
    assert headers["X-Microsoft-OutputFormat"] == "audio-24khz-48kbitrate-mono-mp3"
    assert headers["User-Agent"]
    ssml = body.decode()
    assert "name='zh-CN-XiaochenNeural'" in ssml and "xml:lang='zh-CN'" in ssml
    assert "rate='+10%'" in ssml and "pitch='-5Hz'" in ssml and "volume='+20%'" in ssml
    assert "你好，世界。今天天气很好！" in ssml

    audio = client.get(task["audio_url"], headers=AUTH).content
    assert audio == azure.mp3
    srt = client.get(task["subtitles_url"], headers=AUTH).text
    cues = re.findall(r"(\d+):(\d+):(\d+),(\d+) --> (\d+):(\d+):(\d+),(\d+)", srt)
    assert len(cues) == 2  # 两个句子
    last_end = int(cues[-1][5]) * 60 + int(cues[-1][6]) + int(cues[-1][7]) / 1000
    assert 1.9 < last_end <= 2.1  # 覆盖约 2 秒的音频
    assert KEY not in srt and KEY not in str(task)


def test_segments_pipeline_with_azure_and_cache(backend):
    client, azure, _ = backend
    configure(client)
    payload = {
        "engine": "azure",
        "segments": [{"title": "旁白", "text": "夜深了。"}, {"title": "对话", "text": "你好吗？"}],
    }
    task = wait_for(client, client.post("/api/tasks", headers=AUTH, json=payload).json()["id"])
    assert task["status"] == "succeeded", task
    assert [c["cached"] for c in task["chapters"]] == [False, False]
    assert len(azure.speaks()) == 2
    again = wait_for(client, client.post("/api/tasks", headers=AUTH, json=payload).json()["id"])
    assert [c["cached"] for c in again["chapters"]] == [True, True]
    assert len(azure.speaks()) == 2  # 命中缓存，没有再请求 Azure


def test_failed_auth_is_not_retried_and_message_is_clear(backend):
    client, azure, _ = backend
    configure(client)
    azure.status = 401
    task = wait_for(
        client,
        client.post("/api/tasks", headers=AUTH, json={"text": "你好。", "engine": "azure"}).json()[
            "id"
        ],
    )
    assert task["status"] == "failed"
    assert task["error"]["code"] == "azure_auth" and task["error"]["retryable"] is False
    assert len(azure.speaks()) == 1


def test_delete_key_disables_engine(backend):
    client, _, _ = backend
    configure(client)
    assert client.delete("/api/engines/azure", headers=AUTH).status_code == 204
    assert client.get("/api/engines", headers=AUTH).json()["engines"][1]["configured"] is False
    response = client.post("/api/tasks", headers=AUTH, json={"text": "你好。", "engine": "azure"})
    assert response.status_code == 409


# ---- 纯函数 ----


def test_estimate_cues_cover_duration_in_order():
    cues = estimate_cues("第一句。第二句话更长一些，对吧？第三句！", 10.0, offset=5.0)
    assert [c[2] for c in cues] == ["第一句。", "第二句话更长一些，对吧？", "第三句！"]
    assert cues[0][0] == pytest.approx(5.0) and cues[-1][1] == pytest.approx(15.0)
    assert all(a[1] == pytest.approx(b[0]) for a, b in zip(cues, cues[1:], strict=False))
    assert (cues[1][1] - cues[1][0]) > (cues[0][1] - cues[0][0])  # 更长的句子分到更多时间
    assert estimate_cues("", 3.0) == [] and estimate_cues("你好。", 0) == []


def test_ssml_escaping_and_limits():
    ssml = build_ssml('a < b & "c" \x07', "zh-CN-liaoning-XiaobeiNeural", -90, 0, 0)
    assert "a &lt; b &amp;" in ssml and "\x07" not in ssml
    assert "xml:lang='zh-CN'" in ssml and "rate='-50%'" in ssml  # Azure 语速下限
    assert chunk_limit(0) == 1500 and chunk_limit(-50) == 750 and chunk_limit(100) == 3000
    assert endpoint("eastus") == "https://eastus.tts.speech.microsoft.com"
    assert endpoint("chinaeast2") == "https://chinaeast2.tts.speech.azure.cn"


def test_long_text_is_split_into_multiple_requests(tmp_path, azure):
    """超过安全长度的文本会拆成多个请求，避免被 10 分钟上限截断。"""

    class Fixed:
        def get(self):
            return "eastus", KEY

    engine = AzureEngine(Fixed(), base_url=azure.url)
    text = "这是一句话。" * 600  # 3600 字符，远超 1500
    request = SynthesisRequest(text=text, engine="azure")
    asyncio.run(engine.synthesize(request, tmp_path / "a.mp3", tmp_path / "a.srt", lambda n: None))
    count = len(azure.speaks())
    assert count >= 3
    assert (tmp_path / "a.mp3").stat().st_size == len(azure.mp3) * count
    cues = (tmp_path / "a.srt").read_text(encoding="utf-8").count("-->")
    assert cues == 600


def test_error_mapping():
    class Fixed:
        def get(self):
            return "eastus", KEY

    async def status_error(code):
        class Server:
            status = code

            async def text(self):
                return "bad voice"

        await AzureEngine._check(Server())

    for code, name, retry in [
        (401, "azure_auth", False),
        (403, "azure_forbidden", False),
        (429, "azure_rate_limit", True),
        (400, "azure_bad_request", False),
        (503, "upstream_http", True),
        (404, "upstream_http", False),
    ]:
        with pytest.raises(EngineError) as info:
            asyncio.run(status_error(code))
        error = classify_error(info.value)
        assert (error.code, error.retryable) == (name, retry), code
        assert KEY not in error.message
    assert AzureEngine(Fixed())._setup()[1]["Ocp-Apim-Subscription-Key"] == KEY
    assert AzureCredentials is not None


# ---- 用量统计（Azure 免费额度）----


def test_billable_chars_follow_azure_rules():
    from edge_tts_backend.usage import billable_chars

    assert billable_chars("你好") == 4  # 每个汉字算 2
    assert billable_chars("abc, d") == 6  # 字母、标点、空格各算 1
    assert billable_chars("你好，世界。") == 4 + 1 + 4 + 1  # 全角标点不是汉字，算 1
    assert billable_chars("日本語ひらがな") == 6 + 4  # 日文汉字算 2，假名算 1
    assert billable_chars("😀") == 1  # 按 Unicode 码位计，不是 UTF-16 单元


def test_default_params_have_no_prosody_markup():
    plain = build_ssml("你好", "zh-CN-XiaoxiaoNeural", 0, 0, 0)
    assert "<prosody" not in plain and "<voice name='zh-CN-XiaoxiaoNeural'>你好</voice>" in plain
    assert "<prosody" in build_ssml("你好", "zh-CN-XiaoxiaoNeural", 5, 0, 0)


def test_usage_counts_successful_requests_only(backend):
    from edge_tts_backend.engine_azure import ssml_body
    from edge_tts_backend.usage import billable_chars

    client, azure, _ = backend
    configure(client)
    usage = lambda: client.get("/api/engines", headers=AUTH).json()["engines"][1]["usage"]  # noqa: E731
    assert usage()["chars"] == 0 and usage()["limit"] == 500_000

    text = "你好，世界。今天天气很好！"
    task = wait_for(
        client,
        client.post(
            "/api/tasks", headers=AUTH, json={"text": text, "engine": "azure", "rate": 10}
        ).json()["id"],
    )
    assert task["status"] == "succeeded"
    assert usage()["chars"] == billable_chars(ssml_body(text, 10, 0, 0))  # 带 prosody 标记

    before = usage()["chars"]
    task = wait_for(
        client,
        client.post("/api/tasks", headers=AUTH, json={"text": text, "engine": "azure"}).json()[
            "id"
        ],
    )
    assert usage()["chars"] - before == billable_chars(text)  # 默认参数：只有正文

    azure.status = 401
    before = usage()["chars"]
    wait_for(
        client,
        client.post("/api/tasks", headers=AUTH, json={"text": "失败。", "engine": "azure"}).json()[
            "id"
        ],
    )
    assert usage()["chars"] == before  # 失败的请求不计费


def test_usage_calibration_and_month_rollover(backend):
    from datetime import UTC, datetime

    from edge_tts_backend.usage import AzureUsage

    client, _, settings = backend
    configure(client)
    response = client.put(
        "/api/engines/azure/usage", headers=AUTH, json={"chars": 123456, "limit": 400000}
    )
    assert response.status_code == 200
    assert response.json()["chars"] == 123456 and response.json()["limit"] == 400000
    assert client.put("/api/engines/azure/usage", headers=AUTH, json={}).status_code == 422
    assert (
        client.put("/api/engines/azure/usage", headers=AUTH, json={"chars": -1}).status_code == 422
    )

    class Store:
        data = {}

        def get_cache(self, key):
            return self.data.get(key)

        def put_cache(self, key, value):
            self.data[key] = value

    now = [datetime(2026, 10, 31, tzinfo=UTC)]
    usage = AzureUsage(Store(), clock=lambda: now[0])
    usage.set(chars=480000, limit=400000)
    usage.add(30)
    assert usage.get() == {"month": "2026-10", "chars": 480030, "limit": 400000}
    now[0] = datetime(2026, 11, 1, tzinfo=UTC)  # 跨月：清零，上限保留
    assert usage.get() == {"month": "2026-11", "chars": 0, "limit": 400000}


# ---- 说话风格（express-as）----


def test_style_in_ssml_billing_and_validation(backend):
    from edge_tts_backend.engine_azure import ssml_body
    from edge_tts_backend.usage import billable_chars

    client, azure, _ = backend
    configure(client)
    payload = {
        "text": "你好。",
        "engine": "azure",
        "voice": "zh-CN-XiaochenNeural",
        "style": "cheerful",
    }
    task = wait_for(client, client.post("/api/tasks", headers=AUTH, json=payload).json()["id"])
    assert task["status"] == "succeeded", task
    body = azure.speaks()[-1][2].decode()
    assert "xmlns:mstts='https://www.w3.org/2001/mstts'" in body
    assert "<mstts:express-as style='cheerful'>你好。</mstts:express-as>" in body
    usage = client.get("/api/engines", headers=AUTH).json()["engines"][1]["usage"]["chars"]
    assert usage == billable_chars(ssml_body("你好。", 0, 0, 0, "cheerful"))  # 标记也计费
    for bad in ("bad style!", "x" * 41, "a'b"):
        response = client.post("/api/tasks", headers=AUTH, json={**payload, "style": bad})
        assert response.status_code == 422, bad
    assert "<mstts" not in build_ssml("你好", "zh-CN-XiaochenNeural", 0, 0, 0)


def test_style_changes_segment_cache_key(backend):
    client, azure, _ = backend
    configure(client)
    base = {"engine": "azure", "segments": [{"title": "旁白", "text": "夜深了。"}]}

    def run(**extra):
        response = client.post("/api/tasks", headers=AUTH, json={**base, **extra})
        return wait_for(client, response.json()["id"])

    assert run()["chapters"][0]["cached"] is False
    assert run(style="sad")["chapters"][0]["cached"] is False  # 风格不同，不能复用
    assert run(style="sad")["chapters"][0]["cached"] is True
    assert run()["chapters"][0]["cached"] is True  # 原来的默认风格缓存仍然有效
    assert len(azure.speaks()) == 2
    bodies = [r[2].decode() for r in azure.speaks()]
    assert sum("express-as" in b for b in bodies) == 1


def test_segment_level_style_overrides_task_style(backend):
    client, azure, _ = backend
    configure(client)
    payload = {
        "engine": "azure",
        "style": "sad",
        "segments": [{"text": "第一段。", "style": "cheerful"}, {"text": "第二段。"}],
    }
    wait_for(client, client.post("/api/tasks", headers=AUTH, json=payload).json()["id"])
    bodies = [r[2].decode() for r in azure.speaks()]
    assert "style='cheerful'" in bodies[0] and "style='sad'" in bodies[1]


def test_preview_text_matches_voice_language(backend):
    client, _, _ = backend
    expected = {
        "zh-CN-XiaoxiaoNeural": "你好",
        "ja-JP-NanamiNeural": "こんにちは",
        "ko-KR-SunHiNeural": "안녕하세요",
        "en-US-GuyNeural": "Hello",
        "xx-YY-UnknownNeural": "Hello",  # 未知语言回退英文
    }
    for voice, start in expected.items():
        response = client.post("/api/voices/preview", headers=AUTH, json={"voice": voice})
        assert response.status_code == 202, response.text
        assert response.json()["request"]["segments"][0]["text"].startswith(start), voice
