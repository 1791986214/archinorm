
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
