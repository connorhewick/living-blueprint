/* Builds the whole page from the JSON in #lb-data. Every string from the doc reaches the page
   through textContent: a doc comes from a repository and is not trusted to carry markup. */
(function () {
  'use strict';
  var doc = JSON.parse(document.getElementById('lb-data').textContent);
  var NS = 'http://www.w3.org/2000/svg';
  var main = document.getElementById('lb-main');

  var layers = {};
  (doc.layers || []).forEach(function (l, i) {
    var color = /^#[0-9a-fA-F]{6}$/.test(l.color || '') ? l.color : 'var(--l' + (i % 8) + ')';
    layers[l.id] = { label: l.label || l.id, color: color, order: i };
  });
  function layerOf(id) { return layers[id] || { label: id || 'Other', color: 'var(--l6)', order: 99 }; }

  function h(tag, parent, attrs, text) {
    var e = document.createElement(tag);
    for (var k in attrs || {}) e.setAttribute(k, attrs[k]);
    if (text !== undefined) e.textContent = text;
    if (parent) parent.appendChild(e);
    return e;
  }
  /* `code` and **bold** only; everything else stays text. */
  function rich(parent, s) {
    String(s === undefined ? '' : s).split(/(`[^`]*`|\*\*[^*]+\*\*)/).forEach(function (part) {
      if (/^`[^`]*`$/.test(part)) h('code', parent, null, part.slice(1, -1));
      else if (/^\*\*[^*]+\*\*$/.test(part)) h('b', parent, null, part.slice(2, -2));
      else if (part) parent.appendChild(document.createTextNode(part));
    });
    return parent;
  }
  var WORD = { proposed: 'NEW', changed: 'CHANGES', removed: 'REMOVES' };
  function statusOf(t) { return t.status || 'built'; }
  function tags(parent, thing) {
    if (WORD[statusOf(thing)]) h('span', parent, { 'class': 'tag new' }, WORD[statusOf(thing)]);
    if (thing.evidence === 'unverified') h('span', parent, { 'class': 'tag warn' }, 'unverified');
    if (thing.open) h('span', parent, { 'class': 'tag warn', title: thing.open }, 'open');
  }

  /* ---------- measuring and svg ---------- */
  var ctx = document.createElement('canvas').getContext('2d');
  var MONO = '700 11.5px ui-monospace,SFMono-Regular,Menlo,Consolas,monospace';
  var SANS = '11px -apple-system,BlinkMacSystemFont,"Segoe UI",system-ui,sans-serif';
  function tw(s, f) { ctx.font = f; return ctx.measureText(s).width * 1.04; }
  function wrap(s, max, f) {
    var out = [];
    String(s).split('\n').forEach(function (part) {
      var toks = part.match(/[^ .\/_(:\-]+?(?:[ .\/_(:\-]+|(?<=[a-z0-9])(?=[A-Z][a-z])|$)|[ .\/_(:\-]+/g) || [part];
      var cur = '';
      toks.forEach(function (t) {
        if (cur && tw((cur + t).replace(/\s+$/, ''), f) > max) { out.push(cur.replace(/\s+$/, '')); cur = t; } else cur += t;
        while (tw(cur.replace(/\s+$/, ''), f) > max && cur.length > 2) {
          var k = cur.length - 1;
          while (k > 1 && tw(cur.slice(0, k), f) > max) k--;
          out.push(cur.slice(0, k)); cur = cur.slice(k);
        }
      });
      if (cur.trim()) out.push(cur.replace(/\s+$/, ''));
    });
    return out;
  }
  function el(tag, attrs, parent) {
    var e = document.createElementNS(NS, tag);
    for (var k in attrs) e.setAttribute(k, attrs[k]);
    if (parent) parent.appendChild(e);
    return e;
  }
  function txt(parent, x, y, s, cls, extra) {
    var a = { x: x, y: y };
    if (cls) a['class'] = cls;
    for (var k in extra || {}) a[k] = extra[k];
    var t = el('text', a, parent);
    t.textContent = s;
    return t;
  }
  function svgFor(host, height, label) {
    var box = h('div', host, { 'class': 'scroll' });
    return el('svg', { viewBox: '0 0 1000 ' + height, 'class': 'd', role: 'img', 'aria-label': label }, box);
  }
  function nodeLines(thing, title, sub, width) {
    var lines = [];
    if (WORD[statusOf(thing)]) lines.push([WORD[statusOf(thing)], 'm']);
    if (thing.evidence === 'unverified') lines.push(['UNVERIFIED', 'm']);
    wrap(title, width - 12, MONO).forEach(function (l) { lines.push([l, 't']); });
    sub.forEach(function (s) { wrap(s, width - 12, SANS).forEach(function (l) { lines.push([l, 's']); }); });
    return lines;
  }
  function drawNode(svg, x, y, w, height, key, lines, layer, thing, cls) {
    var g = el('g', {
      'class': 'node' + (cls ? ' ' + cls : ''), style: '--c:' + layerOf(layer).color,
      'data-title': key, 'data-status': statusOf(thing), tabindex: '0', role: 'button', 'aria-label': 'Trace ' + key
    }, svg);
    el('rect', { x: x, y: y, width: w, height: height, rx: 3 }, g);
    lines.forEach(function (l, i) { txt(g, x + 6, y + 15 + i * 13.5, l[0], l[1]); });
    return g;
  }
  function drawEdge(svg, pts, o) {
    var g = el('g', { 'class': 'eg', 'data-status': o.status || 'built' }, svg);
    el('polyline', { 'class': 'edge' + (o.dash ? ' dash' : ''), points: pts.map(function (p) { return p.join(','); }).join(' ') }, g);
    if (!o.nohead) {
      var a = pts[pts.length - 2], b = pts[pts.length - 1];
      var dx = b[0] - a[0], dy = b[1] - a[1], d = Math.hypot(dx, dy) || 1;
      dx /= d; dy /= d;
      el('polygon', { 'class': 'head', points: [b, [b[0] - 8 * dx - 4 * dy, b[1] - 8 * dy + 4 * dx], [b[0] - 8 * dx + 4 * dy, b[1] - 8 * dy - 4 * dx]].join(' ') }, g);
    }
    return g;
  }

  /* ---------- graph: nodes sit on a grid, arrows travel only in the gutters between cells,
     so no arrow can cross a box whatever the doc says. ---------- */
  function graph(host, block, label) {
    var nodes = block.nodes || [], edges = block.edges || [];
    var cols = Math.max.apply(null, nodes.map(function (n) { return n.col; }).concat(1)) + 1;
    var rows = Math.max.apply(null, nodes.map(function (n) { return n.row; }).concat(0)) + 1;
    var cw = 1000 / cols, gx = Math.min(140, cw * 0.4), bw = cw - gx, GY = 64;
    var rowH = [], byId = {};
    nodes.forEach(function (n) {
      var title = n.title + '';
      var sub = (n.lines || []).slice();
      if (n.was && n.was.title !== n.title) sub.push('was: ' + n.was.title);
      var lines = nodeLines(n, title, sub, bw);
      byId[n.id] = { n: n, col: n.col, row: n.row, lines: lines, need: lines.length * 13.5 + 12 };
      rowH[n.row] = Math.max(rowH[n.row] || 44, byId[n.id].need);
    });
    var top = [], y = GY / 2;
    for (var r = 0; r < rows; r++) { rowH[r] = rowH[r] || 20; top[r] = y; y += rowH[r] + GY; }
    var height = y - GY / 2;
    Object.keys(byId).forEach(function (id) { var b = byId[id]; b.x = b.col * cw + gx / 2; b.y = top[b.row]; b.w = bw; b.h = rowH[b.row]; });

    var ports = {}, tracks = {};
    function port(id, side) { var k = id + side; ports[k] = ports[k] || { total: 0, used: 0 }; return ports[k]; }
    function plan(e) {
      var a = byId[e.from], b = byId[e.to];
      if (a.row === b.row && Math.abs(a.col - b.col) === 1) return { kind: 'across', a: a.col < b.col ? 'r' : 'l', b: a.col < b.col ? 'l' : 'r' };
      if (a.col === b.col && Math.abs(a.row - b.row) === 1) return { kind: 'down', a: a.row < b.row ? 'b' : 't', b: a.row < b.row ? 't' : 'b' };
      if (a.row === b.row) return { kind: 'under', a: 'b', b: 'b' };
      var aSide = b.row > a.row ? 'b' : 't', bSide = b.row > a.row ? 't' : 'b';
      return { kind: Math.abs(a.row - b.row) === 1 ? 'step' : 'far', a: aSide, b: bSide };
    }
    var plans = edges.map(function (e) { var p = plan(e); port(e.from, p.a).total++; port(e.to, p.b).total++; return p; });
    function at(node, side, f) {
      if (side === 'l') return [node.x, node.y + node.h * f];
      if (side === 'r') return [node.x + node.w, node.y + node.h * f];
      return [node.x + node.w * f, side === 't' ? node.y : node.y + node.h];
    }
    function nextPort(id, side) { var p = port(id, side); p.used++; return p.used / (p.total + 1); }
    /* parallel runs in one gutter get their own track */
    function track(key, spread) { var n = tracks[key] = (tracks[key] || 0) + 1; var step = [0, -1, 1, -2, 2, -3, 3][(n - 1) % 7]; return step * spread; }
    /* gutter g sits above row g */
    function rowGutter(g) { var base = g === 0 ? GY / 4 : g >= rows ? height - GY / 4 : top[g] - GY / 2; return base + track('r' + g, g === 0 || g >= rows ? 3 : 8); }
    /* a vertical run hugs the box it is heading for, which leaves the middle of the gutter for labels */
    function colGutter(g, side) { return g * cw + side * (gx / 2 - 9) + track('c' + g + side, 2.5); }

    var routes = edges.map(function (e, i) {
      var p = plans[i], a = byId[e.from], b = byId[e.to];
      var fa = nextPort(e.from, p.a), fb = nextPort(e.to, p.b);
      var s = at(a, p.a, fa), t = at(b, p.b, fb), g;
      if (p.kind === 'across') return [s, [t[0], s[1]]].map(function (q, n) { return n ? [q[0], Math.min(b.y + b.h - 4, Math.max(b.y + 4, q[1]))] : q; });
      if (p.kind === 'down') return [s, [s[0], t[1]]];
      if (p.kind === 'under') { g = rowGutter(a.row + 1); return [s, [s[0], g], [t[0], g], t]; }
      if (p.kind === 'step') { g = rowGutter(Math.max(a.row, b.row)); return [s, [s[0], g], [t[0], g], t]; }
      var down = b.row > a.row;
      var g1 = rowGutter(down ? a.row + 1 : a.row), g2 = rowGutter(down ? b.row : b.row + 1);
      var cx = b.col > a.col ? colGutter(b.col, 1) : colGutter(b.col + 1, -1);
      return [s, [s[0], g1], [cx, g1], [cx, g2], [t[0], g2], t];
    });

    var svg = svgFor(host, height, label);
    var groups = routes.map(function (pts, i) { return drawEdge(svg, pts, { status: statusOf(edges[i]) }); });
    Object.keys(byId).forEach(function (id) {
      var b = byId[id];
      drawNode(svg, b.x, b.y, b.w, b.h, b.n.title, b.lines, b.n.layer, b.n);
    });

    var placed = [];
    var boxes = Object.keys(byId).map(function (id) { var b = byId[id]; return { x: b.x, y: b.y, w: b.w, h: b.h }; });
    function overlaps(r, o) { return r.x < o.x + o.w && o.x < r.x + r.w && r.y < o.y + o.h && o.y < r.y + r.h; }
    function clash(r, own) {
      if (r.x < 1 || r.x + r.w > 999 || r.y < 0 || r.y + r.h > height) return true;
      if (boxes.concat(placed).some(function (o) { return overlaps(r, o); })) return true;
      /* another edge's line through the words makes it unclear which arrow the label names */
      return routes.some(function (pts, j) {
        return j !== own && pts.slice(1).some(function (p, k) {
          return overlaps({ x: r.x, y: r.y + 2, w: r.w, h: r.h - 4 }, { x: Math.min(p[0], pts[k][0]), y: Math.min(p[1], pts[k][1]), w: Math.abs(p[0] - pts[k][0]) || 1, h: Math.abs(p[1] - pts[k][1]) || 1 });
        });
      });
    }
    edges.forEach(function (e, i) {
      var text = (WORD[statusOf(e)] ? WORD[statusOf(e)] + ' ' : '') + (e.label || '');
      if (!text) return;
      var pts = routes[i], segments = [];
      for (var k = 0; k < pts.length - 1; k++) segments.push([pts[k], pts[k + 1]]);
      segments.sort(function (m, n) { return Math.hypot(n[1][0] - n[0][0], n[1][1] - n[0][1]) - Math.hypot(m[1][0] - m[0][0], m[1][1] - m[0][1]); });
      var widths = [200, gx - 14, 90, 64], chosen = null, fallback = null;
      for (var w = 0; w < widths.length && !chosen; w++) {
        var parts = wrap(text, widths[w], SANS);
        var lw = Math.max.apply(null, parts.map(function (s) { return tw(s, SANS); })), lh = parts.length * 13;
        for (var s = 0; s < segments.length && !chosen; s++) {
          var m = segments[s][0], n = segments[s][1], vertical = Math.abs(m[0] - n[0]) < 1;
          [0.5, 0.3, 0.7, 0.15, 0.85, 0.05, 0.95].some(function (f) {
            var x = m[0] + (n[0] - m[0]) * f, yy = m[1] + (n[1] - m[1]) * f;
            var options = vertical
              ? [{ x: x + 6, y: yy - lh / 2, anchor: 'start', tx: x + 6 }, { x: x - 6 - lw, y: yy - lh / 2, anchor: 'end', tx: x - 6 }]
              : [{ x: x - lw / 2, y: yy - lh - 3, anchor: 'middle', tx: x }, { x: x - lw / 2, y: yy + 3, anchor: 'middle', tx: x }];
            return options.some(function (o) {
              var rect = { x: o.x, y: o.y, w: lw, h: lh };
              var candidate = { rect: rect, anchor: o.anchor, tx: o.tx, parts: parts };
              fallback = fallback || candidate;
              if (clash(rect, i)) return false;
              chosen = candidate; return true;
            });
          });
        }
      }
      var use = chosen || fallback;
      placed.push(use.rect);
      use.parts.forEach(function (part, n) { txt(groups[i], use.tx, use.rect.y + 10 + n * 13, part, 'elbl', { 'text-anchor': use.anchor }); });
    });
  }

  /* ---------- swimlane ---------- */
  function swim(host, block, label) {
    var steps = block.steps || [], lanes = block.lanes || [];
    var hasEffect = steps.some(function (s) { return s.effect; }), fxW = hasEffect ? 220 : 0, lw = (1000 - fxW) / Math.max(1, lanes.length), bw = lw - 12;
    var laneIndex = {};
    lanes.forEach(function (l, i) { laneIndex[l.id] = i; });
    var heads = lanes.map(function (l) { return wrap(l.title, lw - 8, MONO); });
    var headH = Math.max.apply(null, heads.map(function (x) { return x.length; }).concat(1)) * 13.5 + 14;
    var y = headH + 14, byId = {};
    var rows = steps.map(function (s, i) {
      var lines = nodeLines(s, (i + 1) + '. ' + s.title, s.note ? [s.note] : [], bw), height = lines.length * 13.5 + 10;
      var fx = s.effect ? wrap(s.effect, fxW - 20, SANS).map(function (l) { return [l, 's']; }) : null, fxH = fx ? fx.length * 13.5 + 10 : 0;
      var row = { s: s, i: i, x: laneIndex[s.lane] * lw + 6, y: y, h: height, lines: lines, fx: fx, fxH: fxH };
      byId[s.id] = row;
      y += Math.max(height, fxH) + 28;
      return row;
    });
    var svg = svgFor(host, y - 8, label);
    lanes.forEach(function (l, i) {
      el('rect', { 'class': 'lane', x: i * lw + 1, y: 1, width: lw - 2, height: y - 10 }, svg);
      heads[i].forEach(function (s, j) { txt(svg, i * lw + lw / 2, 16 + j * 13.5, s, 'lanehead', { 'text-anchor': 'middle', style: '--c:' + layerOf(l.layer).color }); });
    });
    if (hasEffect) txt(svg, 1000 - fxW + 8, 16, 'Side effects', 's');
    rows.forEach(function (row, i) {
      var sources = row.s.from ? row.s.from.map(function (id) { return byId[id]; }) : (i ? [rows[i - 1]] : []);
      sources.forEach(function (a) {
        var gap = row.y - 14, cx = row.x + bw / 2, pts;
        if (a.i === i - 1) {
          var ax = a.x + bw / 2;
          pts = ax === cx ? [[ax, a.y + a.h], [cx, row.y]] : [[ax, a.y + a.h], [ax, gap], [cx, gap], [cx, row.y]];
        } else {
          var channel = a.x - 3;
          pts = [[a.x, a.y + a.h - 8], [channel, a.y + a.h - 8], [channel, gap], [cx - 14, gap], [cx - 14, row.y]];
        }
        drawEdge(svg, pts, { status: statusOf(row.s) }).setAttribute('data-step', i);
      });
      var node = drawNode(svg, row.x, row.y, bw, row.h, row.s.title, row.lines, lanes[laneIndex[row.s.lane]].layer, row.s);
      node.setAttribute('data-step', i);
      node.setAttribute('data-desc', (WORD[statusOf(row.s)] ? WORD[statusOf(row.s)] + ' ' : '') + row.s.title + (row.s.note ? ': ' + row.s.note : '') + (row.s.effect ? '. Side effect: ' + row.s.effect : ''));
      if (row.fx) {
        var fxX = 1000 - fxW + 8;
        drawEdge(svg, [[row.x + bw, row.y + 12], [fxX, row.y + 12]], { dash: true, nohead: true }).setAttribute('data-step', i);
        drawNode(svg, fxX, row.y, fxW - 10, row.fxH, row.s.effect, row.fx, null, {}, 'fx').setAttribute('data-step', i);
      }
    });
  }

  function bars(host, block, label) {
    var list = block.bars || [];
    var max = Math.max.apply(null, list.map(function (b) { return b.value; }).concat(1));
    var svg = svgFor(host, list.length * 30 + 10, label);
    list.forEach(function (b, i) {
      var y = 8 + i * 30, w = Math.max(3, 520 * b.value / max);
      wrap(b.label, 190, SANS).slice(0, 2).forEach(function (s, n, all) { txt(svg, 200, y + (all.length > 1 ? 8 + n * 13 : 14), s, '', { 'text-anchor': 'end' }); });
      el('rect', { 'class': 'bar-r', x: 210, y: y, width: w, height: 20, style: '--c:' + layerOf(b.layer).color }, svg);
      txt(svg, 218 + w, y + 14, Number(b.value).toLocaleString('en-US') + (block.unit ? ' ' + block.unit : '') + (b.detail ? ' · ' + b.detail : ''), 's');
    });
  }

  function table(host, block) {
    var t = h('table', h('div', host, { 'class': 'scroll' }));
    var headRow = h('tr', t);
    (block.columns || []).forEach(function (c) { rich(h('th', headRow), c); });
    (block.rows || []).forEach(function (row) {
      var tr = h('tr', t, { 'data-status': statusOf(row) });
      row.cells.forEach(function (cell, i) {
        var td = h('td', tr);
        if (i === 0) tags(td, row);
        rich(h('span', td, { 'class': 'val' }), cell);
        if (row.was && row.was.cells && row.was.cells[i] !== cell) rich(h('span', td, { 'class': 'was' }, 'was: '), row.was.cells[i]);
      });
    });
  }

  /* ---------- sections ---------- */
  rich(h('h1', main), doc.title);
  if (doc.summary) rich(h('p', main), doc.summary);
  var meta = h('p', main);
  if (doc.kind === 'design') h('span', meta, { 'class': 'tag new' }, 'Design: ' + (doc.state || 'draft'));
  rich(meta, doc.commit ? 'Pinned to commit `' + doc.commit + '`.' : 'Not pinned to a commit yet.');
  var pending = [];
  (doc.sections || []).forEach(function (s) {
    s.blocks.forEach(function (b) {
      [b].concat(b.nodes || [], b.edges || [], b.steps || [], b.rows || [], b.items || []).forEach(function (x) {
        if (statusOf(x) !== 'built' && x.design && pending.indexOf(x.design) < 0) pending.push(x.design);
      });
    });
  });
  if (pending.length) rich(h('p', main, { 'class': 'notice' }), '**Not everything here is built.** Items marked NEW, CHANGES or REMOVES are proposed by: ' + pending.join(', ') + '.');
  if ((doc.openQuestions || []).length) {
    var qs = h('ul', main, { 'class': 'gaps' });
    doc.openQuestions.forEach(function (question) { var li = h('li', qs); h('span', li, { 'class': 'tag warn' }, 'open question'); rich(li, question); });
  }

  var matrices = [], stories = [];
  (doc.sections || []).forEach(function (section) {
    h(section.level === 3 ? 'h3' : 'h2', main, { id: section.id }, section.title || section.id);
    section.blocks.forEach(function (block) {
      if (block.type === 'text') { var p = rich(h('p', main, { id: block.id }), block.text); tags(p, block); return; }
      var caption = block.caption || {};
      if (block.type === 'list') {
        var wrapper = h('figure', main, { id: block.id });
        var ul = h('ul', wrapper, { 'class': 'gaps' });
        (block.items || []).forEach(function (item) { var li = h('li', ul, { 'data-status': statusOf(item) }); tags(li, item); rich(h('span', li, { 'class': 'val' }), item.text); });
        captionFor(wrapper, block);
        return;
      }
      var fig = h('figure', main, { id: block.id, 'data-block': block.type });
      var label = caption.takeaway || block.id;
      if (block.type === 'graph') graph(fig, block, label);
      else if (block.type === 'swimlane') { swim(fig, block, label); stories.push({ fig: fig, block: block }); }
      else if (block.type === 'bars') bars(fig, block, label);
      else if (block.type === 'table') table(fig, block);
      else if (block.type === 'code') h('pre', fig, null, block.code || '');
      else if (block.type === 'matrix') matrices.push(fig);
      captionFor(fig, block);
    });
  });
  function captionFor(fig, block) {
    var c = block.caption || {};
    var cap = h('figcaption', fig);
    tags(cap, block);
    rich(h('b', cap), c.takeaway || '');
    if (c.text) { cap.appendChild(document.createTextNode(' ')); rich(cap, c.text); }
    if (block.evidence && block.evidence !== 'unverified') cap.appendChild(document.createTextNode(' Evidence: ' + ({ run: 'run', read: 'read in source', search: 'text search' })[block.evidence] + '.'));
  }

  /* ---------- matrix, derived from every swimlane that names a story ---------- */
  matrices.forEach(function (fig) {
    var named = stories.filter(function (s) { return s.block.story; }), comps = {};
    var touched = named.map(function (s) {
      var set = {};
      (s.block.lanes || []).forEach(function (l) { comps[l.title] = l.layer; set[l.title] = 1; });
      return set;
    });
    var cols = Object.keys(comps).sort(function (a, b) { return layerOf(comps[a]).order - layerOf(comps[b]).order; });
    var order = [];
    cols.forEach(function (c) { if (order.indexOf(comps[c]) < 0) order.push(comps[c]); });
    var bar = h('div', null, { 'class': 'bar' }), box = h('div', null, { 'class': 'scroll' }), t = h('table', box, { 'class': 'matrix' });
    fig.insertBefore(box, fig.firstChild);
    fig.insertBefore(bar, box);
    function button(parent, text, attrs) { var b = h('button', parent, attrs, text); b.type = 'button'; return b; }
    var r1 = h('tr', t), r2 = h('tr', t);
    h('th', r1, null, 'Layer'); h('th', r2, null, 'Story');
    order.forEach(function (l) {
      var th = h('th', r1, { 'data-layer': l, 'class': 'lay' });
      th.colSpan = cols.filter(function (c) { return comps[c] === l; }).length;
      button(th, layerOf(l).label, { 'class': 'link', 'data-fl': l });
    });
    cols.forEach(function (c) { button(h('th', r2, { 'class': 'comp', 'data-layer': comps[c], 'data-comp': c }), c, { 'data-fc': c }); });
    named.forEach(function (s, i) {
      var tr = h('tr', t, { 'data-story': s.block.id });
      button(h('th', tr), s.block.story, { 'class': 'link', 'data-go': s.block.id });
      cols.forEach(function (c) { h('td', tr, { 'class': 'm', 'data-layer': comps[c], 'data-comp': c }, touched[i][c] ? '●' : ''); });
    });
    button(bar, 'All', { 'data-fall': '1' });
    order.forEach(function (l) { button(bar, layerOf(l).label, { 'data-fl': l }); });
    var select = h('select', bar, { 'aria-label': 'Filter by component' });
    h('option', select, { value: '' }, 'Component…');
    cols.forEach(function (c) { h('option', select, { value: c }, c); });
    var out = h('span', bar, { 'class': 'out', 'aria-live': 'polite' });
    function filter(kind, value) {
      var rowsEls = t.querySelectorAll('tr[data-story]'), hit = 0;
      t.querySelectorAll('[data-layer]').forEach(function (c) {
        var off = kind === 'layer' ? c.getAttribute('data-layer') !== value : kind === 'comp' ? (c.classList.contains('lay') ? c.getAttribute('data-layer') !== comps[value] : c.getAttribute('data-comp') !== value) : false;
        c.classList.toggle('off', off);
        if (c.classList.contains('lay')) c.colSpan = kind === 'comp' ? 1 : cols.filter(function (x) { return comps[x] === c.getAttribute('data-layer'); }).length;
      });
      rowsEls.forEach(function (tr) {
        var ok = !kind || Array.prototype.some.call(tr.querySelectorAll('td'), function (td) { return td.textContent && (kind === 'layer' ? td.getAttribute('data-layer') === value : td.getAttribute('data-comp') === value); });
        tr.classList.toggle('nomatch', !ok);
        if (ok) hit++;
      });
      out.textContent = kind ? hit + ' of ' + rowsEls.length + ' stories touch ' + (kind === 'layer' ? layerOf(value).label : value) : 'Showing all ' + rowsEls.length + ' stories and ' + cols.length + ' components';
      bar.querySelectorAll('button').forEach(function (b) { b.setAttribute('aria-pressed', String(kind === 'layer' ? b.getAttribute('data-fl') === value : !kind && b.hasAttribute('data-fall'))); });
      select.value = kind === 'comp' ? value : '';
    }
    fig.addEventListener('click', function (e) {
      var b = e.target.closest('button');
      if (!b) return;
      if (b.hasAttribute('data-fall')) filter();
      else if (b.hasAttribute('data-fl')) filter('layer', b.getAttribute('data-fl'));
      else if (b.hasAttribute('data-fc')) filter('comp', b.getAttribute('data-fc'));
      else if (b.hasAttribute('data-go')) go(document.getElementById(b.getAttribute('data-go')));
    });
    select.addEventListener('change', function () { if (select.value) filter('comp', select.value); else filter(); });
    filter();
  });

  /* ---------- stepper ---------- */
  stories.forEach(function (story) {
    var fig = story.fig, nodes = Array.prototype.slice.call(fig.querySelectorAll('.node[data-step]:not(.fx)')), all = fig.querySelectorAll('[data-step]');
    if (!nodes.length) return;
    var current = -1, timer = null, bar = h('div', null, { 'class': 'bar stepper' }), buttons = {};
    ['Back', 'Next', 'Play', 'Show all'].forEach(function (n) { buttons[n] = h('button', bar, { type: 'button' }, n); });
    var out = h('span', bar, { 'class': 'out', 'aria-live': 'polite' });
    fig.insertBefore(bar, fig.querySelector('figcaption'));
    function show(i) {
      current = i;
      all.forEach(function (e) {
        var s = +e.getAttribute('data-step');
        e.classList.toggle('future', i >= 0 && s > i);
        if (e.classList.contains('node')) e.classList.toggle('cur', i >= 0 && s === i && !e.classList.contains('fx'));
      });
      out.textContent = i < 0 ? 'All ' + nodes.length + ' steps shown' : 'Step ' + (i + 1) + ' of ' + nodes.length + '. ' + nodes[i].getAttribute('data-desc');
    }
    function stop() { clearInterval(timer); timer = null; buttons.Play.textContent = 'Play'; }
    buttons.Back.onclick = function () { stop(); show(Math.max(0, current < 0 ? nodes.length - 1 : current - 1)); };
    buttons.Next.onclick = function () { stop(); show(Math.min(nodes.length - 1, current + 1)); };
    buttons['Show all'].onclick = function () { stop(); show(-1); };
    buttons.Play.onclick = function () {
      if (timer) { stop(); return; }
      if (current < 0 || current >= nodes.length - 1) show(0);
      buttons.Play.textContent = 'Pause';
      timer = setInterval(function () { if (current >= nodes.length - 1) stop(); else show(current + 1); }, 1500);
    };
    show(-1);
  });

  /* ---------- trace: connections come from geometry, an arrow belongs to the box its end touches ---------- */
  var tbar = document.getElementById('tracebar'), tcount = document.getElementById('tracecount'), matches = [], matchIndex = 0;
  function boxOf(n) { var r = n.querySelector('rect'); return { x: +r.getAttribute('x'), y: +r.getAttribute('y'), w: +r.getAttribute('width'), h: +r.getAttribute('height') }; }
  function touches(p, b) {
    var T = 1.5, inX = p[0] >= b.x - T && p[0] <= b.x + b.w + T, inY = p[1] >= b.y - T && p[1] <= b.y + b.h + T;
    return (inX && (Math.abs(p[1] - b.y) <= T || Math.abs(p[1] - b.y - b.h) <= T)) || (inY && (Math.abs(p[0] - b.x) <= T || Math.abs(p[0] - b.x - b.w) <= T));
  }
  function clearTrace() { document.querySelectorAll('svg.d .faded,svg.d .sel,svg.d .same').forEach(function (e) { e.classList.remove('faded', 'sel', 'same'); }); tbar.hidden = true; matches = []; }
  function trace(node) {
    var was = node.classList.contains('sel');
    clearTrace();
    if (was) return;
    var svg = node.ownerSVGElement, nodes = Array.prototype.slice.call(svg.querySelectorAll('.node')), me = boxOf(node), keepN = new Set([node]), keepE = new Set();
    svg.querySelectorAll('.eg').forEach(function (g) {
      var pts = g.querySelector('polyline').getAttribute('points').trim().split(/\s+/).map(function (s) { return s.split(',').map(Number); });
      var a = pts[0], z = pts[pts.length - 1], atA = touches(a, me), atZ = touches(z, me);
      if (!atA && !atZ) return;
      keepE.add(g);
      nodes.forEach(function (n) { var b = boxOf(n); if ((atA && touches(z, b)) || (atZ && touches(a, b))) keepN.add(n); });
    });
    nodes.forEach(function (n) { n.classList.toggle('faded', !keepN.has(n)); });
    svg.querySelectorAll('.eg').forEach(function (g) { g.classList.toggle('faded', !keepE.has(g)); });
    node.classList.add('sel');
    var key = node.getAttribute('data-title').trim();
    matches = Array.prototype.filter.call(document.querySelectorAll('svg.d .node'), function (n) { return n.getAttribute('data-title').trim() === key; });
    matches.forEach(function (n) { if (n !== node) n.classList.add('same'); });
    matchIndex = matches.indexOf(node);
    tcount.textContent = (keepN.size - 1) + ' neighbours · ' + matches.length + (matches.length === 1 ? ' box' : ' boxes') + ' named this';
    tbar.hidden = false;
  }
  document.querySelectorAll('svg.d').forEach(function (s) {
    s.addEventListener('click', function (e) { var n = e.target.closest('.node'); if (n) trace(n); else clearTrace(); });
    s.addEventListener('keydown', function (e) { var n = e.target.closest('.node'); if (n && (e.key === 'Enter' || e.key === ' ')) { e.preventDefault(); trace(n); } });
  });
  document.getElementById('traceclear').onclick = clearTrace;
  document.getElementById('tracenext').onclick = function () { if (!matches.length) return; matchIndex = (matchIndex + 1) % matches.length; reveal(matches[matchIndex]); };

  /* ---------- collapsible sections and contents, both read from the rendered page ---------- */
  Array.prototype.slice.call(main.querySelectorAll(':scope > h2')).forEach(function (heading) {
    var section = h('section', null, { 'class': 'sec' }), body = h('div', null, { 'class': 'secbody' });
    while (heading.nextSibling && heading.nextSibling.nodeName !== 'H2') body.appendChild(heading.nextSibling);
    main.insertBefore(section, heading);
    section.appendChild(heading);
    section.appendChild(body);
    heading.setAttribute('data-label', heading.textContent);
    var b = h('button', heading, { type: 'button', 'class': 'sectoggle', 'aria-expanded': 'true' }, 'Collapse');
    b.onclick = function () { setOpen(section, section.classList.contains('closed')); };
  });
  function setOpen(section, open) {
    section.classList.toggle('closed', !open);
    var b = section.querySelector('.sectoggle');
    b.textContent = open ? 'Collapse' : 'Expand';
    b.setAttribute('aria-expanded', String(open));
  }
  function reveal(e) { var s = e.closest('.sec'); if (s && s.classList.contains('closed')) setOpen(s, true); e.scrollIntoView({ block: 'center', inline: 'center' }); }
  var toc = document.getElementById('toc'), fab = document.getElementById('fab'), list = document.getElementById('toclist'), links = [];
  function closeToc() { toc.classList.remove('open'); fab.setAttribute('aria-expanded', 'false'); }
  function go(target) { var s = target.closest('.sec'); if (s && s.classList.contains('closed')) setOpen(s, true); target.scrollIntoView({ block: 'start' }); closeToc(); }
  fab.onclick = function () { fab.setAttribute('aria-expanded', String(toc.classList.toggle('open'))); };
  main.querySelectorAll('h2,h3,figure').forEach(function (e, i) {
    var label, cls;
    if (e.nodeName === 'FIGURE') { var b = e.querySelector('figcaption b'); if (!b || !b.textContent) return; label = b.textContent; cls = 'lf'; }
    else { label = e.getAttribute('data-label') || e.textContent; cls = e.nodeName === 'H2' ? 'l2' : 'l3'; }
    if (!e.id) e.id = 'n' + i;
    var a = h('a', h('li', list, { 'class': cls }), { href: '#' + e.id }, label);
    a.onclick = function (ev) { ev.preventDefault(); go(e); };
    links.push([e, a]);
  });
  var ticking = false, lastCurrent = null;
  function spy() {
    ticking = false;
    var current = links[0];
    for (var i = 0; i < links.length; i++) {
      var e = links[i][0];
      if (!e.offsetParent) continue;
      if (e.getBoundingClientRect().top <= 130) current = links[i]; else break;
    }
    if (current && current[1] !== lastCurrent) {
      if (lastCurrent) lastCurrent.classList.remove('cur');
      lastCurrent = current[1];
      lastCurrent.classList.add('cur');
      if (window.innerWidth >= 1100) { var a = lastCurrent.offsetTop; if (a < toc.scrollTop + 150 || a > toc.scrollTop + toc.clientHeight - 40) toc.scrollTop = a - toc.clientHeight / 2; }
    }
  }
  /* a timer, not requestAnimationFrame, which a hidden or headless page may never fire */
  window.addEventListener('scroll', function () { if (!ticking) { ticking = true; setTimeout(spy, 60); } }, { passive: true });
  spy();
  document.getElementById('collapseAll').onclick = function () { main.querySelectorAll('.sec').forEach(function (s) { setOpen(s, false); }); };
  document.getElementById('expandAll').onclick = function () { main.querySelectorAll('.sec').forEach(function (s) { setOpen(s, true); }); };

  /* ---------- search ---------- */
  var q = document.getElementById('q'), qcount = document.getElementById('qcount'), hits = [], hitIndex = -1, debounce;
  function clearHits() {
    main.querySelectorAll('mark').forEach(function (m) { var p = m.parentNode; p.replaceChild(document.createTextNode(m.textContent), m); p.normalize(); });
    main.querySelectorAll('svg text.hit,svg text.now').forEach(function (t) { t.classList.remove('hit', 'now'); });
    hits = []; hitIndex = -1; qcount.textContent = '';
  }
  function search() {
    clearHits();
    var s = q.value.trim().toLowerCase();
    if (s.length < 2) return;
    var walker = document.createTreeWalker(main, NodeFilter.SHOW_TEXT), nodes = [], n;
    while ((n = walker.nextNode())) nodes.push(n);
    nodes.forEach(function (node) {
      var p = node.parentElement;
      if (p.closest('button,select,.stepper')) return;
      var at = node.nodeValue.toLowerCase().indexOf(s);
      if (at < 0) return;
      if (p.closest('svg')) { var t = p.closest('text'); if (t) { t.classList.add('hit'); hits.push(t); } return; }
      while (at >= 0) {
        var rest = node.splitText(at), after = rest.splitText(s.length), m = document.createElement('mark');
        rest.parentNode.insertBefore(m, rest);
        m.appendChild(rest);
        hits.push(m);
        node = after;
        at = node.nodeValue.toLowerCase().indexOf(s);
      }
    });
    qcount.textContent = hits.length + (hits.length === 1 ? ' match' : ' matches');
  }
  function stepHit(d) {
    if (!hits.length) return;
    if (hitIndex >= 0) hits[hitIndex].classList.remove('now');
    hitIndex = hitIndex < 0 ? (d > 0 ? 0 : hits.length - 1) : (hitIndex + d + hits.length) % hits.length;
    hits[hitIndex].classList.add('now');
    reveal(hits[hitIndex]);
    qcount.textContent = (hitIndex + 1) + ' of ' + hits.length;
  }
  q.addEventListener('input', function () { clearTimeout(debounce); debounce = setTimeout(search, 150); });
  q.addEventListener('keydown', function (e) {
    if (e.key === 'Enter' || e.key === 'ArrowDown') { e.preventDefault(); if (!hits.length) search(); stepHit(e.shiftKey ? -1 : 1); }
    else if (e.key === 'ArrowUp') { e.preventDefault(); stepHit(-1); }
  });
  document.getElementById('qnext').onclick = function () { stepHit(1); };
  document.getElementById('qprev').onclick = function () { stepHit(-1); };
  document.addEventListener('keydown', function (e) {
    if (e.key === '/' && !/INPUT|SELECT|TEXTAREA/.test(document.activeElement.tagName)) { e.preventDefault(); if (window.innerWidth < 1100) { toc.classList.add('open'); fab.setAttribute('aria-expanded', 'true'); } q.focus(); }
    else if (e.key === 'Escape') { if (q.value) { q.value = ''; clearHits(); } q.blur(); clearTrace(); closeToc(); }
  });
  document.documentElement.setAttribute('data-lb-ready', '1');
})();
