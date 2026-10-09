
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
