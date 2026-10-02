import { desktopConn, isDesktop } from "./desktop";
import type { About, EngineInfo, EngineName, Preferences, SynthesisRequest, Task, TaskPage, VoiceList, Preset, ImportedDocument, StorageInfo } from "./types";

export interface Conn {
  baseUrl: string;
  token: string;
}

export class ApiError extends Error {
  constructor(public code: string, message: string) {
    super(message);
  }
}

export async function getConn(): Promise<Conn> {
  if (isDesktop) return desktopConn();
  const res = await fetch("/__conn");
  if (!res.ok) throw new Error(`无法启动后端：${await res.text()}`);
  return res.json();
}

export class Api {
  constructor(private conn: Conn) {}

  private auth(): HeadersInit {
    return { Authorization: `Bearer ${this.conn.token}` };
  }

  private async request<T>(method: string, path: string, body?: unknown): Promise<T> {
    const res = await fetch(this.conn.baseUrl + path, {
      method,
      headers: body === undefined ? this.auth() : { ...this.auth(), "Content-Type": "application/json" },
      body: body === undefined ? undefined : JSON.stringify(body),
    });
    if (res.status === 204) return undefined as T;
    const data = await res.json().catch(() => null);
    if (!res.ok) {
      const err = data?.error;
      const detail = err?.details?.map((d: { message: string }) => d.message).join("；");
      throw new ApiError(err?.code ?? "http_error", [err?.message, detail].filter(Boolean).join("：") || `HTTP ${res.status}`);
    }
    return data as T;
  }

  voices = (refresh = false, engine: EngineName = "edge") =>
    this.request<VoiceList>("GET", `/api/voices?engine=${engine}${refresh ? "&refresh=true" : ""}`);
  engines = () => this.request<{ engines: EngineInfo[] }>("GET", "/api/engines").then((r) => r.engines);
  saveAzure = (region: string, key?: string) =>
    this.request<{ configured: boolean; region: string; key_hint: string }>("PUT", "/api/engines/azure", key ? { region, key } : { region });
  setAzureUsage = (body: { chars?: number; limit?: number }) =>
    this.request<{ month: string; chars: number; limit: number }>("PUT", "/api/engines/azure/usage", body);
  about = () => this.request<About>("GET", "/api/about");
  exportLogs = (destination: string) => this.request<{ destination: string; bytes: number }>("POST", "/api/logs/export", { destination, overwrite: true });
  deleteAzure = () => this.request<void>("DELETE", "/api/engines/azure");
  testAzure = () => this.request<{ ok: boolean; voices?: number; message?: string }>("POST", "/api/engines/azure/test");
  tasks = (search = "", status = "", offset = 0, limit = 50) => this.request<TaskPage>("GET", `/api/tasks?${new URLSearchParams({ search, offset: String(offset), limit: String(limit), ...(status ? { status } : {}) })}`);
  task = (id: string) => this.request<Task>("GET", `/api/tasks/${id}`);
  create = (body: SynthesisRequest) => this.request<Task>("POST", "/api/tasks", body);
  batch = (items: SynthesisRequest[]) => this.request<Task[]>("POST", "/api/tasks/batch", { items });
  cancel = (id: string) => this.request<Task>("POST", `/api/tasks/${id}/cancel`);
  retry = (id: string) => this.request<Task>("POST", `/api/tasks/${id}/retry`);
  settings = () => this.request<Preferences>("GET", "/api/settings");
  saveSettings = (p: Preferences) => this.request<Preferences>("PUT", "/api/settings", p);
  export = (id: string, destination: string, kind: "audio" | "subtitles" | "vtt") =>
    this.request<{ destination: string; bytes: number }>("POST", `/api/tasks/${id}/export`, { destination, kind, overwrite: true });
  remove = (id: string) => this.request<void>("DELETE", `/api/tasks/${id}`);
  removeMany = (ids: string[]) => this.request<{ deleted: string[]; errors: {id: string; message: string}[] }>("POST", "/api/tasks/delete-many", { ids });
  rename = (id: string, title: string) => this.request<Task>("PUT", `/api/tasks/${id}/title`, { title });
  favorites = () => this.request<{ voices: string[] }>("GET", "/api/favorites");
  saveFavorites = (voices: string[]) => this.request<{ voices: string[] }>("PUT", "/api/favorites", { voices });
  presets = () => this.request<Preset[]>("GET", "/api/presets");
  savePreset = (name: string, settings: Preferences) => this.request<Preset>("POST", "/api/presets", { name, settings });
  updatePreset = (id: string, name: string, settings: Preferences) => this.request<Preset>("PUT", `/api/presets/${id}`, { name, settings });
  deletePreset = (id: string) => this.request<void>("DELETE", `/api/presets/${id}`);
  preview = (settings: Preferences) => this.request<Task>("POST", "/api/voices/preview", settings);
  storage = () => this.request<StorageInfo>("GET", "/api/storage");
  clearCache = () => this.request<{ cleared: boolean }>("DELETE", "/api/storage/segment-cache");

  async importDocument(file: File): Promise<ImportedDocument> {
    const form = new FormData(); form.append("file", file);
    const res = await fetch(this.conn.baseUrl + "/api/documents/import", { method: "POST", headers: this.auth(), body: form });
    const data = await res.json();
    if (!res.ok) throw new Error(data.error?.message || "文档导入失败");
    return data;
  }

  async archive(ids: string[], destination?: string): Promise<Blob | { destination: string }> {
    const res = await fetch(this.conn.baseUrl + "/api/tasks/export-zip", { method: "POST",
      headers: { ...this.auth(), "Content-Type": "application/json" },
      body: JSON.stringify({ ids, destination, overwrite: !!destination, include_subtitles: true }) });
    if (!res.ok) { const data = await res.json(); throw new Error(data.error?.message || "批量导出失败"); }
    return destination ? res.json() : res.blob();
  }

  /** 带鉴权取回音频/字幕为 Blob（audio 标签无法自带 Authorization）。 */
  async blob(path: string): Promise<Blob> {
    const res = await fetch(this.conn.baseUrl + path, { headers: this.auth() });
    if (!res.ok) throw new Error("文件加载失败");
    return res.blob();
  }

  /** 订阅 SSE，返回取消函数；断线后 2 秒重连（重连会收到新的 snapshot）。 */
  events(onEvent: (event: string, data: any) => void, onState: (online: boolean) => void): () => void {
    const ctrl = new AbortController();
    const run = async () => {
      while (!ctrl.signal.aborted) {
        try {
          const res = await fetch(this.conn.baseUrl + "/api/events", { headers: this.auth(), signal: ctrl.signal });
          if (!res.ok || !res.body) throw new Error("sse");
          onState(true);
          const reader = res.body.pipeThrough(new TextDecoderStream()).getReader();
          let buf = "";
          for (;;) {
            const { value, done } = await reader.read();
            if (done) break;
            buf += value;
            let i;
            while ((i = buf.indexOf("\n\n")) >= 0) {
              const block = buf.slice(0, i);
              buf = buf.slice(i + 2);
              const ev = /^event: (.+)$/m.exec(block)?.[1];
              const data = /^data: (.+)$/m.exec(block)?.[1];
              if (ev && data) onEvent(ev, JSON.parse(data));
            }
          }
        } catch {
          /* 落入重连 */
        }
        if (ctrl.signal.aborted) return;
        onState(false);
        await new Promise((r) => setTimeout(r, 2000));
      }
    };
    void run();
    return () => ctrl.abort();
  }
}
