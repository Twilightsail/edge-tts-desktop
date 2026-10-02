import { useState } from "react";
import { useApp } from "./ctx";
import { isDesktop, pickSavePath } from "./desktop";
import { localeName } from "./locales";
import type { SynthesisRequest, Task } from "./types";
import { Avatar, clock, fileName, hash, hm, Icon, isLive, mb, saveBlob, styleLabel, voiceName } from "./ui";

const STATUS_TEXT: Record<string, string> = { queued: "排队中…", running: "正在合成…" };

function Wave({ id, progress, playing, onSeek }: { id: string; progress: number; playing: boolean; onSeek?: (f: number) => void }) {
  const bars = Array.from({ length: 38 }, (_, i) => 18 + (hash(`${id}${i}`) % 82));
  return (
    <div
      className={playing ? "wave playing" : "wave"}
      onClick={(e) => {
        if (!onSeek) return;
        const r = e.currentTarget.getBoundingClientRect();
        onSeek((e.clientX - r.left) / r.width);
      }}
    >
      {bars.map((h, i) => (
        <i key={i} className={i / bars.length < progress ? "on" : ""} style={{ height: `${h}%`, ["--k" as string]: i }} />
      ))}
    </div>
  );
}

interface Props {
  task: Task;
  selecting: boolean;
  chosen: boolean;
  toggle: () => void;
  edit: (request: SynthesisRequest) => void;
}

export default function TaskMessage({ task, selecting, chosen, toggle, edit }: Props) {
  const { api, notify, player, changed, voiceMap } = useApp();
  const [busy, setBusy] = useState(false);
  const [expanded, setExpanded] = useState(false);
  const [chapters, setChapters] = useState(false);
  const [renaming, setRenaming] = useState(false);
  const [title, setTitle] = useState(task.request?.title ?? "");
  const [deleting, setDeleting] = useState(false);

  const req = task.request;
  const live = isLive(task);
  const text = req?.text ?? "";
  const long = text.length > 220 || text.split("\n").length > 5;
  const active = player.id === task.id;
  const showTitle = req?.title;

  const run = async (fn: () => Promise<void>) => {
    if (busy) return;
    setBusy(true);
    try { await fn(); } catch (e) { notify((e as Error).message, "err"); } finally { setBusy(false); }
  };

  const download = (kind: "audio" | "subtitles" | "vtt") => run(async () => {
    const ext = kind === "audio" ? "mp3" : kind === "subtitles" ? "srt" : "vtt";
    if (isDesktop) {
      const dest = await pickSavePath(`${fileName(task)}.${ext}`, ext);
      if (dest) { await api.export(task.id, dest, kind); notify(`已保存到 ${dest}`, "ok"); }
    } else {
      const path = kind === "audio" ? task.audio_url : kind === "subtitles" ? task.subtitles_url : task.vtt_url;
      saveBlob(await api.blob(path!), `${fileName(task)}.${ext}`);
    }
  });

  const tick = task.status === "succeeded" ? <Icon name="check2" size={16} />
    : task.status === "failed" ? <Icon name="alert" size={15} />
    : task.status === "cancelled" ? <Icon name="close" size={15} />
    : <Icon name="clock" size={14} />;

  const voiceInfo = req ? voiceMap.get(req.voice) : undefined;

  return (
    <div className={`pair ${chosen ? "chosen" : ""} ${selecting ? "selecting" : ""}`} onClick={selecting && !live ? toggle : undefined}>
      {selecting && <span className={chosen ? "sel-dot on" : live ? "sel-dot off" : "sel-dot"}>{chosen && <Icon name="check" size={14} />}</span>}

      <div className="msg out">
        <div className="bubble">
          {req && <div className="sender" style={{ color: `hsl(${hash(req.voice) % 360} 60% var(--sender-l))` }}>{voiceName(req.voice)}{req.engine === "azure" && <em className="engine-tag">Azure</em>}{req.style && <em className="engine-tag">{styleLabel(req.style)}</em>}<span> · {voiceInfo ? localeName(voiceInfo.Locale) : req.voice.split("-").slice(0, 2).join("-")}</span></div>}
          {showTitle && <div className="b-title">{showTitle}</div>}
          <div className={expanded ? "b-text" : "b-text clamp"}>{text}</div>
          {long && <button className="link" onClick={(e) => { e.stopPropagation(); setExpanded(!expanded); }}>{expanded ? "收起" : "展开全文"}</button>}
          <div className="b-meta">
            {req?.segments && req.segments.length > 0 && <span>{req.segments.length} 个章节 · </span>}
            {req && (req.rate !== 0 || req.pitch !== 0 || req.volume !== 0) && (
              <span>语速 {req.rate}% · 音调 {req.pitch}Hz · 音量 {req.volume}% · </span>
            )}
            <span>{text.length.toLocaleString()} 字符</span>
            <span className="time">{hm(task.created_at)}</span>
            <span className={`tick ${task.status}`}>{tick}</span>
          </div>
        </div>
      </div>

      <div className="msg in">
        <Avatar name="Edge TTS" size={34}><Icon name="wave" size={18} /></Avatar>
        <div className="bubble">
          {live && (
            <div className="working">
              <div className="w-line"><span className="spinner" />{STATUS_TEXT[task.status]}{task.stage === "retry_wait" && " 网络异常，等待重试"}</div>
              <progress value={task.segment_completed || 0} max={task.segment_total || 1} />
              <div className="w-sub">已完成 {task.segment_completed || 0}/{task.segment_total || 1} 段 · 第 {task.attempt || 1} 次尝试</div>
            </div>
          )}

          {task.status === "succeeded" && task.audio_url && (
            <div className="voice">
              <button className="play" aria-label={active && player.playing ? "暂停" : "播放"} onClick={(e) => { e.stopPropagation(); void run(() => player.toggle(task.id, () => api.blob(task.audio_url!))); }}>
                <span className={active && player.playing ? "morph on" : "morph"}>
                  <Icon name="play" size={24} />
                  <Icon name="pause" size={24} />
                </span>
              </button>
              <div className="vbody">
                <Wave id={task.id} progress={active && player.duration ? player.time / player.duration : 0} playing={active && player.playing} onSeek={active ? player.seek : undefined} />
                <div className="vmeta">
                  <span>{active && player.time > 0 ? clock(player.time) : clock(task.duration_seconds)}</span>
                  <span className="dim">{mb(task.audio_bytes)}</span>
                  {active && <button className="rate" onClick={(e) => { e.stopPropagation(); player.cycleRate(); }}>{player.rate}×</button>}
                </div>
              </div>
            </div>
          )}

          {(task.status === "failed" || task.status === "cancelled") && (
            <div className="fail">
              <Icon name="alert" size={18} />
              <div>{task.error?.message ?? (task.status === "cancelled" ? "任务已取消" : "合成失败")}</div>
            </div>
          )}

          {task.chapters?.length > 0 && (
            <>
              <button className="link chap" onClick={(e) => { e.stopPropagation(); setChapters(!chapters); }}>
                <Icon name="list" size={15} />章节明细 {task.segment_completed}/{task.segment_total} <Icon name={chapters ? "up" : "down"} size={14} />
              </button>
              {chapters && (
                <ol className="chap-list">
                  {task.chapters.map((c) => (
                    <li key={c.index}>
                      <b>{c.title}</b> · {voiceName(c.voice)} · {c.status === "succeeded" ? "已完成" : c.status === "running" ? "处理中" : "等待"}
                      {c.cached && " · 复用缓存"}
                    </li>
                  ))}
                </ol>
              )}
            </>
          )}

          {renaming && (
            <div className="rename" onClick={(e) => e.stopPropagation()}>
              <input aria-label="修改任务标题" autoFocus value={title} maxLength={120} onChange={(e) => setTitle(e.target.value)}
                onKeyDown={(e) => { if (e.key === "Enter") document.getElementById(`rn-${task.id}`)?.click(); if (e.key === "Escape") setRenaming(false); }} />
              <button id={`rn-${task.id}`} disabled={busy} onClick={() => run(async () => { await api.rename(task.id, title); setRenaming(false); changed(); })}><Icon name="check" size={18} /></button>
              <button onClick={() => setRenaming(false)}><Icon name="close" size={18} /></button>
            </div>
          )}

          {!selecting && (
            <div className="kb" onClick={(e) => e.stopPropagation()}>
              {deleting ? (
                <>
                  <div className="kb-note">删除任务及内部音频？已导出的文件会保留。</div>
                  <div className="kb-row">
                    <button className="danger" disabled={busy} onClick={() => run(async () => { player.forget(task.id); await api.remove(task.id); changed(); })}>确认删除</button>
                    <button onClick={() => setDeleting(false)}>保留</button>
                  </div>
                </>
              ) : (
                <>
                  {(task.audio_url || task.subtitles_url || task.vtt_url) && (
                    <div className="kb-row">
                      {task.audio_url && <button disabled={busy} onClick={() => download("audio")}><Icon name="download" size={16} />保存音频</button>}
                      {task.subtitles_url && <button disabled={busy} onClick={() => download("subtitles")}>SRT</button>}
                      {task.vtt_url && <button disabled={busy} onClick={() => download("vtt")}>VTT</button>}
                    </div>
                  )}
                  <div className="kb-row">
                    {live ? (
                      <button disabled={busy} onClick={() => run(async () => { await api.cancel(task.id); changed(); })}><Icon name="stop" size={14} />取消任务</button>
                    ) : (
                      <>
                        {(task.status === "failed" || task.status === "cancelled") && (
                          <button disabled={busy} onClick={() => run(async () => { await api.retry(task.id); changed(); })}><Icon name="refresh" size={16} />重试</button>
                        )}
                        <button onClick={() => { if (req) edit({ ...req }); }}><Icon name="edit" size={16} />重新编辑</button>
                        <button onClick={() => { setTitle(req?.title ?? ""); setRenaming(!renaming); }}>{showTitle ? "改标题" : "加标题"}</button>
                        <button className="danger" onClick={() => setDeleting(true)}><Icon name="trash" size={16} /></button>
                      </>
                    )}
                  </div>
                </>
              )}
            </div>
          )}
          <div className="b-meta in-meta"><span className="time">{hm(task.updated_at)}</span></div>
        </div>
      </div>
    </div>
  );
}
