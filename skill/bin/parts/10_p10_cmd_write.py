
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
