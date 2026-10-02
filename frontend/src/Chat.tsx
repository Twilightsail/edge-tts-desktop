import { useEffect, useLayoutEffect, useRef, useState, type ReactNode } from "react";
import { useApp } from "./ctx";
import { isDesktop, pickSavePath } from "./desktop";
import { localeName } from "./locales";
import Segmented from "./Segmented";
import { useEscape } from "./useEscape";
import TaskMessage from "./TaskMessage";
import type { SynthesisRequest, Task, TaskPage } from "./types";
import { Avatar, dayLabel, genderLabel, Icon, isLive, saveBlob, voiceName } from "./ui";

const STATUSES: [string, string][] = [["", "全部"], ["succeeded", "已完成"], ["running", "合成中"], ["queued", "排队中"], ["failed", "失败"], ["cancelled", "已取消"]];
const PREVIEW_TITLE = "音色试听";
const STEP = 50;
const MAX = 200;

interface Props {
  edit: (request: SynthesisRequest) => void;
  panelOpen: boolean;
  onPanel: () => void;
  online: boolean;
  sendNonce: number;
  onDropFile: (file: File) => void;
  children: ReactNode; // 输入栏
}

export default function Chat({ edit, panelOpen, onPanel, online, sendNonce, onDropFile, children }: Props) {
  const { api, notify, revision, event, changed, prefs, voiceMap, previewVoice, previewing, player } = useApp();
  const [query, setQuery] = useState("");
  const [status, setStatus] = useState("");
  const [searchOpen, setSearchOpen] = useState(false);
  const [limit, setLimit] = useState(STEP);
  const [page, setPage] = useState<TaskPage>({ items: [], total: 0, offset: 0, limit: STEP });
  const [selecting, setSelecting] = useState(false);
  const [chosen, setChosen] = useState<Record<string, Task>>({});
  const [confirmDelete, setConfirmDelete] = useState(false);
  const [busy, setBusy] = useState(false);
  const [drag, setDrag] = useState(false);

  const searchInput = useRef<HTMLInputElement>(null);
  useEffect(() => {
    if (!searchOpen) return;
    const t = setTimeout(() => searchInput.current?.focus(), 160); // 等展开动画走完再聚焦，避免滚动跳动
    return () => clearTimeout(t);
  }, [searchOpen]);

  const scroller = useRef<HTMLDivElement>(null);
  const stick = useRef(true);
  const anchor = useRef<number | null>(null);
  const generation = useRef(0);

  useEffect(() => {
    const id = ++generation.current;
    const timer = setTimeout(() => {
      api.tasks(query, status, 0, limit).then((result) => {
        if (id === generation.current) setPage(result);
      }).catch((e) => { if (id === generation.current) notify(e.message, "err"); });
    }, 150);
    return () => { clearTimeout(timer); generation.current++; };
  }, [api, query, status, limit, revision, notify]);

  useEffect(() => {
    if (!event?.id) return;
    setPage((p) => ({ ...p, items: p.items.map((t) => (t.id === event.id ? { ...t, ...event } : t)) }));
  }, [event]);

  useEffect(() => { stick.current = true; }, [sendNonce]);

  const shown = page.items.filter((t) => t.request?.title !== PREVIEW_TITLE).slice().reverse();

  const loaded = useRef(false);
  const lastNewest = useRef("");
  useLayoutEffect(() => {
    const el = scroller.current;
    if (!el) return;
    if (anchor.current !== null) {
      el.scrollTop += el.scrollHeight - anchor.current;
      anchor.current = null;
    } else if (stick.current) {
      // 首次载入直接到底；之后有新消息时平滑滚动
      const newest = page.items[0]?.id ?? "";
      const smooth = loaded.current && newest !== lastNewest.current;
      el.scrollTo({ top: el.scrollHeight, behavior: smooth ? "smooth" : "auto" });
      lastNewest.current = newest;
      if (page.items.length) loaded.current = true;
    }
  }, [page.items, searchOpen]);

  const onScroll = () => {
    const el = scroller.current!;
    stick.current = el.scrollHeight - el.scrollTop - el.clientHeight < 120;
  };

  const loadEarlier = () => {
    anchor.current = scroller.current!.scrollHeight;
    setLimit((n) => Math.min(MAX, n + STEP));
  };

  const action = async (fn: () => Promise<void>) => {
    setBusy(true);
    try { await fn(); } catch (e) { notify((e as Error).message, "err"); } finally { setBusy(false); }
  };

  const chosenIds = Object.keys(chosen);
  const toggle = (task: Task) => setChosen((c) => {
    const next = { ...c };
    if (next[task.id]) delete next[task.id];
    else if (Object.keys(next).length < MAX) next[task.id] = task;
    return next;
  });
  const endSelect = () => { setSelecting(false); setChosen({}); setConfirmDelete(false); };
  useEscape(selecting, endSelect);
  useEscape(searchOpen, () => { setSearchOpen(false); setQuery(""); setStatus(""); });

  const exportMany = () => action(async () => {
    if (!chosenIds.length) throw new Error("请先选择已完成的任务");
    if (Object.values(chosen).some((t) => t.status !== "succeeded")) throw new Error("ZIP 导出仅支持已完成任务，请取消选择失败或取消的任务");
    if (isDesktop) {
      const dest = await pickSavePath("配音导出.zip", "zip");
      if (dest) { await api.archive(chosenIds, dest); notify(`已保存到 ${dest}`, "ok"); }
    } else {
      saveBlob((await api.archive(chosenIds)) as Blob, "配音导出.zip");
    }
  });

  const removeMany = () => action(async () => {
    chosenIds.forEach(player.forget);
    const result = await api.removeMany(chosenIds);
    setChosen((c) => Object.fromEntries(Object.entries(c).filter(([id]) => !result.deleted.includes(id))));
    setConfirmDelete(false);
    changed();
    if (result.errors.length) throw new Error(`已删除 ${result.deleted.length} 项；${result.errors.map((e) => e.message).join("；")}`);
    endSelect();
  });

  const voice = voiceMap.get(prefs.voice);
  const items: ReactNode[] = [];
  let lastDay = "";
  for (const task of shown) {
    const day = dayLabel(task.created_at);
    if (day !== lastDay) {
      items.push(<div className="day" key={`d-${day}-${task.id}`}><span>{day}</span></div>);
      lastDay = day;
    }
    items.push(<TaskMessage key={task.id} task={task} selecting={selecting} chosen={!!chosen[task.id]} toggle={() => toggle(task)} edit={edit} />);
  }
  const hidden = page.total - page.items.length;

  return (
    <section
      className={drag ? "chat dragging" : "chat"}
      onDragOver={(e) => { e.preventDefault(); setDrag(true); }}
      onDragLeave={(e) => { if (e.currentTarget === e.target) setDrag(false); }}
      onDrop={(e) => { e.preventDefault(); setDrag(false); const f = e.dataTransfer.files[0]; if (f) onDropFile(f); }}
    >
      <header className="chat-head">
        <span key={prefs.voice} className="swap-in"><Avatar name={voiceName(prefs.voice)} size={42} /></span>
        <div className="ch-title" onClick={onPanel}>
          <strong key={prefs.voice} className="swap-in">{voiceName(prefs.voice)}</strong>
          <span className={online ? "ch-sub online" : "ch-sub"}>
            {online ? "引擎已连接" : "重连中…"} · {voice ? `${localeName(voice.Locale)} · ${genderLabel(voice.Gender)}` : prefs.voice}
          </span>
        </div>
        <button className="round" title="试听当前音色" onClick={() => void previewVoice(prefs.voice)}>
          {previewing === prefs.voice ? <span className="spinner" /> : <Icon name="speaker" />}
        </button>
        <button className={searchOpen ? "round on" : "round"} title="搜索历史" onClick={() => { setSearchOpen(!searchOpen); if (searchOpen) { setQuery(""); setStatus(""); } }}><Icon name="search" /></button>
        <button className={selecting ? "round on" : "round"} title="多选" onClick={() => (selecting ? endSelect() : setSelecting(true))}><Icon name="select" /></button>
        <button className={panelOpen ? "round on" : "round"} title="合成设置" onClick={onPanel}><Icon name="info" /></button>
      </header>

      <div className={searchOpen ? "collapse open" : "collapse"} aria-hidden={!searchOpen}>
        <div className="collapse-in">
          <div className="search-bar">
            <label className="search-box">
              <Icon name="search" size={18} />
              <input ref={searchInput} tabIndex={searchOpen ? 0 : -1} aria-label="搜索全部历史" placeholder="搜索全部历史的标题或正文" value={query} onChange={(e) => setQuery(e.target.value)} />
            </label>
            <Segmented variant="pill" className="small scroll" options={STATUSES} value={status} onChange={setStatus} />
          </div>
        </div>
      </div>

      <div className="messages" ref={scroller} onScroll={onScroll}>
        <div className="messages-inner">
          {hidden > 0 && page.items.length < MAX && (
            <button className="earlier" onClick={loadEarlier}>加载更早的消息（还有 {hidden} 条）</button>
          )}
          {hidden > 0 && page.items.length >= MAX && <div className="day"><span>仅显示最近 {MAX} 条，更早的请用搜索</span></div>}
          {shown.length === 0 ? (
            <div className="chat-empty">
              <Avatar name={voiceName(prefs.voice)} size={72} />
              <h3>{query || status ? "没有符合条件的消息" : `和 ${voiceName(prefs.voice)} 开始对话`}</h3>
              <p>{query || status ? "换个关键词或状态试试" : "在下方输入文本发送，它会用当前音色读给你听。也可以点回形针导入 TXT、Markdown、DOCX 文档。"}</p>
            </div>
          ) : items}
        </div>
      </div>

      {drag && <div className="drop-hint"><Icon name="doc" size={44} />松开以导入文档（TXT / Markdown / DOCX）</div>}

      {selecting ? (
        <div className="select-bar">
          {confirmDelete ? (
            <>
              <span>确认删除所选 {chosenIds.length} 项及其内部音频？</span>
              <button className="danger" disabled={busy} onClick={removeMany}>确认删除</button>
              <button onClick={() => setConfirmDelete(false)}>保留</button>
            </>
          ) : (
            <>
              <button className="round" title="退出多选" onClick={endSelect}><Icon name="close" /></button>
              <strong>已选 {chosenIds.length}</strong>
              <button onClick={() => setChosen(Object.fromEntries(shown.filter((t) => !isLive(t)).slice(0, MAX).map((t) => [t.id, t])))}>全选</button>
              <span className="grow" />
              <button disabled={busy || !chosenIds.length} onClick={exportMany}><Icon name="zip" size={18} />导出 ZIP</button>
              <button className="danger" disabled={busy || !chosenIds.length} onClick={() => setConfirmDelete(true)}><Icon name="trash" size={18} />删除</button>
            </>
          )}
        </div>
      ) : children}
    </section>
  );
}
