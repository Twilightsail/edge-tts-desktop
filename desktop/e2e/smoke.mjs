// 端到端冒烟测试：启动打包好的桌面应用 + 假 Azure 服务器，驱动真实窗口走完主要流程。
// 完全离线、使用临时数据目录；结束后自动清理。用法：先构建应用，再运行  npm run e2e
import { spawn, spawnSync } from "node:child_process";
import { existsSync, mkdtempSync, readFileSync, rmSync, writeFileSync, mkdirSync } from "node:fs";
import { tmpdir } from "node:os";
import path from "node:path";
import { fileURLToPath } from "node:url";
import { connect } from "./lib.mjs";

const here = path.dirname(fileURLToPath(import.meta.url));
// E2E_EXE 可指向“安装出来的”程序（见 install-test.mjs），默认用构建目录里的
const exe = process.env.E2E_EXE ?? path.resolve(here, "../src-tauri/target/release/edge-tts-desktop.exe");
const python = path.resolve(here, "../../backend/.venv/Scripts/python.exe");
const GOOD = "A1b2C3d4E5f6G7h8I9j0K1l2M3n4O5p6";
const CDP = 9444, FAKE = 18081;
const windowState = path.join(process.env.APPDATA ?? "", "com.edgettsdesktop.app", ".window-state.json");

for (const [what, file] of [["应用", exe], ["后端虚拟环境", python]]) {
  if (!existsSync(file)) { console.error(`找不到${what}：${file}\n请先构建（desktop 下 npx tauri build）并在 backend 下 uv sync`); process.exit(2); }
}
if (spawnSync("tasklist", ["/FI", "IMAGENAME eq edge-tts-desktop.exe"], { encoding: "utf8" }).stdout.includes("edge-tts-desktop.exe")) {
  console.error("检测到 Edge TTS 正在运行，请先关闭它再运行测试（否则单实例机制会让测试接管你的窗口）。");
  process.exit(2);
}

const work = mkdtempSync(path.join(tmpdir(), "edge-tts-e2e-"));
const dataDir = path.join(work, "data"), localDir = path.join(work, "local"), logFile = path.join(work, "azure.log");
mkdirSync(dataDir); mkdirSync(localDir);
const savedState = existsSync(windowState) ? readFileSync(windowState) : null; // 测试会改写窗口状态文件，结束时还原

let fake, app, passed = 0, failed = 0;
const check = (name, ok, detail = "") => {
  ok ? passed++ : failed++;
  console.log(`${ok ? "  ✓" : "  ✗"} ${name}${!ok && detail ? `  ← ${detail}` : ""}`);
};
const sleep = (ms) => new Promise((r) => setTimeout(r, ms));
const waitFor = async (fn, ms = 20000, step = 250) => {
  const end = Date.now() + ms;
  while (Date.now() < end) { try { const v = await fn(); if (v) return v; } catch { /* 继续等 */ } await sleep(step); }
  return null;
};

async function cleanup() {
  if (app?.pid) {
    spawnSync("taskkill", ["/PID", String(app.pid)], { stdio: "ignore" }); // 先优雅关闭，让后端也正常退出
    await sleep(9000);
    spawnSync("taskkill", ["/PID", String(app.pid), "/T", "/F"], { stdio: "ignore" });
  }
  if (fake?.pid) spawnSync("taskkill", ["/PID", String(fake.pid), "/T", "/F"], { stdio: "ignore" });
  await sleep(500);
  try { savedState ? writeFileSync(windowState, savedState) : rmSync(windowState, { force: true }); } catch { /* 忽略 */ }
  try { rmSync(work, { recursive: true, force: true }); } catch { /* 数据库文件可能仍被占用，留给系统清理临时目录 */ }
}

try {
  console.log("启动假 Azure 服务器与桌面应用…");
  fake = spawn(python, [path.join(here, "fake_azure.py"), String(FAKE), logFile], { stdio: "ignore" });
  await waitFor(async () => (await fetch(`http://127.0.0.1:${FAKE}/cognitiveservices/voices/list`)).status === 401, 30000);
  app = spawn(exe, [], {
    stdio: "ignore",
    env: {
      ...process.env, LOCALAPPDATA: localDir, EDGE_TTS_DATA_DIR: dataDir,
      // 浏览器存储（localStorage 里的主题、侧栏宽度、额度提醒标记）必须单独隔离，否则会写进真实应用的数据
      WEBVIEW2_USER_DATA_FOLDER: path.join(work, "webview"),
      EDGE_TTS_AZURE_BASE_URL: `http://127.0.0.1:${FAKE}`,
      WEBVIEW2_ADDITIONAL_BROWSER_ARGUMENTS: `--remote-debugging-port=${CDP}`,
    },
  });
  const page = await waitFor(async () => { const p = await connect(CDP); return (await p.ev(`!!document.querySelector('.shell')`)) ? p : (p.close(), null); }, 60000, 500);
  if (!page) throw new Error("应用窗口没有在 60 秒内出现");
  const { ev, sleep: wait, type, shot, close } = page;
  const text = (sel) => ev(`document.querySelector(${JSON.stringify(sel)})?.innerText?.replace(/\\n/g,' | ') ?? ''`);
  const press = (key, opts = "") => ev(`window.dispatchEvent(new KeyboardEvent('keydown',{key:${JSON.stringify(key)},bubbles:true,cancelable:true${opts}}))`);
  const clickIn = (scope, label) => ev(`(()=>{const b=[...document.querySelector(${JSON.stringify(scope)}).querySelectorAll('button')].find(x=>x.innerText.includes(${JSON.stringify(label)}));if(!b)return false;b.click();return true})()`);
  const setSelect = (sel, value) => ev(`(()=>{const s=document.querySelector(${JSON.stringify(sel)});Object.getOwnPropertyDescriptor(HTMLSelectElement.prototype,'value').set.call(s,${JSON.stringify(value)});s.dispatchEvent(new Event('change',{bubbles:true}));return true})()`);
  const api = (method, route, body) => ev(`(async()=>{const c=await window.__TAURI_INTERNALS__.invoke('get_conn');const r=await fetch(c.baseUrl+${JSON.stringify(route)},{method:${JSON.stringify(method)},headers:{Authorization:'Bearer '+c.token,'Content-Type':'application/json'},body:${body ? JSON.stringify(JSON.stringify(body)) : "undefined"}});return JSON.stringify({status:r.status,text:await r.text()})})()`).then(JSON.parse);

  console.log("\n[启动与连接]");
  check("后端已连接", !!(await waitFor(async () => (await text(".ch-sub")).includes("引擎已连接"), 30000)));
  // 注意：调试接口执行的代码不受 CSP 约束，所以用“往页面里注入内联脚本”来检验策略是否真的在拦截
  check("CSP 已生效（页面内联脚本被拦截）", (await ev(`(()=>{window.__csp=0;const s=document.createElement("script");s.textContent="window.__csp=1";document.head.appendChild(s);return window.__csp===0})()`)) === true);
  check("单实例：再次启动不会多开窗口", await (async () => {
    spawn(exe, [], { stdio: "ignore", env: process.env }).unref(); await sleep(4000);
    return spawnSync("tasklist", ["/FI", "IMAGENAME eq edge-tts-desktop.exe"], { encoding: "utf8" }).stdout.split("edge-tts-desktop.exe").length - 1 === 1;
  })());

  console.log("\n[Azure 配置]");
  await clickIn(".engine-row", "Azure"); await wait(900);
  check("未配置时点 Azure：打开面板并提示", (await ev(`document.querySelector('.panel').classList.contains('open')`)) && (await text(".toast")).includes("密钥"));
  await type("input[aria-label='Azure 区域']", "eastus");
  await type("input[aria-label='Azure 密钥']", "WrongKey0000000000000000000000000");
  await clickIn(".azure-box", "保存并测试");
  await waitFor(async () => (await text(".azure-box .error-text")).length > 0, 15000);
  check("错误密钥：给出清楚的提示", (await text(".azure-box .error-text")).includes("密钥无效"), await text(".azure-box .error-text"));
  await type("input[aria-label='Azure 密钥']", GOOD);
  await clickIn(".azure-box", "保存并测试");
  await waitFor(async () => (await text(".azure-box .ok-text")).includes("连接成功"), 15000);
  check("正确密钥：连接成功", (await text(".azure-box .ok-text")).includes("连接成功"), await text(".azure-box .ok-text"));
  check("密钥只显示末 4 位", (await text(".azure-head .tag")).includes("O5p6"));

  console.log("\n[音色与引擎切换]");
  await press("Escape"); await wait(500);
  check("Esc 关闭面板", !(await ev(`document.querySelector('.panel').classList.contains('open')`)));
  await clickIn(".engine-row", "Azure");
  await waitFor(async () => (await text(".voice-row .vr-sub")).includes("晓"), 15000);
  check("切到 Azure，显示中文名", (await text(".voice-row .vr-sub")).includes("晓辰"));
  check("中文标签里有可读中文的多语言音色", (await ev(`[...document.querySelectorAll('.group-title')].some(h=>h.innerText.includes('多语言音色'))`)));
  await ev(`document.querySelector('.search-box input').focus()`);
  const before = await text(".voice-row.sel .vr-name");
  await ev(`document.querySelector('.search-box input').dispatchEvent(new KeyboardEvent('keydown',{key:'ArrowDown',bubbles:true,cancelable:true}))`); await wait(300);
  check("↓ 键切换音色", (await text(".voice-row.sel .vr-name")) !== before, `${before} → ${await text(".voice-row.sel .vr-name")}`);

  console.log("\n[说话风格与合成]");
  await ev(`[...document.querySelectorAll('.voice-row')].find(r=>r.innerText.includes('Xiaochen')).click()`); await wait(300);
  await ev(`document.querySelector('button[title=合成设置]').click()`); await wait(900);
  check("支持风格的音色出现风格下拉框", !!(await ev(`!!document.querySelector("select[aria-label='说话风格']")`)));
  check("风格显示中文名", (await ev(`[...document.querySelectorAll("select[aria-label='说话风格'] option")].map(o=>o.innerText).join(',')`)).includes("开朗"));
  await setSelect("select[aria-label='说话风格']", "cheerful"); await wait(300);
  await press("Escape"); await wait(500);
  const msg = "你好，这是端到端测试。今天天气不错！";
  await type("textarea", msg); await wait(300);
  check("发送前预估 Azure 消耗", (await text(".counter")).includes("预计消耗"));
  await ev(`document.querySelector('.send').click()`);
  const done = await waitFor(async () => ev(`!!document.querySelector('.msg.in .voice')`), 20000);
  check("合成完成并出现语音消息", !!done);
  check("气泡标出 Azure 与风格", (await text(".msg.out .sender")).includes("Azure") && (await text(".msg.out .sender")).includes("开朗"), await text(".msg.out .sender"));
  const speaks = readFileSync(logFile, "utf8").trim().split("\n").map((l) => JSON.parse(l)).filter((l) => l.kind === "speak");
  check("请求带认证头与输出格式", speaks[0]?.key === GOOD && speaks[0]?.fmt === "audio-24khz-48kbitrate-mono-mp3");
  check("SSML 含 express-as 风格", speaks[0]?.body.includes("<mstts:express-as style='cheerful'>"), speaks[0]?.body);
  await ev(`document.querySelector('.play').click()`); await wait(900);
  check("点击播放进入播放状态", (await ev(`document.querySelector('.morph').className`)).includes("on"));

  console.log("\n[用量与风格重置]");
  await ev(`document.querySelector('button[title=合成设置]').click()`); await wait(900);
  const usage = await text(".usage-head");
  check("用量增加（含风格标记）", /[1-9]\d* \/ 500,000/.test(usage), usage);
  await ev(`[...document.querySelectorAll('.voice-row')].find(r=>r.innerText.includes('Xiaoxiao')).click()`); await wait(500);
  check("换到不支持风格的音色：风格选项消失", !(await ev(`!!document.querySelector("select[aria-label='说话风格']")`)));
  await press("Escape"); await wait(500);

  console.log("\n[侧栏]");
  const width = () => ev(`Math.round(document.querySelector('.sidebar').getBoundingClientRect().width)`);
  const w0 = await width();
  // 回归：侧栏拖到最窄时，右上角的折叠按钮不能被裁掉
  const mouse = (type, x) => page.call("Input.dispatchMouseEvent", { type, x, y: 300, button: "left", buttons: type === "mouseReleased" ? 0 : 1, clickCount: 1 });
  const edge = (await width()) - 3;
  await mouse("mouseMoved", edge); await mouse("mousePressed", edge);
  for (const x of [300, 270, 262, 260]) { await mouse("mouseMoved", x); await wait(40); }
  await mouse("mouseReleased", 260); await wait(700);
  const fits = await ev(`(()=>{const sb=document.querySelector('.sidebar').getBoundingClientRect(),b=document.querySelector('.side-top > .round').getBoundingClientRect();return Math.round(sb.width)+':'+(b.right<=sb.right&&b.left>=sb.left)})()`);
  check("侧栏最窄(260)时折叠按钮完整可见", fits === "260:true", fits);
  await mouse("mouseMoved", 257); await mouse("mousePressed", 257); await mouse("mouseMoved", w0); await mouse("mouseReleased", w0); await wait(600);
  await press("b", ",ctrlKey:true"); await wait(900);
  check("Ctrl+B 折叠成窄栏", (await width()) < 100 && (await ev(`document.querySelector('.shell').classList.contains('collapsed')`)), String(await width()));
  // 折叠窄栏：要能看清是什么、能操作
  const railText = await text(".side-rail");
  check("窄栏有分组标题与当前音色名", railText.includes("当前") && (await text(".rail-item.big .rail-name")).length > 0, railText.slice(0, 60));
  check("窄栏显示当前引擎", (await text(".rail-engine")).includes("Azure"), await text(".rail-engine"));
  const target = JSON.parse(await ev(`(()=>{const el=[...document.querySelectorAll('.rail-item')].find(e=>!e.classList.contains('sel'));const r=el.getBoundingClientRect();return JSON.stringify({x:r.left+r.width/2,y:r.top+r.height/2,name:el.querySelector('.rail-name').innerText})})()`));
  await page.call("Input.dispatchMouseEvent", { type: "mouseMoved", x: target.x, y: target.y }); await wait(500);
  check("悬停弹出详情卡片", (await text(".rail-tip")).includes(target.name), await text(".rail-tip"));
  const headerBefore = await text(".ch-title strong");
  await ev(`[...document.querySelectorAll('.rail-item')].find(e=>!e.classList.contains('sel')).click()`); await wait(400);
  check("点击窄栏里的音色可切换", (await text(".ch-title strong")) !== headerBefore, `${headerBefore} → ${await text(".ch-title strong")}`);
  await ev(`document.querySelector('.rail-bottom .round').click()`); await wait(1200);
  check("窄栏的搜索入口：展开并聚焦搜索框", !(await ev(`document.querySelector('.shell').classList.contains('collapsed')`)) && (await ev(`document.activeElement?.getAttribute('aria-label')==='搜索音色'`)));
  check("展开后恢复宽度", Math.abs((await width()) - w0) < 3);

  console.log("\n[诊断与安全]");
  await ev(`document.querySelector('button[title=合成设置]').click()`); await wait(900);
  const aboutText = await text(".about");
  check("关于面板显示版本与数据目录", /\d+\.\d+\.\d+/.test(aboutText) && aboutText.includes(dataDir.slice(0, 12)), aboutText.slice(0, 120));
  const logs = await api("GET", "/api/logs");
  check("日志可读取且含后端启动记录", logs.status === 200 && logs.text.includes("starting"));
  check("日志中没有 Azure 密钥", !logs.text.includes(GOOD) && !logs.text.includes("WrongKey"));
  const exported = path.join(work, "exported.log");
  const ex = await api("POST", "/api/logs/export", { destination: exported });
  check("导出日志到外部路径", ex.status === 200 && existsSync(exported) && !readFileSync(exported, "utf8").includes(GOOD));
  const db = readFileSync(path.join(dataDir, "history.sqlite3"));
  const wal = existsSync(path.join(dataDir, "history.sqlite3-wal")) ? readFileSync(path.join(dataDir, "history.sqlite3-wal")) : Buffer.alloc(0);
  check("数据库里没有明文密钥", !db.includes(GOOD) && !wal.includes(GOOD));

  console.log("\n[清理]");
  await clickIn(".azure-box", "删除密钥"); await wait(1200);
  check("删除密钥后回到未配置并切回 Edge", (await text(".azure-head .tag")).includes("未配置") && (await text(".engine-row button.on")).includes("Edge"));
  await shot(path.join(work, "final.png"));
  close();
} catch (error) {
  failed++;
  console.error("\n测试中断：", error.message);
} finally {
  await cleanup();
}

console.log(`\n${failed ? "✗ 失败" : "✓ 全部通过"}：${passed} 项通过，${failed} 项失败`);
process.exit(failed ? 1 : 0);
