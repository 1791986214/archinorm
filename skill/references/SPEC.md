# Archinorm 规范（WorkBuddy 移植版）

本源：[yan-mc/dsh-normify](https://github.com/yan-mc/dsh-normify)（MIT）。原为 DSH（DeepSeek Harness）
插件，31 个 `archinorm_*` 工具由 `lib/index.js` 在运行时注册。本移植版把工具收敛成 30 个 CLI 命令，
去掉 DSH / cordis 依赖，只留 Python ≥ 3.9 + PyYAML。

引擎：`bin/archinorm.py`（由 `bin/parts/NN_*.py` 经 `bin/build.py` 合并生成，改源码后必须重新 build）
自检：`tests/selftest.py`（73 项断言，期望全绿）

---

## 1. 数据模型

整个数据库 = 无数个**结构完全相同**的模块。每个模块 = 一个 Markdown 文件
（frontmatter 机器读，正文人读可选）。**分形**：点开任一模块即其子层。

### 必填 9 字段

| 字段 | 规则 |
|---|---|
| `uid` | 8 位小写 hex；全项目唯一；**分配后永不变**（重命名/移动都保留） |
| `id` | 路径式 `[a-z0-9][a-z0-9-]*` 段以 `.` 连接；首段 = 树名；全项目唯一；深度不设上限 |
| `parent` | **必须等于 `id` 去掉最后一段**；根（单段 id）为 `null`。唯一存储的结构引用 |
| `name` | `{zh, en}`，各 ≤ 60 字符 |
| `description` | `{zh, en}`，各 ≤ 500 字符，刻意精炼（人和 AI 都读它） |
| `source` | 数组 `{path, line?, end_line?}`；仓库相对路径、正斜杠、无 `..`；根模块允许 `[]` |
| `revision` | 生成时仓库的 40 位 git SHA；非 git 仓库记 40 个 `0` 并告警 |
| `updated_at` | ISO 8601，如 `2026-08-30T12:00:00Z` |
| `fingerprint` | `source` 的确定性指纹（见 §4）。**用 `fingerprint` 命令算，不要手估** |

### 可选字段

- `state`：`active`（默认）| `planned`（计划态）| `deprecated`（废弃，可带 `replacement`）
  - 计划态**必须** `fingerprint: pending`；实现后用 `change-close --activate` 转 active
- `repository`：仅根模块，该树对应仓库的 http(s) URL
- `tags`：自由标签（≤ 12 个）
- `apis`：**仅叶子**。条目 `{protocol, method?, path, description{zh,en}}`
  - `protocol ∈ http|ws|rpc|amqp|kafka|mysql|redis|file|grpc|graphql`
  - http **必须**有大写 `method`；非 http **禁止**带 `method`
  - 键全局唯一：http → `METHOD path`；非 http → `protocol:path`
- `deps`：**出向**依赖箭头（只存源端）。条目 `{kind, to, from_api?, to_api?, label?{zh,en}}`
  - `kind ∈ call|event|dataflow|reference`（call=同步调用、event=发布订阅、dataflow=数据管道、reference=一般引用）
  - `to` 为目标模块 id，**可跨树**（跨树箭头就是普通 deps，零新语法）
  - `from_api` 只能是**本模块** API 键；`to_api` 只能是**目标模块自身** API 键

### 容器 vs 叶子

- **容器** = 有子模块的模块 → 文件落在 `<最后一段>/index.md`
- **叶子** = 没有子模块的模块 → 文件落在 `<最后一段>.md`
- 文件形态由工具自动升降级；叶子必须有 `apis`（可为空数组），容器禁止 `apis`
- `children` 字段**不存在**，由父指针派生

---

## 2. 目录布局

```
archinorm-<slug>/
├── modules/                      # 结构数据（一模块一 Markdown）
│   ├── <slug>/index.md           # 根（parent: null）
│   ├── <slug>/auth.md            # 叶子
│   └── <slug>/order/checkout/payment.md
├── renders/<id 点号换斜杠>.json   # 渲染数据（每个容器一份）
├── changes/<变更 id>.json         # 变更日志，随结构回档
├── policy.yml                    # 架构规则
├── outline.md                    # 派生：人读大纲
├── tree.json                     # 派生：渲染器输入
├── api-index.json                # 派生：API 键 → 所属模块
└── receipt.json                  # 派生：冻结回执（含 digest）
```

**只读原则**：绝不修改 `modules/` `renders/` `changes/` `policy.yml` 之外的任何文件；
业务源码**零改动**。

---

## 3. YAML 子集（手写 frontmatter 时必须遵守）

- 只用：普通标量、`{zh, en}` 内联映射、数组、`>-` 折叠块
- **禁止**：锚点/别名、`|` 字面块、TAB
- 长文本（> 70 字符）用 `>-` 折叠块，**单行书写**（多行会被折叠成空格，中文尤其不能多出空格）
- 序列化器实现见 `_needs_quote` / `_scalar` / `_bi_block` / `_bi_inline`

---

## 4. 指纹算法

```
对 source 的 path 去重后按升序排序，逐个：
    sha256.update(UTF-8(path))
    sha256.update(b"\x00")
    sha256.update(文件全部字节)
取 SHA-256 十六进制前 32 位
```

- 与传入顺序**无关**（内部排序）
- `source` 为空 → 空集指纹（sha256 of empty）
- 缺失文件不参与计算，但会被报出
- 用途：增量同步靠它检测漂移（`evidence/fingerprint-drift`）

---

## 5. 冻结回执

`build` 通过 0 error 门禁后产出 `receipt.json`：

```json
{"schema_version":1,"project":"...","built_at":"...","module_count":N,
 "digest":"<sha256>","errors":0,"warnings":N,"frozen":true,"stats":{...}}
```

`digest` = 对 `modules/**/*.md` 与 `renders/**/*.json` 按相对路径升序做同样的
「路径 + 0x00 + 字节」SHA-256（`structure_digest()`）。**可复算**：任何时刻重算应相等，
不等即结构数据被外部改过（绕过工具裸写）。

---

## 6. 校验：severity 分级

**error（阻断 build / change-close）**

`structure/parse-error` `structure/id-format` `structure/uid-format`
`structure/file-id-mismatch` `structure/parent-mismatch` `structure/parent-not-exist`
`structure/bilingual-missing` `structure/revision-format` `structure/fingerprint-format`
`structure/root-missing` `state-invalid` `state/planned-fingerprint`
`evidence/source-invalid`
`api/leaf-missing` `api/non-leaf` `api/key-duplicate` `api/protocol-invalid`
`api/method-invalid` `api/path-missing`
`dep/target-missing` `dep/kind-invalid` `dep/self` `dep/from-api-invalid` `dep/to-api-invalid`
`deprecation/inbound`
`layout/orphan` `layout/not-container` `layout/order-child` `layout/group-child`
`layout/mode-invalid` `layout/max-columns-invalid`
`change/create-not-landed` `change/create-missing` `refresh/activate-not-landed`
`policy/<rule-id>`（severity=error 的规则）

**warning（记录但不阻断）**

`api/leaf-empty` `api/non-leaf-empty` `dep/unanchored`
`structure/leaf-too-coarse` `structure/shallow-hierarchy` `structure/planned-source-missing`
`evidence/fingerprint-drift` `evidence/source-missing`
`state/deprecated-no-replacement`
`layout/missing` `layout/hint-edge-missing`
`delete/dangling-edges` `promote/apis-dropped`
`refresh/git-unavailable` `sync/git-failed`
`policy/<rule-id>`（severity=warning 的规则）

完整对照表：`run.sh help errors`

---

## 7. 粒度与规模

- **目标深度**：小仓库 ≥ 3 层；中型 ≥ 5–8 层；大仓 8 层以上。**深度不设上限**
- **叶子判据**：一个文件 / 一个类 / 一组内聚函数 / 一个 UI 组件 / 一条路由组
- **必须继续拆的信号**（触发 `structure/leaf-too-coarse`）：
  - `source` 覆盖 ≥ 3 个文件
  - 单文件行跨度 ≥ 300
  - `apis` ≥ 6 条且能按子功能分组
- **规模不设上限**：真实项目常见 100–1000+ 模块。宁可多建框，不要粗粒度合并
- **单批 ≤ 200 个模块**（`upsert` 批量提交原子、失败回滚）
- **每叶 API 建议 3–5 个**：越少，箭头锚定越精确

---

## 8. 渲染数据集

`renders/<id>.json` 描述"这一层怎么画"。作用域是**当前根模块**（下钻后即被下钻的那个）。
✅ = 渲染器已消费；⚠️ = schema 接受但当前不影响渲染。

| 字段 | 状态 | 作用 |
|---|---|---|
| `order` | ✅ | 直接子模块的纵向次序（生产者 → 消费者；未列出的按原树序追加在后） |
| `reading` | ✅ | `{zh,en}` 一句话阅读导语，画布上方一条导语带 |
| `groups` | ✅ | `[{id, title:{zh,en}, children:[...]}]`；**需同时把 `mode` 设为 `groups`**，才给每组画带标题的虚线框 |
| `edge_hints` | ✅ | `[{from,to,kind?,lane?,style?}]` 给单条边定车道或线型。`lane` 2..4 → 纵向偏移 0/12/24px；`style` 传 SVG dasharray 串或 `"solid"` |
| `mode` | ⚠️ | 只在 `=groups` 时决定"要不要画分组框"。`auto` / `layers` / `grid` **不改变布局** |
| `max_columns` | ⚠️ | **未实现**。`grid` 换行与列数控制尚未落地 |

`edge_hints.bundle` / `priority` 字段 schema 保留，暂未实现。

### 已知差距

- 布局恒为**单列整洁树**，实际排列完全由 `order` 驱动。
- `layers` / `grid` 目前只是标签，不产生与 `auto` 不同的布局效果。
  想让管道从左到右流，只能靠 `order` 手工排序。
- `max_columns` 无任何效果。

**可读性配方（务必遵守）**

1. **顺序 = 数据流**：`order` 按"谁先产生、谁后消费"排
2. **分组 = 领域边界**：同一子系统/层/角色的子模块放一组；每组 2–5 个为宜（配 `mode: groups`）
3. **导语 = 阅读路径**：`reading` 一句话说明"从哪看起、箭头代表什么"
4. **长边提示**：回指/跨整张图的边写 `edge_hints`，`lane` 2..4 拉开轨道
5. **不要硬凑分组**：一组平级功能就别写 `groups`

---

## 9. 架构规则（policy.yml）

项目创建时自动安装：

```yaml
version: 1
rules:
  - id: core-acyclic
    type: acyclic          # 禁环
    severity: error
  - id: no-deprecated-inbound
    type: forbid-dependency
    severity: warning
    to_state: deprecated
```

已实现的规则类型：

| type | 参数 | 语义 |
|---|---|---|
| `acyclic` | — | 依赖图禁环 |
| `max-depth` | `limit` | id 段数上限 |
| `naming` | `pattern` | 每个 id 段的命名正则 |
| `forbid-dependency` | `from` / `to` / `to_state` | 禁某些依赖；`from`/`to` 支持 `xxx.*` 前缀 |
| `dependency-direction` | `layers` | 层顺序即允许方向（层号小的不可被层号大的调用） |

**先定规则再动手**：`validate` / `check` 都按同一套规则执行。违规先改设计；
规则确需调整时用 `policy-upsert` 覆盖并说明理由，**不能用删除规则的方式绕过**。

---

## 10. 命令与迁移对应表

原 DSH 版 31 个工具 → 本版 30 个命令的映射：

| 原工具 | 本版命令 | 说明 |
|---|---|---|
| `archinorm_tree_list` + `archinorm_module_list` | `list` | 合并；`--parent` / `--tree` / `--leaves` / `--max-depth` 过滤 |
| `archinorm_project_init` | `init` | 建目录 + 默认 policy + 可选计划态根 |
| `archinorm_module_upsert` / `_batch` | `upsert` | 单条或数组批量（原子） |
| `archinorm_module_patch` | `patch` | 支持 `--expect-updated-at` / `--dry-run` |
| `archinorm_module_get` | `get` | |
| `archinorm_module_delete` | `delete` | 返回悬空边预警 |
| `archinorm_module_move` | `move` | 保 uid、级联、重写 deps、迁移渲染数据 |
| `archinorm_module_promote` | `promote` | 叶子 → 容器 |
| `archinorm_module_refresh` | `change-close --activate` / `patch` | 本版无独立 refresh，激活走 change-close |
| `archinorm_fingerprint` | `fingerprint` | |
| `archinorm_validate` | `validate` | |
| `archinorm_build` | `build` | |
| `archinorm_render` | `render` | |
| `archinorm_outline` | `build` 内含 | 编译时自动重建 |
| `archinorm_search` | `search` | |
| `archinorm_deps_find` | `deps` | 出向 + 反向 |
| `archinorm_sync` | `sync` | |
| `archinorm_check` | `check` | |
| `archinorm_brief` | `brief` | |
| `archinorm_layout_get` / `_upsert` / `_delete` | `layout-get` / `layout-upsert` / `layout-delete` | |
| `archinorm_change_open/update/list/close` | `change-open/update/list/close` | |
| `archinorm_policy_get/upsert` | `policy-get` / `policy-upsert` | |
| `archinorm_help` | `help` | 主题：fields/deps/renders/flow/errors/migrate/tools/all/`tool:<名>` |
| — | `inventory` | **新增**：只读清点仓库 |
| — | `migrate` | **新增**：一步迁移 |
| — | `migrate-all` | **新增**：批量迁移 |

---

## 11. 迁移语义（重点澄清）

**"迁移项目"≠ 改代码。** 它是给项目生成一份结构数据 + 架构图：

- 只读扫描仓库，按目录结构切模块，`source` 填该目录下的代码文件
- `description` 一律写成 `【待审】` 占位 → **必须人工补全**
- 叶子 `apis: []` → 会出 `api/leaf-empty` 警告，属正常起步状态
- `fingerprint` 用真实文件算出；非 git 仓库 `revision` 记 40 个 0
- 跳过 `node_modules` / `.git` / `dist` / `build` / `__pycache__` / `.venv` / `target` / `vendor` 等
- 输出目录 = `<--dir>/archinorm-<slug>/`；`--force` 只删 `archinorm-*` 结构目录（有安全校验）

**参数建议**：`--depth 2` 小项目 / 3 中型 / 大仓先 2 起步再逐层下钻；
`--max-modules` 默认 300 防爆量，撑爆就降 `--depth`。
