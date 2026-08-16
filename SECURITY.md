# Security Policy

## Overview

PassPaper is a **local-first** tool. It is designed to run entirely on your own
machine and your own LAN:

- The daemon binds `0.0.0.0` so a tablet on your LAN can reach it; the MCP
  shim connects to it from `127.0.0.1`.
- Every WebSocket / HTTP route is authenticated with a **128-bit persistent
  pairing token** (`secrets.token_hex(16)`), stored at `~/.passpaper/pairing.json`.
- There is no account, no cloud, and no outbound network call from the core
  pipeline.

The pairing token is the only secret. Treat it like a password: anyone on your
LAN who obtains it could connect a fake "tablet" and push strokes. Rotate it
with `passpaper rotate-token` if it ever leaks.

## Recognition endpoint is user-configured

The optional local handwriting recognition (`PASSPAPER_RECOGNIZER_ENDPOINT`)
points at **your own** OpenAI-compatible VLM (e.g. ollama / llama.cpp / vLLM on
`127.0.0.1`). PassPaper sends the handwriting image **only** to that endpoint.
Do not point it at an endpoint you do not control — you would be sending your
handwriting off-machine. When the variable is unset, PassPaper does **not** call
any recognition service and simply lets the AI agent read the image directly.

## Supported versions

| Version | Status |
|---------|--------|
| 1.0.x   | Supported |
| < 1.0   | End of life (pre-daemon architecture) |

## Reporting a vulnerability

Please **do not** open a public GitHub issue for security problems.

Instead, report privately via GitHub's
[private vulnerability reporting](https://github.com/Bin-H-17/passpaper/security/advisories/new)
or email the maintainer (see the maintainer section in README). You will receive
an acknowledgement within a few days, and we will coordinate a fix and disclosure
timeline with you.

We will credit reporters who wish to be named.
