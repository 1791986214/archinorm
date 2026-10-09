
# --------------------------------------------------------------------------
# 命令参考表 + CLI
# --------------------------------------------------------------------------

COMMAND_REF = {
    "init": {"summary": "建项目目录 + 默认架构规则",
             "required": {"--dir 或 --project": "项目定位"},
             "optional": {"--slug": "项目 slug", "--repo": "源码仓库根",
                          "--repo-url": "仓库 URL（仅根模块）",
                          "--root-id": "同时建计划态根模块",
                          "--title / --title-en": "根模块双语名"}},
    "upsert": {"summary": "写模块（批量、幂等、写时自动校验）",
               "required": {"--module <json|->  或  --module-file <path>": "模块数据"},
               "optional": {"--repo": "用于算 fingerprint / revision"}},
    "patch": {"summary": "部分更新模块（只传变更字段）",
              "required": {"--id": "模块 id", "--fields <json>": "要改的字段"},
              "optional": {"--expect-updated-at": "并发保护",
                           "--dry-run": "只出 diff 不落盘", "--repo": ""}},
    "get": {"summary": "读单个模块", "required": {"--id": ""}, "optional": {}},
    "list": {"summary": "列模块 / 树",
             "required": {},
             "optional": {"--parent": "按父过滤", "--tree": "按树过滤",
                          "--leaves": "只要叶子", "--max-depth": "深度上限"}},
    "delete": {"summary": "删模块及子树（返回悬空边预警）",
               "required": {"--id": ""},
               "optional": {"--cascade": "连子模块一起删"}},
    "move": {"summary": "重命名/移动子树（保 uid、级联、重写 deps）",
             "required": {"--from": "源 id", "--to": "目标 id"},
             "optional": {"--dry-run": "", "--repo": ""}},
    "promote": {"summary": "叶子晋升为容器（便于继续下钻）",
                "required": {"--id": ""}, "optional": {}},
    "fingerprint": {"summary": "按引擎算法算 source 指纹",
                    "required": {"--repo": "仓库根"},
                    "optional": {"--path": "可重复，仓库相对路径",
                                 "--source": "JSON 数组"}},
    "validate": {"summary": "全项目校验（0 error 门禁，含 policy）",
                 "required": {}, "optional": {"--repo": "开启指纹漂移检查"}},
    "build": {"summary": "编译 + 冻结回执（tree.json / outline / api-index / receipt）",
              "required": {},
              "optional": {"--repo": "", "--render": "同时出 HTML", "--out": "HTML 路径"}},
    "render": {"summary": "tree.json -> 单文件交互式下钻 HTML",
               "required": {}, "optional": {"--out": "输出路径"}},
    "search": {"summary": "检索模块 / API",
               "required": {"--q": "关键词"},
               "optional": {"--limit": "默认 20"}},
    "deps": {"summary": "看某模块的出向依赖与反查",
             "required": {"--id": ""}, "optional": {}},
    "layout-get": {"summary": "读某容器的渲染数据",
                   "required": {"--id": ""}, "optional": {}},
    "layout-upsert": {"summary": "写/覆盖某容器的渲染数据（写时校验）",
                      "required": {"--id": "", "--data <json>": ""}, "optional": {}},
    "layout-delete": {"summary": "删渲染数据（回退自动布局）",
                      "required": {"--id": ""}, "optional": {}},
    "change-open": {"summary": "开一次开发变更",
                    "required": {"--title": "纯字符串或 {zh,en}"},
                    "optional": {"--intent": "", "--modules <json>":
                                 "{create,modify,delete}", "--acceptance <json>":
                                 "纯字符串数组", "--repo": ""}},
    "change-update": {"summary": "更新变更",
                      "required": {"--id": ""}, "optional": {"--json <json>": ""}},
    "change-list": {"summary": "列变更",
                    "required": {}, "optional": {"--status": "open|verified"}},
    "change-close": {"summary": "收尾变更（刷新指纹 / 激活 planned / 0 error 强制 / 编译）",
                     "required": {"--id": ""},
                     "optional": {"--activate": "", "--render": "", "--repo": "",
                                  "--force": ""}},
    "policy-get": {"summary": "读架构规则", "required": {}, "optional": {}},
    "policy-upsert": {"summary": "安装/覆盖架构规则",
                      "required": {"--data <json>": "含 rules"},
                      "optional": {}},
    "check": {"summary": "设计前预检：拟建模块 + 拟加依赖跑同一套规则",
              "required": {},
              "optional": {"--modules <json>": "拟建模块数组",
                           "--deps <json>": "拟加依赖数组"}},
    "brief": {"summary": "开发指引：契约、影响面、规则、验收清单",
              "required": {"--id": ""}, "optional": {}},
    "sync": {"summary": "增量再生成计划器（只读）",
             "required": {"--repo": ""},
             "optional": {"--range": "git diff 范围，默认 HEAD"}},
    "help": {"summary": "分主题速查",
             "required": {},
             "optional": {"topic": "fields|deps|renders|flow|errors|tools|all|"
                                  "tool:<命令名>"}},
}


def add_proj_args(p):
    p.add_argument("--dir", help="项目目录绝对路径（archinorm-<slug>/）")
    p.add_argument("--project", help="项目 slug（找 archinorm-<slug>）")


def build_parser():
    ap = argparse.ArgumentParser(
        prog="archinorm", description="归一化分形模块树构建器（WorkBuddy 版）")
    ap.add_argument("--human", action="store_true", help="人类可读输出（默认 JSON）")
    sub = ap.add_subparsers(dest="cmd", required=True)

    p = sub.add_parser("init", help="建项目目录 + 默认架构规则")
    add_proj_args(p)
    p.add_argument("--slug"); p.add_argument("--repo")
    p.add_argument("--repo-url"); p.add_argument("--root-id")
    p.add_argument("--title"); p.add_argument("--title-en")
    p.set_defaults(fn=cmd_init)

    p = sub.add_parser("upsert", help="写模块")
    add_proj_args(p); p.add_argument("--repo")
    p.add_argument("--module", help="模块 JSON，或 - 表示读 stdin")
    p.add_argument("--module-file")
    p.set_defaults(fn=cmd_upsert)

    p = sub.add_parser("patch", help="部分更新模块")
    add_proj_args(p); p.add_argument("--repo")
    p.add_argument("--id", required=True); p.add_argument("--fields")
    p.add_argument("--expect-updated-at"); p.add_argument("--dry-run", action="store_true")
    p.set_defaults(fn=cmd_patch)

    p = sub.add_parser("get", help="读单个模块")
    add_proj_args(p); p.add_argument("--id", required=True)
    p.set_defaults(fn=cmd_get)

    p = sub.add_parser("list", help="列模块 / 树")
    add_proj_args(p)
    p.add_argument("--parent"); p.add_argument("--tree")
    p.add_argument("--leaves", action="store_true"); p.add_argument("--max-depth", type=int)
    p.set_defaults(fn=cmd_list)

    p = sub.add_parser("delete", help="删模块及子树")
    add_proj_args(p); p.add_argument("--id", required=True)
    p.add_argument("--cascade", action="store_true")
    p.set_defaults(fn=cmd_delete)

    p = sub.add_parser("move", help="重命名/移动子树")
    add_proj_args(p); p.add_argument("--repo")
    p.add_argument("--from", dest="src", required=True)
    p.add_argument("--to", dest="dst", required=True)
    p.add_argument("--dry-run", action="store_true")
    p.set_defaults(fn=cmd_move)

    p = sub.add_parser("promote", help="叶子晋升为容器")
    add_proj_args(p); p.add_argument("--id", required=True)
    p.set_defaults(fn=cmd_promote)

    p = sub.add_parser("fingerprint", help="算 source 指纹")
    p.add_argument("--repo", required=True)
    p.add_argument("--path", action="append"); p.add_argument("--source")
    p.set_defaults(fn=cmd_fingerprint)

    p = sub.add_parser("validate", help="全项目校验")
    add_proj_args(p); p.add_argument("--repo")
    p.set_defaults(fn=cmd_validate)

    p = sub.add_parser("build", help="编译 + 冻结回执")
    add_proj_args(p); p.add_argument("--repo")
    p.add_argument("--render", action="store_true"); p.add_argument("--out")
    p.set_defaults(fn=cmd_build)

    p = sub.add_parser("render", help="出单文件交互 HTML")
    add_proj_args(p); p.add_argument("--out")
    p.set_defaults(fn=cmd_render)

    p = sub.add_parser("search", help="检索模块 / API")
    add_proj_args(p); p.add_argument("--q", required=True)
    p.add_argument("--limit", type=int, default=20)
    p.set_defaults(fn=cmd_search)

    p = sub.add_parser("deps", help="看依赖与反查")
    add_proj_args(p); p.add_argument("--id", required=True)
    p.set_defaults(fn=cmd_deps)

    p = sub.add_parser("layout-get", help="读渲染数据")
    add_proj_args(p); p.add_argument("--id", required=True)
    p.set_defaults(fn=cmd_layout_get)

    p = sub.add_parser("layout-upsert", help="写渲染数据")
    add_proj_args(p); p.add_argument("--id", required=True); p.add_argument("--data")
    p.set_defaults(fn=cmd_layout_upsert)

    p = sub.add_parser("layout-delete", help="删渲染数据")
    add_proj_args(p); p.add_argument("--id", required=True)
    p.set_defaults(fn=cmd_layout_delete)

    p = sub.add_parser("change-open", help="开变更")
    add_proj_args(p); p.add_argument("--repo")
    p.add_argument("--title"); p.add_argument("--intent")
    p.add_argument("--modules"); p.add_argument("--acceptance")
    p.set_defaults(fn=cmd_change_open)

    p = sub.add_parser("change-update", help="更新变更")
    add_proj_args(p); p.add_argument("--id", required=True); p.add_argument("--json")
    p.set_defaults(fn=cmd_change_update)

    p = sub.add_parser("change-list", help="列变更")
    add_proj_args(p); p.add_argument("--status")
    p.set_defaults(fn=cmd_change_list)

    p = sub.add_parser("change-close", help="收尾变更")
    add_proj_args(p); p.add_argument("--id", required=True); p.add_argument("--repo")
    p.add_argument("--activate", action="store_true"); p.add_argument("--render", action="store_true")
    p.add_argument("--force", action="store_true")
    p.set_defaults(fn=cmd_change_close)

    p = sub.add_parser("policy-get", help="读架构规则")
    add_proj_args(p); p.set_defaults(fn=cmd_policy_get)

    p = sub.add_parser("policy-upsert", help="写架构规则")
    add_proj_args(p); p.add_argument("--data")
    p.set_defaults(fn=cmd_policy_upsert)

    p = sub.add_parser("check", help="设计前预检")
    add_proj_args(p); p.add_argument("--modules"); p.add_argument("--deps")
    p.set_defaults(fn=cmd_check)

    p = sub.add_parser("brief", help="开发指引")
    add_proj_args(p); p.add_argument("--id", required=True)
    p.set_defaults(fn=cmd_brief)

    p = sub.add_parser("sync", help="增量再生成计划器")
    add_proj_args(p); p.add_argument("--repo"); p.add_argument("--range")
    p.set_defaults(fn=cmd_sync)

    p = sub.add_parser("help", help="分主题速查")
    p.add_argument("topic", nargs="?")
    p.set_defaults(fn=cmd_help)

    register_migrate_subparsers(sub)
    return ap


def main(argv=None) -> int:
    argv = list(sys.argv[1:] if argv is None else argv)
    human = "--human" in argv
    argv = [x for x in argv if x != "--human"]
    ap = build_parser()
    a = ap.parse_args(argv)
    a.human = human or getattr(a, "human", False)
    try:
        res = a.fn(a)
    except SystemExit:
        raise
    except Exception as exc:  # pragma: no cover
        r = Result(getattr(a, "cmd", "cli"))
        r.err("internal/error", f"{type(exc).__name__}: {exc}")
        return r.emit(human=a.human)
    return res.emit(human=a.human)
