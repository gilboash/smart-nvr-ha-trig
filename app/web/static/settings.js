(async function () {
  const form = document.getElementById('env-form');
  const status = document.getElementById('env-status');
  if (!form) return;

  // Load current values
  const res = await fetch('/api/settings/env');
  if (!res.ok) { status.textContent = 'Failed to load settings.'; return; }
  const vals = await res.json();
  for (const [k, v] of Object.entries(vals)) {
    const el = form.querySelector(`[name="${k}"]`);
    if (el) el.value = v;
  }

  form.addEventListener('submit', async e => {
    e.preventDefault();
    const values = {};
    for (const el of form.querySelectorAll('[name]')) {
      values[el.name] = el.value;
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
})();
