# 递纸 PassPaper

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

## 四大差异化卖点（为什么用递纸而不是别的）

递纸不做一个「AI 白板」去和成熟白板 / 绘图工具正面竞争，而是把四个窄而深的差异化点全部做满：

1. **中文潦草 / 公式手写识别（本地、隐私）** — 配置一个本地 VLM（`PASSPAPER_RECOGNIZER_ENDPOINT`，如 ollama / llama.cpp / vLLM 的 OpenAI 兼容端点）后，递纸会在把图片交给 Agent 前，先转成结构化**文本 / LaTeX**。未配置时**自动回退**到「Agent 直接看图」——核心体验零依赖、不降级。详见 [docs/RECOGNITION.md](docs/RECOGNITION.md)。
2. **25ms 级低延迟跨设备接力** — 平板落笔即增量渲染到内存画布，取图 = 读缓存（实测 ~25ms）；WebSocket 断线时笔画本地缓存、重连自动批量补发。手写从平板到 AI 视野几乎无感。
3. **手写会话可随项目回溯** — 每一笔都落盘为 JSONL（`~/.passpaper/sessions/`）。关掉标签页、重启机器、`git checkout` 旧会话——墨迹都还在，还能导出 Markdown / Excalidraw（在 Excalidraw / tldraw 里回放编辑）。这是本赛道的独有特性（多数工具「关闭即清空」或只存内存）。
4. **通用 MCP + 本地优先（不锁客户端）** — 极薄 MCP shim 同时支持 **Claude Code** 和 **Codex**；数据只走你自己的机器和局域网，无账号、无云、无出站调用。借鉴来源逐条署名见 [REFERENCES.md](REFERENCES.md)。

## 为什么这样设计（daemon + shim 双层）

| 痛点 | 解法 |
|------|---------|
| AI 客户端里 MCP 加载慢/超时 | shim 纯标准库、**<100ms 完成握手**；重活全在 daemon |
| 连接不稳定 | daemon 常驻、独立于客户端生命周期；日志写文件不写管道；平板断线笔画本地缓存、重连自动补发 |
| 传输慢 | 笔画**到达即增量渲染**，取图 = 读缓存（实测 ~25ms）；图片自动裁切+限制 1568px+调色板 PNG |
| 每次用每次扫码 | **持久配对码**：平板上存书签，点开就写，永远有效（`passpaper rotate-token` 可轮换） |
| 客户端重启后僵尸进程占端口 | shim 在 stdin 关闭时立即退出；daemon 用 PID 文件管理，优雅关机先存盘 |
| 想用 Codex | 同一 shim，`passpaper setup` 同时注册 Claude Code + Codex；`save_snapshot` 提供文件兜底 |

## 快速开始（Windows）

1. 双击 `start.bat`（自动检测 Python、装依赖、注册、启动 daemon）
2. 打开 Claude Code 或 Codex，说 **"我要用递纸"**
3. 在平板上打开它给你的链接（Chrome），**存成书签**
4. 写字，然后对 AI 说 **"看看我写的"**

以后每次用：打开书签直接写。daemon 没跑的话 shim 会自动拉起。

### 手动命令

```bash
python src/passpaper/cli.py setup      # 一次性：依赖 + 运行时包 + 注册 CC/Codex
python src/passpaper/cli.py start      # 启动 daemon（后台常驻）
python src/passpaper/cli.py status     # 健康状态 / 笔画数 / 平板数 / 链接
python src/passpaper/cli.py stop       # 优雅停止（先存盘）
python src/passpaper/cli.py doctor     # 环境诊断
python src/passpaper/cli.py rotate-token  # 配对码泄露时轮换
```

可选开机自启：`python src/passpaper/cli.py setup --autostart`

## MCP 工具

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

## 深入阅读

- [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md) — daemon + shim 双层架构、数据流、延迟与鉴权细节
- [docs/RECOGNITION.md](docs/RECOGNITION.md) — 本地中文/公式识别端点配置 + 推荐模型组合
- [docs/ACCEPTANCE_TEST_PLAN.md](docs/ACCEPTANCE_TEST_PLAN.md) — 真机验收清单（怎么测、看什么）

## 依赖

Python ≥ 3.10，`websockets` `Pillow` `qrcode`（shim 本身零依赖，纯标准库）。

## 测试

```bash
python scripts/e2e_test.py
# 26 项检查：shim 冷握手速度、daemon 自动拉起、平板 WS、取图延迟、
# 6 万点渲染性能、离线批量补发、优雅关机等
```

## 设计要点

- **坐标系**：平板端把可视区域等比映射到 2048×1536 规范坐标（letterbox），
  所见即所得，与设备方向/缩放无关
- **橡皮擦**：白墨覆盖渲染（视觉等同真擦除），擦除笔迹不参与自动裁切
- **安全**：128-bit 持久配对码，WS/HTTP 全部校验；仅局域网监听
- **运行时包**：`setup` 把 daemon/shim 复制到 `~/.passpaper/`（纯 ASCII 路径），
  客户端配置指向那里——项目在中文路径下也不会踩 spawn 编码坑
- **环境变量**：`PASSPAPER_HOME` 可改数据目录（测试/便携安装用）

## 路线图

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

## 故障排除

- `passpaper doctor` — 一键诊断 Python / 依赖 / 运行时包 / MCP 注册 / 配对令牌。
- daemon 没起来？看 `~/.passpaper/daemon.log` 与 `~/.passpaper/daemon.spawn.log`。
- 端口 8765 被占？`passpaper stop` 后再 `passpaper start`；或改 `PORT`（需同步改 canvas）。
- 平板连不上：确认与电脑同一 WiFi；用 `passpaper url` 重新获取链接；公司/校园网可能隔离设备——换手机热点测试。
- 识别没反应：未配置 `PASSPAPER_RECOGNIZER_ENDPOINT` 时走「Agent 直接看图」回退，属正常；配置方法见 [docs/RECOGNITION.md](docs/RECOGNITION.md)。

## 贡献

欢迎 Issue / PR。开发环境、测试与两条硬性规则见 [CONTRIBUTING.md](CONTRIBUTING.md)。安全漏洞请私下报告，见 [SECURITY.md](SECURITY.md)。

## 参考与灵感来源

递纸的设计受到多个开源项目的启发，逐条署名见 [REFERENCES.md](REFERENCES.md)。

## License

[MIT](LICENSE) — Copyright (c) 2026 B.Han.
