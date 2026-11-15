/* Bookings page: render the cards, filter them, and create/edit/delete. */

(() => {
  let bookings = App.readData('data-bookings') || [];
  const places = App.readData('data-places') || [];
  const kinds = App.readData('data-kinds') || {};

  const grid = document.getElementById('booking-grid');
  const emptyMsg = document.getElementById('booking-empty');
  const dialog = document.getElementById('booking-dialog');
  const form = document.getElementById('booking-form');
  const errorBox = document.getElementById('form-error');
  const dialogTitle = document.getElementById('dialog-title');

  let filter = 'all';
  let editingId = null;
  const docKinds = App.readData('data-doc-kinds') || {};
  let docsBooking = null;

  /* --- rendering -------------------------------------------------------- */

  function card(booking, index) {
    const style = kinds[booking.kind] || { colour: '#717171', glyph: 'dot', label: 'Other' };
    const esc = App.escapeHtml;

    const when = booking.starts_at
      ? (booking.ends_at && booking.ends_at.slice(0, 10) !== booking.starts_at.slice(0, 10)
          ? `${App.fmtDateTime(booking.starts_at)} &rarr; ${App.fmtDate(booking.ends_at)}`
          : App.fmtDateTime(booking.starts_at))
      : 'No date set';

    return `
      <article class="card booking" data-kind="${esc(booking.kind)}" data-id="${booking.id}"
               style="--c:${esc(style.colour)}; --delay:${Math.min(index * 55, 500)}ms">
        <div class="booking-head">
          <span class="booking-icon">
            <svg viewBox="0 0 24 24" width="18" height="18"><use href="#i-${esc(style.glyph)}"/></svg>
          </span>
          <div style="flex:1">
            <h3>${booking.url
              ? `<a href="${esc(booking.url)}" target="_blank" rel="noopener noreferrer">${esc(booking.title)}</a>`
              : esc(booking.title)}</h3>
            <div class="provider">
              ${esc(style.label)}${booking.provider ? ` &middot; ${esc(booking.provider)}` : ''}
            </div>
          </div>
          <span class="status ${esc(booking.status)}">${esc(booking.status)}</span>
        </div>

        ${booking.description ? `<p class="desc">${esc(booking.description)}</p>` : ''}

        <div class="booking-meta">
          <span class="tag">${when}</span>
          ${booking.place ? `<span class="tag">${esc(booking.place)}</span>` : ''}
          ${booking.confirmation ? `<span class="tag">ref ${esc(booking.confirmation)}</span>` : ''}
        </div>

        ${booking.notes ? `<p class="notes">${esc(booking.notes)}</p>` : ''}

        ${docList(booking)}

        <div class="booking-foot">
          <span class="cost num">${booking.cost ? App.money(booking.cost, booking.currency) : 'Free'}</span>
          <span class="acts">
            ${booking.url ? `
              <a class="icon-btn" href="${esc(booking.url)}" target="_blank" rel="noopener noreferrer"
                 title="Open booking" aria-label="Open booking link">
                <svg viewBox="0 0 24 24" width="14" height="14"><use href="#i-link"/></svg>
              </a>` : ''}
            ${App.isStatic ? '' : `
            <button class="icon-btn" data-act="docs" title="Documents" aria-label="Manage documents">
              <svg viewBox="0 0 24 24" width="14" height="14"><use href="#i-paperclip"/></svg>
            </button>
            <button class="icon-btn" data-act="edit" title="Edit" aria-label="Edit booking">
              <svg viewBox="0 0 24 24" width="14" height="14"><use href="#i-edit"/></svg>
            </button>
            <button class="icon-btn danger" data-act="delete" title="Delete" aria-label="Delete booking">
              <svg viewBox="0 0 24 24" width="14" height="14"><use href="#i-trash"/></svg>
            </button>`}
          </span>
        </div>
      </article>`;
  }

  /* --- documents -------------------------------------------------------- */

  function fileSize(bytes) {
    if (!bytes) return '';
    if (bytes >= 1048576) return `${(bytes / 1048576).toFixed(1)} MB`;
    return `${Math.max(1, Math.round(bytes / 1024))} KB`;
  }

  /* One row per attached document. A stored file that is not published is
     marked, because the link works here and will 404 for anyone opening the
     published site -- better to say so than to let it look broken. */
  function docList(booking) {
    const docs = booking.documents || [];
    if (!docs.length) return '';
    const esc = App.escapeHtml;
    return `
      <ul class="docs">
        ${docs.map((d) => {
          const glyph = (docKinds[d.kind] || {}).glyph || 'link';
          const meta = [
            d.is_file ? fileSize(d.size_bytes) : 'link',
            d.is_file && !d.publish ? 'on this machine only' : '',
          ].filter(Boolean).join(' · ');
          return `
            <li class="doc${d.is_file && !d.publish ? ' doc-local' : ''}">
              <svg viewBox="0 0 24 24" width="13" height="13"><use href="#i-${esc(glyph)}"/></svg>
              <a href="${esc(d.href)}" target="_blank" rel="noopener noreferrer">${esc(d.label)}</a>
              <span class="doc-meta">${esc(meta)}</span>
            </li>`;
        }).join('')}
      </ul>`;
  }

  function renderGrid() {
    const visible = bookings.filter((b) => filter === 'all' || b.kind === filter);
    grid.innerHTML = visible.map(card).join('');
    emptyMsg.style.display = visible.length ? 'none' : '';
  }

  function renderAll() {
    renderGrid();
  }

  /* --- filters ---------------------------------------------------------- */

  document.getElementById('filters').addEventListener('click', (ev) => {
    const chip = ev.target.closest('.chip');
    if (!chip) return;
    filter = chip.dataset.filter;
    document.querySelectorAll('#filters .chip').forEach((c) => {
      c.classList.toggle('on', c === chip);
    });
    renderGrid();
  });

  /* --- dialog ----------------------------------------------------------- */

  function openDialog(booking = null) {
    editingId = booking ? booking.id : null;
    dialogTitle.textContent = booking ? 'Edit booking' : 'Add a booking';
    errorBox.style.display = 'none';
    form.reset();

    if (booking) {
      form.title.value = booking.title || '';
      form.kind.value = booking.kind || 'other';
      form.status.value = booking.status || 'confirmed';
      form.provider.value = booking.provider || '';
      form.place_id.value = booking.place_id ?? '';
      form.url.value = booking.url || '';
      form.description.value = booking.description || '';
      form.starts_at.value = toLocalInput(booking.starts_at);
      form.ends_at.value = toLocalInput(booking.ends_at);
      form.cost.value = booking.cost ?? 0;
      form.currency.value = booking.currency || 'THB';
      form.confirmation.value = booking.confirmation || '';
      form.notes.value = booking.notes || '';
    }
    dialog.showModal();
    form.title.focus();
  }

  /** <input type="datetime-local"> wants "YYYY-MM-DDTHH:MM" with no zone. */
  function toLocalInput(iso) {
    if (!iso) return '';
    return iso.slice(0, 16);
  }

  // Creating a booking needs a POST, so in a static build the button is
  // removed rather than left to fail on submit. Bookings come from seed.py,
  // which means editing them is a code change plus a rebuild.
  const addButton = document.getElementById('add-booking');
  if (App.isStatic) {
    addButton.hidden = true;
  } else {
    addButton.addEventListener('click', () => openDialog());
  }
  document.getElementById('dialog-cancel').addEventListener('click', () => dialog.close());

  grid.addEventListener('click', async (ev) => {
    const btn = ev.target.closest('[data-act]');
    if (!btn) return;
    const host = btn.closest('.booking');
    const id = Number(host.dataset.id);
    const booking = bookings.find((b) => b.id === id);
    if (!booking) return;

    if (btn.dataset.act === 'edit') {
      openDialog(booking);
      return;
    }

    if (btn.dataset.act === 'docs') {
      openDocs(booking);
      return;
    }

    if (!window.confirm(`Delete "${booking.title}"? This cannot be undone.`)) return;
    try {
      await App.api(`/api/bookings/${id}`, { method: 'DELETE' });
      bookings = bookings.filter((b) => b.id !== id);
      renderAll();
      App.toast('Booking deleted');
    } catch (err) {
      App.toast(err.message, 'bad');
    }
  });

  /* --- documents dialog ------------------------------------------------- */

  const docsDialog = document.getElementById('docs-dialog');
  const docsForm = document.getElementById('docs-form');
  const docsList = document.getElementById('docs-list');
  const docsTitle = document.getElementById('docs-title');
  const docsError = document.getElementById('docs-error');

  function openDocs(booking) {
    docsBooking = booking;
    docsTitle.textContent = `Documents for ${booking.title}`;
    docsError.style.display = 'none';
    docsForm.reset();
    renderDocsList();
    docsDialog.showModal();
  }

  function renderDocsList() {
    const docs = (docsBooking && docsBooking.documents) || [];
    if (!docs.length) {
      docsList.innerHTML = '<div class="empty">Nothing attached yet.</div>';
      return;
    }
    const esc = App.escapeHtml;
    docsList.innerHTML = docs.map((d) => `
      <div class="doc-row" data-doc="${d.id}">
        <div class="doc-row-main">
          <a href="${esc(d.href)}" target="_blank" rel="noopener noreferrer">${esc(d.label)}</a>
          <span class="doc-meta">
            ${d.is_file ? esc(fileSize(d.size_bytes)) : 'link'}
            ${d.is_file ? ` &middot; ${d.publish ? 'published' : 'this machine only'}` : ''}
          </span>
        </div>
        ${d.is_file ? `
          <label class="doc-toggle" title="Published files are committed and readable by anyone who visits the site">
            <input type="checkbox" data-act="publish" ${d.publish ? 'checked' : ''}>
            publish
          </label>` : ''}
        <button class="icon-btn danger" type="button" data-act="rm" aria-label="Remove document">
          <svg viewBox="0 0 24 24" width="14" height="14"><use href="#i-trash"/></svg>
        </button>
      </div>`).join('');
  }

  function syncBooking(updated) {
    bookings = bookings.map((b) => (b.id === updated.id ? updated : b));
    docsBooking = updated;
    renderDocsList();
    renderAll();
  }

  async function reloadBooking(id) {
    const fresh = await App.api(`/api/bookings/${id}`);
    syncBooking(fresh);
  }

  docsList.addEventListener('click', async (ev) => {
    const btn = ev.target.closest('[data-act="rm"]');
    if (!btn || !docsBooking) return;
    const id = Number(btn.closest('.doc-row').dataset.doc);
    if (!window.confirm('Remove this document? The file is deleted too.')) return;
    try {
      await App.api(`/api/documents/${id}`, { method: 'DELETE' });
      await reloadBooking(docsBooking.id);
      App.toast('Document removed');
    } catch (err) {
      App.toast(err.message, 'bad');
    }
  });

  docsList.addEventListener('change', async (ev) => {
    const box = ev.target.closest('[data-act="publish"]');
    if (!box || !docsBooking) return;
    const id = Number(box.closest('.doc-row').dataset.doc);
    const body = new FormData();
    body.append('publish', box.checked ? 'true' : 'false');
    try {
      await App.api(`/api/documents/${id}`, { method: 'PATCH', body });
      await reloadBooking(docsBooking.id);
      App.toast(box.checked
        ? 'Published. It goes live once you commit and push.'
        : 'Held back. The file stays on this machine.');
    } catch (err) {
      box.checked = !box.checked;
      App.toast(err.message, 'bad');
    }
  });

  docsForm.addEventListener('submit', async (ev) => {
    ev.preventDefault();
    if (!docsBooking) return;
    docsError.style.display = 'none';

    const fd = new FormData(docsForm);
    const file = docsForm.file.files[0];
    const link = (docsForm.url.value || '').trim();

    // The endpoint wants exactly one of the two, so say which is missing here
    // rather than round-tripping for a 422.
    if (!!file === !!link) {
      docsError.textContent = file
        ? 'Choose a file or paste a link, not both.'
        : 'Choose a file or paste a link.';
      docsError.style.display = '';
      return;
    }
    if (!file) fd.delete('file');
    if (!link) fd.delete('url');
    fd.set('publish', docsForm.publish.checked ? 'true' : 'false');

    const submit = document.getElementById('docs-submit');
    submit.disabled = true;
    try {
      await App.api(`/api/bookings/${docsBooking.id}/documents`, {
        method: 'POST', body: fd,
      });
      docsForm.reset();
      await reloadBooking(docsBooking.id);
      App.toast('Document attached');
    } catch (err) {
      docsError.textContent = err.message;
      docsError.style.display = '';
    } finally {
      submit.disabled = false;
    }
  });

  document.getElementById('docs-close')
    .addEventListener('click', () => docsDialog.close());

  form.addEventListener('submit', async (ev) => {    ev.preventDefault();
    const save = document.getElementById('dialog-save');
    save.disabled = true;
    errorBox.style.display = 'none';

    const payload = {
      title: form.title.value.trim(),
      kind: form.kind.value,
      status: form.status.value,
      provider: form.provider.value.trim(),
      place_id: form.place_id.value ? Number(form.place_id.value) : null,
      url: form.url.value.trim(),
      description: form.description.value.trim(),
      starts_at: form.starts_at.value || null,
      ends_at: form.ends_at.value || null,
      cost: Number(form.cost.value) || 0,
      currency: form.currency.value,
      confirmation: form.confirmation.value.trim(),
      notes: form.notes.value.trim(),
    };

    try {
      const saved = editingId
        ? await App.api(`/api/bookings/${editingId}`, {
            method: 'PATCH', body: JSON.stringify(payload),
          })
        : await App.api('/api/bookings', {
            method: 'POST', body: JSON.stringify(payload),
          });

      if (editingId) {
        bookings = bookings.map((b) => (b.id === saved.id ? saved : b));
      } else {
        bookings.push(saved);
      }
      // Keep chronological so the grid stays in trip order.
      bookings.sort((a, b) => {
        if (!a.starts_at) return 1;
        if (!b.starts_at) return -1;
        return a.starts_at.localeCompare(b.starts_at);
      });

      renderAll();
      dialog.close();
      App.toast(editingId ? 'Booking updated' : 'Booking added');
    } catch (err) {
      errorBox.textContent = err.message;
      errorBox.style.display = '';
    } finally {
      save.disabled = false;
    }
  });

  renderAll();
})();
