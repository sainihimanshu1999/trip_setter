/* Journey page: add, edit and delete itinerary places and legs.
 *
 * Mirrors bookings.js: hidden entirely on a static build, which has no
 * backend to send these to -- same reason the itinerary only has one
 * writable copy, in app/seed.py and data/itinerary.json, committed by hand
 * or published from here. After any change this just reloads the page
 * rather than patching the SVG map in place, because the layout (which node
 * sits where) is computed on the server from the whole itinerary at once. */

(() => {
  if (App.isStatic) return;

  document.getElementById('itinerary-actions')?.removeAttribute('hidden');
  document.querySelectorAll('.rail-acts').forEach((el) => el.removeAttribute('hidden'));

  const journey = App.readData('data-journey');

  function reloadSoon(delay = 450) {
    setTimeout(() => window.location.reload(), delay);
  }

  /* --- places ------------------------------------------------------------ */

  const placeDialog = document.getElementById('place-dialog');
  const placeForm = document.getElementById('place-form');
  const placeError = document.getElementById('place-form-error');
  const placeTitle = document.getElementById('place-dialog-title');
  let editingPlaceId = null;

  function openPlaceDialog(place = null) {
    editingPlaceId = place ? place.id : null;
    placeTitle.textContent = place ? 'Edit place' : 'Add a place';
    placeError.style.display = 'none';
    placeForm.reset();
    if (place) {
      placeForm.name.value = place.name || '';
      placeForm.slug.value = place.slug || '';
      placeForm.region.value = place.region || '';
      placeForm.country.value = place.country || '';
      placeForm.lat.value = place.lat ?? '';
      placeForm.lon.value = place.lon ?? '';
      placeForm.arrive_on.value = place.arrive_on || '';
      placeForm.depart_on.value = place.depart_on || '';
      placeForm.nights.value = place.nights ?? 0;
      placeForm.blurb.value = place.blurb || '';
      placeForm.match_terms.value = place.match_terms || '';
      placeForm.order_index.value = place.order_index ?? 0;
    }
    // A fresh place needs a slug nobody has used yet; editing keeps its own.
    placeForm.slug.readOnly = Boolean(place);
    placeDialog.showModal();
    placeForm.name.focus();
  }

  document.getElementById('add-place')?.addEventListener('click', () => openPlaceDialog());
  document.getElementById('place-dialog-cancel').addEventListener('click', () => placeDialog.close());

  placeForm.addEventListener('submit', async (ev) => {
    ev.preventDefault();
    const save = document.getElementById('place-dialog-save');
    save.disabled = true;
    placeError.style.display = 'none';

    const payload = {
      name: placeForm.name.value.trim(),
      slug: placeForm.slug.value.trim().toLowerCase(),
      region: placeForm.region.value.trim(),
      country: placeForm.country.value.trim(),
      lat: Number(placeForm.lat.value),
      lon: Number(placeForm.lon.value),
      arrive_on: placeForm.arrive_on.value || null,
      depart_on: placeForm.depart_on.value || null,
      nights: Number(placeForm.nights.value) || 0,
      blurb: placeForm.blurb.value.trim(),
      match_terms: placeForm.match_terms.value.trim(),
      order_index: Number(placeForm.order_index.value) || 0,
    };

    try {
      if (editingPlaceId) {
        await App.api(`/api/places/${editingPlaceId}`, {
          method: 'PATCH', body: JSON.stringify(payload),
        });
      } else {
        await App.api('/api/places', { method: 'POST', body: JSON.stringify(payload) });
      }
      App.toast(editingPlaceId ? 'Place updated' : 'Place added. Reloading…');
      placeDialog.close();
      reloadSoon();
    } catch (err) {
      placeError.textContent = err.message;
      placeError.style.display = '';
    } finally {
      save.disabled = false;
    }
  });

  // The panel's innerHTML is replaced every time a node is clicked, so its
  // buttons are handled by delegation on the panel itself rather than being
  // bound once at load.
  document.getElementById('place-panel')?.addEventListener('click', async (ev) => {
    const btn = ev.target.closest('[data-act="edit-place"], [data-act="delete-place"]');
    if (!btn) return;
    const id = Number(btn.dataset.placeId);

    if (btn.dataset.act === 'edit-place') {
      try {
        const { places } = await App.api('/api/places');
        const place = places.find((p) => p.id === id);
        if (place) openPlaceDialog(place);
      } catch (err) {
        App.toast(err.message, 'bad');
      }
      return;
    }

    const node = journey.nodes.find((n) => n.place_id === id);
    const name = node ? node.name : 'this place';
    if (!window.confirm(`Delete "${name}"? Any leg touching it is removed too.`)) return;
    try {
      await App.api(`/api/places/${id}`, { method: 'DELETE' });
      App.toast('Place deleted. Reloading…');
      reloadSoon();
    } catch (err) {
      App.toast(err.message, 'bad');
    }
  });

  /* --- legs ---------------------------------------------------------------- */

  const legDialog = document.getElementById('leg-dialog');
  const legForm = document.getElementById('leg-form');
  const legError = document.getElementById('leg-form-error');
  const legTitle = document.getElementById('leg-dialog-title');
  let editingLegId = null;

  function fillPlaceOptions(select, selectedSlug) {
    select.innerHTML = journey.nodes
      .slice()
      .sort((a, b) => a.order - b.order)
      .map((n) => `<option value="${n.id}"${n.id === selectedSlug ? ' selected' : ''}>`
        + `${App.escapeHtml(n.name)}</option>`)
      .join('');
  }

  /** <input type="datetime-local"> wants "YYYY-MM-DDTHH:MM" with no zone. */
  function toLocalInput(iso) {
    return iso ? iso.slice(0, 16) : '';
  }

  function openLegDialog(leg = null) {
    editingLegId = leg ? leg.id : null;
    legTitle.textContent = leg ? 'Edit leg' : 'Add a leg';
    legError.style.display = 'none';
    legForm.reset();
    fillPlaceOptions(legForm.from_slug, leg ? leg.from : null);
    fillPlaceOptions(legForm.to_slug, leg ? leg.to : null);
    if (leg) {
      legForm.mode.value = leg.mode || 'plane';
      legForm.operator.value = leg.operator || '';
      legForm.reference.value = leg.reference || '';
      legForm.depart_at.value = toLocalInput(leg.depart_at);
      legForm.arrive_at.value = toLocalInput(leg.arrive_at);
      legForm.duration_minutes.value = leg.duration_minutes ?? 0;
      legForm.booking_url.value = leg.booking_url || '';
      legForm.notes.value = leg.notes || '';
      legForm.order_index.value = leg.order_index ?? 0;
    }
    legDialog.showModal();
  }

  document.getElementById('add-leg')?.addEventListener('click', () => openLegDialog());
  document.getElementById('leg-dialog-cancel').addEventListener('click', () => legDialog.close());

  legForm.addEventListener('submit', async (ev) => {
    ev.preventDefault();
    const save = document.getElementById('leg-dialog-save');
    save.disabled = true;
    legError.style.display = 'none';

    if (legForm.from_slug.value === legForm.to_slug.value) {
      legError.textContent = 'A leg needs two different places.';
      legError.style.display = '';
      save.disabled = false;
      return;
    }

    const payload = {
      from_slug: legForm.from_slug.value,
      to_slug: legForm.to_slug.value,
      mode: legForm.mode.value,
      operator: legForm.operator.value.trim(),
      reference: legForm.reference.value.trim(),
      depart_at: legForm.depart_at.value || null,
      arrive_at: legForm.arrive_at.value || null,
      duration_minutes: Number(legForm.duration_minutes.value) || 0,
      booking_url: legForm.booking_url.value.trim(),
      notes: legForm.notes.value.trim(),
      order_index: Number(legForm.order_index.value) || 0,
    };

    try {
      if (editingLegId) {
        await App.api(`/api/legs/${editingLegId}`, {
          method: 'PATCH', body: JSON.stringify(payload),
        });
      } else {
        await App.api('/api/legs', { method: 'POST', body: JSON.stringify(payload) });
      }
      App.toast(editingLegId ? 'Leg updated' : 'Leg added. Reloading…');
      legDialog.close();
      reloadSoon();
    } catch (err) {
      legError.textContent = err.message;
      legError.style.display = '';
    } finally {
      save.disabled = false;
    }
  });

  document.querySelector('.rail')?.addEventListener('click', async (ev) => {
    const btn = ev.target.closest('[data-act="edit-leg"], [data-act="delete-leg"]');
    if (!btn) return;
    const id = Number(btn.closest('.rail-item').dataset.legId);

    if (btn.dataset.act === 'edit-leg') {
      try {
        const { legs } = await App.api('/api/legs');
        const leg = legs.find((l) => l.id === id);
        if (leg) openLegDialog(leg);
      } catch (err) {
        App.toast(err.message, 'bad');
      }
      return;
    }

    if (!window.confirm('Delete this leg?')) return;
    try {
      await App.api(`/api/legs/${id}`, { method: 'DELETE' });
      App.toast('Leg deleted. Reloading…');
      reloadSoon();
    } catch (err) {
      App.toast(err.message, 'bad');
    }
  });
})();
