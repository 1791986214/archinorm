
# --------------------------------------------------------------------------
# 变更日志
# --------------------------------------------------------------------------

def change_path(proj: Path, cid: str) -> Path:
    return changes_dir(proj) / f"{cid}.json"


def load_changes(proj: Path) -> list:
    d = changes_dir(proj)
    if not d.is_dir():
        return []
    out = []
    for f in sorted(d.glob("*.json")):
        try:
            out.append(json.loads(f.read_text(encoding="utf-8")))
        except Exception:
            pass
    return out


def save_change(proj: Path, c: dict):
    ensure_dir(changes_dir(proj))
    change_path(proj, c["id"]).write_text(
        json.dumps(c, ensure_ascii=False, indent=2), encoding="utf-8")


def normalise_modules_arg(raw) -> dict:
    """modules 允许 {create,modify,delete} 或裸列表（视为 create）。"""
    if raw is None:
        return {"create": [], "modify": [], "delete": []}
    if isinstance(raw, list):
        return {"create": [str(x) for x in raw], "modify": [], "delete": []}
    out = {}
    for k in ("create", "modify", "delete"):
        v = raw.get(k) or []
        if not isinstance(v, list):
            raise ValueError(f"modules.{k} 必须是数组")
        out[k] = [str(x) for x in v]
    return out


def bi_arg(v) -> dict:
    if v is None:
        return {"zh": "", "en": ""}
    try:
        parsed = json.loads(v)
        if isinstance(parsed, dict):
            return {"zh": parsed.get("zh", ""), "en": parsed.get("en", "")}
    except Exception:
        pass
    return {"zh": v, "en": ""}


# --------------------------------------------------------------------------
# 架构规则（policy.yml）
# --------------------------------------------------------------------------

DEFAULT_POLICY = {
    "version": 1,
    "rules": [
        {"id": "core-acyclic", "type": "acyclic", "severity": "error"},
        {"id": "no-deprecated-inbound", "type": "forbid-dependency",
         "severity": "warning", "to_state": "deprecated"},
    ],
}


def load_policy(proj: Path) -> dict:
    p = proj / "policy.yml"
    if not p.is_file():
        return json.loads(json.dumps(DEFAULT_POLICY))
    try:
        data = yaml.safe_load(p.read_text(encoding="utf-8"))
        return data if isinstance(data, dict) else json.loads(json.dumps(DEFAULT_POLICY))
    except Exception:
        return json.loads(json.dumps(DEFAULT_POLICY))


def _id_match(mid, pattern) -> bool:
    if pattern.endswith(".*"):
        return mid.startswith(pattern[:-1])
    return mid == pattern


def _rank(mid, rank):
    best = None
    for pat, i in rank.items():
        if _id_match(mid, pat):
            best = i if best is None else min(best, i)
    return best


def check_policy(proj: Path, mods: dict) -> Result:
    r = Result("policy")
    pol = load_policy(proj)
    rules = pol.get("rules") or []

    for rule in rules:
        t = rule.get("type")
        sev = rule.get("severity", "error")
        rid = rule.get("id", t)
        emit = r.err if sev == "error" else r.warn

        if t == "acyclic":
            color, found = {}, []

            def dfs(u):
                color[u] = 1
                for d in (mods[u].get("deps") or []):
                    v = d.get("to")
                    if v not in mods:
                        continue
                    if color.get(v) == 1:
                        found.append((u, v))
                    elif color.get(v, 0) == 0:
                        dfs(v)
                color[u] = 2

            for k in mods:
                if color.get(k, 0) == 0:
                    dfs(k)
            for u, v in found:
                emit(f"policy/{rid}", f"依赖成环：{u} → {v}", u)

        elif t == "max-depth":
            limit = rule.get("limit", 8)
            for k in mods:
                if depth_of(k) > limit:
                    emit(f"policy/{rid}", f"深度 {depth_of(k)} 超过上限 {limit}", k)

        elif t == "naming":
            pat = re.compile(rule.get("pattern") or r"^[a-z0-9-]+$")
            for k in mods:
                bad = next((s for s in k.split(".") if not pat.match(s)), None)
                if bad:
                    emit(f"policy/{rid}", f"id 段 `{bad}` 不符合命名规则", k)

        elif t == "forbid-dependency":
            fr, to = rule.get("from"), rule.get("to")
            to_state = rule.get("to_state")
            for k, m in mods.items():
                if fr and not _id_match(k, fr):
                    continue
                for d in (m.get("deps") or []):
                    tgt = d.get("to")
                    if to and _id_match(tgt, to):
                        emit(f"policy/{rid}", f"禁止的依赖：{k} → {tgt}", k)
                    if to_state and (mods.get(tgt) or {}).get("state") == to_state:
                        emit(f"policy/{rid}",
                             f"依赖指向 {to_state} 模块：{k} → {tgt}", k)

        elif t == "dependency-direction":
            rank = {}
            for i, grp in enumerate(rule.get("layers") or []):
                for pat in grp:
                    rank[pat] = i
            for k, m in mods.items():
                for d in (m.get("deps") or []):
                    tgt = d.get("to")
                    a, b = _rank(k, rank), _rank(tgt, rank)
                    if a is not None and b is not None and b < a:
                        emit(f"policy/{rid}",
                             f"依赖方向违规：{k}（第{a}层）→ {tgt}（第{b}层）", k)

        else:
            r.warn("policy/unknown-rule-type",
                   f"规则 `{rid}` 的类型 `{t}` 未实现，已跳过")

    r.data = {"rules": len(rules)}
    return r
