# 递纸（PassPaper）— 操作手册

> 完整架构与 MCP 工具说明见 [README.md](README.md)。本手册只讲怎么用。

---

## 一次性设置（Windows）

```bash
# 1. 安装依赖（仅首次）
pip install -r requirements.txt

# 2. 配置全局 MCP（仅首次，注册 Claude Code + Codex）
python scripts/setup_global_mcp.py

# 3. 启动常驻 daemon
python src/passpaper/cli.py start
```

> 更省事：直接双击 `start.bat`（自动检测 Python、装依赖、注册、启动 daemon）。

---

## 每次使用

1. 打开 Claude Code（任意目录），对它说 **「我要用递纸」**。
2. AI 会主动给出**二维码 / 平板链接**——平板 Chrome 打开后**存成书签**。
3. 写字，然后对 AI 说 **「看看我刚写的」**，它就会通过 MCP 工具来读取你的手写。

```
平板 Chrome 打开书签 → 写字 → 对 AI 说「看看我刚写的」
```

以后每次用：打开书签直接写。daemon 没跑的话，MCP shim 会自动拉起。

---

## 常用命令

```bash
python src/passpaper/cli.py start         # 启动 daemon（后台常驻）
python src/passpaper/cli.py status        # 健康状态 / 笔画数 / 平板数 / 链接
python src/passpaper/cli.py stop          # 优雅停止（先存盘）
python src/passpaper/cli.py doctor        # 环境诊断
python src/passpaper/cli.py rotate-token  # 配对码泄露时轮换
```

---

## 故障排查

| 问题 | 解决 |
|------|------|
| 依赖缺失 | `pip install -r requirements.txt` |
| 平板连不上 | 同一 WiFi？系统防火墙放行 TCP 8765？ |
| IP 变了 | 用 `status` 命令重新获取链接 / 二维码 |
| CC 不主动说地址 | 问「地址是什么」或让它调用 `get_connection_info` |
