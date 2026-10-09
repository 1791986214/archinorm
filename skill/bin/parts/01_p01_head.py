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
