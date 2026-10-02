"""Validate CLI/frozen readiness, authentication, SSE and HTTP without upstream calls."""

import argparse
import json
import os
import queue
import subprocess
import sys
import tempfile
import threading
import time

import httpx


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--executable")
    parser.add_argument("--live", action="store_true", help="Also test real short synthesis")
    args = parser.parse_args()
    command = [args.executable] if args.executable else [sys.executable, "-m", "edge_tts_backend"]
    with tempfile.TemporaryDirectory(prefix="edge-tts-process-") as data_dir:
        process = subprocess.Popen(
            [*command, "--data-dir", data_dir],
            stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            encoding="utf-8",
        )
        output: queue.Queue = queue.Queue()
        logs: list[str] = []

        def read_stdout():
            for line in process.stdout:
                output.put(line)

        def read_stderr():
            for line in process.stderr:
                logs.append(line)

        readers = [
            threading.Thread(target=read_stdout, daemon=True),
            threading.Thread(target=read_stderr, daemon=True),
        ]
        for reader in readers:
            reader.start()
        try:
            ready = json.loads(output.get(timeout=40))
            assert ready["event"] == "ready" and ready["host"] == "127.0.0.1"
            with httpx.Client(base_url=f"http://127.0.0.1:{ready['port']}", timeout=10) as client:
                assert client.get("/api/health").status_code == 401
                client.headers["Authorization"] = f"Bearer {ready['token']}"
                assert client.get("/api/health").json()["status"] == "ready"
                assert client.get("/api/openapi.json").status_code == 200
                with client.stream("GET", "/api/events") as response:
                    assert response.status_code == 200
                    lines = response.iter_lines()
                    assert next(lines) == "event: snapshot"
                    assert next(lines).startswith("data: ")
                if args.live:
                    voices = client.get("/api/voices?locale=zh-CN", timeout=40)
                    voices.raise_for_status()
                    assert voices.json()["total"] > 0
                    created = client.post(
                        "/api/tasks",
                        json={
                            "text": "你好，这是独立程序的语音测试。",
                        },
                    )
                    created.raise_for_status()
                    task_id = created.json()["id"]
                    deadline = time.monotonic() + 180
                    while time.monotonic() < deadline:
                        task = client.get(f"/api/tasks/{task_id}").json()
                        if task["status"] == "failed":
                            raise RuntimeError(str(task["error"]))
                        if task["status"] == "succeeded":
                            assert len(client.get(task["audio_url"]).content) > 1000
                            assert "-->" in client.get(task["subtitles_url"]).text
                            break
                        time.sleep(0.2)
                    else:
                        raise TimeoutError("Live frozen synthesis timed out")
                    project = {
                        "title": "多角色验证",
                        "subtitle_max_chars": 8,
                        "segments": [
                            {"text": "你好，我是第一个角色。", "voice": "zh-CN-XiaoxiaoNeural"},
                            {"text": "你好，我是第二个角色。", "voice": "zh-CN-YunxiNeural"},
                        ],
                    }
                    created = client.post("/api/tasks", json=project)
                    created.raise_for_status()
                    project_id = created.json()["id"]
                    deadline = time.monotonic() + 180
                    while time.monotonic() < deadline:
                        result = client.get(f"/api/tasks/{project_id}").json()
                        if result["status"] == "failed":
                            raise RuntimeError(str(result["error"]))
                        if result["status"] == "succeeded":
                            assert (
                                result["segment_completed"] == 2 and result["duration_seconds"] > 1
                            )
                            assert client.get(result["vtt_url"]).text.startswith("WEBVTT")
                            archive = client.post(
                                "/api/tasks/export-zip", json={"ids": [task_id, project_id]}
                            )
                            assert archive.status_code == 200 and archive.content.startswith(b"PK")
                            break
                        time.sleep(0.2)
                    else:
                        raise TimeoutError("Multi-role synthesis timed out")
                assert client.post("/api/shutdown").status_code == 202
                process.wait(timeout=15)
                assert process.returncode == 0
                print(
                    json.dumps(
                        {
                            "process": "frozen" if args.executable else "python",
                            "health": "passed",
                            "auth": "passed",
                            "sse": "passed",
                            "shutdown": "passed",
                            "live_synthesis": "passed" if args.live else "not_requested",
                            "multi_role_zip_vtt": "passed" if args.live else "not_requested",
                            "version": ready["version"],
                        }
                    ),
                    flush=True,
                )
        except Exception:
            print("".join(logs)[-3000:], file=sys.stderr)
            raise
        finally:
            if process.poll() is None:
                if os.name == "nt":
                    subprocess.run(
                        ["taskkill", "/PID", str(process.pid), "/T", "/F"],
                        capture_output=True,
                        check=False,
                    )
                else:
                    process.terminate()
                try:
                    process.wait(timeout=10)
                except subprocess.TimeoutExpired:
                    process.kill()
                    process.wait(timeout=10)
            for reader in readers:
                reader.join(timeout=2)
            process.stdout.close()
            process.stderr.close()


if __name__ == "__main__":
    main()
