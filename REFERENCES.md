# 参考与灵感来源 · References & Inspirations

**重要声明（先说结论）**：PassPaper（递纸）是**原创实现**，以 **MIT** 许可证发布。我们**没有包含、修改或分发任何第三方项目的源代码**（已逐文件核查：`src/` 下无任何第三方版权头、许可头或嵌入代码；唯一提及竞品处是 `recorder.py` 里一条关于 mcp_excalidraw `describe` 思路的设计注释）。

因此：

- **没有法律上的署名义务。** 版权 / 许可证义务（包括 AGPL 的 Copyleft）只在「包含、修改或分发他人源代码」时才会触发。我们没用，所以不触发。
- **下面的署名是「开源社区惯例下的礼貌致谢」**，针对我们**确实参考过设计**的公开工作，而非「衍生关系」声明。我们刻意不夸大与任何项目的关系。

> 差异化定位：递纸不与下述项目在「AI 白板 / 绘图工具」赛道正面竞争，而是聚焦「平板手写 → 本地 AI 编码助手」这一窄场景，以 **中文潦草 / 公式手写识别、25ms 级低延迟取图、手写会话可随项目回溯、通用 MCP（不锁客户端）** 作为区隔。

---

## 一、真正的设计启发（我们确实参考了的）

### mcp_excalidraw — https://github.com/yctimlin/mcp_excalidraw （MIT）
- **借鉴**：`常驻 daemon + 薄驱动层（shim）` 的拆分层；`describe`（结构化文本）+ `screenshot`（渲染图）双通道，让 agent「看见并修正」自己产出的图；CLI 优先、零 API Key 的本地运行形态。
- **我们的差异**：把这套「daemon + 极薄 stdio shim」用于**人类手写输入**而非程序化绘图；取图采用**笔画到达即增量渲染**（实测 ~25ms）而非整图截图；shim 纯标准库、握手 <100ms。

### Weylus — https://github.com/H-M-H/Weylus （AGPL-3.0）
- **借鉴**：`二维码 / 书签零安装配对` 的 UX 范式——平板用浏览器即可，无需安装 App；以及「旧平板当第二屏 / 手绘板」的设备复用思路。
- **我们的差异**：递纸把「平板 → 电脑」的通道专用于手写墨迹实时喂给本地 AI agent，并在 `setup` 阶段完成**一次配对、永久有效**（`rotate-token` 可轮换），而非每次手动查 IP。

---

## 二、相关 / 竞争上下文（我们未采用其方案，仅作差异化对照）

### PenEcho — https://github.com/penecho/penecho （AGPL-3.0）
- **已知的最接近竞品**：`lasso 圈选发送`、`token 预算分级`、`512² 稀疏瓦片`省 token、多模型 source 抽象（Claude CLI / Codex CLI / 兼容 API）。
- **我们未采用上述设计**，而是以**本地优先常驻 daemon + 增量渲染** + **中文潦草 / 公式手写鲁棒识别** + **手写会话可随项目 Git 回溯** 形成差异化——后两点是 PenEcho 当前未覆盖的国产刚需。此处列出仅为「明示我们清楚它在做什么、且不重复造它」，**不构成借鉴或署名义务**。

### claude-monet-mcp — https://github.com/yahavfuchs/claude-monet-mcp （MIT，仓库当前 404）
- **SVG-first** 思路（矢量路径 / 坐标而非位图喂模型）。我们**仅将其列为后续演进方向**（矢量墨迹输出），当前未采用。

---

## 三、技术生态（行业标杆，设计上参考其理念，未引入其代码）

- **Model Context Protocol** — https://github.com/modelcontextprotocol （规范 + Python / TypeScript SDK）：递纸实现的就是 MCP server（stdio 传输）。
- **Excalidraw / tldraw / perfect-freehand / rough.js / yjs**：手绘风渲染、自由笔触、CRDT 协同的业界标杆。递纸实现的是独立的轻量增量渲染器，**未直接依赖上述库**，仅设计上参考其笔触 / 协同理念。

---

## 四、中文手写 / OCR 候选模型（未使用，仅作 POC 参考）

- **PaddleOCR** （Apache-2.0）/ **GLM-OCR** （Apache-2.0）：作为递纸「中文潦草 / 公式手写识别护城河」的候选本地模型参考，**非运行时依赖**。

---

## 五、相关生态（叙事参照，非借鉴实现）

- **draw-a-ui** — https://github.com/SawyerHood/draw-a-ui ：手绘线框 → 代码的完整闭环，与递纸互补而非竞争。

---

## 六、许可证边界（明确说明，避免误解）

- 递纸以 **MIT** 发布，允许自由集成与再分发。
- PenEcho、Weylus 采用 **AGPL-3.0**（强 copyleft）。递纸**未包含其任何源代码**，仅参考公开设计理念；因此 AGPL 的「派生 / 修改须开源」义务**对递纸不适用**。
- 本文档是**礼貌致谢 + 差异化声明**，不是许可证合规要求。若未来在递纸中**引入**上述项目的代码，将另行按对应许可证处理。
