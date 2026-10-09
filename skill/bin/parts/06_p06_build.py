
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
