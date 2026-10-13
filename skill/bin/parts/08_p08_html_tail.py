import sys

# --------------------------------------------------------------------------
# 渲染（二）：图画布 + 面板 + 交互
#
# 画布是"真图"而不是卡片网格：按层级分列的节点链路图，
# 结构边（父子）细灰，依赖边（deps）按 kind 语义着色，可平移/缩放/下钻。
# --------------------------------------------------------------------------

# --------------------------------------------------------------------------
# 增强层样式（2026-10-12）：与 normify.html 视觉/功能对齐
#
#   ① P0 基础动效（边流动 + 节点脉冲 + 无障碍降级）
#   ② 自研三套动效（Apple Spring / OpenAI Glow / Apple Depth）
#   ③ P2 形制（卡片节点渐变 + 泳道带）
#   ④ P3 三套配色（signal / blueprint / ember）
#   ⑤ P8 archify 原版复刻（错峰流动 + 双峰脉冲 + 斜向柔光）
#   ⑥ P7 修复：配色预设 × 亮色主题 冲突
#
# 关键约定（动手前必读）：
#   · 本段是 Python 原始字符串（r"""…"""），正则/转义写「单反斜杠」——
#     JS 里要 \s 就在这里写 \s，写 \\s 反而会把两个反斜杠原样吐进 HTML。
#   · data-preset / data-motion 挂在 <html> 上（不是 body）——
#     因为引擎用 getComputedStyle(document.documentElement) 读设计令牌，
#     挂在 body 上 JS 读不到（CSS 能继承，JS 不能）。
#   · 配色选择器与原生 html[data-theme] 同为 (0,1,1)，本段在其后 ⇒ 会盖掉
#     亮色主题，故 P7 必须补 (0,2,1) 的「亮色 × 预设」组合规则。
#   · 层次一律用「描边 + 渐变」表达，不用常驻 SVG 滤镜（每帧重算滤镜是卡顿主因）。
# --------------------------------------------------------------------------

HTML_ENHANCE_CSS = r"""<style>
/* ===== P3 三套配色预设（挂在 <html> 上，便于 JS 直接读取令牌）===== */
/* signal = 原生默认：刻意不覆盖任何令牌，保证「不选预设」时视觉零变化 */
html[data-preset="blueprint"]{
  --canvas:#08142A; --mask:#0D1F3D; --ink:#E9F2FF; --muted:#8FB0D4;
  --dim:#4F6E96; --border:#1D3A63;
  --frontend:#4DA3FF; --backend:#7DD3FC; --database:#A78BFA;
  --cloud:#FBBF24; --security:#FB7185; --messagebus:#FB923C; --external:#94A3B8;
}
html[data-preset="ember"]{
  --canvas:#191110; --mask:#241816; --ink:#F8ECE6; --muted:#C2A396;
  --dim:#7A5C4E; --border:#4A3128;
  --frontend:#FF8A4C; --backend:#FFD166; --database:#E8A87C;
  --cloud:#FBBF24; --security:#F87171; --messagebus:#FB923C; --external:#A8968C;
}

/* ===== P7 修复：配色预设 × 亮色主题 冲突 =====
   根因：html[data-preset] 与 html[data-theme] 同为 specificity(0,1,1)，
   增强层样式排在原生 <style> 之后 ⇒ 预设会盖掉亮色主题的浅底。
   对策：补一层 (0,2,1) 的「亮色 × 预设」组合变量，稳赢。 */
html[data-theme="light"][data-preset="signal"]{
  --canvas:#F8FAFC; --mask:#FFFFFF; --ink:#0B1220; --muted:#64748B;
  --dim:#94A3B8; --border:#E2E8F0;
  --frontend:#0891B2; --backend:#059669; --database:#7C3AED;
  --cloud:#B45309; --security:#BE123C; --messagebus:#C2410C; --external:#64748B;
}
html[data-theme="light"][data-preset="blueprint"]{
  --canvas:#F2F7FF; --mask:#FFFFFF; --ink:#0F2544; --muted:#5A7396;
  --dim:#8CA6C4; --border:#C8DCF5;
  --frontend:#1F6FD0; --backend:#0F8F6A; --database:#7C3AED;
  --cloud:#B45309; --security:#BE123C; --messagebus:#C2410C; --external:#64748B;
}
html[data-theme="light"][data-preset="ember"]{
  --canvas:#FDF6F2; --mask:#FFFFFF; --ink:#3A2318; --muted:#8A6A58;
  --dim:#B39B8C; --border:#E8D2C4;
  --frontend:#D9662E; --backend:#B8801F; --database:#9B5DE5;
  --cloud:#B45309; --security:#BE123C; --messagebus:#C2410C; --external:#8A6A58;
}

/* ===== P2 形制：卡片节点 + 泳道带 ===== */
/* 卡片感来自「圆角加大 + 上下渐变 + 描边」，不加常驻投影（避开滤镜卡顿） */
.nbox{fill:url(#nmCardGrad)}
.nbox.leaf{fill:url(#nmCardLeafGrad)}
/* 泳道带：分组框 + 顶部标题带 + 左侧强调色条 */
.grp{fill:rgba(255,255,255,.022);stroke:var(--border);stroke-dasharray:5 5}
html[data-theme="light"] .grp{fill:rgba(15,23,42,.016)}
.group-bar{fill:var(--frontend);opacity:.085}
.group-rail{fill:var(--frontend);opacity:.5}
.grplabel{fill:var(--frontend);opacity:.92;letter-spacing:.12em;text-transform:uppercase}
html[data-preset="blueprint"] .grp{stroke-dasharray:2 4}
html[data-preset="ember"] .grp{fill:rgba(255,138,76,.03)}
html[data-preset="ember"] .grplabel{font-weight:700}

/* ===== P0 基础动效：边流动 + 节点脉冲 + 无障碍 ===== */
@keyframes nm-flow{to{stroke-dashoffset:-26}}
@keyframes nm-pulse{0%,100%{stroke-width:1.2}50%{stroke-width:2.4}}
/* 边流动层：叠在依赖边之上的一条流动光带（不参与交互、无箭头） */
.edge-flow{
  fill:none;stroke:var(--frontend);stroke-width:2;stroke-linecap:round;
  stroke-dasharray:6 20;opacity:.45;pointer-events:none;
  animation:nm-flow 1.6s linear infinite;
  will-change:stroke-dashoffset,opacity;
}
/* 节点脉冲：用描边呼吸代替发光滤镜（GPU 友好） */
.node:hover .nbox{animation:nm-pulse 2.4s ease-in-out infinite}
@media (prefers-reduced-motion:reduce){
  .edge-flow{animation:none!important;opacity:0!important}
  .node:hover .nbox{animation:none!important}
}

/* ===== 自研三套动效：Apple Spring / OpenAI Glow / Apple Depth ===== */
.nbox,.node,.node-g{transform-box:fill-box;transform-origin:center}
@keyframes nm-rise{from{opacity:0;transform:translateY(9px) scale(.985)}to{opacity:1;transform:none}}
@keyframes nm-breathe{0%,100%{opacity:.2;stroke-width:1.4}50%{opacity:.58;stroke-width:2.6}}
@keyframes nm-run{to{stroke-dashoffset:-196}}
@keyframes nm-oai-glow{0%,100%{stroke-width:1.2;opacity:.9}50%{stroke-width:2.6;opacity:1}}
@keyframes nm-draw{from{stroke-dashoffset:1600;opacity:.18}to{stroke-dashoffset:0;opacity:.5}}

/* 预设 A · Apple Spring：回弹物理、克制
   注意：边动效一律挂 .edge-flow 覆盖层，不挂原边 —— 原边可能被样式隐藏，
   而 display:none 的元素不跑 CSS 动画。 */
html[data-motion="spring"] .edge-flow{
  stroke-dasharray:none;animation:nm-breathe 3.2s ease-in-out infinite;
}
html[data-motion="spring"] .node{animation:nm-rise .52s cubic-bezier(.34,1.56,.64,1) backwards}
html[data-motion="spring"] .node .nbox{
  transition:transform .38s cubic-bezier(.34,1.56,.64,1),fill .3s ease,stroke .3s ease;
}
html[data-motion="spring"] .node:hover .nbox{
  transform:scale(1.035) translateY(-1.5px);animation:none;
}

/* 预设 B · OpenAI Glow：跑光点 + 逐条绘制 + 描边发光 */
html[data-motion="glow"] .edge-flow{
  stroke-dasharray:2 96;stroke-width:2.6;opacity:.92;
  animation:nm-run 2.6s linear infinite;
}
html[data-motion="glow"] .dedge{opacity:.5;animation:nm-draw 1.1s ease-out backwards}
html[data-motion="glow"] .node:hover .nbox{animation:nm-oai-glow 2.6s ease-in-out infinite}

/* 预设 C · Apple Depth：玻璃纵深 + 抬升 */
html[data-motion="depth"] .node{
  animation:nm-rise .6s cubic-bezier(.22,.61,.36,1) backwards;
  transition:transform .42s cubic-bezier(.22,.61,.36,1);
}
html[data-motion="depth"] .node:hover{transform:translateY(-3px)}
html[data-motion="depth"] .node:hover .nbox{
  fill:var(--mask);stroke:var(--frontend);stroke-width:2.3;
}
html[data-motion="depth"] .edge-flow{
  stroke-dasharray:10 26;stroke-width:2.2;opacity:.5;animation-duration:2.2s;
}

/* ===== P8 archify 原版复刻：错峰流动 + 双峰脉冲 + 斜向柔光 =====
   严格对齐 archify 关键参数：dasharray 10 8 / dashoffset 54 / 1.75s linear /
   节点双峰脉冲(18%,36%) / 逐元素 --step*160ms 错峰 / 斜向柔光 .035 */
@keyframes nm-archify-edge{to{stroke-dashoffset:0}}
@keyframes nm-archify-node{
  0%,72%,100%{stroke-width:1.2}
  18%,36%{stroke-width:2.6;filter:drop-shadow(0 0 8px var(--frontend))}
}
@keyframes nm-signal-scan{
  0%,18%{transform:translateX(-70%)}
  70%,100%{transform:translateX(70%)}
}
html[data-motion="archify"] .edge-flow{
  stroke-dasharray:10 8;stroke-dashoffset:54;stroke-linecap:round;opacity:.85;
  animation:nm-archify-edge 1.75s linear infinite;
  animation-delay:calc(var(--step,0) * 160ms);
}
html[data-motion="archify"] .dedge{opacity:.62}
html[data-motion="archify"] .node .nbox{
  animation:nm-archify-node 3.1s ease-in-out infinite;
  animation-delay:calc(var(--step,0) * 160ms);
}
/* 忠于 archify 原版：整块画布上一道极淡的斜向柔光带，是「氛围」而非「特效」 */
html[data-motion="archify"] .canvaswrap,
html[data-motion="scan"] .canvaswrap{position:relative;overflow:hidden}
html[data-motion="archify"] .canvaswrap::before,
html[data-motion="scan"] .canvaswrap::before{
  content:"";position:absolute;inset:0;z-index:3;pointer-events:none;
  background:linear-gradient(115deg,transparent 28%,rgba(103,232,249,.035) 48%,transparent 68%);
  transform:translateX(-70%);
  animation:nm-signal-scan 6s ease-in-out infinite;
}
html[data-motion="scan"] .edge-flow{animation:none;opacity:.4}

/* 无障碍：任一动效预设下统一降级 */
@media (prefers-reduced-motion:reduce){
  .edge-flow,.dedge,.node,.node .nbox{
    animation:none!important;transition:none!important;transform:none!important;
  }
  html[data-motion="archify"] .canvaswrap::before,
  html[data-motion="scan"] .canvaswrap::before{animation:none!important}
}

/* ===== 工具栏：动效 / 配色 / 导出（P4 切换按钮 + P1 五种导出）===== */
.export-wrap{position:relative;display:inline-block}
.export-menu{
  position:absolute;right:0;top:calc(100% + 6px);z-index:60;
  background:var(--mask);border:1px solid var(--border);
  border-radius:var(--r-control);padding:4px;min-width:178px;
  box-shadow:0 10px 28px rgba(0,0,0,.45);
}
.export-menu[hidden]{display:none}
.export-menu button{
  display:block;width:100%;text-align:left;padding:7px 10px;
  background:transparent;border:0;border-radius:var(--r-control);
  color:var(--ink);font:400 .68rem/1.45 var(--mono);cursor:pointer;
}
.export-menu button:hover{background:var(--canvas)}
.export-menu button[disabled]{opacity:.38;cursor:not-allowed}
.export-menu button[disabled]:hover{background:transparent}
.export-menu button.on{color:var(--frontend)}
.export-sep{height:1px;margin:4px 6px;background:var(--border)}
</style>
"""

HTML_TAIL = HTML_ENHANCE_CSS + r"""<script id="payload" type="application/json">__TREE_JSON__</script>
<script>
(function(){
  var DATA = JSON.parse(document.getElementById('payload').textContent);
  var M = DATA.modules || {}, L = DATA.layouts || {};
  var PAL = ['frontend','backend','database','cloud','security','messagebus','external'];

  // —— 增强层初始化（2026-10-12）——
  // 配色 / 动效预设必须在首次 render() 之前挂上，否则第一帧取到的是默认令牌。
  // 挂在 <html> 上而非 <body>：引擎用 getComputedStyle(documentElement) 读令牌。
  // URL 参数：?preset=signal|blueprint|ember  ?motion=spring|glow|depth|archify|scan
  (function nmInitPrefs(){
    try {
      var q = new URLSearchParams(location.search);
      document.documentElement.setAttribute('data-preset', q.get('preset') || 'signal');
      var mv = q.get('motion');
      if (mv) document.documentElement.setAttribute('data-motion', mv);
    } catch (e) {
      document.documentElement.setAttribute('data-preset', 'signal');
    }
  })();

  var W = 198, H = 50, GAPY = 72, COLW = 268, PAD = 28;
  var cur = location.hash.indexOf('#module=') === 0
    ? decodeURIComponent(location.hash.slice(8)) : (DATA.trees[0] || '');
  if (!M[cur]) cur = DATA.trees[0] || '';
  var mode = 'scope', sel = null, tab = 'overview';
  var view = {x:0, y:0, k:1};
  var collapsed = {};

  var svg = document.getElementById('canvas');
  var NS = 'http://www.w3.org/2000/svg';

  function el(tag, attrs, text){
    var n = document.createElementNS(NS, tag);
    for (var k in attrs) if (attrs[k] !== null && attrs[k] !== undefined) {
      n.setAttribute(k, attrs[k]);
    }
    if (text !== undefined && text !== null) n.textContent = text;
    return n;
  }
  function clear(n){ while (n.firstChild) n.removeChild(n.firstChild); }
  function kids(id){ return (M[id] && M[id].children) || []; }
  function bi(o){ return (o && (o.zh || o.en)) || ''; }
  function v(name){ return getComputedStyle(document.documentElement)
      .getPropertyValue('--' + name).trim(); }
  function esc(s){ return String(s == null ? '' : s).replace(/[&<>"]/g, function(c){
    return {'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;'}[c]; }); }
  function trunc(s, n){ s = String(s == null ? '' : s);
    return s.length > n ? s.slice(0, n - 1) + '\u2026' : s; }

  function semOf(m){
    if (m.state === 'planned') return 'cloud';
    if (m.state === 'deprecated') return 'external';
    if (m.is_leaf){
      var ps = (m.apis || []).map(function(a){ return a.protocol; });
      if (ps.indexOf('kafka') >= 0 || ps.indexOf('amqp') >= 0) return 'messagebus';
      if (ps.indexOf('mysql') >= 0 || ps.indexOf('redis') >= 0
          || ps.indexOf('file') >= 0) return 'database';
      if (ps.indexOf('http') >= 0 || ps.indexOf('ws') >= 0
          || ps.indexOf('graphql') >= 0) return 'frontend';
      if (ps.indexOf('rpc') >= 0 || ps.indexOf('grpc') >= 0) return 'backend';
      return 'external';
    }
    return null;
  }
  function edgeColor(kind){
    return kind === 'call' ? 'backend' : kind === 'event' ? 'messagebus'
         : kind === 'dataflow' ? 'database' : 'external';
  }

  // —— 渲染数据（renders/<id>.json）消费 ——

  function layOf(id){ return L[id] || {}; }

  // order：同级阅读顺序（生产者到消费者）。列出的排前、按给定次序；未列出的保持原树序追加在后。
  function orderedKids(id){
    var ks = kids(id).slice();
    var o = layOf(id).order;
    if (!o || !o.length) return ks;
    var idx = {};
    o.forEach(function(x, i){ idx[x] = i; });
    return ks.map(function(k, i){
      return {k: k, o: (idx[k] === undefined ? o.length + i : idx[k])};
    }).sort(function(a, b){ return a.o - b.o; }).map(function(x){ return x.k; });
  }

  // edge_hints：给指定的一条边定车道或线型
  function hintFor(a, b, kind){
    var hs = layOf(cur).edge_hints;
    if (!hs || !hs.length) return null;
    for (var i = 0; i < hs.length; i++){
      var h = hs[i];
      if (h.from === a && h.to === b && (!h.kind || h.kind === kind)) return h;
    }
    return null;
  }

  function buildScope(){
    var depthLimit = mode === 'all' ? 2 : 1;
    var start = mode === 'all' ? (DATA.trees[0] || cur) : cur;
    var nodes = [], edges = [], order = {};
    function walk(id, d){
      if (!M[id] || d > depthLimit) return;
      order[id] = nodes.length;
      nodes.push({id: id, d: d});
      var ks = orderedKids(id);            // ← 按 renders 的 order 排
      for (var i = 0; i < ks.length; i++){
        if (d < depthLimit){
          edges.push({t:'s', a:id, b:ks[i]});
          walk(ks[i], d + 1);
        }
      }
    }
    walk(start, 0);
    var vis = {}; nodes.forEach(function(n){ vis[n.id] = 1; });
    nodes.forEach(function(n){
      (M[n.id].deps || []).forEach(function(d){
        if (vis[d.to]) edges.push({t:'d', a:n.id, b:d.to, kind:d.kind,
                                   label:bi(d.label)});
      });
    });
    return {nodes:nodes, edges:edges, order:order, start:start};
  }

  function layout(sc){
    var pos = {}, ymap = {}, slot = 0;
    (function assign(id, d){
      var ks = orderedKids(id).filter(function(c){ return sc.order[c] !== undefined; });
      if (ks.length && d < 3){
        ks.forEach(function(c){ assign(c, d + 1); });
        var cy = ks.map(function(c){ return ymap[c]; });
        ymap[id] = (Math.min.apply(null, cy) + Math.max.apply(null, cy)) / 2;
      } else {
        ymap[id] = PAD + slot * GAPY + H / 2;
        slot++;
      }
    })(sc.start, 0);

    var maxD = 0;
    sc.nodes.forEach(function(n){
      maxD = Math.max(maxD, n.d);
      pos[n.id] = {x: PAD + n.d * COLW, y: ymap[n.id] - H / 2, w: W, h: H};
    });
    return {pos: pos, w: PAD * 2 + (maxD + 1) * COLW - (COLW - W),
            h: PAD * 2 + Math.max(1, slot) * GAPY};
  }

  function render(){
    clear(svg);
    var sc = buildScope();
    if (!sc.nodes.length){
      document.getElementById('empty').style.display = 'flex';
      return;
    }
    document.getElementById('empty').style.display = 'none';
    var lay = layout(sc), pos = lay.pos;

    var root = el('g', {id:'world'});
    svg.appendChild(root);
    var gGrp = el('g'), gEdge = el('g'), gNode = el('g');
    root.appendChild(gGrp); root.appendChild(gEdge); root.appendChild(gNode);

    var layCur = layOf(cur);

    // —— 分组框：renders 的 mode=groups + groups（画在节点之下）——
    if (layCur.mode === 'groups' && layCur.groups && layCur.groups.length){
      layCur.groups.forEach(function(g){
        var mem = (g.children || []).filter(function(c){ return pos[c]; });
        if (!mem.length) return;
        var x1 = Infinity, y1 = Infinity, x2 = -Infinity, y2 = -Infinity;
        mem.forEach(function(c){
          var p = pos[c];
          x1 = Math.min(x1, p.x);       y1 = Math.min(y1, p.y);
          x2 = Math.max(x2, p.x + p.w); y2 = Math.max(y2, p.y + p.h);
        });
        var pad = 11, head = 15;
        var gx = x1 - pad, gy = y1 - pad - head;
        var gw = (x2 - x1) + pad * 2, gh = (y2 - y1) + pad * 2 + head;
        gGrp.appendChild(el('rect', {x: gx, y: gy, width: gw, height: gh,
          rx: 13, 'class': 'grp'}));
        // P2 泳道带：顶部标题带 + 左侧强调色条（画在节点之下、分组框之上）
        gGrp.appendChild(el('rect', {x: gx, y: gy, width: gw, height: head,
          rx: 13, 'class': 'group-bar'}));
        gGrp.appendChild(el('rect', {x: gx, y: gy + 4, width: 3,
          height: Math.max(10, gh - 10), rx: 1.5, 'class': 'group-rail'}));
        gGrp.appendChild(el('text', {x: gx + 11, y: y1 - pad - 4,
          'class': 'grplabel'}, trunc(bi(g.title) || g.id, 24)));
      });
    }

    // —— 阅读导语：renders 的 reading，显示在图上方 ——
    var rdEl = document.getElementById('reading');
    var rd = layCur.reading;
    if (rd && (rd.zh || rd.en)){
      rdEl.textContent = rd.zh || rd.en;
      rdEl.classList.remove('hidden');
    } else {
      rdEl.classList.add('hidden');
    }

    var nb = {};
    if (sel){
      nb[sel] = 1;
      (M[sel].deps || []).forEach(function(d){ nb[d.to] = 1; });
      (M[sel].incoming || []).forEach(function(d){ nb[d.from] = 1; });
    }

    var depIdx = 0;
    sc.edges.forEach(function(e){
      var a = pos[e.a], b = pos[e.b];
      if (!a || !b) return;
      var x1 = a.x + a.w, y1 = a.y + a.h / 2, x2 = b.x, y2 = b.y + b.h / 2;
      if (e.t === 's'){
        var mx = (x1 + x2) / 2;
        gEdge.appendChild(el('path', {d: 'M' + x1 + ',' + y1 + ' L' + mx + ',' + y1
                                       + ' L' + mx + ',' + y2 + ' L' + x2 + ',' + y2,
                                     'class': 'sedge'}));
        return;
      }
      var h = hintFor(e.a, e.b, e.kind);
      var lane = ((depIdx++ % 3) - 1) * 7;
      if (h && h.lane !== undefined) lane = (h.lane - 2) * 12;   // lane 2..4 → 0/12/24
      y1 += lane; y2 += lane;
      var dx = Math.max(34, Math.abs(x2 - x1) * 0.38);
      var c = edgeColor(e.kind);
      var dash = (h && h.style)
        ? (h.style === 'solid' ? null : h.style)
        : (e.kind === 'event' ? '5 4' : e.kind === 'reference' ? '2 4' : null);
      var p = el('path', {
        d: 'M' + x1 + ',' + y1 + ' C' + (x1 + dx) + ',' + y1 + ' '
           + (x2 - dx) + ',' + y2 + ' ' + x2 + ',' + y2,
        'class': 'dedge', stroke: v(c), 'marker-end': 'url(#ah-' + c + ')',
        'stroke-dasharray': dash});
      if (sel && !(e.a === sel || e.b === sel)) p.setAttribute('opacity', '0.1');
      gEdge.appendChild(p);
      // P0 动效：与依赖边同 d 的流动覆盖层（只负责动画，不参与交互、不带箭头）。
      // 挂覆盖层而非原边 —— 原边可能被选中态调成 opacity .1，动画仍需照跑。
      gEdge.appendChild(el('path', {d: p.getAttribute('d'), 'class': 'edge-flow'}));
    });

    sc.nodes.forEach(function(n){
      var m = M[n.id], p = pos[n.id], c = semOf(m);
      var ks = kids(n.id);
      var g = el('g', {'class': 'node' + (sel === n.id ? ' sel' : '')
                             + (sel && !nb[n.id] ? ' dimmed' : '')
                             + (sel && nb[n.id] && n.id !== sel ? ' hot' : ''),
                       'data-id': n.id});
      g.appendChild(el('rect', {x:p.x, y:p.y, width:p.w, height:p.h, rx:13,
        'class':'nbox' + (m.is_leaf ? ' leaf' : ''),
        fill: m.is_leaf ? 'url(#nmCardLeafGrad)' : 'url(#nmCardGrad)',
        stroke: c ? v(c) : v('dim'),
        'stroke-width': c ? 1.2 : 1}));
      if (c) g.appendChild(el('rect', {x:p.x, y:p.y, width:3, height:p.h, rx:1.5,
        fill: v(c)}));
      g.appendChild(el('circle', {cx: p.x + 16, cy: p.y + p.h / 2, r: 4,
        'class':'ndot', fill: c ? v(c) : v('dim')}));
      g.appendChild(el('text', {x: p.x + 27, y: p.y + p.h / 2 - 6,
        'class':'nlabel'}, trunc(bi(m.name) || n.id, 16)));
      g.appendChild(el('text', {x: p.x + 27, y: p.y + p.h / 2 + 11,
        'class':'nid'}, trunc(n.id, 25)));
      var meta = ks.length ? (ks.length + ' SUB') : ((m.apis || []).length + ' API');
      if ((m.deps || []).length) meta += '  ' + m.deps.length + '\u2192';
      g.appendChild(el('text', {x: p.x + p.w - 9, y: p.y + p.h / 2,
        'class':'nmeta', 'text-anchor':'end'}, meta));
      if (ks.length){
        g.appendChild(el('text', {x: p.x + p.w - 9, y: p.y + 10,
          'class':'nmeta', 'text-anchor':'end'}, collapsed[n.id] ? '\u25b8' : '\u25be'));
      }
      gNode.appendChild(g);
    });

    var defs = el('defs');
    // P2 卡片渐变：上浅下深，营造卡片浮起感。
    // 用 JS 直接读令牌写 stop-color（而非 CSS 覆盖）——
    // 这样导出 SVG 时颜色已内联，不依赖样式表，且随主题/预设实时变化。
    [['nmCardGrad',    v('mask') || '#0F172A', v('canvas') || '#020617'],
     ['nmCardLeafGrad', v('mask') || '#0F172A', v('canvas') || '#020617']
    ].forEach(function(pair){
      var grad = el('linearGradient', {id: pair[0], x1:'0', y1:'0', x2:'0', y2:'1'});
      grad.appendChild(el('stop', {offset:'0%',   'stop-color': pair[1]}));
      grad.appendChild(el('stop', {offset:'100%', 'stop-color': pair[2]}));
      defs.appendChild(grad);
    });
    PAL.forEach(function(c){
      var mk = el('marker', {id:'ah-' + c, viewBox:'0 0 10 10', refX:'9', refY:'5',
        markerWidth:'6', markerHeight:'6', orient:'auto-start-reverse'});
      mk.appendChild(el('path', {d:'M1 1L9 5L1 9', fill:'none', stroke: v(c),
        'stroke-width':'1.6', 'stroke-linecap':'round', 'stroke-linejoin':'round'}));
      defs.appendChild(mk);
    });
    root.insertBefore(defs, root.firstChild);

    svg.setAttribute('viewBox', '0 0 ' + (svg.clientWidth || 900) + ' '
                                            + (svg.clientHeight || 600));
    // P8：给流动层与节点分配 --step（archify 用逐元素 --step*160ms 做错峰延迟）
    ;(function nmAssignSteps(){
      var flows = svg.querySelectorAll('.edge-flow');
      for (var i = 0; i < flows.length; i++){
        flows[i].style.setProperty('--step', String(i));
      }
      for (var j = 0; j < gNode.children.length; j++){
        gNode.children[j].style.setProperty('--step', String(j));
      }
    })();
    applyView();
    drawLegend();
  }

  function applyView(){
    var w = document.getElementById('world');
    if (w) w.setAttribute('transform',
      'translate(' + view.x + ',' + view.y + ') scale(' + view.k + ')');
  }

  function fit(){
    var sc = buildScope();
    if (!sc.nodes.length) return;
    var lay = layout(sc);
    var cw = svg.clientWidth || 900, ch = svg.clientHeight || 600;
    var k = Math.min((cw - 26) / Math.max(1, lay.w), (ch - 26) / Math.max(1, lay.h), 1.1);
    view.k = Math.max(k, 0.26);
    view.x = (cw - lay.w * view.k) / 2;
    view.y = (ch - lay.h * view.k) / 2;
    applyView();
  }

  var LEGEND = [['frontend','HTTP / WS'], ['backend','RPC / CALL'],
                ['database','STORE'], ['messagebus','EVENT / MQ'],
                ['cloud','PLANNED'], ['external','OTHER']];
  function drawLegend(){
    var used = {};
    Object.keys(M).forEach(function(k){ var c = semOf(M[k]); if (c) used[c] = 1; });
    var html = '';
    LEGEND.forEach(function(p){
      if (used[p[0]]) html += '<span><i style="background:' + v(p[0]) + '"></i>'
                            + p[1] + '</span>';
    });
    document.getElementById('legend').innerHTML = html || '<span>纯结构视图</span>';
  }

  function apiKey(a){
    return (a.protocol === 'http' && a.method)
      ? a.method + ' ' + a.path : a.protocol + ':' + a.path;
  }
  function paintPanel(){
    var pn = document.getElementById('panel');
    if (!sel || !M[sel]){ pn.classList.add('hidden'); return; }
    pn.classList.remove('hidden');
    var m = M[sel];
    document.getElementById('p-title').textContent = bi(m.name) || sel;
    document.getElementById('p-en').textContent = (m.name && m.name.en) || '';
    document.getElementById('p-id').textContent = sel;
    var h = '';
    if (tab === 'overview'){
      h += '<p class="desc">' + esc((m.description || {}).zh || '') + '</p>';
      if ((m.description || {}).en)
        h += '<p class="desc" style="color:var(--dim)">' + esc(m.description.en) + '</p>';
      var st = (m.state && m.state !== 'active')
        ? '<span class="pill ' + m.state + '">' + m.state + '</span>' : 'ACTIVE';
      h += '<table>'
        + '<tr><td class="k">状态</td><td>' + st + '</td></tr>'
        + '<tr><td class="k">层级</td><td>' + m.depth + '　'
        + (m.is_leaf ? '叶子' : '容器 · ' + kids(sel).length + ' 子模块') + '</td></tr>'
        + '<tr><td class="k">接口</td><td>' + (m.apis || []).length + ' 条</td></tr>'
        + '<tr><td class="k">出向依赖</td><td>' + (m.deps || []).length + ' 条</td></tr>'
        + '<tr><td class="k">被依赖</td><td>' + (m.incoming || []).length + ' 条</td></tr>'
        + '</table>';
      if (kids(sel).length){
        h += '<div class="edgebar">';
        kids(sel).forEach(function(c){
          h += '<button class="btn" data-goto="' + esc(c) + '">'
             + esc(trunc(bi(M[c] && M[c].name) || c, 11)) + '</button>';
        });
        h += '</div><div class="hint">单击选中 · 再击或双击下钻</div>';
      }
      if ((m.source || []).length){
        h += '<table style="margin-top:10px"><tr><th>代码证据</th><th>行</th></tr>';
        m.source.forEach(function(s){
          h += '<tr><td>' + esc(s.path) + '</td><td>'
             + esc(s.line ? (s.line + '-' + (s.end_line || s.line)) : '-')
             + '</td></tr>';
        });
        h += '</table>';
      }
    } else if (tab === 'apis'){
      var a = m.apis || [];
      if (!a.length) h = '<div class="note">无 API。容器模块的接口由编译器从子层聚合。</div>';
      else {
        h = '<table><tr><th>协议</th><th>键</th></tr>';
        var cc = semOf(m) || 'frontend';
        a.forEach(function(x){
          h += '<tr><td><span class="pill" style="color:' + v(cc) + '">'
             + esc(x.protocol) + '</span></td><td>' + esc(apiKey(x))
             + '<div style="color:var(--dim);margin-top:3px">'
             + esc(((x.description || {}).zh) || '') + '</div></td></tr>';
        });
        h += '</table>';
      }
    } else if (tab === 'edges'){
      var out = (m.deps || []).map(function(d){
        return {dir:'OUT', other:d.to, kind:d.kind, note:bi(d.label)}; });
      (m.incoming || []).forEach(function(d){
        out.push({dir:'IN', other:d.from, kind:d.kind, note:bi(d.label)}); });
      if (!out.length) h = '<div class="note">无依赖边。</div>';
      else {
        h = '<table><tr><th>向</th><th>类型</th><th>目标</th></tr>';
        out.forEach(function(d){
          var o = M[d.other] || {};
          h += '<tr><td><span class="pill" style="color:' + v(edgeColor(d.kind))
             + '">' + d.dir + '</span></td><td>' + esc(d.kind || '') + '</td>'
             + '<td><a href="#module=' + encodeURIComponent(d.other)
             + '" data-goto="' + esc(d.other) + '">'
             + esc(bi(o.name) || d.other) + '</a>'
             + (d.note ? '<div style="color:var(--dim);margin-top:3px">'
                + esc(d.note) + '</div>' : '') + '</td></tr>';
        });
        h += '</table>';
      }
    } else {
      h = '<table>'
        + '<tr><td class="k">uid</td><td>' + esc(m.uid) + '</td></tr>'
        + '<tr><td class="k">revision</td><td>' + esc(trunc(m.revision, 12)) + '</td></tr>'
        + '<tr><td class="k">fingerprint</td><td>' + esc(trunc(m.fingerprint, 16)) + '</td></tr>'
        + '<tr><td class="k">updated_at</td><td>' + esc(m.updated_at) + '</td></tr>'
        + '<tr><td class="k">parent</td><td>' + esc(m.parent || '(root)') + '</td></tr>'
        + '</table>';
    }
    document.getElementById('p-body').innerHTML = h;
  }

  svg.addEventListener('click', function(e){
    var g = e.target.closest ? e.target.closest('.node') : null;
    if (!g){ sel = null; paintPanel(); render(); return; }
    var id = g.getAttribute('data-id');
    if (sel === id && kids(id).length){
      cur = id; sel = null; collapsed[id] = false;
      history.replaceState(null, '', '#module=' + encodeURIComponent(id));
      render(); fit(); paintPanel(); return;
    }
    sel = id; paintPanel(); render();
  });
  svg.addEventListener('dblclick', function(e){
    var g = e.target.closest ? e.target.closest('.node') : null;
    if (!g) return;
    var id = g.getAttribute('data-id');
    if (kids(id).length){
      cur = id; sel = null; collapsed[id] = false;
      history.replaceState(null, '', '#module=' + encodeURIComponent(id));
      render(); fit(); paintPanel();
    }
  });

  var drag = null;
  svg.addEventListener('mousedown', function(e){
    drag = {x: e.clientX - view.x, y: e.clientY - view.y};
    svg.classList.add('dragging');
  });
  window.addEventListener('mousemove', function(e){
    if (!drag) return;
    view.x = e.clientX - drag.x; view.y = e.clientY - drag.y; applyView();
  });
  window.addEventListener('mouseup', function(){
    drag = null; svg.classList.remove('dragging'); });
  svg.addEventListener('wheel', function(e){
    if (!e.ctrlKey && !e.metaKey && Math.abs(e.deltaY) < 60) return;
    e.preventDefault();
    var r = svg.getBoundingClientRect();
    var mx = e.clientX - r.left, my = e.clientY - r.top;
    var k2 = Math.min(2.4, Math.max(0.25,
      view.k * (e.deltaY < 0 ? 1.12 : 1 / 1.12)));
    view.x = mx - (mx - view.x) * (k2 / view.k);
    view.y = my - (my - view.y) * (k2 / view.k);
    view.k = k2; applyView();
  }, {passive: false});

  document.body.addEventListener('click', function(e){
    var d = e.target.dataset;
    if (!d) return;
    if (d.theme !== undefined){
      document.documentElement.setAttribute('data-theme', d.theme);
      [].forEach.call(document.querySelectorAll('#themebar .btn'), function(b){
        b.setAttribute('aria-pressed', String(b === e.target)); });
      render(); paintPanel(); return;
    }
    if (d.mode !== undefined){
      mode = d.mode;
      [].forEach.call(document.querySelectorAll('#modebar .btn'), function(b){
        b.setAttribute('aria-pressed', String(b.dataset.mode === mode)); });
      sel = null; render(); fit(); paintPanel(); return;
    }
    if (d.tab !== undefined){
      tab = d.tab;
      [].forEach.call(document.querySelectorAll('#ptabs .btn'), function(b){
        b.setAttribute('aria-pressed', String(b.dataset.tab === tab)); });
      paintPanel(); return;
    }
    if (d.goto !== undefined){
      sel = d.goto;
      if (kids(d.goto).length) cur = d.goto;
      history.replaceState(null, '', '#module=' + encodeURIComponent(d.goto));
      render(); fit(); paintPanel(); return;
    }
    if (e.target.id === 'btn-fit'){ sel = null; fit(); return; }
  });

  window.addEventListener('resize', function(){
    svg.setAttribute('viewBox', '0 0 ' + (svg.clientWidth || 900) + ' '
                                            + (svg.clientHeight || 600));
    applyView();
  });
  window.addEventListener('hashchange', function(){
    var id = location.hash.indexOf('#module=') === 0
      ? decodeURIComponent(location.hash.slice(8)) : '';
    if (M[id] && id !== cur){ cur = id; sel = null; render(); fit(); paintPanel(); }
  });

  (function boot(){
    var s = DATA.stats;
    document.getElementById('ttl').textContent = DATA.project.slug;
    document.getElementById('sub').textContent = '归一化框架图 · ' + DATA.engine;
    document.getElementById('kpis').innerHTML =
        '<span class="chip"><b>' + s.modules + '</b>MOD</span>'
      + '<span class="chip"><b>' + s.leaves + '</b>LEAF</span>'
      + '<span class="chip"><b>' + s.trees + '</b>TREE</span>'
      + '<span class="chip"><b>' + s.max_depth + '</b>DEPTH</span>'
      + '<span class="chip"><b>' + s.apis + '</b>API</span>'
      + '<span class="chip"><b>' + s.deps + '</b>EDGE</span>'
      + '<span class="chip">' + esc(DATA.digest.slice(0, 8)) + '</span>';
    document.getElementById('ft').textContent =
      '拖动平移 · 滚轮缩放 · 单击选中 · 再击/双击下钻 · 深链 #module=<id>';
    render(); fit(); paintPanel();
  })();

  // ==========================================================================
  // 增强层（2026-10-12）· 与 normify.html 视觉/功能对齐
  //   P4 动效/配色切换按钮 · P1 五种导出（SVG/PNG/JPEG/WebP/WebM）
  // 说明：按钮由脚本注入工具栏，而不是改 07 分段的 HTML —— 保持「只动本分段」。
  // ==========================================================================

  /* —— P1 导出：克隆 #canvas 并把计算样式内联 ——
     关键：不内联计算样式的话，光栅化出来是「没有样式」的裸图。
     注意本段位于 Python 原始字符串内，正则里的反斜杠写「一个」即可。 */
  var NM_SVG_CSS = [
    '.nbox{fill:#0F172A;stroke:#1E293B;stroke-width:1}',
    '.nbox.leaf{fill:#0F172A;stroke:#1E293B}',
    '.nlabel{fill:#FFFFFF;font-family:ui-monospace,Consolas,monospace}',
    '.nid{fill:#475569;font-family:ui-monospace,Consolas,monospace}',
    '.nmeta{fill:#94A3B8;font-family:ui-monospace,Consolas,monospace}',
    '.sedge{fill:none;stroke:#1E293B;stroke-width:1}',
    '.dedge{fill:none;stroke-width:1.4}',
    '.edge-flow{fill:none;stroke:#22D3EE;stroke-width:2;stroke-linecap:round}',
    '.grp{fill:none;stroke:#1E293B;stroke-dasharray:4 4}',
    '.group-bar{fill:#22D3EE;opacity:.085}',
    '.group-rail{fill:#22D3EE;opacity:.5}',
    '.grplabel{fill:#475569;font-size:11px;font-family:ui-monospace,Consolas,monospace}'
  ].join('');

  function nmCurrentSvg(){ return document.getElementById('canvas'); }

  function nmSnapshotSvg(){
    var orig = nmCurrentSvg();
    if (!orig) return null;
    var clone = orig.cloneNode(true);
    clone.setAttribute('xmlns', 'http://www.w3.org/2000/svg');
    clone.setAttribute('xmlns:xlink', 'http://www.w3.org/1999/xlink');
    clone.removeAttribute('id');
    var sel = '.edge-flow, .dedge, .sedge, .nbox, .nlabel, .nid, .nmeta,'
            + ' .grp, .group-bar, .group-rail, .grplabel';
    var oN = orig.querySelectorAll(sel), cN = clone.querySelectorAll(sel);
    for (var i = 0; i < oN.length && i < cN.length; i++){
      var cs = getComputedStyle(oN[i]);
      var st = cN[i].style;
      st.opacity = cs.opacity;
      st.strokeWidth = cs.strokeWidth;
      st.stroke = cs.stroke;
      st.fill = cs.fill;
      if (cs.filter && cs.filter !== 'none') st.filter = cs.filter;
      if (cs.transform && cs.transform !== 'none') st.transform = cs.transform;
    }
    var styleEl = el('style');
    styleEl.textContent = NM_SVG_CSS;
    clone.insertBefore(styleEl, clone.firstChild);
    return clone;
  }

  function nmSvgString(){
    var c = nmSnapshotSvg();
    return c ? new XMLSerializer().serializeToString(c) : '';
  }

  function nmDownload(blob, name){
    var a = document.createElement('a');
    a.href = URL.createObjectURL(blob);
    a.download = name;
    document.body.appendChild(a);
    a.click();
    setTimeout(function(){ URL.revokeObjectURL(a.href); a.remove(); }, 5000);
  }

  function nmVb(scale){
    var svg = nmCurrentSvg();
    var raw = svg ? String(svg.getAttribute('viewBox')) : '';
    var vb = (raw || '0 0 800 600').split(/\s+/).map(Number);
    var s = scale || 2;
    return {x: vb[0], y: vb[1], w: vb[2], h: vb[3],
            px: Math.round(vb[2] * s), py: Math.round(vb[3] * s)};
  }

  function nmRasterize(scale, cb){
    var g = nmVb(scale);
    var str = nmSvgString();
    if (!str){ cb(null); return; }
    var img = new Image();
    img.onload = function(){
      var c = document.createElement('canvas');
      c.width = Math.min(6000, g.px); c.height = Math.min(6000, g.py);
      var ctx = c.getContext('2d');
      ctx.fillStyle = getComputedStyle(document.body).backgroundColor || '#020617';
      ctx.fillRect(0, 0, c.width, c.height);
      ctx.drawImage(img, 0, 0, c.width, c.height);
      cb(c);
    };
    img.onerror = function(){ cb(null); };
    img.src = 'data:image/svg+xml;charset=utf-8,' + encodeURIComponent(str);
  }

  function nmExportStatic(fmt){
    var base = 'architecture-' + (cur || 'view');
    if (fmt === 'svg'){
      var str = nmSvgString();
      if (!str) return;
      nmDownload(new Blob([str], {type:'image/svg+xml;charset=utf-8'}), base + '.svg');
      return;
    }
    nmRasterize(2, function(c){
      if (!c){ alert('导出失败：SVG 光栅化异常'); return; }
      var mime = fmt === 'jpeg' ? 'image/jpeg'
               : (fmt === 'webp' ? 'image/webp' : 'image/png');
      c.toBlob(function(b){
        if (b) nmDownload(b, base + '.' + (fmt === 'jpeg' ? 'jpg' : fmt));
      }, mime, fmt === 'jpeg' ? 0.92 : undefined);
    });
  }

  function nmWebmSupported(){
    if (!('MediaRecorder' in window)) return false;
    try {
      var c = document.createElement('canvas');
      return !!(c.captureStream && c.captureStream(1));
    } catch (e){ return false; }
  }

  function nmExportWebM(seconds){
    if (!nmWebmSupported()){
      alert('当前浏览器不支持录制，请改用 PNG / SVG 导出。'); return;
    }
    var sec = seconds || 6;
    var g = nmVb(0);
    var W = Math.min(1600, g.px || 1200);
    var H = Math.round(W * (g.h / g.w));
    var c = document.createElement('canvas');
    c.width = W; c.height = H;
    var ctx = c.getContext('2d');
    var mime = ['video/webm;codecs=vp9', 'video/webm;codecs=vp8', 'video/webm']
      .filter(function(m){
        return MediaRecorder.isTypeSupported && MediaRecorder.isTypeSupported(m);
      })[0] || 'video/webm';
    var stream = c.captureStream(25);
    var rec;
    try { rec = new MediaRecorder(stream, {mimeType: mime, videoBitsPerSecond: 4000000}); }
    catch (e){ alert('录制初始化失败：' + e.message); return; }
    var chunks = [];
    rec.ondataavailable = function(e){ if (e.data && e.data.size) chunks.push(e.data); };
    rec.onstop = function(){
      if (!chunks.length){ alert('录制未产生数据，请重试。'); return; }
      nmDownload(new Blob(chunks, {type:'video/webm'}), 'architecture-motion.webm');
    };
    rec.start();
    var t0 = performance.now();
    var bg = getComputedStyle(document.body).backgroundColor || '#020617';
    function tick(){
      var img = new Image();
      img.onload = function(){
        ctx.fillStyle = bg;
        ctx.fillRect(0, 0, W, H);
        ctx.drawImage(img, 0, 0, W, H);
        if (performance.now() - t0 < sec * 1000) requestAnimationFrame(tick);
        else setTimeout(function(){ rec.stop(); }, 220);
      };
      img.onerror = function(){
        if (performance.now() - t0 < sec * 1000) requestAnimationFrame(tick);
        else rec.stop();
      };
      img.src = 'data:image/svg+xml;charset=utf-8,'
              + encodeURIComponent(nmSvgString());
    }
    tick();
  }

  /* —— P4 切换按钮：注入工具栏 —— */
  var NM_MOTION_OPTS = [
    ['',        '默认（流动）'],
    ['spring',  'Apple Spring · 弹性'],
    ['glow',    'OpenAI Glow · 光晕'],
    ['depth',   'Apple Depth · 纵深'],
    ['archify', 'Archify 原版 · 错峰流动'],
    ['scan',    'Archify 信号扫描 · 柔光']
  ];
  var NM_PRESET_OPTS = [
    ['signal',    'Signal Flow · 青蓝'],
    ['blueprint', 'Blueprint · 蓝图'],
    ['ember',     'Ember · 暖橙']
  ];
  var NM_EXPORT_OPTS = [
    ['svg',  'SVG 矢量'],
    ['png',  'PNG 图片'],
    ['jpeg', 'JPEG 图片'],
    ['webp', 'WebP 图片'],
    ['sep',  ''],
    ['webm', 'WebM 动图（6 秒）']
  ];

  function nmInjectWrap(tools, btnId, label, menuId, opts, attr){
    var wrap = document.createElement('span');
    wrap.className = 'export-wrap';
    var html = '<button class="btn" id="' + btnId + '">' + label + ' ▾</button>'
             + '<div class="export-menu" id="' + menuId + '" hidden>';
    opts.forEach(function(o){
      if (o[0] === 'sep'){ html += '<div class="export-sep"></div>'; return; }
      html += '<button ' + attr + '="' + o[0] + '">' + o[1] + '</button>';
    });
    wrap.innerHTML = html + '</div>';
    tools.appendChild(wrap);
  }

  function nmMarkActive(menuId, attr, bodyAttr){
    var menu = document.getElementById(menuId);
    if (!menu) return;
    var curv = document.documentElement.getAttribute(bodyAttr) || '';
    var btns = menu.querySelectorAll('button[' + attr + ']');
    for (var i = 0; i < btns.length; i++){
      var on = (btns[i].getAttribute(attr) || '') === curv;
      btns[i].classList.toggle('on', on);
    }
  }

  function nmBindMenu(btnId, menuId, attr, onPick){
    var btn = document.getElementById(btnId);
    var menu = document.getElementById(menuId);
    if (!btn || !menu) return;
    btn.addEventListener('click', function(e){
      e.stopPropagation();
      menu.hidden = !menu.hidden;
    });
    document.addEventListener('click', function(){ menu.hidden = true; });
    menu.addEventListener('click', function(e){
      e.stopPropagation();
      var b = e.target.closest ? e.target.closest('button[' + attr + ']') : null;
      if (!b || b.disabled) return;
      menu.hidden = true;
      onPick(b.getAttribute(attr) || '');
    });
  }

  function nmSyncUrl(key, val){
    try {
      var u = new URL(location.href);
      if (val) u.searchParams.set(key, val); else u.searchParams.delete(key);
      history.replaceState(null, '', u.toString());
    } catch (e){ /* file:// 下忽略 */ }
  }

  function nmSetMotion(val){
    var h = document.documentElement;
    if (val) h.setAttribute('data-motion', val); else h.removeAttribute('data-motion');
    nmSyncUrl('motion', val);
    nmMarkActive('nmMotionMenu', 'data-motion-opt', 'data-motion');
    render(); fit();       // 重绘以重播入场动效
  }

  function nmSetPreset(val){
    document.documentElement.setAttribute('data-preset', val || 'signal');
    nmSyncUrl('preset', val);
    nmMarkActive('nmPresetMenu', 'data-preset-opt', 'data-preset');
    render();              // 重绘以重读设计令牌
  }

  (function nmInitEnhance(){
    var tools = document.querySelector('.topbar .tools');
    if (!tools) return;
    nmInjectWrap(tools, 'btnMotion', '动效', 'nmMotionMenu', NM_MOTION_OPTS, 'data-motion-opt');
    nmInjectWrap(tools, 'btnPreset', '配色', 'nmPresetMenu', NM_PRESET_OPTS, 'data-preset-opt');
    nmInjectWrap(tools, 'btnExport', '导出', 'nmExportMenu', NM_EXPORT_OPTS, 'data-export');

    nmBindMenu('btnMotion', 'nmMotionMenu', 'data-motion-opt', nmSetMotion);
    nmBindMenu('btnPreset', 'nmPresetMenu', 'data-preset-opt', nmSetPreset);
    nmBindMenu('btnExport', 'nmExportMenu', 'data-export', function(k){
      if (k === 'webm') nmExportWebM(6); else nmExportStatic(k);
    });

    // 不支持录制时禁用 WebM 项（fail-closed，不给出假承诺）
    if (!nmWebmSupported()){
      var wb = document.querySelector('#nmExportMenu [data-export="webm"]');
      if (wb){
        wb.disabled = true;
        wb.title = '当前浏览器不支持录制（需 MediaRecorder + captureStream）';
      }
    }

    nmMarkActive('nmMotionMenu', 'data-motion-opt', 'data-motion');
    nmMarkActive('nmPresetMenu', 'data-preset-opt', 'data-preset');

    // 暴露导出能力（便于自动化验证 / 二次开发）
    window.nmExport = {
      svgString: nmSvgString,
      rasterize: nmRasterize,
      exportStatic: nmExportStatic,
      exportWebM: nmExportWebM,
      webmSupported: nmWebmSupported
    };
  })();
})();
</script>
</body>
</html>
"""

HTML_TEMPLATE = HTML_HEAD + HTML_TAIL


def _normify_engine_dir() -> Path:
    """normify 渲染引擎所在目录（技能内置）。"""
    return Path(__file__).resolve().parent.parent / 'lib' / 'normify'


def _find_node() -> str:
    """找一个可用的 node 解释器（含 WorkBuddy 托管版兜底）。"""
    import os, glob, shutil
    if os.environ.get('WB_NODE') and Path(os.environ['WB_NODE']).exists():
        return os.environ['WB_NODE']
    for name in ('node', 'nodejs'):
        p = shutil.which(name)
        if p:
            return p
    # WorkBuddy 托管 node（~/.workbuddy/binaries/node/versions/<ver>/bin/node）
    for p in sorted(glob.glob(str(Path.home() / '.workbuddy' / 'binaries' / 'node' / 'versions' / '*' / 'bin' / 'node')), reverse=True):
        if Path(p).exists():
            return p
    return ''


def render_html(tree: dict, out_path: Path) -> Path:
    """渲染架构图为单文件 HTML。

    优先用 normify 引擎（Node）渲染，产物与项目里的 normify.html 视觉一致；
    引擎或 Node 不可用时自动回退到内置模板 —— 保证技能在任何环境都可用。
    """
    out_path = Path(out_path)
    out_path.parent.mkdir(parents=True, exist_ok=True)

    # —— ① 首选：normify 引擎 ——
    eng = _normify_engine_dir()
    renderer = eng / 'render.mjs'
    node = _find_node()
    if renderer.exists() and node:
        import subprocess, tempfile
        tmp_tree = None
        try:
            with tempfile.NamedTemporaryFile('w', suffix='.json', delete=False, encoding='utf-8') as f:
                json.dump(tree, f, ensure_ascii=False)
                tmp_tree = f.name
            title = f"{tree['project']['slug']} · 归一化框架图"
            proc = subprocess.run(
                [node, str(renderer), tmp_tree, str(out_path), title],
                capture_output=True, text=True, timeout=180,
            )
            if proc.returncode == 0 and out_path.exists() and out_path.stat().st_size > 20000:
                return out_path
            print(f'  ! normify 引擎渲染失败（rc={proc.returncode}），回退内置模板', file=sys.stderr)
            if proc.stderr:
                print(f'    {proc.stderr.strip()[:300]}', file=sys.stderr)
        except Exception as exc:                                   # noqa: BLE001
            print(f'  ! normify 引擎异常（{type(exc).__name__}: {exc}），回退内置模板', file=sys.stderr)
        finally:
            if tmp_tree:
                try:
                    Path(tmp_tree).unlink()
                except OSError:
                    pass

    # —— ② 回退：内置模板 ——
    payload = json.dumps(tree, ensure_ascii=False).replace("</", "<\\/")
    html = (HTML_TEMPLATE
            .replace("__TITLE__", f"{tree['project']['slug']} · 归一化框架图")
            .replace("__TREE_JSON__", payload))
    out_path.write_text(html, encoding="utf-8")
    return out_path
