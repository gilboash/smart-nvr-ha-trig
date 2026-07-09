(async function () {
  const root = document.getElementById('clips-app');
  const LIMIT = 50;
  let offset = 0;
  let cameraFilter = null;
  let cameras = [];
  let activeVideoRow = null;

  async function loadCameras() {
    const res = await fetch('/api/cameras');
    if (!res.ok) return;
    cameras = await res.json();
  }

  function buildControls() {
    const bar = document.createElement('div');
    bar.className = 'filter-bar';

    const sel = document.createElement('select');
    sel.id = 'cam-filter';
    const allOpt = document.createElement('option');
    allOpt.value = '';
    allOpt.textContent = 'All cameras';
    sel.appendChild(allOpt);
    for (const c of cameras) {
      const opt = document.createElement('option');
      opt.value = c.id;
      opt.textContent = c.name;
      sel.appendChild(opt);
    }
    sel.addEventListener('change', () => {
      cameraFilter = sel.value ? parseInt(sel.value) : null;
      offset = 0;
      load();
    });

    bar.appendChild(sel);
    root.appendChild(bar);
  }

  async function load() {
    let url = `/api/clips?limit=${LIMIT}&offset=${offset}`;
    if (cameraFilter !== null) url += `&camera_id=${cameraFilter}`;
    const res = await fetch(url);
    if (!res.ok) { renderError(); return; }
    const clips = await res.json();
    renderTable(clips);
  }

  function renderError() {
    const el = document.getElementById('clips-table-wrap');
    if (el) el.innerHTML = '<p>Failed to load clips.</p>';
  }

  function renderTable(clips) {
    let wrap = document.getElementById('clips-table-wrap');
    if (!wrap) {
      wrap = document.createElement('div');
      wrap.id = 'clips-table-wrap';
      root.appendChild(wrap);
    }
    activeVideoRow = null;

    if (clips.length === 0 && offset === 0) {
      wrap.innerHTML = '<p>No clips yet. Clips are recorded when a detection zone fires.</p>';
      renderPager(wrap, 0);
      return;
    }

    const table = document.createElement('table');
    table.innerHTML = `
      <thead>
        <tr>
          <th>Camera</th>
          <th>Class</th>
          <th>Zone</th>
          <th>Duration</th>
          <th>Recorded at</th>
          <th></th>
        </tr>
      </thead>
      <tbody></tbody>
    `;
    const tbody = table.querySelector('tbody');

    for (const clip of clips) {
      const tr = document.createElement('tr');
      tr.style.cursor = 'pointer';
      tr.dataset.clipId = clip.id;
      tr.innerHTML = `
        <td>${escapeHtml(clip.camera_name || ('#' + clip.camera_id))}</td>
        <td>${escapeHtml(clip.class_name)}</td>
        <td>${clip.zone_id ?? '—'}</td>
        <td>${clip.duration_s != null ? clip.duration_s.toFixed(0) + 's' : '—'}</td>
        <td>${fmt(clip.created_at)}</td>
        <td><button class="btn-sm btn-danger" data-del="${clip.id}">Delete</button></td>
      `;
      tr.addEventListener('click', (e) => {
        if (e.target.dataset.del) return;
        toggleVideo(tr, clip.id);
      });
      tbody.appendChild(tr);
    }

    wrap.innerHTML = '';
    wrap.appendChild(table);
    renderPager(wrap, clips.length);

    wrap.querySelectorAll('[data-del]').forEach(btn => {
      btn.addEventListener('click', async (e) => {
        e.stopPropagation();
        if (!confirm('Delete this clip?')) return;
        const id = btn.dataset.del;
        const r = await fetch(`/api/clips/${id}`, { method: 'DELETE' });
        if (r.ok || r.status === 204) load();
      });
    });
  }

  function toggleVideo(tr, clipId) {
    // Remove existing video row if any
    if (activeVideoRow) {
      activeVideoRow.remove();
      activeVideoRow = null;
      // If same row clicked again, just close
      if (tr.dataset.open === '1') {
        tr.dataset.open = '';
        return;
      }
    }
    tr.dataset.open = '';

    // Close previously opened marker
    document.querySelectorAll('tr[data-open="1"]').forEach(r => r.dataset.open = '');
    tr.dataset.open = '1';

    const videoRow = document.createElement('tr');
    videoRow.className = 'video-row';
    const td = document.createElement('td');
    td.colSpan = 6;
    td.innerHTML = `
      <video controls autoplay style="max-width:100%;max-height:480px;display:block;margin:0.5rem auto;">
        <source src="/api/clips/${clipId}/video.mp4" type="video/mp4">
        Your browser does not support the video tag.
      </video>
    `;
    videoRow.appendChild(td);
    tr.after(videoRow);
    activeVideoRow = videoRow;
  }

  function renderPager(wrap, count) {
    let pager = document.getElementById('clips-pager');
    if (pager) pager.remove();
    pager = document.createElement('div');
    pager.id = 'clips-pager';
    pager.className = 'pager';

    if (offset > 0) {
      const prev = document.createElement('button');
      prev.textContent = '← Prev';
      prev.className = 'btn-sm';
      prev.addEventListener('click', () => { offset = Math.max(0, offset - LIMIT); load(); });
      pager.appendChild(prev);
    }

    if (count === LIMIT) {
      const next = document.createElement('button');
      next.textContent = 'Next →';
      next.className = 'btn-sm';
      next.addEventListener('click', () => { offset += LIMIT; load(); });
      pager.appendChild(next);
    }

    if (pager.children.length) root.appendChild(pager);
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
  buildControls();
  load();
})();
