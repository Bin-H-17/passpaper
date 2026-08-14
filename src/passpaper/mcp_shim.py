#!/usr/bin/env python3
"""
PassPaper — MCP shim (stdio ↔ daemon)
=====================================
A tiny, dependency-free MCP server. AI clients (Claude Code, Codex) spawn THIS
process via stdio. It answers the MCP handshake instantly and forwards tool
calls to the always-on daemon over localhost HTTP.

Why this fixes v3's "MCP won't load / slow to prepare":
  - Imports only stdlib → process is ready in <100ms
  - `initialize` is answered immediately; no port scans, no QR popups, no Pillow
  - Implements ping + echoes the client's protocolVersion + answers
    resources/list & prompts/list (some clients probe these)
  - stdin uses readline() (no readahead buffering stalls)
  - stdin EOF → exit immediately (no zombie processes holding port 8765)
  - If the daemon isn't running, the shim auto-launches it (detached)

stdout carries ONLY JSON-RPC. All diagnostics go to stderr.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
import time
import urllib.request
import urllib.error
from pathlib import Path

try:
    from .common import (
        DAEMON_HOST, DATA_DIR, VERSION, is_daemon_alive, daemon_http_headers,
        find_pythonw, sync_runtime_bundle,
    )
except ImportError:  # running as a plain script (runtime bundle)
    from common import (
        DAEMON_HOST, DATA_DIR, VERSION, is_daemon_alive, daemon_http_headers,
        find_pythonw, sync_runtime_bundle,
    )

# Force UTF-8 on stdio pipes (Windows default codepage would mangle Chinese).
try:
    sys.stdin.reconfigure(encoding="utf-8", errors="replace")
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

SUPPORTED_PROTOCOL_VERSIONS = ("2025-06-18", "2025-03-26", "2024-11-05")

TOOLS = [
    {
        "name": "get_handwriting",
        "description": (
            "Read the user's CURRENT handwriting from the tablet. Returns a PNG image. "
            "Only call this AFTER the user has written something and asks you to look. "
            "Triggers: '看看我写的', '看我写的', 'look at my writing', "
            "'帮我检查这个推导', '你看一下'. "
            "Do NOT call this for initial setup — use get_connection_info first."
        ),
        "inputSchema": {"type": "object", "properties": {}, "required": []},
    },
    {
        "name": "clear_canvas",
        "description": "【递纸】Clear the tablet canvas. Call when user says '清空画布', 'clear', '重新开始'.",
        "inputSchema": {"type": "object", "properties": {}, "required": []},
    },
    {
        "name": "get_handwriting_status",
        "description": (
            "【递纸】Check tablet status: stroke count, revision, connected tablets, "
            "new-content flag. Does NOT render an image. Lightweight. "
            "Call when user asks '有更新吗', '有没有新内容'."
        ),
        "inputSchema": {"type": "object", "properties": {}, "required": []},
    },
    {
        "name": "get_connection_info",
        "description": (
            "【递纸】Get the PassPaper tablet connection URL + QR code image. "
            "Call this FIRST whenever the user mentions '递纸', 'passpaper', "
            "'手写板', '平板连接', '画布', '地址', '二维码', '扫码', "
            "'我要用递纸', '打开递纸', '连接平板', '连平板'. "
            "The pairing is persistent — the user can bookmark the URL."
        ),
        "inputSchema": {"type": "object", "properties": {}, "required": []},
    },
    {
        "name": "save_snapshot",
        "description": (
            "【递纸】Save the current handwriting as a PNG file on disk and return "
            "its path. Use this when you cannot receive images through MCP directly "
            "(e.g. some Codex setups) — then read the file instead."
        ),
        "inputSchema": {"type": "object", "properties": {}, "required": []},
    },
    {
        "name": "list_sessions",
        "description": "【递纸】列出本地保存的手写会话（按时间倒序）。每个会话是一份可随项目 Git 提交、可回放、可导出的文本记录。",
        "inputSchema": {"type": "object", "properties": {}, "required": []},
    },
    {
        "name": "start_session",
        "description": "【递纸】开始一个新的手写会话（之前的会话会被保留，可随时导出）。",
        "inputSchema": {"type": "object", "properties": {}, "required": []},
    },
    {
        "name": "export_session",
        "description": (
            "【递纸】导出一个手写会话为可移植格式：md（人类可读+识别文本）、"
            "jsonl（原始日志）、json（笔画重放）、excalidraw（可在 Excalidraw 打开）。"
            "session_id 留空则用当前会话。"
        ),
        "inputSchema": {"type": "object", "properties": {
            "session_id": {"type": "string", "description": "会话 ID，来自 list_sessions；留空=当前会话"},
            "format": {"type": "string", "enum": ["md", "jsonl", "json", "excalidraw"],
                       "description": "导出格式，默认 md"},
        }, "required": []},
    },
    {
        "name": "recognize_handwriting",
        "description": (
            "【递纸】对手写画布做结构化识别（若已配置本地 VLM/PaddleOCR-VL/GLM-OCR 则"
            "输出中文文本与 LaTeX；否则回退为让 Agent 直接看图）。同时把识别结果"
            "记入当前会话，便于回溯。"
        ),
        "inputSchema": {"type": "object", "properties": {}, "required": []},
    },
]


def _log(msg: str):
    try:
        sys.stderr.write(f"[passpaper-shim] {msg}\n")
        sys.stderr.flush()
    except Exception:
        pass


def _daemon_script() -> Path:
    """daemon.py sitting next to this shim (runtime bundle) or in the package."""
    return Path(__file__).parent / "daemon.py"


def ensure_daemon() -> bool:
    """Make sure the daemon is up; auto-launch it detached if not."""
    if is_daemon_alive():
        return True
    script = _daemon_script()
    if not script.exists():
        _log(f"daemon script not found at {script}")
        return False
    try:
        log_fh = open(DATA_DIR / "daemon.spawn.log", "ab")
        creationflags = 0
        if os.name == "nt":
            creationflags = (
                getattr(subprocess, "DETACHED_PROCESS", 0x00000008)
                | getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0x00000200)
                | getattr(subprocess, "CREATE_NO_WINDOW", 0x08000000)
            )
        subprocess.Popen(
            [find_pythonw(), str(script)],
            stdin=subprocess.DEVNULL, stdout=log_fh, stderr=log_fh,
            creationflags=creationflags, close_fds=True,
        )
        _log("daemon auto-launched")
    except Exception as e:
        _log(f"daemon launch failed: {e}")
        return False
    # Wait for readiness (bind-first design makes this fast).
    deadline = time.time() + 6
    while time.time() < deadline:
        if is_daemon_alive(timeout=0.5):
            return True
        time.sleep(0.3)
    return False


def call_daemon_tool(name: str, arguments: dict) -> dict:
    """Forward one tools/call to the daemon. Returns an MCP result object."""
    from urllib.parse import quote

    qs = f"name={quote(name)}&args={quote(json.dumps(arguments or {}))}"
    url = f"{DAEMON_HOST}/mcp/call?{qs}"

    def _attempt() -> dict:
        req = urllib.request.Request(url, headers=daemon_http_headers(), method="GET")
        with urllib.request.urlopen(req, timeout=15) as resp:
            return json.loads(resp.read().decode("utf-8"))

    try:
        return _attempt()
    except Exception:
        pass
    # Daemon down or hiccup → try to (re)launch and retry once.
    if ensure_daemon():
        try:
            return _attempt()
        except Exception as e:
            _log(f"tool call failed after retry: {e}")
    return {
        "content": [{"type": "text", "text": (
            "递纸 daemon 暂时不可用。可以尝试：\n"
            "1. 运行 `passpaper start` 手动启动 daemon\n"
            "2. 运行 `passpaper doctor` 诊断环境\n"
            "3. 查看日志 ~/.passpaper/daemon.log"
        )}],
        "isError": True,
    }


def handle_request(req: dict) -> dict | None:
    method = req.get("method", "")
    req_id = req.get("id")

    if method == "initialize":
        # Negotiate: echo the client's version if we know it, else our newest.
        client_ver = (req.get("params") or {}).get("protocolVersion", "")
        version = client_ver if client_ver in SUPPORTED_PROTOCOL_VERSIONS else SUPPORTED_PROTOCOL_VERSIONS[0]
        return {
            "jsonrpc": "2.0", "id": req_id,
            "result": {
                "protocolVersion": version,
                "serverInfo": {"name": "passpaper", "version": VERSION},
                "capabilities": {"tools": {}},
            },
        }

    if method == "ping":
        return {"jsonrpc": "2.0", "id": req_id, "result": {}}

    if method == "tools/list":
        return {"jsonrpc": "2.0", "id": req_id, "result": {"tools": TOOLS}}

    if method == "resources/list":
        return {"jsonrpc": "2.0", "id": req_id, "result": {"resources": []}}

    if method == "prompts/list":
        return {"jsonrpc": "2.0", "id": req_id, "result": {"prompts": []}}

    if method == "tools/call":
        params = req.get("params") or {}
        name = params.get("name", "")
        arguments = params.get("arguments") or {}
        if not name:
            return {"jsonrpc": "2.0", "id": req_id,
                    "error": {"code": -32602, "message": "missing tool name"}}
        result = call_daemon_tool(name, arguments)
        return {"jsonrpc": "2.0", "id": req_id, "result": result}

    if method.startswith("notifications/"):
        return None  # notifications never get responses

    return {"jsonrpc": "2.0", "id": req_id,
            "error": {"code": -32601, "message": f"Method not found: {method}"}}


def main() -> int:
    # Best-effort: make sure the runtime bundle exists (no-op when already synced
    # or when running from the bundle itself).
    try:
        if Path(__file__).parent != (Path.home() / ".passpaper"):
            sync_runtime_bundle()
    except Exception:
        pass

    # Warm the daemon in the background so the first tool call is instant —
    # but NEVER block the handshake on it.
    import threading
    threading.Thread(target=ensure_daemon, daemon=True).start()

    while True:
        try:
            line = sys.stdin.readline()
        except Exception:
            break
        if not line:  # EOF: client exited → die immediately, no zombies
            break
        line = line.strip()
        if not line:
            continue
        try:
            req = json.loads(line)
        except json.JSONDecodeError:
            continue
        try:
            resp = handle_request(req)
        except Exception as e:
            _log(f"handler error: {e}")
            resp = {"jsonrpc": "2.0", "id": req.get("id"),
                    "error": {"code": -32603, "message": str(e)}}
        if resp is not None:
            try:
                sys.stdout.write(json.dumps(resp, ensure_ascii=False) + "\n")
                sys.stdout.flush()
            except (BrokenPipeError, OSError):
                return 0  # client gone
    return 0


if __name__ == "__main__":
    sys.exit(main())
