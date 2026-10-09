---
name: archinorm
description: 项目框架·归一化框架图构建器。把项目架构写成归一化的分形模块树，并渲染成深色交互式架构图（节点链路图 + 依赖曲线 + 语义着色 + 下钻面板）。触发词：架构图、框架图、结构图、模块树、项目结构、画架构、代码地图、archinorm、归一化、迁移项目、给项目建结构。凡涉及代码的项目在设计或开发阶段应默认套用本框架。
agent_created: true
---

# 项目框架·归一化框架图构建器（archinorm）

把代码仓库的架构写成"人机共读"的**分形模块树**：每个模块结构完全相同，点开即子层，
叶子承载 API；配套 写时校验 / 全量校验 / 冻结回执 / **单文件交互式框架图**。

视觉语言（深色证据控制台、全等宽字体、七个语义色、扁平克制）吸收自
[archify](https://github.com/tt-a1i/archify)（MIT）的 DESIGN.md。
结构语义与规范移植自 [yan-mc/dsh-normify](https://github.com/yan-mc/dsh-normify)（MIT），
原为 DSH 插件（31 个 `archinorm_*` 工具），本包收敛成 30 个 CLI 命令，**零第三方依赖**。

## 0. 铁律（MUST）

1. **只读业务代码**：绝不修改任何源码。结构数据只写入 `archinorm-<slug>/` 目录。
2. **不裸写文件**：模块一律经 `upsert` 写入（工具内置校验与文件形态自动升降级）。
3. **零容忍收尾**：任何阶段以 `validate` 的 **0 error** 为交付标准；warning 记录但不阻断。
4. **单方向引用**：只写 `parent` 与出向 `deps`；`children` 字段不存在（由父指针派生）。
5. **API 只在叶子存一次**：非叶子（含根）禁止 `apis`；聚合由编译器派生。
6. **未接箭头的 API 完全合法**：不得因"看起来孤立"删除。
7. **双语必填**：`name` / `description` 的 zh 与 en 均非空。
8. **计划优先**：先建计划态树（`state=planned`）再逐个模块落地，禁止"先写代码、后补结构"。
9. **规则先行**：架构规则（`policy.yml`）在设计阶段定好并强制；违规先改设计，不能绕过。
10. **收尾即闭环**：每个开发任务用 `change-close` 收尾，0 error 强制，并记录 revision。
11. **交付必须标注**：交付说明里明确写"本项目已采用 archinorm 框架"并附架构图路径。

## 1. 怎么调用

引擎装在技能目录里，用启动器调用（自选 Python 解释器，含 PyYAML）：

```sh
SKILL=/Users/lang/.workbuddy/skills/archinorm
"$SKILL/bin/run.sh" <命令> [参数...]
```

输出统一是 JSON 信封：`{"ok", "command", "data", "errors", "warnings"}`
（加 `--human` 出人读文本）。退出码：`0` 无 error，`1` 有 error，`2` 用法错。

**回答"命令怎么用"永远不要猜**：

```sh
"$SKILL/bin/run.sh" help all              # 全部命令 + 主题
"$SKILL/bin/run.sh" help tools            # 30 个命令的必填/可选参数树
"$SKILL/bin/run.sh" help tool:migrate     # 单个命令的完整参数树
"$SKILL/bin/run.sh" help fields|deps|renders|flow|errors|migrate
```

## 2. 什么时候用

- 用户说：画架构图 / 项目结构 / 模块树 / 代码地图 / 这项目怎么组织的
- 新项目立项或大改架构前，需要先把结构定下来（计划态建树）
- 接手陌生代码库，需要快速理解结构（`migrate` 一步生成）
- 代码改了，结构数据要跟着同步（`sync` → 增量重建）
- **默认启用**：任何涉及代码的新项目，在设计与开发阶段默认套用本框架

## 3. 三条主流程

### 3.1 迁移已有项目（最快上手）

```sh
"$SKILL/bin/run.sh" inventory --repo /path/to/proj           # 先只读清点，看会生成什么
"$SKILL/bin/run.sh" migrate --repo /path/to/proj --dir <输出目录> --render
"$SKILL/bin/run.sh" migrate-all --root /path/to/projects --dir <输出目录> --render
```

**语义**：迁移 = 给项目生成一份 `archinorm-<slug>/` 结构数据 + 架构图，**不改一行业务代码**。
这是文档/可视化层，不是运行时依赖。

自动生成的模块是**骨架**：按目录切模块、`source` 填该目录下的代码文件、
`description` 一律写 `【待审】` 占位。**必须人工补全 description 与叶子 apis 后才算完成**。
叶子 `apis: []` 会出 `api/leaf-empty` 警告，属正常起步状态。

### 3.2 伴随开发（新建 / 重构，推荐）

设计 → 计划态建树 → 逐个模块实现 → 关闭变更：

```sh
R() { "$SKILL/bin/run.sh" "$@"; }

# 0) 新项目初始化（建结构目录 + 默认架构规则）
R init --dir ./archinorm-myproj --slug myproj --root-id myproj --title "我的项目"

# 1) 开变更（acceptance 只接受纯字符串数组！需要双语请写 title/intent）
R change-open --dir ./archinorm-myproj --title "实现支付模块" \
  --intent "对接渠道、回调、状态机" \
  --modules '{"create":["shop.order.payment"],"modify":[],"delete":[]}' \
  --acceptance '["validate 0 error","渲染图可下钻到支付模块"]'

# 2) 拿开发指引（契约、影响面、规则、验收清单）
R brief --dir ./archinorm-myproj --id shop.order.payment

# 3) 设计前预检：拟建模块 + 拟加依赖先跑同一套规则
R check --dir ./archinorm-myproj --modules '[{"id":"shop.new","name":{"zh":"新","en":"New"}}]'

# 4) 建计划态模块（state=planned、fingerprint=pending、source 可指向未落地文件）
R upsert --dir ./archinorm-myproj --module '{"id":"shop.order.payment","state":"planned",
  "name":{"zh":"支付","en":"Payment"},"description":{"zh":"...","en":"..."},
  "source":[{"path":"src/order/payment.ts"}]}'
R layout-upsert --dir ./archinorm-myproj --id shop.order --data '{"order":["shop.order.payment"]}'

# 5) 逐个模块实现完后转 active
R patch --dir ./archinorm-myproj --id shop.order.payment \
  --fields '{"state":"active"}' --repo /path/to/repo

# 6) 收尾（刷新指纹 / 激活 planned / 0 error 强制 / 编译渲染）
R change-close --dir ./archinorm-myproj --id chg-20261005-01 --activate --render --repo /path/to/repo
```

### 3.3 代码变更后同步

```sh
R sync --dir ./archinorm-myproj --repo /path/to/repo    # 只读：脏子树 / 新增文件 / 失效 source / planned 进度
# 深到浅重建 affected，逐个 upsert / patch / promote，再：
R validate --dir ./archinorm-myproj --repo /path/to/repo
R build --dir ./archinorm-myproj --repo /path/to/repo --render
```

## 4. 数据结构要点

结构数据目录 `archinorm-<slug>/`：

```
archinorm-myproj/
├── modules/                     # 模块树源数据（一模块一 Markdown）
│   ├── myproj/index.md          # 根（id: myproj，parent: null）
│   ├── myproj/auth.md           # 叶子（id: myproj.auth）
│   └── myproj/order/checkout/index.md   # 容器
├── renders/<id 点号换斜杠>.json  # 渲染数据（每个容器一份）
├── changes/<变更 id>.json        # 变更日志，随结构回档
├── policy.yml                   # 架构规则
└── outline.md / tree.json / api-index.json / receipt.json   # 编译器派生产物
```

完整字段与规则见 `references/SPEC.md`，或跑 `help fields` / `help deps` / `help renders`。

**必填 9 个字段**：`uid` `id` `parent` `name` `description` `source` `revision` `updated_at` `fingerprint`
**关键约束**：
- `parent` 必须等于 `id` 去掉最后一段；根模块为 `null`
- 容器模块文件 = `<最后一段>/index.md`，叶子 = `<最后一段>.md`（工具自动升降级）
- 叶子必须有 `apis`（可为空数组）；容器禁止 `apis`
- `deps` 只存出向；跨树箭头就是普通 deps
- 两端都声明了 API 时补 `from_api`/`to_api`，箭头才能钉到 API 行
- `fingerprint` 一律用 `fingerprint` 命令算，不要手估

## 5. 渲染数据（人读性的另一半）

每个**容器模块**都要有一份 `renders/<id>.json`，否则 `layout/missing` 会提醒。字段：
`mode`(auto/groups/layers/grid) · `max_columns`(1-6) · `order` · `groups` · `reading` · `edge_hints`

可读性配方（照做）：
1. **顺序 = 数据流**：`order` 按"谁先产生、谁后消费"排；管道链用 `mode: layers`
2. **分组 = 领域边界**：同一子系统的子模块放一组；每组 2-5 个为宜
3. **导语 = 阅读路径**：`reading` 一句话说明"从哪看起、箭头代表什么"
4. **长边提示**：回指/跨图的边写 `edge_hints`，`lane` 2..4 拉开轨道
5. **不要硬凑分组**：一组平级功能就直接 `grid`

## 6. 命令速查（30 个）

| 分组 | 命令 |
|---|---|
| 迁移 | `inventory` `migrate` `migrate-all` |
| 项目/模块 | `init` `upsert` `patch` `get` `list` `delete` `move` `promote` |
| 校验编译 | `validate` `build` `render` `fingerprint` |
| 检索 | `search` `deps` `brief` `sync` |
| 渲染数据 | `layout-get` `layout-upsert` `layout-delete` |
| 变更 | `change-open` `change-update` `change-list` `change-close` |
| 规则 | `policy-get` `policy-upsert` `check` |
| 帮助 | `help` |

不确定参数就跑 `help tool:<命令名>`，别猜。

## 7. 常见诊断码 → 修法

`help errors` 有完整对照表。高频的几条：

| 诊断码 | 含义 | 修法 |
|---|---|---|
| `structure/parent-mismatch` | parent ≠ id 去尾段 | 按 evidence.derived 改 parent |
| `structure/file-id-mismatch` | 文件路径与 id 不一致 | 用 upsert 重写该模块 |
| `api/leaf-missing` | 叶子缺 apis | 补 apis（可为 `[]`） |
| `api/non-leaf` | 容器写了 apis | 下放到叶子并删掉本字段 |
| `api/key-duplicate` | API 键全局重复 | 只留一个定义，其余改 path/method |
| `dep/target-missing` | 悬空箭头 | 建目标模块或改/删箭头 |
| `layout/order-child` | order 引用了非直接子级 | 改成直接子模块 id |
| `layout/missing` | 容器缺渲染数据 | `layout-upsert` 补 order/groups/mode |
| `policy/<rule>` | 架构规则违规 | 改设计；规则确需调整用 `policy-upsert` |
| `change/create-not-landed` | close 时 create 仍有 planned | 先实现并激活再 close |

## 8. 自检（改完引擎必跑）

```sh
/Users/lang/.workbuddy/binaries/python/envs/default/bin/python \
  /Users/lang/.workbuddy/skills/archinorm/tests/selftest.py
# 期望：73/73 通过
# 顺带验零依赖路径： ARCHINORM_NO_PYYAML=1 再跑一次，同样应 73/73
```

引擎源码在 `bin/parts/NN_*.py`，改完必须跑 `bin/build.py` 重新合并成 `bin/archinorm.py`
（它会顺带做语法检查、单例守卫与 CLI 装配冒烟）。

**零依赖**：有 PyYAML 就用 PyYAML，没有就自动切内置迷你解析器（已等价性验证）。

## 8.1 技能自我更新（skillup）

技能自带的 `bin/skillup.py` 可盯着 GitHub 源仓库自动更新：比对版本 → 备份 → 替换 →
跑自检 → 失败自动回滚。**绝不删除任何东西**，旧版一律改名成 `<名>.bak-<版本>-<时间戳>`。

```sh
"$SKILL/bin/run.sh" 内置命令之外，更新器单独调：
python "$SKILL/bin/skillup.py" status            # 当前版本 / 源仓库 / 上次检查 / 备份
python "$SKILL/bin/skillup.py" check --force     # 强制联网查新版
python "$SKILL/bin/skillup.py" update --dry-run  # 演一遍不落盘
python "$SKILL/bin/skillup.py" update            # 备份+替换+自检，失败自动回滚
python "$SKILL/bin/skillup.py" rollback          # 回滚到最近备份
```

- `bin/run.sh` / `bin/run.bat` 启动时**每天最多一次**静默检查（24 小时节流）；
  未配置更新源时立即返回、不联网，不影响任何调用。
- 本包 `manifest.json` 的 `source.repo` 默认是 `null`（本包暂无自己的发布仓库）。
  要启用自动更新，把它填成你的发布仓库；**archify 的现成写法见 `examples/manifest.archify.json`**。
- **注意**：乐享知识库只是文件仓库，不会替你跟踪版本；更新只能回到 GitHub 源仓库。
  完整说明见 `examples/README-AUTO-UPDATE.md`。

## 9. 交付标注规范（硬性）

任何采用了本框架的交付，说明里必须包含：

```
架构框架：archinorm（归一化分形模块树）
结构数据：<项目路径>/archinorm-<slug>/
架构图　：<项目路径>/archinorm-<slug>/architecture.html
校验状态：validate 0 error（warning N 条）
配置状态：description/apis 已人工补全  ← 或 → 仍为【待审】占位
```
