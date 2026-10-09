# 技能自动更新说明

## 一句话结论

**乐享知识库本身不提供"技能自动更新"能力**——它只是个文件仓库，存的是你上传那一刻的静态快照，
不会去跟踪源仓库的版本。所以自动更新必须绕回 **GitHub 源仓库**，
由技能自己在本地完成「比对版本 → 下载新版 → 替换 → 自检 → 失败回滚」。

本包自带这套机制：`bin/skillup.py`（零第三方依赖，只用 Python 标准库）。

---

## 一、它怎么工作

```
每 24 小时（或你手动触发）
   │
   ├─ 1. 读本技能 manifest.json 里的 source（repo / ref / releases / artifact）
   ├─ 2. 打 GitHub API 取远端版本
   │       releases: true  → /releases/latest 的 tag_name
   │       releases: false → /commits?sha=<ref>&per_page=1 的 commit SHA
   │       version_file 配了 → 再读仓库里那个文件的首个版本号
   ├─ 3. 与 manifest.version 比对：不新就结束，一行日志都不多写
   └─ 4. 有新版本 →
          ① 下载（整个仓库 zip / 指定 artifact / release 资产）
          ② 把现有技能目录**改名**成 <名>.bak-<版本>-<时间戳>（不是删除）
          ③ 展开新版到位
          ④ 跑 manifest.self_test
              通过 → 写回 installed.version/commit，完事
              失败 → 自动把备份改回来，新版挪到 <名>.broken-<时间戳> 留证
```

### 五条硬护栏

| # | 护栏 | 说明 |
|---|---|---|
| 1 | **只动自己** | 只对 `<技能目录>` 及其同级备份目录操作，绝不碰别处 |
| 2 | **绝不删除** | 旧版一律改名挪走；出问题随时能 `rollback` 或手动改名还原 |
| 3 | **自检门禁** | 替换后必须过 `self_test`，不过就自动回滚，不留半成品 |
| 4 | **静默降级** | 没网 / 仓库挂了 / API 限流 → 只写一行提示到 stderr，技能照常用 |
| 5 | **24 小时节流** | 不是每次调用都打网络；`.state/last_check` 控制 |

### 代理自动回退

按顺序试：显式 `--proxy` → 环境变量 `HTTPS_PROXY/HTTP_PROXY` → manifest 的 `source.proxy`
→ 直连 → `http://127.0.0.1:7897`（本机 Clash/Mihomo 类代理的常见端口）。
全部失败则静默放弃，不影响技能运行。

---

## 二、三种触发方式

### 方式 A：每次使用自动看一眼（默认已启用，零配置）

`bin/run.bat` / `bin/run.sh` 在启动引擎前会调一次
`skillup.py --quiet check`，24 小时内只真联网一次。
发现新版会把一行提示写到 stderr（**代理/助手能看到**）；没配置更新源时立即返回，不联网。

这是最省事的方式：**只要技能被用过，就不会长期停留在旧版本**。

### 方式 B：手动一键更新

- Windows：双击包根的 **`update.bat`**
- macOS / Linux：`./update.sh`

它先打印 `status`（当前版本/源仓库/上次检查/备份列表），再执行 `update`。

### 方式 C：系统计划任务（想完全自动就上这个）

**Windows（每天 09:00，任务名 `archinorm-update`）**

```bat
schtasks /Create /TN "archinorm-update" /SC DAILY /ST 09:00 /F ^
  /TR "\"%USERPROFILE%\.workbuddy\skills\archinorm\bin\run.bat\" updatetask"
```

更直接的做法是让它跑 skillup 本身：

```bat
schtasks /Create /TN "archinorm-update" /SC DAILY /ST 09:00 /F ^
  /TR "py -3 \"%USERPROFILE%\.workbuddy\skills\archinorm\bin\skillup.py\" update"
```

删除：`schtasks /Delete /TN "archinorm-update" /F`

**macOS（每天 09:00，launchd）**

存成 `~/Library/LaunchAgents/com.local.archinorm.update.plist`：

```xml
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN"
  "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0"><dict>
  <key>Label</key><string>com.local.archinorm.update</string>
  <key>ProgramArguments</key><array>
    <string>/usr/bin/python3</string>
    <string>__SKILL__/bin/skillup.py</string>
    <string>update</string>
  </array>
  <key>StartCalendarInterval</key><dict>
    <key>Hour</key><integer>9</integer><key>Minute</key><integer>0</integer>
  </dict>
  <key>StandardErrorPath</key><string>/tmp/archinorm-update.err</string>
</dict></plist>
```

装载：`launchctl load ~/Library/LaunchAgents/com.local.archinorm.update.plist`
（把 `__SKILL__` 换成技能实际路径，如 `$HOME/.workbuddy/skills/archinorm`）

---

## 三、给别的技能接上自动更新

三步：

### 1. 把 `skillup.py` 放进那个技能的 `bin/`

### 2. 在它的 `manifest.json` 里写 `source`

已备好现成样例：**`examples/manifest.archify.json`**（archify 的真实配置）。

**archify 例子**（`github.com/tt-a1i/archify`）：

```json
"source": {
  "type": "github",
  "repo": "tt-a1i/archify",
  "ref": "main",
  "releases": false,
  "artifact": "archify.zip",
  "strip_root": true,
  "auto_update": false
}
```

这份配置的意思是：盯 `main` 分支的最新 commit，只下载仓库根目录那个 `archify.zip`，
解包时自动剥掉多余的一层根目录。

实测（2026-10-09）：远程最新 commit `bb990b1`（2026-10-08 18:10 UTC 推送），
`check` 能正确识别并提示可更新。

### 3. 跑一次

```sh
python bin/skillup.py check --force    # 只查，不改
python bin/skillup.py update --dry-run # 演一遍
python bin/skillup.py update           # 真更新
python bin/skillup.py rollback         # 后悔了
```

---

## 四、字段速查

| 字段 | 必填 | 说明 |
|---|---|---|
| `source.repo` | ✅ | `owner/name` |
| `source.ref` | | 分支或 tag，默认 `main` |
| `source.releases` | | `true` 用 release tag 判版本；`false`（默认）用最新 commit SHA |
| `source.version_file` | | 读仓库里某文件的首个版本号，比 commit 更可读 |
| `source.artifact` | | 只下这一个文件（如 `archify.zip`），不下整个仓库 |
| `source.asset_pattern` | | 配合 `releases:true`，从 release 资产里通配挑，如 `*.zip` |
| `source.package_subdir` | | 压缩包内只取这个子目录，如 `skill` |
| `source.strip_root` | | 默认 `true`，自动剥掉压缩包多出来的根目录层 |
| `source.auto_update` | | `true`：每日自检时直接装；`false`：只提示 |
| `source.proxy` | | 如 `http://127.0.0.1:7897` |
| `self_test` | | 相对技能根的自检脚本路径；跑不过就回滚 |
| `updater` | | `skillup.py` 的路径 |

---

## 五、常见问题

| 现象 | 原因 / 处理 |
|---|---|
| `check` 说"未配置更新源" | `manifest.source.repo` 是 `null`（本包默认如此，因为暂无自己仓库）。填上你的仓库即可。 |
| `check` 报网络错误但不影响用 | 正常降级。加 `--proxy http://127.0.0.1:7897` 或写进 `source.proxy`。 |
| 一直显示"已是最新" | 确认 `ref` 写对；`releases:true` 时仓库得真有 release。 |
| 更新后自检没过，被回滚了 | 看同级目录里 `<名>.broken-<时间戳>`，里面是没通过的新版，可人工排查。 |
| 想彻底关掉自动检查 | 把 `manifest.source.repo` 置 `null`，或删掉 `.state/` 目录并在 run 脚本里去掉那行调用。 |
| 备份目录越攒越多 | `skillup.py backups` 列出来，确认新版没问题后自己删旧的（工具**不会**替你删）。 |

---

## 六、边界说明（别误解）

- ❌ 这套机制**不会**更新乐享知识库里的那个 zip。乐享是发布渠道，不是更新通道。
  想让库里的包也是新版，得重新打包上传。
- ❌ **不能**对着 `github.com/yan-mc/dsh-normify` 自动更新本包——那是 DSH 插件形态，
  与本 CLI 包结构不同（本包已吸收它的全部规范语义，但文件形态是两回事）。
- ✅ 只要某个技能**自己带了** `manifest.json` + `skillup.py`，不管它最初是从乐享、
  网盘还是 U 盘装进来的，装完之后就都能自我更新到源仓库最新版。

---

*本文档随「项目框架·归一化框架图构建器」v1.2.0 发布。*
