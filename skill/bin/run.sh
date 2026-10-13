#!/bin/sh
# archinorm 引擎启动器（macOS / Linux）
# 优先用技能自带虚拟环境，其次 $WB_PYTHON，最后 PATH 里的 python3
set -e
DIR="$(cd "$(dirname "$0")" && pwd)"
export PYTHONUTF8=1
export PYTHONIOENCODING=utf-8

if [ -x "$DIR/.venv/bin/python" ]; then
  PY="$DIR/.venv/bin/python"
elif [ -n "$WB_PYTHON" ] && [ -x "$WB_PYTHON" ]; then
  PY="$WB_PYTHON"
elif command -v python3 >/dev/null 2>&1; then
  PY="$(command -v python3)"
else
  echo "[archinorm] 找不到 python3，请先安装 Python 3.9+" >&2
  exit 2
fi

# 每天最多一次的版本自检（静默非阻塞；未配更新源时立即返回，不联网）
"$PY" "$DIR/skillup.py" --quiet check >&2 2>/dev/null || true

exec "$PY" "$DIR/archinorm.py" "$@"
