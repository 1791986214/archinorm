#!/bin/sh
# 项目框架·归一化框架图构建器 —— 一键更新（macOS / Linux）
# 流程：查远端 -> 备份 -> 替换 -> 自检 -> 失败自动回滚
set -e
DIR="$(cd "$(dirname "$0")" && pwd)"
export PYTHONUTF8=1 PYTHONIOENCODING=utf-8
SKILL="$DIR/skill"

if [ -x "$SKILL/bin/.venv/bin/python" ]; then
  PY="$SKILL/bin/.venv/bin/python"
elif [ -n "$WB_PYTHON" ] && [ -x "$WB_PYTHON" ]; then
  PY="$WB_PYTHON"
elif command -v python3 >/dev/null 2>&1; then
  PY="$(command -v python3)"
else
  echo "[archinorm] 找不到 python3" >&2
  exit 2
fi

echo "============================================================"
echo "  技能自动更新"
echo "============================================================"
"$PY" "$SKILL/bin/skillup.py" status
echo
"$PY" "$SKILL/bin/skillup.py" update
echo
echo "提示：加 --dry-run 可先演一遍不落盘；出问题用 rollback 一键回滚。"
