#!/usr/bin/env python3
"""
Smoke tests for PassPaper v1.0.0 recorder + recognition contracts.

These are pure-logic checks (no Pillow / websockets / network needed), so they
run anywhere — including the sandbox. Run:
    python tests/test_recorder_recognition.py
"""
from __future__ import annotations

import json
import shutil
import sys
from pathlib import Path

# Make the package importable whether run from repo root or src/.
ROOT = Path(__file__).resolve().parent.parent
for cand in (ROOT / "src", ROOT):
    if cand.exists():
        sys.path.insert(0, str(cand))

from passpaper.recorder import SessionRecorder  # noqa: E402
from passpaper.recognition import (  # noqa: E402
    AgentVisionFallback, LocalVLMRecognizer, get_recognizer, RecognitionResult,
)

# NOTE: avoid tempfile.TemporaryDirectory — on this Windows sandbox the system
# %TEMP% directory creation hangs. Use a local, repo-scoped temp dir instead.
_TMP = ROOT / ".test_tmp_sessions"


def _tmp_sessions_dir():
    if _TMP.exists():
        shutil.rmtree(_TMP)
    _TMP.mkdir(parents=True, exist_ok=True)
    return _TMP


def _sample_strokes():
    return [
        {"points": [{"x": 10, "y": 10}, {"x": 20, "y": 25}, {"x": 30, "y": 40}],
         "color": "#000000", "width": 3, "eraser": False},
        {"points": [{"x": 100, "y": 100}, {"x": 120, "y": 110}],
         "color": "#e53935", "width": 5, "eraser": False},
    ]


def test_recorder_roundtrip():
    d = _tmp_sessions_dir()
    rec = SessionRecorder(d)
    for s in _sample_strokes():
        rec.record_stroke(s)
    rec.record_clear()
    rec.record_stroke(_sample_strokes()[0])

    sessions = rec.list_sessions()
    assert len(sessions) == 1, sessions
    assert sessions[0]["strokes"] == 3, sessions[0]

    sid = sessions[0]["session_id"]
    strokes = rec.strokes_of(sid)
    assert len(strokes) == 3
    assert strokes[0]["color"] == "#000000"

    # export formats
    for fmt in ("jsonl", "json", "md", "excalidraw"):
        res = rec.export(sid, fmt)
        assert not res.get("error"), (fmt, res)
        assert res["strokes"] == 3
        assert res["content"]

    # excalidraw must be valid JSON with freedraw elements
    ex = json.loads(rec.export(sid, "excalidraw")["content"])
    assert ex["type"] == "excalidraw"
    assert len(ex["elements"]) == 3
    assert all(e["type"] == "freedraw" for e in ex["elements"])

    # unknown session -> error, not crash
    err = rec.export("nope", "md")
    assert err.get("error")


def test_new_session_isolation():
    d = _tmp_sessions_dir()
    rec = SessionRecorder(d)
    rec.record_stroke(_sample_strokes()[0])
    sid1 = rec.start_new_session()
    rec.record_stroke(_sample_strokes()[1])
    assert len(rec.strokes_of(sid1)) == 1
    sessions = rec.list_sessions()
    assert len(sessions) == 2


def test_recognition_fallback():
    r = get_recognizer()
    assert isinstance(r, AgentVisionFallback)
    res = r.recognize(b"fakepng")
    assert res.engine == "agent_vision"
    assert res.note


def test_local_vlm_parse():
    # No network: just verify the latex/text splitter works on a canned reply.
    rec = LocalVLMRecognizer(endpoint="http://127.0.0.1:1/v1")
    out = rec._parse("你好世界 $$E=mc^2$$ 还有 $x+1$ 结束")
    assert "你好世界" in out.text
    assert "E=mc^2" in out.latex
    assert "x+1" in out.latex
    assert out.engine == "local_vlm"


if __name__ == "__main__":
    test_recorder_roundtrip()
    test_new_session_isolation()
    test_recognition_fallback()
    test_local_vlm_parse()
    print("ALL PASSPAPER v1.0.0 SMOKE TESTS PASSED")
