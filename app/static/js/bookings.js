/* Bookings page: render the cards, filter them, and create/edit/delete. */

(() => {
  let bookings = App.readData('data-bookings') || [];
  const places = App.readData('data-places') || [];
  const kinds = App.readData('data-kinds') || {};

  const grid = document.getElementById('booking-grid');
  const emptyMsg = document.getElementById('booking-empty');
  const rail = document.getElementById('rail');
  const dialog = document.getElementById('booking-dialog');
  const form = document.getElementById('booking-form');
  const errorBox = document.getElementById('form-error');
  const dialogTitle = document.getElementById('dialog-title');

  let filter = 'all';
  let editingId = null;

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

        <div class="booking-foot">
          <span class="cost num">${booking.cost ? App.money(booking.cost, booking.currency) : 'Free'}</span>
          <span class="acts">
            ${booking.url ? `
              <a class="icon-btn" href="${esc(booking.url)}" target="_blank" rel="noopener noreferrer"
                 title="Open booking" aria-label="Open booking link">
                <svg viewBox="0 0 24 24" width="14" height="14"><use href="#i-link"/></svg>
              </a>` : ''}
            ${App.isStatic ? '' : `
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

  function renderGrid() {
    const visible = bookings.filter((b) => filter === 'all' || b.kind === filter);
    grid.innerHTML = visible.map(card).join('');
    emptyMsg.style.display = visible.length ? 'none' : '';
  }

  function renderRail() {
    const dated = bookings
      .filter((b) => b.starts_at && b.status !== 'cancelled')
      .sort((a, b) => a.starts_at.localeCompare(b.starts_at));

    if (!dated.length) {
      rail.innerHTML = '<div class="empty">Add dates to see the timeline.</div>';
      return;
    }
    rail.innerHTML = dated.map((b) => {
      const style = kinds[b.kind] || { colour: '#717171', label: 'Other' };
      return `
        <div class="rail-item" style="--c:${App.escapeHtml(style.colour)}">
          <div class="when">${App.fmtDateTime(b.starts_at)} &middot; ${App.escapeHtml(style.label)}</div>
          <div class="what">${App.escapeHtml(b.title)}</div>
          <div class="when">
            ${b.place ? App.escapeHtml(b.place) : ''}
            ${b.cost ? ` &middot; ${App.money(b.cost, b.currency)}` : ''}
          </div>
        </div>`;
    }).join('');
  }

  function renderAll() {
    renderGrid();
    renderRail();
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

  form.addEventListener('submit', async (ev) => {
    ev.preventDefault();
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
      // Keep chronological so the rail and grid stay sensible.
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
