// 安装测试：把安装包静默安装到临时目录，用安装出来的程序跑一遍端到端测试，再静默卸载并检查是否清理干净。
// 这是在“没有开发环境的机器”上的体验的近似（同一台机器上，但程序来自安装目录而不是构建目录）。
//   npm run e2e:install
import { spawnSync } from "node:child_process";
import { existsSync, mkdtempSync, readFileSync, readdirSync, rmSync } from "node:fs";
import { tmpdir } from "node:os";
import path from "node:path";
import { fileURLToPath } from "node:url";

const here = path.dirname(fileURLToPath(import.meta.url));
const version = JSON.parse(readFileSync(path.resolve(here, "../src-tauri/tauri.conf.json"), "utf8")).version;
const installer = path.resolve(here, `../src-tauri/target/release/bundle/nsis/Edge TTS_${version}_x64-setup.exe`);
let passed = 0, failed = 0;
const check = (name, ok, detail = "") => { ok ? passed++ : failed++; console.log(`${ok ? "  ✓" : "  ✗"} ${name}${!ok && detail ? `  ← ${detail}` : ""}`); };
// 用 -EncodedCommand 传脚本：经过 Node/Windows 命令行时，脚本里的引号和 $ 不会被吃掉
const ps = (script) => spawnSync("pwsh", ["-NoProfile", "-EncodedCommand", Buffer.from(script, "utf16le").toString("base64")], { encoding: "utf8" }).stdout.trim();

if (!existsSync(installer)) { console.error(`找不到安装包：${installer}\n请先构建（npx tauri build）`); process.exit(2); }

// 安装/卸载会操作注册表里的卸载项和开始菜单快捷方式；如果机器上已有正式安装的版本，测试可能影响到它，所以直接中止
const existing = ps(`@('HKCU:','HKLM:') | % { Get-ChildItem "$_\\Software\\Microsoft\\Windows\\CurrentVersion\\Uninstall" -ErrorAction SilentlyContinue } | % { Get-ItemProperty $_.PSPath } | ? { $_.DisplayName -like 'Edge TTS*' } | % { $_.DisplayName }`);
if (existing) { console.error(`检测到已安装的「${existing}」。为避免影响它，安装测试已中止（请先卸载，或在干净的虚拟机里运行）。`); process.exit(2); }
const shortcut = () => ps(`Get-ChildItem "$env:APPDATA\\Microsoft\\Windows\\Start Menu\\Programs" -Recurse -Filter 'Edge TTS*.lnk' -ErrorAction SilentlyContinue | % { $_.Name }`);
const uninstallEntry = () => ps(`Get-ChildItem 'HKCU:\\Software\\Microsoft\\Windows\\CurrentVersion\\Uninstall' -ErrorAction SilentlyContinue | % { Get-ItemProperty $_.PSPath } | ? { $_.DisplayName -like 'Edge TTS*' } | % { $_.DisplayName }`);

const work = mkdtempSync(path.join(tmpdir(), "edge-tts-install-"));
const dir = path.join(work, "app"); // 路径里不能有空格：NSIS 的 /D= 不能加引号
let exitCode = 1;
try {
  console.log(`安装 ${path.basename(installer)} → ${dir}`);
  const install = spawnSync(installer, ["/S", `/D=${dir}`], { stdio: "ignore" });
  check("安装程序正常退出", install.status === 0, `退出码 ${install.status}`);
  const mainExe = path.join(dir, "edge-tts-desktop.exe");
  check("主程序已安装", existsSync(mainExe));
  check("后端程序（sidecar）与主程序在同一目录", existsSync(path.join(dir, "edge-tts-backend.exe")));
  check("卸载程序已生成", existsSync(path.join(dir, "uninstall.exe")));
  check("已注册到“应用”列表", uninstallEntry().includes("Edge TTS"), "未找到卸载项。请在普通的 PowerShell/cmd 里运行本测试：某些受限或沙箱化的终端会隔离注册表写入，导致这一项误报");
  check("已创建开始菜单快捷方式", shortcut().length > 0, shortcut());

  console.log("\n用安装出来的程序运行端到端测试：");
  const e2e = spawnSync("node", [path.join(here, "smoke.mjs")], { stdio: "inherit", env: { ...process.env, E2E_EXE: mainExe } });
  check("端到端测试全部通过", e2e.status === 0, `退出码 ${e2e.status}`);

  console.log("\n卸载：");
  const un = spawnSync(path.join(dir, "uninstall.exe"), ["/S", `_?=${dir}`], { stdio: "ignore" }); // _?= 让卸载程序同步执行
  check("卸载程序正常退出", un.status === 0, `退出码 ${un.status}`);
  const left = existsSync(dir) ? readdirSync(dir).filter((f) => f !== "uninstall.exe") : [];
  check("程序文件已清除", left.length === 0, left.join(", "));
  check("“应用”列表中的条目已移除", uninstallEntry() === "", uninstallEntry());
  check("开始菜单快捷方式已移除", shortcut() === "", shortcut());
  const residue = ps(`if (Test-Path 'HKCU:\Software\Edge TTS') { 'HKCU\Software\Edge TTS' }`);
  if (residue) { console.log(`  ⚠ 注册表残留（NSIS 的厂商键，无害）：${residue}，已由测试清除`); ps(`Remove-Item 'HKCU:\Software\Edge TTS' -Recurse -Force`); }
  exitCode = failed ? 1 : 0;
} finally {
  try { rmSync(work, { recursive: true, force: true }); } catch { /* 忽略 */ }
}
console.log(`\n${failed ? "✗ 失败" : "✓ 全部通过"}：${passed} 项通过，${failed} 项失败`);
process.exit(exitCode);
