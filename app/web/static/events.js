(async function () {
  const root = document.getElementById('events-app');
  const PAGE = 50;
  let cameras = {};
  let oldestTs = null;
  let exhausted = false;

  async function loadCameras() {
    const res = await fetch('/api/cameras');
    if (!res.ok) return;
    const list = await res.json();
    cameras = Object.fromEntries(list.map(c => [c.id, c.name]));
  }

  // ── Initial load ──────────────────────────────────────────────────────────

  async function initialLoad() {
    const res = await fetch(`/api/events?limit=${PAGE}`);
    if (!res.ok) { root.innerHTML = '<p>Failed to load events.</p>'; return; }
    const events = await res.json();
    root.innerHTML = '';
    if (events.length === 0) {
      root.innerHTML = '<p>No events yet.</p>';
      return;
    }
    const table = makeTable();
    root.appendChild(table);
    appendRows(table.querySelector('tbody'), events);
    oldestTs = events[events.length - 1].start_ts;
    exhausted = events.length < PAGE;
    if (!exhausted) root.appendChild(makeLoadMoreBtn());
  }

  // ── Load more (older) ──────────────────────────────────────────────────────

  async function loadMore() {
    if (exhausted || oldestTs === null) return;
    const res = await fetch(`/api/events?limit=${PAGE}&before_ts=${oldestTs}`);
    if (!res.ok) return;
    const events = await res.json();
    const btn = document.getElementById('load-more-btn');
    if (btn) btn.remove();
    if (events.length === 0) { exhausted = true; return; }
    const tbody = root.querySelector('tbody');
    appendRows(tbody, events);
    oldestTs = events[events.length - 1].start_ts;
    exhausted = events.length < PAGE;
    if (!exhausted) root.appendChild(makeLoadMoreBtn());
  }

  // ── Prepend a single new event (from WebSocket) ───────────────────────────

  function prependEvent(ev) {
    let tbody = root.querySelector('tbody');
    if (!tbody) {
      // First event ever — build the table now
      root.innerHTML = '';
      const table = makeTable();
      root.appendChild(table);
      tbody = table.querySelector('tbody');
    }
    const tr = makeRow(ev);
    tbody.insertBefore(tr, tbody.firstChild);
  }

  // ── DOM helpers ───────────────────────────────────────────────────────────

  function makeTable() {
    const table = document.createElement('table');
    table.innerHTML = `
      <thead>
        <tr>
          <th></th><th>Camera</th><th>Class</th><th>Zone</th>
          <th>Confidence</th><th>Frames</th><th>Start</th><th>End</th>
        </tr>
      </thead>
      <tbody></tbody>
    `;
    return table;
  }

  function appendRows(tbody, events) {
    for (const e of events) tbody.appendChild(makeRow(e));
  }

  function makeRow(e) {
    const tr = document.createElement('tr');
    const thumb = e.snapshot_path
      ? `<img class="thumb" src="/api/events/${e.id}/snapshot.jpg" alt="" loading="lazy">`
      : '<span class="badge">no snap</span>';
    const open = e.end_ts == null;
    tr.innerHTML = `
      <td>${thumb}</td>
      <td>${esc(cameras[e.camera_id] || ('#' + e.camera_id))}</td>
      <td>${esc(e.class_name)}</td>
      <td>${e.zone_id ?? '—'}</td>
      <td>${(e.max_confidence * 100).toFixed(0)}%</td>
      <td>${e.frame_count}</td>
      <td>${fmt(e.start_ts)}</td>
      <td>${open ? '<span class="badge open">open</span>' : fmt(e.end_ts)}</td>
    `;
    return tr;
  }

  function makeLoadMoreBtn() {
    const btn = document.createElement('button');
    btn.id = 'load-more-btn';
    btn.textContent = 'Load more';
    btn.style.cssText = 'display:block;margin:1rem auto;';
    btn.addEventListener('click', loadMore);
    return btn;
  }

  function fmt(ts) { return new Date(ts * 1000).toLocaleString(); }
  function esc(s) {
    return String(s).replace(/[&<>"']/g, c =>
      ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]));
  }

  // ── Boot ──────────────────────────────────────────────────────────────────

  await loadCameras();
  await initialLoad();

  const proto = location.protocol === 'https:' ? 'wss:' : 'ws:';
  const ws = new WebSocket(`${proto}//${location.host}/ws/events`);
  ws.onmessage = async (msg) => {
    try {
      const ev = JSON.parse(msg.data);
      // Only prepend on ENTER (new detection) — EXIT just updates an existing row
      if (ev.kind === 'ENTER') prependEvent(ev);
    } catch (_) {}
  };
})();
