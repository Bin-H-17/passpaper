#!/usr/bin/env python3
"""
PassPaper v4 — end-to-end verification script.
Runs the whole loop: shim handshake speed, daemon auto-spawn, tablet WS,
snapshot latency/size, render performance under load, graceful shutdown.
Prints PASS/FAIL per check. Exits 0 if all critical checks pass.
"""

from __future__ import annotations

import asyncio
import base64
import json
import os
import subprocess
import sys
import time
import urllib.request
from pathlib import Path

ROOT = Path(__file__).parent.parent
PKG = ROOT / "src" / "passpaper"
DATA = Path(os.environ.get("PASSPAPER_HOME", str(Path.home() / ".passpaper")))
HOST = "http://127.0.0.1:8765"

results = []  # (name, ok, detail)


def check(name: str, ok: bool, detail: str = "", critical: bool = True):
    results.append((name, ok, detail, critical))
    mark = "PASS" if ok else "FAIL"
    print(f"  [{mark}] {name}" + (f" — {detail}" if detail else ""))


def http(path: str, timeout: float = 5, headers: dict | None = None):
    req = urllib.request.Request(HOST + path, headers=headers or {})
    return urllib.request.urlopen(req, timeout=timeout)


def token() -> str:
    return json.loads((DATA / "pairing.json").read_text())["token"]


def stop_daemon_silently():
    try:
        http("/shutdown", timeout=1.5, headers={"X-Passpaper-Token": token()}).read()
        time.sleep(1.5)
    except Exception:
        pass
    try:
        pid = int((DATA / "daemon.pid").read_text().strip())
        subprocess.run(["taskkill", "/PID", str(pid), "/F"], capture_output=True)
        time.sleep(1)
    except Exception:
        pass


def daemon_alive() -> bool:
    try:
        http("/health", timeout=1).read()
        return True
    except Exception:
        return False


# ─────────────────────────────────────────────────────────────────
print("== PassPaper v4 E2E ==")
os.environ["PYTHONDONTWRITEBYTECODE"] = "1"

# Clean slate
stop_daemon_silently()
backup = DATA / "strokes_backup.json"
try:
    backup.unlink(missing_ok=True)
except Exception:
    pass

# ── 1. Shim cold handshake (daemon DOWN) ──
print("\n[1] Shim handshake speed (daemon down)")
PY = sys.executable
shim = subprocess.Popen(
    [PY, str(PKG / "mcp_shim.py")],
    stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
    text=True, encoding="utf-8",
)
t0 = time.time()
init_req = {"jsonrpc": "2.0", "id": 1, "method": "initialize",
            "params": {"protocolVersion": "2025-06-18", "capabilities": {},
                       "clientInfo": {"name": "e2e", "version": "1"}}}
shim.stdin.write(json.dumps(init_req) + "\n")
shim.stdin.flush()
line = shim.stdout.readline()
handshake_ms = (time.time() - t0) * 1000
try:
    resp = json.loads(line)
    pv = resp.get("result", {}).get("protocolVersion")
    check("shim initialize", pv == "2025-06-18",
          f"protocolVersion={pv}, {handshake_ms:.0f}ms cold (incl. python boot)")
    check("handshake < 1000ms", handshake_ms < 1000, f"{handshake_ms:.0f}ms")
except Exception as e:
    check("shim initialize", False, f"bad response: {line!r} {e}")

# tools/list
shim.stdin.write(json.dumps({"jsonrpc": "2.0", "id": 2, "method": "tools/list"}) + "\n")
shim.stdin.flush()
resp = json.loads(shim.stdout.readline())
tools = [t["name"] for t in resp.get("result", {}).get("tools", [])]
check("tools/list has 9 tools", len(tools) == 9, ", ".join(tools))

# ping
shim.stdin.write(json.dumps({"jsonrpc": "2.0", "id": 3, "method": "ping"}) + "\n")
shim.stdin.flush()
resp = json.loads(shim.stdout.readline())
check("ping", resp.get("result") == {})

# resources/prompts probe
shim.stdin.write(json.dumps({"jsonrpc": "2.0", "id": 4, "method": "resources/list"}) + "\n")
shim.stdin.flush()
resp = json.loads(shim.stdout.readline())
check("resources/list", resp.get("result", {}).get("resources") == [])

# ── 2. tools/call triggers daemon auto-spawn ──
print("\n[2] Daemon auto-spawn via shim")
t0 = time.time()
shim.stdin.write(json.dumps({
    "jsonrpc": "2.0", "id": 5, "method": "tools/call",
    "params": {"name": "get_handwriting_status", "arguments": {}}}) + "\n")
shim.stdin.flush()
resp = json.loads(shim.stdout.readline())
spawn_ms = (time.time() - t0) * 1000
text = (resp.get("result", {}).get("content") or [{}])[0].get("text", "")
check("tool call via shim", "Status:" in text, f"{spawn_ms:.0f}ms (incl. auto-spawn)")
check("daemon auto-spawned", daemon_alive(), "")
check("auto-spawn < 8s", spawn_ms < 8000, f"{spawn_ms:.0f}ms")

# ── 3. stdin EOF → shim exits (no zombie) ──
print("\n[3] Shim exits on stdin EOF")
shim.stdin.close()
try:
    shim.wait(timeout=5)
    check("shim exits on EOF", True, f"rc={shim.returncode}")
except subprocess.TimeoutExpired:
    shim.kill()
    check("shim exits on EOF", False, "did not exit within 5s")

# ── 4. Tablet WebSocket ──
print("\n[4] Tablet WebSocket")
import websockets.asyncio.client as ws_client


async def ws_tests():
    tok = token()
    ok_flags = {"hello": False, "bad_token_rejected": False}

    # bad token must be rejected
    try:
        async with ws_client.connect("ws://127.0.0.1:8765/?token=WRONG") as bad:
            try:
                await asyncio.wait_for(bad.recv(), 2)
            except Exception:
                ok_flags["bad_token_rejected"] = True
    except Exception:
        ok_flags["bad_token_rejected"] = True

    async with ws_client.connect(f"ws://127.0.0.1:8765/?token={tok}") as ws:
        await ws.send(json.dumps({"action": "hello", "viewport": {"w": 1280, "h": 800}}))
        reply = json.loads(await asyncio.wait_for(ws.recv(), 3))
        ok_flags["hello"] = reply.get("ok") is True

        # 3 normal strokes
        for i in range(3):
            pts = [{"x": 100 + j * 5, "y": 100 + i * 60 + j} for j in range(50)]
            await ws.send(json.dumps({
                "action": "stroke", "points": pts,
                "color": "#000000", "width": 6}))

        # offline-queue style batch
        batch = {"action": "batch", "strokes": [
            {"points": [{"x": 400 + j * 4, "y": 300 + j} for j in range(40)],
             "color": "#e53935", "width": 6} for _ in range(5)
        ]}
        await ws.send(json.dumps(batch))
        reply = json.loads(await asyncio.wait_for(ws.recv(), 3))
        ok_flags["batch_accepted"] = reply.get("accepted") == 5

        # eraser stroke
        await ws.send(json.dumps({
            "action": "stroke", "eraser": True,
            "points": [{"x": 150 + j * 3, "y": 150} for j in range(30)], "width": 40}))

        # ping
        await ws.send(json.dumps({"action": "ping"}))
        reply = json.loads(await asyncio.wait_for(ws.recv(), 3))
        ok_flags["pong"] = reply.get("pong") is True

    return ok_flags


flags = asyncio.run(ws_tests())
check("WS hello handshake", flags.get("hello", False))
check("WS strokes + batch", flags.get("batch_accepted", False))
check("WS ping/pong", flags.get("pong", False), critical=False)
check("bad token rejected", flags.get("bad_token_rejected", False))

# ── 5. Snapshot latency + size ──
print("\n[5] Snapshot latency + size")
t0 = time.time()
r = http(f"/snapshot?token={token()}", timeout=5)
png = r.read()
first_ms = (time.time() - t0) * 1000
t0 = time.time()
png2 = http(f"/snapshot?token={token()}", timeout=5).read()
cached_ms = (time.time() - t0) * 1000
check("snapshot content", png[:4] == b"\x89PNG", f"{len(png)} bytes")
check("snapshot fast", first_ms < 500, f"first {first_ms:.0f}ms, cached {cached_ms:.0f}ms")
check("snapshot small", len(png) < 400_000, f"{len(png)/1024:.0f}KB", critical=False)

# ── 6. Render performance under load ──
print("\n[6] Render performance (200 strokes × 300 pts = 60k points)")


async def load_test():
    tok = token()
    async with ws_client.connect(f"ws://127.0.0.1:8765/?token={tok}") as ws:
        await ws.send(json.dumps({"action": "hello"}))
        await asyncio.wait_for(ws.recv(), 3)
        t0 = time.time()
        for i in range(200):
            pts = [{"x": 50 + (j * 7 + i * 3) % 1900, "y": 50 + (i * 7 + j) % 1400}
                   for j in range(300)]
            await ws.send(json.dumps({
                "action": "stroke", "points": pts, "color": "#1e88e5", "width": 5}))
        return time.time() - t0


send_s = asyncio.run(load_test())
time.sleep(0.5)  # let the daemon finish processing the queue
t0 = time.time()
big = http(f"/snapshot?token={token()}", timeout=10).read()
render_ms = (time.time() - t0) * 1000
check("60k points ingested", send_s < 30, f"sent in {send_s:.1f}s")
check("big render < 3s", render_ms < 3000, f"{render_ms:.0f}ms, {len(big)/1024:.0f}KB")

# health shows strokes
h = json.loads(http("/health", timeout=2).read())
check("health stroke count", h.get("strokes", 0) >= 208, f"{h.get('strokes')} strokes")

# ── 7. Full tool round-trip via shim (with image) ──
print("\n[7] tools/call get_handwriting via shim")
shim2 = subprocess.Popen(
    [PY, str(PKG / "mcp_shim.py")],
    stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
    text=True, encoding="utf-8",
)
shim2.stdin.write(json.dumps({"jsonrpc": "2.0", "id": 1, "method": "initialize",
                              "params": {"protocolVersion": "2024-11-05"}}) + "\n")
shim2.stdin.flush()
shim2.stdout.readline()
t0 = time.time()
shim2.stdin.write(json.dumps({
    "jsonrpc": "2.0", "id": 2, "method": "tools/call",
    "params": {"name": "get_handwriting", "arguments": {}}}) + "\n")
shim2.stdin.flush()
resp = json.loads(shim2.stdout.readline())
fetch_ms = (time.time() - t0) * 1000
content = resp.get("result", {}).get("content", [])
img = next((c for c in content if c.get("type") == "image"), None)
check("get_handwriting returns image", img is not None and len(img.get("data", "")) > 1000,
      f"{fetch_ms:.0f}ms round-trip, {len(img['data'])//1024 if img else 0}KB b64")
check("fetch < 1500ms", fetch_ms < 1500, f"{fetch_ms:.0f}ms")

# save_snapshot (Codex fallback path)
shim2.stdin.write(json.dumps({
    "jsonrpc": "2.0", "id": 3, "method": "tools/call",
    "params": {"name": "save_snapshot", "arguments": {}}}) + "\n")
shim2.stdin.flush()
resp = json.loads(shim2.stdout.readline())
text = (resp.get("result", {}).get("content") or [{}])[0].get("text", "")
check("save_snapshot writes file", (DATA / "snapshot.png").exists(), text.split("\n")[0])

# clear canvas
shim2.stdin.write(json.dumps({
    "jsonrpc": "2.0", "id": 4, "method": "tools/call",
    "params": {"name": "clear_canvas", "arguments": {}}}) + "\n")
shim2.stdin.flush()
resp = json.loads(shim2.stdout.readline())
h = json.loads(http("/health", timeout=2).read())
check("clear_canvas", h.get("strokes") == 0)

# get_connection_info
shim2.stdin.write(json.dumps({
    "jsonrpc": "2.0", "id": 5, "method": "tools/call",
    "params": {"name": "get_connection_info", "arguments": {}}}) + "\n")
shim2.stdin.flush()
resp = json.loads(shim2.stdout.readline())
content = resp.get("result", {}).get("content", [])
has_qr = any(c.get("type") == "image" for c in content)
url_text = content[0].get("text", "") if content else ""
check("get_connection_info (URL + QR)", "http://" in url_text and has_qr,
      url_text.split("\n")[0][:60])

shim2.stdin.close()
shim2.wait(timeout=5)

# ── 8. Graceful shutdown ──
print("\n[8] Graceful shutdown")
http("/shutdown", timeout=2, headers={"X-Passpaper-Token": token()}).read()
time.sleep(2)
check("daemon stops gracefully", not daemon_alive())
check("backup saved", backup.exists(), f"{backup.stat().st_size if backup.exists() else 0} bytes")

# ── Summary ──
print("\n== Summary ==")
failed = [r for r in results if not r[1] and r[3]]
warned = [r for r in results if not r[1] and not r[3]]
print(f"  {len(results) - len(failed) - len(warned)} passed, {len(warned)} warnings, {len(failed)} FAILED")
sys.exit(1 if failed else 0)
