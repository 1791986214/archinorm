#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""用 Chrome DevTools Protocol 的 Page.startScreencast 逐帧录屏，并合成 GIF。

为什么不用 agent-browser 的 record：它需要 ffmpeg 封装 WebM，本机没装。
CDP screencast 直接吐 JPEG 帧，省掉 ffmpeg，Pillow 就能合成 GIF。

用法：
  python cdp_record.py --cdp <ws-url> --js <交互脚本.js> --out <帧目录> --seconds 9
"""
from __future__ import annotations

import argparse
import base64
import json
import threading
import time
from pathlib import Path

import websocket  # websocket-client


class CDP:
    def __init__(self, url: str):
        # suppress_origin：Chrome 会拒绝带 Origin 头的 CDP WebSocket 连接
        # （报 "Rejected an incoming WebSocket connection ... --remote-allow-origins"）
        self.ws = websocket.create_connection(
            url, timeout=30, max_size=64 * 1024 * 1024, suppress_origin=True)
        self._id = 0
        self._lock = threading.Lock()
        self.session_id = None

    def send(self, method, params=None, session=None, wait=True):
        with self._lock:
            self._id += 1
            mid = self._id
            msg = {"id": mid, "method": method, "params": params or {}}
            if session:
                msg["sessionId"] = session
            self.ws.send(json.dumps(msg))
        if not wait:
            return mid
        while True:
            data = json.loads(self.ws.recv())
            if data.get("id") == mid:
                if "error" in data:
                    raise RuntimeError(f"{method} -> {data['error']}")
                return data.get("result", {})

    def attach_page(self, match: str = ""):
        targets = self.send("Target.getTargets")["targetInfos"]
        pages = [t for t in targets if t.get("type") == "page"]
        if match:
            hit = [t for t in pages if match in (t.get("url") or "")]
            if hit:
                pages = hit
        # 排除 chrome:// 内部页，优先真实页面
        real = [t for t in pages if not (t.get("url") or "").startswith("chrome://")]
        if real:
            pages = real
        if not pages:
            raise RuntimeError("没有可用的 page target")
        self.session_id = self.send(
            "Target.attachToTarget",
            {"targetId": pages[0]["targetId"], "flatten": True})["sessionId"]
        return pages[0]


def record(cdp_url, js_path, out_dir, seconds, quality, fps_cap, match=""):
    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)
    for f in out.glob("*.jpg"):
        f.unlink()

    c = CDP(cdp_url)
    tgt = c.attach_page(match)
    print(f"  目标页: {tgt.get('title', '')[:50]}  {tgt.get('url', '')[:70]}")

    c.send("Page.enable", session=c.session_id)
    c.send("Runtime.enable", session=c.session_id)
    c.send("Page.startScreencast",
           {"format": "jpeg", "quality": quality,
            "maxWidth": 1280, "maxHeight": 800, "everyNthFrame": 1},
           session=c.session_id)
    print("  screencast 已启动")

    # 触发交互（不等待 promise，页面里自己异步推进）
    js = Path(js_path).read_text(encoding="utf-8")
    c.send("Runtime.evaluate",
           {"expression": js, "awaitPromise": False, "returnByValue": False},
           session=c.session_id, wait=False)
    print("  交互脚本已注入，开始收帧")

    frames = []
    t0 = time.time()
    last = 0.0
    min_gap = 1.0 / fps_cap
    c.ws.settimeout(2.0)
    while time.time() - t0 < seconds:
        try:
            raw = c.ws.recv()
        except Exception:
            continue
        try:
            msg = json.loads(raw)
        except Exception:
            continue
        if msg.get("method") != "Page.screencastFrame":
            continue
        p = msg["params"]
        ack_id = p.get("sessionId")
        now = time.time() - t0
        if ack_id is not None:
            c.send("Page.screencastFrameAck", {"sessionId": ack_id},
                   session=c.session_id, wait=False)
        if now - last < min_gap:
            continue
        last = now
        idx = len(frames)
        pth = out / f"f{idx:04d}.jpg"
        pth.write_bytes(base64.b64decode(p["data"]))
        frames.append((now, pth))

    c.send("Page.stopScreencast", session=c.session_id)
    c.ws.close()
    print(f"  收到 {len(frames)} 帧，时长 {frames[-1][0]:.2f}s" if frames else "  没收到帧")
    return frames


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--cdp", required=True)
    ap.add_argument("--js", required=True)
    ap.add_argument("--out", required=True)
    ap.add_argument("--seconds", type=float, default=9.0)
    ap.add_argument("--quality", type=int, default=82)
    ap.add_argument("--fps-cap", type=float, default=25.0)
    ap.add_argument("--match", default="", help="按 URL 子串挑选目标页")
    a = ap.parse_args()
    record(a.cdp, a.js, a.out, a.seconds, a.quality, a.fps_cap, a.match)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
