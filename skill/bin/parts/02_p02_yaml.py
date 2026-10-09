
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
