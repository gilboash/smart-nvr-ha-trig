(async function () {
  const root = document.getElementById('dashboard-app');
  const REFRESH_MS = 3000;  // per-camera refresh interval

  async function loadCameras() {
    const res = await fetch('/api/cameras');
    if (!res.ok) { root.innerHTML = '<p>Failed to load cameras.</p>'; return []; }
    return res.json();
  }

  function buildGrid(cameras) {
    if (cameras.length === 0) {
      root.innerHTML = '<p>No cameras configured yet. <a href="/cameras">Add one.</a></p>';
      return;
    }
    const grid = document.createElement('div');
    grid.className = 'cam-grid';
    for (const cam of cameras) {
      const card = document.createElement('div');
      card.className = 'cam-card';
      card.dataset.camId = cam.id;

      const header = document.createElement('div');
      header.className = 'cam-card-header';
      header.innerHTML = `<span class="cam-name">${esc(cam.name)}</span><span class="cam-status" id="status-${cam.id}"></span>`;

      const imgWrap = document.createElement('div');
      imgWrap.className = 'cam-img-wrap';

      const img = document.createElement('img');
      img.className = 'cam-preview';
      img.alt = cam.name;
      img.id = `preview-${cam.id}`;

      const offlineDiv = document.createElement('div');
      offlineDiv.className = 'cam-offline';
      offlineDiv.id = `offline-${cam.id}`;
      offlineDiv.textContent = 'No feed';
      offlineDiv.style.display = 'none';

      imgWrap.appendChild(img);
      imgWrap.appendChild(offlineDiv);
      card.appendChild(header);
      card.appendChild(imgWrap);
      grid.appendChild(card);
    }
    root.innerHTML = '';
    root.appendChild(grid);
  }

  function refreshCamera(cam) {
    if (!cam.enabled) return;
    const img = document.getElementById(`preview-${cam.id}`);
    const offlineDiv = document.getElementById(`offline-${cam.id}`);
    const status = document.getElementById(`status-${cam.id}`);
    if (!img) return;

    const url = `/api/cameras/${cam.id}/preview.jpg?t=${Date.now()}`;
    img.onload = () => {
      img.style.display = '';
      offlineDiv.style.display = 'none';
      status.textContent = 'live';
      status.className = 'cam-status status-ok';
    };
    img.onerror = () => {
      img.style.display = 'none';
      offlineDiv.style.display = '';
      status.textContent = 'offline';
      status.className = 'cam-status status-bad';
    };
    img.src = url;
  }

  function scheduleRefreshes(cameras) {
    // Stagger cameras evenly across REFRESH_MS so they never all hit at once
    const enabled = cameras.filter(c => c.enabled);
    const gap = enabled.length > 1 ? REFRESH_MS / enabled.length : REFRESH_MS;
    enabled.forEach((cam, idx) => {
      setTimeout(function tick() {
        if (!document.hidden) refreshCamera(cam);
        setTimeout(tick, REFRESH_MS);
      }, idx * gap);
    });
  }

  function esc(s) {
    return String(s).replace(/[&<>"']/g, c =>
      ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]));
  }

  const cameras = await loadCameras();
  buildGrid(cameras);
  scheduleRefreshes(cameras);
})();
