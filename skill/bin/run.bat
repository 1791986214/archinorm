@echo off
rem archinorm 引擎启动器（Windows）
rem 依次尝试：技能自带虚拟环境 -> WB_PYTHON -> py -3 -> python
setlocal
chcp 65001 >nul 2>&1
set "PYTHONUTF8=1"
set "PYTHONIOENCODING=utf-8"
set "HERE=%~dp0"

set "PY="
if exist "%HERE%.venv\Scripts\python.exe" set "PY=%HERE%.venv\Scripts\python.exe"
if not defined PY if defined WB_PYTHON if exist "%WB_PYTHON%" set "PY=%WB_PYTHON%"
if not defined PY where py >nul 2>&1 && set "PY=py"
if not defined PY where python >nul 2>&1 && set "PY=python"

if not defined PY (
  echo [archinorm] 找不到 Python。请安装 Python 3.9+ 并勾选 "Add python.exe to PATH"。
  echo [archinorm] 下载： https://www.python.org/downloads/windows/
  exit /b 2
)

rem —— 每天最多一次的版本自检（静默、非阻塞；未配置更新源时立即返回，不联网）——
set "RUNPY=%PY%"
if /i "%PY%"=="py" set "RUNPY=py -3"
%RUNPY% "%HERE%skillup.py" --quiet check 1>&2 2>nul

if /i "%PY%"=="py" (
  py -3 "%HERE%archinorm.py" %*
) else (
  "%PY%" "%HERE%archinorm.py" %*
)
exit /b %ERRORLEVEL%
