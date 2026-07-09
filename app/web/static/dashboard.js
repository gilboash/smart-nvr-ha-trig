(async function () {
  const root = document.getElementById('dashboard-app');
  const REFRESH_MS = 2000;

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
      header.innerHTML = `<span class="cam-name">${escapeHtml(cam.name)}</span><span class="cam-status" id="status-${cam.id}"></span>`;

      const imgWrap = document.createElement('div');
      imgWrap.className = 'cam-img-wrap';

      const img = document.createElement('img');
      img.className = 'cam-preview';
      img.alt = cam.name;
      img.id = `preview-${cam.id}`;

      const offline = document.createElement('div');
      offline.className = 'cam-offline';
      offline.id = `offline-${cam.id}`;
      offline.textContent = 'No feed';
      offline.style.display = 'none';

      imgWrap.appendChild(img);
      imgWrap.appendChild(offline);
      card.appendChild(header);
      card.appendChild(imgWrap);
      grid.appendChild(card);
    }

    root.innerHTML = '';
    root.appendChild(grid);
  }

  function refreshAll(cameras) {
    for (const cam of cameras) {
      if (!cam.enabled) continue;
      const img = document.getElementById(`preview-${cam.id}`);
      const offline = document.getElementById(`offline-${cam.id}`);
      const status = document.getElementById(`status-${cam.id}`);
      if (!img) continue;

      const url = `/api/cameras/${cam.id}/preview.jpg?t=${Date.now()}`;
      const probe = new Image();
      probe.onload = () => {
        img.src = probe.src;
        img.style.display = '';
        offline.style.display = 'none';
        status.textContent = 'live';
        status.className = 'cam-status status-ok';
      };
      probe.onerror = () => {
        img.style.display = 'none';
        offline.style.display = '';
        status.textContent = 'offline';
        status.className = 'cam-status status-bad';
      };
      probe.src = url;
    }
  }

  function escapeHtml(s) {
    return String(s).replace(/[&<>"']/g, c => ({
      '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;'
    }[c]));
  }

  const cameras = await loadCameras();
  buildGrid(cameras);
  refreshAll(cameras);
  setInterval(() => refreshAll(cameras), REFRESH_MS);
})();
