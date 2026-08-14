# 手写识别模块（recognition）端点说明 & 推荐模型

> 配套代码：`src/passpaper/recognition.py`
> 配套命令：`passpaper recognize [--image <png>]`
> 配套 MCP 工具：`recognize_handwriting`

---

## 1. 它解决什么问题

递纸默认让 AI 客户端（Claude Code / Codex）**直接读取手写 PNG**（Agent 自带多模态视觉），这条路零依赖、永远可用。

但在两个场景里，先在本地把图转成**结构化文本 / LaTeX** 更好：

- **中文潦草 / 数学公式**：Agent 视觉对潦草中文和复杂公式经常读错；本地 VLM 可以专门优化，给出可复制的文本与 LaTeX。
- **可回溯会话**：识别结果会随会话 JSONL 一起落盘，回放时连「转录文字」都有。

所以递纸做了**可插拔**识别：配了本地模型就走本地 VLM，没配就优雅回退到 Agent 视觉。**核心体验不依赖任何模型**。

---

## 2. 快速配置（环境变量）

只需一个端点即可开启本地识别，其余可选：

| 变量 | 必填 | 说明 |
|------|------|------|
| `PASSPAPER_RECOGNIZER_ENDPOINT` | 是 | 本地 OpenAI 兼容的 `/v1` 端点，例如 `http://127.0.0.1:11434/v1`（ollama）、`http://127.0.0.1:8080/v1`（llama.cpp）、`http://127.0.0.1:8000/v1`（vLLM / LM Studio） |
| `PASSPAPER_RECOGNIZER_MODEL` | 否 | 模型名，例如 `qwen2.5-vl:7b`。空时识别后端用 `"local"` 占位 |
| `PASSPAPER_RECOGNIZER_KEY` | 否 | 若端点需要 Bearer 鉴权则填，否则留空 |

```bash
# 例：用 ollama 跑 Qwen2.5-VL
ollama pull qwen2.5-vl:7b
export PASSPAPER_RECOGNIZER_ENDPOINT=http://127.0.0.1:11434/v1
export PASSPAPER_RECOGNIZER_MODEL=qwen2.5-vl:7b

# 然后正常启动；识别会自动走本地 VLM
passpaper start

# 或单独测识别（无需 AI 客户端）：把当前画布截图送识别
passpaper recognize
# 或对一张已有的图测试
passpaper recognize --image ./my_handwriting.png
```

> Windows 下建议把 `export` 换成**用户环境变量（系统设置 → 环境变量）**或写进 `start.bat`，避免每次开终端都要设。

---

## 3. 端点协议（OpenAI 兼容 /chat/completions）

递纸用**纯标准库 `urllib`** 调用，不引入任何 SDK。它向 `<ENDPOINT>/chat/completions` 发送如下请求：

**请求体（POST, `application/json`）**
```json
{
  "model": "<PASSPAPER_RECOGNIZER_MODEL 或 \"local\">",
  "temperature": 0.1,
  "messages": [
    {
      "role": "user",
      "content": [
        { "type": "text",
          "text": "请识别这张手写图片中的文字与公式。用中文输出可阅读文本；公式请用 LaTeX 表示（行内用 $...$，独立公式用 $$...$$）。不要编造看不清的内容。" },
        { "type": "image_url",
          "image_url": { "url": "data:image/png;base64,<PNG_BASE64>" } }
      ]
    }
  ]
}
```

**期望响应（取第一个 choice 的 message.content）**
```json
{
  "choices": [
    { "message": { "content": "递纸 PassPaper $$E=mc^2$$ 写得不错" } }
  ]
}
```

**递纸如何解析返回**：从 `content` 中抽取：
- 所有 `$$...$$`（独立公式）与 `$...$`（行内公式）→ 合并进 `latex` 字段；
- 去掉公式后的剩余文本 → `text` 字段；
- 若调用失败（端点没起 / 超时 / 非 200），返回一个**软失败结果**（`engine="local_vlm"`，`note` 写明原因），**绝不抛出到热路径**，Agent 端会看到说明文字而不是崩溃。

> 想换提示词？`LocalVLMRecognizer(endpoint, model, prompt=...)` 的 `prompt` 参数可调；若要固化为项目默认，可在 `recognition.py` 里改默认值。

---

## 4. 推荐模型组合（2026 年常用方向）

> 模型版本迭代很快，下表是**方向性推荐**，落地前请确认各项目前的最新小版本号。本地模型走「OpenAI 兼容端点」，云模型走「Agent 视觉回退」路径（即不配 `PASSPAPER_RECOGNIZER_ENDPOINT`，让 Claude/GPT/Gemini 直接看图）。

### 4.1 本地 VLM（隐私、零出站、可离线）

| 模型 | 典型端点 | 适合 | 备注 |
|------|---------|------|------|
| **Qwen2.5-VL（7B / 72B）** | ollama `qwen2.5-vl:7b` | 中文 + 公式综合最强候选；7B 可在消费级显卡跑 | 中文场景首选推荐 |
| **MiniCPM-V 2.6 / 3** | ollama / llama.cpp | 端侧小模型，显存友好 | 平板/笔记本本地跑很合适 |
| **InternVL2.5 / 3** | vLLM / llama.cpp | 高精度，公式识别强 | 偏重，需较好显卡 |
| **GLM-4V**（智谱） | 本地或 GLM 开放平台 | 中文原生友好 | 也可走云端 API |
| **Llama-4-Scout / Pixtral / Gemma-3** | llama.cpp / vLLM | 英文/多语通用 | 中文公式略逊于 Qwen 系 |
| **PaddleOCR-VL**（百度） | 独立服务 | 纯 OCR 取向、印刷/手写 mixed |  formula 能力看具体版本 |

### 4.2 云端 Agent 视觉（无需本地模型，回退路径）

| Agent / 模型 | 何时用 | 说明 |
|------|--------|------|
| **Claude（Opus/Sonnet）** | 默认 `recognize_handwriting` 回退 / 直接 `get_handwriting` | 多模态强，潦草中文尚可 |
| **GPT-4.1 / 4o** | Codex 端 | 公式识别稳 |
| **Gemini 2.x** | 多模态长上下文 | 整页草图友好 |
| **GLM-4V / 阶跃/千问 云** | 中文优先 | 国内低延迟 |

### 4.3 推荐组合（按你的机器）

| 场景 | 组合 | 配置 |
|------|------|------|
| **轻量本机（无独显 / 小显存）** | ollama + `qwen2.5-vl:7b`（或 MiniCPM-V） | `ENDPOINT=http://127.0.0.1:11434/v1` |
| **有独显、要精度** | vLLM + `Qwen2.5-VL-72B` 或 `InternVL2.5` | `ENDPOINT=http://127.0.0.1:8000/v1` |
| **不想装模型 / 走云端** | 不配端点，直接用 Claude/GPT 视觉 | 留空 `PASSPAPER_RECOGNIZER_ENDPOINT` |
| **公式重度用户** | 本地 Qwen2.5-VL + 云端 Claude 双保险 | 本地失败时自然回退 Agent 视觉 |

---

## 5. 怎么验证识别在工作

1. 启动模型端点（如 `ollama run qwen2.5-vl:7b` 会顺带起服务）。
2. 设好 `PASSPAPER_RECOGNIZER_ENDPOINT` / `MODEL`，`passpaper start`。
3. 平板上写几个**潦草中文字 + 一个公式**（如 `E=mc²` 或 `∫x dx`）。
4. 跑 `passpaper recognize` —— 应看到 `engine: local_vlm` 和解析出的 `text` / `latex`。
5. 或在 Claude Code 里说「识别我刚写的」，它会调 `recognize_handwriting` 工具。
6. **没配模型时**：`passpaper recognize` 会显示 `engine: agent_vision` 和一段说明，证明回退链路正常、核心体验不受影响。

---

## 6. 隐私与边界

- 识别图片**只发往你配置的本地端点**（默认 127.0.0.1）。不要把 `ENDPOINT` 指向你不控制的地址，否则等于把手写内容发出本机。
- 不配置 `PASSPAPER_RECOGNIZER_ENDPOINT` 时，递纸**完全不调用任何识别服务**，直接让 AI 客户端看图 —— 零出站。
- 识别结果是「尽力而为」：模型看不清的内容请人工校对，避免把幻觉当真。
