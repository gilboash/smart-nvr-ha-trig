(async function () {
  const root = document.getElementById('camera-edit');
  const cameraId = Number(root.dataset.cameraId);
  let camera = null;
  let editor = null;

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
          <strong style="color:#7ec6e2">Detection</strong> — only trigger YOLO alerts when an object enters this area.<br>
          <strong style="color:#c07ee2">State (CLIP)</strong> — continuously classify what's in this area using your own labels (e.g. "open, closed"). An event fires when the state changes.
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
        const labels = z.state_labels ? z.state_labels.join(', ') : '—';
        tr.innerHTML = `
          <td>${z.id}</td>
          <td>${escapeHtml(z.name)}</td>
          <td><span class="badge ${z.zone_type === 'state' ? 'badge-state' : 'badge-det'}">${z.zone_type}</span></td>
          <td class="zone-state-cell">${z.zone_type === 'state' ? '<span class="muted">…</span>' : '—'}</td>
          <td>${z.polygon.length}</td>
          <td><button class="danger" data-zone="${z.id}">Delete</button></td>
        `;
        tbody.appendChild(tr);
      }
      tbody.querySelectorAll('button[data-zone]').forEach(b => b.addEventListener('click', async e => {
        const id = e.target.dataset.zone;
        if (!confirm('Delete zone #' + id + '?')) return;
        await fetch('/api/zones/' + id, { method: 'DELETE' });
        load();
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
