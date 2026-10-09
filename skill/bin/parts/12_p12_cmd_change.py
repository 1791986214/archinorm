
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
