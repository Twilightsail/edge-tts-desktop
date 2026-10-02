"""Opt-in real-network synthesis through the API; saves inspectable sample artifacts."""

import argparse
import json
import time
from pathlib import Path

from fastapi.testclient import TestClient

from edge_tts_backend.app import create_app
from edge_tts_backend.config import Settings


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--long-text", action="store_true")
    parser.add_argument("--data-dir", type=Path, default=Path(".local-data/live-smoke"))
    parser.add_argument("--proxy")
    args = parser.parse_args()
    settings = Settings(
        data_dir=args.data_dir.resolve(),
        token="local-smoke-token",
        attempts=1,
        task_timeout=180,
        proxy=args.proxy,
    )
    headers = {"Authorization": f"Bearer {settings.token}"}
    with TestClient(create_app(settings)) as client:
        voices = client.get("/api/voices?locale=zh-CN&refresh=true", headers=headers)
        if voices.status_code != 200:
            raise RuntimeError(f"Voice discovery failed: {voices.text}")
        print(json.dumps({"voices": voices.json()["total"], "stale": voices.json()["stale"]}))
        text = "你好，这是桌面版后端的真实语音测试。"
        if args.long_text:
            text = "长文本分块测试。" * 220
        created = client.post("/api/tasks", headers=headers, json={"text": text})
        created.raise_for_status()
        task_id = created.json()["id"]
        deadline = time.monotonic() + 200
        while time.monotonic() < deadline:
            task = client.get(f"/api/tasks/{task_id}", headers=headers).json()
            if task["status"] in ("failed", "cancelled"):
                raise RuntimeError(f"Synthesis failed: {task['error']}")
            if task["status"] == "succeeded":
                audio = client.get(task["audio_url"], headers=headers)
                subtitle = client.get(task["subtitles_url"], headers=headers)
                assert audio.status_code == 200 and len(audio.content) > 1000
                assert subtitle.status_code == 200 and "-->" in subtitle.text
                ranged = client.get(task["audio_url"], headers={**headers, "Range": "bytes=0-99"})
                assert ranged.status_code == 206 and len(ranged.content) == 100
                print(
                    json.dumps(
                        {
                            "status": task["status"],
                            "task_id": task_id,
                            "audio_bytes": len(audio.content),
                            "subtitle_cues": subtitle.text.count("-->"),
                            "input_utf8_bytes": len(text.encode()),
                            "artifact_dir": str(settings.data_dir / "tasks" / task_id),
                        }
                    )
                )
                return
            time.sleep(0.25)
        raise TimeoutError("Synthesis did not complete before smoke deadline")


if __name__ == "__main__":
    main()
