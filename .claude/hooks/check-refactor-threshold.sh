#!/bin/bash
# check-refactor-threshold.sh — Stop Hook
# Checks if modified/new business files exceed the 600-line hard limit.
# Blocks stop and instructs Claude to trigger refactor-expert subagent.
# Skips: automated mode (ralph), subagent context, repeated stop attempts.

set -euo pipefail

INPUT=$(cat)

# ── Skip: automated sessions (ralph scripts, CI/CD) ──
if echo "$INPUT" | grep -qE '"permission_mode"[[:space:]]*:[[:space:]]*"(auto|bypassPermissions|dontAsk)"'; then
  exit 0
fi

# ── Skip: already continued from a previous Stop hook ──
if echo "$INPUT" | grep -qE '"stop_hook_active"[[:space:]]*:[[:space:]]*true'; then
  exit 0
fi

# ── Skip: running inside a subagent (refactor-expert itself) ──
if echo "$INPUT" | grep -qE '"agent_type"[[:space:]]*:[[:space:]]*"[^"]+"'; then
  exit 0
fi

# ── Collect modified and untracked business files ──
FILES=$( { git diff --name-only HEAD 2>/dev/null; git ls-files --others --exclude-standard 2>/dev/null; } | sort -u )

if [ -z "$FILES" ]; then
  exit 0
fi

VIOLATIONS=""

while IFS= read -r f; do
  # Skip non-business files
  case "$f" in
    *.d.ts|*.config.*|*node_modules*|*dist*|*.next*) continue ;;
    *__pycache__*|*.pyc|.venv/*|*.egg-info*) continue ;;
    .docs/*|.claude/*|.git/*) continue ;;
    *.md|*.txt|*.rst|*.adoc|*.pdf) continue ;;
  esac

  # Only check business code files (frontend + backend)
  case "$f" in
    *.tsx|*.ts|*.jsx|*.js|*.py)
      if [ -f "$f" ]; then
        lines=$(wc -l < "$f")
        lines=$((lines))
        if [ "$lines" -gt 600 ]; then
          VIOLATIONS="${VIOLATIONS}  ${f} (${lines} 行)\n"
        fi
      fi
      ;;
  esac
done <<< "$FILES"

if [ -n "$VIOLATIONS" ]; then
  {
    echo "⚠️ 自动拦截：检测到以下文件超过 600 行硬限制，必须委派 refactor-expert 子智能体进行拆分："
    echo -e "$VIOLATIONS"
    echo "请使用 Agent 工具调用 refactor-expert 子智能体重构上述文件。"
  } >&2
  exit 2
fi

exit 0
