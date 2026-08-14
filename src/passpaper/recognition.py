#!/usr/bin/env python3
"""
PassPaper — pluggable handwriting recognition
===================================================

Design goal: let the user *optionally* attach a LOCAL model (e.g. Qwen2.5-VL
served by ollama / llama.cpp / vLLM, or PaddleOCR-VL / GLM-OCR) so that
**Chinese cursive handwriting + math formulas** are turned into structured
text / LaTeX *before* the AI agent sees the image.

If no local model is configured, PassPaper gracefully falls back to the
"agent vision" default — Claude / Codex read the PNG directly, exactly as the
default behavior does. Nothing breaks; the recognition tool just explains the
fallback.

This is the moat we are building (see REFERENCES.md and the PRD): local,
private, CJK + formula aware. The contract below is stable; the concrete model
backends are wired via environment variables so the core stays dependency-free.

Configure a local VLM:
  export PASSPAPER_RECOGNIZER_ENDPOINT=http://127.0.0.1:11434/v1
  export PASSPAPER_RECOGNIZER_MODEL=qwen2.5-vl:7b
  # optional: export PASSPAPER_RECOGNIZER_KEY=...
"""

from __future__ import annotations

import base64
import json
import os
import re
import urllib.request
from dataclasses import dataclass, field


@dataclass
class RecognitionResult:
    text: str = ""
    latex: str = ""
    confidence: float | None = None
    segments: list = field(default_factory=list)
    engine: str = "none"
    note: str = ""


class BaseRecognizer:
    name = "base"

    def recognize(self, png_bytes: bytes, strokes=None) -> RecognitionResult:
        raise NotImplementedError


class AgentVisionFallback(BaseRecognizer):
    """No local model: the agent's own multimodal vision is the recognizer."""

    name = "agent_vision"

    def recognize(self, png_bytes, strokes=None) -> RecognitionResult:
        return RecognitionResult(
            text="", latex="", confidence=None, engine=self.name,
            note=(
                "未配置本地识别模型；请在 Agent 端直接读取图片（递纸默认行为）。"
                " 设置 PASSPAPER_RECOGNIZER_ENDPOINT 后将自动走本地 VLM。"
            ),
        )


class LocalVLMRecognizer(BaseRecognizer):
    """
    Calls a local OpenAI-compatible vision endpoint
    (ollama / llama.cpp / vLLM / LM Studio). Pure stdlib — no SDK dependency.
    """

    name = "local_vlm"

    def __init__(self, endpoint: str, model: str = "", api_key: str = "",
                 prompt: str = (
                     "请识别这张手写图片中的文字与公式。"
                     "用中文输出可阅读文本；公式请用 LaTeX 表示（行内用 $...$，"
                     "独立公式用 $$...$$）。不要编造看不清的内容。"
                 )):
        self.endpoint = endpoint.rstrip("/")
        self.model = model
        self.api_key = api_key
        self.prompt = prompt

    def recognize(self, png_bytes, strokes=None) -> RecognitionResult:
        try:
            b64 = base64.b64encode(png_bytes).decode("ascii")
            payload = {
                "model": self.model or "local",
                "messages": [{
                    "role": "user",
                    "content": [
                        {"type": "text", "text": self.prompt},
                        {"type": "image_url",
                         "image_url": {"url": f"data:image/png;base64,{b64}"}},
                    ],
                }],
                "temperature": 0.1,
            }
            data = json.dumps(payload).encode("utf-8")
            headers = {"Content-Type": "application/json"}
            if self.api_key:
                headers["Authorization"] = f"Bearer {self.api_key}"
            req = urllib.request.Request(
                self.endpoint + "/chat/completions", data=data,
                headers=headers, method="POST")
            with urllib.request.urlopen(req, timeout=30) as r:
                resp = json.loads(r.read().decode("utf-8"))
            content = resp["choices"][0]["message"]["content"]
            return self._parse(content)
        except Exception as e:  # noqa: BLE001 — surface as a soft result
            return RecognitionResult(engine=self.name,
                                     note=f"本地 VLM 调用失败: {e}")

    def _parse(self, content: str) -> RecognitionResult:
        latex = []
        text = content
        for m in re.findall(r"\$\$(.+?)\$\$", content, re.S):
            latex.append(m.strip())
            text = text.replace(f"$${{m}}$$".format(m=m), "")
        for m in re.findall(r"(?<!\$)\$([^$]+?)\$(?!\$)", content):
            latex.append(m.strip())
            text = text.replace(f"${m}$", "")
        return RecognitionResult(
            text=text.strip(),
            latex="\n".join(latex),
            confidence=None,
            engine=self.name,
        )


def get_recognizer() -> BaseRecognizer:
    """Pick a recognizer from the environment; default to the safe fallback."""
    endpoint = os.environ.get("PASSPAPER_RECOGNIZER_ENDPOINT")
    if endpoint:
        return LocalVLMRecognizer(
            endpoint=endpoint,
            model=os.environ.get("PASSPAPER_RECOGNIZER_MODEL", ""),
            api_key=os.environ.get("PASSPAPER_RECOGNIZER_KEY", ""),
        )
    return AgentVisionFallback()
