
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
