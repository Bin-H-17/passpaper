# Contributing to 递纸 PassPaper

Thanks for your interest in PassPaper! This document explains how to set up a
development environment, run the tests, and the two hard rules you must follow
when touching the runtime code.

## Project shape

```
src/passpaper/        # the package (pure-stdlib shim + daemon)
scripts/             # e2e test + one-click publish script
tests/               # pure-logic smoke tests (no Pillow/network needed)
docs/                # test SOP and other dev docs
```

PassPaper is a **two-layer** design:

- `daemon.py` — an always-on local server (WebSocket + HTTP). It owns the canvas
  and renders every stroke the moment it arrives.
- `mcp_shim.py` — a *thin* MCP server (stdio, pure standard library) that the AI
  client spawns. It forwards tool calls to the daemon over localhost HTTP.

The shim must stay dependency-free so its handshake is fast (<100ms). All heavy
work lives in the daemon.

## Dev setup

```bash
git clone https://github.com/Bin-H-17/passpaper.git
cd passpaper
python -m venv .venv && source .venv/bin/activate   # or: .venv\Scripts\activate
pip install -e ".[dev]"                             # installs deps + the CLI
passpaper setup        # syncs the runtime bundle to ~/.passpaper and registers MCP
passpaper start        # run the daemon in the background
```

## Running the tests

- **End-to-end** (simulates an MCP client + a tablet):
  ```bash
  python scripts/e2e_test.py
  ```
- **recorder / recognition contracts** (pure logic, runs anywhere):
  ```bash
  python tests/test_recorder_recognition.py
  ```

> Note: on some Windows sandboxes, creating a temp directory under a
> non-ASCII path can hang. The pure-logic test uses a repo-local temp dir for
> this reason. On a normal machine it runs fine.

## 🔴 Hard rule #1 — runtime files must be listed in `BUNDLE_FILES`

`common.py` defines `BUNDLE_FILES` — the exact set of files `setup` copies into
`~/.passpaper/` (a pure-ASCII path, so Windows spawn entries never hit encoding
bugs). **If you add a new module that the daemon or shim imports at runtime, you
MUST add it to `BUNDLE_FILES`.** Otherwise the synced bundle will be missing the
file and the import will crash on the user's machine even though it works in
your `src/` tree.

This is how `recorder.py` and `recognition.py` were added in v1.0.0.

## 🔴 Hard rule #2 — adding a new MCP tool is a 3-step change

A tool is only usable once it exists in **all three** places:

1. A `tool_<name>()` function in `daemon.py` that returns the MCP
   `{"content": [...]}` shape.
2. A route in `dispatch_tool()` in `daemon.py`.
3. A tool definition in the `TOOLS` list in `mcp_shim.py` (with a correct
   `inputSchema`).

Miss any one and the tool is invisible to the AI client.

## Style

- `daemon.py` logging goes to a **file**, never per-stroke `print` to stderr
  (a full stderr pipe used to freeze the event loop).
- Recording / recognition must **never** block or crash the hot stroke path —
  all I/O is wrapped so a failed disk write or model call degrades gracefully.
- Keep `mcp_shim.py` and `common.py` pure standard library.

## Pull requests

- Open an issue first for anything non-trivial.
- Keep PRs focused; describe the *why*, not just the *what*.
- Make sure both test suites pass.
- By contributing you agree your contributions are licensed under MIT (same as
  the project).

See [README.md](README.md) and [REFERENCES.md](REFERENCES.md) for the big picture.
