(async function () {
  const root = document.getElementById('camera-edit');
  const cameraId = Number(root.dataset.cameraId);
  let camera = null;
  let editor = null;
  let _activeTrainZoneId = null;

  async function load() {
    const [camRes, zonesRes] = await Promise.all([
      fetch('/api/cameras/' + cameraId),
      fetch('/api/cameras/' + cameraId + '/zones'),
    ]);
    if (!camRes.ok) { root.innerHTML = '<p>Camera not found.</p>'; return; }
    camera = await camRes.json();
    const zones = zonesRes.ok ? await zonesRes.json() : [];
    document.getElementById('camera-name').textContent = camera.name;
    render(zones);
  }

  function render(zones) {
    root.innerHTML = `
      <div class="card">
        <h2>Settings</h2>
        <form id="edit-form">
          <div class="row">
            <div><label>Name</label><input name="name" value="${escapeHtml(camera.name)}"></div>
            <div><label>RTSP URL</label><input name="rtsp_url" value="${escapeHtml(camera.rtsp_url)}"></div>
          </div>
          <div class="row">
            <div><label>Enabled</label><select name="enabled">
              <option value="1" ${camera.enabled ? 'selected' : ''}>enabled</option>
              <option value="0" ${!camera.enabled ? 'selected' : ''}>disabled</option>
            </select></div>
            <div><label>Target FPS</label><input name="target_fps" type="number" step="0.5" min="0" max="30" value="${camera.target_fps}"></div>
            <div><label>Model</label><input name="model" value="${escapeHtml(camera.model)}"></div>
            <div><label>Detection classes</label><div id="edit-classes-picker"></div></div>
            <div><label>Hysteresis (s)</label><input name="hysteresis_s" type="number" step="0.5" min="0.5" max="120" value="${camera.hysteresis_s}"></div>
          </div>
          <button class="primary" type="submit">Save</button>
          <button class="probe" type="button">Probe RTSP</button>
          <span class="probe-result"></span>
        </form>
      </div>

      <div class="card">
        <h2>Live preview</h2>
        <img id="preview" class="snapshot" alt="preview">
        <label style="margin-top:0.5rem"><input type="checkbox" id="show-boxes" checked> show boxes</label>
      </div>

      <div class="card">
        <h2>Zones</h2>
        <table>
          <thead><tr><th>ID</th><th>Name</th><th>Type</th><th>Current state</th><th>Vertices</th><th></th></tr></thead>
          <tbody id="zones-body"></tbody>
        </table>
      </div>

      <div id="train-panel-host"></div>

      <div class="card">
        <h2>Draw a new zone</h2>
        <p style="color:var(--muted);font-size:0.88rem">
          <strong style="color:inherit">Click</strong> to add vertices &nbsp;·&nbsp;
          <strong style="color:inherit">Double-click</strong> or <strong style="color:inherit">right-click</strong> on the last point to close the polygon &nbsp;·&nbsp;
          <strong style="color:inherit">Drag</strong> a vertex to move it &nbsp;·&nbsp;
          <strong style="color:inherit">Z</strong> to undo last vertex &nbsp;·&nbsp;
          <strong style="color:inherit">Esc</strong> to cancel
        </p>
        <p style="color:var(--muted);font-size:0.88rem">
          <strong style="color:#7ec6e2">Detection</strong> — trigger YOLO alerts when an object enters this area.<br>
          <strong style="color:#c07ee2">State (few-shot)</strong> — capture a few example images of each state (e.g. "closed", "open"). The system classifies the zone by comparing to your examples.
        </p>
        <div id="zone-editor-host"></div>
      </div>
    `;

    const tbody = root.querySelector('#zones-body');
    if (zones.length === 0) {
      tbody.innerHTML = '<tr><td colspan="6">No zones yet.</td></tr>';
    } else {
      for (const z of zones) {
        const tr = document.createElement('tr');
        tr.dataset.zoneId = z.id;
        tr.dataset.zoneType = z.zone_type;
        const labels = z.state_labels ? z.state_labels.join(' / ') : '';
        const stateCell = z.zone_type === 'state'
          ? `<span class="muted" title="${escapeHtml(labels)}">waiting…</span>`
          : '—';
        const trainBtn = z.zone_type === 'state'
          ? `<button class="secondary train-btn" data-zone-id="${z.id}" style="margin-right:0.4rem">Train</button>`
          : '';
        tr.innerHTML = `
          <td>${z.id}</td>
          <td>${escapeHtml(z.name)}</td>
          <td><span class="badge ${z.zone_type === 'state' ? 'badge-state' : 'badge-det'}">${z.zone_type}</span></td>
          <td class="zone-state-cell">${stateCell}</td>
          <td>${z.polygon.length}</td>
          <td style="white-space:nowrap">${trainBtn}<button class="danger del-btn" data-zone-id="${z.id}">Delete</button></td>
        `;
        tbody.appendChild(tr);
      }

      tbody.querySelectorAll('.del-btn').forEach(b => b.addEventListener('click', async e => {
        const id = e.currentTarget.dataset.zoneId;
        if (!confirm('Delete zone #' + id + '?')) return;
        await fetch('/api/zones/' + id, { method: 'DELETE' });
        load();
      }));

      tbody.querySelectorAll('.train-btn').forEach(b => b.addEventListener('click', e => {
        const zoneId = Number(e.currentTarget.dataset.zoneId);
        const zone = zones.find(z => z.id === zoneId);
        if (zone) trainZone(zone);
      }));

      if (zones.some(z => z.zone_type === 'state')) {
        pollStates(zones);
      }
    }

    let classPicker = null;
    ClassPicker.create(root.querySelector('#edit-classes-picker'), camera.classes).then(p => { classPicker = p; });
    root.querySelector('#edit-form').addEventListener('submit', e => onSave(e, classPicker));
    root.querySelector('.probe').addEventListener('click', onProbe);

    editor = ZoneEditor.create(
      root.querySelector('#zone-editor-host'),
      '/api/cameras/' + cameraId + '/snapshot.jpg'
    );
    editor.onSave(async (data) => {
      const res = await fetch('/api/cameras/' + cameraId + '/zones', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(data),
      });
      if (!res.ok) { alert('Save failed: ' + await res.text()); return; }
      editor.resetCurrent();
      load();
    });

    startPreview(root.querySelector('#preview'), root.querySelector('#show-boxes'));
  }

  // ── Training panel ───────────────────────────────────────────────────────────

  async function trainZone(zone) {
    _activeTrainZoneId = zone.id;
    const host = root.querySelector('#train-panel-host');
    const labels = zone.state_labels || [];

    const card = document.createElement('div');
    card.className = 'card';
    card.id = 'train-panel';
    card.innerHTML = `
      <div style="display:flex;justify-content:space-between;align-items:center;margin-bottom:0.75rem">
        <h2 style="margin:0">Train: ${escapeHtml(zone.name)}</h2>
        <button class="secondary close-train">Close</button>
      </div>
      <p style="color:var(--muted);font-size:0.88rem;margin-top:0">
        Point the camera at the zone in each state, then click <em>Capture</em>. 3–5 examples per label gives better accuracy.
      </p>
      <div style="display:flex;gap:1rem;align-items:flex-start;flex-wrap:wrap">
        <div>
          <div style="font-weight:600;margin-bottom:0.35rem;font-size:0.88rem;color:var(--muted)">Zone crop preview</div>
          <canvas id="train-crop-canvas" style="border:1px solid var(--border);border-radius:4px;max-width:320px;display:block"></canvas>
          <button class="secondary" id="refresh-crop" style="margin-top:0.4rem;font-size:0.82rem">Refresh snapshot</button>
        </div>
        <div style="flex:1;min-width:180px">
          <div id="label-rows"></div>
          <div style="margin-top:0.75rem">
            <button class="danger" id="clear-samples">Clear all examples</button>
          </div>
          <div id="train-status" style="margin-top:0.75rem;font-size:0.88rem"></div>
        </div>
      </div>
    `;
    host.innerHTML = '';
    host.appendChild(card);
    host.scrollIntoView({ behavior: 'smooth', block: 'start' });

    card.querySelector('.close-train').addEventListener('click', () => {
      host.innerHTML = '';
      _activeTrainZoneId = null;
    });

    card.querySelector('#refresh-crop').addEventListener('click', () => refreshCrop(zone));
    card.querySelector('#clear-samples').addEventListener('click', async () => {
      if (!confirm('Delete all training examples for this zone?')) return;
      await fetch('/api/zones/' + zone.id + '/samples', { method: 'DELETE' });
      await refreshCounts(zone, labels);
    });

    // Build per-label capture buttons
    const labelRows = card.querySelector('#label-rows');
    for (const lbl of labels) {
      const row = document.createElement('div');
      row.style.cssText = 'display:flex;align-items:center;gap:0.75rem;margin-bottom:0.5rem';
      row.dataset.label = lbl;
      row.innerHTML = `
        <button class="primary capture-btn" style="min-width:140px">Capture as "${escapeHtml(lbl)}"</button>
        <span class="count-badge" style="font-size:0.85rem;color:var(--muted)">0 examples</span>
      `;
      row.querySelector('.capture-btn').addEventListener('click', async () => {
        const blob = await grabCrop(zone);
        if (!blob) { alert('Could not capture crop. Is the camera running?'); return; }
        const btn = row.querySelector('.capture-btn');
        btn.disabled = true;
        btn.textContent = 'saving…';
        await fetch('/api/zones/' + zone.id + '/samples?label=' + encodeURIComponent(lbl), {
          method: 'POST',
          headers: { 'Content-Type': 'image/jpeg' },
          body: blob,
        });
        btn.disabled = false;
        btn.textContent = `Capture as "${lbl}"`;
        await refreshCounts(zone, labels);
      });
      labelRows.appendChild(row);
    }

    await refreshCrop(zone);
    await refreshCounts(zone, labels);
  }

  async function refreshCrop(zone) {
    const canvas = root.querySelector('#train-crop-canvas');
    if (!canvas) return;
    const img = new Image();
    img.crossOrigin = 'anonymous';
    img.src = '/api/cameras/' + cameraId + '/snapshot.jpg?t=' + Date.now();
    await new Promise(res => { img.onload = res; img.onerror = res; });
    const { x1, y1, cropW, cropH } = computeBbox(zone.polygon, img.naturalWidth, img.naturalHeight);
    canvas.width = cropW || 320;
    canvas.height = cropH || 240;
    const ctx = canvas.getContext('2d');
    ctx.drawImage(img, x1, y1, cropW, cropH, 0, 0, cropW, cropH);
  }

  async function grabCrop(zone) {
    const img = new Image();
    img.crossOrigin = 'anonymous';
    img.src = '/api/cameras/' + cameraId + '/snapshot.jpg?t=' + Date.now();
    await new Promise(res => { img.onload = res; img.onerror = res; });
    if (!img.naturalWidth) return null;
    const { x1, y1, cropW, cropH } = computeBbox(zone.polygon, img.naturalWidth, img.naturalHeight);
    if (cropW <= 0 || cropH <= 0) return null;
    const canvas = document.createElement('canvas');
    canvas.width = cropW;
    canvas.height = cropH;
    canvas.getContext('2d').drawImage(img, x1, y1, cropW, cropH, 0, 0, cropW, cropH);
    return new Promise(res => canvas.toBlob(res, 'image/jpeg', 0.92));
  }

  function computeBbox(polygon, natW, natH) {
    const xs = polygon.map(([x]) => Math.round(x * natW));
    const ys = polygon.map(([, y]) => Math.round(y * natH));
    const x1 = Math.max(0, Math.min(...xs));
    const y1 = Math.max(0, Math.min(...ys));
    const x2 = Math.min(natW, Math.max(...xs));
    const y2 = Math.min(natH, Math.max(...ys));
    return { x1, y1, cropW: x2 - x1, cropH: y2 - y1 };
  }

  async function refreshCounts(zone, labels) {
    const panel = root.querySelector('#train-panel');
    if (!panel) return;
    const res = await fetch('/api/zones/' + zone.id + '/samples');
    if (!res.ok) return;
    const samples = await res.json();

    const counts = {};
    for (const s of samples) counts[s.label] = (counts[s.label] || 0) + 1;

    for (const lbl of labels) {
      const row = panel.querySelector(`[data-label="${CSS.escape(lbl)}"]`);
      if (!row) continue;
      const n = counts[lbl] || 0;
      row.querySelector('.count-badge').textContent = n + (n === 1 ? ' example' : ' examples');
    }

    const missing = labels.filter(l => !counts[l]);
    const statusEl = panel.querySelector('#train-status');
    if (missing.length === 0) {
      statusEl.innerHTML = '<span style="color:#4caf50">Ready ✓ — classifier will activate on next check cycle.</span>';
    } else {
      statusEl.innerHTML = `<span style="color:var(--muted)">Need examples for: <strong>${missing.map(escapeHtml).join(', ')}</strong></span>`;
    }
  }

  // ── Camera settings ──────────────────────────────────────────────────────────

  async function onSave(e, classPicker) {
    e.preventDefault();
    const fd = new FormData(e.target);
    const classes = classPicker ? classPicker.selected() : camera.classes;
    if (classes.length === 0) { alert('Select at least one detection class.'); return; }
    const body = {
      name: fd.get('name'),
      rtsp_url: fd.get('rtsp_url'),
      enabled: fd.get('enabled') === '1',
      target_fps: Number(fd.get('target_fps')),
      model: fd.get('model'),
      classes,
      hysteresis_s: Number(fd.get('hysteresis_s')),
    };
    const res = await fetch('/api/cameras/' + cameraId, {
      method: 'PATCH',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(body),
    });
    if (!res.ok) { alert('Save failed: ' + await res.text()); return; }
    load();
  }

  async function onProbe(e) {
    const span = root.querySelector('.probe-result');
    span.textContent = 'probing…';
    const res = await fetch('/api/cameras/' + cameraId + '/probe', { method: 'POST' });
    const j = await res.json();
    if (j.ok) {
      span.className = 'status-ok';
      span.textContent = `ok — ${j.width}×${j.height}`;
    } else {
      span.className = 'status-bad';
      span.textContent = 'failed: ' + (j.error || 'unknown');
    }
  }

  // ── State polling ────────────────────────────────────────────────────────────

  let _stateTimer = null;
  function pollStates(zones) {
    if (_stateTimer) clearInterval(_stateTimer);
    async function refresh() {
      try {
        const res = await fetch('/api/cameras/' + cameraId + '/zones/states');
        if (!res.ok) return;
        const data = await res.json();
        for (const [zid, state] of Object.entries(data)) {
          const tr = root.querySelector(`tr[data-zone-id="${zid}"]`);
          if (!tr) continue;
          const cell = tr.querySelector('.zone-state-cell');
          if (!cell) continue;
          if (!state) { cell.innerHTML = '<span class="muted">waiting…</span>'; continue; }
          const ranked = state.ranked.map(([l, p]) => `${escapeHtml(l)} ${p}%`).join(' · ');
          cell.innerHTML = `<strong>${escapeHtml(state.label)}</strong> <span class="muted">${state.prob}%</span><br><small class="muted">${ranked}</small>`;
        }
      } catch (_) {}
    }
    refresh();
    _stateTimer = setInterval(refresh, 2000);
  }

  // ── Live preview ─────────────────────────────────────────────────────────────

  function startPreview(imgEl, boxesCheckbox) {
    let ws = null;
    function connect() {
      const boxes = boxesCheckbox.checked ? '1' : '0';
      const proto = location.protocol === 'https:' ? 'wss:' : 'ws:';
      ws = new WebSocket(`${proto}//${location.host}/ws/preview/${cameraId}?boxes=${boxes}`);
      ws.binaryType = 'arraybuffer';
      ws.onmessage = ev => {
        const blob = new Blob([ev.data], { type: 'image/jpeg' });
        const url = URL.createObjectURL(blob);
        imgEl.onload = () => URL.revokeObjectURL(url);
        imgEl.src = url;
      };
      ws.onclose = () => { setTimeout(connect, 1500); };
      ws.onerror = () => { try { ws.close(); } catch (_) {} };
    }
    connect();
    boxesCheckbox.addEventListener('change', () => {
      if (ws) try { ws.close(); } catch (_) {}
    });
  }

  function escapeHtml(s) {
    return String(s).replace(/[&<>"']/g, c => ({
      '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;'
    }[c]));
  }

  load();
})();
