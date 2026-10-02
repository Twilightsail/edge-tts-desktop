// 把已构建的后端 EXE 复制为 Tauri sidecar 要求的带目标三元组文件名。
import { copyFileSync, existsSync } from "node:fs";
import { fileURLToPath } from "node:url";

const src = fileURLToPath(new URL("../../backend/dist/edge-tts-backend.exe", import.meta.url));
const dst = fileURLToPath(new URL("../src-tauri/binaries/edge-tts-backend-x86_64-pc-windows-msvc.exe", import.meta.url));
if (!existsSync(src)) throw new Error("请先在 backend/ 下运行 build.ps1 生成 dist/edge-tts-backend.exe");
copyFileSync(src, dst);
console.log("sidecar 已就绪");
