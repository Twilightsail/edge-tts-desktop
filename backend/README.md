# Edge TTS Desktop 后端

Python 3.12+，FastAPI + edge-tts + SQLite。独立进程只监听 127.0.0.1；所有 API 都需要会话令牌。依赖版本由 `uv.lock` 固定。

## 已实现

- 日志写入数据目录 `logs/backend.log`（轮转），不含用户文本和密钥；`GET /api/about`、`/api/logs` 提供诊断信息。
- Azure 说话风格（`style`）与用量统计。
- 双引擎：默认 Edge 在线语音（免费）；可选 Azure AI Speech（用户自备密钥，REST 接口）。密钥在 Windows 上用 DPAPI 加密保存，接口只返回末 4 位。Azure 字幕按句子字数估算，详见[接口契约](../docs/api.md)。
- 音色查询、语言/性别/关键字筛选、24 小时缓存；联网刷新失败时回退缓存并返回 `stale: true`。
- 文本合成与批量创建；语速、音量、音调可调，输出 MP3 和可选 SRT。
- edge-tts 内置长文本分块、连续音频和字幕偏移处理。
- 默认两个并发任务，最多 100 个待处理任务；支持取消、有限自动重试和手动重试。
- SQLite 历史、分页、状态筛选、偏好设置；退出后排队任务保留，异常中断任务标记为失败。
- SSE 状态推送、认证音频下载、Range 请求、字幕下载、原子文件导出和任务删除。
- 随机端口、会话鉴权、限定 CORS、数据目录单实例锁、Windows 独立 EXE 构建脚本。
- 带鉴权的正常关闭接口，避免单文件打包子进程残留。

## 本地启动

在此目录打开 PowerShell：

```powershell
uv sync --frozen --extra dev
.\start.ps1
```

默认数据目录是 `%LOCALAPPDATA%\EdgeTTSDesktop`。开发时可隔离目录：

```powershell
.\start.ps1 -Port 8765 -DataDir "$PWD\.local-data\dev"
```

启动完成后 stdout 输出一行 JSON：

```json
{"event":"ready","host":"127.0.0.1","port":8765,"token":"<本次会话令牌>","version":"0.1.0"}
```

stderr 输出日志。桌面外壳应从私有管道读取 stdout，保存端口与令牌，在收到 ready 后发请求。令牌不要写入日志、URL、持久配置或共享给其他应用。终端开发时可通过环境变量 `EDGE_TTS_TOKEN` 设置自己的令牌；未设置则每次随机生成。

自定义代理使用 `EDGE_TTS_PROXY` 或 `--proxy`。自定义前端来源使用可重复的 `--origin` 参数；提供参数时替换默认来源列表。完整参数：

```powershell
.\.venv\Scripts\python.exe -m edge_tts_backend --help
```

## 验证

```powershell
.\.venv\Scripts\pytest.exe -q
.\.venv\Scripts\ruff.exe check src tests scripts run_backend.py
.\.venv\Scripts\python.exe scripts\smoke_process.py
```

真实联网测试（会把所写测试文本发送给在线语音服务，并保留样例文件）：

```powershell
.\.venv\Scripts\python.exe scripts\smoke_live.py
.\.venv\Scripts\python.exe scripts\smoke_live.py --long-text
```

## Windows 打包

```powershell
.\build.ps1
```

输出 `dist\edge-tts-backend.exe`，包含 Python 运行时与业务依赖。构建后自动验证启动、令牌校验、健康检查、OpenAPI 和 SSE。桌面外壳需要隐藏子进程窗口；这是供外壳调用的控制台程序。

可额外验证 EXE 的真实联网合成：

```powershell
.\.venv\Scripts\python.exe scripts\smoke_process.py --executable dist\edge-tts-backend.exe --live
```

后续集成 Tauri 时，将程序复制并按其平台后缀规则命名为 sidecar，例如 `edge-tts-backend-x86_64-pc-windows-msvc.exe`。当前测试在本机 Windows 上完成，尚未进行其他机器、杀毒软件环境与 Tauri 安装包的验收。

## 运行约定

- 设置接口保存 UI 偏好；创建任务仍需发送具体参数，省略字段使用接口默认值，不隐式读取用户偏好。
- 单文本最多 100,000 字符，单批最多 50 项。并发数量可以通过 CLI 设置为 1–4。
- 每次合成尝试最多 30 分钟；网络超时、连接失败、HTTP 429/5xx 与无音频最多尝试三次，等待 2 秒、4 秒后重试。
- 不伪造百分比；返回实际阶段和已接收音频字节数。
- 取消会移除部分结果；手动重试创建新任务 ID，保留原任务历史。
- 正常关闭时正在运行的任务标记为 interrupted，可手动重试；强制终止后的 running 记录在下次启动时恢复为 interrupted。queued 记录会重新入队。
- 删除终态任务会删除其内部输出文件；导出到用户目录的文件保留。
- 导出目标必须为已存在目录中的绝对路径，扩展名为 `.mp3` 或 `.srt`。默认拒绝覆盖；显式 `overwrite: true` 才替换。
- 已生成结果支持离线试听，新的合成仍依赖在线服务。后端不提供离线模型、声音克隆、任意 SSML、情绪控制或 WAV 转码。

前端对接详见 [接口契约](../docs/api.md)。
