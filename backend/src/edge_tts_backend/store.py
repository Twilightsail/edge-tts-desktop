import json
import sqlite3
import threading
from datetime import UTC, datetime
from pathlib import Path
from uuid import uuid4

from .models import Preferences, Status, SynthesisRequest, TaskError, TaskPage, TaskView


def now() -> str:
    return datetime.now(UTC).isoformat()


class Store:
    def __init__(self, path: Path):
        self.lock = threading.RLock()
        self.db = sqlite3.connect(path, check_same_thread=False)
        self.db.execute("PRAGMA journal_mode=WAL")
        self.db.execute("PRAGMA busy_timeout=5000")
        self.db.executescript("""
            CREATE TABLE IF NOT EXISTS tasks (
                id TEXT PRIMARY KEY, status TEXT NOT NULL, document TEXT NOT NULL
            );
            CREATE INDEX IF NOT EXISTS tasks_status ON tasks(status);
            CREATE TABLE IF NOT EXISTS settings (key TEXT PRIMARY KEY, value TEXT NOT NULL);
            PRAGMA user_version=1;
        """)
        self.db.commit()

    def close(self):
        with self.lock:
            self.db.close()

    def create(self, requests: list[SynthesisRequest]) -> list[TaskView]:
        result = []
        with self.lock, self.db:
            for request in requests:
                timestamp = now()
                task = TaskView(
                    id=uuid4().hex,
                    status=Status.queued,
                    request=request,
                    created_at=timestamp,
                    updated_at=timestamp,
                    stage="queued",
                )
                self.db.execute(
                    "INSERT INTO tasks VALUES (?,?,?)",
                    (
                        task.id,
                        task.status,
                        task.model_dump_json(),
                    ),
                )
                result.append(task)
        return result

    def get(self, task_id: str) -> TaskView | None:
        with self.lock:
            row = self.db.execute("SELECT document FROM tasks WHERE id=?", (task_id,)).fetchone()
        return TaskView.model_validate_json(row[0]) if row else None

    def update(self, task_id: str, **changes) -> TaskView:
        with self.lock, self.db:
            task = self.get(task_id)
            if task is None:
                raise KeyError(task_id)
            task = TaskView.model_validate(
                {
                    **task.model_dump(),
                    **changes,
                    "updated_at": now(),
                }
            )
            self.db.execute(
                "UPDATE tasks SET status=?,document=? WHERE id=?",
                (
                    task.status,
                    task.model_dump_json(),
                    task_id,
                ),
            )
            return task

    def page(self, status: Status | None, offset: int, limit: int, search: str = "") -> TaskPage:
        conditions, args = [], []
        if status:
            conditions.append("status=?")
            args.append(status)
        if search:
            conditions.append(
                "(instr(lower(json_extract(document,'$.request.title')),lower(?))>0 "
                "OR instr(lower(json_extract(document,'$.request.text')),lower(?))>0)"
            )
            args.extend([search, search])
        clause = " WHERE " + " AND ".join(conditions) if conditions else ""
        with self.lock:
            total = self.db.execute("SELECT COUNT(*) FROM tasks" + clause, args).fetchone()[0]
            rows = self.db.execute(
                "SELECT document FROM tasks" + clause + " ORDER BY rowid DESC LIMIT ? OFFSET ?",
                [*args, limit, offset],
            ).fetchall()
        return TaskPage(
            items=[TaskView.model_validate_json(row[0]) for row in rows],
            total=total,
            offset=offset,
            limit=limit,
        )

    def recover(self) -> list[TaskView]:
        with self.lock:
            rows = self.db.execute(
                "SELECT document FROM tasks WHERE status IN ('queued','running') ORDER BY rowid"
            ).fetchall()
            queued = []
            for row in rows:
                task = TaskView.model_validate_json(row[0])
                if task.status == Status.queued:
                    queued.append(task)
                else:
                    self.update(
                        task.id,
                        status=Status.failed,
                        stage="failed",
                        error=TaskError(
                            code="interrupted",
                            message="上次运行意外中断，请重试",
                            retryable=True,
                        ),
                    )
        return queued

    def delete(self, task_id: str):
        with self.lock, self.db:
            self.db.execute("DELETE FROM tasks WHERE id=?", (task_id,))

    def preferences(self) -> Preferences:
        with self.lock:
            row = self.db.execute("SELECT value FROM settings WHERE key='preferences'").fetchone()
        return Preferences.model_validate_json(row[0]) if row else Preferences()

    def save_preferences(self, preferences: Preferences):
        self.put_cache("preferences", preferences.model_dump())

    def get_cache(self, key: str):
        with self.lock:
            row = self.db.execute("SELECT value FROM settings WHERE key=?", (key,)).fetchone()
        return json.loads(row[0]) if row else None

    def put_cache(self, key: str, value):
        with self.lock, self.db:
            self.db.execute(
                "INSERT OR REPLACE INTO settings VALUES (?,?)",
                (
                    key,
                    json.dumps(value, ensure_ascii=False),
                ),
            )
