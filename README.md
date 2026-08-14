# 递纸 PassPaper

[中文](#中文) | [English](#english)

---

## 中文

**在平板上手写公式/草图，AI 自己调用工具过来看。**

不是截图发给 AI——是你写字，AI 通过 [MCP](https://modelcontextprotocol.io) 工具主动读取。
支持 **Claude Code** 和 **Codex CLI**。

> **状态**：v1.0.0 早期版本。核心功能已实现并通过代码级校验（`py_compile` / import / 识别解析），但尚未在大规模真机环境验证。欢迎在 GitHub Issues 反馈问题与使用场景。

> **定位差异**：递纸不做一个「AI 白板」去和现有白板 / 绘图工具正面竞争，而是专注一个窄而深的场景——**把平板手写实时、稳定、私密地喂给你的本地 AI 编码助手**，并围绕 *中文潦草 / 公式手写识别*、*25ms 级低延迟取图*、*手写会话可随项目回溯*、*通用 MCP（不锁客户端）* 做差异化。设计上受到多个开源项目的启发，逐条署名见 [REFERENCES.md](REFERENCES.md)。

```
[平板 Chrome]                    [电脑]
 手写 canvas ──WebSocket──▶ passpaper daemon (常驻)
                              │  笔画落笔即渲染到内存画布
   Claude Code / Codex ◀─MCP stdio─ mcp_shim (极薄, <100ms 握手)
                              └──── localhost HTTP ────┘
```

### 四大差异化卖点（为什么用递纸而不是别的）

递纸不做一个「AI 白板」去和成熟白板 / 绘图工具正面竞争，而是把四个窄而深的差异化点全部做满：

1. **中文潦草 / 公式手写识别（本地、隐私）** — 配置一个本地 VLM（`PASSPAPER_RECOGNIZER_ENDPOINT`，如 ollama / llama.cpp / vLLM 的 OpenAI 兼容端点）后，递纸会在把图片交给 Agent 前，先转成结构化**文本 / LaTeX**。未配置时**自动回退**到「Agent 直接看图」——核心体验零依赖、不降级。详见 [docs/RECOGNITION.md](docs/RECOGNITION.md)。
2. **25ms 级低延迟跨设备接力** — 平板落笔即增量渲染到内存画布，取图 = 读缓存（实测 ~25ms）；WebSocket 断线时笔画本地缓存、重连自动批量补发。手写从平板到 AI 视野几乎无感。
3. **手写会话可随项目回溯** — 每一笔都落盘为 JSONL（`~/.passpaper/sessions/`）。关掉标签页、重启机器、`git checkout` 旧会话——墨迹都还在，还能导出 Markdown / Excalidraw（在 Excalidraw / tldraw 里回放编辑）。这是本赛道的独有特性（多数工具「关闭即清空」或只存内存）。
4. **通用 MCP + 本地优先（不锁客户端）** — 极薄 MCP shim 同时支持 **Claude Code** 和 **Codex**；数据只走你自己的机器和局域网，无账号、无云、无出站调用。借鉴来源逐条署名见 [REFERENCES.md](REFERENCES.md)。

### 为什么这样设计（daemon + shim 双层）

| 痛点 | 解法 |
|------|---------|
| AI 客户端里 MCP 加载慢/超时 | shim 纯标准库、**<100ms 完成握手**；重活全在 daemon |
| 连接不稳定 | daemon 常驻、独立于客户端生命周期；日志写文件不写管道；平板断线笔画本地缓存、重连自动补发 |
| 传输慢 | 笔画**到达即增量渲染**，取图 = 读缓存（实测 ~25ms）；图片自动裁切+限制 1568px+调色板 PNG |
| 每次用每次扫码 | **持久配对码**：平板上存书签，点开就写，永远有效（`passpaper rotate-token` 可轮换） |
| 客户端重启后僵尸进程占端口 | shim 在 stdin 关闭时立即退出；daemon 用 PID 文件管理，优雅关机先存盘 |
| 想用 Codex | 同一 shim，`passpaper setup` 同时注册 Claude Code + Codex；`save_snapshot` 提供文件兜底 |

### 快速开始（Windows）

1. 双击 `start.bat`（自动检测 Python、装依赖、注册、启动 daemon）
2. 打开 Claude Code 或 Codex，说 **"我要用递纸"**
3. 在平板上打开它给你的链接（Chrome），**存成书签**
4. 写字，然后对 AI 说 **"看看我写的"**

以后每次用：打开书签直接写。daemon 没跑的话 shim 会自动拉起。

#### 手动命令

```bash
python src/passpaper/cli.py setup      # 一次性：依赖 + 运行时包 + 注册 CC/Codex
python src/passpaper/cli.py start      # 启动 daemon（后台常驻）
python src/passpaper/cli.py status     # 健康状态 / 笔画数 / 平板数 / 链接
python src/passpaper/cli.py stop       # 优雅停止（先存盘）
python src/passpaper/cli.py doctor     # 环境诊断
python src/passpaper/cli.py rotate-token  # 配对码泄露时轮换
```

可选开机自启：`python src/passpaper/cli.py setup --autostart`

### MCP 工具

| 工具 | 用途 |
|------|------|
| `get_connection_info` | 平板链接 + 二维码（AI 首次必调） |
| `get_handwriting` | 当前手写内容（PNG，自动裁切/缩放） |
| `get_handwriting_status` | 笔画数/修订号/有无新内容（轻量） |
| `clear_canvas` | 清空画布 |
| `save_snapshot` | 存 PNG 到磁盘返回路径（无法接收 MCP 图片的客户端走这里） |
| `list_sessions` | 列出已录制手写会话（笔画数/时间） |
| `start_session` | 开新会话，旧会话保留可回溯 |
| `export_session` | 导出会话为 md / jsonl / json / excalidraw，可随项目 Git 提交 |
| `recognize_handwriting` | 调用本地 VLM 识别中文/公式（未配置则回退到 Agent 视觉） |

### 深入阅读

- [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md) — daemon + shim 双层架构、数据流、延迟与鉴权细节
- [docs/RECOGNITION.md](docs/RECOGNITION.md) — 本地中文/公式识别端点配置 + 推荐模型组合
- [docs/ACCEPTANCE_TEST_PLAN.md](docs/ACCEPTANCE_TEST_PLAN.md) — 真机验收清单（怎么测、看什么）

### 依赖

Python ≥ 3.10，`websockets` `Pillow` `qrcode`（shim 本身零依赖，纯标准库）。

### 测试

```bash
python scripts/e2e_test.py
# 26 项检查：shim 冷握手速度、daemon 自动拉起、平板 WS、取图延迟、
# 6 万点渲染性能、离线批量补发、优雅关机等
```

### 设计要点

- **坐标系**：平板端把可视区域等比映射到 2048×1536 规范坐标（letterbox），
  所见即所得，与设备方向/缩放无关
- **橡皮擦**：白墨覆盖渲染（视觉等同真擦除），擦除笔迹不参与自动裁切
- **安全**：128-bit 持久配对码，WS/HTTP 全部校验；仅局域网监听
- **运行时包**：`setup` 把 daemon/shim 复制到 `~/.passpaper/`（纯 ASCII 路径），
  客户端配置指向那里——项目在中文路径下也不会踩 spawn 编码坑
- **环境变量**：`PASSPAPER_HOME` 可改数据目录（测试/便携安装用）

### 路线图

**已发布（v1.0.0）**
- [x] 常驻 daemon + 极薄 MCP shim（实时、稳定、私密）
- [x] 持久配对 / 离线补发 / 增量渲染（~25ms 取图、MCP 握手 <100ms）
- [x] 手写会话录制 + 多格式导出（md / jsonl / json / excalidraw）
- [x] 可插拔中文 / 公式识别管线（本地 VLM，无模型时回退）

**进行中 / 下一步**
- [ ] 真机验收（平板 + Claude Code / Codex 实跑）
- [ ] PyPI 发布 + MCP 市场提交（`pip install passpaper-mcp`）
- [ ] Cloudflare Tunnel 模式（户外 / 跨网络）
- [ ] 真·语义擦除（笔画级删除）
- [ ] 系统托盘 App 形态
- [ ] 更多本地识别后端（PaddleOCR-VL / GLM-OCR 开箱集成）

### 故障排除

- `passpaper doctor` — 一键诊断 Python / 依赖 / 运行时包 / MCP 注册 / 配对令牌。
- daemon 没起来？看 `~/.passpaper/daemon.log` 与 `~/.passpaper/daemon.spawn.log`。
- 端口 8765 被占？`passpaper stop` 后再 `passpaper start`；或改 `PORT`（需同步改 canvas）。
- 平板连不上：确认与电脑同一 WiFi；用 `passpaper url` 重新获取链接；公司/校园网可能隔离设备——换手机热点测试。
- 识别没反应：未配置 `PASSPAPER_RECOGNIZER_ENDPOINT` 时走「Agent 直接看图」回退，属正常；配置方法见 [docs/RECOGNITION.md](docs/RECOGNITION.md)。

### 贡献

欢迎 Issue / PR。开发环境、测试与两条硬性规则见 [CONTRIBUTING.md](CONTRIBUTING.md)。安全漏洞请私下报告，见 [SECURITY.md](SECURITY.md)。

### 参考与灵感来源

递纸的设计受到多个开源项目的启发，逐条署名见 [REFERENCES.md](REFERENCES.md)。

### License

[MIT](LICENSE) — Copyright (c) 2026 B.Han.

---

## English

**Write formulas/sketches on your tablet — the AI calls its own tools and comes to look.**

Not "take a screenshot and send it to the AI" — you write, and the AI actively reads through [MCP](https://modelcontextprotocol.io) tools.
Supports **Claude Code** and **Codex CLI**.

> **Status**: v1.0.0 early release. Core features are implemented and verified at the code level (`py_compile` / import / recognition parsing), but not yet validated in large-scale real-device environments. Please report issues and use cases via GitHub Issues.

> **Positioning**: PassPaper does not build an "AI whiteboard" to compete head-on with existing whiteboard / drawing tools. Instead, it focuses on a narrow but deep scenario — **feeding tablet handwriting to your local AI coding assistant in real time, reliably and privately** — differentiated by *messy-Chinese / formula handwriting recognition*, *~25ms low-latency image capture*, *handwriting sessions traceable per project*, and *generic MCP (client-agnostic)*. The design draws inspiration from several open-source projects, credited one by one in [REFERENCES.md](REFERENCES.md).

```
[Tablet Chrome]                   [Computer]
 handwriting canvas ──WebSocket──▶ passpaper daemon (resident)
                              │   strokes rendered to in-memory canvas on arrival
  Claude Code / Codex ◀─MCP stdio─ mcp_shim (ultra-thin, <100ms handshake)
                              └──── localhost HTTP ────┘
```

### Four differentiators (why PassPaper instead of alternatives)

PassPaper does not build an "AI whiteboard" to compete head-on with mature whiteboard / drawing tools; instead it nails four narrow, deep differentiators:

1. **Messy-Chinese / formula handwriting recognition (local & private)** — After you configure a local VLM (`PASSPAPER_RECOGNIZER_ENDPOINT`, e.g. an OpenAI-compatible endpoint from ollama / llama.cpp / vLLM), PassPaper converts the image into structured **text / LaTeX** before handing it to the agent. Without a configured endpoint it **automatically falls back** to "let the agent look at the image directly" — the core experience has zero hard dependencies and never degrades. See [docs/RECOGNITION.md](docs/RECOGNITION.md).
2. **~25ms low-latency cross-device relay** — Strokes are incrementally rendered to an in-memory canvas as they land on the tablet; capturing an image = reading a cache (~25ms measured). On WebSocket disconnect, strokes are cached locally and bulk re-sent on reconnect. Handwriting travels from tablet to the AI's view almost imperceptibly.
3. **Handwriting sessions traceable per project** — Every stroke is persisted to JSONL (`~/.passpaper/sessions/`). Close the tab, reboot the machine, `git checkout` an old session — the ink is still there, and sessions can be exported as Markdown / Excalidraw (replay and edit in Excalidraw / tldraw). This is unique in this niche (most tools "clear on close" or keep only in-memory state).
4. **Generic MCP + local-first (client-agnostic)** — An ultra-thin MCP shim supports both **Claude Code** and **Codex**; data travels only over your own machine and LAN — no account, no cloud, no outbound calls. Sources of inspiration are credited one by one in [REFERENCES.md](REFERENCES.md).

### Why this design (daemon + shim two layers)

| Pain point | Solution |
|------|---------|
| MCP loads slowly / times out inside AI clients | shim is pure stdlib, **handshake completes in <100ms**; all heavy work lives in the daemon |
| Unstable connections | daemon is resident and independent of the client lifecycle; logs go to files, not pipes; tablet strokes cached locally on disconnect, bulk re-sent on reconnect |
| Slow transfer | strokes are **incrementally rendered on arrival**; capture = reading a cache (~25ms measured); images auto-cropped + capped at 1568px + palette PNG |
| Re-scanning a QR code every time | **Persistent pairing code**: save a bookmark on the tablet, tap to write, valid forever (`passpaper rotate-token` to rotate) |
| Zombie processes holding the port after client restart | shim exits immediately when stdin closes; daemon is managed via a PID file; graceful shutdown persists data first |
| Want to use Codex | Same shim — `passpaper setup` registers both Claude Code and Codex; `save_snapshot` provides a file-based fallback |

### Quick start (Windows)

1. Double-click `start.bat` (auto-detects Python, installs dependencies, registers, starts the daemon)
2. Open Claude Code or Codex and say **"I want to use PassPaper"**
3. Open the link it gives you on your tablet (Chrome) and **save it as a bookmark**
4. Write, then tell the AI **"look at what I wrote"**

From then on: open the bookmark and just write. If the daemon isn't running, the shim starts it automatically.

#### Manual commands

```bash
python src/passpaper/cli.py setup      # one-time: dependencies + runtime package + register CC/Codex
python src/passpaper/cli.py start      # start the daemon (resident in background)
python src/passpaper/cli.py status     # health / stroke count / tablet count / links
python src/passpaper/cli.py stop       # graceful stop (persists data first)
python src/passpaper/cli.py doctor     # environment diagnostics
python src/passpaper/cli.py rotate-token  # rotate when the pairing code leaks
```

Optional autostart at boot: `python src/passpaper/cli.py setup --autostart`

### MCP tools

| Tool | Purpose |
|------|------|
| `get_connection_info` | Tablet link + QR code (the AI must call this first) |
| `get_handwriting` | Current handwriting content (PNG, auto-cropped / scaled) |
| `get_handwriting_status` | Stroke count / revision / whether new content exists (lightweight) |
| `clear_canvas` | Clear the canvas |
| `save_snapshot` | Save PNG to disk and return the path (for clients that cannot receive MCP images) |
| `list_sessions` | List recorded handwriting sessions (stroke count / time) |
| `start_session` | Start a new session; old sessions are kept for traceability |
| `export_session` | Export a session as md / jsonl / json / excalidraw, committable with the project's Git |
| `recognize_handwriting` | Call the local VLM to recognize Chinese / formulas (falls back to agent vision if unconfigured) |

### Further reading

- [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md) — daemon + shim two-layer architecture, data flow, latency and auth details
- [docs/RECOGNITION.md](docs/RECOGNITION.md) — local Chinese / formula recognition endpoint configuration + recommended model combinations
- [docs/ACCEPTANCE_TEST_PLAN.md](docs/ACCEPTANCE_TEST_PLAN.md) — real-device acceptance checklist (what to test, what to look for)

### Dependencies

Python ≥ 3.10, `websockets` `Pillow` `qrcode` (the shim itself has zero dependencies — pure stdlib).

### Testing

```bash
python scripts/e2e_test.py
# 26 checks: shim cold-handshake speed, daemon auto-spawn, tablet WS, capture latency,
# 60k-point rendering performance, offline bulk re-send, graceful shutdown, etc.
```

### Design notes

- **Coordinate system**: the tablet maps the visible area proportionally onto 2048×1536 canonical coordinates (letterbox) — WYSIWYG, independent of device orientation / zoom
- **Eraser**: white-ink overlay rendering (visually equivalent to a real erase); erased strokes don't participate in auto-cropping
- **Security**: 128-bit persistent pairing code, verified on WS/HTTP; listens on LAN only
- **Runtime package**: `setup` copies daemon/shim to `~/.passpaper/` (pure ASCII path); client config points there — no spawn encoding issues even when the project lives under a non-ASCII path
- **Environment variable**: `PASSPAPER_HOME` changes the data directory (for testing / portable installs)

### Roadmap

**Shipped (v1.0.0)**
- [x] Resident daemon + ultra-thin MCP shim (real-time, stable, private)
- [x] Persistent pairing / offline re-send / incremental rendering (~25ms capture, MCP handshake <100ms)
- [x] Handwriting session recording + multi-format export (md / jsonl / json / excalidraw)
- [x] Pluggable Chinese / formula recognition pipeline (local VLM, falls back when no model)

**In progress / next**
- [ ] Real-device acceptance (tablet + Claude Code / Codex in actual use)
- [ ] PyPI release + MCP marketplace submission (`pip install passpaper-mcp`)
- [ ] Cloudflare Tunnel mode (outdoor / cross-network)
- [ ] True semantic erasing (stroke-level deletion)
- [ ] System tray app
- [ ] More local recognition backends (PaddleOCR-VL / GLM-OCR out-of-the-box integration)

### Troubleshooting

- `passpaper doctor` — one-shot diagnostics for Python / dependencies / runtime package / MCP registration / pairing token.
- Daemon not starting? Check `~/.passpaper/daemon.log` and `~/.passpaper/daemon.spawn.log`.
- Port 8765 taken? Run `passpaper stop` then `passpaper start`; or change `PORT` (must also update the canvas).
- Tablet can't connect: make sure it's on the same WiFi as the computer; re-fetch the link with `passpaper url`; corporate / campus networks may isolate devices — try a phone hotspot.
- Recognition not responding: without `PASSPAPER_RECOGNIZER_ENDPOINT` configured it falls back to "agent looks at the image directly", which is expected; configuration see [docs/RECOGNITION.md](docs/RECOGNITION.md).

### Contributing

Issues and PRs welcome. Dev environment, tests and the two hard rules: see [CONTRIBUTING.md](CONTRIBUTING.md). Report security vulnerabilities privately, see [SECURITY.md](SECURITY.md).

### References & inspiration

PassPaper's design is inspired by several open-source projects, credited one by one in [REFERENCES.md](REFERENCES.md).

### License

[MIT](LICENSE) — Copyright (c) 2026 B.Han.
