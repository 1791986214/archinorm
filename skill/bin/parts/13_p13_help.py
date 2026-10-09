
# --------------------------------------------------------------------------
# 分主题速查
# --------------------------------------------------------------------------

HELP_TOPICS = {
"fields": """模块 frontmatter 字段
必填 9 个：uid / id / parent / name / description / source / revision / updated_at / fingerprint
- uid         8 位小写 hex，全项目唯一，分配后永不变（重命名/移动都保留）
- id          路径式 `[a-z0-9][a-z0-9-]*` 段以 . 连接；首段 = 树名；全项目唯一
- parent      必须等于 id 去掉最后一段；根模块为 null（唯一存储的结构引用）
- name        {zh, en}，各 <= 60 字符
- description {zh, en}，各 <= 500 字符，刻意精炼（人和 AI 都读它）
- source      数组 {path, line?, end_line?}：repo 相对路径、正斜杠、无 ..
- revision    生成时仓库的 40 位 git SHA（无 git 写 40 个 0 并告警）
- updated_at  ISO 8601，如 2026-08-30T12:00:00Z
- fingerprint source 的确定性指纹：按 path 升序，逐个
              update(UTF-8(path)) + update(0x00) + update(文件字节)，
              再取 SHA-256 前 32 位 hex。用 fingerprint 命令算，不要手估

可选字段
- state        active(默认) | planned(计划态) | deprecated(废弃)
               计划态必须 fingerprint: pending
               deprecated 可带 replacement 指向替代模块
- repository   仅根模块，该树对应仓库的 http(s) URL
- tags         自由标签（<= 12 个）
- apis         仅叶子。{protocol, method?, path, description{zh,en}}
               protocol 属于 http|ws|rpc|amqp|kafka|mysql|redis|file|grpc|graphql
               http 必须有大写 method，非 http 禁止 method
- deps         出向依赖箭头（只存源端）
               {kind, to, from_api?, to_api?, label?{zh,en}}
               kind 属于 call|event|dataflow|reference；to 可跨树
               from_api 只能是本模块 API 键；to_api 只能是目标模块自身 API 键

文件形态：有子模块的 = 容器，落 <段>/index.md；没有子模块的 = 叶子，落 <段>.md。
工具自动升降级文件形态，不用手工挪文件。""",

"deps": """箭头与 API 直连
- 只写 parent 与出向 deps；children 字段不存在（由父指针派生）。
- 跨树箭头就是普通 deps：to 指向另一棵树的模块 id，零新语法。
- API 直连：两端都声明了 API 时补 from_api / to_api，箭头才会钉在具体 API 行上；
  不补则只能落在框边，validate 会给出聚合警告 dep/unanchored。
- kind 语义：call=同步调用、event=发布/订阅、dataflow=数据管道、reference=一般引用。
  不确定就 reference 或干脆不写。
- 悬空边（dep/target-missing）是 error，删模块后必须按返回的 dangling_edges 修完。""",

"renders": """渲染数据集（renders/）
结构数据描述"是什么"，渲染数据描述"这一层怎么画"。
每个容器模块（有子模块的模块）都应在同一轮建立渲染数据；叶子不需要。
路径：renders/<id 的点号换斜杠>.json，与容器模块一一对应。

字段（✅ = 渲染器已消费；⚠️ = schema 接受但当前不影响渲染）
- order       ✅ 直接子模块的阅读顺序（生产者到消费者；未列出的按原树序追加在后）
- reading     ✅ {zh,en} 一句话阅读导语，显示在画布上方
- groups      ✅ [{id,title:{zh,en},children:[...]}]，需同时把 mode 设为 groups，
                 才会给每组画一个带标题的虚线框
- edge_hints  ✅ [{from,to,kind?,lane?,style?}] 给指定的一条边定车道或线型
                 lane 2..4 → 纵向偏移 0/12/24px；style 传 SVG dasharray 串或 "solid"
                 （bundle / priority 字段 schema 保留，暂未实现）
- mode        ⚠️ 当前只在 =groups 时决定"要不要画分组框"。auto / layers / grid
                 不改变布局 —— 实际排列完全由 order 驱动，始终是单列整洁树
- max_columns ⚠️ 暂未实现：grid 换行与列数控制尚未落地

可读性配方
1. 顺序 = 数据流：order 按"谁先产生、谁后消费"排
2. 分组 = 领域边界：同一子系统/层/角色的子模块放一组；每组 2-5 个为宜（配 mode: groups）
3. 导语 = 阅读路径：reading 一句话说明"从哪看起、箭头代表什么"
4. 长边提示：回指/跨整张图的边写 edge_hints，lane 2..4 拉开轨道
5. 不要硬凑分组：一组平级功能就别写 groups""",

"flow": """伴随开发流程（先建树、再逐个模块完成）
铁律：架构树伴随工程生长，任何"先写代码后补树"都会造成结构漂移。

一、任务开始（设计）
1. init             新项目/空目录：建 archinorm-<slug>/ 并写入默认架构规则
2. change-open      开变更（title / intent / modules{create,modify,delete} / acceptance）
                    acceptance 只接受纯字符串数组；需要双语请写 title/intent
3. brief            拿开发指引：契约、影响面、架构规则、验收清单
4. check            把拟建模块与拟加依赖先预检（parent 推导、深度、环、policy 违规）
5. upsert           建计划态模块：state=planned、fingerprint=pending、source 可指向未落地文件
                    容器同轮用 layout-upsert 写该层渲染数据

二、逐个模块实现（编码）
- 每完成一个叶子就把 state 改 active（源码未落地会报 refresh/activate-not-landed）
- 改字段用 patch（--expect-updated-at 并发保护、--dry-run 先看 diff）
- 改名/挪层用 move（保 uid、级联子模块、重写全项目 deps.to，先 --dry-run）
- 子级变化后同轮更新该层渲染数据，否则 layout/missing 会提醒
- 每次结构性改动后可跑 sync，拿到脏子树、新增文件、失效 source、planned 进度

三、任务收尾（交付）
1. change-close --activate --render：刷新指纹、激活 planned、validate 0 error 强制
2. 汇报：变更 id、涉及模块、validate/build 结果、渲染路径""",

"errors": """常见诊断码 -> 修复对照
structure/parent-mismatch     parent 不等于 id 去尾段 -> 按 evidence.derived 改 parent
structure/parent-not-exist    孤儿（父不存在）-> 创建父模块或改 parent
structure/file-id-mismatch    文件路径与 id 不一致 -> 用 upsert 重写该模块
structure/root-missing        没有 parent: null 的根模块
structure/uid-format          uid 不是 8 位小写 hex
structure/bilingual-missing   name/description 的 zh 或 en 为空
structure/leaf-too-coarse     WARN 叶子覆盖 >=3 文件 / 行跨度 >=300 / API >=6 -> promote 后拆
structure/shallow-hierarchy   WARN 模块数多但层级过浅 -> 继续下钻补中间层
api/leaf-missing              叶子缺 apis -> 补 apis
api/non-leaf                  容器/根写了 apis -> 下放到叶子并删除本字段
api/leaf-empty                WARN 叶子 apis 为空数组
api/key-duplicate             API 键全局重复 -> 只保留一个定义，其余改 path/method
api/protocol-invalid          protocol 不在白名单
api/method-invalid            http 缺大写 method / 非 http 带了 method
dep/target-missing            悬空箭头 -> 建目标模块或改/删箭头
dep/from-api-invalid          from_api 不是本模块 API -> 用本模块 apis 的键
dep/to-api-invalid            to_api 不是目标模块自身 API 键
dep/kind-invalid              kind 不在白名单
dep/self                      依赖指向自身
dep/unanchored                WARN 两端有 API 但未补 from_api/to_api
deprecation/inbound           依赖指向已废弃模块 -> 迁移到 replacement 或删除
evidence/fingerprint-drift    WARN 数据过期 -> 跑 sync 计划增量重建
evidence/source-invalid       source path 含 .. / 反斜杠 / 绝对路径
state-invalid                 state 非法
state/planned-fingerprint     计划态 fingerprint 必须是 pending
structure/planned-source-missing  WARN 计划态 source 尚未落地
layout/missing                WARN 容器缺渲染数据 -> layout-upsert 补
layout/order-child            order 引用了非直接子级
layout/group-child            groups 引用了非直接子级
layout/hint-edge-missing      WARN edge_hint 指向的兄弟边不存在
layout/orphan                 渲染数据没有对应容器
layout/not-container          叶子模块不应有渲染数据
change/module-missing         变更引用的模块不存在 -> 先建模块（可 planned）
change/create-not-landed      close 时 create 清单仍有 planned
refresh/activate-not-landed   请求激活但源码未落地
policy/<rule-id>              架构规则违规 -> 改设计；规则确需调整用 policy-upsert
concurrency/updated-at-mismatch  patch 的 expect_updated_at 与当前值不符
args/invalid-patch            patch 缺字段 / 空对象 / 非对象 -> 传非空对象""",
}


def cmd_help(a) -> Result:
    r = Result("help")
    topic = a.topic or "all"
    if topic.startswith("tool:"):
        name = topic.split(":", 1)[1]
        entry = COMMAND_REF.get(name)
        if not entry:
            return r.err("args/unknown-tool", f"未知命令 `{name}`",
                         known=sorted(COMMAND_REF))
        r.data = {"topic": topic, "tool": name, "help": entry}
        return r
    if topic == "all":
        r.data = {"topics": sorted(HELP_TOPICS),
                  "commands": {k: v["summary"] for k, v in COMMAND_REF.items()}}
        return r
    if topic == "tools":
        r.data = {"count": len(COMMAND_REF), "tools": COMMAND_REF}
        return r
    if topic not in HELP_TOPICS:
        return r.err("args/unknown-topic", f"未知主题 `{topic}`",
                     known=sorted(HELP_TOPICS) + ["tools", "all", "tool:<命令名>"])
    r.data = {"topic": topic, "text": HELP_TOPICS[topic]}
    return r
