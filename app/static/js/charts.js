/* Hand-rolled charts. No chart library, so the easing, stagger and theme all
   match the rest of the page exactly. */

const Charts = (() => {

  /* --- per-person expenditure bars -------------------------------------- */

  function people(host, payload) {
    const { people: rows, currency, per_head: perHead } = payload;
    host.innerHTML = '';
    if (!rows.length) {
      host.innerHTML = '<div class="empty">No expenses yet.</div>';
      return;
    }
    const maxPaid = Math.max(...rows.map((p) => p.paid), 1);

    rows.forEach((person, i) => {
      const row = document.createElement('div');
      row.className = 'person';

      const net = person.net;
      const sign = net >= 0 ? 'pos' : 'neg';
      const verdict = net >= 0
        ? `fronted ${App.moneyShort(net, currency)}`
        : `under by ${App.moneyShort(Math.abs(net), currency)}`;

      row.innerHTML = `
        <div class="avatar" style="border-color:${App.escapeHtml(person.color || '#888')}">
          <img src="${App.escapeHtml(person.avatar_3d || person.avatar || '')}" alt="" loading="lazy" onerror="this.replaceWith(document.createTextNode('${App.escapeHtml(person.initials)}'))">
        </div>
        <div>
          <div class="person-top">
            <span class="nm">${App.escapeHtml(person.name)}</span>
            <span class="delta ${sign}">${verdict}</span>
            <span class="amt num" data-paid="${person.paid}"></span>
          </div>
          <div class="track" style="--person-color:${App.escapeHtml(person.color || 'var(--accent)')}">
            <div class="fill"></div>
            <div class="marker" style="left:${((perHead / maxPaid) * 100).toFixed(2)}%"></div>
          </div>
        </div>`;
      host.appendChild(row);

      const fill = row.querySelector('.fill');
      const amt = row.querySelector('.amt');
      const marker = row.querySelector('.marker');
      const width = (person.paid / maxPaid) * 100;

      // Stagger so the bars cascade rather than all firing at once.
      setTimeout(() => {
        fill.style.width = `${width.toFixed(2)}%`;
        App.countUp(amt, person.paid, { currency, short: true, duration: 1000 });
        marker.classList.add('show');
      }, App.reduceMotion ? 0 : 120 + i * 130);
    });
  }

  /* --- category breakdown ----------------------------------------------- */

  function buckets(host, payload) {
    const { buckets: rows, currency } = payload;
    host.innerHTML = '';
    if (!rows.length) {
      host.innerHTML = '<div class="empty">Nothing categorised yet.</div>';
      return;
    }
    const top = rows[0].amount || 1;

    rows.forEach((bucket, i) => {
      const row = document.createElement('div');
      row.className = 'bucket';
      row.style.setProperty('--c', bucket.colour);
      row.innerHTML = `
        <div class="bucket-top">
          <i class="swatch" style="background:${App.escapeHtml(bucket.colour)}"></i>
          <span>${App.escapeHtml(bucket.label)}</span>
          <span class="pc num">${(bucket.share * 100).toFixed(1)}%</span>
          <span class="amt num">${App.moneyShort(bucket.amount, currency)}</span>
        </div>
        <div class="track"><div class="fill"></div></div>`;
      host.appendChild(row);

      const fill = row.querySelector('.fill');
      setTimeout(() => {
        fill.style.width = `${((bucket.amount / top) * 100).toFixed(2)}%`;
      }, App.reduceMotion ? 0 : 160 + i * 95);
    });
  }

  /* --- daily timeline --------------------------------------------------- */

  function timeline(host, payload) {
    const { days, max, currency } = payload;
    host.innerHTML = '';
    if (!days.length) {
      host.innerHTML = '<div class="empty">No dated expenses yet.</div>';
      return;
    }

    days.forEach((day, i) => {
      const cell = document.createElement('div');
      cell.className = `day${day.amount >= max && max > 0 ? ' peak' : ''}`;
      const modes = day.modes.length
        ? `<span class="t-top">moved by ${day.modes.join(', ')}</span>` : '';
      cell.innerHTML = `
        <div class="tip">
          <b>${App.money(day.amount, currency)}</b> &middot; ${day.count} item${day.count === 1 ? '' : 's'}
          ${day.top ? `<span class="t-top">Top: ${App.escapeHtml(day.top)}</span>` : ''}
          ${modes}
        </div>
        <div class="bar"></div>
        <span class="tick">${App.escapeHtml(day.label.split(' ')[0])}</span>`;
      host.appendChild(cell);

      const bar = cell.querySelector('.bar');
      const pct = max > 0 ? Math.max(2.5, (day.amount / max) * 100) : 2.5;
      setTimeout(() => { bar.style.height = `${pct.toFixed(1)}%`; },
        App.reduceMotion ? 0 : 180 + i * 55);
    });
  }

  /* --- who owes whom ---------------------------------------------------- */

  function settlements(host, payload) {
    const { settlements: rows, currency } = payload;
    host.innerHTML = '';
    if (!rows.length) {
      host.innerHTML = `
        <div class="all-square">
          <svg viewBox="0 0 24 24" width="26" height="26"><use href="#i-check"/></svg>
          <span>Everyone is square. Nothing to settle.</span>
        </div>`;
      return;
    }

    rows.forEach((row, i) => {
      const item = document.createElement('div');
      item.className = 'settle reveal';
      item.style.setProperty('--delay', `${i * 85}ms`);
      item.innerHTML = `
        <span class="who">${App.escapeHtml(row.from_name)}</span>
        <svg class="arrow" viewBox="0 0 24 24" width="17" height="17"><use href="#i-arrow"/></svg>
        <span class="who">${App.escapeHtml(row.to_name)}</span>
        <span class="amt num">${App.money(row.amount, currency)}</span>`;
      host.appendChild(item);
    });
    App.observeReveals(host);
  }

  /* --- settlement arc graph --------------------------------------------- */

  /** People on a circle, debts drawn as curved arrows between them. */
  function settlementGraph(host, payload) {
    const { settlements: rows, balances, currency } = payload;
    host.innerHTML = '';
    if (!balances || balances.length < 2) return;

    const W = 420;
    const H = 300;
    const cx = W / 2;
    const cy = H / 2 + 6;
    const radius = Math.min(W, H) * 0.33;
    const NS = 'http://www.w3.org/2000/svg';

    const svg = document.createElementNS(NS, 'svg');
    svg.setAttribute('viewBox', `0 0 ${W} ${H}`);
    svg.setAttribute('class', 'settle-graph');
    svg.setAttribute('role', 'img');
    svg.setAttribute('aria-label', `${rows.length} transfers settle the group`);

    const pos = new Map();
    balances.forEach((person, i) => {
      const angle = -Math.PI / 2 + (i / balances.length) * Math.PI * 2;
      pos.set(person.id, {
        x: cx + Math.cos(angle) * radius,
        y: cy + Math.sin(angle) * radius,
        person,
      });
    });

    const maxAmount = Math.max(...rows.map((r) => r.amount), 1);

    rows.forEach((row, i) => {
      const a = pos.get(row.from_id);
      const b = pos.get(row.to_id);
      if (!a || !b) return;

      const mx = (a.x + b.x) / 2;
      const my = (a.y + b.y) / 2;
      // Bow the arc away from the centre so opposing debts never overlap.
      const bow = 0.26;
      const kx = mx + (mx - cx) * bow;
      const ky = my + (my - cy) * bow;

      const path = document.createElementNS(NS, 'path');
      path.setAttribute('d', `M ${a.x} ${a.y} Q ${kx} ${ky} ${b.x} ${b.y}`);
      path.setAttribute('class', 'settle-arc');
      path.setAttribute('stroke-width', String(1.6 + (row.amount / maxAmount) * 4.4));
      svg.appendChild(path);

      const len = 400;
      path.style.strokeDasharray = String(len);
      path.style.strokeDashoffset = String(len);
      path.style.setProperty('--delay', `${300 + i * 200}ms`);

      if (!App.reduceMotion) {
        const bead = document.createElementNS(NS, 'circle');
        bead.setAttribute('r', '3.4');
        bead.setAttribute('class', 'settle-bead');
        const motion = document.createElementNS(NS, 'animateMotion');
        motion.setAttribute('dur', '2.6s');
        motion.setAttribute('repeatCount', 'indefinite');
        motion.setAttribute('begin', `${(300 + i * 200) / 1000 + 1.1}s`);
        motion.setAttribute('path', `M ${a.x} ${a.y} Q ${kx} ${ky} ${b.x} ${b.y}`);
        bead.appendChild(motion);
        svg.appendChild(bead);
      }

      const mid = document.createElementNS(NS, 'text');
      mid.setAttribute('x', String(kx));
      mid.setAttribute('y', String(ky - 6));
      mid.setAttribute('class', 'settle-amt');
      mid.textContent = App.moneyShort(row.amount, currency);
      svg.appendChild(mid);
    });

    pos.forEach(({ x, y, person }) => {
      const g = document.createElementNS(NS, 'g');
      g.setAttribute('class', `settle-node ${person.balance >= 0 ? 'cred' : 'debt'}`);

      const personColor = person.color || 'var(--ink-3)';

      // Colored ring behind the avatar. Set via style, not a presentation
      // attribute, so stylesheet rules cannot override the person's colour.
      const ring = document.createElementNS(NS, 'circle');
      ring.setAttribute('cx', String(x));
      ring.setAttribute('cy', String(y));
      ring.setAttribute('r', '23');
      ring.setAttribute('class', 'settle-ring');
      ring.style.stroke = personColor;
      ring.style.strokeWidth = '2.5';
      g.appendChild(ring);

      // The face is a soft wash of the person's colour, so the ring, the wash
      // and the bar on the left all agree even before the avatar loads.
      const bg = document.createElementNS(NS, 'circle');
      bg.setAttribute('cx', String(x));
      bg.setAttribute('cy', String(y));
      bg.setAttribute('r', '21');
      bg.setAttribute('class', 'settle-face');
      bg.style.fill = personColor;
      g.appendChild(bg);

      // Initials sit under the avatar. If the image loads it covers them; if
      // DiceBear is unreachable the person is still identifiable.
      const initials = document.createElementNS(NS, 'text');
      initials.setAttribute('x', String(x));
      initials.setAttribute('y', String(y + 5));
      initials.setAttribute('class', 'settle-ini');
      initials.textContent = person.initials || person.first_name.slice(0, 1);
      g.appendChild(initials);

      if (person.avatar_3d) {
        const clipId = `clip-${person.id}`;
        const clipPath = document.createElementNS(NS, 'clipPath');
        clipPath.setAttribute('id', clipId);
        const clipCircle = document.createElementNS(NS, 'circle');
        clipCircle.setAttribute('cx', String(x));
        clipCircle.setAttribute('cy', String(y));
        clipCircle.setAttribute('r', '20');
        clipPath.appendChild(clipCircle);
        svg.appendChild(clipPath);

        const img = document.createElementNS(NS, 'image');
        img.setAttribute('href', person.avatar_3d);
        img.setAttribute('x', String(x - 20));
        img.setAttribute('y', String(y - 20));
        img.setAttribute('width', '40');
        img.setAttribute('height', '40');
        img.setAttribute('clip-path', `url(#${clipId})`);
        // A broken image would otherwise sit as an empty square over the
        // initials, hiding the only remaining label.
        img.addEventListener('error', () => img.remove());
        g.appendChild(img);
      }

      const name = document.createElementNS(NS, 'text');
      name.setAttribute('x', String(x));
      name.setAttribute('y', String(y + 38));
      name.setAttribute('class', 'settle-name');
      name.textContent = person.first_name;
      g.appendChild(name);

      const bal = document.createElementNS(NS, 'text');
      bal.setAttribute('x', String(x));
      bal.setAttribute('y', String(y + 51));
      bal.setAttribute('class', 'settle-bal');
      bal.textContent = App.moneyShort(person.balance, currency);
      g.appendChild(bal);

      svg.appendChild(g);
    });

    host.appendChild(svg);
  }

  return { people, buckets, timeline, settlements, settlementGraph };
})();
