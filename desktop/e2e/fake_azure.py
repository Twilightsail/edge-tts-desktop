"""假的 Azure Speech 服务器，仅供端到端测试：不联网、不需要真实密钥。

用法：python fake_azure.py <端口> <请求日志文件>
正确密钥是 GOOD_KEY；其他密钥返回 401，与真实服务对错误密钥的反应一致。
"""

import json
import subprocess
import sys
import tempfile
from pathlib import Path

import imageio_ffmpeg
from aiohttp import web

GOOD_KEY = "A1b2C3d4E5f6G7h8I9j0K1l2M3n4O5p6"
LOG = Path(sys.argv[2])

tmp = Path(tempfile.mkdtemp()) / "tone.mp3"
subprocess.run(
    [imageio_ffmpeg.get_ffmpeg_exe(), "-hide_banner", "-loglevel", "error", "-f", "lavfi", "-i",
     "sine=frequency=440:duration=3", "-ac", "1", "-ar", "24000", "-b:a", "48k", "-f", "mp3", str(tmp)],
    check=True,
)
MP3 = tmp.read_bytes()

MANDARIN = "Chinese (Mandarin, Simplified)"
VOICES = [
    {"DisplayName": "Xiaochen", "LocalName": "晓辰", "ShortName": "zh-CN-XiaochenNeural", "Gender": "Female",
     "Locale": "zh-CN", "LocaleName": MANDARIN, "StyleList": ["cheerful", "sad", "newscast"], "VoiceType": "Neural"},
    {"DisplayName": "Xiaoxiao", "LocalName": "晓晓", "ShortName": "zh-CN-XiaoxiaoNeural", "Gender": "Female",
     "Locale": "zh-CN", "LocaleName": MANDARIN, "VoiceType": "Neural"},
    {"DisplayName": "Yunfeng", "LocalName": "云枫", "ShortName": "zh-CN-YunfengNeural", "Gender": "Male",
     "Locale": "zh-CN", "LocaleName": MANDARIN, "StyleList": ["angry"], "VoiceType": "Neural"},
    {"DisplayName": "Ava Multilingual", "LocalName": "Ava Multilingual", "ShortName": "en-US-AvaMultilingualNeural",
     "Gender": "Female", "Locale": "en-US", "LocaleName": "English (United States)",
     "SecondaryLocaleList": ["zh-CN", "ja-JP"], "VoiceType": "Neural"},
    {"DisplayName": "Jenny", "LocalName": "Jenny", "ShortName": "en-US-JennyNeural", "Gender": "Female",
     "Locale": "en-US", "LocaleName": "English (United States)", "VoiceType": "Neural"},
]


def record(kind, request, body=b""):
    with LOG.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps({
            "kind": kind,
            "key": request.headers.get("Ocp-Apim-Subscription-Key"),
            "ctype": request.headers.get("Content-Type"),
            "fmt": request.headers.get("X-Microsoft-OutputFormat"),
            "body": body.decode("utf-8", "replace"),
        }, ensure_ascii=False) + "\n")


def authorized(request):
    return request.headers.get("Ocp-Apim-Subscription-Key") == GOOD_KEY


async def voices(request):
    record("voices", request)
    return web.json_response(VOICES) if authorized(request) else web.Response(status=401, text="denied")


async def speak(request):
    body = await request.read()
    record("speak", request, body)
    if not authorized(request):
        return web.Response(status=401, text="denied")
    return web.Response(body=MP3, content_type="audio/mpeg")


app = web.Application()
app.router.add_get("/cognitiveservices/voices/list", voices)
app.router.add_post("/cognitiveservices/v1", speak)
web.run_app(app, host="127.0.0.1", port=int(sys.argv[1]), print=lambda *_: None)
