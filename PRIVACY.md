# Privacy Policy / 隐私政策

**生效日期：2026-08-16** · Applies to PassPaper v1.0.0

## 中文

递纸 PassPaper 是**本地优先（local-first）**工具。核心原则：数据只存在于用户自己的设备和局域网。

### 收集的数据

- **手写笔画**：存储于本机 `~/.passpaper/sessions/`（JSONL）。用于会话回放与导出，不上传任何服务器。
- **配对令牌**：128 位随机令牌，存储于本机 `~/.passpaper/pairing.json`。用于平板与本机之间的认证。
- **日志**：仅写本机文件，不发送至外部。

### 不收集的数据

- 无账号、无云服务、无遥测、无广告追踪。
- 本工具不发起任何出站网络调用（识别端点由用户自行配置且默认关闭）。

### 识别（可选）

若用户配置了 `PASSPAPER_RECOGNIZER_ENDPOINT`，手写图片仅发送至**用户自己指定的**本地 VLM 端点（如 ollama / llama.cpp / vLLM）。未配置时，图片不出本机。

### 第三方

- 项目托管于 GitHub（代码公开可见）。
- MCP 信任评分徽章由 M8ven 提供（仅读取公开仓库元数据，见 <https://m8ven.ai>）。

### 联系

通过 GitHub Issues：<https://github.com/Bin-H-17/passpaper/issues>

---

## English

PassPaper is a **local-first** tool. The core principle: data lives only on the user's own device and LAN.

### Data we collect

- **Handwriting strokes**: stored locally in `~/.passpaper/sessions/` (JSONL), used for session replay and export. Never uploaded.
- **Pairing token**: a 128-bit random token stored in `~/.passpaper/pairing.json`, used to authenticate the tablet.
- **Logs**: written to local files only.

### Data we do NOT collect

- No account, no cloud, no telemetry, no ad tracking.
- No outbound network calls (the recognition endpoint is user-configured and off by default).

### Recognition (optional)

If `PASSPAPER_RECOGNIZER_ENDPOINT` is configured, handwriting images are sent **only** to the user-specified local VLM endpoint (e.g. ollama / llama.cpp / vLLM). When unset, images never leave the machine.

### Third parties

- Source code is hosted on GitHub (public).
- The MCP trust badge is served by M8ven, which reads only public repository metadata (see <https://m8ven.ai>).

### Contact

Via GitHub Issues: <https://github.com/Bin-H-17/passpaper/issues>
