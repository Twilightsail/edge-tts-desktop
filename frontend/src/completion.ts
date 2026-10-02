import type { Api } from "./api";
import { notifyDesktop } from "./desktop";
import type { Task } from "./types";
import { clock } from "./ui";

const PREVIEW_TITLE = "音色试听";
const FLUSH_MS = 1200;

interface Finished { ok: boolean; title: string; detail: string }

/**
 * 监听任务状态事件：仅当任务从排队/合成中转为完成或失败、且窗口不在前台时发系统通知。
 * 短时间内连续完成的多个任务合并成一条，避免批量合成时刷屏。
 */
export function createCompletionNotifier(api: Api) {
  const live = new Set<string>();
  let buffer: Finished[] = [];
  let timer: ReturnType<typeof setTimeout> | undefined;

  const flush = () => {
    timer = undefined;
    const items = buffer;
    buffer = [];
    if (!items.length) return;
    if (items.length === 1) {
      const [t] = items;
      void notifyDesktop(t.ok ? "合成完成" : "合成失败", `${t.title}${t.detail ? ` · ${t.detail}` : ""}`);
      return;
    }
    const failed = items.filter((t) => !t.ok).length;
    void notifyDesktop("批量合成已结束", failed ? `${items.length - failed} 个完成，${failed} 个失败` : `${items.length} 个任务全部完成`);
  };

  const finish = async (id: string, status: string) => {
    if (document.hasFocus()) return;
    let task: Task;
    try { task = await api.task(id); } catch { return; }
    const title = task.request?.title ?? "";
    if (title === PREVIEW_TITLE) return;
    const name = title || task.request?.text.slice(0, 20) || "语音任务";
    buffer.push(
      status === "succeeded"
        ? { ok: true, title: name, detail: task.duration_seconds > 0 ? `时长 ${clock(task.duration_seconds)}` : "" }
        : { ok: false, title: name, detail: task.error?.message ?? "" },
    );
    timer ??= setTimeout(flush, FLUSH_MS);
  };

  return (kind: string, data: Partial<Task>) => {
    if (!data.id || (kind !== "task.created" && kind !== "task.updated")) return;
    if (data.status === "queued" || data.status === "running") {
      live.add(data.id);
    } else if ((data.status === "succeeded" || data.status === "failed") && live.delete(data.id)) {
      void finish(data.id, data.status);
    } else if (data.status) {
      live.delete(data.id);
    }
  };
}
