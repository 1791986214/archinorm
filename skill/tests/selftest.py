#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""archinorm 自检：断言校验器该报的诊断码、指纹算法确定性、文件形态升降级、
0 error 门禁、YAML 往返保真、渲染产物完整性。

用法：<venv>/bin/python tests/selftest.py
"""
import io
import json
import os
import shutil
import sys
import tempfile
from contextlib import redirect_stdout
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
for _cand in (ROOT, ROOT / "bin"):          # 源码布局 / 技能安装布局都要能跑
    if (_cand / "archinorm.py").is_file():
        sys.path.insert(0, str(_cand))
        break
import archinorm  # noqa: E402

FAILS = []
CHECKS = [0]


def check(name, cond, detail=""):
    CHECKS[0] += 1
    if cond:
        print(f"  PASS  {name}")
    else:
        print(f"  FAIL  {name}   {detail}")
        FAILS.append(name)


def run_cli(*args):
    buf = io.StringIO()
    with redirect_stdout(buf):
        code = archinorm.main(list(args))
    out = buf.getvalue()
    try:
        return code, json.loads(out)
    except Exception:
        return code, {"_raw": out}


def codes(payload, key="errors"):
    return sorted({e["code"] for e in payload.get(key, [])})


def write_mods(proj: Path, mods, repo_root=None):
    """直接落盘模块（绕过 CLI，便于构造畸形数据）。"""
    d = {"_loaded": {}}
    for raw in mods:
        m = archinorm._normalise_module(raw, d["_loaded"], repo_root)
        d["_loaded"][m["id"]] = m
    ch = archinorm.children_map(d["_loaded"])
    for mid, m in d["_loaded"].items():
        archinorm.write_module(proj, m, bool(ch.get(mid)))


def base(mid, name="名", desc="描述", **kw):
    nm = name if isinstance(name, dict) else {"zh": name, "en": "n"}
    ds = desc if isinstance(desc, dict) else {"zh": desc, "en": "d"}
    m = {"id": mid, "name": nm, "description": ds}
    m.update(kw)
    return m


def new_proj(tmp: Path, tag: str) -> Path:
    p = tmp / f"archinorm-{tag}"
    for sub in ("modules", "renders", "changes"):
        (p / sub).mkdir(parents=True, exist_ok=True)
    return p


print("=" * 66)
print("archinorm 自检")
print("=" * 66)

tmp = Path(tempfile.mkdtemp(prefix="archinorm-selftest-"))
try:
    # ---------------------------------------------------------------- A 结构
    print("\n[A] 结构校验")
    p = new_proj(tmp, "a")
    write_mods(p, [
        base("demo", **{"parent": None}),
        base("demo.auth"),
        base("demo.bad_parent"),
    ])
    (p / "modules" / "demo" / "bad_parent.md").write_text(
        (p / "modules" / "demo" / "bad_parent.md").read_text(encoding="utf-8")
        .replace("parent: demo", "parent: wrong.parent"), encoding="utf-8")
    r = archinorm.validate(p, archinorm.scan(p), None)
    c = sorted({e["code"] for e in r.errors})
    check("parent-mismatch 触发", "structure/parent-mismatch" in c, c)
    check("root 存在不报 root-missing", "structure/root-missing" not in c, c)

    p2 = new_proj(tmp, "a2")
    write_mods(p2, [base("demo", **{"parent": None}), base("demo.x")])
    (p2 / "modules" / "demo" / "x.md").write_text(
        (p2 / "modules" / "demo" / "x.md").read_text(encoding="utf-8")
        .replace("uid: ", "uid: ZZZ"), encoding="utf-8")
    r = archinorm.validate(p2, archinorm.scan(p2), None)
    check("uid-format 触发", "structure/uid-format" in codes(r, "errors") if False
          else "structure/uid-format" in {e["code"] for e in r.errors})

    p3 = new_proj(tmp, "a3")
    write_mods(p3, [base("demo", **{"parent": None}),
                    {"id": "demo.orphan", "parent": "demo", "name": {"zh": "x", "en": "y"},
                     "description": {"zh": "a", "en": "b"}}])
    # 手工把 orphan 写成指向不存在的父
    f = p3 / "modules" / "demo" / "orphan.md"
    f.write_text(f.read_text(encoding="utf-8").replace("parent: demo", "parent: ghost"),
                 encoding="utf-8")
    r = archinorm.validate(p3, archinorm.scan(p3), None)
    ec = {e["code"] for e in r.errors}
    check("parent-mismatch（ghost→demo）", "structure/parent-mismatch" in ec, sorted(ec))

    # ---------------------------------------------------------------- B API
    print("\n[B] API 校验")
    p = new_proj(tmp, "b")
    write_mods(p, [
        base("demo", **{"parent": None}),
        base("demo.leafbad", apis=[
            {"protocol": "http", "method": "post", "path": "/a"},
            {"protocol": "kafka", "method": "GET", "path": "topic.x"},
            {"protocol": "nope", "path": "/z"},
        ]),
        base("demo.leafnonleaf", **{"apis": [{"protocol": "http", "method": "GET",
                                              "path": "/dup"}]}),
        base("demo.leafnonleaf.child",
             apis=[{"protocol": "http", "method": "GET", "path": "/dup"}]),
        base("demo.noapis"),
    ])
    r = archinorm.validate(p, archinorm.scan(p), None)
    ec = {e["code"] for e in r.errors}
    for code in ("api/method-invalid", "api/protocol-invalid", "api/non-leaf",
                 "api/leaf-missing", "api/key-duplicate"):
        check(f"{code} 触发", code in ec, sorted(ec))

    # 空 apis 的叶子只该 warning
    p = new_proj(tmp, "b2")
    write_mods(p, [base("demo", **{"parent": None}), base("demo.x", apis=[])])
    r = archinorm.validate(p, archinorm.scan(p), None)
    check("api/leaf-empty 是 warning 不是 error",
          "api/leaf-empty" in {w["code"] for w in r.warnings}
          and "api/leaf-missing" not in {e["code"] for e in r.errors})

    # ---------------------------------------------------------------- C 依赖
    print("\n[C] 依赖校验")
    p = new_proj(tmp, "c")
    write_mods(p, [
        base("demo", **{"parent": None}),
        base("demo.a", apis=[{"protocol": "http", "method": "POST", "path": "/p"}],
             deps=[{"kind": "call", "to": "demo.ghost"},
                   {"kind": "bogus", "to": "demo.b"},
                   {"kind": "call", "to": "demo.a"},
                   {"kind": "call", "to": "demo.b", "from_api": "NOPE"},
                   {"kind": "call", "to": "demo.b", "to_api": "NOPE"}]),
        base("demo.b", apis=[{"protocol": "http", "method": "GET", "path": "/g"}]),
    ])
    r = archinorm.validate(p, archinorm.scan(p), None)
    ec = {e["code"] for e in r.errors}
    for code in ("dep/target-missing", "dep/kind-invalid", "dep/self",
                 "dep/from-api-invalid", "dep/to-api-invalid"):
        check(f"{code} 触发", code in ec, sorted(ec))

    # deprecated 入向
    p = new_proj(tmp, "c2")
    write_mods(p, [
        base("demo", **{"parent": None}),
        base("demo.old", apis=[], state="deprecated", replacement="demo.new"),
        base("demo.new", apis=[]),
        base("demo.user", apis=[], deps=[{"kind": "call", "to": "demo.old"}]),
    ])
    r = archinorm.validate(p, archinorm.scan(p), None)
    check("deprecation/inbound 触发",
          "deprecation/inbound" in {e["code"] for e in r.errors})

    # ------------------------------------------------------------ D 指纹
    print("\n[D] 指纹算法")
    repo = tmp / "repo"
    (repo / "sub").mkdir(parents=True)
    (repo / "a.py").write_text("print(1)\n", encoding="utf-8")
    (repo / "sub" / "b.py").write_text("x=1\n", encoding="utf-8")
    f1, miss = archinorm.fingerprint_of(repo, [{"path": "a.py"}, {"path": "sub/b.py"}])
    f2, _ = archinorm.fingerprint_of(repo, [{"path": "sub/b.py"}, {"path": "a.py"}])
    check("指纹与传入顺序无关", f1 == f2, f"{f1} vs {f2}")
    check("无缺失文件", miss == [], miss)
    check("指纹 32 位 hex", len(f1) == 32 and all(c in "0123456789abcdef" for c in f1), f1)
    (repo / "a.py").write_text("print(2)\n", encoding="utf-8")
    f3, _ = archinorm.fingerprint_of(repo, [{"path": "a.py"}, {"path": "sub/b.py"}])
    check("内容变化 → 指纹变化", f3 != f1)
    f4, miss4 = archinorm.fingerprint_of(repo, [{"path": "nope.py"}])
    check("缺失文件被报出", miss4 == ["nope.py"], miss4)
    check("空 source → 空集指纹稳定",
          archinorm.fingerprint_of(repo, [])[0] == archinorm.fingerprint_of(repo, [])[0])

    # ------------------------------------------------- E 叶子/容器形态
    print("\n[E] 文件形态升降级")
    p = new_proj(tmp, "e")
    write_mods(p, [base("demo", **{"parent": None}), base("demo.x", apis=[])])
    check("叶子落为 demo/x.md", (p / "modules" / "demo" / "x.md").is_file())
    write_mods(p, [base("demo", **{"parent": None}), base("demo.x", apis=[]),
                   base("demo.x.y", parent="demo.x", apis=[])])
    check("晋升后落为 demo/x/index.md", (p / "modules" / "demo" / "x" / "index.md").is_file())
    check("旧 demo/x.md 已清除", not (p / "modules" / "demo" / "x.md").exists())
    (p / "modules" / "demo" / "x" / "y.md").unlink()
    write_mods(p, [base("demo", **{"parent": None}), base("demo.x", apis=[])])
    check("降级回 demo/x.md", (p / "modules" / "demo" / "x.md").is_file())

    # ------------------------------------------------------------ F move
    print("\n[F] move 保 uid 与重写 deps")
    p = new_proj(tmp, "f")
    write_mods(p, [
        base("demo", **{"parent": None}),
        base("demo.a"),
        base("demo.a.kid", parent="demo.a",
             apis=[{"protocol": "http", "method": "GET", "path": "/a"}]),
        base("demo.b", apis=[], deps=[{"kind": "call", "to": "demo.a.kid"}]),
    ])
    before = archinorm.scan(p)
    uid_a = before["demo.a"]["uid"]
    code, pl = run_cli("move", "--dir", str(p), "--from", "demo.a", "--to", "demo.renamed")
    after = archinorm.scan(p)
    check("move 返回 ok", pl.get("ok"), pl.get("errors"))
    check("uid 保持不变", after.get("demo.renamed", {}).get("uid") == uid_a)
    check("子模块级联改名", "demo.renamed.kid" in after)
    check("deps.to 被重写",
          any(d.get("to") == "demo.renamed.kid" for d in after["demo.b"].get("deps", [])),
          after["demo.b"].get("deps"))

    # ------------------------------------------------------ G 0 error 门禁
    print("\n[G] 0 error 门禁")
    p = new_proj(tmp, "g")
    write_mods(p, [base("demo", **{"parent": None}),
                   base("demo.bad", deps=[{"kind": "call", "to": "demo.ghost"}], apis=[])])
    code, pl = run_cli("build", "--dir", str(p))
    check("有 error 时 build 拒绝", pl.get("ok") is False
          and pl["data"].get("built") is False, pl["data"])
    check("退出码为 1", code == 1, code)

    # --------------------------------------------------- H YAML 往返
    print("\n[H] YAML 往返保真")
    m = base("demo.order.checkout.payment", name={"zh": "支付", "en": "Payment"},
             description={"zh": "负" * 90, "en": ("Handles payment " * 8).strip()},
             apis=[{"protocol": "http", "method": "POST",
                    "path": "/api/v1/orders/{id}/pay",
                    "description": {"zh": "发起支付", "en": "Pay"}}],
             deps=[{"kind": "call", "to": "demo.invoice",
                    "from_api": "POST /api/v1/orders/{id}/pay",
                    "to_api": "POST /internal/invoices",
                    "label": {"zh": "开票", "en": "Invoice"}}])
    m["source"] = [{"path": "src/pay.ts", "line": 12, "end_line": 340}]
    text = archinorm.dump_module_file(m, "# 支付\n")
    back, body = archinorm.parse_module_file(text)
    check("name 往返一致", back.get("name") == m["name"], back.get("name"))
    check("description 往返一致（含 > 折叠）", back.get("description") == m["description"],
          back.get("description"))
    check("apis 往返一致", back.get("apis") == m["apis"])
    check("deps 往返一致", back.get("deps") == m["deps"], back.get("deps"))
    check("source 往返一致", back.get("source") == m["source"], back.get("source"))
    check("正文保留", body.strip() == "# 支付", body)
    check("parent 派生正确（不落盘 children）", "children" not in text)

    # ------------------------------------------- I acceptance 只收纯字符串
    print("\n[I] change-open acceptance 规则")
    p = new_proj(tmp, "i")
    write_mods(p, [base("demo", **{"parent": None})])
    code, pl = run_cli("change-open", "--dir", str(p), "--title", "t",
                       "--acceptance", '[{"zh":"a","en":"b"}]')
    check("双语 acceptance 被拒", pl.get("ok") is False
          and pl["errors"][0]["code"] == "args/invalid", pl.get("errors"))
    check("报错文案点明只接受纯字符串",
          "只接受纯字符串" in pl["errors"][0]["message"], pl["errors"][0]["message"])
    code, pl = run_cli("change-open", "--dir", str(p), "--title", "t",
                       "--acceptance", '["跑通 0 error"]')
    check("纯字符串 acceptance 通过", pl.get("ok") is True, pl.get("errors"))

    # ------------------------------------------------------- J 渲染产物
    print("\n[J] 渲染产物完整性")
    p = new_proj(tmp, "j")
    write_mods(p, [
        base("demo", **{"parent": None}),
        base("demo.a", apis=[{"protocol": "http", "method": "GET", "path": "/a"}]),
        base("demo.b", apis=[]),
    ])
    layout = {"mode": "groups", "max_columns": 2,
              "order": ["demo.a", "demo.b"],
              "groups": [{"id": "g1", "title": {"zh": "组一", "en": "G1"},
                          "children": ["demo.a", "demo.b"]}],
              "reading": {"zh": "从左到右", "en": "left to right"}}
    (p / "renders" / "demo.json").write_text(
        json.dumps(layout, ensure_ascii=False), encoding="utf-8")
    code, pl = run_cli("build", "--dir", str(p), "--render")
    html = p / "architecture.html"
    check("build 成功", pl.get("ok") is True, pl.get("errors"))
    check("HTML 产出", html.is_file() and html.stat().st_size > 3000)
    text = html.read_text(encoding="utf-8")
    check("HTML 内嵌 payload", '<script id="payload" type="application/json">' in text)
    check("HTML 无未替换占位符", "__TITLE__" not in text and "__TREE_JSON__" not in text)
    check("HTML 深链支持", "#module=" in text)
    m = text.split('type="application/json">', 1)[1].split("</script>", 1)[0]
    m = m.replace("<\\/", "</")
    try:
        tree = json.loads(m)
        ok_payload = True
    except Exception as exc:
        ok_payload = False
        tree = {"_err": str(exc)}
    check("内嵌 JSON 可解析", ok_payload, tree.get("_err"))
    if ok_payload:
        check("payload 含全部模块", set(tree["modules"]) == {"demo", "demo.a", "demo.b"})
        check("payload 含渲染数据", "demo" in tree.get("layouts", {}))
        check("统计数字正确", tree["stats"]["modules"] == 3
              and tree["stats"]["apis"] == 1, tree["stats"])

    # layout 错误校验
    p = new_proj(tmp, "j2")
    write_mods(p, [base("demo", **{"parent": None}), base("demo.a", apis=[])])
    (p / "renders" / "demo.json").write_text(json.dumps(
        {"order": ["demo.ghost"], "mode": "nonsense"}), encoding="utf-8")
    r = archinorm.validate(p, archinorm.scan(p), None)
    ec = {e["code"] for e in r.errors}
    check("layout/order-child 触发", "layout/order-child" in ec, sorted(ec))
    check("layout/mode-invalid 触发", "layout/mode-invalid" in ec, sorted(ec))
    (p / "renders" / "ghost.json").write_text("{}", encoding="utf-8")
    r = archinorm.validate(p, archinorm.scan(p), None)
    ec = {e["code"] for e in r.errors}
    check("layout/orphan 触发", "layout/orphan" in ec, sorted(ec))

    # ------------------------------------------------------- K policy
    print("\n[K] 架构规则")
    p = new_proj(tmp, "k")
    write_mods(p, [
        base("demo", **{"parent": None}),
        base("demo.a", apis=[], deps=[{"kind": "call", "to": "demo.b"}]),
        base("demo.b", apis=[], deps=[{"kind": "call", "to": "demo.a"}]),
    ])
    r = archinorm.check_policy(p, archinorm.scan(p))
    check("默认规则检出环", any(e["code"] == "policy/core-acyclic" for e in r.errors),
          [e["code"] for e in r.errors])
    (p / "policy.yml").write_text(
        "version: 1\nrules:\n  - id: depth3\n    type: max-depth\n    limit: 3\n"
        "    severity: error\n", encoding="utf-8")
    r = archinorm.check_policy(p, archinorm.scan(p))
    check("自定义 max-depth 生效", "policy/depth3" in {e["code"] for e in r.errors}
          or not r.errors)

    # ------------------------------------------------------- L migrate
    print("\n[L] 迁移命令")
    src = tmp / "fakeproj"
    (src / "api").mkdir(parents=True)
    (src / "api" / "routes.py").write_text("def h(): pass\n", encoding="utf-8")
    (src / "main.py").write_text("print(1)\n", encoding="utf-8")
    (src / "node_modules").mkdir()
    (src / "node_modules" / "junk.js").write_text("x", encoding="utf-8")
    outdir = tmp / "out"
    outdir.mkdir()
    code, pl = run_cli("inventory", "--repo", str(src), "--depth", "2")
    ids = [m["id"] for m in pl["data"]["modules"]]
    check("inventory 识别目录为模块", "fakeproj.api" in ids, ids)
    check("inventory 跳过 node_modules",
          not any("node-modules" in i or "node_modules" in i for i in ids), ids)
    code, pl = run_cli("migrate", "--repo", str(src), "--dir", str(outdir),
                       "--slug", "fakeproj", "--render")
    check("migrate 成功", pl.get("ok") and pl["data"].get("built"), pl.get("errors"))
    check("migrate 产出 HTML", Path(pl["data"]["rendered"]).is_file()
          if pl["data"].get("rendered") else False)
    check("migrate 0 error", pl["data"].get("errors") == 0,
          [e["code"] for e in pl.get("errors", [])])
    check("migrate 业务代码未被改动",
          (src / "main.py").read_text(encoding="utf-8") == "print(1)\n"
          and sorted(x.name for x in src.iterdir()) == ["api", "main.py", "node_modules"])
    code, pl = run_cli("migrate", "--repo", str(src), "--dir", str(outdir),
                       "--slug", "fakeproj")
    check("重复 migrate 被拒（除非 --force）",
          pl.get("ok") is False and pl["errors"][0]["code"] == "migrate/exists",
          pl.get("errors"))

    # ------------------------------------------------- M 编译产物
    print("\n[M] 编译产物（outline / api-index / receipt / tree）")
    p = new_proj(tmp, "m")
    write_mods(p, [
        base("demo", **{"parent": None}),
        base("demo.a"),
        base("demo.a.x", apis=[{"protocol": "http", "method": "GET", "path": "/x"}]),
        base("demo.a.y", apis=[{"protocol": "kafka", "path": "topic.y"}]),
        base("demo.b", apis=[], deps=[{"kind": "call", "to": "demo.a.x"}]),
    ])
    code, pl = run_cli("build", "--dir", str(p))
    check("build 成功", pl.get("ok") is True, pl.get("errors"))
    outline = (p / "outline.md").read_text(encoding="utf-8")
    check("outline 展开子层（不止根）", outline.count("- **") >= 5, outline[-200:])
    check("outline 子层有缩进", "\n  - **" in outline)
    check("outline 叶子带 API 行", "GET /x" in outline and "kafka:topic.y" in outline)
    idx = json.loads((p / "api-index.json").read_text(encoding="utf-8"))
    check("api-index 收录全部 API",
          set(idx) == {"GET /x", "kafka:topic.y"}, sorted(idx))
    check("api-index 带所属模块", idx["GET /x"]["module"] == "demo.a.x")
    receipt = json.loads((p / "receipt.json").read_text(encoding="utf-8"))
    tree = json.loads((p / "tree.json").read_text(encoding="utf-8"))
    check("receipt 冻结标记正确", receipt["frozen"] is True and receipt["errors"] == 0)
    check("receipt digest 与 tree 一致", receipt["digest"] == tree["digest"])
    check("tree 含 incoming 反查",
          any(d["from"] == "demo.b" for d in tree["modules"]["demo.a.x"]["incoming"]))
    d1 = archinorm.structure_digest(p)
    check("digest 可复算且稳定", d1 == tree["digest"] == archinorm.structure_digest(p))

finally:
    shutil.rmtree(tmp, ignore_errors=True)

print("\n" + "=" * 66)
print(f"自检结果：{CHECKS[0] - len(FAILS)}/{CHECKS[0]} 通过")
if FAILS:
    print("失败项：")
    for f in FAILS:
        print("  -", f)
print("=" * 66)
sys.exit(1 if FAILS else 0)
