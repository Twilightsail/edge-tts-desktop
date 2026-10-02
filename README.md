# Edge TTS Desktop

把文字变成语音的 Windows 桌面工具。界面像 Telegram：左边挑音色，中间是对话，你发一段文字，它回你一条语音消息。

## 它能做什么

- **两种语音引擎**：Edge 在线语音（免费，无需账号），或接入你自己的 Azure AI Speech（音色更多，有多种说话风格）。左上角一键切换。
- **长文本**：自动分段合成，失败时自动重试，不用自己切文章。
- **章节与多角色**：一篇文字可拆成多个章节/角色，每段单独指定音色和风格；也可以按段落输出成多个独立文件。
- **导入文档**：点回形针或直接拖入 TXT、Markdown、DOCX。
- **字幕导出**：生成 SRT / VTT。Edge 引擎的字幕与语音逐句对齐。
- **批量导出**：多选历史消息，打包成 ZIP。
- **语音消息播放器**：波形可点击跳转，支持 1× / 1.5× / 2× 倍速，可保存为 MP3。
- **调参与预设**：语速、音量、音调可调，常用组合存为预设，一键套用。
- **音色栏**：搜索、收藏、试听；可拖动调宽，或折叠成头像窄栏（Ctrl+B）。
- **Azure 用量提示**：显示本月估算用量，发送前预估消耗，用到 80% 和 100% 时提醒。
- **桌面体验**：单实例运行、记住窗口位置和大小、任务完成时发系统通知。

## 下载与安装

到 **[Releases](https://github.com/Twilightsail/edge-tts-desktop/releases/latest)** 下载 `Edge-TTS_x.y.z_x64-setup.exe`，双击安装。需要 Windows 10/11 64 位和网络，不需要管理员权限。

> 安装包没有代码签名，Windows 会弹出“Windows 已保护你的电脑”，点 **“更多信息” → “仍要运行”** 即可。可用 Release 里的 `SHA256SUMS.txt` 校验文件。

使用方法见 [用户指南](docs/用户指南.md)。

## 隐私与注意事项

- 你输入的文字会发送到微软的服务器进行合成（Edge 引擎发给 Edge 朗读服务，Azure 引擎发给你自己的 Azure 资源）。
- 软件不含任何统计或遥测。Azure 密钥用 Windows 账户加密保存在本机；日志不含你的文字和密钥。
- Edge 在线语音使用的是微软的非官方接口，可能随时变化或失效；Azure 引擎需要你自己的订阅密钥。

遇到问题请[提交 Issue](https://github.com/Twilightsail/edge-tts-desktop/issues)，并附上应用内“关于与诊断 → 导出日志”得到的日志。

## 技术栈

Tauri 2（桌面外壳）+ React / TypeScript / Vite（界面）+ Python / FastAPI（本地后端，打包为 EXE 作为 sidecar）。

| 目录 | 说明 |
| --- | --- |
| `backend/` | 语音合成、任务管理、配置与历史记录（[后端说明](backend/README.md)） |
| `frontend/` | 聊天界面、播放器、任务进度 |
| `desktop/` | Tauri 外壳、后端进程管理、安装包 |
| `docs/` | [技术方案](docs/architecture.md)、[接口契约](docs/api.md)、[发布指南](docs/发布指南.md) |

## 许可

源码以 [MIT 许可](LICENSE) 发布。安装包还包含第三方组件（如 GPL-3.0 的 FFmpeg、LGPL-3.0 的 edge-tts），各自遵循自己的许可，完整声明见应用内“关于与诊断 → 开源许可”和 Release 里的《第三方许可声明》。
