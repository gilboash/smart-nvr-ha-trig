(async function () {
  const root = document.getElementById('clips-app');
  const CAM_COLORS = ['#7ee2b8', '#e27e7e', '#7eb8e2', '#e2c97e', '#c97ee2', '#e2b87e', '#7ebfe2'];
  const CLASS_COLORS = {
    person:     '#e27e7e',
    car:        '#7eb8e2',
    truck:      '#e2c97e',
    bicycle:    '#c97ee2',
    motorcycle: '#e2b87e',
    bus:        '#7ee2b8',
    dog:        '#a0e27e',
    cat:        '#a0e27e',
  };

  let timelineRange = 86400;
  let cameraFilter = null;
  let cameras = [];

  // ── Init ──────────────────────────────────────────────────────────────────

  async function init() {
    const [camRes, statsRes] = await Promise.all([
      fetch('/api/cameras'),
      fetch('/api/recordings/stats'),
    ]);
    if (camRes.ok) cameras = await camRes.json();
    if (statsRes.ok) renderStorageCard(await statsRes.json());
    buildControls();
    load();
  }

  function renderStorageCard(stats) {
    let card = document.getElementById('rec-storage-card');
    if (!card) {
      card = document.createElement('div');
      card.id = 'rec-storage-card';
      card.className = 'clips-storage-card';
      root.appendChild(card);
    }
    const total = stats.disk_bytes || 0;
    const age = stats.max_age_days > 0 ? `auto-delete after ${stats.max_age_days} days` : 'kept forever';
    card.innerHTML =
      `<div class="storage-total">` +
      `<strong>${humanBytes(total)}</strong> used &nbsp;·&nbsp; ${stats.count} segments &nbsp;·&nbsp; ${age}` +
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
          `<span class="storage-cam-count">${cam.segment_count} segs</span>`;
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

    const camSel = document.createElement('select');
    camSel.id = 'cam-filter';
    camSel.innerHTML = '<option value="">All cameras</option>';
    for (const cam of cameras) {
      const o = document.createElement('option');
      o.value = cam.id;
      o.textContent = cam.name;
      camSel.appendChild(o);
    }
    bar.appendChild(camSel);
    camSel.addEventListener('change', () => {
      cameraFilter = camSel.value ? +camSel.value : null;
      load();
    });

    for (const [label, s] of [['24 h', 86400], ['48 h', 172800], ['7 d', 604800]]) {
      const b = document.createElement('button');
      b.className = 'btn-sm tl-range-btn' + (timelineRange === s ? ' tl-range-active' : '');
      b.textContent = label;
      b.addEventListener('click', () => {
        timelineRange = s;
        document.querySelectorAll('.tl-range-btn').forEach(x => x.classList.remove('tl-range-active'));
        b.classList.add('tl-range-active');
        load();
      });
      bar.appendChild(b);
    }
  }

  // ── Data load ─────────────────────────────────────────────────────────────

  async function load() {
    let url = `/api/recordings/timeline?range_s=${timelineRange}`;
    if (cameraFilter !== null) url += `&camera_id=${cameraFilter}`;
    const res = await fetch(url);
    if (!res.ok) {
      mainWrap().innerHTML = '<p class="status-bad">Failed to load recordings.</p>';
      return;
    }
    renderTimeline(await res.json());
  }

  function mainWrap() {
    let w = document.getElementById('clips-main');
    if (!w) { w = document.createElement('div'); w.id = 'clips-main'; root.appendChild(w); }
    return w;
  }

  // ── Timeline ──────────────────────────────────────────────────────────────

  function renderTimeline(data) {
    const wrap = mainWrap();
    wrap.innerHTML = '';

    const { range_start, range_end, segments, events } = data;
    const range_s = range_end - range_start;

    if (!segments.length && !events.length) {
      wrap.innerHTML = '<p style="color:var(--muted)">No recordings in this range. Cameras with <em>Record continuously</em> enabled will appear here after their first segment flushes (up to ' +
        Math.round(range_s / 60) + ' min wait).</p>';
      return;
    }

    // Group by camera, preserving encounter order
    const camOrder = [];
    const camMap = {};
    function ensureCam(cam_id, cam_name) {
      if (!camMap[cam_id]) {
        camMap[cam_id] = { name: cam_name, segments: [], events: [] };
        camOrder.push(cam_id);
      }
    }
    for (const s of segments) ensureCam(s.camera_id, s.camera_name);
    for (const e of events)   ensureCam(e.camera_id, e.camera_name);
    for (const s of segments) camMap[s.camera_id].segments.push(s);
    for (const e of events)   camMap[e.camera_id].events.push(e);

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
      track.className = 'tl-track tl-track-dvr';

      // Coverage blocks (one per segment)
      for (const seg of cam.segments) {
        const x1pct = (seg.start_ts - range_start) / range_s * 100;
        const x2pct = ((seg.end_ts ?? range_end) - range_start) / range_s * 100;
        if (x2pct < 0 || x1pct > 100) continue;
        const block = document.createElement('div');
        block.className = 'tl-seg';
        block.style.left = Math.max(0, x1pct) + '%';
        block.style.width = (Math.min(100, x2pct) - Math.max(0, x1pct)) + '%';
        block.style.background = color + '66';
        block.dataset.segId = seg.id;
        block.dataset.segStart = seg.start_ts;
        block.dataset.segEnd = seg.end_ts ?? range_end;
        block.title = `${cam.name}\n${fmt(seg.start_ts)} → ${seg.end_ts ? fmt(seg.end_ts) : 'in progress'}`;
        block.addEventListener('click', e => {
          const rect = track.getBoundingClientRect();
          const pct = (e.clientX - rect.left) / rect.width;
          const ts = range_start + pct * range_s;
          playSegment(seg, ts, cam.name);
        });
        track.appendChild(block);
      }

      // Event ticks
      for (const ev of cam.events) {
        const xPct = (ev.start_ts - range_start) / range_s * 100;
        if (xPct < 0 || xPct > 100) continue;
        const tick = document.createElement('div');
        tick.className = 'tl-event-tick';
        tick.style.left = xPct + '%';
        tick.style.background = CLASS_COLORS[ev.class_name] || '#e2b87e';
        const label = ev.class_name + (ev.zone_name ? ' · ' + ev.zone_name : '');
        tick.title = `${label}\n${fmt(ev.start_ts)}`;
        track.appendChild(tick);
      }

      row.appendChild(label);
      row.appendChild(track);
      inner.appendChild(row);
    });

    // Time axis
    const axisRow = document.createElement('div');
    axisRow.className = 'tl-row tl-axis-row';
    axisRow.appendChild(Object.assign(document.createElement('div'), { className: 'tl-label' }));
    const axis = document.createElement('div');
    axis.className = 'tl-track tl-axis';
    for (const tick of timeTicks(range_start, range_end)) {
      const span = document.createElement('span');
      span.style.left = ((tick.ts - range_start) / range_s * 100) + '%';
      span.textContent = tick.label;
      axis.appendChild(span);
    }
    axisRow.appendChild(axis);
    inner.appendChild(axisRow);

    container.appendChild(inner);
    wrap.appendChild(container);

    // Legend
    const legend = document.createElement('div');
    legend.className = 'tl-legend';
    for (const [cls, col] of Object.entries(CLASS_COLORS)) {
      const item = document.createElement('span');
      item.className = 'tl-legend-item';
      item.innerHTML = `<span class="tl-dot" style="background:${col}"></span>${esc(cls)}`;
      legend.appendChild(item);
    }
    wrap.appendChild(legend);

    // Video area
    const videoArea = document.createElement('div');
    videoArea.id = 'tl-video-area';
    videoArea.className = 'tl-video-area';
    wrap.appendChild(videoArea);
  }

  function playSegment(seg, clickedTs, camName) {
    const area = document.getElementById('tl-video-area');
    if (!area) return;
    area.innerHTML = '';

    const hdr = document.createElement('div');
    hdr.className = 'tl-video-hdr';
    hdr.innerHTML =
      `<span class="tl-video-meta">${esc(camName)} &nbsp;·&nbsp; ` +
      `${fmt(seg.start_ts)} → ${seg.end_ts ? fmt(seg.end_ts) : 'in progress'}</span>`;

    const video = document.createElement('video');
    video.controls = true;
    video.autoplay = true;
    video.style.cssText = 'max-width:100%;max-height:480px;display:block;';
    video.src = `/api/recordings/${seg.id}/video`;
    video.addEventListener('loadedmetadata', () => {
      const offset = clickedTs - seg.start_ts;
      if (offset > 0 && offset < video.duration) video.currentTime = offset;
    });
    video.onerror = () => {
      area.innerHTML = '<span style="color:#e27e7e;display:block;margin-top:0.5rem">' +
        'Could not play recording — segment may still be encoding (check back in a few minutes).</span>';
    };

    area.appendChild(hdr);
    area.appendChild(video);
    area.scrollIntoView({ behavior: 'smooth', block: 'nearest' });
  }

  // ── Utilities ─────────────────────────────────────────────────────────────

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

  function fmt(ts) { return new Date(ts * 1000).toLocaleString(); }
  function esc(s) {
    return String(s).replace(/[&<>"']/g, c =>
      ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]));
  }

  init();
})();
