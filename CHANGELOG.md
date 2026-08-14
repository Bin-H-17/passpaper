# Changelog

All notable changes to PassPaper are documented here. The format is based on
[Keep a Changelog](https://keepachangelog.com/), and this project adheres to
[Semantic Versioning](https://semver.org/).

> **Version note:** `v1.0.0` is the **first public open-source release**.
> Internally it is the 4th architecture generation (the "v4" daemon + shim
> design), so you will still see "v4 架构" referenced in the README when we talk
> about the design lineage. The public release number starts fresh at `1.0.0`.

## [1.0.0] — 2026-08-07 (first public release)

### Added — core (always-on, dependency-light)
- **v4 architecture**: an always-on `daemon.py` (WebSocket + HTTP, incremental
  in-memory canvas rendering, persistent 128-bit pairing token, PID-file process
  management) + a thin, pure-stdlib `mcp_shim.py` (sub-100ms MCP handshake,
  auto-spawns the daemon). Works with **Claude Code** and **Codex CLI**.
- **Tablet canvas** with canonical 2048×1536 coordinate mapping, offline queue,
  heartbeat, and auto-reconnect with batch replay.
- **CLI** (`passpaper setup/start/stop/restart/status/url/serve/mcp/doctor/
  rotate-token`) with dual Claude Code + Codex registration and optional
  Windows autostart.
- **26-check end-to-end test suite** (`scripts/e2e_test.py`).
- **MIT license** + attribution document `REFERENCES.md` (legal-prudent
  per-item credit of AGPL-3.0 upstreams).

### Added — differentiation layer
- **Replayable handwriting sessions.** Every stroke (and clear / recognition
  event) is durably logged as JSONL under `~/.passpaper/sessions/`. Close the
  tab, reboot, or `git checkout` an old session — the ink is still there.
  - New MCP tools: `list_sessions`, `start_session`, `export_session`.
  - `export_session` supports `md` / `jsonl` / `json` / `excalidraw`
    (Excalidraw/tldraw-replayable) so a sketch becomes a version-controlled
    artifact. This is uncommon in this niche (most tools clear on close).
- **Pluggable Chinese-cursive / formula recognition pipeline.**
  - `recognition.py` with a stable `RecognitionResult` contract and two backends:
    `AgentVisionFallback` (default — the agent reads the image directly, zero
    dependency) and `LocalVLMRecognizer` (OpenAI-compatible local VLM over
    stdlib `urllib`, no SDK).
  - Set `PASSPAPER_RECOGNIZER_ENDPOINT` (+ optional `PASSPAPER_RECOGNIZER_MODEL`
    / `PASSPAPER_RECOGNIZER_KEY`) to turn handwriting into structured text /
    LaTeX *before* the agent sees the image.
  - New MCP tool: `recognize_handwriting` (soft-fails to a helpful note when no
    model is configured).
- **CLI sessions + recognize**: `passpaper sessions list|current|new|show|
  export` and `passpaper recognize [--image <png>]` for offline inspection and
  local-model testing without an AI client.
- Canvas UI buttons: "保存会话" (export current session as Excalidraw) and
  "新建会话" (start a fresh session without losing the old one).

### Notes
- Design influences are credited per-item in [REFERENCES.md](REFERENCES.md)
  (MIT project; legal-prudent attribution of AGPL-3.0 upstreams).

[1.0.0]: https://github.com/passpaper-community/passpaper/releases/tag/v1.0.0
