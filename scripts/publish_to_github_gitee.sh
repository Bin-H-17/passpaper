#!/usr/bin/env bash
# publish_to_github_gitee.sh — 一键把递纸 PassPaper 发布到 GitHub（主）+ Gitee（镜像）
# 用法（在 Git Bash 中，项目根目录运行）：  bash scripts/publish_to_github_gitee.sh
# 前置：
#   1. 已安装 git
#   2. 已 `gh auth login`（GitHub CLI）
#   3. Gitee 镜像部分：先在 gitee.com 建同名空仓库，并设置环境变量 GITEE_USER / GITEE_TOKEN
set -euo pipefail

REPO_NAME="passpaper"
GH_USER="${GH_USER:-passpaper-community}"
REMOTE_URL="https://github.com/${GH_USER}/${REPO_NAME}.git"
GITEE_USER="${GITEE_USER:-$GH_USER}"
GITEE_URL="https://${GITEE_USER}:${GITEE_TOKEN:-<token>}@gitee.com/${GITEE_USER}/${REPO_NAME}.git"
TAG="v1.0.0"

echo "==> 1. 校验环境"
command -v git >/dev/null || { echo "需要 git"; exit 1; }
command -v gh  >/dev/null || { echo "需要 GitHub CLI (gh)，请先安装并 gh auth login"; exit 1; }
gh auth status >/dev/null 2>&1 || { echo "请先执行 gh auth login"; exit 1; }

echo "==> 2. 初始化仓库（如尚未）"
if [ ! -d .git ]; then git init -q && git branch -m main; fi

echo "==> 3. 暂存（.gitignore 已排除敏感/内部文件：.mcp.json、deliverables/、PASSPAPER_TECH_OVERVIEW.txt、__pycache__ 等）"
git add -A
if git diff --cached --quiet; then
  echo "没有可提交的改动，跳过 commit"
else
  git commit -m "chore: prepare PassPaper v1.0.0 for open source (MIT)

- v4 daemon + 极薄 MCP shim 架构（实测 ~25ms 取图、MCP 握手 <100ms）
- v1.0.0 差异化：手写会话可回溯（JSONL 录制 + 多格式导出）+ 可插拔中文/公式识别管线
- 署名式借鉴文档 REFERENCES.md（法律审慎 + 社区规范）
- 清理 v3 遗留与脱敏"
fi

echo "==> 4. 创建 GitHub 仓库并推送"
if ! git remote get-url origin >/dev/null 2>&1; then
  gh repo create "$REPO_NAME" --public \
    --description "递纸 PassPaper — 把平板手写实时喂给你的本地 AI 编码助手 (Claude Code / Codex)" \
    --homepage "https://github.com/${GH_USER}/${REPO_NAME}" \
    --source . --push --main branch=main || git remote add origin "$REMOTE_URL"
fi
git push -u origin main

echo "==> 5. 打标签并发布 release"
git tag -a "$TAG" -m "PassPaper v1.0.0 — real-time tablet handwriting to local AI agents, with replayable sessions & pluggable CJK/formula recognition" || true
git push origin "$TAG" || true
gh release create "$TAG" --title "PassPaper $TAG" \
  --notes "v1.0.0 公开版本：常驻 daemon + 极薄 MCP shim（实时/稳定/私密）；新增手写会话可回溯（JSONL 录制 + md/jsonl/json/excalidraw 导出）与可插拔中文/公式识别管线（本地 VLM，无模型时优雅回退）。详见 README 与 REFERENCES.md。" || true

echo "==> 6. Gitee 镜像"
if [ -n "${GITEE_TOKEN:-}" ]; then
  git remote add gitee "$GITEE_URL" 2>/dev/null || git remote set-url gitee "$GITEE_URL"
  git push -u gitee main
  git push gitee "$TAG" || true
  echo "Gitee 镜像完成：https://gitee.com/${GITEE_USER}/${REPO_NAME}"
else
  echo "未设置 GITEE_TOKEN，跳过自动推送。手动步骤："
  echo "  1) 在 gitee.com 建空仓库 ${REPO_NAME}"
  echo "  2) git remote add gitee https://gitee.com/${GITEE_USER}/${REPO_NAME}.git"
  echo "  3) git push --mirror gitee"
fi

echo "==> 完成。GitHub: $REMOTE_URL"
