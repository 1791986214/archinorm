#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
archinorm — 归一化分形模块树构建器（WorkBuddy 移植版）

把代码仓库的架构写成"人机共读"的分形模块树：
每个模块结构完全相同，点开即子层，叶子承载 API。
支持 写时校验 / 全量校验 / 冻结回执 / 单文件交互式下钻渲染图。

移植自 https://github.com/yan-mc/dsh-normify (MIT, yan-mc) 的 DSH 插件版，
将原 31 个 normify_* 工具收敛为同一套 CLI 子命令，去掉 DSH 依赖。

依赖：Python >= 3.9；PyYAML 可选（缺失时自动启用内置迷你解析器，零依赖可跑）
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path


# --------------------------------------------------------------------------
# Windows 兼容：控制台默认 GBK 会把中文 JSON 打崩，强制 UTF-8 收口
# --------------------------------------------------------------------------

def _force_utf8_io():
    for name in ("stdout", "stderr", "stdin"):
        s = getattr(sys, name, None)
        if s is None:
            continue
        try:
            if hasattr(s, "reconfigure"):
                s.reconfigure(encoding="utf-8", errors="replace")
        except Exception:
            pass


_force_utf8_io()


# --------------------------------------------------------------------------
# 内置迷你 YAML 子集解析/序列化（PyYAML 缺失时的兜底）
#
# 为什么：Windows 上 pip 可能被安全软件拦截，也不希望用户装依赖。
# 覆盖范围严格限定为本框架自己写的 frontmatter 子集：
#   普通标量 / 引号标量 / null / 内联映射 {k: v, ...} / 内联数组 [] / 块映射 /
#   块数组 / 数组元素为映射 / 折叠块 >- 与字面块 |-
# 超出子集的写法按普通标量处理，不会静默丢数据。
# --------------------------------------------------------------------------

_BLOCK_MARKS = (">", ">-", ">+", "|", "|-", "|+")


def _mini_split_kv(s: str):
    """按第一个「不在引号内」的冒号切分，返回 (key, rest) 或 (None, None)。"""
    q = None
    for i, ch in enumerate(s):
        if q:
            if ch == q:
                q = None
        elif ch in "\"'":
            q = ch
        elif ch == ":":
            return s[:i], s[i + 1:]
    return None, None


def _mini_split_commas(s: str) -> list:
    out, buf, q = [], [], None
    for ch in s:
        if q:
            buf.append(ch)
            if ch == q:
                q = None
        elif ch in "\"'":
            q = ch
            buf.append(ch)
        elif ch == ",":
            out.append("".join(buf))
            buf = []
        else:
            buf.append(ch)
    if buf:
        out.append("".join(buf))
    return out


def _mini_scalar(s: str):
    s = (s or "").strip()
    if s in ("", "null", "Null", "NULL", "~"):
        return None
    if s == "[]":
        return []
    if s == "{}":
        return {}
    if len(s) >= 2 and s[0] == s[-1] == '"':
        return (s[1:-1].replace('\\"', '"').replace("\\n", "\n")
                .replace("\\\\", "\\"))
    if len(s) >= 2 and s[0] == s[-1] == "'":
        return s[1:-1].replace("''", "'")
    if s.startswith("{") and s.endswith("}"):
        d = {}
        for part in _mini_split_commas(s[1:-1]):
            if not part.strip():
                continue
            k, v = _mini_split_kv(part)
            if k is None:
                continue
            d[k.strip()] = _mini_scalar(v)
        return d
    if s.startswith("[") and s.endswith("]"):
        return [_mini_scalar(x) for x in _mini_split_commas(s[1:-1]) if x.strip()]
    if s in ("true", "True", "yes", "on"):
        return True
    if s in ("false", "False", "no", "off"):
        return False
    if re.fullmatch(r"[-+]?\d+", s):
        return int(s)
    if re.fullmatch(r"[-+]?(\d+\.\d*|\.\d+)([eE][-+]?\d+)?", s):
        return float(s)
    return s


def _mini_dump_scalar(v) -> str:
    if v is None:
        return "null"
    if v is True:
        return "true"
    if v is False:
        return "false"
    if isinstance(v, int):
        return str(v)
    if isinstance(v, float):
        return repr(v)
    s = str(v)
    low = s.lower()
    if (s == "" or s != s.strip() or ":" in s or "#" in s
            or any(c in s for c in '{}[]"\'\n\t')
            or low in ("null", "~", "true", "false", "yes", "no", "on", "off")
            or re.fullmatch(r"[-+]?\d+", s)):
        esc = s.replace("\\", "\\\\").replace('"', '\\"').replace("\n", "\\n")
        return f'"{esc}"'
    return s


def _mini_dump(obj, indent: int = 0) -> str:
    pad = " " * indent
    out = []
    if isinstance(obj, dict):
        for k, v in obj.items():
            if isinstance(v, (dict, list)) and v:
                out.append(f"{pad}{k}:")
                out.append(_mini_dump(v, indent + 2))
            elif isinstance(v, list):
                out.append(f"{pad}{k}: []")
            elif isinstance(v, dict):
                out.append(f"{pad}{k}: {{}}")
            else:
                out.append(f"{pad}{k}: {_mini_dump_scalar(v)}")
    elif isinstance(obj, list):
        for it in obj:
            if isinstance(it, dict) and it:
                items = list(it.items())
                k0, v0 = items[0]
                if isinstance(v0, (dict, list)) and v0:
                    out.append(f"{pad}- {k0}:")
                    out.append(_mini_dump(v0, indent + 4))
                else:
                    out.append(f"{pad}- {k0}: {_mini_dump_scalar(v0)}")
                for k, v in items[1:]:
                    if isinstance(v, (dict, list)) and v:
                        out.append(f"{pad}  {k}:")
                        out.append(_mini_dump(v, indent + 4))
                    else:
                        out.append(f"{pad}  {k}: {_mini_dump_scalar(v)}")
            else:
                out.append(f"{pad}- {_mini_dump_scalar(it)}")
    else:
        out.append(f"{pad}{_mini_dump_scalar(obj)}")
    return "\n".join(out)


def _mini_load(text: str):
    """按缩进递归解析 YAML 子集；超出子集的写法按普通标量处理。"""
    raw = (text or "").replace("\r\n", "\n").replace("\r", "\n").split("\n")
    lines = [(len(l) - len(l.lstrip(" ")), l) for l in raw]
    n = len(lines)
    pos = [0]

    def cur():
        while pos[0] < n:
            _, ln = lines[pos[0]]
            if not ln.strip() or ln.lstrip().startswith("#"):
                pos[0] += 1
            else:
                return lines[pos[0]]
        return None

    def block_scalar(parent_ind: int) -> str:
        parts = []
        while pos[0] < n:
            ind, ln = lines[pos[0]]
            if not ln.strip():
                pos[0] += 1
                if parts:
                    parts.append("")
                continue
            if ind <= parent_ind:
                break
            parts.append(ln.strip())
            pos[0] += 1
        joined = []
        for p in parts:
            if p == "":
                if joined and joined[-1] != "\n":
                    joined.append("\n")
            else:
                if joined and joined[-1] != "\n":
                    joined.append(" ")
                joined.append(p)
        return "".join(joined).strip("\n")

    def parse(ind_min: int):
        c = cur()
        if c is None or c[0] < ind_min:
            return None
        ind0 = c[0]

        if c[1].lstrip().startswith("-"):
            items = []
            while True:
                c = cur()
                if c is None:
                    break
                ind, ln = c
                if ind != ind0 or not ln.lstrip().startswith("-"):
                    break
                rest = ln.lstrip()[1:].strip()
                pos[0] += 1
                if rest == "":
                    items.append(parse(ind0 + 1))
                    continue
                k, v = _mini_split_kv(rest)
                if k is None:
                    items.append(_mini_scalar(rest))
                    continue
                d = {}
                vs = (v or "").strip()
                if vs in _BLOCK_MARKS:
                    d[k.strip()] = block_scalar(ind)
                elif vs == "":
                    nxt = cur()
                    d[k.strip()] = parse(nxt[0]) if (nxt and nxt[0] > ind) else None
                else:
                    d[k.strip()] = _mini_scalar(vs)
                while True:
                    c2 = cur()
                    if c2 is None:
                        break
                    ind2, ln2 = c2
                    if ind2 <= ind or ln2.lstrip().startswith("-"):
                        break
                    k2, v2 = _mini_split_kv(ln2.strip())
                    if k2 is None:
                        pos[0] += 1
                        continue
                    pos[0] += 1
                    v2s = (v2 or "").strip()
                    if v2s in _BLOCK_MARKS:
                        d[k2.strip()] = block_scalar(ind2)
                    elif v2s == "":
                        nxt = cur()
                        d[k2.strip()] = (parse(nxt[0])
                                         if (nxt and nxt[0] > ind2) else None)
                    else:
                        d[k2.strip()] = _mini_scalar(v2s)
                items.append(d)
            return items

        d = {}
        while True:
            c = cur()
            if c is None or c[0] != ind0 or c[1].lstrip().startswith("-"):
                break
            k, v = _mini_split_kv(c[1].strip())
            if k is None:
                pos[0] += 1
                continue
            pos[0] += 1
            vs = (v or "").strip()
            if vs in _BLOCK_MARKS:
                d[k.strip()] = block_scalar(ind0)
            elif vs == "":
                nxt = cur()
                if nxt and nxt[0] > ind0:
                    d[k.strip()] = parse(nxt[0])
                else:
                    d[k.strip()] = None
            else:
                d[k.strip()] = _mini_scalar(vs)
        return d

    result = parse(0)
    return result if isinstance(result, dict) else (result or {})


class _MiniYaml:
    """与 yaml 模块同形的极简替身，覆盖本框架用到的两个方法。"""

    name = "mini"

    @staticmethod
    def safe_load(text, *a, **kw):
        return _mini_load(text)

    @staticmethod
    def safe_dump(obj, *a, **kw):
        return _mini_dump(obj) + "\n"


# --------------------------------------------------------------------------
# YAML 后端选择：优先 PyYAML；缺了就无缝切内置解析器（设 ARCHINORM_NO_PYYAML=1 可强制走兜底）
# --------------------------------------------------------------------------

if os.environ.get("ARCHINORM_NO_PYYAML"):
    yaml = _MiniYaml()
    YAML_BACKEND = "内置迷你解析器（强制）"
else:
    try:
        import yaml  # type: ignore
        YAML_BACKEND = "PyYAML " + str(getattr(yaml, "__version__", "?"))
    except ImportError:  # pragma: no cover
        yaml = _MiniYaml()  # type: ignore
        YAML_BACKEND = "内置迷你解析器"


SCHEMA_VERSION = 1
ENGINE_VERSION = "1.2.0"

ID_SEG = re.compile(r"^[a-z0-9][a-z0-9-]*$")
UID_RE = re.compile(r"^[0-9a-f]{8}$")
SHA1_RE = re.compile(r"^[0-9a-f]{40}$")
HEX_RE = re.compile(r"^[0-9a-f]{8,64}$")
ZERO_SHA = "0" * 40

PROTOCOLS = {
    "http", "ws", "rpc", "amqp", "kafka",
    "mysql", "redis", "file", "grpc", "graphql",
}
DEP_KINDS = {"call", "event", "dataflow", "reference"}
STATES = {"active", "planned", "deprecated"}
VALID_MODES = {"auto", "groups", "layers", "grid"}


class Result:
    """统一输出信封：{"ok", "command", "data", "errors", "warnings"}"""

    def __init__(self, command: str):
        self.command = command
        self.data: dict = {}
        self.errors: list = []
        self.warnings: list = []

    def err(self, code, message, module=None, **evidence):
        item = {"code": code, "message": message}
        if module:
            item["module"] = module
        if evidence:
            item["evidence"] = evidence
        self.errors.append(item)
        return self

    def warn(self, code, message, module=None, **evidence):
        item = {"code": code, "message": message}
        if module:
            item["module"] = module
        if evidence:
            item["evidence"] = evidence
        self.warnings.append(item)
        return self

    def extend(self, other):
        self.errors.extend(other.errors)
        self.warnings.extend(other.warnings)
        return self

    @property
    def ok(self) -> bool:
        return not self.errors

    def emit(self, human=False):
        payload = {
            "ok": self.ok,
            "command": self.command,
            "data": self.data,
            "errors": self.errors,
            "warnings": self.warnings,
        }
        text = (_render_human(payload) + "\n" if human
                else json.dumps(payload, ensure_ascii=False, indent=2) + "\n")
        try:
            sys.stdout.write(text)
        except UnicodeEncodeError:          # 极端老控制台的最后一道保险
            sys.stdout.write(text.encode("utf-8", "replace").decode("utf-8"))
        return 0 if self.ok else 1


def _render_human(payload: dict) -> str:
    out = []
    mark = "OK " if payload["ok"] else "ERR"
    out.append(f"[{mark}] {payload['command']}")
    for k, v in (payload.get("data") or {}).items():
        if isinstance(v, (dict, list)):
            v = json.dumps(v, ensure_ascii=False)
        v = str(v)
        if len(v) > 160:
            v = v[:157] + "..."
        out.append(f"  {k}: {v}")
    for w in payload.get("warnings") or []:
        out.append(f"  WARN {w['code']}: {w['message']}")
    for e in payload.get("errors") or []:
        out.append(f"  ERROR {e['code']}: {e['message']}")
    return "\n".join(out)


# --------------------------------------------------------------------------
# YAML 子集序列化（精确控制 frontmatter 形态）
# --------------------------------------------------------------------------

_AMBIGUOUS = {"null", "~", "true", "false", "yes", "no", "on", "off", "none", ""}
_NUM_RE = re.compile(r"^[-+]?(\d+\.?\d*|\.\d+)([eE][-+]?\d+)?$")
_DATE_RE = re.compile(
    r"^\d{4}-\d{2}-\d{2}([T ]\d{2}:\d{2}(:\d{2}(\.\d+)?)?"
    r"(Z|[-+]\d{2}:?\d{2})?)?$"
)


def _needs_quote(s: str) -> bool:
    if s == "":
        return True
    if s != s.strip():
        return True
    if any(ch in s for ch in "{}[]\"'\n\t"):
        return True
    if ": " in s or s.endswith(":"):
        return True
    if " #" in s:
        return True
    if s[0] in "-?:,[]{}#&*!|>'\"%@`":
        return True
    low = s.lower()
    if low in _AMBIGUOUS:
        return True
    if _NUM_RE.match(s) or _DATE_RE.match(s):
        return True
    return False


def _scalar(v) -> str:
    if v is None:
        return "null"
    if v is True:
        return "true"
    if v is False:
        return "false"
    if isinstance(v, int):
        return str(v)
    if isinstance(v, float):
        return repr(v)
    s = str(v)
    if _needs_quote(s):
        esc = s.replace("\\", "\\\\").replace('"', '\\"').replace("\n", "\\n")
        return f'"{esc}"'
    return s


def _bi_block(key: str, obj, ind: int) -> list:
    """输出 {zh, en} 块映射。

    长文本用 >- 折叠块（strip 模式，单行写，折叠无副作用）：
      - 用 >- 而非 > ，否则解析回来会多一个尾部换行，破坏往返保真；
      - 单行书写，避免折叠把换行转成空格（中文尤其不能多出空格）。
    """
    obj = obj or {}
    lines = [" " * ind + f"{key}:"]
    for k in ("zh", "en"):
        v = obj.get(k)
        v = "" if v is None else str(v)
        if v.endswith("\n") and "\n" not in v[:-1]:
            v = v[:-1]
        if len(v) > 70 and "\n" not in v and not v.startswith(" ") and v == v.rstrip():
            lines.append(" " * (ind + 2) + f"{k}: >-")
            lines.append(" " * (ind + 4) + v)
        else:
            lines.append(" " * (ind + 2) + f"{k}: {_scalar(v)}")
    return lines


def _bi_inline(obj) -> str:
    obj = obj or {}
    return ("{ zh: " + _scalar(obj.get("zh", ""))
            + ", en: " + _scalar(obj.get("en", "")) + " }")


FIELD_ORDER = (
    "uid", "id", "parent", "revision", "updated_at", "fingerprint",
    "state", "repository", "replacement", "tags",
)


def dump_frontmatter(m: dict) -> str:
    lines: list = []
    for f in FIELD_ORDER:
        v = m.get(f)
        if v is None or v == [] or v == "":
            if f == "parent":
                lines.append("parent: null")
            continue
        if f == "tags":
            lines.append("tags:")
            for t in v:
                lines.append(f"  - {_scalar(t)}")
        else:
            lines.append(f"{f}: {_scalar(v)}")

    src = m.get("source")
    if src:
        lines.append("source:")
        for s in src:
            lines.append(f"  - path: {_scalar(s.get('path', ''))}")
            if s.get("line") is not None:
                lines.append(f"    line: {s['line']}")
            if s.get("end_line") is not None:
                lines.append(f"    end_line: {s['end_line']}")
    else:
        lines.append("source: []")

    lines += _bi_block("name", m.get("name"), 0)
    lines += _bi_block("description", m.get("description"), 0)

    if "apis" in m:
        apis = m.get("apis") or []
        if not apis:
            lines.append("apis: []")
        else:
            lines.append("apis:")
            for a in apis:
                lines.append(f"  - protocol: {_scalar(a.get('protocol', ''))}")
                if a.get("method") is not None:
                    lines.append(f"    method: {_scalar(a['method'])}")
                lines.append(f"    path: {_scalar(a.get('path', ''))}")
                lines += _bi_block("description", a.get("description"), 4)

    if "deps" in m:
        deps = m.get("deps") or []
        if not deps:
            lines.append("deps: []")
        else:
            lines.append("deps:")
            for d in deps:
                lines.append(f"  - kind: {_scalar(d.get('kind', ''))}")
                lines.append(f"    to: {_scalar(d.get('to', ''))}")
                if d.get("from_api"):
                    lines.append(f"    from_api: {_scalar(d['from_api'])}")
                if d.get("to_api"):
                    lines.append(f"    to_api: {_scalar(d['to_api'])}")
                if d.get("label"):
                    lines.append(f"    label: {_bi_inline(d['label'])}")
    return "\n".join(lines) + "\n"


def dump_module_file(m: dict, body: str = "") -> str:
    return f"---\n{dump_frontmatter(m)}---\n\n{body or ''}"


def parse_module_file(text: str):
    if not text.startswith("---"):
        raise ValueError("缺少 frontmatter 起始标记 ---")
    end = text.find("\n---", 3)
    if end < 0:
        raise ValueError("frontmatter 未闭合")
    data = yaml.safe_load(text[3:end]) or {}
    if not isinstance(data, dict):
        raise ValueError("frontmatter 不是映射")
    return data, text[end + 4:].lstrip("\n")


# --------------------------------------------------------------------------
# 工具函数
# --------------------------------------------------------------------------

def now_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def gen_uid() -> str:
    return os.urandom(4).hex()


def path_to_id(rel: str) -> str:
    p = rel[:-3] if rel.endswith(".md") else rel
    parts = [x for x in p.split("/") if x]
    if parts and parts[-1] == "index":
        parts = parts[:-1]
    return ".".join(parts)


def id_to_relpath(mid: str, is_container: bool) -> str:
    parts = mid.split(".")
    if is_container:
        return "/".join(parts) + "/index.md"
    return "/".join(parts) + ".md"


def parent_of(mid: str):
    parts = mid.split(".")
    return ".".join(parts[:-1]) if len(parts) > 1 else None


def depth_of(mid: str) -> int:
    return len(mid.split("."))


def tree_of(mid: str) -> str:
    return mid.split(".")[0]


def api_key(a: dict) -> str:
    proto = (a.get("protocol") or "").strip()
    method = (a.get("method") or "").strip()
    path = (a.get("path") or "").strip()
    if proto == "http" and method:
        return f"{method} {path}"
    return f"{proto}:{path}"


def public(m: dict) -> dict:
    return {k: v for k, v in m.items() if not k.startswith("_")}


def slugify(s: str) -> str:
    s = re.sub(r"[^a-zA-Z0-9]+", "-", s or "").strip("-").lower()
    return s or "project"


def git_sha(repo_root):
    if not repo_root:
        return None
    try:
        p = subprocess.run(
            ["git", "-C", str(repo_root), "rev-parse", "HEAD"],
            capture_output=True, text=True, timeout=10)
        if p.returncode == 0 and SHA1_RE.match(p.stdout.strip()):
            return p.stdout.strip()
    except Exception:
        pass
    return None


def is_git_repo(repo_root) -> bool:
    return git_sha(repo_root) is not None


def ensure_dir(p: Path) -> Path:
    """幂等建目录。

    注意：本机文件代理在目录已存在时会抛 PermissionError(EEXIST) 而不是
    FileExistsError，导致 Python 的 mkdir(exist_ok=True) 压不住。所以先判存在，
    再兜一层异常。
    """
    if p.is_dir():
        return p
    try:
        p.mkdir(parents=True, exist_ok=True)
    except FileExistsError:
        pass
    except Exception:
        if not p.is_dir():
            raise
    return p


# --------------------------------------------------------------------------
# 存储
# --------------------------------------------------------------------------

def resolve_project(args):
    d = getattr(args, "dir", None)
    if d:
        return Path(d).expanduser().resolve()
    slug = getattr(args, "project", None)
    if not slug:
        return None
    bases = []
    if os.environ.get("ARCHINORM_HOME"):
        bases.append(Path(os.environ["ARCHINORM_HOME"]))
    bases += [Path.cwd(), Path.cwd().parent, Path.home()]
    for base in bases:
        p = base / f"archinorm-{slug}"
        if (p / "modules").is_dir():
            return p.resolve()
    r = Result("resolve")
    r.err("project/not-found",
          f"找不到项目 archinorm-{slug}；用 --dir 指定绝对路径",
          searched=[str(b) for b in bases])
    raise SystemExit(r.emit())


def modules_dir(proj: Path) -> Path:
    return proj / "modules"


def renders_dir(proj: Path) -> Path:
    return proj / "renders"


def changes_dir(proj: Path) -> Path:
    return proj / "changes"


def scan(proj: Path) -> dict:
    """扫描 modules/，返回 id -> module dict（含 _file / _body / _id_from_path）。"""
    out: dict = {}
    base = modules_dir(proj)
    if not base.is_dir():
        return out
    for f in sorted(base.rglob("*.md")):
        rel = str(f.relative_to(base)).replace(os.sep, "/")
        try:
            m, body = parse_module_file(f.read_text(encoding="utf-8"))
        except Exception as exc:
            out[f"__broken__{rel}"] = {
                "_parse_error": str(exc), "_file": rel,
                "id": rel, "_id_from_path": path_to_id(rel)}
            continue
        m["_file"] = rel
        m["_body"] = body
        m["_id_from_path"] = path_to_id(rel)
        out[m.get("id") or m["_id_from_path"]] = m
    return out


def children_map(mods: dict) -> dict:
    ch: dict = {k: [] for k in mods}
    for mid, m in mods.items():
        p = m.get("parent")
        if p in ch:
            ch[p].append(mid)
    for k in ch:
        ch[k].sort()
    return ch


def write_module(proj: Path, m: dict, is_container: bool) -> str:
    base = modules_dir(proj)
    rel = id_to_relpath(m["id"], is_container)
    target = base / rel
    ensure_dir(target.parent)
    body = m.get("_body") or ""
    if not body.strip():
        label = (m.get("name") or {}).get("zh") or m["id"]
        body = f"# {label}\n"
    target.write_text(dump_module_file(m, body), encoding="utf-8")
    other = base / id_to_relpath(m["id"], not is_container)
    if other.exists() and other != target:
        other.unlink()
        try:
            other.parent.rmdir()
        except OSError:
            pass
    return rel


def prune_empty_dirs(proj: Path):
    base = modules_dir(proj)
    if not base.is_dir():
        return
    for d in sorted((x for x in base.rglob("*") if x.is_dir()),
                    key=lambda p: -len(p.parts)):
        try:
            d.rmdir()
        except OSError:
            pass


# --------------------------------------------------------------------------
# 指纹
# --------------------------------------------------------------------------

def fingerprint_of(repo_root, sources: list):
    """(指纹, 缺失文件列表)。算法：按 path 升序，逐个
    update(UTF-8(path)) + update(0x00) + update(文件字节)，再取 SHA-256 前 32 位。"""
    missing: list = []
    h = hashlib.sha256()
    seen = set()
    for s in sources or []:
        p = (s.get("path") or "").strip() if isinstance(s, dict) else str(s).strip()
        if p:
            seen.add(p)
    for p in sorted(seen):
        if not repo_root:
            missing.append(p)
            continue
        fp = Path(repo_root) / p
        if not fp.is_file():
            missing.append(p)
            continue
        h.update(p.encode("utf-8"))
        h.update(b"\x00")
        h.update(fp.read_bytes())
    return h.hexdigest()[:32], missing


def structure_digest(proj: Path) -> str:
    h = hashlib.sha256()
    for sub in ("modules", "renders"):
        base = proj / sub
        if not base.is_dir():
            continue
        for f in sorted(base.rglob("*")):
            if not f.is_file():
                continue
            rel = str(f.relative_to(proj)).replace(os.sep, "/")
            h.update(rel.encode("utf-8"))
            h.update(b"\x00")
            h.update(f.read_bytes())
    return h.hexdigest()


# --------------------------------------------------------------------------
# 校验（第一部分：结构 + API）
# --------------------------------------------------------------------------

def validate_core(proj: Path, mods: dict, repo_root=None) -> Result:
    r = Result("validate")
    ch = children_map(mods)
    is_container = {k: bool(v) for k, v in ch.items()}
    api_keys: dict = {}
    roots = [k for k, m in mods.items() if m.get("parent") is None]

    for mid, m in mods.items():
        if "_parse_error" in m:
            r.err("structure/parse-error",
                  f"文件解析失败：{m['_parse_error']}", mid, file=m.get("_file"))
            continue

        bad_seg = next((s for s in mid.split(".") if not ID_SEG.match(s)), None)
        if bad_seg:
            r.err("structure/id-format",
                  f"id 段 `{bad_seg}` 非法：只允许 [a-z0-9-] 且不以 - 开头",
                  mid, segment=bad_seg)

        fid = m.get("_id_from_path")
        if fid is not None and mid != fid:
            r.err("structure/file-id-mismatch",
                  f"文件路径推导 id 为 `{m.get('_id_from_path')}`，"
                  f"但 frontmatter id 为 `{mid}`", mid, file=m.get("_file"))

        uid = m.get("uid")
        if not uid or not UID_RE.match(str(uid)):
            r.err("structure/uid-format",
                  f"uid 必须是 8 位小写 hex，收到 {uid!r}", mid)

        derived = parent_of(mid)
        declared = m.get("parent")
        if declared != derived:
            r.err("structure/parent-mismatch",
                  f"parent 应为 `{derived}`（id 去掉末段），实际 `{declared}`",
                  mid, derived=derived, got=declared)
        elif derived is not None and derived not in mods:
            r.err("structure/parent-not-exist",
                  f"父模块 `{derived}` 不存在（孤儿）", mid, missing=derived)

        for field in ("name", "description"):
            v = m.get(field)
            if not isinstance(v, dict) or not v.get("zh") or not v.get("en"):
                r.err("structure/bilingual-missing",
                      f"{field} 的 zh 与 en 均必需且非空", mid, field=field)

        rev = m.get("revision")
        if rev and rev != "pending" and not SHA1_RE.match(str(rev)):
            r.err("structure/revision-format",
                  f"revision 必须是 40 位 hex git SHA 或 pending，收到 {rev!r}", mid)

        fp = m.get("fingerprint")
        if fp and fp != "pending" and not HEX_RE.match(str(fp)):
            r.err("structure/fingerprint-format",
                  f"fingerprint 必须是 hex 或 pending，收到 {fp!r}", mid)

        state = m.get("state")
        if state is not None and state not in STATES:
            r.err("state-invalid",
                  f"state 只能是 {sorted(STATES)}，收到 {state!r}", mid)
        if state == "planned" and fp != "pending":
            r.err("state/planned-fingerprint",
                  f"计划态模块的 fingerprint 必须是 pending，实际 {fp!r}", mid)
        if state == "deprecated" and not m.get("replacement"):
            r.warn("state/deprecated-no-replacement",
                   "废弃模块未提供 replacement", mid)

        for s in (m.get("source") or []):
            p = (s.get("path") or "") if isinstance(s, dict) else ""
            if p.startswith("/") or ".." in p.split("/") or "\\" in p:
                r.err("evidence/source-invalid",
                      f"source path 必须是仓库相对路径、正斜杠、无 ..，收到 {p!r}",
                      mid, path=p)

    if not roots:
        r.err("structure/root-missing", "项目里没有任何 parent: null 的根模块")

    for mid, m in mods.items():
        if "_parse_error" in m:
            continue
        has_apis = "apis" in m
        apis = m.get("apis") or []
        if is_container.get(mid):
            if has_apis and apis:
                r.err("api/non-leaf",
                      "非叶子（含根）禁止写 apis；请下放到叶子", mid,
                      count=len(apis))
            if has_apis and not apis:
                r.warn("api/non-leaf-empty", "非叶子带了空 apis 字段，建议删除", mid)
        else:
            if not has_apis:
                r.err("api/leaf-missing", "叶子必须声明 apis（可以是空数组）", mid)
            elif not apis:
                r.warn("api/leaf-empty", "叶子 apis 为空数组", mid)

        for a in apis:
            proto = a.get("protocol")
            if proto not in PROTOCOLS:
                r.err("api/protocol-invalid",
                      f"protocol 必须是 {sorted(PROTOCOLS)} 之一，收到 {proto!r}", mid)
                continue
            method = a.get("method")
            if proto == "http":
                if not method or str(method) != str(method).upper():
                    r.err("api/method-invalid",
                          f"http API 必须带大写 method，收到 {method!r}", mid)
            elif method is not None:
                r.err("api/method-invalid",
                      f"非 http API 禁止带 method（收到 {method!r}）", mid,
                      protocol=proto)
            if not a.get("path"):
                r.err("api/path-missing", "API 缺少 path", mid)
            api_keys.setdefault(api_key(a), []).append(mid)

    for key, owners in api_keys.items():
        if len(owners) > 1:
            r.err("api/key-duplicate",
                  f"API 键 `{key}` 在多个模块重复定义", owners[0], owners=owners)

    return r


# --------------------------------------------------------------------------
# 校验（第二部分：依赖 / 粒度 / 计划态 / 渲染数据 / 指纹漂移）
# --------------------------------------------------------------------------

def validate(proj: Path, mods: dict, repo_root=None) -> Result:
    r = validate_core(proj, mods, repo_root)
    ch = children_map(mods)
    is_container = {k: bool(v) for k, v in ch.items()}

    unanchored = []
    for mid, m in mods.items():
        if "_parse_error" in m:
            continue
        my_apis = {api_key(a) for a in (m.get("apis") or [])}
        leaf_self = not is_container.get(mid)
        for d in (m.get("deps") or []):
            kind, to = d.get("kind"), d.get("to")
            if kind not in DEP_KINDS:
                r.err("dep/kind-invalid",
                      f"kind 必须是 {sorted(DEP_KINDS)} 之一，收到 {kind!r}", mid)
            if to == mid:
                r.err("dep/self", "依赖指向自身", mid)
            target = mods.get(to)
            if target is None:
                r.err("dep/target-missing",
                      f"悬空箭头：目标模块 `{to}` 不存在", mid, to=to)
                continue
            if target.get("state") == "deprecated":
                r.err("deprecation/inbound",
                      f"依赖指向已废弃模块 `{to}`，请迁移到 "
                      f"`{target.get('replacement')}` 或删除", mid,
                      to=to, replacement=target.get("replacement"))
            fa = d.get("from_api")
            if fa and fa not in my_apis:
                r.err("dep/from-api-invalid",
                      f"from_api `{fa}` 不是本模块的 API 键", mid,
                      valid=sorted(my_apis))
            t_apis = {api_key(a) for a in (target.get("apis") or [])}
            ta = d.get("to_api")
            if ta and ta not in t_apis:
                r.err("dep/to-api-invalid",
                      f"to_api `{ta}` 不是 `{to}` 自身的 API 键", mid,
                      valid=sorted(t_apis))
            if leaf_self and my_apis and t_apis and not (fa and ta):
                unanchored.append({"module": mid, "to": to})

    if unanchored:
        r.warn("dep/unanchored",
               f"{len(unanchored)} 条依赖两端都声明了 API 但未补 "
               f"from_api/to_api，箭头只能落在框边",
               samples=unanchored[:5])

    max_depth = max((depth_of(k) for k in mods), default=0)
    leaves = [k for k, c in is_container.items() if not c]
    for mid in leaves:
        m = mods[mid]
        srcs = m.get("source") or []
        files = {s.get("path") for s in srcs if isinstance(s, dict) and s.get("path")}
        span = 0
        if len(srcs) == 1 and isinstance(srcs[0], dict):
            try:
                a = srcs[0].get("line")
                b = srcs[0].get("end_line")
                if a is not None and b is not None:
                    span = int(b) - int(a)
            except (TypeError, ValueError):
                span = 0
        n_apis = len(m.get("apis") or [])
        if len(files) >= 3 or span >= 300 or n_apis >= 6:
            r.warn("structure/leaf-too-coarse",
                   "叶子粒度过粗，可以继续拆分", mid,
                   files=len(files), line_span=span, apis=n_apis)

    if len(mods) >= 20 and 0 < max_depth < 3:
        r.warn("structure/shallow-hierarchy",
               f"{len(mods)} 个模块但层级只有 {max_depth} 层，建议继续下钻")

    for mid, m in mods.items():
        if m.get("state") != "planned":
            continue
        srcs = m.get("source") or []
        if repo_root and srcs:
            _, missing = fingerprint_of(repo_root, srcs)
            if missing:
                r.warn("structure/planned-source-missing",
                       f"计划态 source 尚未落地：{missing}", mid)

    r.extend(validate_layout(proj, mods, ch, is_container))

    if repo_root:
        for mid, m in mods.items():
            if m.get("state") == "planned":
                continue
            srcs = m.get("source") or []
            if not srcs or not m.get("fingerprint") or m["fingerprint"] == "pending":
                continue
            fp, missing = fingerprint_of(repo_root, srcs)
            if missing:
                r.warn("evidence/source-missing",
                       f"source 文件缺失：{missing}", mid)
            elif fp != m["fingerprint"]:
                r.warn("evidence/fingerprint-drift",
                       "指纹漂移：源码已变，需增量重建该模块", mid,
                       stored=m["fingerprint"], actual=fp)

    r.data = {
        "modules": len(mods), "leaves": len(leaves), "roots": len([k for k, m in mods.items() if m.get("parent") is None]),
        "trees": sorted({tree_of(k) for k in mods if not k.startswith("__broken__")}),
        "max_depth": max_depth,
        "errors": len(r.errors), "warnings": len(r.warnings),
    }
    return r


# --------------------------------------------------------------------------
# 渲染数据集校验
# --------------------------------------------------------------------------

def layout_path(proj: Path, mid: str) -> Path:
    return renders_dir(proj) / (mid.replace(".", "/") + ".json")


def load_layout(proj: Path, mid: str):
    p = layout_path(proj, mid)
    if not p.is_file():
        return None
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except Exception:
        return None


def load_all_layouts(proj: Path) -> dict:
    out: dict = {}
    rd = renders_dir(proj)
    if not rd.is_dir():
        return out
    for f in sorted(rd.rglob("*.json")):
        rel = str(f.relative_to(rd))[:-5].replace(os.sep, "/")
        try:
            out[rel.replace("/", ".")] = json.loads(f.read_text(encoding="utf-8"))
        except Exception:
            out[rel.replace("/", ".")] = {"_parse_error": True}
    return out


def validate_layout(proj, mods, ch, is_container) -> Result:
    r = Result("layout")
    layouts = load_all_layouts(proj)
    for mid, lay in layouts.items():
        if mid not in mods:
            r.err("layout/orphan",
                  f"渲染数据 `renders/{mid.replace('.', '/')}.json` 没有对应模块", mid)
            continue
        if not is_container.get(mid):
            r.err("layout/not-container", "叶子模块不应有渲染数据", mid)
            continue
        kids = set(ch.get(mid) or [])
        for cid in (lay.get("order") or []):
            if cid not in kids:
                r.err("layout/order-child",
                      f"order 引用了非直接子级 `{cid}`", mid, valid=sorted(kids))
        for g in (lay.get("groups") or []):
            for cid in (g.get("children") or []):
                if cid not in kids:
                    r.err("layout/group-child",
                          f"groups 引用了非直接子级 `{cid}`", mid,
                          group=g.get("id"), valid=sorted(kids))
        mode = lay.get("mode")
        if mode is not None and mode not in VALID_MODES:
            r.err("layout/mode-invalid",
                  f"mode 必须是 {sorted(VALID_MODES)} 之一，收到 {mode!r}", mid)
        mc = lay.get("max_columns")
        if mc is not None and not (isinstance(mc, int) and 1 <= mc <= 6):
            r.err("layout/max-columns-invalid",
                  "max_columns 必须是 1..6 的整数", mid, got=mc)
        for hint in (lay.get("edge_hints") or []):
            a, b = hint.get("from"), hint.get("to")
            if a not in kids or b not in kids:
                r.warn("layout/hint-edge-missing",
                       f"edge_hint {a} → {b} 指向的不是本层直接子级", mid)

    for mid, kids in ch.items():
        if len(kids) >= 2 and mid not in layouts:
            r.warn("layout/missing",
                   f"容器有 {len(kids)} 个子模块却没有渲染数据", mid,
                   children=sorted(kids))
    return r


# --------------------------------------------------------------------------
# 编译
# --------------------------------------------------------------------------

def build_tree(proj: Path, mods: dict, layouts: dict) -> dict:
    ch = children_map(mods)
    incoming: dict = {k: [] for k in mods}
    for mid, m in mods.items():
        for d in (m.get("deps") or []):
            t = d.get("to")
            if t in incoming:
                incoming[t].append({"from": mid, **d})

    nodes: dict = {}
    for mid, m in mods.items():
        n = public(m)
        n["children"] = ch.get(mid, [])
        n["is_leaf"] = not ch.get(mid)
        n["depth"] = depth_of(mid)
        n["incoming"] = sorted(incoming.get(mid, []), key=lambda x: x["from"])
        nodes[mid] = n

    roots = sorted([k for k, m in mods.items() if m.get("parent") is None])
    return {
        "schema_version": SCHEMA_VERSION,
        "engine": f"archinorm {ENGINE_VERSION}",
        "project": {"slug": proj.name, "dir": str(proj), "built_at": now_iso()},
        "stats": {
            "modules": len(mods),
            "leaves": sum(1 for k in mods if not ch.get(k)),
            "trees": len(roots),
            "max_depth": max((depth_of(k) for k in mods), default=0),
            "apis": sum(len(m.get("apis") or []) for m in mods.values()),
            "deps": sum(len(m.get("deps") or []) for m in mods.values()),
        },
        "trees": roots,
        "modules": nodes,
        "layouts": {k: v for k, v in layouts.items() if k in nodes},
        "digest": structure_digest(proj),
    }


def write_outline(proj: Path, mods: dict, tree: dict):
    ch = children_map(mods)
    lines = [f"# {proj.name} · 结构大纲", "",
             f"生成时间：{now_iso()}　模块数：{len(mods)}", ""]

    def walk(mid: str, ind: int):
        m = mods[mid]
        nm = m.get("name") or {}
        st = m.get("state")
        badge = f" `{st}`" if st and st != "active" else ""
        lines.append(f"{'  ' * ind}- **{nm.get('zh', mid)}** `{mid}`{badge}")
        if m.get("apis") and not ch.get(mid):
            for a in m["apis"]:
                lines.append(f"{'  ' * ind}  - `{api_key(a)}`")
        for c in ch.get(mid, []):
            walk(c, ind + 1)

    for r in tree["trees"]:
        walk(r, 0)
        lines.append("")
    (proj / "outline.md").write_text("\n".join(lines), encoding="utf-8")


def write_api_index(proj: Path, mods: dict) -> dict:
    idx: dict = {}
    for mid, m in mods.items():
        for a in (m.get("apis") or []):
            idx[api_key(a)] = {
                "module": mid, "protocol": a.get("protocol"),
                "method": a.get("method"), "path": a.get("path"),
                "description": a.get("description"),
            }
    (proj / "api-index.json").write_text(
        json.dumps(idx, ensure_ascii=False, indent=2), encoding="utf-8")
    return idx


def write_receipt(proj: Path, tree: dict, val: Result) -> dict:
    receipt = {
        "schema_version": SCHEMA_VERSION,
        "project": proj.name,
        "built_at": now_iso(),
        "module_count": tree["stats"]["modules"],
        "digest": tree["digest"],
        "errors": len(val.errors),
        "warnings": len(val.warnings),
        "frozen": len(val.errors) == 0,
        "stats": tree["stats"],
    }
    (proj / "receipt.json").write_text(
        json.dumps(receipt, ensure_ascii=False, indent=2), encoding="utf-8")
    return receipt


# --------------------------------------------------------------------------
# 渲染（一）：设计令牌 + 骨架
#
# 视觉语言吸收自 archify（github.com/tt-a1i/archify, MIT）的 DESIGN.md：
#   "The Evidence Console" —— 深色证据控制台、全等宽字体、七个语义色、
#   扁平克制、状态过渡 140-200ms。
# 并遵守其明确禁令：不用 dense dashboard shell、不用无止境的同构卡片网格、
# 不用装饰性玻璃与渐变文字。
# --------------------------------------------------------------------------

HTML_HEAD = r"""<!DOCTYPE html>
<html lang="zh-CN" data-theme="dark">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>__TITLE__</title>
<style>
:root{
  --canvas:#020617; --mask:#0F172A; --ink:#FFFFFF; --muted:#94A3B8;
  --dim:#475569; --border:#1E293B;
  --frontend:#22D3EE; --backend:#34D399; --database:#A78BFA;
  --cloud:#FBBF24; --security:#FB7185; --messagebus:#FB923C; --external:#94A3B8;
  --r-precise:.2rem; --r-control:.5rem; --r-panel:1rem; --r-pill:999px;
  --mono:"JetBrains Mono",ui-monospace,SFMono-Regular,Menlo,Consolas,"Courier New",monospace;
  --t-fast:150ms;
}
html[data-theme="light"]{
  --canvas:#F8FAFC; --mask:#FFFFFF; --ink:#0B1220; --muted:#64748B;
  --dim:#94A3B8; --border:#E2E8F0;
  --frontend:#0891B2; --backend:#059669; --database:#7C3AED;
  --cloud:#B45309; --security:#BE123C; --messagebus:#C2410C; --external:#64748B;
}
html[data-theme="blueprint"]{
  --canvas:#0B1B33; --mask:#0F2547; --ink:#EAF2FF; --muted:#8FB0D9;
  --dim:#5B7CA8; --border:#1D3A66;
  --frontend:#7DD3FC; --backend:#86EFAC; --database:#C4B5FD;
  --cloud:#FDE68A; --security:#FDA4AF; --messagebus:#FDBA74; --external:#94A3B8;
  --r-panel:.35rem; --r-control:.2rem;
}
*{box-sizing:border-box}
html,body{height:100%}
body{margin:0;background:var(--canvas);color:var(--ink);
  font:400 .75rem/1.55 var(--mono);-webkit-font-smoothing:antialiased;
  display:flex;flex-direction:column;overflow:hidden}
a{color:var(--frontend);text-decoration:none}
a:hover{text-decoration:underline}
button{font:inherit;color:inherit;background:none;border:0;cursor:pointer}

.topbar{display:flex;align-items:center;gap:14px;padding:10px 16px;
  background:var(--mask);border-bottom:1px solid var(--border);flex:none;min-height:56px}
.brand{font:700 1.0625rem/1.2 var(--mono);letter-spacing:-.025em;white-space:nowrap}
.brand small{display:block;font:400 .625rem/1.35 var(--mono);color:var(--muted);
  letter-spacing:.12em;text-transform:uppercase;margin-top:2px}
.kpis{display:flex;gap:6px;flex-wrap:wrap;margin-left:8px}
.chip{display:inline-flex;align-items:baseline;gap:4px;padding:3px 8px;
  border:1px solid var(--border);border-radius:var(--r-pill);
  font:700 .625rem/1.35 var(--mono);letter-spacing:.06em;color:var(--muted);white-space:nowrap}
.chip b{font-size:.75rem;font-weight:700;color:var(--ink);letter-spacing:0}
.tools{margin-left:auto;display:flex;gap:6px;align-items:center}
.btn{height:32px;padding:0 11px;border:1px solid var(--border);
  border-radius:var(--r-control);background:transparent;color:var(--ink);
  font:400 .6875rem/1 var(--mono);display:inline-flex;align-items:center;gap:6px;
  transition:border-color var(--t-fast),background var(--t-fast)}
.btn:hover{border-color:var(--frontend)}
.btn:focus-visible{outline:2px solid var(--frontend);outline-offset:2px}
.btn[aria-pressed="true"]{border-color:var(--frontend);color:var(--frontend)}
.seg{display:flex;border:1px solid var(--border);border-radius:var(--r-control);overflow:hidden}
.seg .btn{border:0;border-radius:0;height:30px}
.seg .btn+.btn{border-left:1px solid var(--border)}

.stage{flex:1;display:flex;min-height:0;position:relative}
.canvaswrap{flex:1;min-width:0;position:relative;overflow:hidden}
#canvas{display:block;width:100%;height:100%;cursor:grab}
#canvas.dragging{cursor:grabbing}
.empty{position:absolute;inset:0;display:flex;align-items:center;justify-content:center;
  color:var(--dim);font-size:.75rem;pointer-events:none}

.nbox{transition:stroke var(--t-fast),opacity var(--t-fast)}
.nlabel{fill:var(--ink);font:600 .72rem var(--mono);dominant-baseline:middle}
.nid{fill:var(--dim);font:400 .58rem var(--mono);dominant-baseline:middle}
.nmeta{fill:var(--muted);font:700 .55rem var(--mono);letter-spacing:.1em;dominant-baseline:middle}
.grp{fill:none;stroke:var(--border);stroke-width:1;stroke-dasharray:4 4}
.grplabel{fill:var(--dim);font:700 .56rem var(--mono);letter-spacing:.12em}
.sedge{fill:none;stroke:var(--border);stroke-width:1}
.dedge{fill:none;stroke-width:1.4;opacity:.85}
.node{cursor:pointer}
.node:hover .nbox{stroke:var(--frontend)}
.dimmed{opacity:.14}
.hot .nbox{stroke-width:1.6}

/* 阅读导语：来自 renders/<id>.json 的 reading 字段，显示在图上方 */
.reading{position:absolute;left:14px;top:12px;right:14px;padding:7px 11px;
  background:var(--mask);border:1px solid var(--border);
  border-left:3px solid var(--frontend);border-radius:var(--r-control);
  color:var(--muted);font-size:.66rem;line-height:1.5;pointer-events:none;
  transition:opacity var(--t-fast)}
.reading.hidden{display:none}

.legend{position:absolute;left:14px;bottom:14px;display:flex;gap:12px;flex-wrap:wrap;
  padding:8px 11px;background:var(--mask);border:1px solid var(--border);
  border-radius:var(--r-control);max-width:calc(100% - 28px)}
.legend span{display:inline-flex;align-items:center;gap:5px;
  font:700 .56rem/1 var(--mono);letter-spacing:.1em;color:var(--muted)}
.legend i{width:9px;height:9px;border-radius:2px;display:inline-block}

.panel{width:392px;flex:none;background:var(--mask);border-left:1px solid var(--border);
  display:flex;flex-direction:column;min-height:0}
.panel.hidden{display:none}
.phead{padding:14px 16px 12px;border-bottom:1px solid var(--border);flex:none}
.phead h2{margin:0;font:600 .875rem/1.4 var(--mono);word-break:break-word}
.phead .en{color:var(--muted);font-size:.68rem;margin-top:2px}
.phead .id{color:var(--dim);font-size:.6rem;margin-top:6px;word-break:break-all}
.ptabs{display:flex;border-bottom:1px solid var(--border);flex:none}
.ptabs .btn{flex:1;border:0;border-radius:0;height:34px;justify-content:center;
  color:var(--muted);font-size:.64rem;letter-spacing:.06em}
.ptabs .btn[aria-pressed="true"]{color:var(--frontend);
  box-shadow:inset 0 -2px 0 var(--frontend)}
.pbody{flex:1;overflow:auto;padding:14px 16px 20px}
.pbody table{width:100%;border-collapse:collapse;font-size:.66rem}
.pbody th{text-align:left;font:700 .56rem var(--mono);letter-spacing:.1em;
  color:var(--dim);padding:5px 6px;border-bottom:1px solid var(--border)}
.pbody td{padding:6px;border-bottom:1px solid var(--border);vertical-align:top;
  word-break:break-word}
.pbody td.k{color:var(--muted);width:92px}
.pill{display:inline-block;padding:1px 6px;border-radius:var(--r-pill);
  border:1px solid currentColor;font:700 .54rem/1.5 var(--mono);letter-spacing:.06em}
.pill.planned{color:var(--cloud)}
.pill.deprecated{color:var(--external)}
.note{color:var(--dim);font-size:.64rem;padding:8px 0}
.desc{color:var(--muted);font-size:.68rem;line-height:1.6;margin:0 0 8px}
.hint{color:var(--dim);font-size:.6rem;margin-top:4px}
.edgebar{display:flex;gap:6px;margin:10px 0 4px;flex-wrap:wrap}
.edgebar .btn{height:26px;font-size:.6rem}
footer{flex:none;padding:7px 16px;border-top:1px solid var(--border);
  color:var(--dim);font-size:.58rem;display:flex;gap:14px;flex-wrap:wrap}
@media (prefers-reduced-motion: reduce){*{transition:none!important}}
@media (max-width:900px){.panel{position:absolute;right:0;top:0;bottom:0;width:86%;
  box-shadow:0 18px 48px rgba(0,0,0,.45)}}
</style>
</head>
<body>
<header class="topbar">
  <div class="brand">
    <span id="ttl">__TITLE__</span>
    <small id="sub"></small>
  </div>
  <div class="kpis" id="kpis"></div>
  <div class="tools">
    <div class="seg" id="themebar">
      <button class="btn" data-theme="dark" aria-pressed="true">暗色</button>
      <button class="btn" data-theme="light" aria-pressed="false">亮色</button>
      <button class="btn" data-theme="blueprint" aria-pressed="false">蓝图</button>
    </div>
    <div class="seg" id="modebar">
      <button class="btn" data-mode="scope" aria-pressed="true">当前层</button>
      <button class="btn" data-mode="all" aria-pressed="false">全图</button>
    </div>
    <button class="btn" id="btn-fit">复位</button>
  </div>
</header>

<div class="stage">
  <div class="canvaswrap">
    <svg id="canvas" xmlns="http://www.w3.org/2000/svg"></svg>
    <div class="empty" id="empty" style="display:none">该模块没有可绘制的子结构</div>
    <div class="reading hidden" id="reading"></div>
    <div class="legend" id="legend"></div>
  </div>
  <aside class="panel hidden" id="panel">
    <div class="phead">
      <h2 id="p-title">—</h2>
      <div class="en" id="p-en"></div>
      <div class="id" id="p-id"></div>
    </div>
    <div class="ptabs" id="ptabs">
      <button class="btn" data-tab="overview" aria-pressed="true">概览</button>
      <button class="btn" data-tab="apis" aria-pressed="false">接口</button>
      <button class="btn" data-tab="edges" aria-pressed="false">依赖</button>
      <button class="btn" data-tab="meta" aria-pressed="false">元数据</button>
    </div>
    <div class="pbody" id="p-body"></div>
  </aside>
</div>
<footer id="ft"></footer>
"""


# --------------------------------------------------------------------------
# 渲染（二）：图画布 + 面板 + 交互
#
# 画布是"真图"而不是卡片网格：按层级分列的节点链路图，
# 结构边（父子）细灰，依赖边（deps）按 kind 语义着色，可平移/缩放/下钻。
# --------------------------------------------------------------------------

HTML_TAIL = r"""<script id="payload" type="application/json">__TREE_JSON__</script>
<script>
(function(){
  var DATA = JSON.parse(document.getElementById('payload').textContent);
  var M = DATA.modules || {}, L = DATA.layouts || {};
  var PAL = ['frontend','backend','database','cloud','security','messagebus','external'];

  var W = 198, H = 50, GAPY = 72, COLW = 268, PAD = 28;
  var cur = location.hash.indexOf('#module=') === 0
    ? decodeURIComponent(location.hash.slice(8)) : (DATA.trees[0] || '');
  if (!M[cur]) cur = DATA.trees[0] || '';
  var mode = 'scope', sel = null, tab = 'overview';
  var view = {x:0, y:0, k:1};
  var collapsed = {};

  var svg = document.getElementById('canvas');
  var NS = 'http://www.w3.org/2000/svg';

  function el(tag, attrs, text){
    var n = document.createElementNS(NS, tag);
    for (var k in attrs) if (attrs[k] !== null && attrs[k] !== undefined) {
      n.setAttribute(k, attrs[k]);
    }
    if (text !== undefined && text !== null) n.textContent = text;
    return n;
  }
  function clear(n){ while (n.firstChild) n.removeChild(n.firstChild); }
  function kids(id){ return (M[id] && M[id].children) || []; }
  function bi(o){ return (o && (o.zh || o.en)) || ''; }
  function v(name){ return getComputedStyle(document.documentElement)
      .getPropertyValue('--' + name).trim(); }
  function esc(s){ return String(s == null ? '' : s).replace(/[&<>"]/g, function(c){
    return {'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;'}[c]; }); }
  function trunc(s, n){ s = String(s == null ? '' : s);
    return s.length > n ? s.slice(0, n - 1) + '\u2026' : s; }

  function semOf(m){
    if (m.state === 'planned') return 'cloud';
    if (m.state === 'deprecated') return 'external';
    if (m.is_leaf){
      var ps = (m.apis || []).map(function(a){ return a.protocol; });
      if (ps.indexOf('kafka') >= 0 || ps.indexOf('amqp') >= 0) return 'messagebus';
      if (ps.indexOf('mysql') >= 0 || ps.indexOf('redis') >= 0
          || ps.indexOf('file') >= 0) return 'database';
      if (ps.indexOf('http') >= 0 || ps.indexOf('ws') >= 0
          || ps.indexOf('graphql') >= 0) return 'frontend';
      if (ps.indexOf('rpc') >= 0 || ps.indexOf('grpc') >= 0) return 'backend';
      return 'external';
    }
    return null;
  }
  function edgeColor(kind){
    return kind === 'call' ? 'backend' : kind === 'event' ? 'messagebus'
         : kind === 'dataflow' ? 'database' : 'external';
  }

  // —— 渲染数据（renders/<id>.json）消费 ——

  function layOf(id){ return L[id] || {}; }

  // order：同级阅读顺序（生产者到消费者）。列出的排前、按给定次序；未列出的保持原树序追加在后。
  function orderedKids(id){
    var ks = kids(id).slice();
    var o = layOf(id).order;
    if (!o || !o.length) return ks;
    var idx = {};
    o.forEach(function(x, i){ idx[x] = i; });
    return ks.map(function(k, i){
      return {k: k, o: (idx[k] === undefined ? o.length + i : idx[k])};
    }).sort(function(a, b){ return a.o - b.o; }).map(function(x){ return x.k; });
  }

  // edge_hints：给指定的一条边定车道或线型
  function hintFor(a, b, kind){
    var hs = layOf(cur).edge_hints;
    if (!hs || !hs.length) return null;
    for (var i = 0; i < hs.length; i++){
      var h = hs[i];
      if (h.from === a && h.to === b && (!h.kind || h.kind === kind)) return h;
    }
    return null;
  }

  function buildScope(){
    var depthLimit = mode === 'all' ? 3 : 2;
    var start = mode === 'all' ? (DATA.trees[0] || cur) : cur;
    var nodes = [], edges = [], order = {};
    function walk(id, d){
      if (!M[id] || d > depthLimit) return;
      order[id] = nodes.length;
      nodes.push({id: id, d: d});
      var ks = orderedKids(id);            // ← 按 renders 的 order 排
      for (var i = 0; i < ks.length; i++){
        if (d < depthLimit){
          edges.push({t:'s', a:id, b:ks[i]});
          walk(ks[i], d + 1);
        }
      }
    }
    walk(start, 0);
    var vis = {}; nodes.forEach(function(n){ vis[n.id] = 1; });
    nodes.forEach(function(n){
      (M[n.id].deps || []).forEach(function(d){
        if (vis[d.to]) edges.push({t:'d', a:n.id, b:d.to, kind:d.kind,
                                   label:bi(d.label)});
      });
    });
    return {nodes:nodes, edges:edges, order:order, start:start};
  }

  function layout(sc){
    var pos = {}, ymap = {}, slot = 0;
    (function assign(id, d){
      var ks = orderedKids(id).filter(function(c){ return sc.order[c] !== undefined; });
      if (ks.length && d < 3){
        ks.forEach(function(c){ assign(c, d + 1); });
        var cy = ks.map(function(c){ return ymap[c]; });
        ymap[id] = (Math.min.apply(null, cy) + Math.max.apply(null, cy)) / 2;
      } else {
        ymap[id] = PAD + slot * GAPY + H / 2;
        slot++;
      }
    })(sc.start, 0);

    var maxD = 0;
    sc.nodes.forEach(function(n){
      maxD = Math.max(maxD, n.d);
      pos[n.id] = {x: PAD + n.d * COLW, y: ymap[n.id] - H / 2, w: W, h: H};
    });
    return {pos: pos, w: PAD * 2 + (maxD + 1) * COLW - (COLW - W),
            h: PAD * 2 + Math.max(1, slot) * GAPY};
  }

  function render(){
    clear(svg);
    var sc = buildScope();
    if (!sc.nodes.length){
      document.getElementById('empty').style.display = 'flex';
      return;
    }
    document.getElementById('empty').style.display = 'none';
    var lay = layout(sc), pos = lay.pos;

    var root = el('g', {id:'world'});
    svg.appendChild(root);
    var gGrp = el('g'), gEdge = el('g'), gNode = el('g');
    root.appendChild(gGrp); root.appendChild(gEdge); root.appendChild(gNode);

    var layCur = layOf(cur);

    // —— 分组框：renders 的 mode=groups + groups（画在节点之下）——
    if (layCur.mode === 'groups' && layCur.groups && layCur.groups.length){
      layCur.groups.forEach(function(g){
        var mem = (g.children || []).filter(function(c){ return pos[c]; });
        if (!mem.length) return;
        var x1 = Infinity, y1 = Infinity, x2 = -Infinity, y2 = -Infinity;
        mem.forEach(function(c){
          var p = pos[c];
          x1 = Math.min(x1, p.x);       y1 = Math.min(y1, p.y);
          x2 = Math.max(x2, p.x + p.w); y2 = Math.max(y2, p.y + p.h);
        });
        var pad = 11, head = 15;
        gGrp.appendChild(el('rect', {x: x1 - pad, y: y1 - pad - head,
          width: (x2 - x1) + pad * 2, height: (y2 - y1) + pad * 2 + head,
          rx: 9, 'class': 'grp'}));
        gGrp.appendChild(el('text', {x: x1 - pad + 11, y: y1 - pad - 4,
          'class': 'grplabel'}, trunc(bi(g.title) || g.id, 24)));
      });
    }

    // —— 阅读导语：renders 的 reading，显示在图上方 ——
    var rdEl = document.getElementById('reading');
    var rd = layCur.reading;
    if (rd && (rd.zh || rd.en)){
      rdEl.textContent = rd.zh || rd.en;
      rdEl.classList.remove('hidden');
    } else {
      rdEl.classList.add('hidden');
    }

    var nb = {};
    if (sel){
      nb[sel] = 1;
      (M[sel].deps || []).forEach(function(d){ nb[d.to] = 1; });
      (M[sel].incoming || []).forEach(function(d){ nb[d.from] = 1; });
    }

    var depIdx = 0;
    sc.edges.forEach(function(e){
      var a = pos[e.a], b = pos[e.b];
      if (!a || !b) return;
      var x1 = a.x + a.w, y1 = a.y + a.h / 2, x2 = b.x, y2 = b.y + b.h / 2;
      if (e.t === 's'){
        var mx = (x1 + x2) / 2;
        gEdge.appendChild(el('path', {d: 'M' + x1 + ',' + y1 + ' L' + mx + ',' + y1
                                       + ' L' + mx + ',' + y2 + ' L' + x2 + ',' + y2,
                                     'class': 'sedge'}));
        return;
      }
      var h = hintFor(e.a, e.b, e.kind);
      var lane = ((depIdx++ % 3) - 1) * 7;
      if (h && h.lane !== undefined) lane = (h.lane - 2) * 12;   // lane 2..4 → 0/12/24
      y1 += lane; y2 += lane;
      var dx = Math.max(34, Math.abs(x2 - x1) * 0.38);
      var c = edgeColor(e.kind);
      var dash = (h && h.style)
        ? (h.style === 'solid' ? null : h.style)
        : (e.kind === 'event' ? '5 4' : e.kind === 'reference' ? '2 4' : null);
      var p = el('path', {
        d: 'M' + x1 + ',' + y1 + ' C' + (x1 + dx) + ',' + y1 + ' '
           + (x2 - dx) + ',' + y2 + ' ' + x2 + ',' + y2,
        'class': 'dedge', stroke: v(c), 'marker-end': 'url(#ah-' + c + ')',
        'stroke-dasharray': dash});
      if (sel && !(e.a === sel || e.b === sel)) p.setAttribute('opacity', '0.1');
      gEdge.appendChild(p);
    });

    sc.nodes.forEach(function(n){
      var m = M[n.id], p = pos[n.id], c = semOf(m);
      var ks = kids(n.id);
      var g = el('g', {'class': 'node' + (sel === n.id ? ' sel' : '')
                             + (sel && !nb[n.id] ? ' dimmed' : '')
                             + (sel && nb[n.id] && n.id !== sel ? ' hot' : ''),
                       'data-id': n.id});
      g.appendChild(el('rect', {x:p.x, y:p.y, width:p.w, height:p.h, rx:6,
        'class':'nbox', fill: v('mask'), stroke: c ? v(c) : v('dim'),
        'stroke-width': c ? 1.2 : 1}));
      if (c) g.appendChild(el('rect', {x:p.x, y:p.y, width:3, height:p.h, rx:1.5,
        fill: v(c)}));
      g.appendChild(el('circle', {cx: p.x + 16, cy: p.y + p.h / 2, r: 4,
        'class':'ndot', fill: c ? v(c) : v('dim')}));
      g.appendChild(el('text', {x: p.x + 27, y: p.y + p.h / 2 - 6,
        'class':'nlabel'}, trunc(bi(m.name) || n.id, 16)));
      g.appendChild(el('text', {x: p.x + 27, y: p.y + p.h / 2 + 11,
        'class':'nid'}, trunc(n.id, 25)));
      var meta = ks.length ? (ks.length + ' SUB') : ((m.apis || []).length + ' API');
      if ((m.deps || []).length) meta += '  ' + m.deps.length + '\u2192';
      g.appendChild(el('text', {x: p.x + p.w - 9, y: p.y + p.h / 2,
        'class':'nmeta', 'text-anchor':'end'}, meta));
      if (ks.length){
        g.appendChild(el('text', {x: p.x + p.w - 9, y: p.y + 10,
          'class':'nmeta', 'text-anchor':'end'}, collapsed[n.id] ? '\u25b8' : '\u25be'));
      }
      gNode.appendChild(g);
    });

    var defs = el('defs');
    PAL.forEach(function(c){
      var mk = el('marker', {id:'ah-' + c, viewBox:'0 0 10 10', refX:'9', refY:'5',
        markerWidth:'6', markerHeight:'6', orient:'auto-start-reverse'});
      mk.appendChild(el('path', {d:'M1 1L9 5L1 9', fill:'none', stroke: v(c),
        'stroke-width':'1.6', 'stroke-linecap':'round', 'stroke-linejoin':'round'}));
      defs.appendChild(mk);
    });
    root.insertBefore(defs, root.firstChild);

    svg.setAttribute('viewBox', '0 0 ' + (svg.clientWidth || 900) + ' '
                                            + (svg.clientHeight || 600));
    applyView();
    drawLegend();
  }

  function applyView(){
    var w = document.getElementById('world');
    if (w) w.setAttribute('transform',
      'translate(' + view.x + ',' + view.y + ') scale(' + view.k + ')');
  }

  function fit(){
    var sc = buildScope();
    if (!sc.nodes.length) return;
    var lay = layout(sc);
    var cw = svg.clientWidth || 900, ch = svg.clientHeight || 600;
    var k = Math.min((cw - 26) / Math.max(1, lay.w), (ch - 26) / Math.max(1, lay.h), 1.1);
    view.k = Math.max(k, 0.26);
    view.x = (cw - lay.w * view.k) / 2;
    view.y = (ch - lay.h * view.k) / 2;
    applyView();
  }

  var LEGEND = [['frontend','HTTP / WS'], ['backend','RPC / CALL'],
                ['database','STORE'], ['messagebus','EVENT / MQ'],
                ['cloud','PLANNED'], ['external','OTHER']];
  function drawLegend(){
    var used = {};
    Object.keys(M).forEach(function(k){ var c = semOf(M[k]); if (c) used[c] = 1; });
    var html = '';
    LEGEND.forEach(function(p){
      if (used[p[0]]) html += '<span><i style="background:' + v(p[0]) + '"></i>'
                            + p[1] + '</span>';
    });
    document.getElementById('legend').innerHTML = html || '<span>纯结构视图</span>';
  }

  function apiKey(a){
    return (a.protocol === 'http' && a.method)
      ? a.method + ' ' + a.path : a.protocol + ':' + a.path;
  }
  function paintPanel(){
    var pn = document.getElementById('panel');
    if (!sel || !M[sel]){ pn.classList.add('hidden'); return; }
    pn.classList.remove('hidden');
    var m = M[sel];
    document.getElementById('p-title').textContent = bi(m.name) || sel;
    document.getElementById('p-en').textContent = (m.name && m.name.en) || '';
    document.getElementById('p-id').textContent = sel;
    var h = '';
    if (tab === 'overview'){
      h += '<p class="desc">' + esc((m.description || {}).zh || '') + '</p>';
      if ((m.description || {}).en)
        h += '<p class="desc" style="color:var(--dim)">' + esc(m.description.en) + '</p>';
      var st = (m.state && m.state !== 'active')
        ? '<span class="pill ' + m.state + '">' + m.state + '</span>' : 'ACTIVE';
      h += '<table>'
        + '<tr><td class="k">状态</td><td>' + st + '</td></tr>'
        + '<tr><td class="k">层级</td><td>' + m.depth + '　'
        + (m.is_leaf ? '叶子' : '容器 · ' + kids(sel).length + ' 子模块') + '</td></tr>'
        + '<tr><td class="k">接口</td><td>' + (m.apis || []).length + ' 条</td></tr>'
        + '<tr><td class="k">出向依赖</td><td>' + (m.deps || []).length + ' 条</td></tr>'
        + '<tr><td class="k">被依赖</td><td>' + (m.incoming || []).length + ' 条</td></tr>'
        + '</table>';
      if (kids(sel).length){
        h += '<div class="edgebar">';
        kids(sel).forEach(function(c){
          h += '<button class="btn" data-goto="' + esc(c) + '">'
             + esc(trunc(bi(M[c] && M[c].name) || c, 11)) + '</button>';
        });
        h += '</div><div class="hint">单击选中 · 再击或双击下钻</div>';
      }
      if ((m.source || []).length){
        h += '<table style="margin-top:10px"><tr><th>代码证据</th><th>行</th></tr>';
        m.source.forEach(function(s){
          h += '<tr><td>' + esc(s.path) + '</td><td>'
             + esc(s.line ? (s.line + '-' + (s.end_line || s.line)) : '-')
             + '</td></tr>';
        });
        h += '</table>';
      }
    } else if (tab === 'apis'){
      var a = m.apis || [];
      if (!a.length) h = '<div class="note">无 API。容器模块的接口由编译器从子层聚合。</div>';
      else {
        h = '<table><tr><th>协议</th><th>键</th></tr>';
        var cc = semOf(m) || 'frontend';
        a.forEach(function(x){
          h += '<tr><td><span class="pill" style="color:' + v(cc) + '">'
             + esc(x.protocol) + '</span></td><td>' + esc(apiKey(x))
             + '<div style="color:var(--dim);margin-top:3px">'
             + esc(((x.description || {}).zh) || '') + '</div></td></tr>';
        });
        h += '</table>';
      }
    } else if (tab === 'edges'){
      var out = (m.deps || []).map(function(d){
        return {dir:'OUT', other:d.to, kind:d.kind, note:bi(d.label)}; });
      (m.incoming || []).forEach(function(d){
        out.push({dir:'IN', other:d.from, kind:d.kind, note:bi(d.label)}); });
      if (!out.length) h = '<div class="note">无依赖边。</div>';
      else {
        h = '<table><tr><th>向</th><th>类型</th><th>目标</th></tr>';
        out.forEach(function(d){
          var o = M[d.other] || {};
          h += '<tr><td><span class="pill" style="color:' + v(edgeColor(d.kind))
             + '">' + d.dir + '</span></td><td>' + esc(d.kind || '') + '</td>'
             + '<td><a href="#module=' + encodeURIComponent(d.other)
             + '" data-goto="' + esc(d.other) + '">'
             + esc(bi(o.name) || d.other) + '</a>'
             + (d.note ? '<div style="color:var(--dim);margin-top:3px">'
                + esc(d.note) + '</div>' : '') + '</td></tr>';
        });
        h += '</table>';
      }
    } else {
      h = '<table>'
        + '<tr><td class="k">uid</td><td>' + esc(m.uid) + '</td></tr>'
        + '<tr><td class="k">revision</td><td>' + esc(trunc(m.revision, 12)) + '</td></tr>'
        + '<tr><td class="k">fingerprint</td><td>' + esc(trunc(m.fingerprint, 16)) + '</td></tr>'
        + '<tr><td class="k">updated_at</td><td>' + esc(m.updated_at) + '</td></tr>'
        + '<tr><td class="k">parent</td><td>' + esc(m.parent || '(root)') + '</td></tr>'
        + '</table>';
    }
    document.getElementById('p-body').innerHTML = h;
  }

  svg.addEventListener('click', function(e){
    var g = e.target.closest ? e.target.closest('.node') : null;
    if (!g){ sel = null; paintPanel(); render(); return; }
    var id = g.getAttribute('data-id');
    if (sel === id && kids(id).length){
      cur = id; sel = null; collapsed[id] = false;
      history.replaceState(null, '', '#module=' + encodeURIComponent(id));
      render(); fit(); paintPanel(); return;
    }
    sel = id; paintPanel(); render();
  });
  svg.addEventListener('dblclick', function(e){
    var g = e.target.closest ? e.target.closest('.node') : null;
    if (!g) return;
    var id = g.getAttribute('data-id');
    if (kids(id).length){
      cur = id; sel = null; collapsed[id] = false;
      history.replaceState(null, '', '#module=' + encodeURIComponent(id));
      render(); fit(); paintPanel();
    }
  });

  var drag = null;
  svg.addEventListener('mousedown', function(e){
    drag = {x: e.clientX - view.x, y: e.clientY - view.y};
    svg.classList.add('dragging');
  });
  window.addEventListener('mousemove', function(e){
    if (!drag) return;
    view.x = e.clientX - drag.x; view.y = e.clientY - drag.y; applyView();
  });
  window.addEventListener('mouseup', function(){
    drag = null; svg.classList.remove('dragging'); });
  svg.addEventListener('wheel', function(e){
    if (!e.ctrlKey && !e.metaKey && Math.abs(e.deltaY) < 60) return;
    e.preventDefault();
    var r = svg.getBoundingClientRect();
    var mx = e.clientX - r.left, my = e.clientY - r.top;
    var k2 = Math.min(2.4, Math.max(0.25,
      view.k * (e.deltaY < 0 ? 1.12 : 1 / 1.12)));
    view.x = mx - (mx - view.x) * (k2 / view.k);
    view.y = my - (my - view.y) * (k2 / view.k);
    view.k = k2; applyView();
  }, {passive: false});

  document.body.addEventListener('click', function(e){
    var d = e.target.dataset;
    if (!d) return;
    if (d.theme !== undefined){
      document.documentElement.setAttribute('data-theme', d.theme);
      [].forEach.call(document.querySelectorAll('#themebar .btn'), function(b){
        b.setAttribute('aria-pressed', String(b === e.target)); });
      render(); paintPanel(); return;
    }
    if (d.mode !== undefined){
      mode = d.mode;
      [].forEach.call(document.querySelectorAll('#modebar .btn'), function(b){
        b.setAttribute('aria-pressed', String(b.dataset.mode === mode)); });
      sel = null; render(); fit(); paintPanel(); return;
    }
    if (d.tab !== undefined){
      tab = d.tab;
      [].forEach.call(document.querySelectorAll('#ptabs .btn'), function(b){
        b.setAttribute('aria-pressed', String(b.dataset.tab === tab)); });
      paintPanel(); return;
    }
    if (d.goto !== undefined){
      sel = d.goto;
      if (kids(d.goto).length) cur = d.goto;
      history.replaceState(null, '', '#module=' + encodeURIComponent(d.goto));
      render(); fit(); paintPanel(); return;
    }
    if (e.target.id === 'btn-fit'){ sel = null; fit(); return; }
  });

  window.addEventListener('resize', function(){
    svg.setAttribute('viewBox', '0 0 ' + (svg.clientWidth || 900) + ' '
                                            + (svg.clientHeight || 600));
    applyView();
  });
  window.addEventListener('hashchange', function(){
    var id = location.hash.indexOf('#module=') === 0
      ? decodeURIComponent(location.hash.slice(8)) : '';
    if (M[id] && id !== cur){ cur = id; sel = null; render(); fit(); paintPanel(); }
  });

  (function boot(){
    var s = DATA.stats;
    document.getElementById('ttl').textContent = DATA.project.slug;
    document.getElementById('sub').textContent = '归一化框架图 · ' + DATA.engine;
    document.getElementById('kpis').innerHTML =
        '<span class="chip"><b>' + s.modules + '</b>MOD</span>'
      + '<span class="chip"><b>' + s.leaves + '</b>LEAF</span>'
      + '<span class="chip"><b>' + s.trees + '</b>TREE</span>'
      + '<span class="chip"><b>' + s.max_depth + '</b>DEPTH</span>'
      + '<span class="chip"><b>' + s.apis + '</b>API</span>'
      + '<span class="chip"><b>' + s.deps + '</b>EDGE</span>'
      + '<span class="chip">' + esc(DATA.digest.slice(0, 8)) + '</span>';
    document.getElementById('ft').textContent =
      '拖动平移 · 滚轮缩放 · 单击选中 · 再击/双击下钻 · 深链 #module=<id>';
    render(); fit(); paintPanel();
  })();
})();
</script>
</body>
</html>
"""

HTML_TEMPLATE = HTML_HEAD + HTML_TAIL


def render_html(tree: dict, out_path: Path) -> Path:
    payload = json.dumps(tree, ensure_ascii=False).replace("</", "<\\/")
    html = (HTML_TEMPLATE
            .replace("__TITLE__", f"{tree['project']['slug']} · 归一化框架图")
            .replace("__TREE_JSON__", payload))
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(html, encoding="utf-8")
    return out_path


# --------------------------------------------------------------------------
# 变更日志
# --------------------------------------------------------------------------

def change_path(proj: Path, cid: str) -> Path:
    return changes_dir(proj) / f"{cid}.json"


def load_changes(proj: Path) -> list:
    d = changes_dir(proj)
    if not d.is_dir():
        return []
    out = []
    for f in sorted(d.glob("*.json")):
        try:
            out.append(json.loads(f.read_text(encoding="utf-8")))
        except Exception:
            pass
    return out


def save_change(proj: Path, c: dict):
    ensure_dir(changes_dir(proj))
    change_path(proj, c["id"]).write_text(
        json.dumps(c, ensure_ascii=False, indent=2), encoding="utf-8")


def normalise_modules_arg(raw) -> dict:
    """modules 允许 {create,modify,delete} 或裸列表（视为 create）。"""
    if raw is None:
        return {"create": [], "modify": [], "delete": []}
    if isinstance(raw, list):
        return {"create": [str(x) for x in raw], "modify": [], "delete": []}
    out = {}
    for k in ("create", "modify", "delete"):
        v = raw.get(k) or []
        if not isinstance(v, list):
            raise ValueError(f"modules.{k} 必须是数组")
        out[k] = [str(x) for x in v]
    return out


def bi_arg(v) -> dict:
    if v is None:
        return {"zh": "", "en": ""}
    try:
        parsed = json.loads(v)
        if isinstance(parsed, dict):
            return {"zh": parsed.get("zh", ""), "en": parsed.get("en", "")}
    except Exception:
        pass
    return {"zh": v, "en": ""}


# --------------------------------------------------------------------------
# 架构规则（policy.yml）
# --------------------------------------------------------------------------

DEFAULT_POLICY = {
    "version": 1,
    "rules": [
        {"id": "core-acyclic", "type": "acyclic", "severity": "error"},
        {"id": "no-deprecated-inbound", "type": "forbid-dependency",
         "severity": "warning", "to_state": "deprecated"},
    ],
}


def load_policy(proj: Path) -> dict:
    p = proj / "policy.yml"
    if not p.is_file():
        return json.loads(json.dumps(DEFAULT_POLICY))
    try:
        data = yaml.safe_load(p.read_text(encoding="utf-8"))
        return data if isinstance(data, dict) else json.loads(json.dumps(DEFAULT_POLICY))
    except Exception:
        return json.loads(json.dumps(DEFAULT_POLICY))


def _id_match(mid, pattern) -> bool:
    if pattern.endswith(".*"):
        return mid.startswith(pattern[:-1])
    return mid == pattern


def _rank(mid, rank):
    best = None
    for pat, i in rank.items():
        if _id_match(mid, pat):
            best = i if best is None else min(best, i)
    return best


def check_policy(proj: Path, mods: dict) -> Result:
    r = Result("policy")
    pol = load_policy(proj)
    rules = pol.get("rules") or []

    for rule in rules:
        t = rule.get("type")
        sev = rule.get("severity", "error")
        rid = rule.get("id", t)
        emit = r.err if sev == "error" else r.warn

        if t == "acyclic":
            color, found = {}, []

            def dfs(u):
                color[u] = 1
                for d in (mods[u].get("deps") or []):
                    v = d.get("to")
                    if v not in mods:
                        continue
                    if color.get(v) == 1:
                        found.append((u, v))
                    elif color.get(v, 0) == 0:
                        dfs(v)
                color[u] = 2

            for k in mods:
                if color.get(k, 0) == 0:
                    dfs(k)
            for u, v in found:
                emit(f"policy/{rid}", f"依赖成环：{u} → {v}", u)

        elif t == "max-depth":
            limit = rule.get("limit", 8)
            for k in mods:
                if depth_of(k) > limit:
                    emit(f"policy/{rid}", f"深度 {depth_of(k)} 超过上限 {limit}", k)

        elif t == "naming":
            pat = re.compile(rule.get("pattern") or r"^[a-z0-9-]+$")
            for k in mods:
                bad = next((s for s in k.split(".") if not pat.match(s)), None)
                if bad:
                    emit(f"policy/{rid}", f"id 段 `{bad}` 不符合命名规则", k)

        elif t == "forbid-dependency":
            fr, to = rule.get("from"), rule.get("to")
            to_state = rule.get("to_state")
            for k, m in mods.items():
                if fr and not _id_match(k, fr):
                    continue
                for d in (m.get("deps") or []):
                    tgt = d.get("to")
                    if to and _id_match(tgt, to):
                        emit(f"policy/{rid}", f"禁止的依赖：{k} → {tgt}", k)
                    if to_state and (mods.get(tgt) or {}).get("state") == to_state:
                        emit(f"policy/{rid}",
                             f"依赖指向 {to_state} 模块：{k} → {tgt}", k)

        elif t == "dependency-direction":
            rank = {}
            for i, grp in enumerate(rule.get("layers") or []):
                for pat in grp:
                    rank[pat] = i
            for k, m in mods.items():
                for d in (m.get("deps") or []):
                    tgt = d.get("to")
                    a, b = _rank(k, rank), _rank(tgt, rank)
                    if a is not None and b is not None and b < a:
                        emit(f"policy/{rid}",
                             f"依赖方向违规：{k}（第{a}层）→ {tgt}（第{b}层）", k)

        else:
            r.warn("policy/unknown-rule-type",
                   f"规则 `{rid}` 的类型 `{t}` 未实现，已跳过")

    r.data = {"rules": len(rules)}
    return r


# --------------------------------------------------------------------------
# 命令：项目初始化与模块写操作
# --------------------------------------------------------------------------

def _repo_root(a):
    rp = getattr(a, "repo", None)
    return Path(rp).expanduser().resolve() if rp else None


def _must_project(a, cmd: str) -> Path:
    proj = resolve_project(a)
    if proj is None:
        r = Result(cmd)
        r.err("project/required", "需要 --dir 或 --project 指定项目")
        raise SystemExit(r.emit())
    if not (proj / "modules").is_dir():
        r = Result(cmd)
        r.err("project/not-found", f"{proj} 下没有 modules/ 目录")
        raise SystemExit(r.emit())
    return proj


def cmd_init(a) -> Result:
    r = Result("init")
    proj = resolve_project(a)
    if proj is None:
        proj = Path.cwd() / f"archinorm-{slugify(a.slug or Path.cwd().name)}"
    ensure_dir(proj)
    for sub in ("modules", "renders", "changes"):
        ensure_dir(proj / sub)
    pol = proj / "policy.yml"
    if not pol.exists():
        pol.write_text(yaml.safe_dump(DEFAULT_POLICY, allow_unicode=True,
                                      sort_keys=False), encoding="utf-8")

    created = []
    if a.root_id:
        mid = a.root_id
        if not ID_SEG.match(mid):
            return r.err("args/invalid",
                         "root id 必须匹配 ^[a-z0-9][a-z0-9-]*$")
        mods = scan(proj)
        if mid not in mods:
            m = {
                "uid": gen_uid(), "id": mid, "parent": None,
                "revision": git_sha(_repo_root(a)) or ZERO_SHA,
                "updated_at": now_iso(), "fingerprint": "pending",
                "state": "planned", "repository": a.repo_url or None,
                "source": [],
                "name": {"zh": a.title or mid, "en": a.title_en or mid},
                "description": {"zh": "（待填写）", "en": "(to be filled)"},
            }
            write_module(proj, m, False)
            created.append(mid)
    r.data = {"project_dir": str(proj), "created": created,
              "policy": str(pol), "dirs": ["modules", "renders", "changes"]}
    return r


def _normalise_module(raw: dict, mods: dict, repo_root) -> dict:
    m = dict(raw or {})
    mid = m.get("id")
    if not mid:
        raise ValueError("module.id 必填")
    mid = str(mid).strip()
    m["id"] = mid
    m["parent"] = parent_of(mid)
    m.setdefault("updated_at", now_iso())
    nm = m.get("name")
    if isinstance(nm, str):
        m["name"] = {"zh": nm, "en": nm}
    ds = m.get("description")
    if isinstance(ds, str):
        m["description"] = {"zh": ds, "en": ds}
    m.setdefault("name", {"zh": mid, "en": mid})
    m.setdefault("description", {"zh": "", "en": ""})
    m.setdefault("source", [])
    old = mods.get(mid)
    if old and old.get("uid") and not raw.get("uid"):
        m["uid"] = old["uid"]
    m.setdefault("uid", gen_uid())

    sha = git_sha(repo_root)
    if m.get("state") == "planned":
        m["fingerprint"] = "pending"
        m.setdefault("revision", sha or ZERO_SHA)
    else:
        m.setdefault("revision", sha or ZERO_SHA)
        if not m.get("fingerprint"):
            fp, _ = fingerprint_of(repo_root, m.get("source") or [])
            m["fingerprint"] = fp
    return m


def cmd_upsert(a) -> Result:
    r = Result("upsert")
    proj = _must_project(a, "upsert")
    repo_root = _repo_root(a)
    mods = scan(proj)

    if a.module_file:
        raws = json.loads(Path(a.module_file).read_text(encoding="utf-8"))
    elif a.module:
        raws = json.loads(sys.stdin.read() if a.module == "-" else a.module)
    else:
        return r.err("args/invalid", "需要 --module <json> 或 --module-file <path>")
    if isinstance(raws, dict):
        raws = [raws]
    if not raws:
        return r.err("args/invalid", "模块列表为空")

    written = []
    for raw in raws:
        try:
            m = _normalise_module(raw, mods, repo_root)
        except ValueError as exc:
            return r.err("args/invalid", str(exc))
        if not all(ID_SEG.match(s) for s in m["id"].split(".")):
            return r.err("structure/id-format", f"id `{m['id']}` 含非法段", m["id"])
        if m["id"] in mods:
            m["_body"] = mods[m["id"]].get("_body")
        mods[m["id"]] = m
        written.append(m["id"])

    ch = children_map(mods)
    rels = [write_module(proj, mods[mid], bool(ch.get(mid))) for mid in written]
    prune_empty_dirs(proj)
    mods = scan(proj)
    val = validate(proj, mods, repo_root)
    r.errors.extend(val.errors)
    r.warnings.extend(val.warnings)
    r.data = {"count": len(written), "written": written, "files": rels,
              "errors": len(val.errors), "warnings": len(val.warnings)}
    return r


def cmd_patch(a) -> Result:
    r = Result("patch")
    proj = _must_project(a, "patch")
    repo_root = _repo_root(a)
    mods = scan(proj)
    mid = a.id
    if mid not in mods:
        return r.err("args/unknown-module", f"模块 `{mid}` 不存在")
    if not a.fields:
        return r.err("args/invalid-patch", "需要 --fields <json> 指定要改的字段",
                     got_keys=[])
    fields = json.loads(a.fields)
    if not isinstance(fields, dict):
        return r.err("args/invalid-patch",
                     f"patch 必须是非空对象，收到 {type(fields).__name__}",
                     got_keys=None)
    if not fields:
        return r.err("args/invalid-patch", "patch 是空对象，没有任何字段要改",
                     got_keys=[])
    if a.expect_updated_at and mods[mid].get("updated_at") != a.expect_updated_at:
        return r.err("concurrency/updated-at-mismatch",
                     f"expect_updated_at={a.expect_updated_at} 与当前 "
                     f"{mods[mid].get('updated_at')} 不符", mid)
    merged = dict(mods[mid])
    merged.update(fields)
    merged["id"] = mid
    merged["parent"] = parent_of(mid)
    merged["updated_at"] = now_iso()
    if a.dry_run:
        r.data = {"dry_run": True, "before": public(mods[mid]),
                  "after": public(merged), "changed": sorted(fields)}
        return r
    ch = children_map(mods)
    rel = write_module(proj, merged, bool(ch.get(mid)))
    mods = scan(proj)
    val = validate(proj, mods, repo_root)
    r.errors.extend(val.errors)
    r.warnings.extend(val.warnings)
    r.data = {"patched": mid, "file": rel, "changed": sorted(fields)}
    return r


def cmd_get(a) -> Result:
    r = Result("get")
    proj = _must_project(a, "get")
    mods = scan(proj)
    if a.id not in mods:
        return r.err("args/unknown-module", f"模块 `{a.id}` 不存在")
    ch = children_map(mods)
    m = public(mods[a.id])
    m["children"] = ch.get(a.id, [])
    m["is_leaf"] = not ch.get(a.id)
    r.data = {"module": m}
    return r


def cmd_list(a) -> Result:
    r = Result("list")
    proj = _must_project(a, "list")
    mods = scan(proj)
    ch = children_map(mods)
    items = []
    for mid in sorted(mods):
        m, kk = mods[mid], ch.get(mid, [])
        if a.parent and m.get("parent") != a.parent:
            continue
        if a.tree and tree_of(mid) != a.tree:
            continue
        if a.leaves and kk:
            continue
        if a.max_depth is not None and depth_of(mid) > a.max_depth:
            continue
        items.append({
            "id": mid, "name": (m.get("name") or {}).get("zh"),
            "en": (m.get("name") or {}).get("en"), "parent": m.get("parent"),
            "state": m.get("state", "active"), "depth": depth_of(mid),
            "is_leaf": not kk, "children": len(kk),
            "apis": len(m.get("apis") or []), "deps": len(m.get("deps") or []),
        })
    r.data = {"count": len(items), "modules": items,
              "trees": sorted({tree_of(k) for k in mods if not k.startswith("__broken__")})}
    return r


def cmd_delete(a) -> Result:
    r = Result("delete")
    proj = _must_project(a, "delete")
    mods = scan(proj)
    mid = a.id
    if mid not in mods:
        return r.err("args/unknown-module", f"模块 `{mid}` 不存在")
    ch = children_map(mods)
    victims = {mid}
    if a.cascade:
        stack = [mid]
        while stack:
            for c in ch.get(stack.pop(), []):
                victims.add(c)
                stack.append(c)
    elif ch.get(mid):
        return r.err("delete/has-children",
                     f"`{mid}` 有 {len(ch[mid])} 个子模块，需 --cascade",
                     children=ch[mid])

    dangling = [{"from": k, "to": d.get("to"), "kind": d.get("kind")}
                for k, m in mods.items() if k not in victims
                for d in (m.get("deps") or []) if d.get("to") in victims]
    for v in victims:
        f = modules_dir(proj) / id_to_relpath(v, bool(ch.get(v)))
        if f.exists():
            f.unlink()
        lf = layout_path(proj, v)
        if lf.exists():
            lf.unlink()
    prune_empty_dirs(proj)
    if dangling:
        r.warn("delete/dangling-edges",
               f"有 {len(dangling)} 条依赖指向被删模块，必须修复（悬空边是 error）",
               samples=dangling[:8])
    r.data = {"deleted": sorted(victims), "dangling_edges": dangling}
    return r


def cmd_move(a) -> Result:
    r = Result("move")
    proj = _must_project(a, "move")
    mods = scan(proj)
    src, dst = a.src, a.dst
    if src not in mods:
        return r.err("args/unknown-module", f"源模块 `{src}` 不存在")
    if dst in mods:
        return r.err("args/target-exists", f"目标 `{dst}` 已存在")
    ch = children_map(mods)
    subtree, stack = [src], [src]
    while stack:
        for c in ch.get(stack.pop(), []):
            subtree.append(c)
            stack.append(c)
    plan = [{"from": v, "to": (dst if v == src else dst + v[len(src):])}
            for v in subtree]
    if a.dry_run:
        r.data = {"dry_run": True, "moves": plan, "uid_preserved": True}
        return r

    mapping = {p["from"]: p["to"] for p in plan}
    newmods = {}
    for v in sorted(subtree, key=depth_of):
        m = dict(mods[v])
        nid = mapping[v]
        m["id"], m["parent"], m["updated_at"] = nid, parent_of(nid), now_iso()
        old = modules_dir(proj) / id_to_relpath(v, bool(ch.get(v)))
        if old.exists():
            old.unlink()
        newmods[nid] = m
    for v in subtree:
        mods.pop(v, None)
    mods.update(newmods)
    touched = set()
    for mid, m in mods.items():
        for d in (m.get("deps") or []):
            if d.get("to") in mapping:
                d["to"] = mapping[d["to"]]
                touched.add(mid)
    ch2 = children_map(mods)
    for mid in sorted(set(newmods) | touched):
        write_module(proj, mods[mid], bool(ch2.get(mid)))
    prune_empty_dirs(proj)

    for p in plan:
        old = layout_path(proj, p["from"])
        if old.exists():
            data = json.loads(old.read_text(encoding="utf-8"))
            data["id"] = p["to"]
            newp = layout_path(proj, p["to"])
            ensure_dir(newp.parent)
            newp.write_text(json.dumps(data, ensure_ascii=False, indent=2),
                            encoding="utf-8")
            old.unlink()
    mods = scan(proj)
    val = validate(proj, mods, _repo_root(a))
    r.errors.extend(val.errors)
    r.warnings.extend(val.warnings)
    r.data = {"moves": plan, "uid_preserved": True}
    return r


def cmd_promote(a) -> Result:
    r = Result("promote")
    proj = _must_project(a, "promote")
    mods = scan(proj)
    mid = a.id
    if mid not in mods:
        return r.err("args/unknown-module", f"模块 `{mid}` 不存在")
    if children_map(mods).get(mid):
        r.warn("promote/already-container", "已经是容器模块", mid)
        return r
    m = mods[mid]
    apis = m.pop("apis", None)
    if apis:
        r.warn("promote/apis-dropped",
               f"叶子原有 {len(apis)} 条 API，晋升为容器后必须下放到子模块",
               apis=[api_key(x) for x in apis])
    write_module(proj, m, True)
    r.data = {"promoted": mid, "file": id_to_relpath(mid, True)}
    return r


# --------------------------------------------------------------------------
# 命令：校验 / 编译 / 渲染 / 检索
# --------------------------------------------------------------------------

def cmd_fingerprint(a) -> Result:
    r = Result("fingerprint")
    repo_root = _repo_root(a)
    if not repo_root:
        return r.err("args/invalid", "需要 --repo <仓库根目录>")
    if a.source:
        srcs = json.loads(a.source)
        if isinstance(srcs, str):
            srcs = [{"path": srcs}]
        if isinstance(srcs, list) and srcs and isinstance(srcs[0], str):
            srcs = [{"path": s} for s in srcs]
        if isinstance(srcs, dict):
            srcs = [srcs]
    else:
        srcs = [{"path": p} for p in (a.path or [])]
    if not srcs:
        return r.err("args/invalid", "需要 --path <相对路径> 或 --source <json>")
    fp, missing = fingerprint_of(repo_root, srcs)
    if missing:
        r.warn("fingerprint/source-missing", f"以下文件不存在：{missing}")
    r.data = {"fingerprint": fp,
              "paths": sorted(s.get("path") for s in srcs), "missing": missing}
    return r


def cmd_validate(a) -> Result:
    proj = _must_project(a, "validate")
    mods = scan(proj)
    r = validate(proj, mods, _repo_root(a))
    r.extend(check_policy(proj, mods))
    r.data["errors"] = len(r.errors)
    r.data["warnings"] = len(r.warnings)
    return r


def cmd_build(a) -> Result:
    proj = _must_project(a, "build")
    mods = scan(proj)
    val = validate(proj, mods, _repo_root(a))
    val.extend(check_policy(proj, mods))
    r = Result("build")
    r.errors.extend(val.errors)
    r.warnings.extend(val.warnings)
    if val.errors:
        r.data = {"built": False, "reason": "validate 未通过 0 error 门禁",
                  "errors": len(val.errors), "warnings": len(val.warnings)}
        return r

    tree = build_tree(proj, mods, load_all_layouts(proj))
    (proj / "tree.json").write_text(
        json.dumps(tree, ensure_ascii=False, indent=2), encoding="utf-8")
    write_outline(proj, mods, tree)
    idx = write_api_index(proj, mods)
    write_receipt(proj, tree, val)
    out = None
    if a.render or a.out:
        out = Path(a.out) if a.out else (proj / "architecture.html")
        render_html(tree, out)
    r.data = {
        "built": True, "modules": tree["stats"]["modules"],
        "leaves": tree["stats"]["leaves"], "trees": tree["trees"],
        "max_depth": tree["stats"]["max_depth"], "apis": len(idx),
        "digest": tree["digest"], "warnings": len(val.warnings),
        "receipt": str(proj / "receipt.json"), "tree_json": str(proj / "tree.json"),
        "outline": str(proj / "outline.md"), "api_index": str(proj / "api-index.json"),
        "rendered": str(out) if out else None,
    }
    return r


def cmd_render(a) -> Result:
    proj = _must_project(a, "render")
    mods = scan(proj)
    tree = build_tree(proj, mods, load_all_layouts(proj))
    out = Path(a.out) if a.out else (proj / "architecture.html")
    render_html(tree, out)
    r = Result("render")
    r.data = {"rendered": str(out), "modules": tree["stats"]["modules"],
              "bytes": out.stat().st_size}
    return r


def cmd_search(a) -> Result:
    r = Result("search")
    proj = _must_project(a, "search")
    mods = scan(proj)
    q = (a.q or "").lower()
    if not q:
        return r.err("args/invalid", "需要 --q <关键词>")
    ch = children_map(mods)
    hits = []
    for mid, m in sorted(mods.items()):
        score, where = 0, []
        nm, ds = m.get("name") or {}, m.get("description") or {}
        if q in mid.lower():
            score += 3
            where.append("id")
        if q in (nm.get("zh") or "").lower() or q in (nm.get("en") or "").lower():
            score += 3
            where.append("name")
        if q in (ds.get("zh") or "").lower() or q in (ds.get("en") or "").lower():
            score += 1
            where.append("description")
        if any(q in (x.get("path") or "").lower() for x in (m.get("apis") or [])):
            score += 2
            where.append("api")
        if score:
            hits.append({"id": mid, "name": nm.get("zh"), "en": nm.get("en"),
                         "score": score, "matched": where,
                         "is_leaf": not ch.get(mid)})
    hits.sort(key=lambda x: (-x["score"], x["id"]))
    r.data = {"query": a.q, "count": len(hits), "hits": hits[:a.limit]}
    return r


def cmd_deps(a) -> Result:
    r = Result("deps")
    proj = _must_project(a, "deps")
    mods = scan(proj)
    mid = a.id
    if mid not in mods:
        return r.err("args/unknown-module", f"模块 `{mid}` 不存在")
    out = []
    for d in (mods[mid].get("deps") or []):
        t = d.get("to")
        item = {"to": t, "kind": d.get("kind"), "exists": t in mods,
                "name": (mods.get(t, {}).get("name") or {}).get("zh")}
        if d.get("from_api"):
            item["from_api"] = d["from_api"]
        if d.get("to_api"):
            item["to_api"] = d["to_api"]
        if d.get("label"):
            item["label"] = d["label"]
        out.append(item)
    incoming = [{"from": k, "kind": d.get("kind"),
                 "name": (m.get("name") or {}).get("zh")}
                for k, m in mods.items() for d in (m.get("deps") or [])
                if d.get("to") == mid]
    r.data = {"module": mid, "outgoing": out, "incoming": incoming,
              "children": children_map(mods).get(mid, [])}
    return r


def cmd_layout_get(a) -> Result:
    r = Result("layout-get")
    proj = _must_project(a, "layout-get")
    lay = load_layout(proj, a.id)
    if lay is None:
        r.warn("layout/missing", f"`{a.id}` 没有渲染数据", a.id)
        return r
    r.data = {"id": a.id, "layout": lay}
    return r


def cmd_layout_upsert(a) -> Result:
    r = Result("layout-upsert")
    proj = _must_project(a, "layout-upsert")
    mods = scan(proj)
    ch = children_map(mods)
    mid = a.id
    if mid not in mods:
        return r.err("args/unknown-module", f"模块 `{mid}` 不存在")
    if not ch.get(mid):
        return r.err("layout/not-container",
                     f"`{mid}` 是叶子，没有子层，不需要渲染数据")
    data = json.loads(a.data) if a.data else {}
    if not isinstance(data, dict):
        return r.err("args/invalid", "--data 必须是 JSON 对象")
    kids = set(ch[mid])
    problems = [f"order 含非直接子级 {c}" for c in (data.get("order") or [])
                if c not in kids]
    problems += [f"groups 含非直接子级 {c}"
                 for g in (data.get("groups") or [])
                 for c in (g.get("children") or []) if c not in kids]
    if problems:
        return r.err("args/invalid", "；".join(problems), mid, valid=sorted(kids))
    data.pop("schema_version", None)
    data["id"] = mid
    data["schema_version"] = SCHEMA_VERSION
    data["updated_at"] = now_iso()
    p = layout_path(proj, mid)
    ensure_dir(p.parent)
    p.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    r.data = {"written": str(p), "id": mid, "mode": data.get("mode", "auto")}
    return r


def cmd_layout_delete(a) -> Result:
    r = Result("layout-delete")
    proj = _must_project(a, "layout-delete")
    p = layout_path(proj, a.id)
    if p.exists():
        p.unlink()
        try:
            p.parent.rmdir()
        except OSError:
            pass
    r.data = {"deleted": a.id}
    return r


# --------------------------------------------------------------------------
# 命令：变更日志
# --------------------------------------------------------------------------

def _bi_arg(v):
    if v is None:
        return {"zh": "", "en": ""}
    try:
        parsed = json.loads(v)
        if isinstance(parsed, dict):
            return {"zh": parsed.get("zh", ""), "en": parsed.get("en", "")}
    except Exception:
        pass
    return {"zh": v, "en": ""}


def cmd_change_open(a) -> Result:
    r = Result("change-open")
    proj = resolve_project(a)
    if proj is None:
        return r.err("project/required", "需要 --dir 或 --project")
    ensure_dir(proj)
    ensure_dir(proj / "modules")

    acc = json.loads(a.acceptance) if a.acceptance else []
    if isinstance(acc, str):
        acc = [acc]
    if not isinstance(acc, list):
        return r.err("args/invalid", "acceptance 必须是数组")
    for i, item in enumerate(acc, 1):
        if not isinstance(item, str) or not item.strip():
            return r.err(
                "args/invalid",
                f"第 {i} 条不是非空字符串（收到 {item!r}）：acceptance 只接受"
                f"纯字符串；需要双语请写 title/intent")

    try:
        mods_plan = normalise_modules_arg(
            json.loads(a.modules) if a.modules else None)
    except ValueError as exc:
        return r.err("args/invalid", str(exc))

    title, intent = _bi_arg(a.title), _bi_arg(a.intent)
    if not title.get("zh") and not title.get("en"):
        return r.err("args/invalid", "title 必填（纯字符串或 {zh,en}）")

    seq = len(load_changes(proj)) + 1
    stamp = datetime.now().strftime("%Y%m%d")
    cid = f"chg-{stamp}-{seq:02d}"
    while change_path(proj, cid).exists():
        seq += 1
        cid = f"chg-{stamp}-{seq:02d}"

    known = scan(proj)
    missing = [m for m in mods_plan["modify"] + mods_plan["delete"]
               if m not in known]
    c = {
        "id": cid, "title": title, "intent": intent, "status": "open",
        "modules": mods_plan, "acceptance": acc, "opened_at": now_iso(),
        "closed_at": None, "updated_at": now_iso(),
        "revision": {"before": git_sha(_repo_root(a)), "after": None},
    }
    save_change(proj, c)
    if missing:
        r.warn("change/module-missing",
               f"modify/delete 引用了不存在的模块：{missing}", samples=missing)
    r.data = {"id": cid, "file": str(change_path(proj, cid)),
              "modules": mods_plan, "acceptance": len(acc)}
    return r


def cmd_change_update(a) -> Result:
    r = Result("change-update")
    proj = resolve_project(a)
    if proj is None:
        return r.err("project/required", "需要 --dir 或 --project")
    p = change_path(proj, a.id)
    if not p.exists():
        return r.err("args/unknown-change", f"变更 `{a.id}` 不存在")
    c = json.loads(p.read_text(encoding="utf-8"))
    if a.json:
        patch = json.loads(a.json)
        if "modules" in patch:
            patch["modules"] = normalise_modules_arg(patch["modules"])
        c.update(patch)
    c["updated_at"] = now_iso()
    save_change(proj, c)
    r.data = {"id": c["id"], "status": c.get("status"),
              "modules": c.get("modules")}
    return r


def cmd_change_list(a) -> Result:
    r = Result("change-list")
    proj = resolve_project(a)
    if proj is None:
        return r.err("project/required", "需要 --dir 或 --project")
    items = load_changes(proj)
    if a.status:
        items = [c for c in items if c.get("status") == a.status]
    r.data = {"count": len(items), "changes": [{
        "id": c["id"],
        "title": (c.get("title") or {}).get("zh") or (c.get("title") or {}).get("en"),
        "status": c.get("status"), "opened_at": c.get("opened_at"),
        "closed_at": c.get("closed_at"), "modules": c.get("modules"),
    } for c in items]}
    return r


def cmd_change_close(a) -> Result:
    proj = resolve_project(a)
    r = Result("change-close")
    if proj is None:
        return r.err("project/required", "需要 --dir 或 --project")
    p = change_path(proj, a.id)
    if not p.exists():
        return r.err("args/unknown-change", f"变更 `{a.id}` 不存在")
    c = json.loads(p.read_text(encoding="utf-8"))
    if c.get("status") == "verified" and not a.force:
        r.warn("change/already-closed", "该变更已关闭，未重复处理", a.id)
        r.data = {"closed": True, "id": c["id"], "already": True}
        return r

    repo_root = _repo_root(a)
    plan = c.get("modules") or {}
    mods = scan(proj)

    if a.activate:
        for mid in plan.get("create", []) + plan.get("modify", []):
            m = mods.get(mid)
            if not m or m.get("state") != "planned":
                continue
            srcs = m.get("source") or []
            fp, missing = fingerprint_of(repo_root, srcs)
            if srcs and missing:
                r.err("refresh/activate-not-landed",
                      f"`{mid}` 请求激活但源码未落地：{missing}", mid)
                continue
            m["state"] = "active"
            m["fingerprint"] = fp if srcs else "pending"
            m["revision"] = git_sha(repo_root) or m.get("revision") or ZERO_SHA
            m["updated_at"] = now_iso()
            write_module(proj, m, bool(children_map(mods).get(mid)))
        mods = scan(proj)

    still = [m for m in plan.get("create", [])
             if m in mods and mods[m].get("state") == "planned"]
    if still:
        r.err("change/create-not-landed",
              f"create 清单仍有计划态模块未落地：{still}", samples=still)
    gone = [m for m in plan.get("create", []) if m not in mods]
    if gone:
        r.err("change/create-missing", f"create 清单里的模块不存在：{gone}")

    val = validate(proj, mods, repo_root)
    val.extend(check_policy(proj, mods))
    r.errors.extend(val.errors)
    r.warnings.extend(val.warnings)
    if val.errors:
        r.data = {"closed": False, "reason": "validate 未达 0 error",
                  "errors": len(val.errors), "warnings": len(val.warnings)}
        return r

    tree = build_tree(proj, mods, load_all_layouts(proj))
    (proj / "tree.json").write_text(
        json.dumps(tree, ensure_ascii=False, indent=2), encoding="utf-8")
    write_outline(proj, mods, tree)
    write_api_index(proj, mods)
    write_receipt(proj, tree, val)
    out = None
    if a.render:
        out = proj / "architecture.html"
        render_html(tree, out)

    c["status"], c["closed_at"] = "verified", now_iso()
    c.setdefault("revision", {})["after"] = git_sha(repo_root)
    save_change(proj, c)

    r.data = {"closed": True, "id": c["id"], "modules": plan,
              "digest": tree["digest"], "warnings": len(val.warnings),
              "rendered": str(out) if out else None}
    return r


# --------------------------------------------------------------------------
# 命令：policy / check / brief / sync
# --------------------------------------------------------------------------

def cmd_policy_get(a) -> Result:
    r = Result("policy-get")
    proj = _must_project(a, "policy-get")
    r.data = {"policy": load_policy(proj),
              "default": json.loads(json.dumps(DEFAULT_POLICY))}
    return r


def cmd_policy_upsert(a) -> Result:
    r = Result("policy-upsert")
    proj = _must_project(a, "policy-upsert")
    data = json.loads(a.data) if a.data else {}
    if not isinstance(data, dict) or "rules" not in data:
        return r.err("args/invalid", "--data 必须是含 rules 的 JSON 对象")
    (proj / "policy.yml").write_text(
        yaml.safe_dump(data, allow_unicode=True, sort_keys=False),
        encoding="utf-8")
    r.data = {"written": str(proj / "policy.yml"),
              "rules": len(data.get("rules") or [])}
    return r


def cmd_check(a) -> Result:
    """设计前预检：把拟建模块 / 拟加依赖塞进影子树跑同一套规则。"""
    proj = _must_project(a, "check")
    mods = dict(scan(proj))
    pending = json.loads(a.modules) if a.modules else []
    if isinstance(pending, dict):
        pending = [pending]
    shadow = []
    for raw in pending:
        mid = raw.get("id")
        if not mid:
            return r.err("args/invalid", "拟建模块缺少 id")
        m = dict(raw)
        m["id"] = mid
        m["parent"] = parent_of(mid)
        shadow.append(mid)
        mods[mid] = m
    for d in (json.loads(a.deps) if a.deps else []):
        src = d.get("from") or d.get("module")
        if src in mods:
            mods[src].setdefault("deps", []).append(
                {"kind": d.get("kind", "reference"), "to": d.get("to")})
    r = validate(proj, mods, None)
    r.extend(check_policy(proj, mods))
    r.command = "check"
    r.data = {"shadow_modules": shadow, "errors": len(r.errors),
              "warnings": len(r.warnings)}
    return r


def cmd_brief(a) -> Result:
    r = Result("brief")
    proj = _must_project(a, "brief")
    mods = scan(proj)
    mid = a.id
    if mid not in mods:
        return r.err("args/unknown-module", f"模块 `{mid}` 不存在")
    m = mods[mid]
    incoming = sorted({k for k, x in mods.items()
                       for d in (x.get("deps") or []) if d.get("to") == mid})
    r.data = {
        "id": mid, "name": m.get("name"), "description": m.get("description"),
        "state": m.get("state", "active"),
        "contract": {"apis": m.get("apis") or [], "deps": m.get("deps") or []},
        "children": children_map(mods).get(mid, []),
        "impact": {"depends_on": [d.get("to") for d in (m.get("deps") or [])],
                   "depended_by": incoming},
        "policy": load_policy(proj),
        "acceptance": [
            f"`{mid}` 的 source 文件落地且 fingerprint 可算",
            "validate 全项目 0 error",
            f"若子级变化，同轮更新 renders/{mid.replace('.', '/')}.json",
            "change-close 收尾并记录 revision",
        ],
    }
    return r


def cmd_sync(a) -> Result:
    r = Result("sync")
    proj = _must_project(a, "sync")
    repo_root = _repo_root(a)
    if not repo_root:
        return r.err("args/invalid", "需要 --repo <仓库根目录>")
    if not is_git_repo(repo_root):
        r.warn("refresh/git-unavailable",
               "repoRoot 非 git 仓库：指纹照常重算，revision 保持原值")
    rng = a.range or "HEAD"
    changed = []
    try:
        p = subprocess.run(
            ["git", "-C", str(repo_root), "diff", "--name-only", rng],
            capture_output=True, text=True, timeout=20)
        if p.returncode == 0:
            changed = [x.strip() for x in p.stdout.splitlines() if x.strip()]
        else:
            r.warn("sync/git-failed", p.stderr.strip()[:200])
    except Exception as exc:
        r.warn("sync/git-failed", f"git diff 失败：{exc}")

    mods = scan(proj)
    affected, drifted = [], []
    for mid, m in mods.items():
        srcs = {s.get("path") for s in (m.get("source") or [])
                if isinstance(s, dict) and s.get("path")}
        if srcs & set(changed):
            affected.append(mid)
            continue
        if m.get("state") == "planned":
            continue
        fp, missing = fingerprint_of(repo_root, m.get("source") or [])
        if not missing and m.get("fingerprint") not in (None, "pending") \
                and fp != m["fingerprint"]:
            drifted.append({"id": mid, "stored": m["fingerprint"], "actual": fp})

    covered = {s["path"] for m in mods.values() for s in (m.get("source") or [])
               if isinstance(s, dict) and s.get("path")}
    review = sorted({(mods[x].get("parent") or x)
                     for x in affected + [d["id"] for d in drifted]})
    r.data = {
        "range": rng, "changed_files": changed,
        "affected": sorted(set(affected)), "drift": drifted,
        "new_files_without_module": [c for c in changed if c not in covered],
        "layouts_to_review": [x for x in review if x in mods],
        "planned_pending": sorted(k for k, m in mods.items()
                                  if m.get("state") == "planned"),
    }
    return r


# --------------------------------------------------------------------------
# 分主题速查
# --------------------------------------------------------------------------

HELP_TOPICS = {
"fields": """模块 frontmatter 字段
必填 9 个：uid / id / parent / name / description / source / revision / updated_at / fingerprint
- uid         8 位小写 hex，全项目唯一，分配后永不变（重命名/移动都保留）
- id          路径式 `[a-z0-9][a-z0-9-]*` 段以 . 连接；首段 = 树名；全项目唯一
- parent      必须等于 id 去掉最后一段；根模块为 null（唯一存储的结构引用）
- name        {zh, en}，各 <= 60 字符
- description {zh, en}，各 <= 500 字符，刻意精炼（人和 AI 都读它）
- source      数组 {path, line?, end_line?}：repo 相对路径、正斜杠、无 ..
- revision    生成时仓库的 40 位 git SHA（无 git 写 40 个 0 并告警）
- updated_at  ISO 8601，如 2026-08-30T12:00:00Z
- fingerprint source 的确定性指纹：按 path 升序，逐个
              update(UTF-8(path)) + update(0x00) + update(文件字节)，
              再取 SHA-256 前 32 位 hex。用 fingerprint 命令算，不要手估

可选字段
- state        active(默认) | planned(计划态) | deprecated(废弃)
               计划态必须 fingerprint: pending
               deprecated 可带 replacement 指向替代模块
- repository   仅根模块，该树对应仓库的 http(s) URL
- tags         自由标签（<= 12 个）
- apis         仅叶子。{protocol, method?, path, description{zh,en}}
               protocol 属于 http|ws|rpc|amqp|kafka|mysql|redis|file|grpc|graphql
               http 必须有大写 method，非 http 禁止 method
- deps         出向依赖箭头（只存源端）
               {kind, to, from_api?, to_api?, label?{zh,en}}
               kind 属于 call|event|dataflow|reference；to 可跨树
               from_api 只能是本模块 API 键；to_api 只能是目标模块自身 API 键

文件形态：有子模块的 = 容器，落 <段>/index.md；没有子模块的 = 叶子，落 <段>.md。
工具自动升降级文件形态，不用手工挪文件。""",

"deps": """箭头与 API 直连
- 只写 parent 与出向 deps；children 字段不存在（由父指针派生）。
- 跨树箭头就是普通 deps：to 指向另一棵树的模块 id，零新语法。
- API 直连：两端都声明了 API 时补 from_api / to_api，箭头才会钉在具体 API 行上；
  不补则只能落在框边，validate 会给出聚合警告 dep/unanchored。
- kind 语义：call=同步调用、event=发布/订阅、dataflow=数据管道、reference=一般引用。
  不确定就 reference 或干脆不写。
- 悬空边（dep/target-missing）是 error，删模块后必须按返回的 dangling_edges 修完。""",

"renders": """渲染数据集（renders/）
结构数据描述"是什么"，渲染数据描述"这一层怎么画"。
每个容器模块（有子模块的模块）都应在同一轮建立渲染数据；叶子不需要。
路径：renders/<id 的点号换斜杠>.json，与容器模块一一对应。

字段（✅ = 渲染器已消费；⚠️ = schema 接受但当前不影响渲染）
- order       ✅ 直接子模块的阅读顺序（生产者到消费者；未列出的按原树序追加在后）
- reading     ✅ {zh,en} 一句话阅读导语，显示在画布上方
- groups      ✅ [{id,title:{zh,en},children:[...]}]，需同时把 mode 设为 groups，
                 才会给每组画一个带标题的虚线框
- edge_hints  ✅ [{from,to,kind?,lane?,style?}] 给指定的一条边定车道或线型
                 lane 2..4 → 纵向偏移 0/12/24px；style 传 SVG dasharray 串或 "solid"
                 （bundle / priority 字段 schema 保留，暂未实现）
- mode        ⚠️ 当前只在 =groups 时决定"要不要画分组框"。auto / layers / grid
                 不改变布局 —— 实际排列完全由 order 驱动，始终是单列整洁树
- max_columns ⚠️ 暂未实现：grid 换行与列数控制尚未落地

可读性配方
1. 顺序 = 数据流：order 按"谁先产生、谁后消费"排
2. 分组 = 领域边界：同一子系统/层/角色的子模块放一组；每组 2-5 个为宜（配 mode: groups）
3. 导语 = 阅读路径：reading 一句话说明"从哪看起、箭头代表什么"
4. 长边提示：回指/跨整张图的边写 edge_hints，lane 2..4 拉开轨道
5. 不要硬凑分组：一组平级功能就别写 groups""",

"flow": """伴随开发流程（先建树、再逐个模块完成）
铁律：架构树伴随工程生长，任何"先写代码后补树"都会造成结构漂移。

一、任务开始（设计）
1. init             新项目/空目录：建 archinorm-<slug>/ 并写入默认架构规则
2. change-open      开变更（title / intent / modules{create,modify,delete} / acceptance）
                    acceptance 只接受纯字符串数组；需要双语请写 title/intent
3. brief            拿开发指引：契约、影响面、架构规则、验收清单
4. check            把拟建模块与拟加依赖先预检（parent 推导、深度、环、policy 违规）
5. upsert           建计划态模块：state=planned、fingerprint=pending、source 可指向未落地文件
                    容器同轮用 layout-upsert 写该层渲染数据

二、逐个模块实现（编码）
- 每完成一个叶子就把 state 改 active（源码未落地会报 refresh/activate-not-landed）
- 改字段用 patch（--expect-updated-at 并发保护、--dry-run 先看 diff）
- 改名/挪层用 move（保 uid、级联子模块、重写全项目 deps.to，先 --dry-run）
- 子级变化后同轮更新该层渲染数据，否则 layout/missing 会提醒
- 每次结构性改动后可跑 sync，拿到脏子树、新增文件、失效 source、planned 进度

三、任务收尾（交付）
1. change-close --activate --render：刷新指纹、激活 planned、validate 0 error 强制
2. 汇报：变更 id、涉及模块、validate/build 结果、渲染路径""",

"errors": """常见诊断码 -> 修复对照
structure/parent-mismatch     parent 不等于 id 去尾段 -> 按 evidence.derived 改 parent
structure/parent-not-exist    孤儿（父不存在）-> 创建父模块或改 parent
structure/file-id-mismatch    文件路径与 id 不一致 -> 用 upsert 重写该模块
structure/root-missing        没有 parent: null 的根模块
structure/uid-format          uid 不是 8 位小写 hex
structure/bilingual-missing   name/description 的 zh 或 en 为空
structure/leaf-too-coarse     WARN 叶子覆盖 >=3 文件 / 行跨度 >=300 / API >=6 -> promote 后拆
structure/shallow-hierarchy   WARN 模块数多但层级过浅 -> 继续下钻补中间层
api/leaf-missing              叶子缺 apis -> 补 apis
api/non-leaf                  容器/根写了 apis -> 下放到叶子并删除本字段
api/leaf-empty                WARN 叶子 apis 为空数组
api/key-duplicate             API 键全局重复 -> 只保留一个定义，其余改 path/method
api/protocol-invalid          protocol 不在白名单
api/method-invalid            http 缺大写 method / 非 http 带了 method
dep/target-missing            悬空箭头 -> 建目标模块或改/删箭头
dep/from-api-invalid          from_api 不是本模块 API -> 用本模块 apis 的键
dep/to-api-invalid            to_api 不是目标模块自身 API 键
dep/kind-invalid              kind 不在白名单
dep/self                      依赖指向自身
dep/unanchored                WARN 两端有 API 但未补 from_api/to_api
deprecation/inbound           依赖指向已废弃模块 -> 迁移到 replacement 或删除
evidence/fingerprint-drift    WARN 数据过期 -> 跑 sync 计划增量重建
evidence/source-invalid       source path 含 .. / 反斜杠 / 绝对路径
state-invalid                 state 非法
state/planned-fingerprint     计划态 fingerprint 必须是 pending
structure/planned-source-missing  WARN 计划态 source 尚未落地
layout/missing                WARN 容器缺渲染数据 -> layout-upsert 补
layout/order-child            order 引用了非直接子级
layout/group-child            groups 引用了非直接子级
layout/hint-edge-missing      WARN edge_hint 指向的兄弟边不存在
layout/orphan                 渲染数据没有对应容器
layout/not-container          叶子模块不应有渲染数据
change/module-missing         变更引用的模块不存在 -> 先建模块（可 planned）
change/create-not-landed      close 时 create 清单仍有 planned
refresh/activate-not-landed   请求激活但源码未落地
policy/<rule-id>              架构规则违规 -> 改设计；规则确需调整用 policy-upsert
concurrency/updated-at-mismatch  patch 的 expect_updated_at 与当前值不符
args/invalid-patch            patch 缺字段 / 空对象 / 非对象 -> 传非空对象""",
}


def cmd_help(a) -> Result:
    r = Result("help")
    topic = a.topic or "all"
    if topic.startswith("tool:"):
        name = topic.split(":", 1)[1]
        entry = COMMAND_REF.get(name)
        if not entry:
            return r.err("args/unknown-tool", f"未知命令 `{name}`",
                         known=sorted(COMMAND_REF))
        r.data = {"topic": topic, "tool": name, "help": entry}
        return r
    if topic == "all":
        r.data = {"topics": sorted(HELP_TOPICS),
                  "commands": {k: v["summary"] for k, v in COMMAND_REF.items()}}
        return r
    if topic == "tools":
        r.data = {"count": len(COMMAND_REF), "tools": COMMAND_REF}
        return r
    if topic not in HELP_TOPICS:
        return r.err("args/unknown-topic", f"未知主题 `{topic}`",
                     known=sorted(HELP_TOPICS) + ["tools", "all", "tool:<命令名>"])
    r.data = {"topic": topic, "text": HELP_TOPICS[topic]}
    return r


# --------------------------------------------------------------------------
# 命令参考表 + CLI
# --------------------------------------------------------------------------

COMMAND_REF = {
    "init": {"summary": "建项目目录 + 默认架构规则",
             "required": {"--dir 或 --project": "项目定位"},
             "optional": {"--slug": "项目 slug", "--repo": "源码仓库根",
                          "--repo-url": "仓库 URL（仅根模块）",
                          "--root-id": "同时建计划态根模块",
                          "--title / --title-en": "根模块双语名"}},
    "upsert": {"summary": "写模块（批量、幂等、写时自动校验）",
               "required": {"--module <json|->  或  --module-file <path>": "模块数据"},
               "optional": {"--repo": "用于算 fingerprint / revision"}},
    "patch": {"summary": "部分更新模块（只传变更字段）",
              "required": {"--id": "模块 id", "--fields <json>": "要改的字段"},
              "optional": {"--expect-updated-at": "并发保护",
                           "--dry-run": "只出 diff 不落盘", "--repo": ""}},
    "get": {"summary": "读单个模块", "required": {"--id": ""}, "optional": {}},
    "list": {"summary": "列模块 / 树",
             "required": {},
             "optional": {"--parent": "按父过滤", "--tree": "按树过滤",
                          "--leaves": "只要叶子", "--max-depth": "深度上限"}},
    "delete": {"summary": "删模块及子树（返回悬空边预警）",
               "required": {"--id": ""},
               "optional": {"--cascade": "连子模块一起删"}},
    "move": {"summary": "重命名/移动子树（保 uid、级联、重写 deps）",
             "required": {"--from": "源 id", "--to": "目标 id"},
             "optional": {"--dry-run": "", "--repo": ""}},
    "promote": {"summary": "叶子晋升为容器（便于继续下钻）",
                "required": {"--id": ""}, "optional": {}},
    "fingerprint": {"summary": "按引擎算法算 source 指纹",
                    "required": {"--repo": "仓库根"},
                    "optional": {"--path": "可重复，仓库相对路径",
                                 "--source": "JSON 数组"}},
    "validate": {"summary": "全项目校验（0 error 门禁，含 policy）",
                 "required": {}, "optional": {"--repo": "开启指纹漂移检查"}},
    "build": {"summary": "编译 + 冻结回执（tree.json / outline / api-index / receipt）",
              "required": {},
              "optional": {"--repo": "", "--render": "同时出 HTML", "--out": "HTML 路径"}},
    "render": {"summary": "tree.json -> 单文件交互式下钻 HTML",
               "required": {}, "optional": {"--out": "输出路径"}},
    "search": {"summary": "检索模块 / API",
               "required": {"--q": "关键词"},
               "optional": {"--limit": "默认 20"}},
    "deps": {"summary": "看某模块的出向依赖与反查",
             "required": {"--id": ""}, "optional": {}},
    "layout-get": {"summary": "读某容器的渲染数据",
                   "required": {"--id": ""}, "optional": {}},
    "layout-upsert": {"summary": "写/覆盖某容器的渲染数据（写时校验）",
                      "required": {"--id": "", "--data <json>": ""}, "optional": {}},
    "layout-delete": {"summary": "删渲染数据（回退自动布局）",
                      "required": {"--id": ""}, "optional": {}},
    "change-open": {"summary": "开一次开发变更",
                    "required": {"--title": "纯字符串或 {zh,en}"},
                    "optional": {"--intent": "", "--modules <json>":
                                 "{create,modify,delete}", "--acceptance <json>":
                                 "纯字符串数组", "--repo": ""}},
    "change-update": {"summary": "更新变更",
                      "required": {"--id": ""}, "optional": {"--json <json>": ""}},
    "change-list": {"summary": "列变更",
                    "required": {}, "optional": {"--status": "open|verified"}},
    "change-close": {"summary": "收尾变更（刷新指纹 / 激活 planned / 0 error 强制 / 编译）",
                     "required": {"--id": ""},
                     "optional": {"--activate": "", "--render": "", "--repo": "",
                                  "--force": ""}},
    "policy-get": {"summary": "读架构规则", "required": {}, "optional": {}},
    "policy-upsert": {"summary": "安装/覆盖架构规则",
                      "required": {"--data <json>": "含 rules"},
                      "optional": {}},
    "check": {"summary": "设计前预检：拟建模块 + 拟加依赖跑同一套规则",
              "required": {},
              "optional": {"--modules <json>": "拟建模块数组",
                           "--deps <json>": "拟加依赖数组"}},
    "brief": {"summary": "开发指引：契约、影响面、规则、验收清单",
              "required": {"--id": ""}, "optional": {}},
    "sync": {"summary": "增量再生成计划器（只读）",
             "required": {"--repo": ""},
             "optional": {"--range": "git diff 范围，默认 HEAD"}},
    "help": {"summary": "分主题速查",
             "required": {},
             "optional": {"topic": "fields|deps|renders|flow|errors|tools|all|"
                                  "tool:<命令名>"}},
}


def add_proj_args(p):
    p.add_argument("--dir", help="项目目录绝对路径（archinorm-<slug>/）")
    p.add_argument("--project", help="项目 slug（找 archinorm-<slug>）")


def build_parser():
    ap = argparse.ArgumentParser(
        prog="archinorm", description="归一化分形模块树构建器（WorkBuddy 版）")
    ap.add_argument("--human", action="store_true", help="人类可读输出（默认 JSON）")
    sub = ap.add_subparsers(dest="cmd", required=True)

    p = sub.add_parser("init", help="建项目目录 + 默认架构规则")
    add_proj_args(p)
    p.add_argument("--slug"); p.add_argument("--repo")
    p.add_argument("--repo-url"); p.add_argument("--root-id")
    p.add_argument("--title"); p.add_argument("--title-en")
    p.set_defaults(fn=cmd_init)

    p = sub.add_parser("upsert", help="写模块")
    add_proj_args(p); p.add_argument("--repo")
    p.add_argument("--module", help="模块 JSON，或 - 表示读 stdin")
    p.add_argument("--module-file")
    p.set_defaults(fn=cmd_upsert)

    p = sub.add_parser("patch", help="部分更新模块")
    add_proj_args(p); p.add_argument("--repo")
    p.add_argument("--id", required=True); p.add_argument("--fields")
    p.add_argument("--expect-updated-at"); p.add_argument("--dry-run", action="store_true")
    p.set_defaults(fn=cmd_patch)

    p = sub.add_parser("get", help="读单个模块")
    add_proj_args(p); p.add_argument("--id", required=True)
    p.set_defaults(fn=cmd_get)

    p = sub.add_parser("list", help="列模块 / 树")
    add_proj_args(p)
    p.add_argument("--parent"); p.add_argument("--tree")
    p.add_argument("--leaves", action="store_true"); p.add_argument("--max-depth", type=int)
    p.set_defaults(fn=cmd_list)

    p = sub.add_parser("delete", help="删模块及子树")
    add_proj_args(p); p.add_argument("--id", required=True)
    p.add_argument("--cascade", action="store_true")
    p.set_defaults(fn=cmd_delete)

    p = sub.add_parser("move", help="重命名/移动子树")
    add_proj_args(p); p.add_argument("--repo")
    p.add_argument("--from", dest="src", required=True)
    p.add_argument("--to", dest="dst", required=True)
    p.add_argument("--dry-run", action="store_true")
    p.set_defaults(fn=cmd_move)

    p = sub.add_parser("promote", help="叶子晋升为容器")
    add_proj_args(p); p.add_argument("--id", required=True)
    p.set_defaults(fn=cmd_promote)

    p = sub.add_parser("fingerprint", help="算 source 指纹")
    p.add_argument("--repo", required=True)
    p.add_argument("--path", action="append"); p.add_argument("--source")
    p.set_defaults(fn=cmd_fingerprint)

    p = sub.add_parser("validate", help="全项目校验")
    add_proj_args(p); p.add_argument("--repo")
    p.set_defaults(fn=cmd_validate)

    p = sub.add_parser("build", help="编译 + 冻结回执")
    add_proj_args(p); p.add_argument("--repo")
    p.add_argument("--render", action="store_true"); p.add_argument("--out")
    p.set_defaults(fn=cmd_build)

    p = sub.add_parser("render", help="出单文件交互 HTML")
    add_proj_args(p); p.add_argument("--out")
    p.set_defaults(fn=cmd_render)

    p = sub.add_parser("search", help="检索模块 / API")
    add_proj_args(p); p.add_argument("--q", required=True)
    p.add_argument("--limit", type=int, default=20)
    p.set_defaults(fn=cmd_search)

    p = sub.add_parser("deps", help="看依赖与反查")
    add_proj_args(p); p.add_argument("--id", required=True)
    p.set_defaults(fn=cmd_deps)

    p = sub.add_parser("layout-get", help="读渲染数据")
    add_proj_args(p); p.add_argument("--id", required=True)
    p.set_defaults(fn=cmd_layout_get)

    p = sub.add_parser("layout-upsert", help="写渲染数据")
    add_proj_args(p); p.add_argument("--id", required=True); p.add_argument("--data")
    p.set_defaults(fn=cmd_layout_upsert)

    p = sub.add_parser("layout-delete", help="删渲染数据")
    add_proj_args(p); p.add_argument("--id", required=True)
    p.set_defaults(fn=cmd_layout_delete)

    p = sub.add_parser("change-open", help="开变更")
    add_proj_args(p); p.add_argument("--repo")
    p.add_argument("--title"); p.add_argument("--intent")
    p.add_argument("--modules"); p.add_argument("--acceptance")
    p.set_defaults(fn=cmd_change_open)

    p = sub.add_parser("change-update", help="更新变更")
    add_proj_args(p); p.add_argument("--id", required=True); p.add_argument("--json")
    p.set_defaults(fn=cmd_change_update)

    p = sub.add_parser("change-list", help="列变更")
    add_proj_args(p); p.add_argument("--status")
    p.set_defaults(fn=cmd_change_list)

    p = sub.add_parser("change-close", help="收尾变更")
    add_proj_args(p); p.add_argument("--id", required=True); p.add_argument("--repo")
    p.add_argument("--activate", action="store_true"); p.add_argument("--render", action="store_true")
    p.add_argument("--force", action="store_true")
    p.set_defaults(fn=cmd_change_close)

    p = sub.add_parser("policy-get", help="读架构规则")
    add_proj_args(p); p.set_defaults(fn=cmd_policy_get)

    p = sub.add_parser("policy-upsert", help="写架构规则")
    add_proj_args(p); p.add_argument("--data")
    p.set_defaults(fn=cmd_policy_upsert)

    p = sub.add_parser("check", help="设计前预检")
    add_proj_args(p); p.add_argument("--modules"); p.add_argument("--deps")
    p.set_defaults(fn=cmd_check)

    p = sub.add_parser("brief", help="开发指引")
    add_proj_args(p); p.add_argument("--id", required=True)
    p.set_defaults(fn=cmd_brief)

    p = sub.add_parser("sync", help="增量再生成计划器")
    add_proj_args(p); p.add_argument("--repo"); p.add_argument("--range")
    p.set_defaults(fn=cmd_sync)

    p = sub.add_parser("help", help="分主题速查")
    p.add_argument("topic", nargs="?")
    p.set_defaults(fn=cmd_help)

    register_migrate_subparsers(sub)
    return ap


def main(argv=None) -> int:
    argv = list(sys.argv[1:] if argv is None else argv)
    human = "--human" in argv
    argv = [x for x in argv if x != "--human"]
    ap = build_parser()
    a = ap.parse_args(argv)
    a.human = human or getattr(a, "human", False)
    try:
        res = a.fn(a)
    except SystemExit:
        raise
    except Exception as exc:  # pragma: no cover
        r = Result(getattr(a, "cmd", "cli"))
        r.err("internal/error", f"{type(exc).__name__}: {exc}")
        return r.emit(human=a.human)
    return res.emit(human=a.human)


# --------------------------------------------------------------------------
# 仓库清点与批量迁移（把现有项目搬进框架）
#
# 语义：所谓"迁移"= 给项目生成一份 archinorm-<slug>/ 结构数据 + 架构图，
# 不改一行业务代码。这是文档/可视化层，不是运行时依赖。
# --------------------------------------------------------------------------

SKIP_DIRS = {
    "node_modules", ".git", ".hg", ".svn", "dist", "build", "out", "target",
    "__pycache__", ".venv", "venv", "env", ".next", ".nuxt", ".svelte-kit",
    ".idea", ".vscode", ".vs", "coverage", ".pytest_cache", ".mypy_cache",
    ".ruff_cache", ".tox", ".cache", ".parcel-cache", ".turbo", ".gradle",
    ".dart_tool", "bower_components", "vendor", "third_party", "site-packages",
    ".terraform", ".angular", ".sass-cache",
}

TEXT_EXT = {
    ".py", ".pyi", ".ts", ".tsx", ".js", ".jsx", ".mjs", ".cjs", ".go", ".rs",
    ".java", ".kt", ".kts", ".rb", ".php", ".cs", ".c", ".h", ".cc", ".cpp",
    ".hpp", ".swift", ".m", ".mm", ".scala", ".sh", ".bash", ".zsh", ".ps1",
    ".sql", ".vue", ".svelte", ".html", ".htm", ".css", ".scss", ".less",
    ".json", ".yml", ".yaml", ".toml", ".ini", ".cfg", ".md", ".txt", ".lua",
    ".dart", ".ex", ".exs", ".clj", ".r", ".jl", ".proto", ".graphql",
}

PROJECT_MARKERS = (
    ".git", "package.json", "pyproject.toml", "setup.py", "requirements.txt",
    "go.mod", "Cargo.toml", "pom.xml", "build.gradle", "composer.json",
    "Gemfile", "pubspec.yaml", "Makefile", "CMakeLists.txt",
)


def _sanitize_seg(s: str) -> str:
    s = re.sub(r"[^a-z0-9]+", "-", (s or "").lower()).strip("-")
    if not s or not s[0].isalnum():
        s = "m" + s
    return s


def collect_repo(repo: Path, max_depth: int, max_files: int) -> dict:
    """返回 {relpath: {parts, files, files_total, subdirs}}（已按 SKIP_DIRS 剪枝）。"""
    nodes: dict = {}
    for dirpath, dirnames, filenames in os.walk(repo):
        rel = Path(dirpath).relative_to(repo)
        parts = rel.parts
        if any(p in SKIP_DIRS for p in parts):
            dirnames[:] = []
            continue
        dirnames[:] = sorted(
            d for d in dirnames if d not in SKIP_DIRS and not d.startswith("."))
        files = []
        for fn in sorted(filenames):
            if fn.startswith("."):
                continue
            if Path(fn).suffix.lower() not in TEXT_EXT:
                continue
            files.append("/".join(list(parts) + [fn]))
        key = "" if str(rel) == "." else rel.as_posix()
        nodes[key] = {
            "parts": parts, "files": files[:max_files],
            "files_total": len(files), "subdirs": list(dirnames),
        }
        if len(parts) >= max_depth:
            dirnames[:] = []
    return nodes


def build_skeleton(repo: Path, slug: str, max_depth: int, max_files: int):
    """按目录结构生成模块骨架，返回 (modules, notes, scanned_files)。"""
    nodes = collect_repo(repo, max_depth, max_files)
    notes: list = []
    scanned = sum(n["files_total"] for n in nodes.values())
    sha = git_sha(repo)

    used: dict = {}
    id_of: dict = {}
    for key, node in sorted(nodes.items(), key=lambda kv: len(kv[1]["parts"])):
        if len(node["parts"]) > max_depth:
            continue
        segs = [_sanitize_seg(x) for x in node["parts"]]
        base = ".".join([slug] + segs) if segs else slug
        mid, n = base, 1
        while mid in used:
            n += 1
            mid = f"{base}-{n}"
        if mid != base:
            notes.append(f"id 冲突重命名：{base} → {mid}")
        used[mid] = True
        id_of[key] = mid

    candidate = {k: v for k, v in nodes.items() if len(v["parts"]) <= max_depth}
    mods = []
    for key, node in sorted(candidate.items(), key=lambda kv: (len(kv[1]["parts"]), kv[0])):
        mid = id_of.get(key)
        if not mid:
            continue
        segs = list(node["parts"])
        label = segs[-1] if segs else repo.name
        mods.append({
            "id": mid,
            "parent": parent_of(mid),
            "revision": sha or ZERO_SHA,
            "updated_at": now_iso(),
            "source": [{"path": f} for f in node["files"]],
            "name": {"zh": label, "en": label},
            "description": {
                "zh": (f"【待审】自动生成占位：{label}（{node['files_total']} 个文件）"
                       if segs else f"【待审】自动生成占位：{slug} 仓库根"),
                "en": (f"[REVIEW] auto-generated placeholder: {label} "
                       f"({node['files_total']} files)" if segs
                       else f"[REVIEW] auto-generated placeholder: {slug} root"),
            },
        })

    _sync_leaf_apis(mods)
    if not mods:
        notes.append("仓库里没有可识别为模块的目录")
    return mods, notes, scanned


def _sync_leaf_apis(mods: list):
    """按最终父子关系校正 apis：叶子必须有（可为空数组），容器必须没有。"""
    ids = {m["id"] for m in mods}
    parents = {m.get("parent") for m in mods if m.get("parent")}
    for m in mods:
        has_kids = m["id"] in parents
        if has_kids:
            m.pop("apis", None)
        else:
            m.setdefault("apis", [])


def detect_project_type(repo: Path) -> list:
    kinds = []
    checks = [
        ("node", ("package.json",)), ("python", ("pyproject.toml", "setup.py")),
        ("python-req", ("requirements.txt",)), ("go", ("go.mod",)),
        ("rust", ("Cargo.toml",)), ("jvm", ("pom.xml", "build.gradle")),
        ("php", ("composer.json",)), ("ruby", ("Gemfile",)),
        ("make", ("Makefile",)), ("git", (".git",)),
    ]
    for name, files in checks:
        if any((repo / f).exists() for f in files):
            kinds.append(name)
    return kinds


def cmd_inventory(a) -> Result:
    r = Result("inventory")
    repo = _repo_root(a)
    if not repo or not repo.is_dir():
        return r.err("args/invalid", "需要 --repo <存在的仓库目录>")
    slug = slugify(a.slug or repo.name)
    mods, notes, scanned = build_skeleton(repo, slug, a.depth, a.max_files)
    r.data = {
        "repo": str(repo), "slug": slug,
        "project_types": detect_project_type(repo),
        "scanned_files": scanned,
        "would_create": len(mods),
        "root_id": mods[0]["id"] if mods else None,
        "modules": [{"id": m["id"], "parent": m["parent"],
                     "sources": len(m["source"]),
                     "is_leaf": "apis" in m} for m in mods],
        "notes": notes,
    }
    if len(mods) > a.max_modules:
        r.warn("inventory/too-many-modules",
               f"将生成 {len(mods)} 个模块，超过上限 {a.max_modules}；"
               f"请降低 --depth 或提高 --max-modules")
    return r


def cmd_migrate(a) -> Result:
    """一步迁移：建结构数据目录 → 建树 → validate → build → render。"""
    r = Result("migrate")
    repo = _repo_root(a)
    if not repo or not repo.is_dir():
        return r.err("args/invalid", "需要 --repo <存在的仓库目录>")
    slug = slugify(a.slug or repo.name)
    out_root = Path(a.dir).expanduser().resolve() if a.dir else Path.cwd()
    proj = out_root / f"archinorm-{slug}"

    if proj.exists():
        if not a.force:
            return r.err("migrate/exists",
                         f"{proj} 已存在；加 --force 覆盖重建（仅删 archinorm-* 目录）")
        if not (proj.name.startswith("archinorm-") and (proj / "modules").is_dir()):
            return r.err("migrate/refuse-remove",
                         f"拒绝删除 {proj}：不是 archinorm-<slug> 结构目录（安全保护）")
        import shutil
        shutil.rmtree(proj)
    for sub in ("modules", "renders", "changes"):
        ensure_dir(proj / sub)
    (proj / "policy.yml").write_text(
        yaml.safe_dump(DEFAULT_POLICY, allow_unicode=True, sort_keys=False),
        encoding="utf-8")

    mods_list, notes, scanned = build_skeleton(repo, slug, a.depth, a.max_files)
    if not mods_list:
        return r.err("migrate/empty", f"{repo} 里没扫描到可建模块的代码目录")

    if len(mods_list) > a.max_modules:
        notes.append(f"骨架 {len(mods_list)} 个模块 > --max-modules={a.max_modules}，已截断")
        mods_list = mods_list[:a.max_modules]
        _sync_leaf_apis(mods_list)

    mods: dict = {}
    for raw in mods_list:
        m = _normalise_module(raw, mods, repo)
        mods[m["id"]] = m
    _sync_leaf_apis(list(mods.values()))
    ch = children_map(mods)
    for mid, m in mods.items():
        write_module(proj, m, bool(ch.get(mid)))
    prune_empty_dirs(proj)

    mods = scan(proj)
    ch = children_map(mods)
    val = validate(proj, mods, repo)
    val.extend(check_policy(proj, mods))
    r.errors.extend(val.errors)
    r.warnings.extend(val.warnings)

    digest, rendered = None, None
    if not val.errors:
        tree = build_tree(proj, mods, {})
        (proj / "tree.json").write_text(
            json.dumps(tree, ensure_ascii=False, indent=2), encoding="utf-8")
        write_outline(proj, mods, tree)
        write_api_index(proj, mods)
        write_receipt(proj, tree, val)
        digest = tree["digest"]
        if a.render:
            html = proj / "architecture.html"
            render_html(tree, html)
            rendered = str(html)

    r.data = {
        "project_dir": str(proj), "repo": str(repo), "slug": slug,
        "project_types": detect_project_type(repo), "scanned_files": scanned,
        "modules": len(mods),
        "leaves": sum(1 for k in mods if not ch.get(k)),
        "max_depth": max((depth_of(k) for k in mods), default=0),
        "built": bool(digest), "digest": digest, "rendered": rendered,
        "errors": len(val.errors), "warnings": len(val.warnings),
        "notes": notes,
        "next_step": "description 全部是【待审】占位，需人工补全 zh/en 后重跑 validate",
    }
    return r


def find_candidate_projects(root: Path, max_depth: int) -> list:
    found = []
    for dirpath, dirnames, filenames in os.walk(root):
        rel = Path(dirpath).relative_to(root)
        parts = rel.parts
        if any(p in SKIP_DIRS for p in parts):
            dirnames[:] = []
            continue
        dirnames[:] = sorted(
            d for d in dirnames if d not in SKIP_DIRS and not d.startswith("."))
        if len(parts) > max_depth:
            dirnames[:] = []
            continue
        if any(m in set(filenames) | set(dirnames) for m in PROJECT_MARKERS):
            found.append(Path(dirpath))
            dirnames[:] = []
    return found


def cmd_migrate_all(a) -> Result:
    r = Result("migrate-all")
    root = Path(a.root).expanduser().resolve()
    if not root.is_dir():
        return r.err("args/invalid", f"--root {root} 不是目录")
    out_root = Path(a.dir).expanduser().resolve() if a.dir else Path.cwd()
    cands = find_candidate_projects(root, a.scan_depth)

    results = []
    for repo in cands:
        sub = argparse.Namespace(
            repo=str(repo), slug=slugify(repo.name), dir=str(out_root),
            depth=a.depth, max_files=a.max_files, max_modules=a.max_modules,
            render=a.render, force=a.force, human=False)
        try:
            res = cmd_migrate(sub)
        except SystemExit as exc:
            results.append({"repo": str(repo), "ok": False,
                            "reason": f"SystemExit({exc.code})",
                            "project_dir": str(out_root / f"archinorm-{slugify(repo.name)}")})
            continue
        except Exception as exc:
            results.append({"repo": str(repo), "ok": False,
                            "reason": f"{type(exc).__name__}: {exc}",
                            "project_dir": str(out_root / f"archinorm-{slugify(repo.name)}")})
            continue
        results.append({
            "repo": str(repo), "ok": res.ok,
            "project_dir": res.data.get("project_dir"),
            "modules": res.data.get("modules"),
            "errors": len(res.errors), "warnings": len(res.warnings),
            "rendered": res.data.get("rendered"),
            "first_error": (res.errors[0]["message"] if res.errors else None),
        })

    ok = [x for x in results if x["ok"]]
    bad = [x for x in results if not x["ok"]]
    r.data = {"root": str(root), "candidates": len(cands),
              "succeeded": len(ok), "failed": len(bad), "results": results}
    if bad:
        r.warn("migrate-all/partial",
               f"{len(bad)} 个项目迁移未成功，已如实列出，未掩盖")
    return r


def register_migrate_subparsers(sub):
    if "inventory" in getattr(sub, "choices", {}):
        return sub
    p = sub.add_parser("inventory", help="只读清点仓库，预告会生成哪些模块")
    p.add_argument("--repo", required=True)
    p.add_argument("--slug")
    p.add_argument("--depth", type=int, default=2)
    p.add_argument("--max-files", type=int, default=40)
    p.add_argument("--max-modules", type=int, default=300)
    p.set_defaults(fn=cmd_inventory)

    p = sub.add_parser("migrate", help="一步迁移：建树→validate→build→render")
    add_proj_args(p)
    p.add_argument("--repo", required=True)
    p.add_argument("--slug")
    p.add_argument("--depth", type=int, default=2)
    p.add_argument("--max-files", type=int, default=40)
    p.add_argument("--max-modules", type=int, default=300)
    p.add_argument("--render", action="store_true")
    p.add_argument("--force", action="store_true")
    p.set_defaults(fn=cmd_migrate)

    p = sub.add_parser("migrate-all", help="扫描根目录下的全部项目，逐个迁移")
    p.add_argument("--root", required=True)
    p.add_argument("--dir")
    p.add_argument("--scan-depth", type=int, default=3)
    p.add_argument("--depth", type=int, default=2)
    p.add_argument("--max-files", type=int, default=40)
    p.add_argument("--max-modules", type=int, default=300)
    p.add_argument("--render", action="store_true")
    p.add_argument("--force", action="store_true")
    p.set_defaults(fn=cmd_migrate_all)
    return sub


COMMAND_REF.update({
    "inventory": {"summary": "只读清点仓库，预告会生成哪些模块",
                  "required": {"--repo": "仓库根"},
                  "optional": {"--slug": "项目 slug", "--depth": "默认 2",
                               "--max-files": "每模块保留文件数，默认 40",
                               "--max-modules": "上限，默认 300"}},
    "migrate": {"summary": "一步迁移：建树→validate→build→render（不改业务代码）",
                "required": {"--repo": "仓库根"},
                "optional": {"--dir": "输出目录", "--slug": "",
                             "--depth": "默认 2", "--max-files": "默认 40",
                             "--max-modules": "默认 300",
                             "--render": "同时出 HTML", "--force": "覆盖重建"}},
    "migrate-all": {"summary": "扫描根目录下全部项目，逐个迁移",
                    "required": {"--root": "待扫描根目录"},
                    "optional": {"--dir": "输出目录", "--scan-depth": "默认 3",
                                 "--depth": "模块深度，默认 2",
                                 "--max-modules": "默认 300",
                                 "--render": "", "--force": ""}},
})

HELP_TOPICS["migrate"] = """把现有项目搬进框架

先看清楚会生成什么（只读）：
  archinorm.py inventory --repo /path/to/proj

单个项目迁移：
  archinorm.py migrate --repo /path/to/proj --dir <输出目录> --render

批量迁移：
  archinorm.py migrate-all --root /path/to/projects --dir <输出目录> --render

语义（重要）：
  "迁移" = 给项目生成一份 archinorm-<slug>/ 结构数据 + 架构图，不改一行业务代码。
  这是文档/可视化层，不是运行时依赖；业务代码零改动、零风险。

自动生成的模块：
  - 按目录结构切模块，source 填该目录下的代码文件
  - description 一律写成【待审】占位，必须人工补全 zh/en 后重跑 validate
  - 叶子 apis 为空数组（api/leaf-empty 警告属正常起步状态）
  - fingerprint 用真实文件算出；非 git 仓库 revision 记 40 个 0

参数建议：
  --depth 2     小项目；中型用 3；大仓先从 2 起步再逐层下钻
  --max-modules 默认 300，防爆量；撑爆就降 --depth
  --force       只删 archinorm-* 结构目录，绝不会碰业务代码"""


# --------------------------------------------------------------------------
# 进程入口（必须位于最后一个分段：main() 依赖全部注册函数已加载）
# --------------------------------------------------------------------------

if __name__ == "__main__":
    sys.exit(main())
