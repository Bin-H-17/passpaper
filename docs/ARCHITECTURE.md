# 递纸 PassPaper — 架构说明（v4 架构）

> 版本：公开 v1.0.0（内部为第 4 代架构设计 lineage，以下简称「v4 架构」）。
> 本文是**当前架构的权威说明**，替代根目录历史快照 `PASSPAPER_TECH_OVERVIEW.txt`（v2 懒渲染版，仅作演进留档，已被 gitignore）。
> 配套：`docs/RECOGNITION.md`（识别管线）、`README.md`、`PROJECT_STATUS.md`。

---

## 1. 一句话架构

```
[平板浏览器 canvas.html]  --WebSocket(笔画)-->  [daemon.py 常驻]
                                                     │ 内存画布(增量渲染 ~25ms)
                                                     │ 会话落盘 JSONL(recorder)
                                                     │ 配对令牌鉴权
                                                     ├──HTTP /snapshot /image /mcp/call
                                                     ▼
                                            [mcp_shim.py 极薄 stdio]
                                                     │ 标准 MCP（握手 <100ms）
                                                     ▼
                                         [Claude Code / Codex CLI]
```

**核心思想**：平板落笔 → 常驻 daemon 把笔画存进内存画布并可选录制成会话 → AI 客户端通过极薄 MCP shim 拉取最新手写（图 / 文本 / LaTeX）。AI 是**主动来读**，不是用户拍照推送。

---

## 2. 为什么是「daemon + 极薄 shim」双层（v4 相对 v2/v3 的关键演进）

- **v2（懒渲染）**：`bridge.py`（WS+HTTP）直接被 MCP server 调。简单，但 MCP server 与桥耦合、跨客户端（Codex）要重写。
- **v4**：拆成
  - **daemon.py**：唯一常驻进程。持有内存画布、会话录制、配对鉴权、HTTP 接口。不依赖任何 AI 客户端。
  - **mcp_shim.py**：极薄 stdio 进程。只把 MCP 协议翻译成对 daemon 的 HTTP 调用（标准库实现，握手 <100ms）。**同一份 shim 同时支持 Claude Code 与 Codex**（两者 2026 起均支持 MCP）。

借鉴署名见 `REFERENCES.md`（mcp_excalidraw 的同款 daemon+shim 拆分层）。

---

## 3. 模块职责（对应 `src/passpaper/`）

| 模块 | 职责 |
|------|------|
| `daemon.py` | 常驻服务。WebSocket 收笔画（`stroke`/`batch`/`clear`）、内存画布、HTTP `/snapshot`(PNG) `/image` `/mcp/call`、配对令牌鉴权、断线缓存+重连批量补发。 |
| `mcp_shim.py` | 极薄 stdio MCP server。`TOOLS` 暴露 9 个工具，收到调用后走 HTTP 到 daemon。 |
| `canvas.html` | 平板端单文件网页。Pointer Events + 自研增量渲染；「保存会话 / 新建会话」按钮；存书签即开即用，零安装。 |
| `recorder.py` | `SessionRecorder`：每笔落盘 `DATA_DIR/sessions/<id>.jsonl`；`list_sessions / start_new_session / strokes_of / export(md|jsonl|json|excalidraw)`。增量、可 git、可回放。 |
| `recognition.py` | 可插拔识别：`get_recognizer()`→`LocalVLMRecognizer`(OpenAI 兼容 `/chat/completions`) 或回退 `AgentVisionFallback`。输出 `text / latex / confidence / engine / note`。未配端点时**优雅回退**到「Agent 直接看图」。 |
| `cli.py` | 命令行：`start/stop/status/url/serve/mcp/setup/doctor/rotate-token`、`sessions list|current|new|show|export`、`recognize [--image]`。 |
| `common.py` | `VERSION`、`PORT`、`DATA_DIR`、配对令牌读写、HTTP 头、Pythonw 发现、局域网 IP、运行时 bundle 同步。 |
| `__init__.py` | 包元数据（`__version__`）。 |

---

## 4. 关键数据流

### 4.1 手写 → AI 看见（核心闭环）
1. 平板落笔 → Pointer 事件 → WebSocket JSON（`x,y,pressure,color`）发给 daemon。
2. daemon 存进内存画布（增量渲染，~25ms 取图），并 `recorder.record_stroke` 落盘 JSONL。
3. 用户：「看看我刚写的」。Claude Code / Codex 自主调用 MCP 工具 `get_handwriting`。
4. mcp_shim → HTTP `daemon/snapshot` → 渲染 PNG（base64）回传。
5. AI 多模态模型看图、理解、回应。

### 4.2 识别管线（可选）
- 配了 `PASSPAPER_RECOGNIZER_ENDPOINT`：`recognize_handwriting` 工具 / `passpaper recognize` 会先调本地 VLM 转成 `text + latex`，再交给 AI（或单独返回）。
- 未配：回退 `AgentVisionFallback`，AI 直接看图——核心体验零依赖、不降级。

### 4.3 会话回溯
- 每次笔触/清空都进 JSONL。关页面、重启、甚至 `git checkout` 旧会话都能还原。
- 导出 Excalidraw 可在 Excalidraw / tldraw 里回放编辑（本赛道独有）。

---

## 5. 延迟与韧性设计

- **增量渲染**：取图 = 读内存缓存（实测 ~25ms），非整图重绘。
- **断线缓存**：WebSocket 断连时笔画本地缓存，重连后自动批量补发，墨迹不丢。
- **零云依赖**：纯局域网；无账号、无出站调用；断外网也能跑。

---

## 6. 鉴权与隐私

- **配对令牌**：`setup` 阶段生成一次性配对链接（QR/书签零安装），`rotate-token` 可轮换。HTTP 接口带 `daemon_http_headers()` 鉴权。
- **数据边界**：手写只走你自己的机器 + 局域网；识别若配本地模型则完全离线，配云端端点时仅图片出网（用户可控，详见 `docs/RECOGNITION.md` 隐私段）。

---

## 7. 演进方向（roadmap）

- SVG-first 矢量墨迹输出（借鉴 claude-monet-mcp），兼顾结构化与可编辑。
- 更多本地识别后端开箱（PaddleOCR-VL / GLM-OCR）。
- 系统托盘 App、真·语义擦除、Cloudflare Tunnel 模式（远程调试）。
- PyPI 发布 + MCP 市场提交。

详见 README「路线图」一节。
