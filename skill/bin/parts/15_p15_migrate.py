
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
