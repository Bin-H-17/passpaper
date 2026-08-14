## What

Briefly, what does this PR change and why?

## Checklist

- [ ] I added/updated the new runtime module to `BUNDLE_FILES` in `common.py`
      (if it is imported by daemon/shim at runtime).
- [ ] If I added an MCP tool, it exists in **all three** places:
  daemon `tool_<name>()`, `dispatch_tool()` route, and `mcp_shim.py` `TOOLS`.
- [ ] `python scripts/e2e_test.py` passes.
- [ ] `python tests/test_recorder_recognition.py` passes (if recorder/recognition touched).
- [ ] No new dependency added to `mcp_shim.py` / `common.py` (they must stay stdlib-only).
- [ ] Logging goes to the file, never per-stroke `print` to stderr.

## Notes for reviewer

Anything the reviewer should pay special attention to.
