(async function () {
  const root = document.getElementById('clips-app');
  const LIMIT = 50;
  const TIMELINE_LIMIT = 1000;
  const CAM_COLORS = ['#7ee2b8', '#e27e7e', '#7eb8e2', '#e2c97e', '#c97ee2', '#e2b87e', '#7ebfe2'];

  let offset = 0;
  let cameraFilter = null;
  let zoneFilter = null;
  let mode = 'table';         // 'table' | 'timeline'
  let timelineRange = 86400;  // seconds
  let summary = [];           // from /api/clips/summary
  let activeVideoRow = null;  // table mode inline video row

  // ── Init ──────────────────────────────────────────────────────────────────

  async function init() {
    const [sumRes, statsRes] = await Promise.all([
      fetch('/api/clips/summary'),
      fetch('/api/clips/stats'),
    ]);
    if (sumRes.ok) summary = await sumRes.json();
    if (statsRes.ok) renderStorageCard(await statsRes.json());
    buildControls();
    load();
  }

  function renderStorageCard(stats) {
    let card = document.getElementById('clips-storage-card');
    if (!card) {
      card = document.createElement('div');
      card.id = 'clips-storage-card';
      card.className = 'clips-storage-card';
      root.appendChild(card);
    }

    const total = stats.disk_bytes || 0;
    card.innerHTML =
      `<div class="storage-total">` +
      `<strong>${humanBytes(total)}</strong> used &nbsp;·&nbsp; ${stats.count} clips` +
      `</div>`;

    const cams = stats.per_camera || [];
    if (cams.length) {
      const grid = document.createElement('div');
      grid.className = 'storage-cams';
      for (const cam of cams) {
        const pct = total > 0 ? (cam.disk_bytes / total * 100) : 0;
        const row = document.createElement('div');
        row.className = 'storage-cam-row';
        row.innerHTML =
          `<span class="storage-cam-name">${esc(cam.camera_name)}</span>` +
          `<div class="storage-bar-wrap"><div class="storage-bar" style="width:${pct.toFixed(1)}%"></div></div>` +
          `<span class="storage-cam-size">${humanBytes(cam.disk_bytes)}</span>` +
          `<span class="storage-cam-count">${cam.clip_count} clips</span>`;
        grid.appendChild(row);
      }
      card.appendChild(grid);
    }
  }

  function humanBytes(b) {
    if (b < 1024) return b + ' B';
    if (b < 1048576) return (b / 1024).toFixed(0) + ' KB';
    if (b < 1073741824) return (b / 1048576).toFixed(1) + ' MB';
    return (b / 1073741824).toFixed(2) + ' GB';
  }

  // ── Controls ──────────────────────────────────────────────────────────────

  function buildControls() {
    const bar = document.createElement('div');
    bar.className = 'filter-bar';
    root.appendChild(bar);

    // Camera select
    const camSel = document.createElement('select');
    camSel.id = 'cam-filter';
    camSel.innerHTML = '<option value="">All cameras</option>';
    for (const cam of summary) {
      const o = document.createElement('option');
      o.value = cam.camera_id;
      o.textContent = cam.camera_name;
      camSel.appendChild(o);
    }
    bar.appendChild(camSel);

    // Zone select (hidden until a camera with zones is chosen)
    const zoneSel = document.createElement('select');
    zoneSel.id = 'zone-filter';
    zoneSel.style.display = 'none';
    bar.appendChild(zoneSel);

    // View toggle
    const tog = document.createElement('div');
    tog.className = 'view-toggle';
    tog.innerHTML =
      '<button class="btn-sm active" id="vt-table">Table</button>' +
      '<button class="btn-sm" id="vt-timeline">Timeline</button>';
    bar.appendChild(tog);

    camSel.addEventListener('change', () => {
      cameraFilter = camSel.value ? +camSel.value : null;
      zoneFilter = null;
      offset = 0;
      refreshZoneDropdown(zoneSel);
      load();
    });

    zoneSel.addEventListener('change', () => {
      zoneFilter = zoneSel.value ? +zoneSel.value : null;
      offset = 0;
      load();
    });

    tog.querySelector('#vt-table').addEventListener('click', () => switchMode('table', tog));
    tog.querySelector('#vt-timeline').addEventListener('click', () => switchMode('timeline', tog));
  }

  function switchMode(m, tog) {
    mode = m;
    tog.querySelector('#vt-table').classList.toggle('active', m === 'table');
    tog.querySelector('#vt-timeline').classList.toggle('active', m === 'timeline');
    offset = 0;
    load();
  }

  function refreshZoneDropdown(zoneSel) {
    if (!cameraFilter) { zoneSel.style.display = 'none'; return; }
    const cam = summary.find(c => c.camera_id === cameraFilter);
    const zones = (cam?.zones || []).filter(z => z.zone_id !== null);
    if (!zones.length) { zoneSel.style.display = 'none'; return; }
    zoneSel.innerHTML = '<option value="">All zones</option>';
    for (const z of zones) {
      const o = document.createElement('option');
      o.value = z.zone_id;
      o.textContent = `${z.zone_name} (${z.clip_count})`;
      zoneSel.appendChild(o);
    }
    zoneSel.style.display = '';
  }

  // ── Data load ─────────────────────────────────────────────────────────────

  async function load() {
    const lim = mode === 'timeline' ? TIMELINE_LIMIT : LIMIT;
    let url = `/api/clips?limit=${lim}&offset=${mode === 'table' ? offset : 0}`;
    if (cameraFilter !== null) url += `&camera_id=${cameraFilter}`;
    if (zoneFilter !== null) url += `&zone_id=${zoneFilter}`;
    if (mode === 'timeline') {
      url += `&after_ts=${((Date.now() / 1000) - timelineRange).toFixed(0)}`;
    }
    const res = await fetch(url);
    if (!res.ok) { mainWrap().innerHTML = '<p class="status-bad">Failed to load clips.</p>'; return; }
    const clips = await res.json();
    mode === 'table' ? renderTable(clips) : renderTimeline(clips);
  }

  function mainWrap() {
    let w = document.getElementById('clips-main');
    if (!w) { w = document.createElement('div'); w.id = 'clips-main'; root.appendChild(w); }
    return w;
  }

  // ── Table view ────────────────────────────────────────────────────────────

  function renderTable(clips) {
    const wrap = mainWrap();
    activeVideoRow = null;

    if (!clips.length && offset === 0) {
      wrap.innerHTML = '<p>No clips yet. Clips are recorded when a detection zone fires.</p>';
      renderPager(0);
      return;
    }

    const tbl = document.createElement('table');
    tbl.innerHTML = `<thead><tr>
      <th></th><th>Camera</th><th>Class</th><th>Zone</th>
      <th>Duration</th><th>Recorded at</th><th></th>
    </tr></thead><tbody></tbody>`;
    const tbody = tbl.querySelector('tbody');

    for (const clip of clips) {
      const tr = document.createElement('tr');
      tr.style.cursor = 'pointer';
      tr.dataset.clipId = clip.id;
      tr.innerHTML = `
        <td class="clip-thumb-cell">
          <img class="clip-thumb" src="/api/clips/${clip.id}/thumb.jpg" alt="" loading="lazy"
               onerror="this.style.display='none'">
        </td>
        <td>${esc(clip.camera_name || '#' + clip.camera_id)}</td>
        <td>${esc(clip.class_name)}</td>
        <td>${esc(clip.zone_name || '—')}</td>
        <td>${clip.duration_s != null ? clip.duration_s.toFixed(0) + 's' : '—'}</td>
        <td>${fmt(clip.created_at)}</td>
        <td><button class="btn-sm btn-danger" data-del="${clip.id}">Delete</button></td>
      `;
      tr.addEventListener('click', e => { if (e.target.dataset.del) return; toggleVideo(tr, clip.id); });
      tbody.appendChild(tr);
    }

    wrap.innerHTML = '';
    wrap.appendChild(tbl);
    renderPager(clips.length);

    wrap.querySelectorAll('[data-del]').forEach(btn => {
      btn.addEventListener('click', async e => {
        e.stopPropagation();
        if (!confirm('Delete this clip?')) return;
        const r = await fetch(`/api/clips/${btn.dataset.del}`, { method: 'DELETE' });
        if (r.ok || r.status === 204) load();
      });
    });
  }

  function toggleVideo(tr, clipId) {
    if (activeVideoRow) {
      activeVideoRow.remove();
      activeVideoRow = null;
      if (tr.dataset.open === '1') { tr.dataset.open = ''; return; }
    }
    document.querySelectorAll('tr[data-open="1"]').forEach(r => r.dataset.open = '');
    tr.dataset.open = '1';
    const vtr = document.createElement('tr');
    vtr.className = 'video-row';
    const td = document.createElement('td');
    td.colSpan = 7;
    td.style.padding = '0.5rem';
    const video = document.createElement('video');
    video.controls = true; video.autoplay = true;
    video.style.cssText = 'max-width:100%;max-height:480px;display:block;margin:0 auto;';
    video.src = `/api/clips/${clipId}/video.mp4`;
    video.onerror = () => {
      td.innerHTML = '<span style="padding:0.5rem;display:block;color:#e27e7e">Could not play clip — unsupported codec or file missing.</span>';
    };
    td.appendChild(video);
    vtr.appendChild(td);
    tr.after(vtr);
    activeVideoRow = vtr;
  }

  function renderPager(count) {
    let p = document.getElementById('clips-pager');
    if (p) p.remove();
    if (mode !== 'table') return;
    p = document.createElement('div');
    p.id = 'clips-pager'; p.className = 'pager';
    if (offset > 0) {
      const b = document.createElement('button');
      b.textContent = '← Prev'; b.className = 'btn-sm';
      b.addEventListener('click', () => { offset = Math.max(0, offset - LIMIT); load(); });
      p.appendChild(b);
    }
    if (count === LIMIT) {
      const b = document.createElement('button');
      b.textContent = 'Next →'; b.className = 'btn-sm';
      b.addEventListener('click', () => { offset += LIMIT; load(); });
      p.appendChild(b);
    }
    if (p.children.length) root.appendChild(p);
  }

  // ── Timeline view ─────────────────────────────────────────────────────────

  function renderTimeline(clips) {
    const wrap = mainWrap();
    wrap.innerHTML = '';

    // Range selector
    const rangeBar = document.createElement('div');
    rangeBar.className = 'filter-bar';
    rangeBar.style.marginBottom = '0.75rem';
    for (const [label, s] of [['24 h', 86400], ['7 d', 604800], ['30 d', 2592000]]) {
      const b = document.createElement('button');
      b.className = 'btn-sm' + (timelineRange === s ? ' tl-range-active' : '');
      b.textContent = label;
      b.addEventListener('click', () => { timelineRange = s; load(); });
      rangeBar.appendChild(b);
    }
    wrap.appendChild(rangeBar);

    if (!clips.length) {
      const p = document.createElement('p');
      p.textContent = 'No clips in this time range.';
      wrap.appendChild(p);
      return;
    }

    const nowTs = Date.now() / 1000;
    const startTs = nowTs - timelineRange;

    // Group by camera, preserving first-seen order
    const camOrder = [];
    const camMap = {};
    for (const clip of clips) {
      const id = clip.camera_id;
      if (!camMap[id]) {
        camMap[id] = { name: clip.camera_name || '#' + id, clips: [] };
        camOrder.push(id);
      }
      camMap[id].clips.push(clip);
    }

    const container = document.createElement('div');
    container.className = 'tl-container';
    const inner = document.createElement('div');
    inner.className = 'tl-inner';

    camOrder.forEach((camId, idx) => {
      const cam = camMap[camId];
      const color = CAM_COLORS[idx % CAM_COLORS.length];

      const row = document.createElement('div');
      row.className = 'tl-row';

      const label = document.createElement('div');
      label.className = 'tl-label';
      label.textContent = cam.name;
      label.style.borderLeft = `3px solid ${color}`;

      const track = document.createElement('div');
      track.className = 'tl-track';

      for (const clip of cam.clips) {
        const xPct = (clip.created_at - startTs) / timelineRange * 100;
        if (xPct < 0 || xPct > 100) continue;

        const durPct = clip.duration_s ? Math.max(0.3, clip.duration_s / timelineRange * 100) : 0.5;

        const m = document.createElement('div');
        m.className = 'tl-marker';
        m.style.left = xPct + '%';
        m.style.width = Math.min(durPct, 100 - xPct) + '%';
        m.style.background = color;
        m.dataset.clipId = clip.id;
        m.title = `${clip.class_name}${clip.zone_name ? ' · ' + clip.zone_name : ''}\n${fmt(clip.created_at)}${clip.duration_s ? ' (' + clip.duration_s.toFixed(0) + 's)' : ''}`;
        m.addEventListener('click', () => showTimelineVideo(clip, color));
        track.appendChild(m);
      }

      row.appendChild(label);
      row.appendChild(track);
      inner.appendChild(row);
    });

    // Time axis row
    const axisRow = document.createElement('div');
    axisRow.className = 'tl-row tl-axis-row';
    const axisLabel = document.createElement('div');
    axisLabel.className = 'tl-label';
    const axis = document.createElement('div');
    axis.className = 'tl-track tl-axis';
    for (const tick of timeTicks(startTs, nowTs)) {
      const pct = (tick.ts - startTs) / timelineRange * 100;
      const span = document.createElement('span');
      span.style.left = pct + '%';
      span.textContent = tick.label;
      axis.appendChild(span);
    }
    axisRow.appendChild(axisLabel);
    axisRow.appendChild(axis);
    inner.appendChild(axisRow);

    container.appendChild(inner);
    wrap.appendChild(container);

    // Video area (initially empty)
    const videoArea = document.createElement('div');
    videoArea.id = 'tl-video-area';
    videoArea.className = 'tl-video-area';
    wrap.appendChild(videoArea);
  }

  function showTimelineVideo(clip, color) {
    document.querySelectorAll('.tl-marker.tl-active').forEach(m => m.classList.remove('tl-active'));
    const m = document.querySelector(`.tl-marker[data-clip-id="${clip.id}"]`);
    if (m) m.classList.add('tl-active');

    const area = document.getElementById('tl-video-area');
    area.innerHTML = '';

    const hdr = document.createElement('div');
    hdr.className = 'tl-video-hdr';
    hdr.innerHTML =
      `<span class="tl-dot" style="background:${color}"></span>` +
      `<span class="tl-video-meta">${esc(clip.camera_name || '#' + clip.camera_id)}` +
      ` · ${esc(clip.class_name)}` +
      (clip.zone_name ? ` · ${esc(clip.zone_name)}` : '') +
      ` · ${fmt(clip.created_at)}</span>`;

    const video = document.createElement('video');
    video.controls = true; video.autoplay = true;
    video.style.cssText = 'max-width:100%;max-height:480px;display:block;';
    video.src = `/api/clips/${clip.id}/video.mp4`;
    video.onerror = () => {
      area.innerHTML = '<span style="color:#e27e7e">Could not play clip — unsupported codec or file missing.</span>';
    };

    area.appendChild(hdr);
    area.appendChild(video);
    area.scrollIntoView({ behavior: 'smooth', block: 'nearest' });
  }

  function timeTicks(startTs, endTs) {
    const range = endTs - startTs;
    let step, fmtFn;
    if (range <= 86400) {
      step = 2 * 3600;
      fmtFn = ts => new Date(ts * 1000).toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' });
    } else if (range <= 7 * 86400) {
      step = 86400;
      fmtFn = ts => new Date(ts * 1000).toLocaleDateString([], { weekday: 'short', month: 'numeric', day: 'numeric' });
    } else {
      step = 3 * 86400;
      fmtFn = ts => new Date(ts * 1000).toLocaleDateString([], { month: 'short', day: 'numeric' });
    }
    const ticks = [];
    let ts = Math.ceil(startTs / step) * step;
    while (ts <= endTs) { ticks.push({ ts, label: fmtFn(ts) }); ts += step; }
    return ticks;
  }

  // ── Utilities ─────────────────────────────────────────────────────────────

  function fmt(ts) { return new Date(ts * 1000).toLocaleString(); }
  function esc(s) {
    return String(s).replace(/[&<>"']/g, c =>
      ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]));
  }

  init();
})();
