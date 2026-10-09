# 项目框架·归一化框架图构建器（archinorm）—— 安装说明

> 把代码仓库的架构写成**归一化的分形模块树**，渲染成**深色交互式框架图**。
> 一个 Agent 技能，WorkBuddy / Claude Code / Codex 通用。**零第三方依赖**。
>
> **v1.2.0**　·　引擎 30 命令　·　自检 73/73（两种后端）　·　自带 GitHub 源仓库自动更新
>
> 源码与演示动图：**https://github.com/1791986214/archinorm**

---

## 零、先看它做什么

```
输入                                    输出
~/proj/myapp  ──archinorm migrate──▶   archinorm-myapp/
（你的代码库）                          ├── modules/          分形模块树（人机共读）
                                        ├── renders/          渲染数据
                                        ├── policy.yml        架构规则
                                        └── architecture.html ← 双击即开
```

```bat
set SKILL=%USERPROFILE%\.workbuddy\skills\archinorm
"%SKILL%\bin\run.bat" inventory --repo "D:\proj\myapp"     :: 先只读清点，不写任何东西
"%SKILL%\bin\run.bat" migrate  --repo "D:\proj\myapp" --dir "D:\arch" --render
```

`migrate` **只读扫描，不改一行业务代码**。产出的是**骨架**（`description` 是 `【待审】`占位、
叶子 `apis` 为空），人工补全后才是一张真正能读的图。

完整演示动图、三主题预览、命令实测输出，见仓库首页。

---

## 一、环境要求

| 项 | 要求 |
|---|---|
| 操作系统 | Windows 10/11 · macOS · Linux 均可（同一份包，自带两套启动器） |
| Python | **3.9 或更高**（唯一依赖；Windows 安装时务必勾 `Add python.exe to PATH`） |
| 第三方库 | **无**。PyYAML 有就用，没有自动切内置解析器（已验证等价） |
| 网络 | 生成架构图**完全离线**；只有「自动更新」需要联网 |
| 磁盘 | 约 1.5 MB |

---

## 二、安装

### Windows

1. **完整解压**整个 zip（别在压缩包里直接双击）。
2. 双击 **`install.bat`**，它会：
   - 探测已有同名技能 → 有就**改名备份**（绝不删除）
   - 复制 `skill\` 到 `%USERPROFILE%\.workbuddy\skills\archinorm\`
   - 探测 Python 并跑一次自检
3. **重启 WorkBuddy**，技能即生效。

手动安装：
```bat
mkdir "%USERPROFILE%\.workbuddy\skills"
xcopy /E /I /Y "解压目录\skill" "%USERPROFILE%\.workbuddy\skills\archinorm"
```

### macOS / Linux

```sh
SKILL_DIR="$HOME/.workbuddy/skills/archinorm"
mkdir -p "$(dirname "$SKILL_DIR")"
[ -e "$SKILL_DIR" ] && mv "$SKILL_DIR" "$SKILL_DIR.bak-$(date +%Y%m%d-%H%M%S)"
cp -R "解压目录/skill" "$SKILL_DIR"
chmod +x "$SKILL_DIR/bin/run.sh" "$SKILL_DIR/bin/skillup.py"
```

> 上面那行 `mv` 就是备份动作 —— **不删除**，随时能改回来。

---

## 三、验证安装

**Windows**
```bat
set SKILL=%USERPROFILE%\.workbuddy\skills\archinorm
"%SKILL%\bin\run.bat" help all
python "%SKILL%\tests\selftest.py"                    :: 期望 73/73
set ARCHINORM_NO_PYYAML=1
python "%SKILL%\tests\selftest.py"                    :: 零依赖路径，同样 73/73
```

**macOS / Linux**
```sh
SKILL="$HOME/.workbuddy/skills/archinorm"
"$SKILL/bin/run.sh" help all
python3 "$SKILL/tests/selftest.py"                    # 期望 73/73
ARCHINORM_NO_PYYAML=1 python3 "$SKILL/tests/selftest.py"
```

---

## 四、用起来

### 4.1 迁移一个已有项目

```bat
:: Windows
set SKILL=%USERPROFILE%\.workbuddy\skills\archinorm
"%SKILL%\bin\run.bat" inventory --repo "D:\proj\myapp"
"%SKILL%\bin\run.bat" migrate  --repo "D:\proj\myapp" --dir "D:\arch" --render
```

```sh
# macOS / Linux
"$SKILL/bin/run.sh" inventory --repo ~/proj/myapp
"$SKILL/bin/run.sh" migrate   --repo ~/proj/myapp --dir ~/arch --render
```

### 4.2 批量迁移一个根目录下的所有项目

```bat
"%SKILL%\bin\run.bat" migrate-all --root "D:\proj" --dir "D:\arch" --depth 2 --render
```

### 4.3 读懂一个陌生仓库

```sh
"$SKILL/bin/run.sh" search --dir ./arch/archinorm-<slug> --q 订单      # 按关键词定位模块
"$SKILL/bin/run.sh" deps   --dir ./arch/archinorm-<slug> --id <模块>    # 谁依赖它 / 它依赖谁
"$SKILL/bin/run.sh" brief  --dir ./arch/archinorm-<slug> --id <模块>    # 改这个模块的开发指引
"$SKILL/bin/run.sh" sync   --dir ./arch/archinorm-<slug> --repo <仓库>  # 代码变了，找脏子树
```

### 产物

```
D:\arch\archinorm-myapp\
  modules\            分形模块树（一模块一 Markdown，frontmatter 机器读、正文人读）
  renders\            每个容器一份渲染数据（顺序 / 分组 / 布局 / 阅读导语）
  changes\            变更日志
  policy.yml          架构规则
  architecture.html   ← 交互式框架图，双击浏览器打开，单文件无外链
  tree.json / outline.md / api-index.json / receipt.json
```

**交互**：拖动平移 · 滚轮缩放 · 单击选中（上下游高亮 + 详情面板）·
再击/双击下钻 · 面板四页签（概览/接口/依赖/元数据）· 暗色/亮色/蓝图 · 深链 `#module=<id>`。

### 不确定命令怎么用？

```bat
"%SKILL%\bin\run.bat" help tool:<命令名>    :: 该命令的完整参数树
"%SKILL%\bin\run.bat" help all              :: 全部命令 + 主题
```

**别猜参数。**

---

## 五、自动更新

### 一键
- Windows：双击 **`update.bat`**
- macOS / Linux：`./update.sh`

流程：查远端 → **备份现有版本**（改名，不删除）→ 替换 → 跑自检 →
**自检不过自动回滚**，新版留在 `<名>.broken-<时间戳>` 供排查。

### 每天自动看一眼
`bin/run.bat` / `bin/run.sh` 已在启动时内置「每天最多一次」的静默检查（24 小时节流），
发现新版只提示、不擅自安装。没配更新源时立即返回，不联网、不拖慢。

### 完全自动（系统计划任务）
见 `skill/examples/README-AUTO-UPDATE.md`，里面给了 Windows `schtasks` 与 macOS `launchd` 的现成命令。

### 换源 / 给别的技能接上
把技能的 `manifest.json` 里 `source` 段填上源仓库即可。
**archify 的现成配置**在 `skill/examples/manifest.archify.json`。

> ⚠️ **知识库（乐享 / 网盘等）不提供更新能力** —— 它只是文件仓库，存的是上传那一刻的快照。
> 自动更新必须回到 GitHub 源仓库，由技能本地完成。

---

## 六、常见问题

| 现象 | 处理 |
|---|---|
| `找不到 Python` | 装 Python 3.9+，勾 `Add python.exe to PATH`，重跑 `install.bat` |
| 控制台中文乱码 | 启动器已内置 `chcp 65001` + `PYTHONUTF8=1`；仍乱码就手动 `chcp 65001` |
| `migrate` 报 `migrate/exists` | 加 `--force`（**只删 `archinorm-*` 结构目录，有安全校验**） |
| 架构图打开是空白 | 渲染前先 `build --render`，或 `migrate` 时加 `--render` |
| 迁移后满屏 `【待审】` | 正常。自动生成的是骨架，`description` / 叶子 `apis` 要人工补全 |
| 改完代码图没变 | 图是数据的视图：先 `sync` 找脏子树，再 `build --render` |
| 更新提示网络失败 | 正常降级，不影响使用。需要代理就加 `--proxy http://127.0.0.1:7897` |
| 360 / 火绒拦截 | 本包纯 Python + 批处理，除更新外不联网、不写注册表、不碰业务代码；放行技能目录即可 |

---

## 七、卸载

- Windows：双击 **`uninstall.bat`**（改名移走，不删除，可恢复）
- macOS / Linux：`mv "$HOME/.workbuddy/skills/archinorm" "$HOME/.workbuddy/skills/archinorm.removed"`

---

## 八、包内结构

```
archinorm-v1.2.0\
├── README-INSTALL.md        本文件
├── install.bat / uninstall.bat / update.bat / update.sh
├── VERSION.txt
└── skill\                   ← 复制到 ~/.workbuddy/skills/archinorm
    ├── SKILL.md             技能说明（铁律 / 三条主流程 / 交付标注）
    ├── manifest.json        版本与更新源声明
    ├── bin\
    │   ├── archinorm.py     引擎（30 命令）
    │   ├── run.bat / run.sh 启动器（含每日更新自检）
    │   ├── skillup.py       自动更新器（零依赖）
    │   ├── build.py         由 parts\ 重新合并引擎（含单例守卫）
    │   └── parts\           引擎源码分段（16 段）
    ├── examples\
    │   ├── manifest.archify.json   现成的更新源配置样例
    │   └── README-AUTO-UPDATE.md   自动更新完整说明
    ├── references\SPEC.md   完整规范（数据模型 / 诊断码分级 / 31→30 映射）
    └── tests\selftest.py    73 项断言
```

---

## 九、交付标注规范（硬性）

任何采用本框架的交付，说明里必须写明：

```
架构框架：项目框架·归一化框架图构建器（archinorm）
结构数据：<项目路径>\archinorm-<slug>\
框架图　：<项目路径>\archinorm-<slug>\architecture.html
校验状态：validate 0 error（warning N 条）
配置状态：description/apis 已人工补全  ← 或 → 仍为【待审】占位
```

---

*结构语义源自 github.com/yan-mc/dsh-normify（MIT, yan-mc）；
视觉语言源自 github.com/tt-a1i/archify DESIGN.md（MIT）。*
