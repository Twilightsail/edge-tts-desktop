# 后端 v0.1.0 验证记录

验证环境：本机 Windows 11 x64，Python 3.12.11，edge-tts 7.2.8。确切依赖见 `backend/uv.lock`。

## 自动化测试

`pytest -q`：23 项通过。覆盖鉴权、输入限制、成功合成的业务流程、Range 返回、字幕、原子导出、覆盖保护、删除、删除失败后的历史保留、取消、手动与自动重试、队列容量、批量与分页、音色缓存及失败回退、偏好持久化、中断恢复、CORS、单实例、SSE 缓冲与订阅释放、超时、正常关闭和统一错误格式。

这些测试中的合成器使用测试替身，用于可重复地触发取消、超时和错误。真实服务另行验证。测试工具链有一条 Starlette/httpx 的弃用提示，未影响测试；它不出现在正常后端运行流程。

`ruff check` 与 `ruff format --check`：通过。

## 真实语音服务

运行 `scripts/smoke_live.py --long-text`：

- 获取到 6 个 zh-CN 音色，使用在线刷新结果。
- 输入 UTF-8 长度 5,280 字节，覆盖 edge-tts 的 4,096 字节分块路径。
- 输出 MP3 为 2,871,648 字节，SRT 为 220 条字幕。
- 成功验证音频下载、字幕下载与 100 字节 Range 请求。
- 字幕开始时间保持递增，最后一条结束于 478.55 秒；上游边界含一处 50 毫秒的轻微交叠，按上游时间保留。

样例在 `backend/.local-data/live-smoke/tasks/ae053f8c36194afdb16fcf1a469f3cf7/`，不加入版本控制。

## 独立进程与打包

源码进程与 PyInstaller 单文件 EXE 验证启动 ready 消息、随机端口、会话鉴权、健康检查、OpenAPI、SSE、shutdown 请求及正常退出。

EXE 额外通过 `scripts/smoke_process.py --executable dist/edge-tts-backend.exe --live` 调用真实服务，验证音色获取、短中文 MP3 和字幕合成。

测试只证明当前 Windows 主机上的结果；其他机器、Tauri 外壳、安装器和前端仍需在后续阶段集成验收。
