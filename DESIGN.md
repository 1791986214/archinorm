# Design System: archinorm

> 本渲染器的视觉语言吸收自 [archify](https://github.com/tt-a1i/archify) 的 `DESIGN.md`（MIT）。
> 这份文档记录的是 **archinorm 落地后的实际取值与映射规则**，不是照抄。

```yaml
colors:
  canvas: "#020617"      # 画布底色
  mask:   "#0F172A"      # 面板/节点底色
  ink:    "#FFFFFF"      # 主文字
  muted:  "#94A3B8"      # 次级文字
  dim:    "#475569"      # 三级文字 / 容器描边
  border: "#1E293B"      # 分隔线 / 结构边
  # 语义色 —— 只表示含义，不做装饰
  frontend:   "#22D3EE"  # HTTP / WS
  backend:    "#34D399"  # RPC / CALL
  database:   "#A78BFA"  # 存储
  messagebus: "#FB923C"  # 事件 / MQ
  cloud:      "#FBBF24"  # 计划态
  security:   "#FB7185"  # 保留位（见下）
  external:   "#94A3B8"  # 其它 / 废弃
typography:
  family: 'JetBrains Mono, ui-monospace, SFMono-Regular, Menlo, Consolas, "Courier New", monospace'
  headline: { size: "1.0625rem", weight: 700 }   # 顶栏项目名
  title:    { size: "0.875rem",  weight: 600 }   # 面板标题
  body:     { size: "0.75rem",   weight: 400 }   # 正文 / 节点名
  label:    { size: "0.55rem",   weight: 700, tracking: "0.1em" }  # 节点元信息
  micro:    { size: "0.58rem",   weight: 400 }   # 页脚 / 节点 id
rounded:
  precise: "0.2rem"      # 蓝图主题下的控件
  control: "0.5rem"      # 按钮 / 图例
  panel:   "1rem"        # 侧栏
  node:    "6px"         # 节点矩形
spacing:
  节点宽: "198px"   节点高: "50px"
  列间距: "268px"   行间距: "72px"   画布留白: "28px"
motion:
  fast: "150ms"          # 唯一的时间常量，用于 hover / 状态切换
```

## Overview

**北极星：「结构仪表」（The Structure Console）**

archinorm 的图是一件**工程仪器**，不是画图软件。画布只讲一个空间叙事：
从左到右是层次，箭头是声明的依赖。控件克制、信息渐进披露 ——
读者从主路径走到精确的依赖、API 和代码行证据，全程不丢方向。

- 一块主导画布，配件低干扰
- 一套固定的语义色词汇，节点 / 边 / 图例共用
- **全等宽字体**，小字号标签，为工程审阅保留必要的密度
- 默认深色；亮色与蓝图保持同一套词汇与信息优先级，不是另做一套产品
- 唯一动效常量 150ms；静态导出必须完整可读

## Colors

深色控制台 + 六个生效的语义信号色。**颜色只标识含义，不做装饰。**

### 语义映射规则（这是 archinorm 独有的部分）

自动判定，按优先级从高到低：

| 顺序 | 条件 | 取色 |
|---|---|---|
| 1 | `state: planned` | `cloud` 琥珀 |
| 2 | `state: deprecated` | `external` 灰 |
| 3 | 叶子含 `kafka` / `amqp` 接口 | `messagebus` 橙 |
| 4 | 叶子含 `mysql` / `redis` / `file` 接口 | `database` 紫 |
| 5 | 叶子含 `http` / `ws` / `graphql` 接口 | `frontend` 青 |
| 6 | 叶子含 `rpc` / `grpc` 接口 | `backend` 绿 |
| 7 | 叶子其它情况 | `external` 灰 |
| 8 | 容器模块 | **不着色**，用 `dim` 描边 |

### 边的着色与线型

| `kind` | 颜色 | 线型 |
|---|---|---|
| `call` | `backend` 绿 | 实线 |
| `event` | `messagebus` 橙 | 虚线 `5 4` |
| `dataflow` | `database` 紫 | 实线 |
| `reference` | `external` 灰 | 点线 `2 4` |

线宽 1.4px、不透明度 0.85；箭头用 `<marker>` 单独着色，与线同色。

### ⚠️ `security` 是保留位

`#FB7185`（安全边界）在当前自动映射规则下**不会被产出** —— 没有可判定的协议或字段。
保留它是因为规则扩展（自定义标签、`policy.yml` 里的安全域）时会用到。
**不要为了让这个颜色出现而硬凑一个类别。**

### 主题（Theme Parity Rule）

| 主题 | canvas | mask | 语义色 |
|---|---|---|---|
| 暗色（默认） | `#020617` | `#0F172A` | 上表原值 |
| 亮色 | `#F8FAFC` | `#FFFFFF` | 逐一加深（青 `#0891B2` / 绿 `#059669` / 紫 `#7C3AED` / 琥珀 `#B45309` / 玫瑰 `#BE123C` / 橙 `#C2410C`） |
| 蓝图 | `#0B1B33` | `#0F2547` | 逐一提亮（青 `#7DD3FC` / 绿 `#86EFAC` / 紫 `#C4B5FD` / 琥珀 `#FDE68A` / 玫瑰 `#FDA4AF` / 橙 `#FDBA74`） |

三套主题**只换材质与对比度，不换类别归属**。「青=HTTP」在哪个主题下都成立。

## Typography

单一等宽字族。层级靠字重、字号、字距、大小写拉开，不引入装饰性字体。

| 层级 | 取值 | 用途 |
|---|---|---|
| Headline | 1.0625rem / 700 | 顶栏项目名 |
| Title | 0.875rem / 600 | 面板标题、卡片主名 |
| Body | 0.75rem / 400 | 说明文字、节点名 |
| Label | 0.55rem / 700 / 0.1em | 节点元信息（`3 SUB` `1 API` `3→`） |
| Micro | 0.58rem / 400 | 节点 id、页脚 |

**可读性下限规则**：≤0.58rem 只承载元信息，不承载句子。
读者需要读懂一句话，就把它提到 Body 字号，或者放进面板。

字体族全离线：`JetBrains Mono` 装了就优先，没装则回退到系统等宽。
**不引入 CDN 字体** —— 产物必须能在断网机器上打开。

## Layout

画布是**分层节点链路图**，不是卡片网格：

- 层级 = 列（`x = 留白 + 深度 × 列间距`）
- 同一父节点下按 `renders/<id>.json` 的 `order` 纵向排布；父节点纵向居中对齐其子节点
- 容器模块不着色、`dim` 描边；叶子按协议着色并在左侧加 3px 强调条
- 结构边（父子）用正交折线，1px `border` 色，**刻意压低存在感**
- 依赖边用三次贝塞尔曲线，按 `kind` 着色，最多 3 条并行加 7px 纵向偏移错开
- 每 3 条依赖边分一个车道；`edge_hints.lane` 可覆盖车道（2..4 → 0/12/24px）

缩放范围 0.25×–2.4×，`fit()` 留 26px 边距、上限 1.1×。

页面只 **8 个**自绘 SVG 图元类：`nbox` `ndot` `nlabel` `nid` `nmeta` `sedge` `dedge` `node`，
外加分组框用的 `grp` `grplabel`。没有第三方图形库。

## 渲染数据的消费规则

`renders/<id>.json` 描述"这一层怎么画"。作用域是**当前根模块**（下钻后即被下钻的那个）。
渲染器实际消费：

| 字段 | 状态 | 行为 |
|---|---|---|
| `order` | ✅ | 决定直接子模块的纵向次序；未列出的按原树序追加在后 |
| `reading` | ✅ | 画布上方一条导语带（左侧 3px 青色强调条） |
| `groups` + `mode:groups` | ✅ | 给每组成员画虚线框 + 左上角标题 |
| `edge_hints` | ✅ | 按 `{from,to,kind}` 匹配单条边，可覆盖 `lane` 与线型 `style` |
| `mode`（auto/layers/grid） | ⚠️ | **不改变布局**。只在 `=groups` 时决定要不要画分组框 |
| `max_columns` | ⚠️ | **未实现**。schema 接受，渲染忽略 |

### 已知差距（不藏着）

- **`max_columns` 完全没落地**：`grid` 的网格换行、`layers` 的按列数折行都还没有。
  布局恒为单列整洁树，排列完全由 `order` 驱动。
- **`layers` / `grid` 只是标签**：它们目前不产生任何与 `auto` 不同的布局效果。
  想让管道从左到右流，只能靠 `order` 手工排序。
- **`edge_hints.bundle` / `priority`** schema 保留，未实现。

这些在 `help renders` 里也如实标注了（✅ / ⚠️ 记号），不靠文档外的地方补充。

## Motion

**只有一个时间常量：150ms**，用于节点描边、hover 状态、透明度过渡。

- 没有入场动画、没有自动播放
- 选中时的"上下游点亮"是即时切换 + 150ms 过渡，不是逐帧动画
- 尊重 `prefers-reduced-motion: reduce` —— 命中时全部过渡置空

## Components

### 节点

`198 × 50`，`rx 6`，`mask` 底 + 语义色描边（1.2px）或 `dim` 描边（1px）。
左侧 3px 语义色强调条 + 16px 处一个 4px 圆点。两行文字：名称（Body 600）+ id（Micro）。
右上角元信息：容器显示 `N SUB`，叶子显示 `N API`，有出向依赖追加 `N→`。

### 边

结构边低调、依赖边醒目。选中节点时，**无关的依赖边降到 0.1 不透明度**，
无关节点降到 0.14 —— 强调靠"其余变暗"，不靠"目标变亮"。

### 侧栏（Semantic Passport）

`392px` 固定宽，`mask` 底 + 左侧 1px 分隔线。四页签：
概览 / 接口 / 依赖 / 元数据。图例固定在画布左下角，只列出**当前图里真实出现**的语义色。

### 工具条

顶部 32px 高按钮，1px `border` 描边、透明底。两组互斥分段控件（主题 / 视图模式）
+ 一个复位按钮。窄屏（<900px）时侧栏浮在画布上方，不做第二套界面。

## Do's and Don'ts

### Do

- **Do** 让主路径先可读，再披露次级关系与细节
- **Do** 让每个焦点、依赖、计数都来自声明的结构数据，不做推测性连线
- **Do** 用非颜色线索表达状态（`planned` 除了琥珀色还有文字标签）
- **Do** 保持三主题的信息优先级一致
- **Do** 让导出的单文件 HTML 在断网、无字体、无 JS 增强的情况下仍能读出结构

### Don't

- **Don't** 用密集仪表盘外壳、无止境的同构卡片网格、装饰性玻璃、渐变文字
  —— AI 生成界面的陈词滥调
- **Don't** 引入 CDN 字体 / 图标库 / 图形库；产物必须自包含
- **Don't** 用颜色表达唯一含义（色盲不可读）
- **Don't** 添加需要联网才能看的装饰
- **Don't** 为了塞进一个语义色而硬造类别
- **Don't** 把 `deps` 渲染成暗示运行时调用的样子 —— 它是声明的关系，不是链路追踪

## 出处

- 视觉语言：`archify` 的 `DESIGN.md`（MIT, tt-a1i）—— 深色画布、全等宽字体、
  七语义色、扁平克制、`Theme Parity Rule`
- 结构语义：`dsh-normify`（MIT, yan-mc）—— 模块树、API 归属、依赖分型
- 本文件记录的是 archinorm 的实际实现，取值以 `skill/bin/parts/07_p07_html_head.py`
  与 `parts/08_p08_html_tail.py` 为准
