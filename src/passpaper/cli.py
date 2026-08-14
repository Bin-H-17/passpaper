#!/usr/bin/env python3
"""
PassPaper CLI.

Commands:
  passpaper start        Start the daemon (detached, survives terminal/CC restarts)
  passpaper stop         Gracefully stop the daemon (saves strokes first)
  passpaper restart      stop + start
  passpaper status       Show daemon health, tablet count, stroke count
  passpaper url          Print the persistent tablet URL
  passpaper serve        Run the daemon in the FOREGROUND (debugging)
  passpaper mcp          Run the MCP shim (this is what AI clients spawn)
  passpaper setup        One-time: deps + runtime bundle + register with
                         Claude Code AND Codex + firewall check
                         [--autostart also adds daemon to Windows startup]
  passpaper doctor       Diagnose environment
  passpaper rotate-token Invalidate the current pairing link, issue a new one
  passpaper sessions      List / show / export recorded handwriting sessions
  passpaper recognize    Run local handwriting recognition on the canvas
"""

from __future__ import annotations

import base64
import json
import os
import re
import subprocess
import sys
import time
import urllib.request
from pathlib import Path

try:
    from .common import (
        CONNECTION_FILE, DAEMON_HOST, DATA_DIR, PID_FILE, PORT, VERSION,
        daemon_http_headers, find_pythonw, get_local_ip, is_daemon_alive,
        load_pairing_token, rotate_pairing_token, sync_runtime_bundle,
    )
except ImportError:
    from common import (
        CONNECTION_FILE, DAEMON_HOST, DATA_DIR, PID_FILE, PORT, VERSION,
        daemon_http_headers, find_pythonw, get_local_ip, is_daemon_alive,
        load_pairing_token, rotate_pairing_token, sync_runtime_bundle,
    )

try:
    from .recorder import SessionRecorder
    from .recognition import get_recognizer
except ImportError:
    from recorder import SessionRecorder  # type: ignore
    from recognition import get_recognizer  # type: ignore


def _fwd(p) -> str:
    """Forward-slash path string (safest for JSON/TOML configs on Windows)."""
    return Path(p).as_posix()


def _spawn_detached(argv: list[str], log_name: str):
    log_fh = open(DATA_DIR / log_name, "ab")
    creationflags = 0
    if os.name == "nt":
        creationflags = (
            getattr(subprocess, "DETACHED_PROCESS", 0x00000008)
            | getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0x00000200)
            | getattr(subprocess, "CREATE_NO_WINDOW", 0x08000000)
        )
    return subprocess.Popen(
        argv, stdin=subprocess.DEVNULL, stdout=log_fh, stderr=log_fh,
        creationflags=creationflags, close_fds=True,
    )


def _wait_alive(timeout: float = 8.0) -> bool:
    deadline = time.time() + timeout
    while time.time() < deadline:
        if is_daemon_alive(timeout=0.5):
            return True
        time.sleep(0.3)
    return False


# ── daemon lifecycle ────────────────────────────────────────────────

def cmd_start() -> int:
    if is_daemon_alive():
        print(f"  [OK] daemon already running — {DATA_DIR / 'connection.txt'}")
        print(f"       {_current_url()}")
        return 0
    print("  Syncing runtime bundle to ~/.passpaper/ ...")
    sync_runtime_bundle(log=lambda m: print(f"    {m}"))
    daemon_py = DATA_DIR / "daemon.py"
    if not daemon_py.exists():
        print("  [FAIL] runtime bundle missing daemon.py")
        return 1
    print("  Starting daemon (detached)...")
    _spawn_detached([find_pythonw(), str(daemon_py)], "daemon.spawn.log")
    if _wait_alive():
        print(f"  [OK] daemon v{VERSION} is up")
        print(f"  Tablet URL: {_current_url()}")
        print("  (Bookmark it on your tablet — the pairing is persistent.)")
        return 0
    print("  [FAIL] daemon did not come up. See ~/.passpaper/daemon.spawn.log")
    return 1


def cmd_stop() -> int:
    if not is_daemon_alive():
        print("  daemon is not running.")
        try:
            PID_FILE.unlink(missing_ok=True)
        except Exception:
            pass
        return 0
    # Graceful: ask the daemon to save + exit.
    try:
        req = urllib.request.Request(
            f"{DAEMON_HOST}/shutdown", headers=daemon_http_headers(), method="GET")
        urllib.request.urlopen(req, timeout=2).read()
    except Exception:
        pass
    deadline = time.time() + 5
    while time.time() < deadline:
        if not is_daemon_alive(timeout=0.5):
            print("  [OK] daemon stopped gracefully (strokes saved).")
            return 0
        time.sleep(0.3)
    # Fallback: kill by PID file (never a blind netstat scan).
    try:
        pid = int(PID_FILE.read_text().strip())
        if os.name == "nt":
            subprocess.run(["taskkill", "/PID", str(pid), "/F"], capture_output=True)
        else:
            os.kill(pid, 9)
        print(f"  [WARN] daemon did not stop gracefully; killed PID {pid}.")
    except Exception as e:
        print(f"  [FAIL] could not stop daemon: {e}")
        return 1
    try:
        PID_FILE.unlink(missing_ok=True)
    except Exception:
        pass
    return 0


def cmd_restart() -> int:
    cmd_stop()
    return cmd_start()


def cmd_status() -> int:
    if not is_daemon_alive():
        print("  daemon: NOT running  (start it with `passpaper start`)")
        return 1
    try:
        with urllib.request.urlopen(f"{DAEMON_HOST}/health", timeout=2) as r:
            h = json.loads(r.read().decode("utf-8"))
        print(f"  daemon:   v{h.get('version')} up {h.get('uptime_s')}s")
        print(f"  strokes:  {h.get('strokes')} (revision {h.get('revision')})")
        print(f"  tablets:  {h.get('tablets')} connected")
        print(f"  url:      {_current_url()}")
        return 0
    except Exception as e:
        print(f"  health check failed: {e}")
        return 1


def cmd_url() -> int:
    print(_current_url())
    return 0


def _current_url() -> str:
    try:
        return CONNECTION_FILE.read_text(encoding="utf-8").strip()
    except Exception:
        return f"http://{get_local_ip()}:{PORT}/?token={load_pairing_token()}"


def cmd_serve() -> int:
    """Foreground daemon (Ctrl+C to stop)."""
    os.environ["PASSPAPER_FG"] = "1"
    try:
        from . import daemon
    except ImportError:
        import daemon  # type: ignore
    return daemon.main()


def cmd_mcp() -> int:
    try:
        from . import mcp_shim
    except ImportError:
        import mcp_shim  # type: ignore
    return mcp_shim.main()


# ── setup / registration ────────────────────────────────────────────

def _register_claude(shim_path: Path) -> str:
    cfg = Path.home() / ".claude.json"
    try:
        config = json.loads(cfg.read_text(encoding="utf-8")) if cfg.exists() else {}
    except Exception:
        config = {}
    config.setdefault("mcpServers", {})
    config["mcpServers"]["passpaper"] = {
        "command": _fwd(sys.executable),
        "args": [_fwd(shim_path)],
    }
    cfg.write_text(json.dumps(config, indent=2, ensure_ascii=False), encoding="utf-8")
    return str(cfg)


def _register_codex(shim_path: Path) -> str:
    cfg_dir = Path.home() / ".codex"
    cfg_dir.mkdir(exist_ok=True)
    cfg = cfg_dir / "config.toml"
    text = cfg.read_text(encoding="utf-8") if cfg.exists() else ""
    block = (
        "[mcp_servers.passpaper]\n"
        f'command = "{_fwd(sys.executable)}"\n'
        f'args = ["{_fwd(shim_path)}"]\n'
    )
    pattern = re.compile(r"(?ms)^\[mcp_servers\.passpaper\]\n.*?(?=^\[|\Z)")
    if pattern.search(text):
        text = pattern.sub(block, text)
    else:
        if text and not text.endswith("\n"):
            text += "\n"
        text += "\n" + block
    cfg.write_text(text, encoding="utf-8")
    return str(cfg)


def _setup_autostart() -> str | None:
    """Add daemon to Windows Startup folder (plain-ASCII paths only)."""
    if os.name != "nt":
        return None
    try:
        startup = Path(os.environ["APPDATA"]) / (
            r"Microsoft\Windows\Start Menu\Programs\Startup"
        )
        bat = startup / "passpaper-daemon.bat"
        bat.write_text(
            "@echo off\r\n"
            f'start "" /min "{find_pythonw()}" "{DATA_DIR / "daemon.py"}"\r\n',
            encoding="ascii",
        )
        return str(bat)
    except Exception:
        return None


def cmd_setup(autostart: bool = False) -> int:
    print("=" * 56)
    print(f"  PassPaper v{VERSION} Setup")
    print("=" * 56)

    if sys.version_info < (3, 10):
        print("  [FAIL] Python 3.10+ required")
        return 1
    print(f"  [OK] Python {sys.version_info.major}.{sys.version_info.minor}")

    missing = []
    for mod, pkg in [("websockets", "websockets"), ("PIL", "Pillow"), ("qrcode", "qrcode")]:
        try:
            __import__(mod)
            print(f"  [OK] {pkg}")
        except ImportError:
            missing.append(pkg)
            print(f"  [MISS] {pkg}")
    if missing:
        print(f"  Installing: {', '.join(missing)}")
        subprocess.run([sys.executable, "-m", "pip", "install", *missing])

    print("\n  Syncing runtime bundle to ~/.passpaper/ ...")
    sync_runtime_bundle(log=lambda m: print(f"    {m}"))
    shim_path = DATA_DIR / "mcp_shim.py"
    if not shim_path.exists():
        print("  [FAIL] bundle sync failed — mcp_shim.py missing")
        return 1

    print("\n  Registering MCP server with AI clients:")
    try:
        print(f"    [OK] Claude Code  -> {_register_claude(shim_path)}")
    except Exception as e:
        print(f"    [WARN] Claude Code config: {e}")
    try:
        print(f"    [OK] Codex        -> {_register_codex(shim_path)}")
    except Exception as e:
        print(f"    [WARN] Codex config: {e}")

    if os.name == "nt":
        r = subprocess.run(
            ["netsh", "advfirewall", "firewall", "show", "rule", "name=PassPaper"],
            capture_output=True, text=True,
        )
        if "PassPaper" in r.stdout:
            print("\n  [OK] Firewall rule exists (port 8765)")
        else:
            print("\n  [WARN] No firewall rule. Run once in an ADMIN terminal:")
            print('    netsh advfirewall firewall add rule name="PassPaper" '
                  "dir=in action=allow protocol=TCP localport=8765")

    if autostart:
        bat = _setup_autostart()
        if bat:
            print(f"\n  [OK] Autostart enabled: {bat}")
        else:
            print("\n  [WARN] Autostart setup failed (non-fatal)")

    print("\n" + "=" * 56)
    print("  Setup complete. Next:")
    print("  1. passpaper start            # launch the daemon")
    print("  2. Open Claude Code or Codex, say '我要用递纸'")
    print("  3. Open the tablet URL once, bookmark it — then write anytime")
    print("=" * 56)
    return 0


def cmd_doctor() -> int:
    print("=" * 56)
    print(f"  PassPaper v{VERSION} Doctor")
    print("=" * 56)
    print(f"  Python:  {sys.executable}")
    print(f"  Version: {sys.version.split()[0]}")

    for mod, pkg in [("websockets", "websockets"), ("PIL", "Pillow"), ("qrcode", "qrcode")]:
        try:
            m = __import__(mod)
            print(f"  [OK] {pkg} {getattr(m, '__version__', '?')}")
        except ImportError:
            print(f"  [FAIL] {pkg} missing")

    print(f"  Data dir: {DATA_DIR}")
    for name in ("daemon.py", "mcp_shim.py", "common.py", "canvas.html"):
        mark = "[OK]" if (DATA_DIR / name).exists() else "[MISS]"
        print(f"    {mark} bundle/{name}")

    if is_daemon_alive():
        try:
            with urllib.request.urlopen(f"{DAEMON_HOST}/health", timeout=2) as r:
                h = json.loads(r.read().decode("utf-8"))
            print(f"  [OK] daemon v{h.get('version')} running "
                  f"({h.get('strokes')} strokes, {h.get('tablets')} tablets)")
        except Exception:
            print("  [OK] daemon responding")
    else:
        print("  [INFO] daemon not running (`passpaper start`)")

    shim = _fwd(DATA_DIR / "mcp_shim.py")
    claude = Path.home() / ".claude.json"
    if claude.exists():
        try:
            cfg = json.loads(claude.read_text(encoding="utf-8"))
            entry = cfg.get("mcpServers", {}).get("passpaper", {})
            ok = shim in [str(a) for a in entry.get("args", [])]
            print(f"  {'[OK]' if ok else '[STALE]'} Claude Code MCP registration"
                  + ("" if ok else " — re-run `passpaper setup`"))
        except Exception:
            print("  [WARN] ~/.claude.json unreadable")
    else:
        print("  [WARN] ~/.claude.json not found")

    codex = Path.home() / ".codex" / "config.toml"
    if codex.exists():
        ok = "[mcp_servers.passpaper]" in codex.read_text(encoding="utf-8")
        print(f"  {'[OK]' if ok else '[MISS]'} Codex MCP registration")
    else:
        print("  [INFO] ~/.codex/config.toml not found (Codex not installed?)")

    try:
        token = load_pairing_token()
        print(f"  [OK] pairing token: {token[:8]}… (persistent)")
    except Exception:
        print("  [FAIL] cannot create pairing token")
    return 0


def cmd_rotate_token() -> int:
    token = rotate_pairing_token()
    print(f"  [OK] New pairing token: {token[:8]}…")
    print("  Old tablet links/bookmarks are now invalid.")
    print("  Run `passpaper restart`, then re-open the new URL on your tablet.")
    return 0


# ── sessions / recognition ──────────────────────────────────────────

def _mcp_call(name: str, arguments=None):
    """Call a daemon tool over the local /mcp/call HTTP route (auth'd)."""
    if not is_daemon_alive():
        return None, "daemon not running (`passpaper start`)"
    try:
        from urllib.parse import quote
        q = f"name={name}&args={quote(json.dumps(arguments or {}))}"
        req = urllib.request.Request(
            f"{DAEMON_HOST}/mcp/call?{q}",
            headers=daemon_http_headers(), method="GET")
        with urllib.request.urlopen(req, timeout=5) as r:
            return json.loads(r.read().decode("utf-8")), None
    except Exception as e:  # noqa: BLE001
        return None, str(e)


def _content_text(result) -> str:
    if not isinstance(result, dict):
        return ""
    for item in result.get("content", []) or []:
        if isinstance(item, dict) and item.get("type") == "text":
            return item.get("text", "")
    return ""


def cmd_sessions(args: list[str]) -> int:
    """Inspect / manage recorded handwriting sessions (offline file reads)."""
    sub = args[0] if args else "list"
    sess_dir = DATA_DIR / "sessions"
    rec = SessionRecorder(sess_dir)

    if sub == "list":
        rows = rec.list_sessions()
        if not rows:
            print("  (no sessions yet — open the tablet and draw something)")
            return 0
        print(f"  {'SESSION_ID':<20} {'STROKES':>8}  {'SIZE':>8}")
        for r in rows:
            print(f"  {r['session_id']:<20} {r['strokes']:>8}  {r['size_bytes']:>7}B")
        print(f"\n  {len(rows)} session(s). `passpaper sessions show <id>` to view, "
              "`export <id>` to save.")
        return 0

    if sub == "current":
        print(f"  {rec.current_id}  (latest on disk; equals the live daemon "
              "session until a new one is started elsewhere)")
        return 0

    if sub == "new":
        # The daemon owns the live session; start it there.
        res, err = _mcp_call("start_session")
        if err:
            print(f"  [FAIL] {err}")
            return 1
        print(f"  [OK] {_content_text(res) or 'new session started'}")
        return 0

    if sub == "show":
        sid = args[1] if len(args) > 1 else rec.current_id
        res = rec.export(sid, "md")
        if res.get("error"):
            print(f"  [FAIL] {res['error']}")
            return 1
        print(res["content"])
        return 0

    if sub == "export":
        sid = None
        fmt = "md"
        out = None
        i = 1
        while i < len(args):
            a = args[i]
            if a == "--format" and i + 1 < len(args):
                fmt = args[i + 1]; i += 2; continue
            if a == "--out" and i + 1 < len(args):
                out = args[i + 1]; i += 2; continue
            if not a.startswith("--") and sid is None:
                sid = a
            i += 1
        if sid is None:
            sid = rec.current_id
        res = rec.export(sid, fmt)
        if res.get("error"):
            print(f"  [FAIL] {res['error']}")
            return 1
        if out:
            Path(out).write_text(res["content"], encoding="utf-8")
            print(f"  [OK] wrote {fmt} ({res['strokes']} strokes) -> {out}")
        else:
            print(res["content"])
        return 0

    print("  usage: passpaper sessions list|current|new|show [id]|"
          "export <id> [--format md|jsonl|json|excalidraw] [--out file]")
    return 1


def cmd_recognize(image_path: str | None = None) -> int:
    """Run handwriting recognition on the live canvas or a PNG file."""
    rec = get_recognizer()

    if image_path:
        p = Path(image_path)
        if not p.exists():
            print(f"  [FAIL] image not found: {image_path}")
            return 1
        png = p.read_bytes()
    else:
        if not is_daemon_alive():
            print("  [FAIL] daemon not running. Start it with `passpaper start`,")
            print("         or pass --image <path.png> to recognize a file.")
            return 1
        try:
            req = urllib.request.Request(
                f"{DAEMON_HOST}/snapshot",
                headers=daemon_http_headers(), method="GET")
            with urllib.request.urlopen(req, timeout=5) as r:
                ctype = r.headers.get("Content-Type", "")
                data = r.read()
            png = base64.b64decode(data.decode("ascii")) if "image/png" not in ctype else data
        except Exception as e:
            print(f"  [FAIL] could not fetch canvas: {e}")
            return 1
        if not png:
            print("  [FAIL] canvas is empty — draw something first.")
            return 1

    res = rec.recognize(png)
    print(f"  engine:  {res.engine}")
    if res.text:
        print(f"  text:    {res.text}")
    if res.latex:
        print(f"  latex:   {res.latex}")
    if res.confidence is not None:
        print(f"  conf:    {res.confidence}")
    if res.note:
        print(f"  note:    {res.note}")
    return 0


# ── entry ───────────────────────────────────────────────────────────

USAGE = f"""PassPaper v{VERSION} — let AI agents read your tablet handwriting.

Usage:
  passpaper start / stop / restart / status / url
  passpaper serve          foreground daemon (debug)
  passpaper mcp            MCP shim (spawned by AI clients)
  passpaper setup [--autostart]
  passpaper doctor
  passpaper rotate-token
  passpaper sessions list|current|new|show [id]|export <id> [--format ...] [--out file]
  passpaper recognize [--image <png>]   run local handwriting recognition
"""


def main() -> int:
    argv = sys.argv[1:]
    cmd = argv[0] if argv else "help"
    flags = set(argv[1:])

    if cmd == "start":
        return cmd_start()
    if cmd == "stop":
        return cmd_stop()
    if cmd == "restart":
        return cmd_restart()
    if cmd == "status":
        return cmd_status()
    if cmd == "url":
        return cmd_url()
    if cmd == "serve" or cmd == "daemon":
        return cmd_serve()
    if cmd == "mcp":
        return cmd_mcp()
    if cmd == "setup":
        return cmd_setup(autostart="--autostart" in flags)
    if cmd == "doctor":
        return cmd_doctor()
    if cmd == "rotate-token":
        return cmd_rotate_token()
    if cmd == "sessions":
        return cmd_sessions(argv[1:])
    if cmd == "recognize":
        img = None
        rest = argv[1:]
        for i, a in enumerate(rest):
            if a == "--image" and i + 1 < len(rest):
                img = rest[i + 1]
        return cmd_recognize(img)
    if cmd in ("help", "--help", "-h"):
        print(USAGE)
        return 0
    print(f"Unknown command: {cmd}\n{USAGE}")
    return 1


if __name__ == "__main__":
    sys.exit(main())
