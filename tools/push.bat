@echo off
rem 一键把仓库推到 GitHub。用法： tools\push.bat <owner> [repo]
setlocal
set OWNER=%~1
if "%OWNER%"=="" set OWNER=1791986214
set REPO=%~2
if "%REPO%"=="" set REPO=archinorm
cd /d %~dp0..
if not exist .git git init -q
git add -A
git -c user.name=archinorm -c user.email=archinorm@local commit -qm release
git branch -M main
git remote remove origin 2>nul
git remote add origin https://github.com/%OWNER%/%REPO%.git
echo 推送到 https://github.com/%OWNER%/%REPO% ...
git push -u origin main
pause
