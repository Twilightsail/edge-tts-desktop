import logging

import pytest
from fastapi.testclient import TestClient

from edge_tts_backend.app import create_app
from edge_tts_backend.config import Settings
from edge_tts_backend.diagnostics import read_logs, setup_logging

AUTH = {"Authorization": "Bearer test-secret"}


class QuietEngine:
    async def voices(self):
        return [{"ShortName": "zh-CN-XiaoxiaoNeural", "Locale": "zh-CN", "Gender": "Female"}]

    async def synthesize(self, request, audio, subtitles, progress):
        raise RuntimeError("not used")


@pytest.fixture
def logged(tmp_path):
    """给根日志临时挂上文件处理器，测完恢复，避免影响其他测试的日志捕获。"""
    root = logging.getLogger()
    saved, level = root.handlers[:], root.level
    settings = Settings(data_dir=tmp_path / "data", token="test-secret", concurrency=1)
    setup_logging(settings.data_dir)
    try:
        with TestClient(create_app(settings, QuietEngine())) as client:
            yield client, settings
    finally:
        for handler in root.handlers[:]:
            handler.close()
        root.handlers[:] = saved
        root.setLevel(level)


def test_about_and_logs(logged):
    client, settings = logged
    info = client.get("/api/about", headers=AUTH).json()
    assert info["version"] and info["data_dir"] == str(settings.data_dir)
    assert info["log_file"].endswith("backend.log")
    logging.getLogger("edge_tts_backend.test").warning("diagnostic marker %s", "alpha")
    text = client.get("/api/logs", headers=AUTH)
    assert text.status_code == 200 and text.headers["content-type"].startswith("text/plain")
    assert "diagnostic marker alpha" in text.text and "backend" in text.text
    assert client.get("/api/logs").status_code == 401  # 日志同样需要令牌


def test_log_rotation_keeps_tail(tmp_path):
    from logging.handlers import RotatingFileHandler

    logging.getLogger().handlers  # noqa: B018 - 仅确认根日志可用
    folder = tmp_path / "logs"
    folder.mkdir()
    handler = RotatingFileHandler(
        folder / "backend.log", maxBytes=2000, backupCount=3, encoding="utf-8"
    )
    logger = logging.getLogger("rotation-test")
    logger.addHandler(handler)
    logger.setLevel(logging.INFO)
    try:
        for i in range(200):
            logger.info("line %03d %s", i, "x" * 40)
    finally:
        logger.removeHandler(handler)
        handler.close()
    text = read_logs(tmp_path)
    assert "line 199" in text and "line 000" not in text  # 旧内容被轮转丢弃，新内容保留
    assert len(read_logs(tmp_path, limit=500)) <= 500


def test_export_logs_rules(logged, tmp_path):
    client, settings = logged
    target = tmp_path / "out.log"
    ok = client.post("/api/logs/export", headers=AUTH, json={"destination": str(target)})
    assert ok.status_code == 200 and target.read_text(encoding="utf-8")
    again = client.post("/api/logs/export", headers=AUTH, json={"destination": str(target)})
    assert again.status_code == 409  # 不覆盖
    assert (
        client.post(
            "/api/logs/export", headers=AUTH, json={"destination": str(target), "overwrite": True}
        ).status_code
        == 200
    )
    inside = settings.data_dir / "leak.log"
    assert (
        client.post("/api/logs/export", headers=AUTH, json={"destination": str(inside)}).status_code
        == 400
    )
    wrong = client.post(
        "/api/logs/export", headers=AUTH, json={"destination": str(tmp_path / "x.exe")}
    )
    assert wrong.status_code == 400
    relative = client.post("/api/logs/export", headers=AUTH, json={"destination": "out.log"})
    assert relative.status_code == 422
