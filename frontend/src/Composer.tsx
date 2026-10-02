import { useEffect, useRef, useState } from "react";
import { useApp } from "./ctx";
import { localeName } from "./locales";
import type { ImportedDocument, Preferences, Segment, SynthesisRequest } from "./types";
import Segmented from "./Segmented";
import { useEscape } from "./useEscape";
import { billableChars, Icon, voiceName } from "./ui";

const MAX = 100_000;

export function splitLargeText(text: string, limit = 95000): string[] {
  const parts: string[] = [];
  while (text.length > limit) {
    let cut = text.lastIndexOf("\n", limit);
    if (cut < limit / 2) cut = limit;
    if (/[\uD800-\uDBFF]/.test(text[cut - 1]) && /[\uDC00-\uDFFF]/.test(text[cut])) cut--;
    parts.push(text.slice(0, cut));
    text = text.slice(cut);
  }
  if (text.trim()) parts.push(text);
  return parts;
}

type Mode = "single" | "batch" | "project";
const MODES: [Mode, string][] = [["single", "整篇合成"], ["batch", "分段独立文件"], ["project", "章节 / 多角色"]];

interface Props {
  draft?: { request: SynthesisRequest; nonce: number };
  dropped?: { file: File; nonce: number };
  onSent: () => void;
}

export default function Composer({ draft, dropped, onSent }: Props) {
  const { api, voices, prefs, setPrefs, notify, changed, engines } = useApp();
  const [text, setText] = useState("");
  const [title, setTitle] = useState("");
  const [mode, setMode] = useState<Mode>("single");
  const [segments, setSegments] = useState<Segment[]>([]);
  const [imported, setImported] = useState<ImportedDocument>();
  const [editor, setEditor] = useState(false);
  const [busy, setBusy] = useState(false);
  const fileRef = useRef<HTMLInputElement>(null);
  const area = useRef<HTMLTextAreaElement>(null);

  const action = async (fn: () => Promise<void>) => {
    try { await fn(); } catch (e) { notify((e as Error).message, "err"); }
  };

  useEffect(() => {
    const el = area.current;
    if (!el) return;
    // 先量出目标高度，再从当前高度过渡过去，输入多行时输入框是“长”出来的
    const prev = el.offsetHeight;
    el.style.height = "auto";
    const next = Math.min(el.scrollHeight, 180);
    el.style.height = `${prev}px`;
    void el.offsetHeight;
    el.style.height = `${next}px`;
  }, [text, mode]);

  useEscape(editor, () => setEditor(false));
  const [editorMounted, setEditorMounted] = useState(false);
  useEffect(() => {
    if (editor) { setEditorMounted(true); return; }
    const t = setTimeout(() => setEditorMounted(false), 260); // 等退场动画结束再卸载
    return () => clearTimeout(t);
  }, [editor]);

  useEffect(() => {
    if (!draft) return;
    const { text, title, segments, engine, voice, rate, volume, pitch, subtitles, subtitle_max_chars, subtitle_offset_ms } = draft.request;
    setText(text);
    setTitle(title);
    setPrefs({ engine: engine ?? "edge", style: draft.request.style ?? "", voice, rate, volume, pitch, subtitles, subtitle_max_chars: subtitle_max_chars ?? 24, subtitle_offset_ms: subtitle_offset_ms ?? 0 } as Preferences);
    setSegments(segments ?? []);
    setMode(segments?.length ? "project" : "single");
    notify("已载入原任务，可修改后重新生成；未变化的分段会复用缓存", "ok");
    area.current?.focus();
  }, [draft]); // eslint-disable-line react-hooks/exhaustive-deps

  const loadFile = (file?: File) => action(async () => {
    if (!file) return;
    if (file.size > 8 * 1024 * 1024) throw new Error("文件超过 8 MB，请先拆分");
    setBusy(true);
    try { setImported(await api.importDocument(file)); } finally { setBusy(false); }
  });

  useEffect(() => { if (dropped) void loadFile(dropped.file); }, [dropped]); // eslint-disable-line react-hooks/exhaustive-deps

  const paragraphs = text.split(/\n\s*\n/).map((s) => s.trim()).filter(Boolean);
  const parts = text.length > MAX ? splitLargeText(text) : paragraphs.flatMap((p) => splitLargeText(p));
  const chars = mode === "project" ? segments.reduce((n, s) => n + s.text.length, 0) + Math.max(0, segments.length - 1) * 2 : text.length;
  const valid = mode === "batch" ? parts.length > 0 && parts.length <= 50 : chars > 0 && chars <= MAX && (mode !== "project" || segments.every((s) => s.text.trim()));

  const switchMode = (next: Mode) => {
    if (mode === "project" && next !== "project") setText(segments.map((s) => s.text).join("\n\n"));
    if (next === "project" && !segments.length) {
      const chunks = paragraphs.length <= 200 ? paragraphs : splitLargeText(text, 2000);
      setSegments(chunks.map((t, i) => ({ text: t, title: `第 ${i + 1} 段`, voice: prefs.voice })));
    }
    setMode(next);
    if (next === "project") setEditor(true);
  };

  const applyImport = () => {
    if (!imported) return;
    setText(imported.text);
    setSegments([]);
    setMode(imported.requires_split ? "batch" : "single");
    setTitle(imported.name.replace(/\.[^.]+$/, "").slice(0, 120));
    setImported(undefined);
    notify("已完整导入正文，可修改后再发送", "ok");
  };

  const submit = () => action(async () => {
    if (!valid || busy) return;
    setBusy(true);
    try {
      const base = { ...prefs, title: title.trim(), segment_chars: 2000 };
      if (mode === "batch") {
        await api.batch(parts.map((t, i) => ({ ...base, text: t, title: `${title.trim() || "段落"} ${i + 1}`.slice(0, 120) })));
      } else {
        await api.create({ ...base, text: mode === "project" ? "" : text, segments: mode === "project" ? segments : [] });
      }
      setText("");
      setTitle("");
      if (mode === "project") { setSegments([]); setMode("single"); }
      onSent();
      changed();
      try { await api.saveSettings(prefs); } catch { notify("任务已提交，但参数偏好保存失败", "err"); }
    } finally { setBusy(false); }
  });

  const editSegment = (i: number, changes: Partial<Segment>) => setSegments((ss) => ss.map((s, k) => (k === i ? { ...s, ...changes } : s)));
  const move = (i: number, d: number) => setSegments((ss) => { const r = [...ss]; [r[i], r[i + d]] = [r[i + d], r[i]]; return r; });

  // Azure 按字符计费：发送前预估这次会消耗多少本月额度
  const usage = engines.find((e) => e.id === "azure")?.usage;
  const estimate = prefs.engine !== "azure" ? 0 : (mode === "batch" ? parts : mode === "project" ? segments.map((s) => s.text) : [text]).reduce((n, t) => n + billableChars(t), 0);
  const remaining = usage ? usage.limit - usage.chars : Infinity;
  const quotaWarn = estimate > 0 && estimate > remaining;
  const counter = mode === "batch" ? `${parts.length} 个任务` : mode === "project" ? `${segments.length} 个段落 · ${chars.toLocaleString()} 字符` : `${text.length.toLocaleString()} 字符`;
  const estimateText = estimate > 0 ? ` · 预计消耗 ${estimate.toLocaleString()} 字符` : "";
  const over = (mode !== "batch" && chars > MAX) || (mode === "batch" && parts.length > 50);

  return (
    <div className="composer">
      {imported && (
        <div className="import-card">
          <div className="ic-head">
            <Icon name="doc" size={22} />
            <div><strong>{imported.name}</strong><span>{imported.encoding} · {imported.characters.toLocaleString()} 字符</span></div>
            <button className="round" onClick={() => setImported(undefined)} title="取消导入"><Icon name="close" /></button>
          </div>
          <pre>{imported.text.slice(0, 1500)}{imported.text.length > 1500 ? "\n…仅缩略展示，导入会保留完整正文" : ""}</pre>
          {imported.requires_split && <div className="ic-note">超过单任务上限，将自动拆成多个任务，正文不会截断</div>}
          <button className="primary" onClick={applyImport}>使用完整正文</button>
        </div>
      )}

      <div className="mode-row">
        <Segmented variant="accent" options={MODES} value={mode} onChange={switchMode} />
        <input className="title-input" aria-label="任务标题" placeholder="标题（可选）" maxLength={120} value={title} onChange={(e) => setTitle(e.target.value)} />
        <span className={over || quotaWarn ? "counter bad" : "counter"}>{counter}{estimateText}</span>
      </div>
      {quotaWarn && !over && <div className="over-note">本月 Azure 额度约剩 {Math.max(0, remaining).toLocaleString()} 字符，这次约需 {estimate.toLocaleString()}，超出后可能被限流或产生费用</div>}
      {over && <div className="over-note">{mode === "batch" ? "一次最多 50 个任务，请缩减文本" : "超过 10 万字符，请切换到「分段独立文件」，正文不会被截断"}</div>}

      <div className="input-row">
        <button className="round" title="导入 TXT / Markdown / DOCX" disabled={busy} onClick={() => fileRef.current?.click()}><Icon name="clip" /></button>
        <input ref={fileRef} type="file" accept=".txt,.md,.docx" hidden onChange={(e) => { void loadFile(e.target.files?.[0]); e.target.value = ""; }} />
        {mode === "project" ? (
          <button className="project-box" onClick={() => setEditor(true)}>
            <Icon name="list" size={20} />
            {segments.length ? `编辑 ${segments.length} 个章节 / 角色段落` : "添加章节 / 角色段落"}
          </button>
        ) : (
          <textarea
            ref={area} rows={1} aria-label="合成文本"
            placeholder="输入要朗读的文本…（Ctrl+Enter 发送，Enter 换行）"
            value={text} onChange={(e) => setText(e.target.value)}
            onKeyDown={(e) => { if (e.ctrlKey && e.key === "Enter") void submit(); }}
          />
        )}
        <button className="send" title="发送（Ctrl+Enter）" aria-label="开始合成" disabled={busy || !valid} onClick={submit}>
          {busy ? <span className="spinner light" /> : <Icon name="send" size={22} />}
        </button>
      </div>

      {editorMounted && (
        <div className={editor ? "modal-wrap" : "modal-wrap closing"} onClick={() => setEditor(false)}>
          <div className="modal" role="dialog" aria-label="章节编辑" onClick={(e) => e.stopPropagation()}>
            <div className="modal-head">
              <h2>章节 / 多角色段落</h2>
              <button className="round" onClick={() => setEditor(false)}><Icon name="close" /></button>
            </div>
            <div className="modal-body">
              {segments.map((s, i) => (
                <div className="seg" key={i}>
                  <div className="seg-top">
                    <span className="seg-no">{i + 1}</span>
                    <input aria-label={`第${i + 1}段标题`} value={s.title} maxLength={120} onChange={(e) => editSegment(i, { title: e.target.value })} />
                    <select aria-label={`第${i + 1}段音色`} value={s.voice || prefs.voice} onChange={(e) => editSegment(i, { voice: e.target.value })}>
                      {!voices.some((v) => v.ShortName === (s.voice || prefs.voice)) && <option value={s.voice || prefs.voice}>{s.voice || prefs.voice}</option>}
                      {voices.map((v) => <option key={v.ShortName} value={v.ShortName}>{localeName(v.Locale)} · {voiceName(v.ShortName)}</option>)}
                    </select>
                  </div>
                  <textarea aria-label={`第${i + 1}段正文`} value={s.text} onChange={(e) => editSegment(i, { text: e.target.value })} />
                  <div className="seg-actions">
                    <button disabled={!i} onClick={() => move(i, -1)}><Icon name="up" size={16} />上移</button>
                    <button disabled={i === segments.length - 1} onClick={() => move(i, 1)}><Icon name="down" size={16} />下移</button>
                    <button className="danger" onClick={() => setSegments((ss) => ss.filter((_, k) => k !== i))}><Icon name="trash" size={16} />移除</button>
                  </div>
                </div>
              ))}
              <button className="add-seg" disabled={segments.length >= 200} onClick={() => setSegments((ss) => [...ss, { title: `第 ${ss.length + 1} 段`, text: "", voice: prefs.voice }])}>
                <Icon name="plus" size={18} />添加章节 / 角色段落
              </button>
              <p className="hint">按顺序合并为一个音频；修改后重新生成会复用未变化的分段。默认音色：{voiceName(prefs.voice)}（可在每段单独指定）。</p>
            </div>
            <div className="modal-foot">
              <button className="ghost" onClick={() => { setMode("single"); setText(segments.map((s) => s.text).join("\n\n")); setEditor(false); }}>切回整篇</button>
              <button className="primary" onClick={() => setEditor(false)}>完成</button>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}
