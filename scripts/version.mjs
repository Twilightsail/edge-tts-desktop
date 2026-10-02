// 统一管理版本号：安装包文件名、关于页面、后端 /api/about 都来自这些文件，必须一致。
//   node scripts/version.mjs            检查所有位置是否一致（不一致时退出码为 1）
//   node scripts/version.mjs set 0.3.0  一次改全部位置
import { readFileSync, writeFileSync, existsSync } from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";

const root = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "..");
const at = (file) => path.join(root, file);

// [文件, 取值的正则（第 1 个捕获组是版本号）]。正则只匹配第一处，避开依赖项里的 version 字段。
const SOURCES = [
  ["frontend/package.json", /^\s*"version":\s*"([^"]+)"/m],
  ["desktop/package.json", /^\s*"version":\s*"([^"]+)"/m],
  ["desktop/src-tauri/tauri.conf.json", /^\s*"version":\s*"([^"]+)"/m],
  ["desktop/src-tauri/Cargo.toml", /^version\s*=\s*"([^"]+)"/m],
  ["backend/pyproject.toml", /^version\s*=\s*"([^"]+)"/m],
  ["backend/src/edge_tts_backend/__init__.py", /__version__\s*=\s*"([^"]+)"/],
];
// 锁文件里本项目自己的那一条（工具通常会自动更新，这里一并改，避免出现无意义的差异）
const LOCKS = [
  ["desktop/src-tauri/Cargo.lock", /(name = "edge-tts-desktop"\r?\nversion = ")([^"]+)(")/],
  ["backend/uv.lock", /(name = "edge-tts-desktop-backend"\r?\nversion = ")([^"]+)(")/],
];

const read = () => SOURCES.map(([file, re]) => ({ file, version: re.exec(readFileSync(at(file), "utf8"))?.[1] ?? "（未找到）" }));

const [command, value] = process.argv.slice(2);
if (command === "set") {
  if (!/^\d+\.\d+\.\d+$/.test(value ?? "")) { console.error("用法：node scripts/version.mjs set <主.次.修订>，例如 0.3.0"); process.exit(2); }
  for (const [file, re] of SOURCES) {
    const text = readFileSync(at(file), "utf8");
    writeFileSync(at(file), text.replace(re, (whole, old) => whole.replace(old, value)));
  }
  for (const [file, re] of LOCKS) {
    if (existsSync(at(file))) writeFileSync(at(file), readFileSync(at(file), "utf8").replace(re, `$1${value}$3`));
  }
  for (const file of ["frontend/package-lock.json", "desktop/package-lock.json"]) {
    if (!existsSync(at(file))) continue;
    const lock = JSON.parse(readFileSync(at(file), "utf8"));
    lock.version = value;
    if (lock.packages?.[""]) lock.packages[""].version = value;
    writeFileSync(at(file), JSON.stringify(lock, null, 2) + "\n");
  }
  console.log(`版本号已统一设为 ${value}`);
}

const rows = read();
const versions = new Set(rows.map((r) => r.version));
for (const r of rows) console.log(`  ${r.version.padEnd(10)} ${r.file}`);
if (versions.size !== 1) { console.error(`\n✗ 版本号不一致：${[...versions].join(" / ")}。用 node scripts/version.mjs set <版本> 统一。`); process.exit(1); }
console.log(`\n✓ 全部一致：${[...versions][0]}`);
