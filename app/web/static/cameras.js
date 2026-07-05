(async function () {
  const root = document.getElementById('cameras-app');

  async function load() {
    const res = await fetch('/api/cameras');
    const cameras = await res.json();
    render(cameras);
  }

  function render(cameras) {
    root.innerHTML = '';

    const list = document.createElement('div');
    if (cameras.length === 0) {
      list.innerHTML = '<p>No cameras yet. Add one below.</p>';
    } else {
      const table = document.createElement('table');
      table.innerHTML = `
        <thead>
          <tr>
            <th>ID</th><th>Name</th><th>Enabled</th><th>FPS</th><th>Classes</th><th></th>
          </tr>
        </thead>
        <tbody></tbody>
      `;
      const tbody = table.querySelector('tbody');
      for (const c of cameras) {
        const tr = document.createElement('tr');
        tr.innerHTML = `
          <td>${c.id}</td>
          <td><a href="/cameras/${c.id}">${escapeHtml(c.name)}</a></td>
          <td>${c.enabled ? '✓' : '—'}</td>
          <td>${c.target_fps}</td>
          <td>${escapeHtml(c.classes.join(', '))}</td>
          <td><button data-id="${c.id}" class="danger del">Delete</button></td>
        `;
        tbody.appendChild(tr);
      }
      list.appendChild(table);
    }
    root.appendChild(list);

    const card = document.createElement('div');
    card.className = 'card';
    card.innerHTML = `
      <h2>Add camera</h2>
      <form id="add-form">
        <div class="row">
          <div>
            <label>Name</label>
            <input name="name" required>
          </div>
          <div>
            <label>RTSP URL</label>
            <input name="rtsp_url" required placeholder="rtsp://user:pass@host/stream">
          </div>
        </div>
        <div class="row">
          <div>
            <label>Target FPS (0 = capture only, no inference)</label>
            <input name="target_fps" type="number" step="0.5" min="0" max="30" value="5">
          </div>
          <div>
            <label>Model</label>
            <input name="model" value="yolov8n.pt">
          </div>
          <div>
            <label>Detection classes</label>
            <div id="add-classes-picker"></div>
          </div>
          <div>
            <label>Hysteresis (s)</label>
            <input name="hysteresis_s" type="number" step="0.5" min="0.5" max="120" value="5">
          </div>
        </div>
        <button class="primary" type="submit">Add camera</button>
      </form>
    `;
    root.appendChild(card);

    let classPicker = null;
    ClassPicker.create(card.querySelector('#add-classes-picker'), ['person']).then(p => { classPicker = p; });
    card.querySelector('#add-form').addEventListener('submit', e => onSubmit(e, classPicker));
    root.querySelectorAll('button.del').forEach(b => b.addEventListener('click', onDelete));
  }

  async function onSubmit(e, classPicker) {
    e.preventDefault();
    const fd = new FormData(e.target);
    const classes = classPicker ? classPicker.selected() : ['person'];
    if (classes.length === 0) { alert('Select at least one detection class.'); return; }
    const body = {
      name: fd.get('name'),
      rtsp_url: fd.get('rtsp_url'),
      target_fps: Number(fd.get('target_fps')),
      model: fd.get('model'),
      classes,
      hysteresis_s: Number(fd.get('hysteresis_s')),
    };
    const res = await fetch('/api/cameras', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(body),
    });
    if (!res.ok) {
      alert('Failed: ' + (await res.text()));
      return;
    }
    load();
  }

  async function onDelete(e) {
    const id = e.target.dataset.id;
    if (!confirm('Delete camera #' + id + '?')) return;
    const res = await fetch('/api/cameras/' + id, { method: 'DELETE' });
    if (!res.ok) { alert('Failed'); return; }
    load();
  }

  function escapeHtml(s) {
    return String(s).replace(/[&<>"']/g, c => ({
      '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;'
    }[c]));
  }

  load();
})();
