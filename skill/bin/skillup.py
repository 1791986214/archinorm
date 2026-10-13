#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
skillup — 通用「Agent 技能」自动更新器（零第三方依赖）

解决什么问题
------------
从乐享知识库（或任何地方）下载安装的技能包，本身是**静态快照**：
乐享只是文件仓库，不会跟踪源仓库的版本。本工具让技能自己盯住
它的 GitHub 源仓库，有新版就拉下来替换，并在替换后跑自检，失败自动回滚。

设计原则
--------
1. 只动自己这个技能目录，绝不碰别处；
2. **绝不删除**任何东西：旧版一律改名成 <名>.bak-<版本>-<时间戳> 挪到一边；
3. 替换后必须跑自检；自检不过 → 自动回滚到刚才那个备份；
4. 网络失败、无网络、仓库不可达 → 静默降级，绝不影响技能正常使用；
5. 检查频率有节流（默认 24 小时），不会每次调用都打网络。

用法
----
  python skillup.py status                 # 看当前版本 / 源仓库 / 上次检查
  python skillup.py check                  # 查有没有新版（只读，不改）
  python skillup.py check --force          # 忽略节流，强制联网查
  python skillup.py update                 # 有新版就更新（备份 + 自检 + 失败回滚）
  python skillup.py update --dry-run       # 只演一遍，不落盘
  python skillup.py rollback               # 回滚到最近一次备份
  python skillup.py backups                # 列出所有备份

manifest.json 里 source 段的写法
--------------------------------
  "source": {
    "type": "github",
    "repo": "owner/name",          // 必填
    "ref": "main",                 // 分支或 tag，默认 main
    "releases": false,             // true: 用 /releases/latest 判版本
    "version_file": "VERSION.txt", // 可选: 读仓库里这个文件的第一个版本号
    "artifact": "archify.zip",     // 可选: 只下这个文件（不放整个仓库）
    "asset_pattern": "*.zip",      // 可选: 从 release 资产里挑匹配的
    "package_subdir": "skill",     // 可选: 压缩包内只取这个子目录
    "strip_root": true,            // 压缩包若多一层根目录，自动剥掉
    "auto_update": false           // true: 定时/启动检查时直接装；false: 只提示
  }
"""

from __future__ import annotations

import argparse
import io
import json
import os
import re
import shutil
import subprocess
import sys
import tarfile
import time
import urllib.error
import urllib.request
import zipfile
from datetime import datetime, timezone
from pathlib import Path

HERE = Path(__file__).resolve().parent
SKILL_DIR = HERE.parent                      # <skill>/bin/skillup.py -> <skill>
MANIFEST = SKILL_DIR / "manifest.json"
STATE = SKILL_DIR / ".state"
HEADERS = {"User-Agent": "skillup/1.0 (+local agent skill updater)",
           "Accept": "application/vnd.github+json"}

THROTTLE_SECONDS = 24 * 3600
DEFAULT_PROXIES = [None, "http://127.0.0.1:7897"]


# --------------------------------------------------------------------------
# 输出
# --------------------------------------------------------------------------

def say(msg, quiet=False):
    if not quiet:
        sys.stderr.write(str(msg) + "\n")


def now_iso():
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def stamp():
    return datetime.now().strftime("%Y%m%d-%H%M%S")


# --------------------------------------------------------------------------
# manifest / state
# --------------------------------------------------------------------------

def load_manifest() -> dict:
    if not MANIFEST.is_file():
        raise SystemExit("skillup: 找不到 manifest.json（应在 %s）" % MANIFEST)
    raw = MANIFEST.read_text(encoding="utf-8")
    try:
        return json.loads(raw)
    except Exception as exc:
        raise SystemExit("skillup: manifest.json 解析失败：%s" % exc)


def save_manifest(m: dict):
    MANIFEST.write_text(json.dumps(m, ensure_ascii=False, indent=2) + "\n",
                        encoding="utf-8")


def state_path(name) -> Path:
    STATE.mkdir(parents=True, exist_ok=True)
    return STATE / name


def write_state(name, value):
    state_path(name).write_text(str(value), encoding="utf-8")


def read_state(name, default=None):
    p = STATE / name
    if not p.is_file():
        return default
    try:
        return p.read_text(encoding="utf-8").strip()
    except Exception:
        return default


def throttled() -> bool:
    p = STATE / "last_check"
    if not p.is_file():
        return False
    try:
        return (time.time() - p.stat().st_mtime) < THROTTLE_SECONDS
    except OSError:
        return False


# --------------------------------------------------------------------------
# 网络（带代理自动回退）
# --------------------------------------------------------------------------

def http_get(url, proxy=None, timeout=25) -> bytes:
    req = urllib.request.Request(url, headers=HEADERS)
    if proxy:
        op = urllib.request.build_opener(
            urllib.request.ProxyHandler({"http": proxy, "https": proxy}))
    else:
        op = urllib.request.build_opener(urllib.request.ProxyHandler({}))
    with op.open(req, timeout=timeout) as resp:
        return resp.read()


def get_with_fallback(url, proxies=None, timeout=25):
    """依次尝试各代理，全部失败抛最后一个异常。返回 (bytes, 使用的代理)。"""
    proxies = proxies if proxies is not None else DEFAULT_PROXIES
    last = None
    for p in proxies:
        try:
            return http_get(url, p, timeout), p
        except Exception as exc:                      # noqa: BLE001
            last = exc
    raise last if last else RuntimeError("no proxy tried")


def proxy_candidates(m: dict, cli_proxy=None) -> list:
    out = []
    if cli_proxy:
        out.append(cli_proxy)
    for key in ("HTTPS_PROXY", "https_proxy", "HTTP_PROXY", "http_proxy"):
        if os.environ.get(key):
            out.append(os.environ[key])
            break
    src = m.get("source") or {}
    if src.get("proxy"):
        out.append(src["proxy"])
    out.append(None)
    out.extend([p for p in DEFAULT_PROXIES if p])
    seen, uniq = set(), []
    for p in out:
        if p not in seen:
            seen.add(p)
            uniq.append(p)
    return uniq


# --------------------------------------------------------------------------
# 远端版本探测
# --------------------------------------------------------------------------

def remote_version(m: dict, cli_proxy=None) -> dict:
    """返回 {version, commit, url, artifact_url, via} 或抛异常。"""
    src = m.get("source") or {}
    repo, ref = src.get("repo"), src.get("ref") or "main"
    if not repo:
        raise RuntimeError("manifest.source.repo 未配置")
    proxies = proxy_candidates(m, cli_proxy)
    info = {"repo": repo, "ref": ref}

    if src.get("releases"):
        data, via = get_with_fallback(
            "https://api.github.com/repos/%s/releases/latest" % repo, proxies)
        rel = json.loads(data.decode("utf-8"))
        info["version"] = (rel.get("tag_name") or "").lstrip("v")
        info["commit"] = rel.get("target_commitish")
        info["published_at"] = rel.get("published_at")
        pat = src.get("asset_pattern")
        asset_url = None
        for a in rel.get("assets") or []:
            nm = a.get("name") or ""
            if not pat or _glob(nm, pat):
                asset_url = a.get("browser_download_url")
                info["artifact_name"] = nm
                break
        info["download_url"] = asset_url or rel.get("zipball_url")
        info["via"] = via
        return info

    # commit 模式
    data, via = get_with_fallback(
        "https://api.github.com/repos/%s/commits?sha=%s&per_page=1" % (repo, ref),
        proxies)
    commits = json.loads(data.decode("utf-8"))
    c = commits[0] if isinstance(commits, list) and commits else {}
    info["commit"] = (c.get("sha") or "")
    info["published_at"] = ((c.get("commit") or {}).get("committer") or {}).get("date")
    info["version"] = info["commit"][:7]
    info["via"] = via

    vf = src.get("version_file")
    if vf:
        raw = "https://raw.githubusercontent.com/%s/%s/%s" % (repo, ref, vf)
        try:
            txt, _ = get_with_fallback(raw, proxies, timeout=15)
            found = re.search(r"\d+\.\d+(\.\d+)?", txt.decode("utf-8", "replace"))
            if found:
                info["version"] = found.group(0)
        except Exception:
            pass

    art = src.get("artifact")
    if art:
        info["artifact_name"] = art
        info["download_url"] = "https://raw.githubusercontent.com/%s/%s/%s" % (
            repo, ref, art)
    else:
        info["download_url"] = "https://codeload.github.com/%s/zip/refs/heads/%s" % (
            repo, ref)
    return info


def _glob(name, pattern) -> bool:
    import fnmatch
    return fnmatch.fnmatch(name, pattern)


# --------------------------------------------------------------------------
# 版本比较
# --------------------------------------------------------------------------

def ver_key(s):
    parts = re.findall(r"\d+", str(s or ""))
    return tuple(int(x) for x in parts) if parts else (0,)


def is_newer(remote, local) -> bool:
    r, l = str(remote or ""), str(local or "")
    if not r:
        return False
    if r == l:
        return False
    rk, lk = ver_key(r), ver_key(l)
    if rk != lk:
        return rk > lk
    return r != l


# --------------------------------------------------------------------------
# 解包 / 安装
# --------------------------------------------------------------------------

def extract_into(blob: bytes, name: str, dest: Path, strip_root=True):
    dest.mkdir(parents=True, exist_ok=True)
    if name.endswith(".tar.gz") or name.endswith(".tgz"):
        with tarfile.open(fileobj=io.BytesIO(blob), mode="r:gz") as tf:
            members = _strip_prefix(tf.getnames(), strip_root)
            for mb in tf.getmembers():
                rel = _rel(mb.name, members)
                if rel is None:
                    continue
                mb2 = tf.extractfile(mb)
                if mb2 is None:
                    continue
                out = dest / rel
                out.parent.mkdir(parents=True, exist_ok=True)
                out.write_bytes(mb2.read())
        return len(list(dest.rglob("*")))
    with zipfile.ZipFile(io.BytesIO(blob)) as zf:
        names = zf.namelist()
        prefix = _common_root(names) if strip_root else ""
        n = 0
        for info in zf.infolist():
            if info.is_dir():
                continue
            rel = info.filename
            if prefix and rel.startswith(prefix):
                rel = rel[len(prefix):]
            if not rel or rel.startswith(".."):
                continue
            out = dest / rel
            out.parent.mkdir(parents=True, exist_ok=True)
            out.write_bytes(zf.read(info))
            n += 1
        return n


def _common_root(names):
    tops = {n.split("/")[0] for n in names if "/" in n}
    return (list(tops)[0] + "/") if len(tops) == 1 else ""


def _strip_prefix(names, strip_root):
    return _common_root(names) if strip_root else ""


def _rel(name, prefix):
    if prefix and name.startswith(prefix):
        name = name[len(prefix):]
    return name or None


def backups() -> list:
    parent = SKILL_DIR.parent
    out = []
    for p in parent.iterdir() if parent.is_dir() else []:
        if p.is_dir() and p.name.startswith(SKILL_DIR.name + ".bak-"):
            out.append(p)
    return sorted(out, key=lambda p: p.name, reverse=True)


def apply_update(m, info, quiet=False, dry_run=False) -> bool:
    """把远端内容装到技能目录。先整目录搬家备份，再就地覆盖，失败回滚。"""
    name = info.get("artifact_name") or "package.zip"
    say("skillup: 下载 %s" % (info.get("download_url") or ""), quiet)
    if dry_run:
        say("skillup: [dry-run] 跳过实际下载与替换", quiet)
        return True
    blob = http_get(info["download_url"], info.get("via"), timeout=120)

    staging = SKILL_DIR.parent / ("%s.incoming-%s" % (SKILL_DIR.name, stamp()))
    if staging.exists():
        shutil.rmtree(staging)
    extract_into(blob, name, staging, strip_root=m.get("source", {}).get("strip_root", True))

    sub = (m.get("source") or {}).get("package_subdir")
    if sub:
        inner = staging / sub
        if inner.is_dir():
            tmp = staging.parent / (staging.name + ".sub")
            shutil.move(str(inner), str(tmp))
            shutil.rmtree(staging)
            staging = tmp

    if not (staging / "manifest.json").exists() and (SKILL_DIR / "manifest.json").exists():
        shutil.copy2(SKILL_DIR / "manifest.json", staging / "manifest.json")

    backup = SKILL_DIR.parent / ("%s.bak-%s-%s" % (
        SKILL_DIR.name, m.get("version") or "old", stamp()))
    say("skillup: 备份现有版本 -> %s" % backup.name, quiet)
    shutil.move(str(SKILL_DIR), str(backup))
    shutil.move(str(staging), str(SKILL_DIR))

    ok, detail = run_self_test(quiet)
    if not ok:
        say("skillup: 自检未通过（%s），自动回滚" % detail, quiet)
        broken = SKILL_DIR.parent / ("%s.broken-%s" % (SKILL_DIR.name, stamp()))
        shutil.move(str(SKILL_DIR), str(broken))
        shutil.move(str(backup), str(SKILL_DIR))
        raise SystemExit("skillup: 已回滚到 %s；新版留在 %s（可人工排查）"
                         % (SKILL_DIR.name, broken.name))

    m2 = load_manifest()
    m2["version"] = info.get("version") or m2.get("version")
    m2.setdefault("installed", {})
    m2["installed"].update({
        "version": info.get("version"),
        "commit": info.get("commit"),
        "at": now_iso(),
        "repo": info.get("repo"),
        "ref": info.get("ref"),
    })
    save_manifest(m2)
    write_state("last_check", now_iso())
    say("skillup: 更新完成 -> v%s" % info.get("version"), quiet)
    return True


def run_self_test(quiet=False):
    m = load_manifest()
    st = m.get("self_test")
    if not st:
        return True, "no self_test declared"
    p = SKILL_DIR / st
    if not p.is_file():
        return True, "self_test missing"
    env = dict(os.environ)
    env["PYTHONUTF8"] = "1"
    env["PYTHONIOENCODING"] = "utf-8"
    r = subprocess.run([sys.executable, str(p)], capture_output=True,
                       text=True, env=env, timeout=300)
    if r.returncode == 0:
        tail = (r.stdout or "").strip().splitlines()
        return True, (tail[-1] if tail else "ok")
    return False, (r.stdout or r.stderr or "")[-300:]


# --------------------------------------------------------------------------
# 命令
# --------------------------------------------------------------------------

def cmd_status(a):
    m = load_manifest()
    src = m.get("source") or {}
    inst = m.get("installed") or {}
    print(json.dumps({
        "skill": m.get("name"),
        "display_name": m.get("display_name"),
        "version": m.get("version"),
        "installed": inst or None,
        "source": {k: src.get(k) for k in
                   ("type", "repo", "ref", "releases", "artifact",
                    "version_file", "auto_update")} or None,
        "last_check": read_state("last_check"),
        "backups": [p.name for p in backups()][:8],
        "throttled": throttled(),
    }, ensure_ascii=False, indent=2))
    return 0


def cmd_check(a):
    m = load_manifest()
    if not (m.get("source") or {}).get("repo"):
        print(json.dumps({"ok": True, "update_available": False,
                          "reason": "manifest.source.repo 未配置，本技能无更新源"},
                         ensure_ascii=False, indent=2))
        return 0
    if throttled() and not a.force:
        print(json.dumps({"ok": True, "skipped": True,
                          "reason": "距上次检查不足 24 小时（--force 可强制）",
                          "last_check": read_state("last_check")},
                         ensure_ascii=False, indent=2))
        return 0
    try:
        info = remote_version(m, a.proxy)
    except Exception as exc:                       # noqa: BLE001
        say("skillup: 检查失败（不影响使用）：%s" % exc, a.quiet)
        print(json.dumps({"ok": True, "reachable": False, "reason": str(exc)},
                         ensure_ascii=False, indent=2))
        return 0
    write_state("last_check", now_iso())
    local = m.get("version")
    newer = is_newer(info.get("version"), local)
    print(json.dumps({
        "ok": True, "reachable": True,
        "local_version": local,
        "remote_version": info.get("version"),
        "remote_commit": info.get("commit"),
        "published_at": info.get("published_at"),
        "update_available": newer,
        "auto_update": bool((m.get("source") or {}).get("auto_update")),
        "action": ("可自动更新" if newer and (m.get("source") or {}).get("auto_update")
                   else "有新版本，运行 skillup.py update 安装" if newer
                   else "已是最新"),
    }, ensure_ascii=False, indent=2))
    if newer and not a.quiet:
        say("skillup: 发现新版本 %s（当前 %s）" % (info.get("version"), local))
    return 0


def cmd_update(a):
    m = load_manifest()
    if not (m.get("source") or {}).get("repo"):
        raise SystemExit("skillup: 本技能未配置更新源（manifest.source.repo）")
    info = remote_version(m, a.proxy)
    local = m.get("version")
    if not a.force and not is_newer(info.get("version"), local):
        print(json.dumps({"ok": True, "updated": False,
                          "version": local, "reason": "已是最新"},
                         ensure_ascii=False, indent=2))
        return 0
    done = apply_update(m, info, a.quiet, a.dry_run)
    print(json.dumps({"ok": True, "updated": bool(done),
                      "from": local, "to": info.get("version"),
                      "dry_run": bool(a.dry_run)},
                     ensure_ascii=False, indent=2))
    return 0


def cmd_rollback(a):
    bs = backups()
    if not bs:
        raise SystemExit("skillup: 没有可用备份")
    b = bs[0]
    broken = SKILL_DIR.parent / ("%s.replaced-%s" % (SKILL_DIR.name, stamp()))
    shutil.move(str(SKILL_DIR), str(broken))
    shutil.move(str(b), str(SKILL_DIR))
    print(json.dumps({"ok": True, "rolled_back_from": broken.name,
                      "restored": SKILL_DIR.name},
                     ensure_ascii=False, indent=2))
    return 0


def cmd_backups(a):
    for p in backups():
        n = p / "manifest.json"
        v = ""
        if n.is_file():
            try:
                v = json.loads(n.read_text(encoding="utf-8")).get("version", "")
            except Exception:
                v = "?"
        print("%-52s  v%s" % (p.name, v))
    return 0


def cmd_selftest(a):
    ok, detail = run_self_test(a.quiet)
    print(json.dumps({"ok": ok, "detail": detail}, ensure_ascii=False, indent=2))
    return 0 if ok else 1


def main(argv=None):
    ap = argparse.ArgumentParser(prog="skillup", description="Agent 技能自动更新器")
    ap.add_argument("--quiet", action="store_true", help="安静模式")
    ap.add_argument("--proxy", help="显式指定 HTTP 代理，如 http://127.0.0.1:7897")
    sub = ap.add_subparsers(dest="cmd", required=True)

    p = sub.add_parser("status"); p.set_defaults(fn=cmd_status)
    p = sub.add_parser("check")
    p.add_argument("--force", action="store_true", help="忽略 24 小时节流")
    p.set_defaults(fn=cmd_check)
    p = sub.add_parser("update")
    p.add_argument("--force", action="store_true")
    p.add_argument("--dry-run", action="store_true")
    p.set_defaults(fn=cmd_update)
    p = sub.add_parser("rollback"); p.set_defaults(fn=cmd_rollback)
    p = sub.add_parser("backups"); p.set_defaults(fn=cmd_backups)
    p = sub.add_parser("selftest"); p.set_defaults(fn=cmd_selftest)

    a = ap.parse_args(argv)
    return a.fn(a)


if __name__ == "__main__":
    sys.exit(main())
