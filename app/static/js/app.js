/* Shared helpers. Loaded on every page, no dependencies, no build step. */

const App = (() => {
  const reduceMotion = window.matchMedia('(prefers-reduced-motion: reduce)').matches;

  /* Tell the stylesheet that JS is alive and may animate things in. Until this
     class exists, `.reveal` elements render normally, so a broken script can
     never hide the dashboard. Set before first paint to avoid a flash. */
  if (!reduceMotion) document.documentElement.classList.add('anim');

  const SYMBOLS = { INR: '\u20b9', THB: '\u0e3f', USD: '$', EUR: '\u20ac', GBP: '\u00a3', SGD: 'S$', MYR: 'RM', AED: 'AED ' };

  /** Full value with thousands separators: ₹4,37,340 */
  function money(value, currency = 'INR', decimals = 0) {
    const n = Number(value) || 0;
    const sym = SYMBOLS[currency] || currency + ' ';
    const locale = currency === 'INR' ? 'en-IN' : 'en-US';
    const body = Math.abs(n).toLocaleString(locale, {
      minimumFractionDigits: decimals,
      maximumFractionDigits: decimals,
    });
    return (n < 0 ? '-' : '') + sym + body;
  }

  /** Short value for tight spaces: ₹4.37L, ₹43.6k */
  function moneyShort(value, currency = 'INR') {
    const n = Number(value) || 0;
    const sym = SYMBOLS[currency] || currency + ' ';
    const a = Math.abs(n);
    const sign = n < 0 ? '-' : '';
    if (currency === 'INR' && a >= 100000) return `${sign}${sym}${(a / 100000).toFixed(2)}L`;
    if (a >= 1000000) return `${sign}${sym}${(a / 1000000).toFixed(2)}M`;
    if (a >= 1000) return `${sign}${sym}${(a / 1000).toFixed(1)}k`;
    return `${sign}${sym}${Math.round(a)}`;
  }

  /** Count a number up into an element. Skipped entirely under reduced motion. */
  function countUp(el, to, { duration = 1100, currency = 'INR', short = false } = {}) {
    const fmt = short ? moneyShort : money;
    if (reduceMotion || !el) {
      if (el) el.textContent = fmt(to, currency);
      return;
    }
    const from = 0;
    const start = performance.now();
    function frame(now) {
      // Clamped at both ends: a clock that reports a time before `start`
      // would otherwise drive the easing negative and flash a minus sign on
      // a figure that is positive.
      const t = Math.min(1, Math.max(0, (now - start) / duration));
      // easeOutExpo: fast then settles, matches the CSS easing on the bars.
      const eased = t === 1 ? 1 : 1 - Math.pow(2, -10 * t);
      el.textContent = fmt(from + (to - from) * eased, currency);
      if (t < 1) requestAnimationFrame(frame);
    }
    requestAnimationFrame(frame);
  }

  /** Reveal `.reveal` elements as they scroll into view, with a stagger. */
  function observeReveals(root = document) {
    const items = root.querySelectorAll('.reveal:not(.in)');
    if (reduceMotion || !('IntersectionObserver' in window)) {
      items.forEach((el) => el.classList.add('in'));
      return;
    }

    const io = new IntersectionObserver((entries, obs) => {
      entries.forEach((entry) => {
        if (!entry.isIntersecting) return;
        entry.target.classList.add('in');
        obs.unobserve(entry.target);
      });
    }, { threshold: 0.08, rootMargin: '0px 0px -40px 0px' });

    items.forEach((el, i) => {
      if (!el.style.getPropertyValue('--delay')) {
        el.style.setProperty('--delay', `${Math.min(i * 55, 440)}ms`);
      }
      // Anything already in the viewport animates in now. Waiting for the
      // observer's first callback leaves the page visibly empty, and anything
      // that never intersects (because it starts on screen and is never
      // scrolled) would otherwise rely on the failsafe below.
      if (el.getBoundingClientRect().top < window.innerHeight) {
        el.classList.add('in');
      } else {
        io.observe(el);
      }
    });

    // Failsafe: anything still hidden but already on screen after a beat gets
    // shown anyway, so a layout quirk cannot strand content.
    setTimeout(() => {
      root.querySelectorAll('.reveal:not(.in)').forEach((el) => {
        const box = el.getBoundingClientRect();
        if (box.top < window.innerHeight * 1.5) el.classList.add('in');
      });
    }, 1400);
  }

  function toast(message, kind = 'ok') {
    const wrap = document.getElementById('toasts');
    if (!wrap) return;
    const el = document.createElement('div');
    el.className = `toast ${kind}`;
    el.textContent = message;
    wrap.appendChild(el);
    setTimeout(() => el.remove(), 3400);
  }

  /** fetch + JSON + useful errors. Throws with the server's detail message. */
  async function api(path, options = {}) {
    const response = await fetch(path, {
      headers: { 'Content-Type': 'application/json', ...(options.headers || {}) },
      ...options,
    });
    if (response.status === 204) return null;
    let payload = null;
    try { payload = await response.json(); } catch { /* empty body */ }
    if (!response.ok) {
      const detail = payload && (payload.detail || payload.error);
      throw new Error(formatDetail(detail) || `Request failed (${response.status})`);
    }
    return payload;
  }

  /** FastAPI validation errors arrive as a list of objects. */
  function formatDetail(detail) {
    if (!detail) return '';
    if (typeof detail === 'string') return detail;
    if (Array.isArray(detail)) {
      return detail.map((d) => {
        const field = Array.isArray(d.loc) ? d.loc.filter((p) => p !== 'body').join('.') : '';
        return field ? `${field}: ${d.msg}` : d.msg;
      }).join('; ');
    }
    return String(detail);
  }

  function escapeHtml(text) {
    const div = document.createElement('div');
    div.textContent = text == null ? '' : String(text);
    return div.innerHTML;
  }

  function fmtDate(iso, opts = { day: 'numeric', month: 'short' }) {
    if (!iso) return '';
    const d = new Date(iso);
    if (Number.isNaN(d.getTime())) return '';
    return d.toLocaleDateString('en-GB', opts);
  }

  function fmtDateTime(iso) {
    if (!iso) return '';
    const d = new Date(iso);
    if (Number.isNaN(d.getTime())) return '';
    return d.toLocaleString('en-GB', {
      day: 'numeric', month: 'short', hour: '2-digit', minute: '2-digit', hour12: false,
    });
  }

  /** Read a JSON <script type="application/json"> block rendered by Jinja. */
  function readData(id) {
    const node = document.getElementById(id);
    if (!node) return null;
    try { return JSON.parse(node.textContent); } catch { return null; }
  }

  function initRefresh() {
    const btn = document.getElementById('refresh');
    if (!btn) return;
    btn.addEventListener('click', async () => {
      const icon = btn.querySelector('svg');
      btn.disabled = true;
      icon?.classList.add('spin');
      try {
        const result = await api('/api/refresh', { method: 'POST' });
        toast(`Reloaded ${result.expense_count} expenses from ${result.source === 'demo' ? 'sample data' : 'Splitwise'}`);
        setTimeout(() => window.location.reload(), 700);
      } catch (err) {
        toast(err.message, 'bad');
        btn.disabled = false;
        icon?.classList.remove('spin');
      }
    });
  }

  /** Light/dark toggle. The saved choice is applied inline in <head>; this
      only handles clicks and keeps the button's label honest. */
  function initTheme() {
    const btn = document.getElementById('theme-toggle');
    if (!btn) return;
    const root = document.documentElement;
    const systemDark = window.matchMedia('(prefers-color-scheme: dark)');

    const isDark = () => (root.dataset.theme
      ? root.dataset.theme === 'dark'
      : systemDark.matches);

    const label = () => {
      btn.setAttribute('aria-pressed', String(isDark()));
      btn.title = isDark() ? 'Switch to light' : 'Switch to dark';
    };

    btn.addEventListener('click', () => {
      const next = isDark() ? 'light' : 'dark';
      root.dataset.theme = next;
      try { localStorage.setItem('trip-theme', next); } catch { /* ignore */ }
      label();
    });

    // Follow the OS while the user has not expressed a preference.
    systemDark.addEventListener('change', () => { if (!root.dataset.theme) label(); });
    label();
  }

  /* --- static build: no server behind the page ------------------------- */

  /** True when this page came out of scripts/build_static.py. */
  const isStatic = document.documentElement.dataset.static === '1';

  const TOKEN_KEY = 'trip-gh-token';
  const REPO_KEY = 'trip-gh-repo';
  /** Where the upload writes. Must match SPLITWISE_CSV_PATH in the build. */
  const CSV_PATH = 'data/expenses.csv';
  const MAX_CSV_BYTES = 2 * 1024 * 1024;

  /** Base64 of raw bytes, safe for non-ASCII names in the CSV. */
  function toBase64(buffer) {
    const bytes = new Uint8Array(buffer);
    let binary = '';
    for (let i = 0; i < bytes.length; i += 0x8000) {
      binary += String.fromCharCode.apply(null, bytes.subarray(i, i + 0x8000));
    }
    return btoa(binary);
  }

  async function github(path, token, options = {}) {
    const response = await fetch(`https://api.github.com${path}`, {
      ...options,
      headers: {
        Accept: 'application/vnd.github+json',
        Authorization: `Bearer ${token}`,
        'X-GitHub-Api-Version': '2022-11-28',
        ...(options.headers || {}),
      },
    });
    const payload = await response.json().catch(() => null);
    if (!response.ok) {
      const detail = (payload && payload.message) || `HTTP ${response.status}`;
      const hint = response.status === 401 || response.status === 403
        ? ' Check the token is valid and has Contents: read and write on this repository.'
        : response.status === 404
          ? ' Check the repository name, and that the token can see it.'
          : '';
      throw new Error(detail + hint);
    }
    return payload;
  }

  /** Commit the CSV, replacing whatever is there. */
  async function commitCsv(file, token, repo, say) {
    const contents = `/repos/${repo}/contents/${CSV_PATH}`;

    say('Reading the file…');
    const base64 = toBase64(await file.arrayBuffer());

    // The API needs the blob SHA to replace an existing file. A 404 here just
    // means this is the first upload.
    say('Looking up the current file…');
    let sha;
    try {
      sha = (await github(`${contents}?ref=HEAD`, token)).sha;
    } catch (err) {
      if (!/not found/i.test(err.message)) throw err;
    }

    say('Committing…');
    const stamp = new Date().toISOString().slice(0, 16).replace('T', ' ');
    await github(contents, token, {
      method: 'PUT',
      body: JSON.stringify({
        message: `Update expenses from ${file.name} (${stamp})`,
        content: base64,
        ...(sha ? { sha } : {}),
      }),
    });
  }

  function initUpload() {
    const open = document.getElementById('open-upload');
    const refresh = document.getElementById('refresh');
    if (!isStatic || !open) return;

    // Refresh re-reads the CSV server-side, which there is no longer one of.
    if (refresh) refresh.hidden = true;
    open.hidden = false;

    const dialog = document.getElementById('upload-dialog');
    const form = document.getElementById('upload-form');
    const fileInput = document.getElementById('up-file');
    const tokenInput = document.getElementById('up-token');
    const repoField = document.getElementById('up-repo-field');
    const repoInput = document.getElementById('up-repo-input');
    const repoLabel = document.getElementById('up-repo');
    const status = document.getElementById('up-status');
    const submit = document.getElementById('up-submit');

    const say = (message, kind = '') => {
      status.textContent = message;
      status.className = `up-status ${kind}`;
    };

    // The build bakes the repo in; fall back to asking once.
    const baked = document.documentElement.dataset.repo || '';
    const repoOf = () => baked || repoInput.value.trim()
      || localStorage.getItem(REPO_KEY) || '';

    if (baked) {
      repoLabel.textContent = baked;
    } else {
      repoField.hidden = false;
      repoInput.value = localStorage.getItem(REPO_KEY) || '';
    }

    // Fallback that needs no token: GitHub's own upload page, authenticated
    // by the session the user already has. Dropping a file named
    // expenses.csv there replaces the committed one.
    const webLink = document.getElementById('up-web');
    const setWebLink = () => {
      const repo = repoOf();
      const folder = CSV_PATH.replace(/\/[^/]*$/, '');
      webLink.href = repo
        ? `https://github.com/${repo}/upload/main/${folder}`
        : 'https://github.com';
    };
    setWebLink();
    if (!baked) repoInput.addEventListener('input', setWebLink);

    open.addEventListener('click', () => {
      try { tokenInput.value = localStorage.getItem(TOKEN_KEY) || ''; } catch { /* ignore */ }
      say('');
      dialog.showModal();
    });

    document.getElementById('up-cancel').addEventListener('click', () => dialog.close());

    document.getElementById('up-forget').addEventListener('click', () => {
      try { localStorage.removeItem(TOKEN_KEY); } catch { /* ignore */ }
      tokenInput.value = '';
      say('Token forgotten.', 'ok');
    });

    form.addEventListener('submit', async (event) => {
      event.preventDefault();
      const file = fileInput.files && fileInput.files[0];
      const token = tokenInput.value.trim();
      const repo = repoOf();

      if (!file) return say('Choose a CSV first.', 'bad');
      if (file.size > MAX_CSV_BYTES) return say('That file is too big to be a Splitwise export.', 'bad');
      if (!token) return say('A token is needed to commit.', 'bad');
      if (!/^[\w.-]+\/[\w.-]+$/.test(repo)) return say('Repository should look like owner/trip_setter.', 'bad');

      submit.disabled = true;
      try {
        await commitCsv(file, token, repo, say);
        try {
          localStorage.setItem(TOKEN_KEY, token);
          localStorage.setItem(REPO_KEY, repo);
        } catch { /* private mode */ }
        say('Committed. GitHub is rebuilding the site, usually a minute or '
          + 'two. Reload after that to see the new numbers.', 'ok');
        toast('Export committed, rebuild started');
      } catch (err) {
        say(err.message, 'bad');
      } finally {
        submit.disabled = false;
      }
    });
  }

  document.addEventListener('DOMContentLoaded', () => {
    observeReveals();
    initRefresh();
    initTheme();
    initUpload();
  });

  return {
    reduceMotion, isStatic, money, moneyShort, countUp, observeReveals,
    toast, api, escapeHtml, fmtDate, fmtDateTime, readData, formatDetail,
  };
})();
