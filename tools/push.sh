#!/bin/sh
# 一键把仓库推到 GitHub。用法： ./tools/push.sh <owner> [repo]
set -e
OWNER="${1:-1791986214}"
REPO="${2:-archinorm}"
DIR="$(cd "$(dirname "$0")/.." && pwd)"
cd "$DIR"
git init -q 2>/dev/null || true
git add -A
git -c user.name="${GIT_NAME:-archinorm}" \
    -c user.email="${GIT_EMAIL:-archinorm@local}" \
    commit -qm "release: v$(cat VERSION) — 渲染器重做 + 技能自动更新" || true
git branch -M main
git remote remove origin 2>/dev/null || true
git remote add origin "https://github.com/$OWNER/$REPO.git"
echo "推送到 https://github.com/$OWNER/$REPO ..."
git push -u origin main
echo "完成。仓库： https://github.com/$OWNER/$REPO"
