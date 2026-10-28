/* ==========================================================================
   Journey map.

   Every line on this map exists because of an expense. Split a Delhi-Bangkok
   flight and a dashed flight arc draws itself between those two nodes with a
   plane crawling along it; hover or click the line and you get the expense
   behind it - amount, date, who paid, and everyone's share.

   An itinerary leg with no expense filed yet still appears, but as a faint
   ghost, so you can see what is planned versus what is paid for.
   ========================================================================== */

const Journey = (() => {
  const NS = 'http://www.w3.org/2000/svg';

  /* Glyphs drawn side-on stay upright; the plane is drawn nose-up so it needs
     turning into the direction of travel. */
  const NOSE_UP = new Set(['plane']);

  function el(name, attrs = {}) {
    const node = document.createElementNS(NS, name);
    for (const [k, v] of Object.entries(attrs)) {
      if (v !== null && v !== undefined) node.setAttribute(k, String(v));
    }
    return node;
  }

  /* --- geometry --------------------------------------------------------- */

  /** Arc between two nodes, trimmed so it starts and ends at the circle edge. */
  function legPath(a, b, arc) {
    const dx = b.x - a.x;
    const dy = b.y - a.y;
    const len = Math.hypot(dx, dy) || 1;
    const ux = dx / len;
    const uy = dy / len;

    const x1 = a.x + ux * (a.r + 5);
    const y1 = a.y + uy * (a.r + 5);
    const x2 = b.x - ux * (b.r + 5);
    const y2 = b.y - uy * (b.r + 5);

    const mx = (x1 + x2) / 2;
    const my = (y1 + y2) / 2;
    // Control point pushed perpendicular to the line; sign flips for return legs.
    const cx = mx + -uy * arc * len;
    const cy = my + ux * arc * len;
    return `M ${x1.toFixed(1)} ${y1.toFixed(1)} Q ${cx.toFixed(1)} ${cy.toFixed(1)} ${x2.toFixed(1)} ${y2.toFixed(1)}`;
  }

  /** A petal looping out of a node and back, for rides inside one city. */
  function localPath(node, index, total, arc) {
    const fan = 1.05;
    const base = -Math.PI / 2 + (index - (total - 1) / 2) * fan;
    const spread = 0.36;
    const reach = node.r + 30 + Math.abs(arc) * 110;

    const a1 = base - spread;
    const a2 = base + spread;
    const p = (ang, dist) => [
      node.x + Math.cos(ang) * dist,
      node.y + Math.sin(ang) * dist,
    ];
    const [x1, y1] = p(a1, node.r + 3);
    const [x2, y2] = p(a2, node.r + 3);
    const [c1x, c1y] = p(a1, reach);
    const [c2x, c2y] = p(a2, reach);
    return `M ${x1.toFixed(1)} ${y1.toFixed(1)} C ${c1x.toFixed(1)} ${c1y.toFixed(1)} ${c2x.toFixed(1)} ${c2y.toFixed(1)} ${x2.toFixed(1)} ${y2.toFixed(1)}`;
  }

  /* --- tooltip --------------------------------------------------------- */

  function buildTooltip(parent) {
    const tip = document.createElement('div');
    tip.className = 'edge-tip';
    tip.setAttribute('role', 'tooltip');
    parent.appendChild(tip);
    return tip;
  }

  function edgeTipHtml(edge, currency) {
    const esc = App.escapeHtml;
    const head = edge.kind === 'local'
      ? esc(edge.label)
      : `${esc(edge.fromName)} <span class="to">&rarr;</span> ${esc(edge.toName)}`;

    const sub = [edge.mode_label, edge.label && edge.kind !== 'local' ? edge.label : '']
      .filter(Boolean).map(esc).join(' &middot; ');

    if (!edge.expenses.length) {
      return `
        <div class="tip-head"><span class="sw" style="background:${esc(edge.colour)}"></span>${head}</div>
        <div class="tip-sub">${sub}</div>
        <div class="tip-ghost">Planned leg &mdash; no expense split for it yet.
        Add it in Splitwise and this line lights up.</div>`;
    }

    const rows = edge.expenses.map((x) => {
      const paid = x.payers && x.payers.length
        ? `${esc(x.payers.join(', '))} paid`
        : 'paid';
      const orig = x.currency && x.currency !== currency
        ? ` <span class="orig">(${App.money(x.original, x.currency)})</span>`
        : '';
      const split = x.shares && x.shares.length > 1
        ? `<span class="split">split ${x.shares.length} ways &middot; ${App.money(x.amount / x.shares.length, currency)} each</span>`
        : '';
      return `
        <div class="tip-row">
          <div class="tip-desc">${esc(x.description)}</div>
          <div class="tip-amt">${App.money(x.amount, currency)}${orig}</div>
          <div class="tip-meta">${App.fmtDate(x.date)} &middot; ${paid} ${split}</div>
        </div>`;
    }).join('');

    const total = edge.expenses.length > 1
      ? `<div class="tip-total"><span>${edge.expenses.length} expenses</span><b>${App.money(edge.cost, currency)}</b></div>`
      : '';

    return `
      <div class="tip-head"><span class="sw" style="background:${esc(edge.colour)}"></span>${head}</div>
      <div class="tip-sub">${sub}</div>
      ${rows}${total}`;
  }

  /* --- main ------------------------------------------------------------ */

  function render(wrap, graph, options = {}) {
    const { onNode = null, interactive = true } = options;
    const currency = graph.currency || 'INR';
    const nodes = new Map(graph.nodes.map((n) => [n.id, n]));

    wrap.innerHTML = '';
    const tip = interactive ? buildTooltip(wrap) : null;

    const svg = el('svg', {
      viewBox: `0 0 ${graph.canvas.width} ${graph.canvas.height}`,
      preserveAspectRatio: 'xMidYMid meet',
      role: 'img',
      'aria-label': `Journey map of ${graph.nodes.length} places connected by ${graph.edges.length} transport lines`,
    });

    /* defs: a soft shadow that gives the white place markers their lift */
    const defs = el('defs');
    const shadow = el('filter', {
      id: 'pinShadow', x: '-60%', y: '-60%', width: '220%', height: '220%',
    });
    shadow.appendChild(el('feDropShadow', {
      dx: '0', dy: '1', stdDeviation: '1.6',
      'flood-color': '#000000', 'flood-opacity': '0.14',
    }));
    defs.appendChild(shadow);
    svg.appendChild(defs);

    const gEdges = el('g', { class: 'edges' });
    const gNodes = el('g', { class: 'nodes' });
    svg.append(gEdges, gNodes);

    /* ---- edges ---- */
    // Local petals need to know how many siblings share their node.
    const localIndex = new Map();
    const localTotals = new Map();
    graph.edges.filter((e) => e.kind === 'local').forEach((e) => {
      const n = localTotals.get(e.from) || 0;
      localIndex.set(e.id, n);
      localTotals.set(e.from, n + 1);
    });

    let delay = 160;
    const edgeEls = [];

    graph.edges.forEach((edge) => {
      const from = nodes.get(edge.from);
      const to = nodes.get(edge.to);
      if (!from || !to) return;

      edge.fromName = from.name;
      edge.toName = to.name;

      const d = edge.kind === 'local'
        ? localPath(from, localIndex.get(edge.id) || 0, localTotals.get(edge.from) || 1, edge.arc)
        : legPath(from, to, edge.arc);

      const g = el('g', {
        class: `edge-g ${edge.has_spend ? '' : 'dim'}`,
        'data-edge': edge.id,
        'data-mode': edge.mode,
      });

      const pathId = `p-${edge.id}`;

      // Faint base so the route reads even before the draw-on finishes.
      g.appendChild(el('path', {
        id: pathId, d, class: 'edge-base',
        stroke: edge.colour, 'stroke-width': 1.2,
        'stroke-opacity': 0.22, fill: 'none',
      }));

      const line = el('path', {
        d, class: 'edge-line',
        stroke: edge.colour,
        'stroke-width': edge.has_spend ? 2.8 : 1.6,
        'stroke-dasharray': edge.dash,
      });
      line.style.setProperty('--delay', `${delay}ms`);
      g.appendChild(line);

      if (edge.has_spend) {
        // Second stroke whose dash offset crawls forever: the route in use.
        const flow = el('path', {
          d, class: 'edge-flow',
          stroke: edge.colour, 'stroke-width': 3,
          'stroke-dasharray': edge.dash,
        });
        flow.style.setProperty('--flow-delay', `${delay + 1200}ms`);
        flow.style.setProperty('--crawl', `${(2.6 / (edge.speed || 1)).toFixed(2)}s`);
        g.appendChild(flow);

        if (!App.reduceMotion) {
          g.appendChild(vehicle(edge, pathId, delay));
        }
      }

      // Wide invisible stroke so thin lines are still easy to hover.
      const hit = el('path', { d, class: 'edge-hit' });
      g.appendChild(hit);

      gEdges.appendChild(g);
      edgeEls.push({ edge, g });
      delay += 150;
    });

    /* ---- nodes ---- */
    graph.nodes.forEach((node, i) => {
      const g = el('g', {
        class: 'node-g node-enter',
        'data-node': node.id,
        tabindex: interactive ? '0' : null,
        role: interactive ? 'button' : null,
        'aria-label': `${node.name}, ${App.money(node.spend, currency)} spent`,
      });
      g.style.setProperty('--delay', `${260 + i * 110}ms`);

      /* Google-Maps-style teardrop: a round head with a tail that comes to a
         point at the place's coordinate.

         The head is deliberately kept inside the same vertical band the old
         circle occupied (roughly node.y +/- node.r). The backend works out
         label sides and canvas clamping from that band, so a taller pin would
         push its own name onto the pin above it. */
      const r = node.r;
      const headR = r * 0.80;
      const headCy = node.y - r * 0.32;   // head centre
      const tipY = node.y + r * 0.82;     // the point

      // Where the tangent lines from the tip meet the head. In the right
      // triangle head-centre / touch-point / tip the right angle is at the
      // touch point, so the angle at the centre is acos(headR / distance).
      const reach = tipY - headCy;
      const a = Math.acos(Math.min(1, headR / reach));
      const sx = node.x - headR * Math.sin(a);
      const sy = headCy + headR * Math.cos(a);
      const ex = node.x + headR * Math.sin(a);

      const pinPath = [
        `M ${sx.toFixed(2)} ${sy.toFixed(2)}`,
        // Major arc, so it sweeps over the top of the head.
        `A ${headR.toFixed(2)} ${headR.toFixed(2)} 0 1 1 ${ex.toFixed(2)} ${sy.toFixed(2)}`,
        `L ${node.x.toFixed(2)} ${tipY.toFixed(2)}`,
        'Z',
      ].join(' ');

      g.appendChild(el('path', { d: pinPath, class: 'node-ring' }));

      // Dot in the head, sized off the head rather than the whole pin.
      g.appendChild(el('circle', {
        cx: node.x, cy: headCy, r: Math.max(2.5, headR * 0.34), class: 'node-core',
      }));

      if (node.spend > 0) {
        const halo = el('circle', {
          cx: node.x, cy: headCy, r: headR + 5, class: 'node-halo',
        });
        halo.style.setProperty('--delay', `${600 + i * 180}ms`);
        g.appendChild(halo);
      }

      /* Labels use the band the backend reserved, not the pin's own bounds,
         so they stay where `label_side` expects them. */
      const below = node.label_side === 'bottom';
      const nameY = below ? node.y + r + 20 : node.y - r - 12;
      const subY = below ? node.y - r - 10 : node.y + r + 18;

      // Bed badge for places with somewhere booked to sleep. Capped in size
      // and tucked into the head's shoulder so it clears the name above.
      if (node.has_stay) {
        const badgeR = Math.max(7, Math.min(10, r * 0.3));
        const bx = node.x + headR * 0.68;
        const by = headCy - headR * 0.68;
        const badge = el('g', { class: 'stay-badge' });
        badge.appendChild(el('circle', { cx: bx, cy: by, r: badgeR, class: 'stay-bg' }));
        const scale = (badgeR * 1.25) / 24;
        const icon = el('g', {
          transform: `translate(${(bx - badgeR * 0.62).toFixed(1)},`
                   + `${(by - badgeR * 0.62).toFixed(1)}) scale(${scale.toFixed(3)})`,
        });
        icon.appendChild(el('use', { href: '#i-bed', class: 'stay-icon' }));
        badge.appendChild(icon);
        g.appendChild(badge);
      }

      const label = el('text', { x: node.x, y: nameY, class: 'node-label' });
      label.textContent = node.name;
      g.appendChild(label);

      const sub = el('text', { x: node.x, y: subY, class: 'node-sub' });
      sub.textContent = node.spend > 0
        ? App.moneyShort(node.spend, currency)
        : (node.gateway ? node.country : '');
      g.appendChild(sub);

      if (interactive && onNode) {
        const fire = () => onNode(node, g);
        g.addEventListener('click', fire);
        g.addEventListener('keydown', (ev) => {
          if (ev.key === 'Enter' || ev.key === ' ') { ev.preventDefault(); fire(); }
        });
      }
      gNodes.appendChild(g);
    });

    wrap.appendChild(svg);

    /* ---- interaction ---- */
    if (interactive && tip) {
      wireTooltips(wrap, svg, tip, edgeEls, currency);
    }

    return { svg, edges: edgeEls, replay: () => replay(svg) };
  }

  /** A glyph that rides the path on a loop. */
  function vehicle(edge, pathId, delay) {
    const holder = el('g', { class: 'vehicle', fill: edge.colour, color: edge.colour });
    const dur = (edge.kind === 'local' ? 5.2 : 7.0) / (edge.speed || 1);

    const motion = el('animateMotion', {
      dur: `${dur.toFixed(2)}s`,
      repeatCount: 'indefinite',
      begin: `${(delay + 900) / 1000}s`,
      rotate: NOSE_UP.has(edge.glyph) ? 'auto' : '0',
      calcMode: 'linear',
    });
    const mpath = el('mpath', { href: `#${pathId}` });
    // Safari still wants the namespaced attribute.
    mpath.setAttributeNS('http://www.w3.org/1999/xlink', 'xlink:href', `#${pathId}`);
    motion.appendChild(mpath);
    holder.appendChild(motion);

    const inner = el('g', {
      // Read right-to-left: centre the 24x24 icon, turn it, then shrink it.
      transform: NOSE_UP.has(edge.glyph)
        ? 'scale(0.78) rotate(90) translate(-12,-12)'
        : 'scale(0.78) translate(-12,-12)',
    });
    inner.appendChild(el('use', { href: `#i-${edge.glyph}` }));
    holder.appendChild(inner);
    return holder;
  }

  function wireTooltips(wrap, svg, tip, edgeEls, currency) {
    let pinned = null;

    const place = (ev) => {
      const box = wrap.getBoundingClientRect();
      const tw = tip.offsetWidth || 260;
      const th = tip.offsetHeight || 120;
      let x = ev.clientX - box.left + 16;
      let y = ev.clientY - box.top + 16;
      if (x + tw > box.width - 8) x = ev.clientX - box.left - tw - 16;
      if (y + th > box.height - 8) y = Math.max(8, ev.clientY - box.top - th - 16);
      tip.style.left = `${Math.max(8, x)}px`;
      tip.style.top = `${y}px`;
    };

    const show = (edge, ev) => {
      tip.innerHTML = edgeTipHtml(edge, currency);
      tip.classList.add('show');
      place(ev);
    };

    const hide = () => {
      if (pinned) return;
      tip.classList.remove('show');
    };

    const focusEdge = (id) => {
      edgeEls.forEach(({ edge, g }) => {
        g.classList.toggle('muted', Boolean(id) && edge.id !== id);
        g.classList.toggle('on', edge.id === id);
      });
    };

    edgeEls.forEach(({ edge, g }) => {
      g.addEventListener('mouseenter', (ev) => { if (!pinned) show(edge, ev); });
      g.addEventListener('mousemove', (ev) => { if (!pinned) place(ev); });
      g.addEventListener('mouseleave', hide);
      g.addEventListener('click', (ev) => {
        ev.stopPropagation();
        if (pinned === edge.id) {
          pinned = null;
          focusEdge(null);
          hide();
        } else {
          pinned = edge.id;
          focusEdge(edge.id);
          show(edge, ev);
          tip.classList.add('pinned');
        }
      });
    });

    svg.addEventListener('click', () => {
      pinned = null;
      focusEdge(null);
      tip.classList.remove('show', 'pinned');
    });

    document.addEventListener('keydown', (ev) => {
      if (ev.key === 'Escape' && pinned) {
        pinned = null;
        focusEdge(null);
        tip.classList.remove('show', 'pinned');
      }
    });
  }

  /** Re-trigger the CSS draw-on animations by cloning the nodes. */
  function replay(svg) {
    svg.querySelectorAll('.edge-line, .edge-flow, .node-enter, .node-halo')
      .forEach((node) => {
        const clone = node.cloneNode(true);
        node.replaceWith(clone);
      });
  }

  /** Legend chips that filter the map by transport mode. */
  function wireLegend(legendEl, svg) {
    if (!legendEl) return;
    const off = new Set();
    legendEl.querySelectorAll('[data-mode]').forEach((chip) => {
      chip.addEventListener('click', () => {
        const mode = chip.dataset.mode;
        if (off.has(mode)) { off.delete(mode); } else { off.add(mode); }
        chip.classList.toggle('off', off.has(mode));
        svg.querySelectorAll('.edge-g').forEach((g) => {
          g.style.display = off.has(g.dataset.mode) ? 'none' : '';
        });
      });
    });
  }

  return { render, wireLegend };
})();
