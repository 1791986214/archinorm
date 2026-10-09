#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""把 parts/ 下的编号分段合并为单文件 archinorm.py，并做语法 + 重复定义自检。

用法：<venv>/bin/python build.py
"""
import collections
import re
import shutil
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent
PARTS = ROOT / "parts"
TARGET = ROOT / "archinorm.py"


def main() -> int:
    files = sorted(PARTS.glob("[0-9][0-9]_*.py"))
    if not files:
        print("build: parts/ 下没有编号分段（NN_*.py）", file=sys.stderr)
        return 2

    text = "\n\n".join(f.read_text(encoding="utf-8").rstrip("\n") for f in files) + "\n"

    defs = re.findall(r"^(?:def|class)\s+(\w+)", text, re.M)
    dup = {k: v for k, v in collections.Counter(defs).items() if v > 1}
    consts = re.findall(r"^([A-Z_]{3,})\s*=", text, re.M)
    dupc = {k: v for k, v in collections.Counter(consts).items() if v > 1}
    if dup or dupc:
        print(f"build: 检测到重复定义 def={dup} const={dupc}", file=sys.stderr)
        return 1

    TARGET.write_text(text, encoding="utf-8")
    try:
        compile(text, str(TARGET), "exec")
    except SyntaxError as exc:
        print(f"build: 语法错误 {exc}", file=sys.stderr)
        return 1

    # 冒烟：CLI 必须能装配（能挡住 argparse 子命令冲突、NameError 等）
    import subprocess
    probe = subprocess.run([sys.executable, str(TARGET), "help", "all"],
                           capture_output=True, text=True)
    if probe.returncode != 0:
        print("build: CLI 装配失败\n" + (probe.stderr or probe.stdout)[-1200:],
              file=sys.stderr)
        return 1

    # 单例守卫：入口/装配函数只能出现一次（分段被重复注入时最先崩这里）
    singles = {
        "def main(": 1,
        "def build_parser(": 1,
        'if __name__ == "__main__":': 1,
        "def register_migrate_subparsers(": 1,
    }
    for pat, want in singles.items():
        got = text.count(pat)
        if got != want:
            print(f"build: 单例守卫失败 —— {pat!r} 出现 {got} 次，应为 {want} 次",
                  file=sys.stderr)
            return 1

    print(f"build: {len(files)} 个分段 -> {TARGET.name}　"
          f"{text.count(chr(10))} 行 / {len(text.encode('utf-8'))} 字节 / "
          f"{len(set(defs))} 个顶层定义　单例守卫 OK　CLI 装配 OK")
    return 0


if __name__ == "__main__":
    sys.exit(main())
