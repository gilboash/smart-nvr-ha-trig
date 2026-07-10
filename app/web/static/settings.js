(async function () {
  const form = document.getElementById('env-form');
  const status = document.getElementById('env-status');
  if (!form) return;

  // Load current values (covers inputs inside form and those with form="env-form")
  const res = await fetch('/api/settings/env');
  if (!res.ok) { status.textContent = 'Failed to load settings.'; return; }
  const vals = await res.json();
  for (const [k, v] of Object.entries(vals)) {
    const el = document.querySelector(`[name="${k}"]`);
    if (el) el.value = v;
  }

  form.addEventListener('submit', async e => {
    e.preventDefault();
    const values = {};
    // Inputs inside the form
    for (const el of form.querySelectorAll('[name]')) {
      if (el.name) values[el.name] = el.value;
    }
    // Inputs outside the form but associated via form="env-form"
    for (const el of document.querySelectorAll(`[form="${form.id}"][name]`)) {
      if (el.name) values[el.name] = el.value;
    }
    status.className = '';
    status.textContent = 'Saving…';
    const r = await fetch('/api/settings/env', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ values }),
    });
    if (r.ok) {
      status.className = 'status-ok';
      status.textContent = 'Saved. Restart the container to apply: docker compose up -d';
    } else {
      status.className = 'status-bad';
      status.textContent = 'Save failed: ' + await r.text();
    }
  });

  // Clip stats
  async function loadClipStats() {
    const statsEl = document.getElementById('clip-stats');
    if (!statsEl) return;
    try {
      const r = await fetch('/api/clips/stats');
      if (!r.ok) { statsEl.textContent = 'Could not load clip stats.'; return; }
      const s = await r.json();
      const mb = (s.disk_bytes / 1024 / 1024).toFixed(1);
      const oldest = s.oldest_ts ? new Date(s.oldest_ts * 1000).toLocaleDateString() : '—';
      const newest = s.newest_ts ? new Date(s.newest_ts * 1000).toLocaleDateString() : '—';
      const age = s.max_age_days > 0 ? `auto-delete after ${s.max_age_days} days` : 'kept forever';
      statsEl.innerHTML =
        `<strong>${s.count}</strong> clips &nbsp;·&nbsp; <strong>${mb} MB</strong> on disk &nbsp;·&nbsp; ` +
        `oldest: ${oldest} &nbsp;·&nbsp; newest: ${newest} &nbsp;·&nbsp; ${age}<br>` +
        `<span style="color:#4a5568">Storage: ${s.clips_dir}</span>`;
    } catch (_) {
      statsEl.textContent = 'Could not load clip stats.';
    }
  }

  loadClipStats();

  // Clip cleanup button
  const cleanupBtn = document.getElementById('cleanup-btn');
  const cleanupStatus = document.getElementById('cleanup-status');
  if (cleanupBtn) {
    cleanupBtn.addEventListener('click', async () => {
      cleanupBtn.disabled = true;
      cleanupStatus.className = '';
      cleanupStatus.textContent = 'Running…';
      try {
        const r = await fetch('/api/clips/cleanup', { method: 'POST' });
        if (r.ok) {
          const j = await r.json();
          cleanupStatus.className = 'status-ok';
          cleanupStatus.textContent = j.removed === 0
            ? 'Nothing to remove.'
            : `Removed ${j.removed} clip${j.removed === 1 ? '' : 's'}.`;
          loadClipStats();
        } else {
          cleanupStatus.className = 'status-bad';
          cleanupStatus.textContent = 'Cleanup failed.';
        }
      } catch (_) {
        cleanupStatus.className = 'status-bad';
        cleanupStatus.textContent = 'Request failed.';
      }
      cleanupBtn.disabled = false;
    });
  }

  // Recording cleanup button
  const recCleanupBtn = document.getElementById('rec-cleanup-btn');
  const recCleanupStatus = document.getElementById('rec-cleanup-status');
  if (recCleanupBtn) {
    recCleanupBtn.addEventListener('click', async () => {
      recCleanupBtn.disabled = true;
      recCleanupStatus.className = '';
      recCleanupStatus.textContent = 'Running…';
      try {
        const r = await fetch('/api/recordings/cleanup', { method: 'POST' });
        if (r.ok) {
          const j = await r.json();
          recCleanupStatus.className = 'status-ok';
          recCleanupStatus.textContent = j.removed === 0
            ? 'Nothing to remove.'
            : `Removed ${j.removed} segment${j.removed === 1 ? '' : 's'}.`;
        } else {
          recCleanupStatus.className = 'status-bad';
          recCleanupStatus.textContent = 'Cleanup failed.';
        }
      } catch (_) {
        recCleanupStatus.className = 'status-bad';
        recCleanupStatus.textContent = 'Request failed.';
      }
      recCleanupBtn.disabled = false;
    });
  }
})();
