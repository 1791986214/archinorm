
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
