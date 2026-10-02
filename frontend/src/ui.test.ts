import { describe, expect, it } from "vitest";
import { groupLocales, localeName, tabOf } from "./locales";
import { billableChars, clock, dayLabel, fileName, localName, styleLabel, voiceName, voiceTags } from "./ui";
import type { Task, Voice } from "./types";

describe("billableChars（Azure 计费规则）", () => {
  it("每个汉字算 2，其余每个码位算 1", () => {
    expect(billableChars("你好")).toBe(4);
    expect(billableChars("abc, d")).toBe(6);
    expect(billableChars("你好，世界。")).toBe(4 + 1 + 4 + 1); // 全角标点不是汉字
    expect(billableChars("日本語ひらがな")).toBe(6 + 4);
    expect(billableChars("😀")).toBe(1); // 按码位而不是 UTF-16 单元
    expect(billableChars("")).toBe(0);
  });
});

describe("音色名", () => {
  it("去掉地区前缀和 Neural 后缀", () => {
    expect(voiceName("zh-CN-XiaoxiaoNeural")).toBe("Xiaoxiao");
    expect(voiceName("zh-CN-liaoning-XiaobeiNeural")).toBe("Xiaobei");
    expect(voiceName("en-US-AvaMultilingualNeural")).toBe("AvaMultilingual");
  });
  it("Edge 的中文音色有中文名，Azure 用自带的 LocalName", () => {
    const edge = { ShortName: "zh-CN-YunxiNeural", FriendlyName: "", Locale: "zh-CN", Gender: "Male" } as Voice;
    expect(localName(edge)).toBe("云希");
    expect(localName({ ...edge, ShortName: "zh-CN-XiaochenNeural", LocalName: "晓辰" })).toBe("晓辰");
    expect(localName({ ...edge, ShortName: "fr-FR-DeniseNeural" })).toBe("");
  });
  it("标签翻译：Edge 的性格词与 Azure 的风格名", () => {
    const v = { VoiceTag: { VoicePersonalities: ["Warm", "cheerful", "unknown-thing"] } } as Voice;
    expect(voiceTags(v)).toEqual(["温暖", "开朗"]); // 只取前两个
    expect(styleLabel("newscast")).toBe("新闻播报");
    expect(styleLabel("made-up")).toBe("made-up");
  });
});

describe("语言", () => {
  it("中文名与分组", () => {
    expect(localeName("zh-CN")).toBe("中文（中国）");
    expect(localeName("en-US")).toBe("英语（美国）");
    expect(tabOf("zh-TW")).toBe("zh");
    expect(tabOf("ja-JP")).toBe("jako");
    expect(tabOf("fr-FR")).toBe("other");
  });
  it("常用语言排在前面", () => {
    const { common, other } = groupLocales(["fr-CA", "zh-CN", "ar-EG", "en-US"]);
    expect(common).toEqual(["zh-CN", "en-US"]);
    expect(other).toHaveLength(2);
  });
});

describe("展示工具", () => {
  it("时长格式", () => {
    expect(clock(0)).toBe("0:00");
    expect(clock(65.9)).toBe("1:05");
  });
  it("文件名去掉非法字符并截断", () => {
    const task = { id: "abc", request: { title: 'a<b>:"c"/d?', text: "x" } } as Task;
    expect(fileName(task)).toBe("a_b___c__d_");
    expect(fileName({ id: "id1", request: { title: "", text: "" } } as Task)).toBe("id1");
  });
  it("日期标签", () => {
    expect(dayLabel(new Date().toISOString())).toBe("今天");
    expect(dayLabel(new Date(Date.now() - 86400000).toISOString())).toBe("昨天");
  });
});
