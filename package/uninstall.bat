@echo off
rem archinorm 技能卸载：把技能目录改名移走，不删除任何文件，可随时手动恢复
setlocal
chcp 65001 >nul 2>&1

set "DST=%USERPROFILE%\.workbuddy\skills\archinorm"

if not exist "%DST%" (
  echo [提示] 未发现已安装的 archinorm 技能：%DST%
  echo.
  pause
  exit /b 0
)

set "TS="
for /f %%i in ('powershell -NoProfile -Command "Get-Date -Format yyyyMMdd-HHmmss" 2^>nul') do set "TS=%%i"
if not defined TS set "TS=removed"

echo 将把以下目录改名移走（不删除，可手动改回）：
echo   %DST%
echo       -^>  %DST%.removed-%TS%
echo.
choice /C YN /M "确认卸载"
if errorlevel 2 exit /b 0

move "%DST%" "%DST%.removed-%TS%" >nul
if errorlevel 1 (
  echo [错误] 改名失败，可能技能正在被占用。请先关闭 WorkBuddy 再试。
  echo.
  pause
  exit /b 3
)

echo [完成] 已移走。需要恢复时把上面的目录改回 archinorm 即可。
echo.
pause
