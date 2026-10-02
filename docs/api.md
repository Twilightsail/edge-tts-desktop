# 后端接口契约 v0.2.0

启动和构建方法见 [后端说明](../backend/README.md)。HTTP 基址来自 ready 消息中的动态端口。

生成的静态 [OpenAPI schema](openapi.json) 可用于前端生成类型；运行时 schema 以 `/api/openapi.json` 为准。

## 鉴权

所有 API（包括 health、音频、字幕、事件流与 schema）携带：

```http
Authorization: Bearer <ready 消息中的 token>
```

跨域预检 OPTIONS 不需要 token。默认允许 Vite 的 localhost/127.0.0.1:5173 和 Tauri 的 `http://tauri.localhost`、`https://tauri.localhost`、`tauri://localhost`。安装包集成时应按实际来源通过 `--origin` 配置。

## 接口清单

| 方法 | 路径 | 返回与用途 |
| --- | --- | --- |
| GET | /api/health | status、version、concurrency、pending |
| POST | /api/shutdown | 202，正常关闭独立后端进程 |
| GET | /api/openapi.json | 完整机器可读 schema |
| GET | /api/voices | 音色列表与缓存标识；用 `engine` 参数选择引擎（edge 或 azure） |
| POST | /api/voices/preview | 202，用给定参数合成一段试听，返回任务 |
| GET | /api/engines | 引擎清单与 Azure 配置状态（不含密钥） |
| PUT / DELETE | /api/engines/azure | 保存 / 删除 Azure 区域与密钥 |
| PUT | /api/engines/azure/usage | 按 Azure 门户的数字校准本月用量或额度上限 |
| POST | /api/engines/azure/test | 用已保存的密钥拉一次音色列表，验证密钥与区域 |
| GET / PUT | /api/favorites | 读取 / 整体保存收藏音色 |
| POST | /api/tasks | 202，创建一个任务 |
| POST | /api/tasks/batch | 202，按输入顺序返回任务列表 |
| GET | /api/tasks | 分页任务历史，支持状态筛选与搜索 |
| GET | /api/tasks/{id} | 任务详情 |
| PUT | /api/tasks/{id}/title | 修改任务标题 |
| POST | /api/tasks/{id}/cancel | 取消任务，已终态则原样返回 |
| POST | /api/tasks/{id}/retry | 202，创建新的任务；仅 failed/cancelled 可重试 |
| DELETE | /api/tasks/{id} | 204，删除终态任务和内部结果 |
| POST | /api/tasks/delete-many | 批量删除终态任务，返回 deleted 与 errors |
| GET | /api/tasks/{id}/audio | MP3；支持 Range 和 206 |
| GET | /api/tasks/{id}/subtitles | SRT 下载 |
| GET | /api/tasks/{id}/vtt | VTT 下载 |
| POST | /api/tasks/{id}/export | 导出单个结果，返回 destination、bytes |
| POST | /api/tasks/export-zip | 批量导出 ZIP（写入路径或直接下载） |
| GET | /api/events | SSE 状态流 |
| GET / PUT | /api/settings | 读取 / 保存全部偏好设置 |
| GET / POST | /api/presets | 预设列表 / 新建预设 |
| PUT / DELETE | /api/presets/{id} | 更新 / 删除预设 |
| POST | /api/documents/import | 上传 TXT、Markdown、DOCX，返回解析后的正文 |
| GET | /api/about | 版本、数据目录、日志位置、运行环境 |
| GET | /api/logs | 最近的后端日志（纯文本，最多约 1 MB） |
| POST | /api/logs/export | 把日志导出到应用数据目录外的 `.log` / `.txt` 文件 |
| GET | /api/storage | 任务文件、分段缓存占用 |
| DELETE | /api/storage/segment-cache | 清理分段缓存 |

## 创建任务

```json
{
  "text": "你好，欢迎使用语音合成。",
  "engine": "edge",
  "style": "",
  "voice": "zh-CN-XiaoxiaoNeural",
  "rate": 0,
  "volume": 0,
  "pitch": 0,
  "subtitles": true,
  "title": "欢迎语",
  "segment_chars": 2000,
  "subtitle_max_chars": 24,
  "subtitle_offset_ms": 0,
  "segments": []
}
```

`text` 与 `segments` 至少提供一个；有 `segments` 时 `text` 由各段按空行拼接得到。文本去除首尾空白后不可为空，总长最大 100,000 字符，超长文档请拆为多个任务（导入接口的 `requires_split` 会提示）。`voice` 使用音色列表的 `ShortName`。`rate` 范围 -90～100（百分比），`volume` -100～100（百分比），`pitch` -100～100（Hz）；均为整数。title 最大 120 字符，仅用于展示。未知字段返回 422。

| 字段 | 范围 | 说明 |
| --- | --- | --- |
| engine | `edge`（默认）或 `azure` | 合成引擎；`azure` 要求已配置密钥，否则创建时返回 409 `engine_not_configured` |
| style | 字母、数字、连字符，最长 40，默认空 | Azure 说话风格（如 `cheerful`、`newscast`），仅 `azure` 引擎使用，Edge 引擎忽略。可选值来自音色的 `StyleList`；段落（`segments[].style`）可单独覆盖。风格改变会使分段缓存失效。 |
| segment_chars | 100～5000，默认 2000 | 每个分段的最大字符数；超长段落按句末标点切分 |
| subtitle_max_chars | 8～80，默认 24 | 字幕每行最大字符数 |
| subtitle_offset_ms | -60000～60000，默认 0 | 字幕整体时间偏移，毫秒 |

### 章节 / 多角色（segments）

`segments` 最多 200 项，按顺序合并为一个音频，字幕时间随之累加：

```json
{"segments": [
  {"title": "旁白", "text": "夜深了。", "voice": "zh-CN-YunxiNeural"},
  {"title": "对话", "text": "你还没睡吗？", "voice": "zh-CN-XiaoxiaoNeural", "rate": 10}
]}
```

每段的 `voice`、`rate`、`volume`、`pitch` 可省略，省略时使用任务级的值。段落内容未变时，重新生成会复用分段缓存（`chapters[].cached` 为 true）。

批量请求结构为 `{"items": [上述请求, ...]}`，1～50 项。整批验证和入库；队列容量不足时整批拒绝。

### 任务对象

```json
{
  "id": "随机任务 ID",
  "status": "queued",
  "request": {"text":"你好。","engine":"edge","voice":"zh-CN-XiaoxiaoNeural","rate":0,"volume":0,"pitch":0,"subtitles":true,"title":"","segments":[],"segment_chars":2000,"subtitle_max_chars":24,"subtitle_offset_ms":0},
  "created_at": "ISO 8601 UTC 时间",
  "updated_at": "ISO 8601 UTC 时间",
  "stage": "queued",
  "attempt": 0,
  "audio_bytes": 0,
  "error": null,
  "audio_url": null,
  "subtitles_url": null,
  "vtt_url": null,
  "duration_seconds": 0,
  "segment_total": 1,
  "segment_completed": 0,
  "chapters": []
}
```

状态为 queued、running、succeeded、failed、cancelled。阶段为 queued、synthesizing、retry_wait、finalizing、completed、failed、cancelled、interrupted。成功后 URL 为相对于 HTTP 基址的路径；关闭字幕时 `subtitles_url` 与 `vtt_url` 为 null。关闭或崩溃中断使用 `status: failed` 与 `error.code: interrupted`。运行时 error 在 retry_wait 可暂存最近错误，最终成功时清空。

`segment_total` / `segment_completed` 是真实的分段计数，可直接用于进度条。`chapters` 每项为：

```json
{"index":0,"title":"旁白","voice":"zh-CN-YunxiNeural","status":"succeeded","cached":false,"duration_seconds":3.2}
```

章节 `status` 取值 queued、running、succeeded。`duration_seconds` 在任务成功后为总时长。

### 历史查询

`GET /api/tasks?status=succeeded&search=关键词&offset=0&limit=50`；`status` 可省略，`limit` 范围 1～200，`search` 最长 300 字符，匹配标题或正文。返回 `{items,total,offset,limit}`，按创建时间从新到旧排序。

### 改标题、批量删除

- `PUT /api/tasks/{id}/title`，请求 `{"title":"新标题"}`（可为空串），返回更新后的任务。
- `POST /api/tasks/delete-many`，请求 `{"ids":["…"]}`（1～200 项），返回 `{"deleted":["…"],"errors":[{"id","code","message"}]}`。运行中的任务会进入 errors（`task_active`），其余照常删除。

## 音色

`GET /api/voices` 支持 `locale=zh-CN`、`gender=Female`、`search=Xiaoxiao`、`refresh=true`。返回 `{items,total,timestamp,cached,stale}`。音色字段沿用上游字段，包括 ShortName、Locale、Gender、FriendlyName、VoiceTag（含 VoicePersonalities）等。timestamp 是缓存获取时的 Unix 秒数。stale 为 true 时界面提示正在使用缓存。

`POST /api/voices/preview` 请求体为偏好设置（见下），按音色语言选择示例句（支持中、日、韩、法、德、西、俄、英，未知语言回退英文），返回 202 与一个标题为“音色试听”的普通任务。客户端应轮询或通过 SSE 等待其完成，取走音频后自行删除该任务，避免出现在历史里。

`GET /api/voices?engine=azure` 返回已配置的 Azure 音色（未配置时 409）。两个引擎的音色名可能相同（如 `zh-CN-XiaoxiaoNeural`），音色缓存按引擎分开保存。Azure 音色额外带 `LocalName`（本地化名称，如“晓辰”）和 `StyleList`；为与 Edge 对齐，后端还把风格列表放进 `VoiceTag.VoicePersonalities`。

`GET /api/favorites` 返回 `{"voices":["ShortName",…]}`；`PUT /api/favorites` 以同样的结构整体替换（最多 200 项，自动去重）。Azure 音色的收藏项带 `azure:` 前缀（如 `azure:zh-CN-XiaochenNeural`），Edge 音色保持原样以兼容旧数据。

## 语音引擎

| 引擎 | 说明 |
| --- | --- |
| `edge` | 默认。Edge 在线语音，免费、无需账号；字幕为上游返回的真实句边界。 |
| `azure` | Azure AI Speech（REST）。需要用户自己的 Speech 资源密钥与区域；字幕按句子字数比例估算。 |

`GET /api/engines` 返回：

```json
{"engines":[
  {"id":"edge","name":"Edge 在线语音","configured":true},
  {"id":"azure","name":"Azure AI Speech","configured":true,"region":"eastus","key_hint":"····O5p6",
   "usage":{"month":"2026-10","chars":12340,"limit":500000}}
]}
```

`PUT /api/engines/azure`，请求 `{"region":"eastus","key":"<密钥>"}`。`region` 为小写字母和数字（3～30 位）；`key` 为 16～128 位字母数字，**省略表示沿用已保存的密钥、只更新区域**（尚无密钥时返回 422 `key_required`）。返回与 `GET /api/engines` 中 azure 项相同的配置状态。保存或删除后 Azure 音色缓存作废。`DELETE /api/engines/azure` 返回 204。

`POST /api/engines/azure/test` 总是返回 200：成功为 `{"ok":true,"voices":数量}`，失败为 `{"ok":false,"code":"…","message":"…"}`。它不会回退到旧的音色缓存，因此能真实反映密钥和区域是否有效。

**用量统计**：后端累计每月实际发给 Azure 的计费字符，用于对照免费额度（默认上限 500,000，来自官方定价页）。规则取自 Azure 文档：只统计成功的请求；每个汉字（含日文汉字、韩文汉字）算 2 个字符，其余每个 Unicode 码位算 1 个（含空格、标点）；SSML 中除 `<speak>`、`<voice>` 外的标记也计费，所以默认语速/音量/音调下请求不带 `<prosody>`，省去约 60 个计费字符。试听同样计入。按自然月（UTC）自动清零，上限保留。

这是**本机估算**：只含通过本应用发出的请求，同一密钥在别处的用量不在内，准确数字以 Azure 门户资源“指标”里的 Synthesized Characters 为准。`PUT /api/engines/azure/usage` 请求 `{"chars":123456,"limit":500000}`（两者至少一个），返回 `{month,chars,limit}`；付费档用户可把 `limit` 改成自己的预算。

**密钥安全**：密钥只写不读，任何接口、日志和任务数据都不会返回或记录它，只提供末 4 位提示。Windows 上用 DPAPI（当前用户范围）加密后存入应用数据库，数据库文件被复制到别处无法还原；非 Windows 系统仅做 base64 编码（没有等价的内置机制）。区域为 `chinaeast2`、`chinanorth2`、`chinanorth3` 时使用 `*.tts.speech.azure.cn` 域名，其余使用 `*.tts.speech.microsoft.com`。

**说话风格**：`style` 通过 SSML 的 `mstts:express-as` 应用，标记同样按字符计费（计入用量）。只有 `StyleList` 里列出的风格才有效，换成不支持该风格的音色时应清空。

**Azure 行为差异**：
- REST 接口只返回音频、不提供时间点，字幕时间按句子字数比例在每个请求的真实时长内估算，可能与语音有零点几秒偏差。
- 单次请求音频超过 10 分钟会被服务端静默截断，所以引擎内部按语速把文本拆成多个请求（语速 0% 时约每 1500 字符一个）再拼接。
- 语速下限为 -50%（超出会被钳制）。
- 免费额度、计费方式以 [Azure 官方定价页](https://azure.microsoft.com/en-us/pricing/details/speech/) 为准。音色试听同样会消耗额度。
- 命令行参数 `--azure-base-url`（或环境变量 `EDGE_TTS_AZURE_BASE_URL`）可覆盖 Azure 地址，用于公司网关或测试；默认使用官方地址。

## 偏好设置与预设

偏好设置字段（`GET/PUT /api/settings`，整体保存，省略字段重置为默认值）：

```json
{"engine":"edge","style":"","voice":"zh-CN-XiaoxiaoNeural","rate":0,"volume":0,"pitch":0,"subtitles":true,"subtitle_max_chars":24,"subtitle_offset_ms":0}
```

偏好只保存界面状态，创建任务仍需发送具体参数，不会隐式读取偏好。

预设是命名的偏好快照：`POST /api/presets` 请求 `{"name":"新闻播报","settings":{偏好设置}}`，返回 201 与 `{id,name,settings}`；`PUT /api/presets/{id}` 同结构整体更新；`DELETE` 返回 204。`name` 1～60 字符，最多 100 个。

## 文档导入

`POST /api/documents/import`，`multipart/form-data`，字段名 `file`。支持 `.txt`、`.md`（UTF-8 / UTF-8 BOM / UTF-16 / GBK 自动识别）和 `.docx`（读取正文段落）。文件上限 8 MB，正文上限 2,000,000 字符。

```json
{"name":"小说.txt","text":"正文…","encoding":"utf-8-sig","characters":23,"requires_split":false}
```

接口只解析、不创建任务。`requires_split` 为 true 表示超过单任务 100,000 字符，客户端应切成多个任务（可用批量接口，单批最多 50 项）。

## 日志与诊断

后端把日志写在数据目录的 `logs/backend.log`，自动轮转（1 MB × 4 份）。日志只记录事件和错误类别，**不记录用户文本、音频、令牌或 Azure 密钥**。

- `GET /api/about` 返回 `{version,data_dir,log_file,python,platform,edge_tts}`。
- `GET /api/logs` 以 `text/plain` 返回按时间顺序拼接的最近日志（最多约 1 MB），同样需要令牌。
- `POST /api/logs/export` 请求 `{"destination":"C:\\Users\\用户\\edge-tts.log","overwrite":false}`，目标必须是应用数据目录外、已存在目录中的 `.log` 或 `.txt` 绝对路径；成功返回 `{destination,bytes}`，已存在且未设置 `overwrite` 时 409。

## 存储

`GET /api/storage` 返回 `{"cache_bytes":…,"task_bytes":…,"tasks":…}`：分段缓存、任务输出文件占用字节数与任务数。`DELETE /api/storage/segment-cache` 清理分段缓存，任务输出与已导出的文件不受影响；分段合成运行期间返回 409 `cache_busy`。

## 错误

HTTP 错误结构：

```json
{"error":{"code":"task_not_found","message":"任务不存在"}}
```

422 额外带 `details: [{field,message}]`。

| 状态码 | code | 含义 |
| --- | --- | --- |
| 400 | directory_not_found / internal_destination / invalid_extension / invalid_destination | 导出目标目录不存在、位于应用数据目录内、扩展名不符（`.mp3`、`.srt`、`.vtt`、`.zip`） |
| 400 | document_invalid | 文档格式、编码、大小或内容不被支持 |
| 400 | export_failed | 写入导出文件失败（权限、磁盘等） |
| 401 | unauthorized | 令牌无效 |
| 404 | task_not_found / artifact_not_found / preset_not_found | 任务、结果文件或预设不存在 |
| 409 | invalid_state / task_active / task_not_ready | 状态冲突，如重试了未失败的任务、删除运行中的任务、结果尚未生成 |
| 409 | file_exists | 目标文件已存在（未设置 overwrite） |
| 409 | cache_busy | 分段缓存正被使用 |
| 409 | engine_not_configured | 选择了 Azure 但尚未配置密钥和区域 |
| 409 | preset_limit | 预设已达 100 个上限 |
| 409 | shutdown_unavailable | 当前宿主负责后端生命周期 |
| 429 | queue_full | 待处理任务达到上限 |
| 503 | voices_unavailable | 音色服务不可用且无缓存 |

合成失败不会改变创建接口的 202；失败信息存在任务的 `error` 字段，结构为 `{code,message,retryable}`。网络类错误通常为 network、upstream_http、no_audio；Azure 的错误为 azure_auth（401，密钥无效或与区域不匹配，不重试）、azure_forbidden（403，可能已超出免费额度或资源被停用，不重试）、azure_rate_limit（429，限流或额度用尽，会自动重试）、azure_bad_request（400，音色名或参数不被支持，不重试）；文件错误为 storage；其他错误为 synthesis_failed。

## 音频与导出

浏览器 audio 标签无法自行添加 Authorization。可以通过认证 fetch 获取 Blob，再创建 Object URL 供 audio 标签播放，播放结束或切换任务后释放 URL；不要把 token 放入 URL。

```typescript
const response = await fetch(`${baseUrl}${task.audio_url}`, {
  headers: { Authorization: `Bearer ${token}` },
});
if (!response.ok) throw new Error("音频加载失败");
const objectUrl = URL.createObjectURL(await response.blob());
audio.src = objectUrl;
// 切换音频或组件卸载时：URL.revokeObjectURL(objectUrl)
```

### 单个导出

由桌面文件对话框先选择目标，再发送：

```json
{"destination":"C:\\Users\\用户\\Music\\欢迎语.mp3","kind":"audio","overwrite":false}
```

`kind` 为 `audio`（.mp3）、`subtitles`（.srt）或 `vtt`（.vtt），扩展名必须与之对应。不允许写到内部应用数据目录。缺少字幕、任务尚未完成、目标目录不存在时返回明确错误。

### 批量 ZIP

`POST /api/tasks/export-zip`，请求：

```json
{"ids":["任务 ID"],"destination":"C:\\Users\\用户\\Music\\配音.zip","overwrite":false,"include_subtitles":true}
```

- 提供 `destination`（须为应用数据目录外、已存在目录中的 `.zip` 绝对路径）：后端写入文件，返回 `{destination,bytes,tasks}`。
- 省略 `destination`：直接以 `application/zip` 返回文件内容，浏览器环境可保存为 Blob。

`ids` 1～200 项，且都必须是已完成任务。压缩包内每个任务为 `序号_标题.mp3`，`include_subtitles` 为 true 时附带同名 `.srt` 与 `.vtt`，另含 `manifest.json`（id、文件名、标题、时长）。

## SSE

通过带 Authorization 的 fetch 读取 `/api/events`，使用流式 SSE 解析器。原生 EventSource 不支持自定义请求头，不适用于当前令牌方案。

- snapshot：订阅后的最新 100 项状态，结构为 `{items,total,offset,limit}`。
- task.created、task.updated：任务状态对象；包含任务对象的所有字段（含 `chapters`、`segment_completed`），排除 request，避免反复传输长文本。
- task.deleted：`{"id":"任务 ID"}`。
- resync：客户端处理过慢导致缓冲丢弃，请重新 GET /api/tasks 同步。
- 每 15 秒发送一条注释心跳，不作为业务事件处理。

snapshot 的 items 同样不含 request，需要完整文本或参数时调用详情接口。断线重连后重新接受 snapshot；没有事件持久日志或 Last-Event-ID 回放。历史超过 100 项时通过历史分页接口补齐。进度以 `segment_completed / segment_total` 为准，不要把“合成字节数”转换成未经验证的百分比。

## 桌面进程管理

外壳负责启动 sidecar、读取 ready、保存本次会话凭据、监听异常退出，并关闭子进程。退出前先带令牌 POST `/api/shutdown`，收到 202 后等待进程结束；超时再终止整个进程树。Windows 单文件 EXE 会有外层加载进程与内部业务进程，单独终止外层进程可能残留业务进程。强制退出后，下次启动会修复 running 记录。源代码终端启动支持 Ctrl+C 正常关闭。CLI 的优雅关闭期限为 5 秒，防止长连接无限阻塞退出。

通过其他 Python 宿主直接加载 `create_app` 时，宿主拥有生命周期；shutdown 返回 409。独立 CLI 与 EXE 支持 shutdown。

同一数据目录仅允许一个后端进程；双开使用不同 `--data-dir`。桌面应用本身为单实例，再次启动会把已有窗口带到前台。后端端口始终限定本机环回地址。
