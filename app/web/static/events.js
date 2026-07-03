(async function () {
  const root = document.getElementById('events-app');
  let cameras = {};

  async function loadCameras() {
    const res = await fetch('/api/cameras');
    if (!res.ok) return;
    const list = await res.json();
    cameras = Object.fromEntries(list.map(c => [c.id, c.name]));
  }

  async function loadEvents() {
    const res = await fetch('/api/events?limit=200');
    if (!res.ok) { root.innerHTML = '<p>Failed to load events.</p>'; return; }
    const events = await res.json();
    render(events);
  }

  function render(events) {
    if (events.length === 0) {
      root.innerHTML = '<p>No events yet.</p>';
      return;
    }
    const table = document.createElement('table');
    table.innerHTML = `
      <thead>
        <tr>
          <th></th>
          <th>Camera</th>
          <th>Class</th>
          <th>Zone</th>
          <th>Confidence</th>
          <th>Frames</th>
          <th>Start</th>
          <th>End</th>
        </tr>
      </thead>
      <tbody></tbody>
    `;
    const tbody = table.querySelector('tbody');
    for (const e of events) {
      const tr = document.createElement('tr');
      const thumb = e.snapshot_path
        ? `<img class="thumb" src="/api/events/${e.id}/snapshot.jpg" alt="">`
        : '<span class="badge">no snap</span>';
      const open = e.end_ts == null;
      tr.innerHTML = `
        <td>${thumb}</td>
        <td>${escapeHtml(cameras[e.camera_id] || ('#' + e.camera_id))}</td>
        <td>${escapeHtml(e.class_name)}</td>
        <td>${e.zone_id ?? '—'}</td>
        <td>${(e.max_confidence * 100).toFixed(0)}%</td>
        <td>${e.frame_count}</td>
        <td>${fmt(e.start_ts)}</td>
        <td>${open ? '<span class="badge open">open</span>' : fmt(e.end_ts)}</td>
      `;
      tbody.appendChild(tr);
    }
    root.innerHTML = '';
    root.appendChild(table);
  }

  function fmt(ts) {
    return new Date(ts * 1000).toLocaleString();
  }

  function escapeHtml(s) {
    return String(s).replace(/[&<>"']/g, c => ({
      '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;'
    }[c]));
  }

  await loadCameras();
  loadEvents();

  const proto = location.protocol === 'https:' ? 'wss:' : 'ws:';
  const ws = new WebSocket(`${proto}//${location.host}/ws/events`);
  ws.onmessage = () => { loadEvents(); };
  setInterval(loadEvents, 15000);
})();
