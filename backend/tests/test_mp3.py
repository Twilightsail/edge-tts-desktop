"""MP3 时长解析测试：用 ffmpeg 生成真实文件，并和 mutagen（仅测试时作参照，不随程序分发）对照。"""

import subprocess

import imageio_ffmpeg
import pytest

from edge_tts_backend.mp3 import mp3_duration, mp3_file_duration


def make(path, seconds, rate=24000, extra=()):
    subprocess.run(
        [
            imageio_ffmpeg.get_ffmpeg_exe(),
            "-hide_banner",
            "-loglevel",
            "error",
            "-y",
            "-f",
            "lavfi",
            "-i",
            f"sine=frequency=440:duration={seconds}",
            "-ac",
            "1",
            "-ar",
            str(rate),
            *extra,
            str(path),
        ],
        check=True,
    )
    return path.read_bytes()


@pytest.mark.parametrize(
    ("rate", "extra", "seconds"),
    [
        (24000, ("-b:a", "48k"), 2.0),  # 本程序的实际格式：MPEG-2 Layer III，576 采样/帧
        (24000, ("-b:a", "48k"), 37.5),  # 长一点，误差不应累积
        (44100, ("-b:a", "128k"), 3.5),  # MPEG-1，1152 采样/帧
        (16000, ("-b:a", "32k"), 1.2),  # 另一种 MPEG-2 采样率
        (22050, ("-q:a", "6"), 4.0),  # VBR
        (
            24000,
            ("-b:a", "48k", "-id3v2_version", "3", "-metadata", "title=测试"),
            2.0,
        ),  # 带 ID3v2 标签
    ],
)
def test_duration_matches_reference(tmp_path, rate, extra, seconds):
    from mutagen.mp3 import MP3

    path = tmp_path / "a.mp3"
    data = make(path, seconds, rate, extra)
    ours = mp3_duration(data)
    # 编码器会在首尾各补一小段静音（LAME 约 0.05–0.1 秒），所以和“目标时长”只能大致相等；
    # 与成熟实现的结果则应几乎一致
    assert ours == pytest.approx(seconds, abs=0.15)
    assert ours == pytest.approx(MP3(path).info.length, abs=0.03)
    assert mp3_file_duration(path) == ours


def test_concatenated_files_add_up(tmp_path):
    """Azure 长文本会把多个请求的 MP3 直接拼接，时长应等于各段之和。"""
    raw = ("-b:a", "48k", "-write_xing", "0")  # 不带信息帧的纯帧流，和 Azure 返回的形式一致
    a = make(tmp_path / "a.mp3", 2.0, extra=raw)
    b = make(tmp_path / "b.mp3", 3.0, extra=raw)
    assert mp3_duration(a + b) == pytest.approx(mp3_duration(a) + mp3_duration(b), abs=0.001)
    assert mp3_duration(a + b) == pytest.approx(5.0, abs=0.2)


def test_damaged_and_empty_input_do_not_crash(tmp_path):
    data = make(tmp_path / "a.mp3", 2.0, extra=("-b:a", "48k"))
    assert mp3_duration(b"") == 0.0
    assert mp3_duration(b"not an mp3 at all" * 50) == 0.0
    assert mp3_duration(b"\xff" * 4096) == 0.0  # 全是同步字节但没有有效帧头
    truncated = mp3_duration(data[: len(data) // 2])
    assert 0.8 < truncated < 1.2  # 截断后只计完整的帧
    noisy = data[:1000] + b"garbage" * 30 + data[1000:]
    assert 1.8 < mp3_duration(noisy) <= 2.1  # 中间夹杂垃圾数据时重新同步，继续往后解析


def test_runtime_does_not_import_gpl_mutagen():
    """分发许可：程序本体不能依赖 GPL 的 mutagen（它只允许出现在测试里）。"""
    import pathlib

    source = pathlib.Path(__file__).parent.parent / "src" / "edge_tts_backend"
    offenders = [
        p.name
        for p in source.glob("*.py")
        if "mutagen" in p.read_text(encoding="utf-8").replace("mutagen（", "")
    ]
    assert offenders == [] or offenders == ["mp3.py"], (
        offenders
    )  # mp3.py 的文档字符串里提到它的名字
    assert "import mutagen" not in "".join(
        p.read_text(encoding="utf-8") for p in source.glob("*.py")
    )
    assert "from mutagen" not in "".join(p.read_text(encoding="utf-8") for p in source.glob("*.py"))
