import { useEffect, useMemo, useState, type FocusEvent, type MouseEvent } from "react";
import { useApp } from "./ctx";
import { localeName, tabOf } from "./locales";
import type { Voice } from "./types";
import { Avatar, genderLabel, Icon, localName, voiceName, voiceTags } from "./ui";

/** 音色列表空了超过 8 秒，说明多半加载失败了：不要一直转圈，给出重试入口。 */
export function useLoadStalled(count: number) {
  const [stalled, setStalled] = useState(false);
  useEffect(() => {
    setStalled(false);
    if (count > 0) return;
    const t = setTimeout(() => setStalled(true), 8000);
    return () => clearTimeout(t);
  }, [count]);
  return stalled;
}

interface Tip { x: number; y: number; title: string; lines: string[] }

interface Props {
  collapsed: boolean;
  onToggle: () => void;
  onSearch: () => void;
  onOpenSettings: () => void;
}

/**
 * 折叠后的窄栏：头像 + 名字，分成“当前 / 收藏 / 更多”，顶部显示并可切换引擎，底部有搜索与设置入口。
 * 悬停显示详情卡片；悬停头像出现试听按钮。音色列表还没加载出来时，仍会显示当前音色。
 */
export default function Rail({ collapsed, onToggle, onSearch, onOpenSettings }: Props) {
  const { voices, favorites, prefs, setPref, previewVoice, previewing, setEngine, refreshVoices } = useApp();
  const stalled = useLoadStalled(voices.length);
  const [tip, setTip] = useState<Tip | null>(null);
  useEffect(() => { if (!collapsed) setTip(null); }, [collapsed]);

  const { current, favs, more } = useMemo(() => {
    const byName = new Map(voices.map((v) => [v.ShortName, v]));
    const current =
      byName.get(prefs.voice) ??
      ({ ShortName: prefs.voice, FriendlyName: "", Locale: prefs.voice.split("-").slice(0, 2).join("-"), Gender: "" } as Voice);
    const favs = favorites.map((id) => byName.get(id)).filter((v): v is Voice => !!v && v.ShortName !== prefs.voice);
    const taken = new Set([prefs.voice, ...favs.map((v) => v.ShortName)]);
    const more = voices
      .filter((v) => tabOf(v.Locale) === "zh" && !taken.has(v.ShortName))
      .sort((a, b) => Number(a.Locale !== "zh-CN") - Number(b.Locale !== "zh-CN"))
      .slice(0, Math.max(0, 8 - favs.length));
    return { current, favs, more };
  }, [voices, favorites, prefs.voice]);

  const label = (v: Voice) => localName(v) || voiceName(v.ShortName);
  const show = (e: MouseEvent<HTMLElement> | FocusEvent<HTMLElement>, title: string, ...lines: string[]) => {
    const r = e.currentTarget.getBoundingClientRect();
    setTip({ x: r.right + 10, y: r.top + r.height / 2, title, lines: lines.filter(Boolean) });
  };
  const hover = (title: string, ...lines: string[]) => ({
    onMouseEnter: (e: MouseEvent<HTMLElement>) => show(e, title, ...lines),
    onFocus: (e: FocusEvent<HTMLElement>) => show(e, title, ...lines),
    onMouseLeave: () => setTip(null),
    onBlur: () => setTip(null),
  });

  let order = 0;
  const item = (v: Voice, big = false) => {
    const selected = v.ShortName === prefs.voice;
    const fav = favorites.includes(v.ShortName);
    const detail = [localName(v) && voiceName(v.ShortName), localeName(v.Locale), genderLabel(v.Gender), ...voiceTags(v)].filter(Boolean).join(" · ");
    const choose = () => setPref("voice", v.ShortName);
    return (
      <div
        key={v.ShortName} role="button" aria-pressed={selected} aria-label={`${label(v)}，${detail}`}
        tabIndex={collapsed ? 0 : -1}
        className={`rail-item${selected ? " sel" : ""}${big ? " big" : ""}`}
        style={{ ["--i" as string]: order++ }}
        onClick={choose}
        onKeyDown={(e) => { if (e.key === "Enter" || e.key === " ") { e.preventDefault(); choose(); } }}
        {...hover(label(v), detail)}
      >
        <span className="rail-avatar">
          <Avatar name={voiceName(v.ShortName)} size={big ? 50 : 44} />
          {fav && <span className="fav-dot"><Icon name="star" size={10} filled /></span>}
          <button className="rail-play" tabIndex={-1} aria-label={`试听 ${label(v)}`} onClick={(e) => { e.stopPropagation(); void previewVoice(v.ShortName); }}>
            {previewing === v.ShortName ? <span className="spinner" /> : <Icon name="play" size={12} />}
          </button>
        </span>
        <span className="rail-name">{label(v)}</span>
        {big && <span className="rail-sub">{genderLabel(v.Gender) || localeName(v.Locale)}</span>}
      </div>
    );
  };

  const azure = prefs.engine === "azure";
  return (
    <>
      <div
        className="side-rail" aria-hidden={!collapsed}
        onDoubleClick={(e) => { if (!(e.target as HTMLElement).closest(".rail-item, button")) onToggle(); }}
      >
        <div className="rail-top">
          <button className="round" aria-label="展开侧栏" tabIndex={collapsed ? 0 : -1} onClick={onToggle} {...hover("展开侧栏", "Ctrl+B")}><Icon name="sidebar" /></button>
          <button
            className={azure ? "rail-engine azure" : "rail-engine"} tabIndex={collapsed ? 0 : -1}
            onClick={() => setEngine(azure ? "edge" : "azure")}
            {...hover("语音引擎", azure ? "Azure AI Speech，点击切换到 Edge" : "Edge 在线语音（免费），点击切换到 Azure")}
          >
            {azure ? "Azure" : "Edge"}
          </button>
        </div>

        <div className="rail-scroll">
          <div className="rail-label">当前</div>
          {item(current, true)}
          {favs.length > 0 && (<><div className="rail-label"><Icon name="star" size={11} filled />收藏</div>{favs.map((v) => item(v))}</>)}
          {more.length > 0 && (<><div className="rail-label">更多</div>{more.map((v) => item(v))}</>)}
          {voices.length === 0 && (
            <div className="rail-loading">
              {stalled
                ? <button tabIndex={collapsed ? 0 : -1} onClick={() => void refreshVoices(true).catch(() => {})}><Icon name="refresh" size={16} />重试加载</button>
                : <><span className="spinner" />加载音色…</>}
            </div>
          )}
        </div>

        <div className="rail-bottom">
          <button className="round" aria-label="搜索全部音色" tabIndex={collapsed ? 0 : -1} onClick={onSearch} {...hover("搜索全部音色", "展开侧栏并开始搜索")}><Icon name="search" /></button>
          <button className="round" aria-label="设置与存储" tabIndex={collapsed ? 0 : -1} onClick={onOpenSettings} {...hover("设置与存储")}><Icon name="info" /></button>
        </div>
      </div>

      {collapsed && tip && (
        <div className="rail-tip" role="tooltip" style={{ left: tip.x, top: tip.y }}>
          <b>{tip.title}</b>
          {tip.lines.map((line) => <span key={line}>{line}</span>)}
        </div>
      )}
    </>
  );
}
