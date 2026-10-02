import re


def parse_srt(text: str) -> list[tuple[float, float, str]]:
    cues = []
    for block in re.split(r"\n\s*\n", text.replace("\r\n", "\n").strip()):
        lines = block.splitlines()
        timing = next((i for i, line in enumerate(lines) if " --> " in line), None)
        if timing is None:
            continue
        numbers = re.findall(r"\d+", lines[timing])
        if len(numbers) != 8:
            continue
        h, m, s, ms, eh, em, es, ems = map(int, numbers)
        start = h * 3600 + m * 60 + s + ms / 1000
        end = eh * 3600 + em * 60 + es + ems / 1000
        content = " ".join(lines[timing + 1 :]).strip()
        if end > start and content:
            cues.append((start, end, content))
    return cues


def timestamp(value: float, vtt: bool = False) -> str:
    millis = max(0, round(value * 1000))
    h, rest = divmod(millis, 3600000)
    m, rest = divmod(rest, 60000)
    s, ms = divmod(rest, 1000)
    return f"{h:02}:{m:02}:{s:02}{'.' if vtt else ','}{ms:03}"


def format_cues(cues, vtt: bool = False) -> str:
    blocks = []
    for i, (start, end, text) in enumerate(cues, 1):
        blocks.append(f"{i}\n{timestamp(start, vtt)} --> {timestamp(end, vtt)}\n{text}\n")
    return ("WEBVTT\n\n" if vtt else "") + "\n".join(blocks)


def optimize(cues, max_chars: int, offset_ms: int):
    result = []
    for start, end, text in cues:
        text = text.replace("\n", " ").strip()
        pieces = [text[i : i + max_chars * 2] for i in range(0, len(text), max_chars * 2)]
        for i, piece in enumerate(pieces):
            a = start + (end - start) * i / len(pieces) + offset_ms / 1000
            b = start + (end - start) * (i + 1) / len(pieces) + offset_ms / 1000
            if b <= 0:
                continue
            wrapped = "\n".join(piece[j : j + max_chars] for j in range(0, len(piece), max_chars))
            result.append((max(0, a), b, wrapped))
    result.sort(key=lambda cue: cue[0])
    for i in range(len(result) - 1):
        start, end, text = result[i]
        result[i] = (start, min(end, result[i + 1][0]), text)
    return [cue for cue in result if cue[1] > cue[0]]
