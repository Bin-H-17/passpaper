# 真机验收测试计划（Acceptance Test Plan）

> 目的：在**真实设备**上跑一遍递纸 PassPaper v1.0.0，验证四大差异化卖点 + 核心体验，并把结果反馈回来。
> 谁来跑：你（用户）在本地 Windows + 平板（如 Redmi Pad Pro）+ Claude Code / Codex 上实操。
> 怎么反馈：跑完把现象/问题/效果按文末模板贴给 Claude Code，由代理整理可改进点。
> 为什么不在沙箱跑：沙箱里中文路径建目录会挂；且需要真实平板 + 真实 AI 客户端 + 真实手写，沙箱无法模拟。

---

## 0. 前置条件

- Windows 10/11，Python ≥ 3.10（建议用项目绑定的 managed 运行时或系统 Python 3.10+）。
- 平板与电脑在**同一 WiFi**（跨设备接力必须）。
- 依赖：`websockets` `Pillow` `qrcode`（`passpaper setup` 会自动装）。
- 防火墙：首次需**管理员终端**跑一次
  `netsh advfirewall firewall add rule name="PassPaper" dir=in action=allow protocol=TCP localport=8765`
  （`passpaper doctor` 会提示是否已有该规则）。
- 可选（卖点 1 需要）：本地 VLM。最省事是用 [ollama](https://ollama.com) 跑 `ollama pull qwen2.5-vl:7b`（详见 `docs/RECOGNITION.md`）。

---

## 1. 快速启动

```bash
python src/passpaper/cli.py setup      # 依赖 + 运行时包 + 注册 CC/Codex（看提示处理防火墙）
python src/passpaper/cli.py start      # 后台常驻 daemon
python src/passpaper/cli.py status     # 确认 daemon up、URL、strokes=0
```

打开 Claude Code（或 Codex），说 **「我要用递纸」**；在平板上打开它给的链接（Chrome），**存成书签**。

---

## 2. 测试场景

### 场景 A — 核心体验（必过）
**目的**：手写 → AI 真能看到。
- 步骤：平板上写「你好 world」几个字 → 对 Claude Code 说 **「看看我写的」**。
- 预期：Claude Code 调用 `get_handwriting`，正确描述/转录你写的内容；`status` 里 `strokes` > 0。
- 判定：✅ 能读到且内容基本对；❌ 读不到 / 空白 / 连接失败。
- 额外：试 `clear_canvas`（说「清空画布」）——画面应清空，`status` strokes 归零。

### 场景 B — 卖点 1：中文潦草 / 公式识别（本地、隐私）
**目的**：验证可插拔本地 VLM 管线 + 无模型时的优雅回退。
- **B1 回退路径**（不配模型）：`passpaper recognize` → 应显示 `engine: agent_vision` + 一段说明，证明核心不依赖模型。
- **B2 本地模型路径**：
  1. `ollama pull qwen2.5-vl:7b` 并起服务；设
     `set PASSPAPER_RECOGNIZER_ENDPOINT=http://127.0.0.1:11434/v1`
     `set PASSPAPER_RECOGNIZER_MODEL=qwen2.5-vl:7b`（或写进 `start.bat` / 系统环境变量后重启 daemon）。
  2. 平板上写**潦草中文 + 一个公式**（如 `E=mc²`、`∫x dx`、`∑`）。
  3. 跑 `passpaper recognize` → 应看到 `engine: local_vlm`、`text`、`latex`。
  4. 或在 Claude Code 说「识别我刚写的」→ 调 `recognize_handwriting`。
- 判定：✅ 中文/公式被转成可读文本+LaTeX；❌ 报错、超时、或模型没起来。
- 记录：识别**准不准**（潦草中文、公式分别打分），模型推理**耗时**。

### 场景 C — 卖点 2：25ms 级低延迟跨设备接力
**目的**：平板落笔到 AI 视野几乎无感；断线能恢复。
- **C1 延迟**：平板上快速连写，`python scripts/e2e_test.py` 里有取图延迟项（~25ms 量级）；也可手动：写一笔立刻让 Claude 读，体感应「即时」。
- **C2 断线重连**：写字过程中**关平板 WiFi 再开**（或杀掉平板页面）→ 重连后之前没发出的笔画应**自动批量补发**，不丢墨。
- 判定：✅ 体感即时、断网期间笔画不丢；❌ 明显卡顿、或重连后缺笔。

### 场景 D — 卖点 3：手写会话可随项目回溯
**目的**：手写成为可版本化资产。
- 步骤：
  1. 写一页内容 → 点画布上 **「保存会话」**（或 Claude 说「开新会话」）。
  2. 再写一页 → 点 **「新建会话」**（旧会话保留）。
  3. `passpaper sessions list` 应看到 ≥2 个会话；`passpaper sessions show <id>` 打印 Markdown；`passpaper sessions export <id> --format excalidraw --out s.excalidraw` 导出。
  4. 把导出的 `.excalidraw` 拖进 Excalidraw / tldraw 网站，确认能回放/编辑。
  5. （进阶）把 `~/.passpaper/sessions/*.jsonl` 放进某项目 git 仓库，`git checkout` 旧版本后 `passpaper sessions show` 仍能还原。
- 判定：✅ 多会话隔离、可导出、可外部回放、可 git 回溯；❌ 会话混淆、导出打不开、或重启用丢。

### 场景 E — 卖点 4：通用 MCP + 本地优先（不锁客户端）
**目的**：Claude Code 与 Codex 都能用；无云、无出站。
- **E1 双客户端**：分别用 Claude Code 和 Codex 跑场景 A，确认两者都能注册并调用。
- **E2 本地优先**：断网（仅平板与电脑同 WiFi，但不连外网）下仍能 `get_handwriting` / `recognize_handwriting`（回退 Agent 视觉时也不出站）。确认无外部 API 调用。
- 判定：✅ 两个客户端均可用、纯局域网可用；❌ 某个客户端连不上、或被迫联网。

---

## 3. 自动化测试（在真机跑，补沙箱缺口）

```bash
python scripts/e2e_test.py                      # 26 项：握手速度/自动拉起/WS/取图延迟/6万点渲染/离线补发/优雅关机等
python tests/test_recorder_recognition.py       # 录制+识别契约：往返/新会话隔离/回退/latex 解析
python src/passpaper/cli.py doctor              # 环境诊断（依赖、bundle、MCP 注册、token）
```

预期：e2e 全绿；smoke 打印 `ALL PASSPAPER v1.0.0 SMOKE TESTS PASSED`；doctor 无 `[FAIL]`。

---

## 4. 反馈模板（贴给 Claude Code）

把下面内容填好发回来即可，代理会据此修问题 / 排改进优先级：

```
【设备/环境】Windows 版本、Python 版本、平板型号、AI 客户端(CC/Codex)、是否装了本地 VLM(模型名)
【跑通的】A/B/C/D/E 哪些 ✅，哪条命令/话术最顺手
【问题/报错】（贴关键报错或现象）
  - 场景X：……
  - 场景Y：……
【效果/体感】（主观）
  - 识别准确率（中文/公式）：高/中/低，举例……
  - 延迟体感：即时/可接受/偏慢
  - 断线恢复：丢笔/不丢
【想改进的点】……
【e2e/smoke 输出】（可选，贴末尾）
```

---

## 5. 验收通过标准（建议）

- A、E 必过；B/C/D 至少各跑通主路径（B 的本地模型路径若没装 VLM，至少 B1 回退要过）。
- 自动化 e2e 与 smoke 全绿。
- 无阻断性问题（连接失败、丢笔、崩溃）。

验收后下一步：定稿用户名/仓库名 → 跑 `scripts/publish_to_github_gitee.sh` 上传 → PyPI / MCP 市场。
