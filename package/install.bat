@echo off
rem archinorm 架构框架技能 —— 一键安装到当前用户的 WorkBuddy 技能目录
rem 原则：只新增，不删除。已存在的旧版本一律改名备份。
setlocal
chcp 65001 >nul 2>&1

echo ============================================================
echo   archinorm 架构框架技能  v1.2.0  (Windows)
echo ============================================================
echo.

set "SRC=%~dp0skill"
set "ROOT=%USERPROFILE%\.workbuddy"
set "DST=%ROOT%\skills\archinorm"

if not exist "%SRC%\SKILL.md" (
  echo [错误] 找不到 skill 目录。请先完整解压压缩包再运行本脚本。
  echo.
  pause
  exit /b 2
)

if not exist "%ROOT%" mkdir "%ROOT%"
if not exist "%ROOT%\skills" mkdir "%ROOT%\skills"

set "TS="
for /f %%i in ('powershell -NoProfile -Command "Get-Date -Format yyyyMMdd-HHmmss" 2^>nul') do set "TS=%%i"
if not defined TS set "TS=backup"

if exist "%DST%" (
  echo [提示] 已存在同名技能，先改名备份（不会删除）：
  echo        %DST%.bak-%TS%
  move "%DST%" "%DST%.bak-%TS%" >nul
  echo.
)

echo [1/3] 复制技能文件 ...
xcopy "%SRC%" "%DST%\" /E /I /Y /Q >nul
if errorlevel 1 (
  echo [错误] 复制失败。请确认对 %ROOT% 有写权限后重试。
  echo.
  pause
  exit /b 3
)

echo [2/3] 探测 Python ...
set "PYOK=0"
where py >nul 2>&1 && set "PYOK=1"
if "%PYOK%"=="0" where python >nul 2>&1 && set "PYOK=1"
if "%PYOK%"=="0" (
  echo [警告] 没检测到 Python 3.9+ 。技能已装好，但引擎跑不起来。
  echo        请安装 Python 后重跑本脚本： https://www.python.org/downloads/windows/
  echo.
  pause
  exit /b 4
)

echo [3/3] 自检 ...
call "%DST%\bin\run.bat" help all > "%TEMP%\archinorm_selftest.json" 2>&1
if errorlevel 1 (
  echo [警告] 自检未通过，输出如下：
  type "%TEMP%\archinorm_selftest.json"
) else (
  echo [完成] 自检通过，引擎可用。
)

echo.
echo ------------------------------------------------------------
echo  安装位置： %DST%
echo  调用方式： "%DST%\bin\run.bat" help all
echo  或直接：   python "%DST%\bin\archinorm.py" help all
echo.
echo  重启 WorkBuddy 后技能自动生效。
echo  触发词：架构图 / 结构图 / 模块树 / 项目结构 / archinorm
echo ------------------------------------------------------------
echo.
pause
