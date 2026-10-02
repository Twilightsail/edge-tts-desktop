# 技术选型建议

## 目标与假设

优先开发 Windows 桌面工具，前后端分工开发。第一版支持文本转语音、音色筛选、语速/音量/音调调整、音频试听、MP3 导出、SRT 字幕和任务历史。

edge-tts 使用在线服务；桌面程序仍需要联网。上游支持音色列表、参数调整及字幕输出，但不支持任意自定义 SSML。第一版不承诺情绪控制、声音克隆或离线合成。

## 方案比较

| 方案 | 优点 | 成本与适用情况 |
| --- | --- | --- |
| Tauri 2 + React + Python | 网页界面便于独立开发；Python 直接调用 edge-tts；Tauri 可携带独立后端程序 | 需要维护 Rust/JS/Python 构建链，管理后端进程并按平台打包。推荐用于本项目的前后端分工 |
| PySide6 + Python | 同一语言即可实现界面与业务，无需本地 HTTP 服务；适合快速制作实用工具 | 定制界面需要 Qt Widgets 或 QML 经验；与 Web 前端的分工方式不同。若目标只是尽快获得可用工具，优先考虑此方案 |
| Electron + React + Python | Web 前端开发方便，桌面生态成熟 | 除 Python 外还携带 Chromium/Node.js；仍需管理 Python 进程。团队已有 Electron 经验时值得选择 |

Tauri 外壳通常较轻，但本项目还要携带 Python 运行时与依赖，安装包大小必须以实际构建结果为准。

## 推荐组件

- 前端：React、TypeScript、Vite；页面负责交互与试听。
- 桌面：Tauri 2；Rust 层保持精简，负责窗口、文件对话框与子进程生命周期。
- 后端：Python 3.12、edge-tts、FastAPI、Uvicorn、Pydantic。开发阶段使用独立虚拟环境，交付时锁定经过验证的依赖版本。
- 并发：asyncio 队列与可取消任务，初期限制少量并发，不引入 Redis/Celery。
- 存储：SQLite 保存任务与设置，音频保存在文件系统。数据库与缓存放在用户应用数据目录，避免写入安装目录。
- 打包：先验证 PyInstaller 打包 Python 后端，再作为 Tauri sidecar 随安装包分发。早期就做最小打包验证。

## 通信与生命周期

Tauri 启动常驻 Python 后端，后端只监听 127.0.0.1，通过操作系统分配可用端口并报告就绪状态。每次启动生成会话令牌，所有业务请求校验令牌；CORS 仅允许预期前端来源。开发与安装包环境分别配置来源。

前端通过 HTTP 创建和查询任务，通过 SSE 接收任务状态。应用退出时通知后端关闭，必要时终止子进程。后端意外退出时，界面显示明确错误并提供恢复入口。

生成任务由后端统一负责。前端不直接调用 Microsoft 服务，也不直接操作任务数据库。导出路径由桌面文件对话框选定，后端完成校验和文件写入。

## 后端职责与接口草案

以下是后续实现的接口草案，并非已经可调用的接口。

| 接口 | 用途 |
| --- | --- |
| GET /api/health | 就绪与版本信息 |
| GET /api/voices | 音色列表、语言筛选，支持缓存与刷新 |
| POST /api/tasks | 创建合成任务，返回任务 ID |
| GET /api/tasks | 查询任务历史 |
| GET /api/tasks/{id} | 查询状态、结果与错误 |
| POST /api/tasks/{id}/cancel | 取消排队或运行中的任务 |
| GET /api/events | SSE 推送任务状态 |
| GET /api/tasks/{id}/audio | 返回音频用于试听，支持浏览器所需的范围请求 |
| POST /api/tasks/{id}/export | 导出音频或字幕 |

任务状态：queued、running、succeeded、failed、cancelled。进度必须对应真实可测阶段；无法准确估算时展示阶段名称，不伪造百分比。失败任务提供可读原因与显式重试；自动重试仅用于可恢复网络错误，次数有限。

长文本按段落/句子切分，每段保留顺序与时间偏移，字幕偏移需要随音频拼接调整。第一版先完成单文本闭环，再加入长文本和批量任务。默认输出 MP3；如需 WAV 或复杂拼接，再评估引入 FFmpeg。

## 实施顺序

1. 验证真实合成、音色获取，以及 Python 后端的 Windows 打包。
2. 定义请求/响应模型和错误格式，完成单文本合成、取消、试听与导出。
3. 接入 SQLite 历史、字幕、网络超时与重试，验证异常退出恢复。
4. 对接前端并完成 Tauri 安装包，在没有 Python 开发环境的 Windows 机器上验收。
5. 再扩展长文本、批量转换和其他平台。

## 官方参考

- edge-tts：https://github.com/rany2/edge-tts
- Tauri sidecar：https://v2.tauri.app/develop/sidecar/
- FastAPI：https://fastapi.tiangolo.com/features/
- Qt for Python：https://doc.qt.io/qtforpython-6/
- Electron 进程模型：https://www.electronjs.org/docs/latest/tutorial/process-model
