# Edge TTS Desktop

把文字转成语音的 Windows 桌面工具。Telegram 风格的聊天界面：左边是音色，中间是对话，你发文本，它回语音消息。

支持 Edge 在线语音（免费）和 Azure AI Speech（自备密钥）两种引擎；长文本、章节与多角色、字幕导出（SRT/VTT）、批量导出 ZIP、导入 TXT/Markdown/DOCX。

## 下载

到 **[Releases](https://github.com/Twilightsail/edge-tts-desktop/releases/latest)** 下载 `Edge-TTS_x.y.z_x64-setup.exe`，双击安装（Windows 10/11 64 位，不需要管理员权限）。

> 安装包**没有代码签名**，Windows 会弹出蓝色的“Windows 已保护你的电脑”，点 **“更多信息” → “仍要运行”** 即可。可对照 Release 里的 `SHA256SUMS.txt` 校验文件。

使用说明见 [用户指南](docs/用户指南.md)。**请注意**：Edge 在线语音走的是微软的非官方接口，可能随时变化；你输入的文字会发送给微软的服务器；Azure 引擎需要你自己的订阅密钥。

遇到问题请[提交 Issue](https://github.com/Twilightsail/edge-tts-desktop/issues)，并附上应用内“关于与诊断 → 导出日志”得到的日志（不含你的文字和密钥）。

## 许可

本项目源码以 [MIT 许可](LICENSE) 发布。发布的安装包还包含第三方组件（如 GPL-3.0 的 FFmpeg、LGPL-3.0 的 edge-tts），各自遵循自己的许可，完整声明见应用内“关于与诊断 → 开源许可”和 Release 里的《第三方许可声明》。

---

## 开发说明

当前阶段：后端、前端界面与 Tauri 桌面外壳均已完成，已构建 Windows 安装包。

建议采用 Tauri 2 + React/TypeScript/Vite + Python/FastAPI + SQLite，优先交付 Windows 版本。

目录分工：

- `backend/`：Python 语音合成、任务管理、配置与历史记录。
- `frontend/`：界面、播放器、任务进度与错误展示。
- `desktop/`：Tauri 外壳、文件对话框、后端进程管理与安装包。
- `docs/`：架构方案与后续接口契约。

详细分析见 [技术方案](docs/architecture.md)。

后端启动、测试及构建见 [后端说明](backend/README.md)，前端对接见 [接口契约](docs/api.md)。

## 桌面应用

`desktop/` 是 Tauri 2 外壳：启动后端 EXE、读取 ready 消息、向界面提供端口与令牌、原生"另存为"导出，退出时正常关闭后端。外壳还负责：单实例（再次启动会把已有窗口带到前台）、记住窗口大小与位置、任务完成/失败的系统通知（仅窗口不在前台时发送，连续完成的多个任务合并为一条）。`frontend/` 是 React + TypeScript + Vite 的 Telegram 风格界面。界面左上角可在 Edge（免费）与 Azure 两个引擎间切换；Azure 需在右侧"合成设置"面板填入自己的 Speech 资源密钥和区域（密钥加密保存在本机）。面板里会显示 Azure 本月用量条（本机估算，可按 Azure 门户校准），发送前预估这次消耗，用量到 80% 和 100% 时各提醒一次。

左侧音色栏可拖动右边缘调整宽度（260–480 px），拖得更窄会吸附成头像窄栏；也可点栏顶的按钮、双击分隔线或按 Ctrl+B 折叠/展开。宽度与折叠状态记在本机。

折叠后的窄栏分“当前 / 收藏 / 更多”三组，头像下写着名字（有中文名用中文），顶部显示并可切换当前引擎，底部有搜索和设置入口；悬停显示详情卡片，悬停头像出现试听按钮；音色列表没加载出来时也会显示当前音色，并提供重试。

界面支持键盘操作：Esc 关闭最上层的弹窗/面板/搜索栏，焦点在搜索框或音色列表时用 ↑/↓ 切换音色，Ctrl+B 折叠侧栏。

右侧面板的“关于与诊断”显示版本和数据目录，可一键导出日志。

测试：`backend` 下 `pytest`；`frontend` 下 `npm test`（单元测试）；`desktop` 下 `npm run e2e`（离线端到端冒烟测试，详见 [desktop/e2e/README.md](desktop/e2e/README.md)）。

测试时可设置环境变量 `EDGE_TTS_DATA_DIR` 把后端数据指向临时目录，避免污染真实历史。窗口状态保存在 `%APPDATA%\com.edgettsdesktop.app\.window-state.json`。

```powershell
# 前提：backend/ 已执行 uv sync --frozen --extra dev 和 .\build.ps1
cd desktop
npm install
npm run prepare-backend          # 复制后端 EXE 为 sidecar
npx tauri dev                    # 开发运行（会自动启动前端 dev server）
npx tauri build                  # 生成安装包 src-tauri\target\release\bundle\nsis\
```

另可 `cd frontend && npm run dev` 在浏览器中调试界面（由 Vite 插件代启后端）。

## 发布给别人用

```powershell
.\scripts\release.ps1 -Contact "你的邮箱或网址"   # 一键：检查 → 测试 → 打包 → 许可声明 → 安装包 → 端到端 → release\vX.Y.Z\
cd desktop; npm run e2e:install                   # 另外：静默安装 → 端到端 → 卸载 的安装测试（请在普通 PowerShell 中运行）
```

- 发布前必读：[发布指南](docs/发布指南.md)（许可合规、签名、自动更新、Edge 引擎的风险）。
- 给使用者的说明：[用户指南](docs/用户指南.md)。
- 版本号：`node scripts/version.mjs`（检查一致性）/ `node scripts/version.mjs set 0.3.0`（统一修改）。
- 第三方许可声明由 `scripts/gen_notices.py` 生成，应用内“关于与诊断 → 开源许可”可查看。

