/* Injected by check_page.py after page.js. Picks every target from the rendered page, so it works
   on any doc. Writes its result into #lb-check. */
setTimeout(function () {
  var out = { failures: [], width: window.innerWidth, diagrams: 0, ran: [] };
  function fail(kind, detail) { out.failures.push(kind + ': ' + detail); }
  try {
    (window.__errors || []).forEach(function (e) { fail('console', e); });
    if (!document.documentElement.hasAttribute('data-lb-ready')) fail('script', 'page script did not finish');
    function R(n) { var r = n.querySelector('rect'); return { x: +r.getAttribute('x'), y: +r.getAttribute('y'), w: +r.getAttribute('width'), h: +r.getAttribute('height'), t: n.getAttribute('data-title') }; }
    function hit(a, b, t) { return a.x < b.x + b.w - t && b.x < a.x + a.w - t && a.y < b.y + b.h - t && b.y < a.y + a.h - t; }
    var svgs = Array.from(document.querySelectorAll('svg.d'));
    out.diagrams = svgs.length;
    svgs.forEach(function (s) {
      var id = (s.closest('figure') || {}).id || '?', vb = s.viewBox.baseVal;
      var nodes = Array.from(s.querySelectorAll('.node')), boxes = nodes.map(R);
      boxes.forEach(function (a, i) { boxes.slice(i + 1).forEach(function (b) { if (hit(a, b, 0.5)) fail('overlap', id + ': ' + a.t + ' / ' + b.t); }); });
      nodes.forEach(function (n, i) {
        n.querySelectorAll('text').forEach(function (t) {
          var b = t.getBBox(), r = boxes[i];
          if (b.x < r.x || b.x + b.width > r.x + r.w + 0.5 || b.y < r.y - 0.5 || b.y + b.height > r.y + r.h + 1.5) fail('clipped', id + ': ' + t.textContent);
        });
      });
      var texts = Array.from(s.querySelectorAll('text'));
      texts.forEach(function (t) { var b = t.getBBox(); if (b.x < -0.5 || b.x + b.width > vb.width + 0.5 || b.y < -1 || b.y + b.height > vb.height + 1) fail('outside drawing', id + ': ' + t.textContent); });
      var free = texts.filter(function (t) { return !t.closest('.node'); }).map(function (t) { var b = t.getBBox(); return { x: b.x, y: b.y + 2, w: b.width, h: b.height - 4, t: t.textContent, g: t.parentNode }; });
      free.forEach(function (a, i) {
        boxes.forEach(function (r) { if (hit(a, r, 1)) fail('label on box', id + ': "' + a.t + '" on ' + r.t); });
        free.slice(i + 1).forEach(function (b) { if (a.g !== b.g && hit(a, b, 1)) fail('label on label', id + ': "' + a.t + '" / "' + b.t + '"'); });
      });
      free.forEach(function (a) {
        if (!a.g.classList.contains('eg')) return;
        var crossed = Array.from(s.querySelectorAll('.eg')).some(function (g) {
          if (g === a.g) return false;
          var pts = g.querySelector('polyline').getAttribute('points').trim().split(/\s+/).map(function (q) { return q.split(',').map(Number); });
          return pts.slice(1).some(function (p, k) {
            return hit(a, { x: Math.min(p[0], pts[k][0]), y: Math.min(p[1], pts[k][1]), w: Math.abs(p[0] - pts[k][0]) || 1, h: Math.abs(p[1] - pts[k][1]) || 1 }, 0.5);
          });
        });
        if (crossed) fail('label on arrow', id + ': "' + a.t + '"');
      });
      s.querySelectorAll('.eg polyline').forEach(function (p) {
        var pts = p.getAttribute('points').trim().split(/\s+/).map(function (q) { return q.split(',').map(Number); });
        for (var k = 0; k < pts.length - 1; k++) {
          for (var u = 0; u <= 1; u += 0.004) {
            var x = pts[k][0] + (pts[k + 1][0] - pts[k][0]) * u, y = pts[k][1] + (pts[k + 1][1] - pts[k][1]) * u;
            var inside = boxes.find(function (r) { return x > r.x + 1.5 && x < r.x + r.w - 1.5 && y > r.y + 1.5 && y < r.y + r.h - 1.5; });
            if (inside) { fail('arrow through box', id + ': ' + inside.t); return; }
          }
        }
        [pts[0], pts[pts.length - 1]].forEach(function (q) {
          var on = boxes.some(function (b) {
            var inX = q[0] >= b.x - 1.5 && q[0] <= b.x + b.w + 1.5, inY = q[1] >= b.y - 1.5 && q[1] <= b.y + b.h + 1.5;
            return (inX && (Math.abs(q[1] - b.y) <= 1.5 || Math.abs(q[1] - b.y - b.h) <= 1.5)) || (inY && (Math.abs(q[0] - b.x) <= 1.5 || Math.abs(q[0] - b.x - b.w) <= 1.5));
          });
          if (!on) fail('loose arrow', id + ': ' + q.join(','));
        });
      });
    });
    var links = Array.from(document.querySelectorAll('#toclist a'));
    if (!links.length) fail('contents', 'no entries');
    links.forEach(function (a) { if (!document.getElementById(a.getAttribute('href').slice(1))) fail('contents', 'dead link ' + a.textContent); });
    if (document.documentElement.scrollWidth > window.innerWidth + 1) fail('overflow', 'the page scrolls sideways');
    if (svgs.length) {
      var smallest = Math.min.apply(null, svgs.map(function (s) { return 11 * s.getBoundingClientRect().width / 1000; }));
      if (smallest < 9) fail('small text', smallest.toFixed(2) + 'px');
    }
    function click(e) { e.dispatchEvent(new MouseEvent('click', { bubbles: true })); }
    if (document.querySelector('svg.d .eg')) {
      var found = Array.from(document.querySelectorAll('svg.d .node')).some(function (n) {
        click(n);
        var ok = /^[1-9]\d* neighbours/.test(document.getElementById('tracecount').textContent) && !document.getElementById('tracebar').hidden;
        document.getElementById('traceclear').click();
        return ok;
      });
      if (!found) fail('trace', 'no box reports a neighbour');
      if (document.querySelector('svg.d .faded')) fail('trace', 'clear left boxes faded');
      out.ran.push('trace');
    }
    var stepper = document.querySelector('.stepper');
    if (stepper) {
      var fig = stepper.closest('figure');
      function press(name) { Array.from(stepper.querySelectorAll('button')).find(function (b) { return b.textContent === name; }).click(); }
      press('Next');
      if (!/^Step 1 of /.test(stepper.querySelector('.out').textContent)) fail('stepper', 'Next did not start at step 1');
      press('Show all');
      if (fig.querySelector('.future')) fail('stepper', 'Show all left steps faded');
      out.ran.push('stepper');
    }
    var matrix = document.querySelector('table.matrix');
    if (matrix && matrix.querySelector('tr[data-story]')) {
      var figure = matrix.closest('figure'), layerButton = figure.querySelector('.bar button[data-fl]');
      click(layerButton);
      if (!/\d+ of \d+ stories touch/.test(figure.querySelector('.bar .out').textContent)) fail('matrix', 'filter reports nothing');
      click(figure.querySelector('.bar button[data-fall]'));
      out.ran.push('matrix');
    }
    var q = document.getElementById('q'), heading = document.querySelector('main h2');
    if (heading) {
      var word = (heading.getAttribute('data-label') || '').split(/\s+/).filter(function (w) { return w.length > 2; })[0];
      if (word) {
        q.value = word;
        q.dispatchEvent(new KeyboardEvent('keydown', { key: 'Enter', bubbles: true }));
        if (!/\d+ of [1-9]/.test(document.getElementById('qcount').textContent)) fail('search', 'no match for a heading word');
        q.dispatchEvent(new KeyboardEvent('keydown', { key: 'Escape', bubbles: true }));
        if (document.querySelector('mark')) fail('search', 'Esc left highlights');
        out.ran.push('search');
      }
      document.getElementById('collapseAll').click();
      if (document.querySelector('.sec:not(.closed)')) fail('collapse', 'a section stayed open');
      document.getElementById('expandAll').click();
      if (document.querySelector('.sec.closed')) fail('collapse', 'a section stayed closed');
      out.ran.push('collapse');
    }
  } catch (error) {
    fail('check crashed', String(error && error.stack || error));
  }
  var pre = document.createElement('pre');
  pre.id = 'lb-check';
  pre.hidden = true;
  pre.textContent = btoa(unescape(encodeURIComponent(JSON.stringify(out))));
  document.body.appendChild(pre);
}, 300);
