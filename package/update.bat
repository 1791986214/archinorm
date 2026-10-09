@echo off
rem 项目框架·归一化框架图构建器 —— 一键更新到源仓库最新版
rem 流程：查远端 -> 备份现有版本 -> 替换 -> 跑自检 -> 失败自动回滚
setlocal
chcp 65001 >nul 2>&1
set "PYTHONUTF8=1"
set "PYTHONIOENCODING=utf-8"
set "HERE=%~dp0"

set "PY="
if exist "%HERE%skill\bin\.venv\Scripts\python.exe" set "PY=%HERE%skill\bin\.venv\Scripts\python.exe"
if not defined PY if defined WB_PYTHON if exist "%WB_PYTHON%" set "PY=%WB_PYTHON%"
if not defined PY where py >nul 2>&1 && set "PY=py"
if not defined PY where python >nul 2>&1 && set "PY=python"
if not defined PY (
  echo [archinorm] 找不到 Python，无法执行更新。
  pause
  exit /b 2
)

echo ============================================================
echo   技能自动更新
echo ============================================================
echo.
if /i "%PY%"=="py" (
  py -3 "%HERE%skill\bin\skillup.py" status
  echo.
  py -3 "%HERE%skill\bin\skillup.py" update
) else (
  "%PY%" "%HERE%skill\bin\skillup.py" status
  echo.
  "%PY%" "%HERE%skill\bin\skillup.py" update
)
echo.
echo 提示：加 --dry-run 可先演一遍不落盘；出问题用 rollback 一键回滚。
pause
