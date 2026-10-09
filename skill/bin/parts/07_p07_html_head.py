
# --------------------------------------------------------------------------
# 渲染（一）：设计令牌 + 骨架
#
# 视觉语言吸收自 archify（github.com/tt-a1i/archify, MIT）的 DESIGN.md：
#   "The Evidence Console" —— 深色证据控制台、全等宽字体、七个语义色、
#   扁平克制、状态过渡 140-200ms。
# 并遵守其明确禁令：不用 dense dashboard shell、不用无止境的同构卡片网格、
# 不用装饰性玻璃与渐变文字。
# --------------------------------------------------------------------------

HTML_HEAD = r"""<!DOCTYPE html>
<html lang="zh-CN" data-theme="dark">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>__TITLE__</title>
<style>
:root{
  --canvas:#020617; --mask:#0F172A; --ink:#FFFFFF; --muted:#94A3B8;
  --dim:#475569; --border:#1E293B;
  --frontend:#22D3EE; --backend:#34D399; --database:#A78BFA;
  --cloud:#FBBF24; --security:#FB7185; --messagebus:#FB923C; --external:#94A3B8;
  --r-precise:.2rem; --r-control:.5rem; --r-panel:1rem; --r-pill:999px;
  --mono:"JetBrains Mono",ui-monospace,SFMono-Regular,Menlo,Consolas,"Courier New",monospace;
  --t-fast:150ms;
}
html[data-theme="light"]{
  --canvas:#F8FAFC; --mask:#FFFFFF; --ink:#0B1220; --muted:#64748B;
  --dim:#94A3B8; --border:#E2E8F0;
  --frontend:#0891B2; --backend:#059669; --database:#7C3AED;
  --cloud:#B45309; --security:#BE123C; --messagebus:#C2410C; --external:#64748B;
}
html[data-theme="blueprint"]{
  --canvas:#0B1B33; --mask:#0F2547; --ink:#EAF2FF; --muted:#8FB0D9;
  --dim:#5B7CA8; --border:#1D3A66;
  --frontend:#7DD3FC; --backend:#86EFAC; --database:#C4B5FD;
  --cloud:#FDE68A; --security:#FDA4AF; --messagebus:#FDBA74; --external:#94A3B8;
  --r-panel:.35rem; --r-control:.2rem;
}
*{box-sizing:border-box}
html,body{height:100%}
body{margin:0;background:var(--canvas);color:var(--ink);
  font:400 .75rem/1.55 var(--mono);-webkit-font-smoothing:antialiased;
  display:flex;flex-direction:column;overflow:hidden}
a{color:var(--frontend);text-decoration:none}
a:hover{text-decoration:underline}
button{font:inherit;color:inherit;background:none;border:0;cursor:pointer}

.topbar{display:flex;align-items:center;gap:14px;padding:10px 16px;
  background:var(--mask);border-bottom:1px solid var(--border);flex:none;min-height:56px}
.brand{font:700 1.0625rem/1.2 var(--mono);letter-spacing:-.025em;white-space:nowrap}
.brand small{display:block;font:400 .625rem/1.35 var(--mono);color:var(--muted);
  letter-spacing:.12em;text-transform:uppercase;margin-top:2px}
.kpis{display:flex;gap:6px;flex-wrap:wrap;margin-left:8px}
.chip{display:inline-flex;align-items:baseline;gap:4px;padding:3px 8px;
  border:1px solid var(--border);border-radius:var(--r-pill);
  font:700 .625rem/1.35 var(--mono);letter-spacing:.06em;color:var(--muted);white-space:nowrap}
.chip b{font-size:.75rem;font-weight:700;color:var(--ink);letter-spacing:0}
.tools{margin-left:auto;display:flex;gap:6px;align-items:center}
.btn{height:32px;padding:0 11px;border:1px solid var(--border);
  border-radius:var(--r-control);background:transparent;color:var(--ink);
  font:400 .6875rem/1 var(--mono);display:inline-flex;align-items:center;gap:6px;
  transition:border-color var(--t-fast),background var(--t-fast)}
.btn:hover{border-color:var(--frontend)}
.btn:focus-visible{outline:2px solid var(--frontend);outline-offset:2px}
.btn[aria-pressed="true"]{border-color:var(--frontend);color:var(--frontend)}
.seg{display:flex;border:1px solid var(--border);border-radius:var(--r-control);overflow:hidden}
.seg .btn{border:0;border-radius:0;height:30px}
.seg .btn+.btn{border-left:1px solid var(--border)}

.stage{flex:1;display:flex;min-height:0;position:relative}
.canvaswrap{flex:1;min-width:0;position:relative;overflow:hidden}
#canvas{display:block;width:100%;height:100%;cursor:grab}
#canvas.dragging{cursor:grabbing}
.empty{position:absolute;inset:0;display:flex;align-items:center;justify-content:center;
  color:var(--dim);font-size:.75rem;pointer-events:none}

.nbox{transition:stroke var(--t-fast),opacity var(--t-fast)}
.nlabel{fill:var(--ink);font:600 .72rem var(--mono);dominant-baseline:middle}
.nid{fill:var(--dim);font:400 .58rem var(--mono);dominant-baseline:middle}
.nmeta{fill:var(--muted);font:700 .55rem var(--mono);letter-spacing:.1em;dominant-baseline:middle}
.grp{fill:none;stroke:var(--border);stroke-width:1;stroke-dasharray:4 4}
.grplabel{fill:var(--dim);font:700 .56rem var(--mono);letter-spacing:.12em}
.sedge{fill:none;stroke:var(--border);stroke-width:1}
.dedge{fill:none;stroke-width:1.4;opacity:.85}
.node{cursor:pointer}
.node:hover .nbox{stroke:var(--frontend)}
.dimmed{opacity:.14}
.hot .nbox{stroke-width:1.6}

/* 阅读导语：来自 renders/<id>.json 的 reading 字段，显示在图上方 */
.reading{position:absolute;left:14px;top:12px;right:14px;padding:7px 11px;
  background:var(--mask);border:1px solid var(--border);
  border-left:3px solid var(--frontend);border-radius:var(--r-control);
  color:var(--muted);font-size:.66rem;line-height:1.5;pointer-events:none;
  transition:opacity var(--t-fast)}
.reading.hidden{display:none}

.legend{position:absolute;left:14px;bottom:14px;display:flex;gap:12px;flex-wrap:wrap;
  padding:8px 11px;background:var(--mask);border:1px solid var(--border);
  border-radius:var(--r-control);max-width:calc(100% - 28px)}
.legend span{display:inline-flex;align-items:center;gap:5px;
  font:700 .56rem/1 var(--mono);letter-spacing:.1em;color:var(--muted)}
.legend i{width:9px;height:9px;border-radius:2px;display:inline-block}

.panel{width:392px;flex:none;background:var(--mask);border-left:1px solid var(--border);
  display:flex;flex-direction:column;min-height:0}
.panel.hidden{display:none}
.phead{padding:14px 16px 12px;border-bottom:1px solid var(--border);flex:none}
.phead h2{margin:0;font:600 .875rem/1.4 var(--mono);word-break:break-word}
.phead .en{color:var(--muted);font-size:.68rem;margin-top:2px}
.phead .id{color:var(--dim);font-size:.6rem;margin-top:6px;word-break:break-all}
.ptabs{display:flex;border-bottom:1px solid var(--border);flex:none}
.ptabs .btn{flex:1;border:0;border-radius:0;height:34px;justify-content:center;
  color:var(--muted);font-size:.64rem;letter-spacing:.06em}
.ptabs .btn[aria-pressed="true"]{color:var(--frontend);
  box-shadow:inset 0 -2px 0 var(--frontend)}
.pbody{flex:1;overflow:auto;padding:14px 16px 20px}
.pbody table{width:100%;border-collapse:collapse;font-size:.66rem}
.pbody th{text-align:left;font:700 .56rem var(--mono);letter-spacing:.1em;
  color:var(--dim);padding:5px 6px;border-bottom:1px solid var(--border)}
.pbody td{padding:6px;border-bottom:1px solid var(--border);vertical-align:top;
  word-break:break-word}
.pbody td.k{color:var(--muted);width:92px}
.pill{display:inline-block;padding:1px 6px;border-radius:var(--r-pill);
  border:1px solid currentColor;font:700 .54rem/1.5 var(--mono);letter-spacing:.06em}
.pill.planned{color:var(--cloud)}
.pill.deprecated{color:var(--external)}
.note{color:var(--dim);font-size:.64rem;padding:8px 0}
.desc{color:var(--muted);font-size:.68rem;line-height:1.6;margin:0 0 8px}
.hint{color:var(--dim);font-size:.6rem;margin-top:4px}
.edgebar{display:flex;gap:6px;margin:10px 0 4px;flex-wrap:wrap}
.edgebar .btn{height:26px;font-size:.6rem}
footer{flex:none;padding:7px 16px;border-top:1px solid var(--border);
  color:var(--dim);font-size:.58rem;display:flex;gap:14px;flex-wrap:wrap}
@media (prefers-reduced-motion: reduce){*{transition:none!important}}
@media (max-width:900px){.panel{position:absolute;right:0;top:0;bottom:0;width:86%;
  box-shadow:0 18px 48px rgba(0,0,0,.45)}}
</style>
</head>
<body>
<header class="topbar">
  <div class="brand">
    <span id="ttl">__TITLE__</span>
    <small id="sub"></small>
  </div>
  <div class="kpis" id="kpis"></div>
  <div class="tools">
    <div class="seg" id="themebar">
      <button class="btn" data-theme="dark" aria-pressed="true">暗色</button>
      <button class="btn" data-theme="light" aria-pressed="false">亮色</button>
      <button class="btn" data-theme="blueprint" aria-pressed="false">蓝图</button>
    </div>
    <div class="seg" id="modebar">
      <button class="btn" data-mode="scope" aria-pressed="true">当前层</button>
      <button class="btn" data-mode="all" aria-pressed="false">全图</button>
    </div>
    <button class="btn" id="btn-fit">复位</button>
  </div>
</header>

<div class="stage">
  <div class="canvaswrap">
    <svg id="canvas" xmlns="http://www.w3.org/2000/svg"></svg>
    <div class="empty" id="empty" style="display:none">该模块没有可绘制的子结构</div>
    <div class="reading hidden" id="reading"></div>
    <div class="legend" id="legend"></div>
  </div>
  <aside class="panel hidden" id="panel">
    <div class="phead">
      <h2 id="p-title">—</h2>
      <div class="en" id="p-en"></div>
      <div class="id" id="p-id"></div>
    </div>
    <div class="ptabs" id="ptabs">
      <button class="btn" data-tab="overview" aria-pressed="true">概览</button>
      <button class="btn" data-tab="apis" aria-pressed="false">接口</button>
      <button class="btn" data-tab="edges" aria-pressed="false">依赖</button>
      <button class="btn" data-tab="meta" aria-pressed="false">元数据</button>
    </div>
    <div class="pbody" id="p-body"></div>
  </aside>
</div>
<footer id="ft"></footer>
"""
