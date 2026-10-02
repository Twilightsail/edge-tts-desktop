import { useCallback, useEffect, useMemo, useRef, useState, type CSSProperties } from "react";
import { Api, getConn } from "./api";
import Chat from "./Chat";
import { createCompletionNotifier } from "./completion";
import { notifyDesktop } from "./desktop";
import Composer from "./Composer";
import { AppCtx, type Ctx } from "./ctx";
import Panel from "./Panel";
import { usePlayer } from "./player";
import { useEscape } from "./useEscape";
import Sidebar, { SIDE_MAX, SIDE_MIN } from "./Sidebar";
import type { EngineInfo, EngineName, Preferences, SynthesisRequest, Task, Voice } from "./types";
import { Icon } from "./ui";

type Theme = "light" | "dark";
const initialTheme = (): Theme => {
  const saved = localStorage.getItem("theme");
  return saved === "light" || saved === "dark" ? saved : matchMedia("(prefers-color-scheme: dark)").matches ? "dark" : "light";
};

const DEFAULT_PREFS: Preferences = { engine: "edge", style: "", voice: "zh-CN-XiaoxiaoNeural", rate: 0, volume: 0, pitch: 0, subtitles: true, subtitle_max_chars: 24, subtitle_offset_ms: 0 };
const defaultVoice = (list: Voice[]) => (list.find((v) => v.Locale === "zh-CN") ?? list[0]).ShortName;
const favKey = (engine: EngineName, shortName: string) => (engine === "azure" ? `azure:${shortName}` : shortName);
const SIDE_KEY = "sidebar";
const loadSide = (): { w: number; collapsed: boolean } => {
  try {
    const s = JSON.parse(localStorage.getItem(SIDE_KEY) ?? "null");
    return { w: Math.max(SIDE_MIN, Math.min(SIDE_MAX, Number(s?.w) || 340)), collapsed: !!s?.collapsed };
  } catch {
    return { w: 340, collapsed: false };
  }
};

export default function StudioApp() {
  const [api, setApi] = useState<Api>();
  const [fatal, setFatal] = useState("");
  const [theme, setTheme] = useState<Theme>(initialTheme);
  const firstTheme = useRef(true);
  useEffect(() => {
    const root = document.documentElement;
    if (!firstTheme.current) {
      root.classList.add("theming"); // 切换主题时让颜色平滑过渡，结束后移除以免影响其他动画
      setTimeout(() => root.classList.remove("theming"), 450);
    }
    firstTheme.current = false;
    root.dataset.theme = theme;
    localStorage.setItem("theme", theme);
  }, [theme]);
  useEffect(() => { getConn().then((c) => setApi(new Api(c))).catch((e) => setFatal(e.message)); }, []);

  if (fatal) return <div className="splash error-text">{fatal}</div>;
  if (!api) return <div className="splash"><span className="spinner big" />正在启动语音引擎…</div>;
  return <Workspace api={api} dark={theme === "dark"} onTheme={() => setTheme(theme === "dark" ? "light" : "dark")} />;
}

function Workspace({ api, dark, onTheme }: { api: Api; dark: boolean; onTheme: () => void }) {
  const [voices, setVoices] = useState<Voice[]>([]);
  const [favorites, setFavorites] = useState<string[]>([]);
  const [prefs, setPrefs] = useState<Preferences>(DEFAULT_PREFS);
  const [online, setOnline] = useState(false);
  const [revision, setRevision] = useState(0);
  const [event, setEvent] = useState<Partial<Task>>();
  const [panel, setPanel] = useState(() => innerWidth >= 1180);
  const [draft, setDraft] = useState<{ request: SynthesisRequest; nonce: number }>();
  const [dropped, setDropped] = useState<{ file: File; nonce: number }>();
  const [sendNonce, setSendNonce] = useState(0);
  const [previewing, setPreviewing] = useState("");
  const [toast, setToast] = useState<{ id: number; text: string; kind: "ok" | "err"; leaving?: boolean }>();
  const player = usePlayer();
  const nonce = useRef(0);

  // 左侧音色栏：宽度可拖动、可折叠成头像窄栏，状态记在本机
  const [side, setSide] = useState(loadSide);
  const [dragging, setDragging] = useState(false);
  const [snapping, setSnapping] = useState(false); // 吸附/展开瞬间保留过渡动画
  const sideRef = useRef(side);
  sideRef.current = side;
  const snapTimer = useRef<ReturnType<typeof setTimeout>>();
  useEffect(() => {
    try { localStorage.setItem(SIDE_KEY, JSON.stringify(side)); } catch { /* 无法保存时忽略 */ }
  }, [side]);
  const setCollapsed = useCallback((collapsed: boolean) => {
    if (sideRef.current.collapsed === collapsed) return;
    setSide((s) => ({ ...s, collapsed }));
    setSnapping(true);
    clearTimeout(snapTimer.current);
    snapTimer.current = setTimeout(() => setSnapping(false), 450);
  }, []);
  const toggleSide = useCallback(() => setCollapsed(!sideRef.current.collapsed), [setCollapsed]);
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if ((e.ctrlKey || e.metaKey) && e.key.toLowerCase() === "b") { e.preventDefault(); toggleSide(); }
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [toggleSide]);

  const changed = useCallback(() => setRevision((n) => n + 1), []);
  const notify = useCallback((text: string, kind: "ok" | "err" = "ok") => setToast({ id: ++nonce.current, text, kind }), []);
  useEffect(() => {
    if (!toast || toast.leaving) return;
    const t = setTimeout(() => setToast((cur) => (cur ? { ...cur, leaving: true } : cur)), toast.kind === "err" ? 6000 : 3500);
    return () => clearTimeout(t);
  }, [toast]);
  useEffect(() => {
    if (!toast?.leaving) return;
    const t = setTimeout(() => setToast(undefined), 220);
    return () => clearTimeout(t);
  }, [toast?.leaving]);

  // 引擎：Edge（免费）与 Azure（需自备密钥）。两者音色名可能相同，所以一切按引擎隔离。
  const [engines, setEngines] = useState<EngineInfo[]>([]);
  const [settingsFocus, setSettingsFocus] = useState(0);
  useEscape(panel, () => setPanel(false));
  const engineRef = useRef(prefs.engine);
  const reloadEngines = useCallback(() => api.engines().then(setEngines).catch(() => {}), [api]);

  const loadVoices = useCallback(async (refresh = false) => {
    const engine = engineRef.current;
    const v = await api.voices(refresh, engine);
    if (engineRef.current !== engine) return v; // 加载期间切换了引擎，丢弃过期结果
    setVoices(v.items);
    // 切换引擎后当前音色可能不存在，自动换成该引擎的默认中文音色
    setPrefs((p) => (v.items.length && !v.items.some((x) => x.ShortName === p.voice) ? { ...p, voice: defaultVoice(v.items) } : p));
    return v;
  }, [api]);

  useEffect(() => {
    engineRef.current = prefs.engine;
    setVoices([]);
    loadVoices()
      .then((v) => { if (v.stale) notify("网络不可用，正在使用缓存的音色列表", "err"); })
      .catch((e) => { if (e.code !== "engine_not_configured") notify(e.message, "err"); });
  }, [prefs.engine, loadVoices, notify]);

  useEffect(() => {
    void reloadEngines();
    api.settings().then(setPrefs).catch((e) => notify(e.message, "err"));
    api.favorites().then((r) => setFavorites(r.voices)).catch((e) => notify(e.message, "err"));
    const completed = createCompletionNotifier(api);
    return api.events((kind, data) => {
      completed(kind, data);
      if (kind === "task.updated" && data.status === "succeeded") void reloadEngines(); // 成功的请求会增加 Azure 用量
      if (kind === "task.updated") { setEvent(data); if (data.status !== "running") changed(); }
      else changed();
    }, setOnline);
  }, [api, changed, reloadEngines, notify]);

  // Azure 额度提醒：每个月、每个阈值只提醒一次（记在本机）
  useEffect(() => {
    const usage = engines.find((e) => e.id === "azure")?.usage;
    if (!usage || usage.limit <= 0) return;
    const ratio = usage.chars / usage.limit;
    for (const level of [1, 0.8]) {
      if (ratio < level) continue;
      const key = `azureWarn:${usage.month}:${level}`;
      try { if (localStorage.getItem(key)) return; localStorage.setItem(key, "1"); } catch { /* 无法记录时宁可重复提醒 */ }
      const text = level === 1
        ? `Azure 本月免费额度已用完（约 ${usage.chars.toLocaleString()} / ${usage.limit.toLocaleString()} 字符），继续使用可能被限流或产生费用`
        : `Azure 本月额度已用约 ${Math.round(ratio * 100)}%（${usage.chars.toLocaleString()} / ${usage.limit.toLocaleString()} 字符）`;
      notify(text, "err");
      if (!document.hasFocus()) void notifyDesktop("Azure 额度提醒", text);
      return;
    }
  }, [engines, notify]);

  // 音色或引擎变了，当前风格可能不再适用（只有 Azure 的部分音色支持风格）
  useEffect(() => {
    if (!prefs.style) return;
    const voice = voices.find((v) => v.ShortName === prefs.voice);
    if (prefs.engine !== "azure" || (voice && !(voice.StyleList ?? []).includes(prefs.style))) setPrefs((p) => ({ ...p, style: "" }));
  }, [prefs.engine, prefs.voice, prefs.style, voices]);

  const voiceMap = useMemo(() => new Map(voices.map((v) => [v.ShortName, v])), [voices]);

  const setPref: Ctx["setPref"] = useCallback((key, value) => setPrefs((p) => ({ ...p, [key]: value })), []);

  // 收藏按引擎保存（Azure 的收藏带 "azure:" 前缀，Edge 的保持原样以兼容旧数据）；对界面只暴露当前引擎的
  const favNames = useMemo(
    () => favorites.filter((f) => f.startsWith("azure:") === (prefs.engine === "azure")).map((f) => f.replace(/^azure:/, "")),
    [favorites, prefs.engine],
  );
  const toggleFavorite = useCallback(async (shortName: string) => {
    try {
      const key = favKey(prefs.engine, shortName);
      const next = favorites.includes(key) ? favorites.filter((v) => v !== key) : [...favorites, key];
      setFavorites((await api.saveFavorites(next)).voices);
    } catch (e) { notify((e as Error).message, "err"); }
  }, [api, favorites, notify, prefs.engine]);

  const openAzureSettings = useCallback(() => { setPanel(true); setSettingsFocus((n) => n + 1); }, []);
  const setEngine = useCallback((engine: EngineName) => {
    if (engine === prefs.engine) return;
    if (engine === "azure" && !engines.find((e) => e.id === "azure")?.configured) {
      openAzureSettings();
      notify("请先在右侧面板填写 Azure 密钥和区域", "err");
      return;
    }
    setPrefs((p) => ({ ...p, engine, rate: engine === "azure" ? Math.max(p.rate, -50) : p.rate })); // Azure 语速下限约 -50%
  }, [engines, notify, openAzureSettings, prefs.engine]);

  /** 音色试听：同一音色与参数的结果在本次会话内缓存，重复点击直接播放/暂停。 */
  const previewVoice = useCallback(async (shortName: string) => {
    const settings = { ...prefs, voice: shortName };
    const key = `preview:${prefs.engine}:${shortName}:${prefs.style}:${prefs.rate}:${prefs.volume}:${prefs.pitch}`;
    const load = async () => {
      setPreviewing(shortName);
      let task: Task | undefined;
      try {
        task = await api.preview(settings);
        const deadline = Date.now() + 180000;
        while (Date.now() < deadline) {
          const r = await api.task(task.id);
          if (r.status === "failed" || r.status === "cancelled") throw new Error(r.error?.message || "试听已取消");
          if (r.status === "succeeded") return await api.blob(r.audio_url!);
          await new Promise((res) => setTimeout(res, 500));
        }
        throw new Error("试听超时，请稍后再试");
      } finally {
        setPreviewing("");
        if (task) void api.remove(task.id).catch(() => api.cancel(task!.id).catch(() => {}));
      }
    };
    try { await player.toggle(key, load); } catch (e) { notify((e as Error).message, "err"); }
  }, [api, notify, player, prefs]);

  const ctx: Ctx = {
    api, notify, voices, voiceMap, favorites: favNames, toggleFavorite, prefs, setPref, setPrefs, player,
    previewVoice, previewing, changed, revision, event, engines, reloadEngines, setEngine,
    openAzureSettings, refreshVoices: loadVoices,
  };

  return (
    <AppCtx.Provider value={ctx}>
      <div
        className={["shell", panel && "with-panel", side.collapsed && "collapsed", dragging && !snapping && "resizing"].filter(Boolean).join(" ")}
        style={{ "--side-w": `${side.w}px` } as CSSProperties}
      >
        <Sidebar
          dark={dark}
          collapsed={side.collapsed}
          onToggle={toggleSide}
          onWidth={(w) => setSide((s) => ({ ...s, w }))}
          onCollapse={setCollapsed}
          onDragging={setDragging}
          onTheme={onTheme}
          onRefreshVoices={() => void loadVoices(true).then((v) => notify(v.stale ? "刷新失败，缓存可继续使用" : "音色列表已刷新", v.stale ? "err" : "ok")).catch((e) => notify(e.message, "err"))}
          onOpenSettings={() => setPanel(true)}
          onOpenAzure={openAzureSettings}
        />
        <Chat
          edit={(request) => setDraft({ request, nonce: ++nonce.current })}
          panelOpen={panel}
          onPanel={() => setPanel(!panel)}
          online={online}
          sendNonce={sendNonce}
          onDropFile={(file) => setDropped({ file, nonce: ++nonce.current })}
        >
          <Composer draft={draft} dropped={dropped} onSent={() => setSendNonce((n) => n + 1)} />
        </Chat>
        <div className={panel ? "panel-scrim show" : "panel-scrim"} onClick={() => setPanel(false)} />
        <Panel
          open={panel}
          focusAzure={settingsFocus}
          onClose={() => setPanel(false)}
          onRefreshVoices={() => void loadVoices(true).then((v) => notify(v.stale ? "刷新失败，缓存可继续使用" : "音色列表已刷新", v.stale ? "err" : "ok")).catch((e) => notify(e.message, "err"))}
        />
        {toast && (
          <div className={`toast ${toast.kind}${toast.leaving ? " leaving" : ""}`} role="status" key={toast.id} onClick={() => setToast((cur) => (cur ? { ...cur, leaving: true } : cur))}>
            <Icon name={toast.kind === "ok" ? "check" : "alert"} size={18} />{toast.text}
          </div>
        )}
      </div>
    </AppCtx.Provider>
  );
}
