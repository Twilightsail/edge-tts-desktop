import { useEffect, useMemo, useRef, useState, type KeyboardEvent, type PointerEvent } from "react";
import { useApp } from "./ctx";
import { groupLocales, localeName, TABS, tabOf, type VoiceTab } from "./locales";
import Rail, { useLoadStalled } from "./Rail";
import Segmented from "./Segmented";
import type { Voice } from "./types";
import { useEscape } from "./useEscape";
import { Avatar, genderLabel, Icon, localName, voiceName, voiceTags } from "./ui";

export const SIDE_MIN = 260;
export const SIDE_MAX = 480;
const SNAP = 190; // 拖到比这更窄就吸附成头像窄栏

interface Props {
  dark: boolean;
  collapsed: boolean;
  onToggle: () => void;
  onWidth: (px: number) => void;
  onCollapse: (collapsed: boolean) => void;
  onDragging: (dragging: boolean) => void;
  onTheme: () => void;
  onRefreshVoices: () => void;
  onOpenSettings: () => void;
  onOpenAzure: () => void;
}

const ENGINES = [["edge", "Edge · 免费"], ["azure", "Azure"]] as const;
const GENDERS = [["", "全部"], ["Female", "女声"], ["Male", "男声"]] as const;

export default function Sidebar({ dark, collapsed, onToggle, onWidth, onCollapse, onDragging, onTheme, onRefreshVoices, onOpenSettings, onOpenAzure }: Props) {
  const { voices, favorites, prefs, setPref, previewVoice, previewing, toggleFavorite, engines, setEngine, refreshVoices } = useApp();
  const stalled = useLoadStalled(voices.length);
  const azureMissing = prefs.engine === "azure" && engines.some((e) => e.id === "azure" && !e.configured);
  const [tab, setTab] = useState<VoiceTab>("zh");
  const [query, setQuery] = useState("");
  const [gender, setGender] = useState<"" | "Female" | "Male">("");
  const [menu, setMenu] = useState(false);
  const searchRef = useRef<HTMLInputElement>(null);
  /** 从窄栏点“搜索”：先展开，等展开动画走完再聚焦搜索框。 */
  const expandAndSearch = () => {
    onToggle();
    setTimeout(() => searchRef.current?.focus(), 520);
  };
  useEscape(menu, () => setMenu(false));
  const keyMoved = useRef(false);
  useEffect(() => {
    // 用键盘移动选中项时，让它滚动到可见范围；鼠标点击不触发，避免列表跳动
    if (!keyMoved.current) return;
    keyMoved.current = false;
    document.querySelector(".voice-row.sel")?.scrollIntoView({ block: "nearest" });
  }, [prefs.voice]);

  const groups = useMemo(() => {
    const q = query.trim().toLowerCase();
    const list = voices.filter((v) => {
      if (gender && v.Gender !== gender) return false;
      if (q) {
        return `${v.ShortName} ${v.FriendlyName ?? ""} ${localeName(v.Locale)} ${genderLabel(v.Gender)} ${voiceTags(v).join(" ")}`.toLowerCase().includes(q);
      }
      if (tab === "fav") return favorites.includes(v.ShortName);
      // Azure 的多语言音色（如 en-US 的 Ava Multilingual）也能读中文，放进“中文”标签
      return tab === "all" || tabOf(v.Locale) === tab || (tab === "zh" && !!v.SecondaryLocaleList?.some((l) => l.startsWith("zh")));
    });
    const order = groupLocales([...new Set(list.map((v) => v.Locale))]);
    return [...order.common, ...order.other].map((locale) => ({
      locale,
      items: list.filter((v) => v.Locale === locale).sort((a, b) => voiceName(a.ShortName).localeCompare(voiceName(b.ShortName))),
    }));
  }, [voices, favorites, tab, query, gender]);

  let index = 0;
  const row = (v: Voice) => {
    const selected = v.ShortName === prefs.voice;
    const fav = favorites.includes(v.ShortName);
    const cn = localName(v);
    const local = cn && cn !== voiceName(v.ShortName) ? [cn] : []; // 中文名，如“晓辰”
    const sub = [...local, localeName(v.Locale), genderLabel(v.Gender), ...voiceTags(v)].join(" · ");
    return (
      <li key={v.ShortName} className={selected ? "voice-row sel" : "voice-row"} style={{ ["--i" as string]: Math.min(index++, 14) }} onClick={() => setPref("voice", v.ShortName)}>
        <Avatar name={voiceName(v.ShortName)} />
        <div className="vr-main">
          <div className="vr-name">{voiceName(v.ShortName)}</div>
          <div className="vr-sub">{sub}</div>
        </div>
        <div className="vr-actions">
          <button className={fav ? "mini on" : "mini"} title={fav ? "取消收藏" : "收藏"} onClick={(e) => { e.stopPropagation(); void toggleFavorite(v.ShortName); }}>
            <Icon name="star" size={18} filled={fav} />
          </button>
          <button className="mini" title="试听" onClick={(e) => { e.stopPropagation(); void previewVoice(v.ShortName); }}>
            {previewing === v.ShortName ? <span className="spinner" /> : <Icon name="speaker" size={18} />}
          </button>
        </div>
      </li>
    );
  };

  /** 拖动右侧分隔线调整宽度；拖得太窄会吸附成窄栏，从窄栏往右拖则展开。 */
  const startDrag = (e: PointerEvent<HTMLDivElement>) => {
    const handle = e.currentTarget;
    handle.setPointerCapture(e.pointerId);
    const left = handle.parentElement!.getBoundingClientRect().left;
    onDragging(true);
    const move = (ev: globalThis.PointerEvent) => {
      const x = ev.clientX - left;
      if (x < SNAP) {
        onCollapse(true);
      } else {
        onCollapse(false);
        onWidth(Math.max(SIDE_MIN, Math.min(SIDE_MAX, x)));
      }
    };
    const up = () => {
      handle.removeEventListener("pointermove", move);
      handle.removeEventListener("pointerup", up);
      handle.removeEventListener("pointercancel", up);
      onDragging(false);
    };
    handle.addEventListener("pointermove", move);
    handle.addEventListener("pointerup", up);
    handle.addEventListener("pointercancel", up);
  };

  /** ↑/↓ 在可见的音色之间移动选中项（焦点在搜索框或列表上时）。 */
  const onKeys = (e: KeyboardEvent<HTMLDivElement>) => {
    if (e.key !== "ArrowDown" && e.key !== "ArrowUp") return;
    const target = e.target as HTMLElement;
    if (!target.matches(".voice-scroll, .search-box input")) return;
    const flat = groups.flatMap((g) => g.items);
    if (!flat.length) return;
    e.preventDefault();
    const at = flat.findIndex((v) => v.ShortName === prefs.voice);
    const next = at < 0 ? 0 : Math.max(0, Math.min(flat.length - 1, at + (e.key === "ArrowDown" ? 1 : -1)));
    keyMoved.current = true;
    setPref("voice", flat[next].ShortName);
  };

  const empty = groups.length === 0;
  return (
    <aside className="sidebar" aria-label="音色列表">
      <div className="side-full" aria-hidden={collapsed} onKeyDown={onKeys}>
        <div className="side-top">
          <div className="menu-wrap">
            <button className="round" title="菜单" onClick={() => setMenu(!menu)}><Icon name="menu" /></button>
            <div className={menu ? "scrim show" : "scrim"} onClick={() => setMenu(false)} />
            <div className={menu ? "dropdown open" : "dropdown"}>
              <button onClick={() => { onTheme(); setMenu(false); }}><Icon name={dark ? "sun" : "moon"} size={20} />{dark ? "浅色模式" : "夜间模式"}</button>
              <button onClick={() => { onRefreshVoices(); setMenu(false); }}><Icon name="refresh" size={20} />刷新音色列表</button>
              <button onClick={() => { onOpenSettings(); setMenu(false); }}><Icon name="info" size={20} />设置与存储</button>
            </div>
          </div>
          <label className="search-box">
            <Icon name="search" size={18} />
            <input ref={searchRef} aria-label="搜索音色" placeholder="搜索音色、语言、风格" value={query} onChange={(e) => setQuery(e.target.value)} />
            {query && <button className="clear" onClick={() => setQuery("")}><Icon name="close" size={16} /></button>}
          </label>
          <button className="round" title="折叠侧栏（Ctrl+B）" onClick={onToggle}><Icon name="sidebar" /></button>
        </div>

        <div className="engine-row">
          <Segmented variant="pill" className="stretch" options={ENGINES} value={prefs.engine} onChange={setEngine} />
        </div>
        <Segmented
          variant="line" className="tabs"
          options={TABS.map(([key, label]) => [key, key === "fav" && favorites.length > 0 ? <>{label}<i>{favorites.length}</i></> : label] as const)}
          value={query ? "" : tab}
          onChange={(key) => { setTab(key); setQuery(""); }}
        />
        <div className="gender-row">
          <Segmented variant="pill" className="small" options={GENDERS} value={gender} onChange={setGender} />
          <span className="count-note">{groups.reduce((n, g) => n + g.items.length, 0)} 个音色</span>
        </div>

        <div className="voice-scroll" tabIndex={0} aria-label="音色列表，可用上下键切换">
          {azureMissing && (
            <div className="side-empty setup">
              <Icon name="info" size={30} />
              还没有配置 Azure 密钥
              <button className="primary" onClick={onOpenAzure}>去配置</button>
            </div>
          )}
          {!azureMissing && voices.length === 0 && (
            <div className="side-empty">
              {stalled
                ? <>音色列表没有加载出来，请检查网络<button className="primary" onClick={() => void refreshVoices(true).catch(() => {})}>重试</button></>
                : <><span className="spinner big" />正在加载音色…</>}
            </div>
          )}
          {voices.length > 0 && empty && <div className="side-empty">{tab === "fav" && !query ? "点击音色右侧的星标即可收藏" : "没有匹配的音色"}</div>}
          {groups.map((g) => (
            <section key={`${tab}-${g.locale}`}>
              {groups.length > 1 && tab !== "fav" && <h3 className="group-title">{tab === "zh" && !g.locale.startsWith("zh") ? `${localeName(g.locale)} · 多语言音色（可读中文）` : localeName(g.locale)}</h3>}
              <ul>{g.items.map(row)}</ul>
            </section>
          ))}
        </div>
      </div>

      <Rail collapsed={collapsed} onToggle={onToggle} onSearch={expandAndSearch} onOpenSettings={onOpenSettings} />

      <div className="resizer" role="separator" aria-orientation="vertical" title="拖动调整宽度，双击折叠/展开" onPointerDown={startDrag} onDoubleClick={onToggle} />
    </aside>
  );
}
