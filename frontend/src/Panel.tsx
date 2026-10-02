import { useEffect, useRef, useState } from "react";
import { useApp } from "./ctx";
import { localeName } from "./locales";
import Segmented from "./Segmented";
import type { About, Preferences, Preset, StorageInfo } from "./types";
import { isDesktop, pickSavePath } from "./desktop";
import NoticesDialog from "./NoticesDialog";
import { Avatar, genderLabel, Icon, mb, saveBlob, styleLabel, voiceName, voiceTags } from "./ui";

const SLIDERS = [
  ["rate", "语速", -90, 100, "%"],
  ["volume", "音量", -100, 100, "%"],
  ["pitch", "音调", -100, 100, "Hz"],
] as const;

const ENGINES = [["edge", "Edge · 免费"], ["azure", "Azure"]] as const;

export default function Panel({ open, focusAzure, onClose, onRefreshVoices }: { open: boolean; focusAzure: number; onClose: () => void; onRefreshVoices: () => void }) {
  const { api, prefs, setPref, setPrefs, voiceMap, favorites, toggleFavorite, previewVoice, previewing, notify, revision, engines, reloadEngines, setEngine, refreshVoices } = useApp();
  const azure = engines.find((e) => e.id === "azure");
  const azureRef = useRef<HTMLElement>(null);
  const [region, setRegion] = useState("");
  const [key, setKey] = useState("");
  const [azureBusy, setAzureBusy] = useState(false);
  const [azureMsg, setAzureMsg] = useState<{ ok: boolean; text: string }>();
  const [about, setAbout] = useState<About>();
  const [notices, setNotices] = useState(false);
  const [calibrating, setCalibrating] = useState(false);
  const [calUsed, setCalUsed] = useState("");
  const [calLimit, setCalLimit] = useState("");
  const [presets, setPresets] = useState<Preset[]>([]);
  const [presetId, setPresetId] = useState("");
  const [presetName, setPresetName] = useState("");
  const [storage, setStorage] = useState<StorageInfo>();

  useEffect(() => { api.presets().then(setPresets).catch((e) => notify(e.message, "err")); }, [api, notify]);
  useEffect(() => {
    if (open) api.storage().then(setStorage).catch((e) => notify(e.message, "err"));
  }, [api, notify, revision, open]);

  const action = async (fn: () => Promise<void>) => {
    try { await fn(); } catch (e) { notify((e as Error).message, "err"); }
  };
  useEffect(() => { if (azure?.region) setRegion((r) => r || azure.region!); }, [azure?.region]);
  useEffect(() => {
    if (!focusAzure) return;
    const t = setTimeout(() => azureRef.current?.scrollIntoView({ behavior: "smooth", block: "start" }), 180);
    return () => clearTimeout(t);
  }, [focusAzure]);

  const saveAzure = async () => {
    setAzureBusy(true);
    setAzureMsg(undefined);
    try {
      await api.saveAzure(region.trim().toLowerCase(), key.trim() || undefined);
      setKey("");
      await reloadEngines();
      const result = await api.testAzure();
      setAzureMsg(result.ok ? { ok: true, text: `连接成功，可用 ${result.voices} 个音色` } : { ok: false, text: result.message ?? "连接失败" });
      if (result.ok && prefs.engine === "azure") void refreshVoices(true).catch(() => {});
    } catch (e) {
      setAzureMsg({ ok: false, text: (e as Error).message });
    } finally {
      setAzureBusy(false);
    }
  };
  const usage = azure?.usage;
  const ratio = usage && usage.limit > 0 ? usage.chars / usage.limit : 0;
  const level = ratio >= 1 ? "full" : ratio >= 0.8 ? "warn" : "";
  const openCalibrate = () => {
    setCalUsed(String(usage?.chars ?? 0));
    setCalLimit(String(usage?.limit ?? 500000));
    setCalibrating((v) => !v);
  };
  const saveCalibration = async () => {
    try {
      await api.setAzureUsage({ chars: Math.max(0, Math.round(Number(calUsed))), limit: Math.max(1, Math.round(Number(calLimit))) });
      await reloadEngines();
      setCalibrating(false);
      notify("用量已校准", "ok");
    } catch (e) {
      notify((e as Error).message, "err");
    }
  };
  const removeAzure = async () => {
    try {
      await api.deleteAzure();
      if (prefs.engine === "azure") setEngine("edge");
      await reloadEngines();
      setKey("");
      setAzureMsg({ ok: true, text: "密钥已从本机删除" });
    } catch (e) {
      setAzureMsg({ ok: false, text: (e as Error).message });
    }
  };

  const voice = voiceMap.get(prefs.voice);
  const styles = prefs.engine === "azure" ? voice?.StyleList ?? [] : [];

  useEffect(() => {
    if (open && !about) api.about().then(setAbout).catch(() => {});
  }, [open, about, api]);
  const exportLogs = async () => {
    try {
      if (isDesktop) {
        const dest = await pickSavePath("edge-tts-日志.log", "log");
        if (dest) { await api.exportLogs(dest); notify(`日志已保存到 ${dest}`, "ok"); }
      } else {
        saveBlob(await api.blob("/api/logs"), "edge-tts-日志.log");
      }
    } catch (e) {
      notify((e as Error).message, "err");
    }
  };
  const copyDiagnostics = async () => {
    try {
      await navigator.clipboard.writeText(JSON.stringify({ app: __APP_VERSION__, ...about }, null, 2));
      notify("诊断信息已复制", "ok");
    } catch {
      notify("无法访问剪贴板，请改用“导出日志”", "err");
    }
  };
  const fav = favorites.includes(prefs.voice);

  const applyPreset = (p: Preset) => {
    setPresetId(p.id);
    setPresetName(p.name);
    setPrefs({ ...p.settings, engine: p.settings.engine ?? "edge", style: p.settings.style ?? "" }); // 旧预设没有 engine 字段
  };
  const savePreset = () => action(async () => {
    if (!presetName.trim()) throw new Error("请输入预设名称");
    const p = await api.savePreset(presetName.trim(), prefs);
    setPresets((ps) => [...ps, p]);
    setPresetId(p.id);
    notify("预设已保存", "ok");
  });
  const updatePreset = () => action(async () => {
    await api.updatePreset(presetId, presetName.trim() || "未命名", prefs);
    setPresets(await api.presets());
    notify("预设已更新", "ok");
  });
  const deletePreset = () => action(async () => {
    await api.deletePreset(presetId);
    setPresets((ps) => ps.filter((p) => p.id !== presetId));
    setPresetId("");
  });
  const clearCache = () => action(async () => {
    await api.clearCache();
    setStorage(await api.storage());
    notify("分段缓存已清理，任务输出与已导出的文件保留", "ok");
  });

  return (
    <aside className={open ? "panel open" : "panel"} aria-hidden={!open}>
      <div className="panel-in">
      <div className="panel-head">
        <h2>合成设置</h2>
        <button className="round" onClick={onClose} title="关闭"><Icon name="close" /></button>
      </div>

      <div className="panel-scroll">
        <section className="profile">
          <Avatar name={voiceName(prefs.voice)} size={84} />
          <h3>{voiceName(prefs.voice)}</h3>
          <p>{voice ? [localeName(voice.Locale), genderLabel(voice.Gender), ...voiceTags(voice)].join(" · ") : prefs.voice}</p>
          <div className="profile-actions">
            <button onClick={() => void toggleFavorite(prefs.voice)}><Icon name="star" size={18} filled={fav} />{fav ? "已收藏" : "收藏"}</button>
            <button onClick={() => void previewVoice(prefs.voice)}>
              {previewing === prefs.voice ? <span className="spinner" /> : <Icon name="speaker" size={18} />}试听
            </button>
          </div>
        </section>

        <section ref={azureRef}>
          <h4>语音引擎</h4>
          <Segmented variant="pill" options={ENGINES} value={prefs.engine} onChange={setEngine} />
          <p className="hint">
            {prefs.engine === "azure"
              ? "Azure 的字幕时间按句子字数比例估算，可能与语音有零点几秒偏差；语速最低 -50%。"
              : "Edge 在线语音免费、无需账号，音色较少；字幕为逐句真实时间。"}
          </p>
          <div className="azure-box">
            <div className="azure-head">
              <strong>Azure AI Speech</strong>
              <span className={azure?.configured ? "tag ok" : "tag"}>{azure?.configured ? `已配置 ${azure.key_hint}` : "未配置"}</span>
            </div>
            {azure?.configured && usage && (
              <div className="usage">
                <div className="usage-head"><span>本月约已用</span><b>{usage.chars.toLocaleString()} / {usage.limit.toLocaleString()} 字符</b></div>
                <div className={`usage-bar ${level}`}><i style={{ width: `${Math.min(100, ratio * 100)}%` }} /></div>
                <div className="usage-foot">
                  <span>{Math.round(ratio * 100)}% · 本机估算，每个汉字计 2 字符</span>
                  <button className="link" onClick={openCalibrate}>{calibrating ? "收起" : "校准"}</button>
                </div>
                <div className={calibrating ? "collapse open" : "collapse"}>
                  <div className="collapse-in">
                    <div className="calibrate">
                      <label>本月已用<input aria-label="已用字符" type="number" min={0} value={calUsed} onChange={(e) => setCalUsed(e.target.value)} /></label>
                      <label>额度上限<input aria-label="额度上限" type="number" min={1} value={calLimit} onChange={(e) => setCalLimit(e.target.value)} /></label>
                      <button onClick={saveCalibration}>保存</button>
                      <p className="hint">只统计通过本应用发出的请求。准确数字请在 Azure 门户资源的“指标”里看 Synthesized Characters；付费档可把上限改成自己的预算。</p>
                    </div>
                  </div>
                </div>
              </div>
            )}
            <label>区域<input aria-label="Azure 区域" value={region} placeholder="如 eastus、westeurope" onChange={(e) => setRegion(e.target.value)} /></label>
            <label>密钥<input aria-label="Azure 密钥" type="password" autoComplete="off" spellCheck={false} value={key} placeholder={azure?.configured ? "留空则沿用已保存的密钥" : "粘贴 Speech 资源的密钥"} onChange={(e) => setKey(e.target.value)} /></label>
            <div className="btn-row">
              <button disabled={azureBusy || !region.trim() || (!azure?.configured && !key.trim())} onClick={saveAzure}>
                {azureBusy ? <span className="spinner" /> : <Icon name="check" size={16} />}保存并测试
              </button>
              {azure?.configured && <button className="danger" disabled={azureBusy} onClick={removeAzure}><Icon name="trash" size={16} />删除密钥</button>}
            </div>
            {azureMsg && <div className={azureMsg.ok ? "ok-text" : "error-text"}>{azureMsg.text}</div>}
            <p className="hint">在 Azure 门户创建 Speech 资源并选免费档 F0（官方定价页：神经语音每月 50 万字符免费），把密钥和区域填在这里。密钥用当前 Windows 账户加密保存在本机，不会显示、不会上传到别处。</p>
          </div>
        </section>

        {styles.length > 0 && (
          <section>
            <h4>说话风格</h4>
            <select aria-label="说话风格" value={prefs.style} onChange={(e) => setPref("style", e.target.value)}>
              <option value="">默认</option>
              {styles.map((s) => <option key={s} value={s}>{styleLabel(s)}</option>)}
            </select>
            <p className="hint">该音色支持 {styles.length} 种风格。风格标记也会计入 Azure 字符用量。</p>
          </section>
        )}

        <section>
          <h4>语音参数</h4>
          {SLIDERS.map(([key, label, min, max, unit]) => (
            <label className="slider" key={key}>
              <span className="slider-head">{label}<b>{prefs[key] > 0 ? "+" : ""}{prefs[key]}{unit}</b></span>
              <input type="range" min={key === "rate" && prefs.engine === "azure" ? -50 : min} max={max} value={prefs[key]} onChange={(e) => setPref(key, Number(e.target.value))} onDoubleClick={() => setPref(key, 0)} title="双击复位" />
            </label>
          ))}
        </section>

        <section>
          <h4>字幕</h4>
          <label className="switch-row">
            生成 SRT 和 VTT 字幕
            <input type="checkbox" className="switch" checked={prefs.subtitles} onChange={(e) => setPref("subtitles", e.target.checked)} />
          </label>
          {prefs.subtitles && (
            <div className="two-col">
              <label>每行字符数<input type="number" min={8} max={80} value={prefs.subtitle_max_chars} onChange={(e) => setPref("subtitle_max_chars", Number(e.target.value))} /></label>
              <label>偏移（毫秒）<input type="number" min={-60000} max={60000} step={100} value={prefs.subtitle_offset_ms} onChange={(e) => setPref("subtitle_offset_ms", Number(e.target.value))} /></label>
            </div>
          )}
        </section>

        <section>
          <h4>参数预设</h4>
          {presets.length === 0 && <p className="hint">还没有预设。调好参数后在下面命名保存，之后一键套用。</p>}
          <ul className="preset-list">
            {presets.map((p) => (
              <li key={p.id} className={p.id === presetId ? "on" : ""} onClick={() => applyPreset(p)}>
                <Avatar name={p.name} size={34} />
                <div><strong>{p.name}</strong><span>{voiceName(p.settings.voice)} · 语速 {p.settings.rate}% · 音调 {p.settings.pitch}Hz</span></div>
              </li>
            ))}
          </ul>
          <input aria-label="预设名称" placeholder="预设名称" maxLength={60} value={presetName} onChange={(e) => setPresetName(e.target.value)} />
          <div className="btn-row">
            <button onClick={savePreset}>另存为</button>
            <button disabled={!presetId} onClick={updatePreset}>更新所选</button>
            <button className="danger" disabled={!presetId} onClick={deletePreset}>删除所选</button>
          </div>
        </section>

        <section>
          <h4>关于与诊断</h4>
          <div className="about">
            <div><b>Edge TTS 桌面版</b> {__APP_VERSION__}</div>
            {about && <div className="hint">后端 {about.version} · Python {about.python} · edge-tts {about.edge_tts || "—"}</div>}
            {about && <div className="hint path">数据目录：{about.data_dir}</div>}
            <div className="btn-row">
              <button onClick={exportLogs}><Icon name="download" size={16} />导出日志</button>
              <button onClick={copyDiagnostics}><Icon name="doc" size={16} />复制诊断信息</button>
              <button onClick={() => setNotices(true)}><Icon name="list" size={16} />开源许可</button>
            </div>
            {notices && <NoticesDialog onClose={() => setNotices(false)} />}
            <p className="hint">日志只记录事件和错误类别，不含你的文本、令牌或 Azure 密钥。遇到问题时把导出的日志发给开发者即可。</p>
          </div>
        </section>

        <section>
          <h4>存储与音色</h4>
          <div className="storage">
            <div><b>{mb(storage?.task_bytes ?? 0)}</b><span>任务文件</span></div>
            <div><b>{mb(storage?.cache_bytes ?? 0)}</b><span>分段缓存</span></div>
            <div><b>{storage?.tasks ?? 0}</b><span>任务数</span></div>
          </div>
          <div className="btn-row">
            <button onClick={onRefreshVoices}><Icon name="refresh" size={16} />刷新音色</button>
            <button onClick={clearCache}><Icon name="trash" size={16} />清理缓存</button>
          </div>
        </section>
      </div>
      </div>
    </aside>
  );
}
