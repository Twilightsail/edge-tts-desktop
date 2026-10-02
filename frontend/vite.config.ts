import { readFileSync } from "node:fs";
import { spawn, type ChildProcess } from "node:child_process";
import { createInterface } from "node:readline";
import path from "node:path";
import react from "@vitejs/plugin-react";
import { defineConfig, type Plugin } from "vite";

// 开发期代替 Tauri 外壳：启动后端子进程，读取 ready 消息，把端口与令牌通过 /__conn 交给页面。
function backendLauncher(): Plugin {
  let child: ChildProcess | undefined;
  let conn: Promise<{ baseUrl: string; token: string }> | undefined;
  const backendDir = path.resolve(__dirname, "../backend");

  const launch = () =>
    new Promise<{ baseUrl: string; token: string }>((resolve, reject) => {
      const python = path.join(backendDir, ".venv/Scripts/python.exe");
      const args = ["-m", "edge_tts_backend"];
      if (process.env.EDGE_TTS_DATA_DIR) args.push("--data-dir", process.env.EDGE_TTS_DATA_DIR);
      child = spawn(python, args, { cwd: backendDir, stdio: ["ignore", "pipe", "inherit"] });
      child.on("error", reject);
      child.on("exit", (code) => {
        conn = undefined;
        reject(new Error(`后端已退出 (${code})`));
      });
      createInterface({ input: child.stdout! }).on("line", (line) => {
        try {
          const msg = JSON.parse(line);
          if (msg.event === "ready") {
            resolve({ baseUrl: `http://${msg.host}:${msg.port}`, token: msg.token });
          }
        } catch {
          /* 非 JSON 行忽略 */
        }
      });
    });

  const stop = () => child?.kill();

  return {
    name: "backend-launcher",
    configureServer(server) {
      server.middlewares.use("/__conn", async (_req, res) => {
        try {
          conn ??= launch();
          const body = await conn;
          res.setHeader("Content-Type", "application/json");
          res.setHeader("Cache-Control", "no-store");
          res.end(JSON.stringify(body));
        } catch (e) {
          res.statusCode = 500;
          res.end(String(e));
        }
      });
      server.httpServer?.on("close", stop);
      process.on("exit", stop);
    },
  };
}

// 端口必须是 5173：后端默认 CORS 白名单只包含该来源。
export default defineConfig({
  define: { __APP_VERSION__: JSON.stringify(JSON.parse(readFileSync(path.resolve(__dirname, "package.json"), "utf-8")).version) },
  plugins: [react(), backendLauncher()],
  server: { host: "127.0.0.1", port: 5173, strictPort: true },
});
