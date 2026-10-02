const names = new Intl.DisplayNames(["zh-CN"], { type: "language", languageDisplay: "standard" });
const DIALECT: Record<string, string> = { liaoning: "辽宁", shaanxi: "陕西" };
const COMMON = ["zh-CN", "zh-TW", "zh-HK", "en-US", "en-GB", "ja-JP", "ko-KR", "fr-FR", "de-DE", "es-ES", "ru-RU"];

/** 如 zh-CN → "中文（中国） · zh-CN" */
export function localeLabel(code: string): string {
  const [lang, region, dialect] = code.split("-");
  let label: string;
  try {
    label = names.of(`${lang}-${region}`) ?? code;
  } catch {
    label = code;
  }
  if (dialect) label += `·${DIALECT[dialect] ?? dialect}`;
  return `${label} · ${code}`;
}

/** 仅中文名，如 "中文（中国）"。 */
export function localeName(code: string): string {
  return localeLabel(code).split(" · ")[0];
}

export type VoiceTab = "all" | "fav" | "zh" | "en" | "jako" | "other";
export const TABS: [VoiceTab, string][] = [["all", "全部"], ["fav", "收藏"], ["zh", "中文"], ["en", "英语"], ["jako", "日韩"], ["other", "其他"]];

export function tabOf(code: string): Exclude<VoiceTab, "all" | "fav"> {
  const lang = code.split("-")[0];
  return lang === "zh" ? "zh" : lang === "en" ? "en" : lang === "ja" || lang === "ko" ? "jako" : "other";
}

/** 常用语言在前，其余按中文名排序。 */
export function groupLocales(codes: string[]): { common: string[]; other: string[] } {
  const set = new Set(codes);
  const common = COMMON.filter((c) => set.has(c));
  const other = codes
    .filter((c) => !COMMON.includes(c))
    .sort((a, b) => localeLabel(a).localeCompare(localeLabel(b), "zh-CN"));
  return { common, other };
}
