import type { ReactNode } from "react";
import type { Task, Voice } from "./types";

const P: Record<string, string> = {
  menu: "M4 6h16M4 12h16M4 18h16",
  search: "M11 4a7 7 0 1 0 0 14 7 7 0 0 0 0-14zM21 21l-4.5-4.5",
  clip: "M21 11.5l-8.6 8.6a5 5 0 0 1-7.1-7.1l8.6-8.6a3.3 3.3 0 0 1 4.7 4.7l-8.6 8.6a1.7 1.7 0 0 1-2.4-2.4l7.9-7.9",
  send: "M3.4 20.4l17.5-7.5c.8-.3.8-1.5 0-1.8L3.4 3.6c-.7-.3-1.4.4-1.2 1.1L3.6 10l9 2-9 2-1.4 5.3c-.2.7.5 1.4 1.2 1.1z",
  star: "M12 3.5l2.6 5.4 5.9.8-4.3 4.1 1 5.9L12 17l-5.2 2.7 1-5.9L3.5 9.7l5.9-.8z",
  play: "M8 5.5v13l11-6.5z",
  pause: "M7 5h3.5v14H7zM13.5 5H17v14h-3.5z",
  close: "M6 6l12 12M18 6L6 18",
  info: "M12 3a9 9 0 1 0 0 18 9 9 0 0 0 0-18zM12 11v5M12 8v.01",
  check: "M5 12.5l4.5 4.5L19 7.5",
  check2: "M2.5 12.5L7 17l9.5-9.5M10.5 15.5l1.5 1.5 9.5-9.5",
  download: "M12 4v11M7 10.5l5 5 5-5M5 20h14",
  trash: "M5 7h14M10 7V4h4v3M7 7l1 13h8l1-13M10 11v6M14 11v6",
  edit: "M4 20l1-4L16.5 4.5a2 2 0 0 1 3 3L8 19z",
  refresh: "M20 11a8 8 0 1 0-2.3 5.7M20 4v7h-7",
  sun: "M12 8a4 4 0 1 0 0 8 4 4 0 0 0 0-8zM12 2v2M12 20v2M2 12h2M20 12h2M5 5l1.5 1.5M17.5 17.5L19 19M5 19l1.5-1.5M17.5 6.5L19 5",
  moon: "M20 14.5A8 8 0 0 1 9.5 4a8 8 0 1 0 10.5 10.5z",
  speaker: "M4 9.5v5h3.5L12 18.5v-13L7.5 9.5zM15.5 9a4 4 0 0 1 0 6M18 6.5a8 8 0 0 1 0 11",
  select: "M12 3a9 9 0 1 0 0 18 9 9 0 0 0 0-18zM8 12.5l3 3 5-6",
  zip: "M4 6h16v4H4zM5 10v9h14v-9M10 14h4",
  clock: "M12 3a9 9 0 1 0 0 18 9 9 0 0 0 0-18zM12 7v5l3 2",
  alert: "M12 3a9 9 0 1 0 0 18 9 9 0 0 0 0-18zM12 7.5v5M12 16v.01",
  plus: "M12 5v14M5 12h14",
  up: "M6 15l6-6 6 6",
  down: "M6 9l6 6 6-6",
  stop: "M7 7h10v10H7z",
  list: "M8 6h12M8 12h12M8 18h12M4 6v.01M4 12v.01M4 18v.01",
  doc: "M7 3h7l5 5v13H7zM14 3v5h5",
  wave: "M4 10v4M8 6v12M12 3v18M16 8v8M20 11v2",
  sidebar: "M4 5h16v14H4zM9.5 5v14",
};
const SOLID = new Set(["send", "play", "pause", "stop"]);

export function Icon({ name, size = 22, filled }: { name: string; size?: number; filled?: boolean }) {
  const solid = SOLID.has(name);
  return (
    <svg
      viewBox="0 0 24 24" width={size} height={size} aria-hidden
      fill={solid || filled ? "currentColor" : "none"}
      stroke={solid ? "none" : "currentColor"}
      strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round"
    >
      <path d={P[name]} />
    </svg>
  );
}

const GRADIENTS = [
  ["#ff885e", "#ff516a"], ["#ffcd6a", "#ffa85c"], ["#82b1ff", "#665fff"], ["#a0de7e", "#54cb68"],
  ["#53edd6", "#28c9b7"], ["#72d5fd", "#2a9ef1"], ["#e0a2f3", "#d669ed"],
];

export const hash = (s: string) => [...s].reduce((h, c) => (h * 31 + c.charCodeAt(0)) >>> 0, 7);

export function Avatar({ name, size = 46, children }: { name: string; size?: number; children?: ReactNode }) {
  const [a, b] = GRADIENTS[hash(name) % GRADIENTS.length];
  return (
    <span className="avatar" style={{ width: size, height: size, fontSize: size * 0.42, background: `linear-gradient(135deg, ${a}, ${b})` }}>
      {children ?? name.charAt(0).toUpperCase()}
    </span>
  );
}

/** zh-CN-XiaoxiaoNeural → Xiaoxiao */
export const voiceName = (shortName: string) => (shortName.split("-").pop() ?? shortName).replace(/Neural$/, "");

const TAGS: Record<string, string> = {
  Warm: "温暖", Friendly: "友好", Cheerful: "开朗", Lively: "活泼", Professional: "专业", Reliable: "可靠", Authentic: "真诚",
  Confident: "自信", Pleasant: "愉快", Positive: "积极", Humorous: "幽默", Sunshine: "阳光", Sincere: "诚恳", Rational: "理性",
  Casual: "随和", Comfort: "舒适", Expressive: "有表现力", Caring: "体贴", Bright: "明朗", Passion: "热情", Cute: "可爱", Gentle: "温柔",
};
/** Azure 说话风格的中文名；未收录的原样显示。 */
export const STYLE_ZH: Record<string, string> = {
  cheerful: "开朗", sad: "悲伤", angry: "生气", fearful: "害怕", disgruntled: "不满", serious: "严肃", affectionate: "亲切",
  gentle: "温柔", calm: "平静", lyrical: "抒情", newscast: "新闻播报", "newscast-casual": "新闻（轻松）", "newscast-formal": "新闻（正式）",
  chat: "聊天", "chat-casual": "聊天（随意）", customerservice: "客服", assistant: "助理", "poetry-reading": "诗歌朗诵",
  "narration-relaxed": "轻松旁白", "narration-professional": "专业旁白", embarrassed: "尴尬", depressed: "沮丧", excited: "兴奋",
  friendly: "友好", hopeful: "充满希望", shouting: "呐喊", whispering: "低语", terrified: "惊恐", unfriendly: "冷淡",
  "sports-commentary": "体育解说", "sports-commentary-excited": "体育解说（激动）", advertisement_upbeat: "广告", "advertisement-upbeat": "广告",
  livecommercial: "直播带货", empathetic: "共情", envious: "羡慕", sorry: "抱歉", "documentary-narration": "纪录片旁白", "story": "讲故事",
  "narration": "旁白", "Default": "默认",
};
export const styleLabel = (s: string) => STYLE_ZH[s] ?? s;

/** Edge 中文音色的中文名（Azure 的列表自带 LocalName）。 */
const LOCAL_NAMES: Record<string, string> = {
  "zh-CN-XiaoxiaoNeural": "晓晓", "zh-CN-XiaoyiNeural": "晓伊", "zh-CN-YunjianNeural": "云健", "zh-CN-YunxiNeural": "云希",
  "zh-CN-YunxiaNeural": "云夏", "zh-CN-YunyangNeural": "云扬", "zh-CN-liaoning-XiaobeiNeural": "晓北", "zh-CN-shaanxi-XiaoniNeural": "晓妮",
  "zh-HK-HiuGaaiNeural": "曉佳", "zh-HK-HiuMaanNeural": "曉曼", "zh-HK-WanLungNeural": "雲龍",
  "zh-TW-HsiaoChenNeural": "曉臻", "zh-TW-HsiaoYuNeural": "曉雨", "zh-TW-YunJheNeural": "雲哲",
};
export const localName = (v: Voice) => v.LocalName || LOCAL_NAMES[v.ShortName] || "";

export const voiceTags = (v?: Voice) => (v?.VoiceTag?.VoicePersonalities ?? []).slice(0, 2).map((t) => TAGS[t] ?? STYLE_ZH[t] ?? t);
export const genderLabel = (g?: string) => (g === "Female" ? "女声" : g === "Male" ? "男声" : "");

/** Azure 计费字符：每个汉字（含日文汉字、韩文汉字）算 2，其余每个 Unicode 码位算 1。 */
export const billableChars = (text: string) => {
  let n = 0;
  for (const ch of text) {
    const c = ch.codePointAt(0)!;
    n += (c >= 0x3400 && c <= 0x4dbf) || (c >= 0x4e00 && c <= 0x9fff) || (c >= 0xf900 && c <= 0xfaff) || (c >= 0x20000 && c <= 0x323af) ? 2 : 1;
  }
  return n;
};

export const taskTitle = (t: Task) => t.request?.title || t.request?.text.slice(0, 30) || t.id;
export const fileName = (t: Task) =>
  taskTitle(t).replace(/[<>:"/\\|?*\x00-\x1f]/g, "_").replace(/[. ]+$/, "").slice(0, 80) || t.id;
export const mb = (n: number) => `${(n / 1024 / 1024).toFixed(2)} MB`;
export const clock = (s: number) => `${Math.floor(s / 60)}:${String(Math.floor(s % 60)).padStart(2, "0")}`;
export const hm = (iso: string) => new Date(iso).toLocaleTimeString("zh-CN", { hour: "2-digit", minute: "2-digit", hour12: false });
export const isLive = (t: Task) => t.status === "queued" || t.status === "running";

export function dayLabel(iso: string): string {
  const d = new Date(iso), now = new Date();
  const midnight = (x: Date) => new Date(x.getFullYear(), x.getMonth(), x.getDate()).getTime();
  const diff = Math.round((midnight(now) - midnight(d)) / 864e5);
  if (diff === 0) return "今天";
  if (diff === 1) return "昨天";
  return d.toLocaleDateString("zh-CN", { year: d.getFullYear() === now.getFullYear() ? undefined : "numeric", month: "long", day: "numeric" });
}

export function saveBlob(blob: Blob, name: string) {
  const url = URL.createObjectURL(blob), a = document.createElement("a");
  a.href = url; a.download = name; document.body.appendChild(a); a.click(); a.remove();
  setTimeout(() => URL.revokeObjectURL(url), 10000);
}
