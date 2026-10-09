# 更新日志

## v1.2.0 — 2026-10-09

### 修复：渲染器此前**完全没读** `renders/` 数据

写 `PRODUCT.md` 前核对实现，发现一个 P0 级问题：`help renders` 对外承诺了
`mode` / `max_columns` / `order` / `groups` / `reading` / `edge_hints` 六个字段，
其中明确写着「`mode=groups` 时**每组一个带标题的框**」「`reading` **显示在图上方**」——
但 `parts/08` 里 `renders/` 读进来赋给变量后**从未使用**。
示例项目 `shop.json` 里的导语「从左到右：前端 → 订单域 → 基础设施…」**一次都没渲染出来过**。

**工具在承诺它不做的事。** 修：

| 字段 | 之前 | 现在 |
|---|---|---|
| `order` | 忽略 | ✅ 决定同级纵向次序（生产者 → 消费者） |
| `reading` | 忽略 | ✅ 画布上方导语带（左侧 3px 青色强调条） |
| `groups` + `mode:groups` | 忽略 | ✅ 每组一个虚线框 + 左上角标题 |
| `edge_hints` | 忽略 | ✅ 按 `{from,to,kind}` 匹配单边，覆盖 `lane` 与线型 `style` |
| `mode`(auto/layers/grid) | 忽略 | ⚠️ 仍不改变布局，仅 `=groups` 时决定画不画分组框 |
| `max_columns` | 忽略 | ⚠️ **仍未实现** |

**没做完的如实标出来**：`help renders` 与 `references/SPEC.md` 现在逐个字段标 ✅ / ⚠️，
并新增「已知差距」小节直说 `max_columns` 没落地、`layers`/`grid` 目前只是标签。

### 新增文档：PRODUCT.md / DESIGN.md

参照 archify 的文档结构：

- **`PRODUCT.md`** —— Register / Users / Purpose / Brand Personality /
  **Anti-references** / Design Principles / Accessibility。
  Anti-references 明确列出**不做**什么：「不做 Mermaid 美化器」「不做拖拽绘图工具」
  「**不把声明的 `deps` 说成运行时事实**」「不猜结构」「不自动改代码」。
- **`DESIGN.md`** —— 设计令牌（含三主题实际取值）、语义映射规则（含优先级顺序）、
  边型规则、布局常量、渲染数据消费规则、Do's & Don'ts。
  并**如实标注 `security` 是保留位**（当前自动映射不会产出它）。

### 演示与预览重录

渲染器变了，旧图立刻过期，全部重录：

- `docs/demo.gif` —— 88 帧 / 7.94s / 880×550 / **345 KB**，
  新增展示「阅读导语」与「分组框」（下钻「前端」可见「入口 / 交易」两个框）
- `docs/preview-{dark,light,blueprint}.jpg` —— 同一张全图重拍，现在都含导语带

## v1.1.0 — 2026-10-09

### 更名：normify-skill → **archinorm**

原名 `normify-skill` 只读了「normify 的 skill 版」，完全看不出这个产物是
**dsh-normify 的结构语义 × archify 的视觉语言** 融合出来的新东西。改名成 **archinorm**
（archi + norm），两个源头都点在名字里。

同步更名范围：

| 项 | 旧 | 新 |
|---|---|---|
| 仓库 | `normify-skill` | **`archinorm`** |
| 技能目录 | `skills/normify/` | **`skills/archinorm/`** |
| 引擎入口 | `bin/normify.py` | **`bin/archinorm.py`** |
| 结构数据目录 | `normify-<slug>/` | **`archinorm-<slug>/`** |
| 发行包 | `normify-skill-v1.0.2.zip` | **`archinorm-v1.1.0.zip`** |
| 环境变量 | `NORMIFY_NO_PYYAML` | **`ARCHINORM_NO_PYYAML`** |

### 文档：README 按「讲清核心功能」重写

参照 archify 的信息编排（第一屏就是演示、「预览」放多主题对比、场景独立成节），
把 README 从头理了一遍：

- **第一屏改为演示动图**（原来是"这是什么"的说明文字）
- **新增「输入 → 输出」** —— 补上原来完全缺失的一环：
  两条只读命令 → 真实执行输出 → 可进 Git 的产物目录树。
  并明确说明 `migrate` 产出的是**骨架**（`【待审】`占位 + 空 `apis`），
  补全后才是动图里那张能读的图。
- **新增「读懂一个真实仓库」** —— 一条 `migrate → search → deps → brief → sync`
  的实操路径，全部命令与参数都实测过
- **新增「预览：同一张图，三套主题」** —— 三张全图预览（暗 / 亮 / 蓝图）
- **新增「它解决什么问题」** —— 讲清「图是视图，数据才是产物」这个定位
- **「演示界面」改为操作对照表** —— 动图不再单列，避免与首屏重复
- 演示动图重录：覆盖「分形下钻」与**面板四个页签**（接口 / 依赖 / 元数据），
  原来只演示了选中与切主题，没体现核心

### 文档：安装说明同步 + 打包加版本闸门

- `README-INSTALL.md` 重写：补「先看它做什么」（输入 → 输出 一张图看懂）、
  仓库与演示动图入口、「读懂一个陌生仓库」命令路径、「改完代码图没变」的排查项。
  修正两处过期内容：版本号仍是 v1.0.2、包内结构里的文件名与实际不符
  （`README-安装.md` / `README-自动更新.md` → 实际是 `README-INSTALL.md` / `README-AUTO-UPDATE.md`）。
- **`pack.py` 新增版本一致性闸门**：扫描包内所有 `.md/.bat/.sh/.json/.txt`，
  任何 `vX.Y.Z` 字样都必须等于 `manifest.json` 的版本，否则**拒绝打包并点名文件**。
  已做负向测试（注入 `v1.9.9` → 退出码 1）。
  起因：`install.bat` 和 `examples/README-AUTO-UPDATE.md` 各留了一处旧版本号没跟着升。

> 仅文档资源变更，`VERSION` 保持 1.1.0 —— 已安装的技能不必为此更新。

**保留 `normify` 的地方**（刻意不改）：
- 上游本源引用 `yan-mc/dsh-normify` 与其 31 个 `normify_*` 工具名 —— 那是别人的东西
- `references/SPEC.md` 里的「31 → 30 命令映射表」—— 记录的是历史对应关系

---
## v1.0.2 — 2026-10-09

### 渲染器重做（吸收 archify 设计语言）

- **画布从卡片网格改为真正的图**：分层节点链路图（左→右分列 + 结构边 + 依赖曲线 + 箭头 marker）
- **深色证据控制台**：`#020617` 画布，取代原白底
- **七语义色**按协议自动映射：HTTP→青、RPC→绿、存储→紫、消息→橙、planned→琥珀、deprecated→灰
- **全等宽字体**（JetBrains Mono + 系统回退，离线可用）
- **Semantic Passport 式详情侧栏**：概览 / 接口 / 依赖 / 元数据 四页签
- 三主题：暗色 / 亮色 / 蓝图
- 交互升级：拖动平移 + 滚轮缩放 + 单击选中（上下游高亮、无关淡出）+ 再击/双击下钻 + `#module=<id>` 深链
- 依赖边加 lane 偏移，减少交叉重叠

### 技能自动更新（新增）

- **`bin/skillup.py`** —— 通用技能自动更新器，零第三方依赖
  - 盯 GitHub 源仓库：`/releases/latest` 或最新 commit SHA 判版本
  - 支持整仓 zip / 指定 artifact / release 资产 / `package_subdir` / `strip_root`
  - **备份（改名不删除）→ 替换 → 自检 → 失败自动回滚**
  - 五条硬护栏：只动自己 / 绝不删除 / 自检门禁 / 静默降级 / 24 小时节流
  - 代理自动回退：`--proxy` → 环境变量 → manifest → 直连 → `127.0.0.1:7897`
- **`manifest.json`** —— 声明版本与更新源
- **`examples/manifest.archify.json`** —— 现成样例（实测可识别 `tt-a1i/archify` 最新 commit）
- **`examples/README-AUTO-UPDATE.md`** —— 完整说明，含 Windows `schtasks` 与 macOS `launchd` 现成命令
- `run.bat` / `run.sh` 启动时内置「每天最多一次」静默检查

### 打包

- 新增 `pack.py`：一键组装发行包，自动 `.bat` 转 CRLF、剥 `__pycache__`
- 包内文件名全 ASCII（中文标题保留在内容里），避免老解压器乱码

### 修正

- `_needs_quote("")` 越界崩溃（API 不带 description 时必崩）
- 折叠块改 `>-`（原 `>` 会在解析回来时多一个尾部换行，破坏往返保真）
- 写后复用内存 `mods` 导致的假 `structure/file-id-mismatch`
- `move` 只写被移动模块，引用方 `deps.to` 未落盘
- `write_outline` 漏递归，大纲只输出根节点
- Windows 控制台 GBK 把中文 JSON 打崩 → 强制 UTF-8 收口

---

## v1.0.1 — 2026-10-09

- **零第三方依赖**：内置迷你 YAML 子集解析器，PyYAML 缺失时自动降级（等价性已验证）
- Windows 兼容：`run.bat` 启动器、`install.bat` / `uninstall.bat`（改名备份，绝不删除）
- `.bat` 全部 CRLF

## v1.0.0 — 2026-10-05

- 从 [yan-mc/dsh-normify](https://github.com/yan-mc/dsh-normify)（MIT）移植为独立 CLI
- 原 31 个 `normify_*` 工具收敛为 30 个命令，去掉 DSH / cordis 依赖
- 新增 `inventory` / `migrate` / `migrate-all` 三个原版没有的命令
- 单文件交互式渲染器（初版，卡片网格）
- 73 项自检断言
