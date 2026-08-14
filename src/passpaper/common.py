#!/usr/bin/env python3
"""
PassPaper — shared constants & helpers.
Used by both daemon.py (long-running server) and mcp_shim.py (thin MCP client).
This module is pure stdlib so the shim stays dependency-free and starts fast.
"""

from __future__ import annotations

import json
import os
import secrets
import socket
import sys
from pathlib import Path

VERSION = "1.0.0"

# ── Network ──
PORT = 8765
DAEMON_HOST = f"http://127.0.0.1:{PORT}"

# ── Canonical canvas coordinate space (client normalizes into this) ──
CANVAS_W, CANVAS_H = 2048, 1536

# ── Image output: Claude vision sweet spot; smaller = faster transfer + cheaper ──
MAX_IMAGE_EDGE = 1568

# ── Data directory (runtime state, logs, pairing, runtime bundle) ──
# Override with PASSPAPER_HOME for testing / portable installs.
DATA_DIR = Path(os.environ.get("PASSPAPER_HOME", str(Path.home() / ".passpaper")))
try:
    DATA_DIR.mkdir(exist_ok=True)
except OSError:
    pass

PID_FILE = DATA_DIR / "daemon.pid"
LOG_FILE = DATA_DIR / "daemon.log"
BACKUP_FILE = DATA_DIR / "strokes_backup.json"
PAIRING_FILE = DATA_DIR / "pairing.json"
CONNECTION_FILE = DATA_DIR / "connection.txt"
INFO_FILE = DATA_DIR / "connection_info.txt"
QR_FILE = DATA_DIR / "qrcode.png"
SNAPSHOT_FILE = DATA_DIR / "snapshot.png"

# Runtime bundle location (plain-ASCII path; spawned by CC/Codex/Startup folder)
BUNDLE_FILES = ("daemon.py", "common.py", "mcp_shim.py", "canvas.html",
                "recorder.py", "recognition.py")


def get_local_ip() -> str:
    """Best-effort LAN IP for the tablet URL. No network call beyond UDP connect."""
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        s.connect(("8.8.8.8", 80))
        return s.getsockname()[0]
    except Exception:
        return "127.0.0.1"
    finally:
        s.close()


def load_pairing_token() -> str:
    """
    Persistent pairing token — created once, reused forever.
    This is what makes "pair once, bookmark, write anytime" possible.
    Rotate with `passpaper rotate-token` if it ever leaks.
    """
    try:
        data = json.loads(PAIRING_FILE.read_text(encoding="utf-8"))
        token = data.get("token")
        if token and isinstance(token, str) and len(token) >= 16:
            return token
    except Exception:
        pass
    token = secrets.token_hex(16)  # 128-bit
    try:
        PAIRING_FILE.write_text(json.dumps({"token": token}, indent=2), encoding="utf-8")
    except Exception:
        pass
    return token


def rotate_pairing_token() -> str:
    """Generate a brand-new pairing token (invalidates old bookmarks/QR)."""
    token = secrets.token_hex(16)
    PAIRING_FILE.write_text(json.dumps({"token": token}, indent=2), encoding="utf-8")
    return token


def daemon_http_headers() -> dict:
    """Auth header the shim/CLI uses when calling the daemon's localhost API."""
    return {"X-Passpaper-Token": load_pairing_token(), "Content-Type": "application/json"}


def is_daemon_alive(timeout: float = 0.8) -> bool:
    """Cheap health probe against the local daemon."""
    import urllib.request
    try:
        with urllib.request.urlopen(f"{DAEMON_HOST}/health", timeout=timeout) as r:
            return r.status == 200
    except Exception:
        return False


def sync_runtime_bundle(log=lambda msg: None) -> Path:
    """
    Copy the runtime files (daemon/shim/common/canvas.html) into ~/.passpaper/.

    Why: the project may live under a non-ASCII path. AI clients spawning MCP
    servers and Windows .bat autostart files are both notorious for mangling
    non-ASCII paths. ~/.passpaper is pure ASCII, so every spawn entry point
    (Claude Code global config, Codex config.toml, Startup folder) points there.
    The project src/ remains the development source of truth.
    """
    src_dir = Path(__file__).parent
    import shutil

    for name in BUNDLE_FILES:
        src = src_dir / name
        dst = DATA_DIR / name
        if not src.exists():
            continue
        try:
            if dst.exists() and dst.read_bytes() == src.read_bytes():
                continue
            shutil.copy2(src, dst)
            log(f"bundle: synced {name} -> {dst}")
        except Exception as e:
            log(f"bundle: failed to sync {name}: {e}")
    return DATA_DIR


def find_pythonw() -> str:
    """pythonw.exe next to the current interpreter (no console window)."""
    pyw = Path(sys.executable).with_name("pythonw.exe")
    return str(pyw) if pyw.exists() else sys.executable
