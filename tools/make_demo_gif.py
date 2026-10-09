#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""把 CDP 录下的 JPEG 帧序列合成 GIF（纯 Pillow，不依赖 ffmpeg）。

要点：
  - 先用抽样的若干帧算出**全局调色板**，再让每帧向它量化，
    比逐帧自适应调色板压缩率高得多（帧间差异小 → GIF 帧差压缩有效）。
  - 关闭抖动或只用很轻的抖动：深色 UI 上抖动噪点会显著增大体积。
  - 按给定 fps 均匀给时长，循环播放。

用法：
  python make_demo_gif.py --frames /tmp/ardemo/frames --out docs/demo.gif \
      --width 880 --fps 11 --colors 128
"""
from __future__ import annotations

import argparse
import glob
from pathlib import Path

from PIL import Image


def _diff(a, b) -> float:
    """两帧的平均绝对差（缩到小图再算，够用且快）。"""
    from PIL import ImageChops, ImageStat
    s = (48, 30)
    d = ImageChops.difference(a.resize(s), b.resize(s))
    return ImageStat.Stat(d).mean[0]


def _smooth_biggest_cut(frames, extra=4):
    """找到差异最大的一处硬切，插入若干插值帧做交叉淡入淡出。"""
    if len(frames) < 3:
        return frames, -1
    diffs = [_diff(frames[i], frames[i + 1]) for i in range(len(frames) - 1)]
    idx = max(range(len(diffs)), key=lambda i: diffs[i])
    if diffs[idx] < 4.0:               # 本来就很连续，不动
        return frames, -1
    a, b = frames[idx], frames[idx + 1]
    blends = [Image.blend(a, b, (k + 1) / (extra + 1)) for k in range(extra)]
    return frames[:idx + 1] + blends + frames[idx + 1:], idx


def build(frames_dir, out_path, width, fps, colors, dither, skip, smooth):
    files = sorted(glob.glob(str(Path(frames_dir) / "*.jpg")))
    if not files:
        raise SystemExit("make_demo_gif: 没有帧")
    if skip > 1:
        files = files[::skip]

    base = Image.open(files[0]).convert("RGB")
    h = round(base.height * width / base.width)

    # 1) 全局调色板：从均匀抽样的帧里学习
    step = max(1, len(files) // 12)
    sample = [Image.open(f).convert("RGB").resize((width // 2, h // 2),
                                                  Image.LANCZOS)
              for f in files[::step]]
    sheet = Image.new("RGB", (sample[0].width, sample[0].height * len(sample)))
    for i, im in enumerate(sample):
        sheet.paste(im, (0, i * sample[0].height))
    palette = sheet.quantize(colors=colors, method=Image.MEDIANCUT)

    # 2) 逐帧缩放；必要时在最大硬切处插淡入淡出
    rgb = [Image.open(f).convert("RGB").resize((width, h), Image.LANCZOS)
           for f in files]
    cut_at = -1
    if smooth:
        rgb, cut_at = _smooth_biggest_cut(rgb, extra=4)

    d = Image.Dither.FLOYDSTEINBERG if dither else Image.Dither.NONE
    frames = [im.quantize(palette=palette, dither=d) for im in rgb]

    dur = int(round(1000.0 / fps))
    out = Path(out_path)
    out.parent.mkdir(parents=True, exist_ok=True)
    frames[0].save(out, save_all=True, append_images=frames[1:],
                   duration=dur, loop=0, optimize=True, disposal=1)
    return out, len(frames), (width, h), cut_at


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--frames", required=True)
    ap.add_argument("--out", required=True)
    ap.add_argument("--width", type=int, default=880)
    ap.add_argument("--fps", type=float, default=11.0)
    ap.add_argument("--colors", type=int, default=128)
    ap.add_argument("--dither", action="store_true")
    ap.add_argument("--skip", type=int, default=1, help="每 N 帧取 1")
    ap.add_argument("--no-smooth", action="store_true",
                    help="不做硬切处淡入淡出")
    a = ap.parse_args()
    out, n, size, cut = build(a.frames, a.out, a.width, a.fps, a.colors,
                              a.dither, a.skip, not a.no_smooth)
    kb = out.stat().st_size / 1024
    extra = f"  硬切@帧{cut} 已淡入淡出" if cut >= 0 else ""
    print(f"  {n} 帧  {size[0]}x{size[1]}  {a.fps:g}fps  {a.colors}色  "
          f"-> {out}  {kb:.0f} KB{extra}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
