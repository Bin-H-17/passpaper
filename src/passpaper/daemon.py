#!/usr/bin/env python3
"""
PassPaper — Daemon (always-on LAN server)
=========================================
The daemon owns the canvas. It runs independently of Claude Code / Codex:
tablets can connect and write at any time, whether or not any AI client is up.

Responsibilities:
  - WebSocket server for tablets (persistent pairing token auth)
  - HTTP server: canvas page, health, snapshot, MCP tool dispatch for the shim
  - Incremental rendering: every stroke is drawn onto an in-memory PIL canvas
    the moment it arrives, so get_handwriting never re-renders from scratch
  - Persistence: strokes auto-saved to ~/.passpaper/strokes_backup.json

Design notes (v4 fixes vs v3):
  - Binds the port FIRST, does slow work (QR gen, file writes) in the background
  - Logs to a rotating FILE, never per-stroke stderr prints (a full stderr pipe
    used to freeze the whole event loop)
  - draw.line(joint="curve") instead of per-point ellipses (~50x faster)
  - Output image capped at 1568px long edge, palette-mode PNG (much smaller)
  - PID-file process management, no netstat scans, no QR popups
"""

from __future__ import annotations

import asyncio
import base64
import io
import json
import logging
import os
import signal
import sys
import threading
import time
from datetime import datetime, timezone
from logging.handlers import RotatingFileHandler
from pathlib import Path

try:
    from .common import (
        BACKUP_FILE, CANVAS_H, CANVAS_W, CONNECTION_FILE, DAEMON_HOST, INFO_FILE,
        LOG_FILE, MAX_IMAGE_EDGE, PID_FILE, PORT, QR_FILE, SNAPSHOT_FILE, VERSION,
        get_local_ip, is_daemon_alive, load_pairing_token,
    )
except ImportError:  # running as a plain script (runtime bundle)
    from common import (
        BACKUP_FILE, CANVAS_H, CANVAS_W, CONNECTION_FILE, DAEMON_HOST, INFO_FILE,
        LOG_FILE, MAX_IMAGE_EDGE, PID_FILE, PORT, QR_FILE, SNAPSHOT_FILE, VERSION,
        get_local_ip, is_daemon_alive, load_pairing_token,
    )

# ── v1.0.0: session recording + pluggable recognition (additive, never blocks) ──
try:
    from .recorder import SessionRecorder
    from .recognition import get_recognizer
except ImportError:  # running as a plain script (runtime bundle)
    from recorder import SessionRecorder
    from recognition import get_recognizer

try:
    from PIL import Image, ImageDraw
except ImportError:
    print("[PassPaper] Pillow not installed. Run: pip install Pillow", file=sys.stderr)
    sys.exit(1)

try:
    from websockets.asyncio.server import serve
except ImportError:
    print("[PassPaper] websockets not installed. Run: pip install websockets", file=sys.stderr)
    sys.exit(1)

PAIRING_TOKEN = load_pairing_token()
STARTED_AT = time.time()

# ── Logging: file only. Never block on a stderr pipe. ──
log = logging.getLogger("passpaper")
log.setLevel(logging.INFO)
_fh = RotatingFileHandler(LOG_FILE, maxBytes=1_000_000, backupCount=2, encoding="utf-8")
_fh.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(message)s"))
log.addHandler(_fh)
if os.environ.get("PASSPAPER_FG"):
    log.addHandler(logging.StreamHandler(sys.stderr))


# ═══════════════════════════════════════════════════════════════════
# Canvas: stroke store + incremental render
# ═══════════════════════════════════════════════════════════════════

class Canvas:
    def __init__(self):
        self.image = Image.new("RGB", (CANVAS_W, CANVAS_H), "white")
        self.draw = ImageDraw.Draw(self.image)
        self.strokes: list[dict] = []
        self.revision = 0
        self.content_bbox: list[float] | None = None  # ink only (eraser excluded)
        self.last_stroke_at: float | None = None
        self.last_fetch_revision = -1
        self.dirty = False
        self._snap_rev = -1
        self._snap_png: bytes | None = None

    # ── drawing ──
    def _paint(self, s: dict):
        pts = [(p["x"], p["y"]) for p in s.get("points", [])]
        if not pts:
            return
        color = "#ffffff" if s.get("eraser") else s.get("color", "#000000")
        width = max(1, int(s.get("width", 3)))
        # draw.line with joint="curve" renders a whole polyline in one C call.
        # Round caps only need two ellipses (stroke ends), not one per point.
        if len(pts) == 1:
            x, y = pts[0]
            r = width / 2
            self.draw.ellipse([x - r, y - r, x + r, y + r], fill=color)
        else:
            self.draw.line(pts, fill=color, width=width, joint="curve")
            r = width / 2
            for x, y in (pts[0], pts[-1]):
                self.draw.ellipse([x - r, y - r, x + r, y + r], fill=color)

    def add_stroke(self, s: dict):
        self._paint(s)
        self.strokes.append(s)
        self.revision += 1
        self.dirty = True
        self.last_stroke_at = time.time()
        if not s.get("eraser"):
            w2 = max(1, int(s.get("width", 3))) / 2
            for p in s.get("points", []):
                x, y = p["x"], p["y"]
                if self.content_bbox is None:
                    self.content_bbox = [x - w2, y - w2, x + w2, y + w2]
                else:
                    b = self.content_bbox
                    b[0] = min(b[0], x - w2); b[1] = min(b[1], y - w2)
                    b[2] = max(b[2], x + w2); b[3] = max(b[3], y + w2)

    def clear(self):
        self.image = Image.new("RGB", (CANVAS_W, CANVAS_H), "white")
        self.draw = ImageDraw.Draw(self.image)
        self.strokes.clear()
        self.revision += 1
        self.content_bbox = None
        self.dirty = True
        self._snap_rev = -1
        self._snap_png = None

    # ── snapshot (cached per revision) ──
    def snapshot_png(self) -> bytes:
        if self._snap_rev == self.revision and self._snap_png is not None:
            return self._snap_png
        pad = 40
        if self.content_bbox:
            x0, y0, x1, y1 = self.content_bbox
            cx0 = max(0, int(x0) - pad); cy0 = max(0, int(y0) - pad)
            cx1 = min(CANVAS_W, int(x1) + pad); cy1 = min(CANVAS_H, int(y1) + pad)
            if (cx1 - cx0) < 100 or (cy1 - cy0) < 100:
                cx0, cy0, cx1, cy1 = 0, 0, CANVAS_W, CANVAS_H
        else:
            cx0, cy0, cx1, cy1 = 0, 0, CANVAS_W, CANVAS_H
        img = self.image.crop((cx0, cy0, cx1, cy1))
        img.thumbnail((MAX_IMAGE_EDGE, MAX_IMAGE_EDGE), Image.LANCZOS)
        # Palette PNG: handwriting has a handful of colors, ~3-5x smaller than RGB.
        img = img.convert("P", palette=Image.ADAPTIVE, colors=16)
        buf = io.BytesIO()
        img.save(buf, format="PNG", optimize=True)
        self._snap_png = buf.getvalue()
        self._snap_rev = self.revision
        return self._snap_png

    def has_new_since_last_fetch(self) -> bool:
        if self.last_fetch_revision < 0:
            return len(self.strokes) > 0
        return self.revision > self.last_fetch_revision

    # ── persistence ──
    def save(self):
        if not self.dirty:
            return
        try:
            BACKUP_FILE.write_text(
                json.dumps({"strokes": self.strokes, "revision": self.revision}),
                encoding="utf-8",
            )
            self.dirty = False
        except Exception as e:
            log.warning(f"auto-save failed: {e}")

    def load(self):
        try:
            if not BACKUP_FILE.exists():
                return
            data = json.loads(BACKUP_FILE.read_text(encoding="utf-8"))
            strokes = data.get("strokes", [])
            for s in strokes:
                if isinstance(s, dict) and s.get("points"):
                    self._paint(s)
                    self.strokes.append(s)
                    if not s.get("eraser"):
                        for p in s.get("points", []):
                            x, y = p["x"], p["y"]
                            if self.content_bbox is None:
                                self.content_bbox = [x, y, x, y]
                            else:
                                b = self.content_bbox
                                b[0] = min(b[0], x); b[1] = min(b[1], y)
                                b[2] = max(b[2], x); b[3] = max(b[3], y)
            self.revision = int(data.get("revision", len(self.strokes)))
            self.dirty = False
            if self.strokes:
                self.last_stroke_at = time.time()
            log.info(f"restored {len(self.strokes)} strokes (rev {self.revision})")
        except Exception as e:
            log.warning(f"backup load failed: {e}")


canvas = Canvas()
TABLETS: set = set()
STOP_EVENT: asyncio.Event | None = None  # created in amain, used by /shutdown

# v1.0.0 — durable, git-friendly session log (additive; never raises into the
# hot stroke path because SessionRecorder swallows its own I/O errors).
recorder = SessionRecorder(DATA_DIR / "sessions")


# ═══════════════════════════════════════════════════════════════════
# WebSocket (tablet side)
# ═══════════════════════════════════════════════════════════════════

MAX_POINTS_PER_STROKE = 5000
MAX_TOTAL_STROKES = 20000


def _valid_stroke(s: dict) -> bool:
    pts = s.get("points")
    if not isinstance(pts, list) or not pts or len(pts) > MAX_POINTS_PER_STROKE:
        return False
    for p in pts:
        if not isinstance(p, dict):
            return False
        x, y = p.get("x"), p.get("y")
        if not isinstance(x, (int, float)) or not isinstance(y, (int, float)):
            return False
        if not (0 <= x <= CANVAS_W and 0 <= y <= CANVAS_H):
            return False
    color = s.get("color", "#000000")
    if not isinstance(color, str) or not color.startswith("#") or len(color) != 7:
        return False
    width = s.get("width", 3)
    if not isinstance(width, (int, float)) or not (1 <= width <= 80):
        return False
    return True


async def _send_json(ws, obj: dict):
    try:
        await ws.send(json.dumps(obj))
    except Exception:
        pass


async def ws_handler(ws):
    # Auth: pairing token in URL query (canvas.html always connects with it)
    path = ws.request.path if getattr(ws, "request", None) else "/"
    token = ""
    if "?token=" in path:
        token = path.split("?token=")[-1].split("&")[0]
    if token != PAIRING_TOKEN:
        await ws.close(4001, "Invalid or missing pairing token")
        log.warning(f"WS rejected (bad token) from {ws.remote_address}")
        return

    TABLETS.add(ws)
    log.info(f"tablet connected: {ws.remote_address} (tablets={len(TABLETS)}, rev={canvas.revision})")
    stroke_count = 0
    try:
        async for message in ws:
            if not isinstance(message, str):
                continue
            try:
                data = json.loads(message)
            except json.JSONDecodeError:
                continue
            action = data.get("action", "")

            if action == "hello":
                await _send_json(ws, {
                    "ok": True, "revision": canvas.revision,
                    "strokes": len(canvas.strokes), "version": VERSION,
                })

            elif action == "stroke":
                if len(canvas.strokes) >= MAX_TOTAL_STROKES:
                    await _send_json(ws, {"error": "max_strokes_reached"})
                    continue
                if _valid_stroke(data):
                    stroke = {
                        "points": data["points"],
                        "color": data.get("color", "#000000"),
                        "width": data.get("width", 3),
                        "eraser": bool(data.get("eraser")),
                    }
                    canvas.add_stroke(stroke)
                    recorder.record_stroke(stroke)
                    stroke_count += 1
                    if stroke_count % 100 == 0:
                        log.info(f"received {stroke_count} strokes this connection")

            elif action == "batch":  # offline queue flush from tablet
                strokes = data.get("strokes", [])
                if isinstance(strokes, list):
                    accepted = 0
                    for s in strokes[:500]:
                        if isinstance(s, dict) and _valid_stroke(s):
                            stroke = {
                                "points": s["points"],
                                "color": s.get("color", "#000000"),
                                "width": s.get("width", 3),
                                "eraser": bool(s.get("eraser")),
                            }
                            canvas.add_stroke(stroke)
                            recorder.record_stroke(stroke)
                            accepted += 1
                    log.info(f"batch flush: {accepted}/{len(strokes)} strokes accepted")
                    await _send_json(ws, {"ok": True, "accepted": accepted, "revision": canvas.revision})

            elif action == "clear":
                canvas.clear()
                recorder.record_clear()
                log.info("canvas cleared by tablet")
                await _send_json(ws, {"ok": True, "revision": canvas.revision})

            elif action == "ping":
                await _send_json(ws, {"pong": True})
    finally:
        TABLETS.discard(ws)
        log.info(f"tablet disconnected (tablets={len(TABLETS)}, strokes this conn={stroke_count})")


# ═══════════════════════════════════════════════════════════════════
# MCP tool implementations (called via /mcp/call from the shim)
# ═══════════════════════════════════════════════════════════════════

def tool_get_handwriting() -> dict:
    if not canvas.strokes:
        return {"content": [{"type": "text", "text": "画布为空，还没有写任何内容。"}]}
    png = canvas.snapshot_png()
    canvas.last_fetch_revision = canvas.revision
    age = int(time.time() - canvas.last_stroke_at) if canvas.last_stroke_at else -1
    meta = (
        f"Handwriting retrieved. Revision: {canvas.revision}. "
        f"Strokes: {len(canvas.strokes)}. Image: {len(png)} bytes."
    )
    if age > 300:
        meta += f" ⚠️ 最后一批笔画是 {age // 60} 分钟前写的，可能是旧内容。"
    elif age >= 0:
        meta += f" 最后书写于 {age} 秒前。"
    return {"content": [
        {"type": "text", "text": meta},
        {"type": "image", "data": base64.b64encode(png).decode("ascii"), "mimeType": "image/png"},
    ]}


def tool_clear_canvas() -> dict:
    canvas.clear()
    canvas.save()
    return {"content": [{"type": "text", "text": "画布已清空。"}]}


def tool_get_handwriting_status() -> dict:
    new = canvas.has_new_since_last_fetch()
    return {"content": [{"type": "text", "text": (
        f"Status: {len(canvas.strokes)} strokes, revision {canvas.revision}. "
        f"Tablets connected: {len(TABLETS)}. "
        f"New content since last fetch: {'yes' if new else 'no'}."
    )}]}


def tool_get_connection_info(url: str) -> dict:
    content = [{"type": "text", "text": (
        f"📱 Tablet URL: {url}\n"
        "需要同一 WiFi。在平板上用 Chrome 打开该链接（或扫码），"
        "可以把链接存成书签/桌面图标——配对码是持久的，以后点开就能写。"
    )}]
    try:
        if QR_FILE.exists():
            qr_b64 = base64.b64encode(QR_FILE.read_bytes()).decode("ascii")
            content.append({"type": "image", "data": qr_b64, "mimeType": "image/png"})
    except Exception:
        pass
    return {"content": content}


def tool_save_snapshot() -> dict:
    if not canvas.strokes:
        return {"content": [{"type": "text", "text": "画布为空，没有可保存的内容。"}]}
    png = canvas.snapshot_png()
    try:
        SNAPSHOT_FILE.write_bytes(png)
        return {"content": [{"type": "text", "text": (
            f"Snapshot saved: {SNAPSHOT_FILE}\n"
            f"({len(png)} bytes, revision {canvas.revision}). "
            "For clients that cannot receive images via MCP: read/attach this file."
        )}]}
    except Exception as e:
        return {"content": [{"type": "text", "text": f"保存失败: {e}"}], "isError": True}


# ═══════════════════════════════════════════════════════════════════
# v1.0.0 — session recording & recognition tools
# ═══════════════════════════════════════════════════════════════════

def tool_list_sessions() -> dict:
    rows = recorder.list_sessions()
    if not rows:
        return {"content": [{"type": "text", "text":
            "还没有任何会话记录。在平板上写几笔就会自动建立会话，可随项目 Git 提交、回放、导出。"}]}
    import datetime as _dt
    lines = ["最近会话（按时间倒序）：", ""]
    for r in rows[:20]:
        started = r.get("started")
        started_s = (_dt.datetime.utcfromtimestamp(started).strftime("%Y-%m-%d %H:%M UTC")
                     if isinstance(started, (int, float)) else "?")
        lines.append(f"- {r['session_id']}  笔画 {r['strokes']}  起 {started_s}  ({r['size_bytes']} B)")
    lines.append("")
    lines.append("用 export_session(session_id, format) 导出：md | jsonl | json | excalidraw")
    return {"content": [{"type": "text", "text": "\n".join(lines)}]}


def tool_start_session() -> dict:
    sid = recorder.start_new_session()
    return {"content": [{"type": "text", "text": f"已开始新会话：{sid}（之前的会话已保留，可随时导出）。"}]}


def tool_export_session(session_id: str = "", fmt: str = "md") -> dict:
    if not session_id:
        session_id = recorder.current_id
    res = recorder.export(session_id, fmt)
    if res.get("error"):
        return {"content": [{"type": "text", "text": f"导出失败：{res['error']}"}]}
    return {"content": [{"type": "text", "text":
        f"# 会话 {res['session_id']} 导出（{res['format']}，{res['strokes']} 笔画）\n\n"
        f"```\n{res['content']}\n```\n\n"
        f"（这是可随项目 Git 提交、可回放的文本产物。）"}]}


def tool_recognize_handwriting() -> dict:
    if not canvas.strokes:
        return {"content": [{"type": "text", "text": "画布为空，还没有可识别的内容。"}]}
    png = canvas.snapshot_png()
    rec = get_recognizer().recognize(png, canvas.strokes)
    recorder.record_recognition(rec.text, rec.latex, rec.confidence, engine=rec.engine)
    parts = [f"识别引擎：{rec.engine}"]
    if rec.text:
        parts.append(f"文本：{rec.text}")
    if rec.latex:
        parts.append(f"LaTeX：{rec.latex}")
    if rec.note:
        parts.append(f"说明：{rec.note}")
    # 默认仍把图片交给 Agent（让模型直接看图），识别文本作为辅助结构化信息。
    return {"content": [
        {"type": "text", "text": "\n".join(parts)},
        {"type": "image", "data": base64.b64encode(png).decode("ascii"), "mimeType": "image/png"},
    ]}


def dispatch_tool(name: str, arguments: dict, url: str) -> dict:
    if name == "get_handwriting":
        return tool_get_handwriting()
    if name == "clear_canvas":
        return tool_clear_canvas()
    if name == "get_handwriting_status":
        return tool_get_handwriting_status()
    if name == "get_connection_info":
        return tool_get_connection_info(url)
    if name == "save_snapshot":
        return tool_save_snapshot()
    if name == "list_sessions":
        return tool_list_sessions()
    if name == "start_session":
        return tool_start_session()
    if name == "export_session":
        args = arguments if isinstance(arguments, dict) else {}
        session_id = args.get("session_id", "") or ""
        fmt = args.get("format", "md") or "md"
        return tool_export_session(session_id, fmt)
    if name == "recognize_handwriting":
        return tool_recognize_handwriting()
    return {"content": [{"type": "text", "text": f"Unknown tool: {name}"}], "isError": True}


# ═══════════════════════════════════════════════════════════════════
# HTTP (canvas page, health, snapshot, MCP dispatch)
# ═══════════════════════════════════════════════════════════════════

CURRENT_URL = ""


def _authorized(query: str, headers) -> bool:
    token = ""
    if "token=" in query:
        token = query.split("token=")[-1].split("&")[0]
    if token == PAIRING_TOKEN:
        return True
    return headers.get("X-Passpaper-Token", "") == PAIRING_TOKEN


async def http_handler(connection, request):
    raw_path = request.path
    path, _, query = raw_path.partition("?")

    # WebSocket upgrade: pass through to ws_handler
    if request.headers.get("Upgrade", "").lower() == "websocket":
        return None

    if path in ("/", "/canvas", "/canvas.html"):
        if not _authorized(query, request.headers):
            r = connection.respond(403, "Forbidden: open the full URL with its pairing token.")
            r.headers["Content-Type"] = "text/plain; charset=utf-8"
            return r
        html_file = Path(__file__).parent / "canvas.html"
        if html_file.exists():
            body = html_file.read_text(encoding="utf-8")
            body = body.replace("__SESSION_TOKEN__", PAIRING_TOKEN)
            body = body.replace("__WS_PORT__", str(PORT))
            r = connection.respond(200, body)
            r.headers["Content-Type"] = "text/html; charset=utf-8"
            return r
        return connection.respond(404, "canvas.html not found")

    if path == "/health":
        r = connection.respond(200, json.dumps({
            "status": "ok", "version": VERSION,
            "strokes": len(canvas.strokes), "revision": canvas.revision,
            "tablets": len(TABLETS), "uptime_s": int(time.time() - STARTED_AT),
        }))
        r.headers["Content-Type"] = "application/json"
        return r

    if path == "/shutdown":
        # Graceful stop used by `passpaper stop` — saves strokes before exit.
        if not _authorized(query, request.headers):
            return connection.respond(403, "Forbidden")
        r = connection.respond(200, json.dumps({"status": "shutting_down"}))
        r.headers["Content-Type"] = "application/json"
        if STOP_EVENT is not None:
            asyncio.get_running_loop().call_later(0.3, STOP_EVENT.set)
        return r

    if path == "/snapshot":
        if not _authorized(query, request.headers):
            return connection.respond(403, "Forbidden")
        if not canvas.strokes:
            return connection.respond(204, "")
        # Raw PNG bytes: build the Response directly (connection.respond only
        # accepts text). Falls back to base64 text on older websockets.
        png = canvas.snapshot_png()
        try:
            from websockets.datastructures import Headers
            from websockets.http11 import Response as WSResponse
            return WSResponse(200, "OK", Headers([
                ("Content-Type", "image/png"),
                ("Content-Length", str(len(png))),
                ("Cache-Control", "no-store"),
            ]), png)
        except Exception:
            r = connection.respond(200, base64.b64encode(png).decode("ascii"))
            r.headers["Content-Type"] = "text/plain; charset=utf-8"
            return r

    if path == "/mcp/call":
        # GET-based dispatch: websockets' process_request hook can't read POST
        # bodies, so the shim calls /mcp/call?name=<tool>&args=<urlencoded-json>.
        # All current tools have empty argument schemas, so this stays simple.
        if not _authorized(query, request.headers):
            return connection.respond(403, "Forbidden")
        try:
            from urllib.parse import parse_qs, unquote
            qs = parse_qs(query)
            name = qs.get("name", [""])[0]
            args_raw = qs.get("args", ["{}"])[0]
            arguments = json.loads(unquote(args_raw)) if args_raw else {}
            result = dispatch_tool(name, arguments, CURRENT_URL)
            r = connection.respond(200, json.dumps(result))
            r.headers["Content-Type"] = "application/json"
            return r
        except Exception as e:
            log.warning(f"/mcp/call error: {e}")
            r = connection.respond(400, json.dumps({"error": str(e)}))
            r.headers["Content-Type"] = "application/json"
            return r

    return None


# ═══════════════════════════════════════════════════════════════════
# Startup
# ═══════════════════════════════════════════════════════════════════

def _prepare_connection_files(url: str):
    """Slow, non-critical work: happens in the background after the port is bound."""
    try:
        CONNECTION_FILE.write_text(url, encoding="utf-8")
        INFO_FILE.write_text(
            f"PassPaper v{VERSION} — daemon running\n"
            f"================================\n\n"
            f"Tablet URL (persistent, bookmark it):\n{url}\n\n"
            "Same WiFi required. Open in Chrome on the tablet and write.\n"
            "Then in Claude Code / Codex say: 看看我写的 / look at my writing.\n",
            encoding="utf-8",
        )
    except Exception as e:
        log.warning(f"connection files: {e}")
    try:
        # QR only changes when the token rotates — reuse the existing PNG if fresh.
        import qrcode
        qr = qrcode.QRCode(border=1)
        qr.add_data(url)
        qr.make(fit=True)
        img = qr.make_image(fill_color="black", back_color="white")
        img.save(QR_FILE)
    except Exception as e:
        log.warning(f"QR generation failed (non-fatal): {e}")


async def _auto_save():
    while True:
        await asyncio.sleep(30)
        canvas.save()


async def amain() -> int:
    global CURRENT_URL, STOP_EVENT

    if is_daemon_alive():
        msg = "[PassPaper] daemon already running — exiting."
        print(msg, file=sys.stderr)
        log.info(msg)
        return 0

    ip = get_local_ip()
    CURRENT_URL = f"http://{ip}:{PORT}/?token={PAIRING_TOKEN}"

    # 1) Bind FIRST so the port is listening ASAP (fast readiness).
    try:
        server = await serve(
            ws_handler, "0.0.0.0", PORT,
            process_request=http_handler,
            ping_interval=20, ping_timeout=20,
            max_size=2 * 1024 * 1024,
        )
    except OSError as e:
        log.error(f"cannot bind port {PORT}: {e}")
        print(f"[PassPaper] cannot bind port {PORT}: {e}", file=sys.stderr)
        return 1

    PID_FILE.write_text(str(os.getpid()), encoding="utf-8")
    log.info(f"daemon v{VERSION} listening on :{PORT} (pid {os.getpid()})")

    # 2) Restore previous canvas (daemon is long-lived; CC restarts don't clear it).
    canvas.load()

    # 3) Slow/non-critical work in background thread.
    threading.Thread(target=_prepare_connection_files, args=(CURRENT_URL,), daemon=True).start()

    print(f"[PassPaper] v{VERSION} daemon ready on :{PORT} "
          f"(LAN {ip}). Tablet URL written to ~/.passpaper/connection.txt — "
          f"run `passpaper url` to show it.", file=sys.stderr)
    log.info(f"daemon ready on :{PORT} (lan={ip}); tablet url token redacted in logs")

    save_task = asyncio.create_task(_auto_save())
    STOP_EVENT = asyncio.Event()

    def _sig(*_):
        try:
            asyncio.get_running_loop().call_soon_threadsafe(STOP_EVENT.set)
        except RuntimeError:
            pass

    for sig in (signal.SIGINT, signal.SIGTERM):
        try:
            signal.signal(sig, _sig)
        except (OSError, ValueError, RuntimeError):
            pass

    await STOP_EVENT.wait()
    log.info("shutting down")
    canvas.save()
    save_task.cancel()
    server.close()
    await server.wait_closed()
    try:
        PID_FILE.unlink(missing_ok=True)
    except Exception:
        pass
    return 0


def main() -> int:
    try:
        return asyncio.run(amain())
    except KeyboardInterrupt:
        return 0


if __name__ == "__main__":
    sys.exit(main())
