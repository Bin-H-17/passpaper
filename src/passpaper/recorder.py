#!/usr/bin/env python3
"""
PassPaper — Session recorder
=================================

Every handwriting session is durably logged as line-delimited JSON (JSONL)
under ``~/.passpaper/sessions/<session_id>.jsonl``.

Why this is a differentiator (see REFERENCES.md):
  - Excalidraw / tldraw proved that *text-based, replayable* scene files are
    the right shape for whiteboards — you can commit them, diff them, and
    restore them.
  - mcp_excalidraw's `describe` showed that a *structured, machine-readable*
    canvas state is what agents actually want.

PassPaper goes one step further: the handwritten sketch becomes a **first-class,
version-controlled artifact**. Close the tab, reboot the machine, `git checkout`
an old session — the ink is still there. Nothing else in this niche does this
(most tools "clear on close" or keep strokes only in memory).

The log captures stroke events (points/color/width/eraser), clear events, and
optional recognition results (so a transcribed sketch is replayable too).
"""

from __future__ import annotations

import json
import re
import threading
import time
from datetime import datetime, timezone
from pathlib import Path

# Session ids are timestamps like "20260806-231610". Only allow a small,
# safe charset and reject anything that could escape the sessions directory.
_SESSION_ID_RE = re.compile(r"^[A-Za-z0-9_.-]{1,64}$")


def _iso_now() -> str:
    return datetime.now(timezone.utc).isoformat()


class SessionRecorder:
    def __init__(self, sessions_dir: Path):
        self.sessions_dir = Path(sessions_dir)
        try:
            self.sessions_dir.mkdir(parents=True, exist_ok=True)
        except Exception:
            pass
        self._lock = threading.Lock()
        self.current_id = self._new_id()
        self._open_current()

    # ── session lifecycle ──
    @staticmethod
    def _new_id() -> str:
        # Local, human-readable, sortable. Collisions across a single machine
        # within the same second are astronomically unlikely for handwriting.
        return datetime.now().strftime("%Y%m%d-%H%M%S")

    def _current_path(self) -> Path:
        return self.sessions_dir / f"{self.current_id}.jsonl"

    def _open_current(self):
        self._append({"event": "session_start", "session_id": self.current_id,
                      "ts": time.time(), "iso": _iso_now()})

    def _append(self, obj: dict):
        # Never let logging break the hot stroke path.
        try:
            with self._lock:
                with open(self._current_path(), "a", encoding="utf-8") as f:
                    f.write(json.dumps(obj, ensure_ascii=False) + "\n")
        except Exception:
            pass

    def record_stroke(self, stroke: dict):
        clean = {
            "points": stroke.get("points", []),
            "color": stroke.get("color", "#000000"),
            "width": stroke.get("width", 3),
            "eraser": bool(stroke.get("eraser")),
        }
        self._append({"event": "stroke", "ts": time.time(), "iso": _iso_now(),
                      "stroke": clean})

    def record_clear(self):
        self._append({"event": "clear", "ts": time.time(), "iso": _iso_now()})

    def record_recognition(self, text, latex=None, confidence=None,
                            corrected=None, engine=None):
        self._append({"event": "recognition", "ts": time.time(), "iso": _iso_now(),
                      "text": text, "latex": latex, "confidence": confidence,
                      "corrected": corrected, "engine": engine})

    def start_new_session(self) -> str:
        with self._lock:
            self.current_id = self._new_id()
            self._open_current()
        return self.current_id

    # ── readers ──
    def _safe_session_path(self, session_id: str) -> Path | None:
        """Resolve ``session_id`` to a path strictly inside ``sessions_dir``.

        Returns ``None`` if the id is malformed or tries to escape the directory
        (path-traversal guard: session_id flows in from MCP tool arguments).
        """
        if not isinstance(session_id, str) or not _SESSION_ID_RE.match(session_id):
            return None
        try:
            base = self.sessions_dir.resolve()
            path = (self.sessions_dir / f"{session_id}.jsonl").resolve()
            path.relative_to(base)  # raises ValueError if it escapes
        except (ValueError, OSError):
            return None
        return path

    def list_sessions(self) -> list[dict]:
        out = []
        try:
            for p in sorted(self.sessions_dir.glob("*.jsonl"), reverse=True):
                sid = p.stem
                strokes = 0
                first = None
                last = None
                try:
                    with open(p, "r", encoding="utf-8") as f:
                        for line in f:
                            try:
                                ev = json.loads(line)
                            except Exception:
                                continue
                            if ev.get("event") == "stroke":
                                strokes += 1
                            t = ev.get("ts")
                            if isinstance(t, (int, float)):
                                if first is None:
                                    first = t
                                last = t
                except Exception:
                    continue
                out.append({
                    "session_id": sid,
                    "strokes": strokes,
                    "started": first,
                    "ended": last,
                    "size_bytes": p.stat().st_size,
                })
        except Exception:
            pass
        return out

    def read_events(self, session_id: str) -> list[dict]:
        path = self._safe_session_path(session_id)
        if path is None or not path.exists():
            return []
        events = []
        try:
            with open(path, "r", encoding="utf-8") as f:
                for line in f:
                    try:
                        events.append(json.loads(line))
                    except Exception:
                        continue
        except Exception:
            pass
        return events

    def strokes_of(self, session_id: str) -> list[dict]:
        return [e["stroke"] for e in self.read_events(session_id)
                if e.get("event") == "stroke"]

    # ── exporters ──
    def export(self, session_id: str, fmt: str) -> dict:
        """Return {format, content, strokes, session_id, error?}."""
        events = self.read_events(session_id)
        if not events:
            return {"format": fmt, "content": "", "strokes": 0,
                    "session_id": session_id, "error": "session not found or empty"}
        strokes = self.strokes_of(session_id)
        if fmt == "jsonl":
            content = "\n".join(json.dumps(e, ensure_ascii=False) for e in events)
        elif fmt == "json":
            content = json.dumps(strokes, ensure_ascii=False, indent=1)
        elif fmt == "excalidraw":
            content = _to_excalidraw(strokes)
        elif fmt == "md":
            content = _to_markdown(events, session_id)
        else:
            return {"format": fmt, "content": "", "strokes": 0,
                    "session_id": session_id, "error": "unknown format"}
        return {"format": fmt, "content": content,
                "strokes": len(strokes), "session_id": session_id}


# ─────────────────────────────────────────────────────────────────────
# Excalidraw scene export (freedraw elements)
# ─────────────────────────────────────────────────────────────────────

def _to_excalidraw(strokes: list[dict]) -> str:
    elements = []
    for i, s in enumerate(strokes):
        pts = s.get("points", [])
        if not pts:
            continue
        xs = [p["x"] for p in pts]
        ys = [p["y"] for p in pts]
        minx, miny = min(xs), min(ys)
        rel = [[round(x - minx, 1), round(y - miny, 1)] for x, y in zip(xs, ys)]
        color = "#ffffff" if s.get("eraser") else s.get("color", "#000000")
        elements.append({
            "type": "freedraw",
            "id": f"pp_{i}_{abs(hash((minx, miny, len(pts)))) % 100000}",
            "x": minx,
            "y": miny,
            "points": rel,
            "strokeColor": color,
            "backgroundColor": "transparent",
            "fillStyle": "solid",
            "strokeWidth": max(1, int(s.get("width", 3))),
            "roughness": 1,
            "opacity": 100,
            "versionNonce": (i * 2654435761) % (2 ** 31),
            "version": 1,
            "isDeleted": False,
            "groupIds": [],
            "boundElements": None,
            "updated": int(time.time() * 1000),
            "link": None,
            "locked": False,
            "pressures": [],
            "simulatePressure": True,
            "lastCommittedPoint": None,
        })
    doc = {
        "type": "excalidraw",
        "version": 2,
        "source": "passpaper",
        "elements": elements,
        "appState": {"gridSize": None, "viewBackgroundColor": "#ffffff"},
        "files": {},
    }
    return json.dumps(doc, ensure_ascii=False)


def _to_markdown(events: list[dict], session_id: str) -> str:
    lines = [
        f"# PassPaper 手写会话 {session_id}",
        "",
        f"- 导出时间: {_iso_now()}",
        "",
    ]
    rec = [e for e in events if e.get("event") == "recognition"]
    if rec:
        lines.append("## 识别文本（本地模型 / 人工校对）")
        for r in rec:
            engine = r.get("engine") or "unknown"
            lines.append(f"- （{engine}）{r.get('text') or ''}")
            if r.get("latex"):
                lines.append(f"  - LaTeX: {r['latex']}")
        lines.append("")
    lines.append("## 笔迹记录")
    for e in events:
        if e.get("event") == "stroke":
            s = e["stroke"]
            kind = "橡皮擦" if s.get("eraser") else "笔画"
            lines.append(f"- {kind} 颜色={s.get('color')} 宽度={s.get('width')} 点数={len(s.get('points', []))}")
        elif e.get("event") == "clear":
            lines.append("- （清空画布）")
    return "\n".join(lines)
