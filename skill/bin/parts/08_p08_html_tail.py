
# --------------------------------------------------------------------------
# 渲染（二）：图画布 + 面板 + 交互
#
# 画布是"真图"而不是卡片网格：按层级分列的节点链路图，
# 结构边（父子）细灰，依赖边（deps）按 kind 语义着色，可平移/缩放/下钻。
# --------------------------------------------------------------------------

HTML_TAIL = r"""<script id="payload" type="application/json">__TREE_JSON__</script>
<script>
(function(){
  var DATA = JSON.parse(document.getElementById('payload').textContent);
  var M = DATA.modules || {}, L = DATA.layouts || {};
  var PAL = ['frontend','backend','database','cloud','security','messagebus','external'];

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
    var depthLimit = mode === 'all' ? 3 : 2;
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
        gGrp.appendChild(el('rect', {x: x1 - pad, y: y1 - pad - head,
          width: (x2 - x1) + pad * 2, height: (y2 - y1) + pad * 2 + head,
          rx: 9, 'class': 'grp'}));
        gGrp.appendChild(el('text', {x: x1 - pad + 11, y: y1 - pad - 4,
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
    });

    sc.nodes.forEach(function(n){
      var m = M[n.id], p = pos[n.id], c = semOf(m);
      var ks = kids(n.id);
      var g = el('g', {'class': 'node' + (sel === n.id ? ' sel' : '')
                             + (sel && !nb[n.id] ? ' dimmed' : '')
                             + (sel && nb[n.id] && n.id !== sel ? ' hot' : ''),
                       'data-id': n.id});
      g.appendChild(el('rect', {x:p.x, y:p.y, width:p.w, height:p.h, rx:6,
        'class':'nbox', fill: v('mask'), stroke: c ? v(c) : v('dim'),
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
})();
</script>
</body>
</html>
"""

HTML_TEMPLATE = HTML_HEAD + HTML_TAIL


def render_html(tree: dict, out_path: Path) -> Path:
    payload = json.dumps(tree, ensure_ascii=False).replace("</", "<\\/")
    html = (HTML_TEMPLATE
            .replace("__TITLE__", f"{tree['project']['slug']} · 归一化框架图")
            .replace("__TREE_JSON__", payload))
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(html, encoding="utf-8")
    return out_path
