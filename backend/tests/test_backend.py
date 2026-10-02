import asyncio
import time

import pytest
from fastapi.testclient import TestClient

from edge_tts_backend.app import create_app
from edge_tts_backend.config import Settings
from edge_tts_backend.instance import InstanceLock
from edge_tts_backend.models import Status, SynthesisRequest, TaskError
from edge_tts_backend.service import Events, TaskService
from edge_tts_backend.store import Store

AUTH = {"Authorization": "Bearer test-secret"}


class FakeEngine:
    def __init__(self, delay=0, failures=0):
        self.delay, self.failures = delay, failures
        self.calls = 0
        self.voice_calls = 0
        self.voice_failure = False
        self.started = asyncio.Event()

    async def voices(self):
        self.voice_calls += 1
        if self.voice_failure:
            raise TimeoutError()
        return [
            {"ShortName": "zh-CN-XiaoxiaoNeural", "Locale": "zh-CN", "Gender": "Female"},
            {"ShortName": "en-US-GuyNeural", "Locale": "en-US", "Gender": "Male"},
        ]

    async def synthesize(self, request, audio, subtitles, progress):
        self.started.set()
        self.calls += 1
        audio.write_bytes(b"partial")
        progress(7)
        await asyncio.sleep(self.delay)
        if self.calls <= self.failures:
            raise TimeoutError()
        if request.text == "permanent-error":
            raise ValueError("fake permanent failure")
        audio.write_bytes(b"ID3" + b"a" * 4096)
        if request.subtitles:
            subtitles.write_text("1\n00:00:00,000 --> 00:00:01,000\n测试。\n", encoding="utf-8")
        progress(audio.stat().st_size)


def wait_for(client, task_id, statuses=("succeeded", "failed", "cancelled"), timeout=8):
    end = time.monotonic() + timeout
    while time.monotonic() < end:
        task = client.get(f"/api/tasks/{task_id}", headers=AUTH).json()
        if task["status"] in statuses:
            return task
        time.sleep(0.01)
    raise AssertionError(f"Task did not reach {statuses}: {task}")


@pytest.fixture
def backend(tmp_path):
    engine = FakeEngine()
    settings = Settings(data_dir=tmp_path / "data", token="test-secret", concurrency=1)
    with TestClient(create_app(settings, engine)) as client:
        yield client, engine, settings


def submit(client, **values):
    response = client.post("/api/tasks", headers=AUTH, json={"text": "你好，世界。", **values})
    assert response.status_code == 202, response.text
    return response.json()["id"]


def test_authentication_and_schema(backend):
    client, _, _ = backend
    assert client.get("/api/health").status_code == 401
    assert (
        client.get(
            "/api/health", headers={"Authorization": "Bearer 错误".encode().hex()}
        ).status_code
        == 401
    )
    assert client.get("/api/health", headers=AUTH).json()["status"] == "ready"
    assert client.get("/api/openapi.json").status_code == 401
    schema = client.get("/api/openapi.json", headers=AUTH).json()
    assert "/api/tasks" in schema["paths"]
    assert schema["components"]["securitySchemes"]["HTTPBearer"]["scheme"] == "bearer"


@pytest.mark.parametrize(
    "payload",
    [
        {"text": " "},
        {"text": "\x01\x02"},
        {"text": "a" * 100001},
        {"text": "a", "rate": -91},
        {"text": "a", "pitch": 101},
        {"text": "a", "volume": -101},
        {"text": "a", "voice": "<voice>"},
        {"text": "a", "unknown": True},
    ],
)
def test_validation(backend, payload):
    client, _, _ = backend
    response = client.post("/api/tasks", headers=AUTH, json=payload)
    assert response.status_code == 422
    assert response.json()["error"]["code"] == "validation_error"
    assert all("input" not in detail for detail in response.json()["error"]["details"])


def test_synthesis_range_subtitles_export_delete(backend, tmp_path):
    client, _, settings = backend
    task_id = submit(client)
    task = wait_for(client, task_id)
    assert task["status"] == "succeeded"
    assert task["audio_bytes"] == 4099
    response = client.get(task["audio_url"], headers={**AUTH, "Range": "bytes=0-2"})
    assert response.status_code == 206
    assert response.content == b"ID3"
    assert response.headers["content-range"] == "bytes 0-2/4099"
    assert "测试" in client.get(task["subtitles_url"], headers=AUTH).text
    target = tmp_path / "导出.mp3"
    url = f"/api/tasks/{task_id}/export"
    assert client.post(url, headers=AUTH, json={"destination": str(target)}).status_code == 200
    assert target.read_bytes() == b"ID3" + b"a" * 4096
    assert client.post(url, headers=AUTH, json={"destination": str(target)}).status_code == 409
    assert (
        client.post(
            url, headers=AUTH, json={"destination": str(target), "overwrite": True}
        ).status_code
        == 200
    )
    assert (
        client.post(
            url, headers=AUTH, json={"destination": str(target.with_suffix(".wav"))}
        ).status_code
        == 400
    )
    assert (
        client.post(
            url, headers=AUTH, json={"destination": str(settings.data_dir / "out.mp3")}
        ).status_code
        == 400
    )
    assert client.post(url, headers=AUTH, json={"destination": "relative.mp3"}).status_code == 422
    assert client.delete(f"/api/tasks/{task_id}", headers=AUTH).status_code == 204
    assert client.get(task["audio_url"], headers=AUTH).status_code == 404
    assert not (settings.data_dir / "tasks" / task_id).exists()
    assert target.exists()


def test_without_subtitles_and_retry_conflict(backend):
    client, _, _ = backend
    task_id = submit(client, subtitles=False)
    task = wait_for(client, task_id)
    assert task["subtitles_url"] is None
    assert client.get(f"/api/tasks/{task_id}/subtitles", headers=AUTH).status_code == 404
    assert client.post(f"/api/tasks/{task_id}/retry", headers=AUTH).status_code == 409


def test_running_and_queued_cancellation(backend):
    client, engine, settings = backend
    engine.delay = 2
    first = submit(client)
    wait_for(client, first, ("running",))
    second = submit(client)
    assert client.delete(f"/api/tasks/{first}", headers=AUTH).status_code == 409
    assert client.get(f"/api/tasks/{first}/audio", headers=AUTH).status_code == 409
    for task_id in (second, first):
        response = client.post(f"/api/tasks/{task_id}/cancel", headers=AUTH)
        assert response.json()["status"] == "cancelled"
        assert client.post(f"/api/tasks/{task_id}/cancel", headers=AUTH).status_code == 200
    assert not list((settings.data_dir / "tasks").glob("*/*.part"))
    engine.delay = 0
    retry = client.post(f"/api/tasks/{first}/retry", headers=AUTH).json()["id"]
    assert retry != first
    assert wait_for(client, retry)["status"] == "succeeded"


def test_transient_retry_and_permanent_failure(backend):
    client, engine, _ = backend
    engine.failures = 1
    task = wait_for(client, submit(client))
    assert task["status"] == "succeeded"
    assert task["attempt"] == 2
    assert task["error"] is None
    failed = wait_for(client, submit(client, text="permanent-error"))
    assert failed["status"] == "failed"
    assert failed["attempt"] == 1
    assert failed["error"]["retryable"] is False


def test_batch_capacity_and_pagination(tmp_path):
    settings = Settings(data_dir=tmp_path, token="test-secret", concurrency=1, max_pending=2)
    with TestClient(create_app(settings, FakeEngine(delay=2))) as client:
        response = client.post(
            "/api/tasks/batch",
            headers=AUTH,
            json={"items": [{"text": "first"}, {"text": "second"}]},
        )
        assert response.status_code == 202
        assert client.post("/api/tasks", headers=AUTH, json={"text": "third"}).status_code == 429
        assert client.post("/api/tasks/batch", headers=AUTH, json={"items": []}).status_code == 422
        page = client.get("/api/tasks?limit=1&offset=1", headers=AUTH).json()
        assert page["total"] == 2
        assert len(page["items"]) == 1
        assert client.get("/api/tasks?limit=201", headers=AUTH).status_code == 422


def test_voice_cache_filters_and_stale_fallback(backend):
    client, engine, _ = backend
    result = client.get("/api/voices?locale=zh-CN&gender=Female", headers=AUTH).json()
    assert result["total"] == 1 and result["cached"] is False
    assert client.get("/api/voices?search=Guy", headers=AUTH).json()["total"] == 1
    assert engine.voice_calls == 1
    engine.voice_failure = True
    stale = client.get("/api/voices?refresh=true", headers=AUTH).json()
    assert stale["stale"] is True and len(stale["items"]) == 2


def test_no_voice_cache_failure(tmp_path):
    engine = FakeEngine()
    engine.voice_failure = True
    with TestClient(create_app(Settings(data_dir=tmp_path, token="test-secret"), engine)) as client:
        assert client.get("/api/voices", headers=AUTH).status_code == 503


def test_preferences_persist_and_recovery(tmp_path):
    settings = Settings(data_dir=tmp_path, token="test-secret", concurrency=1)
    with TestClient(create_app(settings, FakeEngine())) as client:
        response = client.put("/api/settings", headers=AUTH, json={"rate": 20})
        assert response.json()["rate"] == 20
        completed = submit(client)
        wait_for(client, completed)
    store = Store(tmp_path / "history.sqlite3")
    queued, interrupted = store.create(
        [SynthesisRequest(text="queue"), SynthesisRequest(text="run")]
    )
    store.update(interrupted.id, status=Status.running)
    store.close()
    partial = tmp_path / "tasks" / interrupted.id
    partial.mkdir()
    (partial / "audio.mp3.part").write_bytes(b"partial")
    with TestClient(create_app(settings, FakeEngine())) as client:
        assert client.get("/api/settings", headers=AUTH).json()["rate"] == 20
        assert client.get(f"/api/tasks/{completed}/audio", headers=AUTH).status_code == 200
        failed = client.get(f"/api/tasks/{interrupted.id}", headers=AUTH).json()
        assert failed["error"]["code"] == "interrupted"
        assert wait_for(client, queued.id)["status"] == "succeeded"
        assert not (partial / "audio.mp3.part").exists()


def test_cors_and_errors(backend):
    client, _, _ = backend
    assert client.post("/api/shutdown").status_code == 401
    assert client.post("/api/shutdown", headers=AUTH).status_code == 409
    response = client.options(
        "/api/tasks",
        headers={
            "Origin": "http://localhost:5173",
            "Access-Control-Request-Method": "POST",
            "Access-Control-Request-Headers": "Authorization,Content-Type",
        },
    )
    assert response.status_code == 200
    assert response.headers["access-control-allow-origin"] == "http://localhost:5173"
    assert (
        client.options(
            "/api/tasks",
            headers={
                "Origin": "https://untrusted.example",
                "Access-Control-Request-Method": "POST",
            },
        ).status_code
        == 400
    )
    assert client.get("/api/tasks/../../outside", headers=AUTH).status_code == 404
    assert (
        client.get("/api/tasks/nonexistent", headers=AUTH).json()["error"]["code"]
        == "task_not_found"
    )


def test_single_instance(tmp_path):
    with InstanceLock(tmp_path), pytest.raises(RuntimeError, match="已有后端"):
        with InstanceLock(tmp_path):
            pass
    with InstanceLock(tmp_path):
        pass


def test_delete_failure_preserves_history(backend, monkeypatch):
    client, _, _ = backend
    task_id = submit(client)
    wait_for(client, task_id)

    def blocked_delete(path):
        raise PermissionError("file in use")

    monkeypatch.setattr("edge_tts_backend.service.shutil.rmtree", blocked_delete)
    response = client.delete(f"/api/tasks/{task_id}", headers=AUTH)
    assert response.status_code == 409
    assert response.json()["error"]["code"] == "delete_failed"
    assert client.get(f"/api/tasks/{task_id}", headers=AUTH).status_code == 200


def test_internal_error_has_consistent_shape(tmp_path, monkeypatch):
    def fail_preferences(self):
        raise OSError("sensitive-detail")

    monkeypatch.setattr(Store, "preferences", fail_preferences)
    app = create_app(Settings(data_dir=tmp_path, token="test-secret"), FakeEngine())
    with TestClient(app, raise_server_exceptions=False) as client:
        response = client.get("/api/settings", headers=AUTH)
        assert response.status_code == 500
        assert response.json()["error"]["code"] == "internal_error"
        assert "sensitive-detail" not in response.text


def test_events_snapshot_updates_and_overflow(tmp_path):
    async def scenario():
        store = Store(tmp_path / "events.sqlite3")
        events = Events()
        stream = events.stream(store)
        initial = await anext(stream)
        assert initial.startswith("event: snapshot")
        events.publish("task.updated", {"id": "one"})
        assert '"id": "one"' in await anext(stream)
        for i in range(140):
            events.publish("task.updated", {"id": i})
        assert "event: resync" in await anext(stream)
        await stream.aclose()
        assert not events.subscribers
        store.close()

    asyncio.run(scenario())


def test_timeout_and_shutdown_cleanup(tmp_path):
    async def scenario():
        settings = Settings(
            data_dir=tmp_path, token="test-secret", concurrency=1, task_timeout=0.01, attempts=1
        )
        store = Store(tmp_path / "timeouts.sqlite3")
        engine = FakeEngine(delay=5)
        service = TaskService(settings, store, engine)
        await service.start()
        task = (await service.submit([SynthesisRequest(text="timeout")]))[0]
        await service.queue.join()
        assert store.get(task.id).status == Status.failed
        assert store.get(task.id).error == TaskError(
            code="network",
            message="连接语音服务超时或中断，请检查网络",
            retryable=True,
        )
        engine.started.clear()
        task = (await service.submit([SynthesisRequest(text="shutdown")]))[0]
        await asyncio.wait_for(engine.started.wait(), timeout=1)
        await service.stop()
        assert store.get(task.id).error.code == "interrupted"
        assert not list((tmp_path / "tasks").glob("*/*.part"))
        store.close()

    asyncio.run(scenario())
