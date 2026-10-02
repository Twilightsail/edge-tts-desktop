"""MP3 时长解析（仅 Layer III），纯 Python 实现。

只为得到音频时长而写：逐帧累加采样数。之所以不用 mutagen，是因为它采用 GPL-2.0-or-later 许可，
打进后端程序会让整个程序受 GPL 约束；这里的实现没有任何第三方依赖。
"""

from pathlib import Path

# 比特率表（kbps），按 MPEG 版本分：MPEG-1 Layer III 与 MPEG-2/2.5 Layer III
_BITRATE_V1 = (0, 32, 40, 48, 56, 64, 80, 96, 112, 128, 160, 192, 224, 256, 320)
_BITRATE_V2 = (0, 8, 16, 24, 32, 40, 48, 56, 64, 80, 96, 112, 128, 144, 160)
_RATE = {3: (44100, 48000, 32000), 2: (22050, 24000, 16000), 0: (11025, 12000, 8000)}  # 键：版本位


def _skip_id3(data: bytes) -> int:
    if data[:3] == b"ID3" and len(data) >= 10:
        size = (
            (data[6] & 0x7F) << 21
            | (data[7] & 0x7F) << 14
            | (data[8] & 0x7F) << 7
            | (data[9] & 0x7F)
        )
        return 10 + size + (10 if data[5] & 0x10 else 0)  # 带 footer 时再加 10 字节
    return 0


def _frame(data: bytes, pos: int):
    """解析 pos 处的帧头，返回 (帧长, 采样数, 采样率)；不是有效的 Layer III 帧头则返回 None。"""
    if pos + 4 > len(data) or data[pos] != 0xFF or (data[pos + 1] & 0xE0) != 0xE0:
        return None
    version = (data[pos + 1] >> 3) & 0x03  # 3=MPEG1，2=MPEG2，0=MPEG2.5，1=保留
    layer = (data[pos + 1] >> 1) & 0x03  # 1=Layer III
    bitrate_index = data[pos + 2] >> 4
    rate_index = (data[pos + 2] >> 2) & 0x03
    padding = (data[pos + 2] >> 1) & 0x01
    if version == 1 or layer != 1 or bitrate_index in (0, 15) or rate_index == 3:
        return None
    rate = _RATE[version][rate_index]
    if version == 3:
        bitrate, samples = _BITRATE_V1[bitrate_index], 1152
        length = 144000 * bitrate // rate + padding
    else:
        bitrate, samples = _BITRATE_V2[bitrate_index], 576
        length = 72000 * bitrate // rate + padding
    return length, samples, rate


def mp3_duration(data: bytes) -> float:
    """返回时长（秒）；无法识别任何有效帧时返回 0.0。"""
    pos, total, rate, seen_audio = _skip_id3(data), 0, 0, False
    while pos < len(data):
        frame = _frame(data, pos)
        if frame is None:  # 损坏或夹杂其他数据：向后找下一个同步字
            pos = data.find(b"\xff", pos + 1)
            if pos < 0:
                break
            continue
        length, samples, rate = frame
        if pos + length > len(data) + 3:  # 末尾被截断的半帧不计
            break
        # 开头的 Xing/Info/VBRI 帧只是编码器写的元数据，不含音频，不计入时长
        if not seen_audio and any(
            tag in data[pos : pos + 44] for tag in (b"Xing", b"Info", b"VBRI")
        ):
            pos += length
            seen_audio = True
            continue
        seen_audio = True
        total += samples
        pos += length
    return total / rate if rate else 0.0


def mp3_file_duration(path: Path) -> float:
    return mp3_duration(path.read_bytes())
