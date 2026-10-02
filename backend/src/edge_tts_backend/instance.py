import os
from pathlib import Path


class InstanceLock:
    """Prevent two backends from mutating the same history and artifacts."""

    def __init__(self, directory: Path):
        self.path = directory / ".backend.lock"
        self.stream = None

    def __enter__(self):
        self.stream = self.path.open("a+b")
        self.stream.seek(0, os.SEEK_END)
        if self.stream.tell() == 0:
            self.stream.write(b"0")
            self.stream.flush()
        self.stream.seek(0)
        try:
            if os.name == "nt":
                import msvcrt

                msvcrt.locking(self.stream.fileno(), msvcrt.LK_NBLCK, 1)
            else:
                import fcntl

                fcntl.flock(self.stream.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError as exc:
            self.stream.close()
            self.stream = None
            raise RuntimeError("已有后端使用此数据目录，请使用其他目录或关闭已有进程") from exc
        return self

    def __exit__(self, *args):
        if self.stream:
            self.stream.close()
            self.stream = None
