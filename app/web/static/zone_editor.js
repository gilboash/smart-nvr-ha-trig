/* Vanilla canvas polygon drawer.
   click        = add vertex
   double-click = close polygon
   right-click  = close polygon
   drag vertex  = move it
   'z'          = undo last vertex
   'Escape'     = cancel current in-progress polygon
   Points are stored as normalized [0..1] coords over the snapshot's natural size.
*/
window.ZoneEditor = (function () {
  class Editor {
    constructor(host, imgUrl) {
      this.host = host;
      this.imgUrl = imgUrl;
      this.polys = [];
      this.current = [];
      this.natW = 0;
      this.natH = 0;
      this.dragIdx = null;
      this._build();
    }

    _build() {
      this.host.innerHTML = '';

      // ── top controls (always visible, above the canvas) ──────────────────
      const top = document.createElement('div');
      top.style.cssText = 'display:grid;grid-template-columns:1fr 1fr;gap:0.75rem;margin-bottom:0.75rem;align-items:start';
      top.innerHTML = `
        <div>
          <label style="font-weight:600;display:block;margin-bottom:0.25rem">Zone name</label>
          <input class="zone-name" placeholder="e.g. walkway" value="zone-1" style="width:100%">
        </div>
        <div>
          <label style="font-weight:600;display:block;margin-bottom:0.25rem">Zone type</label>
          <div style="display:flex;gap:1.25rem;padding-top:0.35rem">
            <label style="cursor:pointer"><input type="radio" name="zone-type" value="detection" checked> Detection</label>
            <label style="cursor:pointer"><input type="radio" name="zone-type" value="state"> State (CLIP)</label>
          </div>
        </div>
        <div class="state-labels-row" style="display:none;grid-column:1/-1">
          <label style="font-weight:600;display:block;margin-bottom:0.25rem">
            State labels
            <span style="font-weight:normal;color:var(--muted);font-size:0.85rem">&nbsp;comma-separated, e.g. open, closed</span>
          </label>
          <input class="state-labels-input" placeholder="open, half open, closed" style="width:100%">
        </div>
      `;
      this.host.append(top);

      // ── canvas area ───────────────────────────────────────────────────────
      const wrap = document.createElement('div');
      wrap.className = 'snapshot-wrap';
      const img = new Image();
      img.className = 'snapshot';
      img.src = this.imgUrl;
      const canvas = document.createElement('canvas');
      canvas.className = 'zone-canvas';
      wrap.append(img, canvas);
      this.host.append(wrap);

      // ── bottom buttons ────────────────────────────────────────────────────
      const btns = document.createElement('div');
      btns.style.marginTop = '0.5rem';
      btns.innerHTML = `
        <button class="save primary">Save polygon</button>
        <button class="cancel">Cancel current</button>
        <button class="reload">Refresh snapshot</button>
      `;
      this.host.append(btns);

      this.img = img;
      this.canvas = canvas;
      this.ctx = canvas.getContext('2d');
      this.top = top;
      this.btns = btns;

      img.addEventListener('load', () => this._onImg());
      canvas.addEventListener('click', e => this._onClick(e));
      canvas.addEventListener('dblclick', e => this._onDblClick(e));
      canvas.addEventListener('contextmenu', e => { e.preventDefault(); this._commit(); });
      canvas.addEventListener('mousedown', e => this._onDown(e));
      canvas.addEventListener('mousemove', e => this._onMove(e));
      window.addEventListener('mouseup', () => { this.dragIdx = null; });
      window.addEventListener('keydown', e => this._onKey(e));

      btns.querySelector('.save').addEventListener('click', () => this._save());
      btns.querySelector('.cancel').addEventListener('click', () => { this.current = []; this._redraw(); });
      btns.querySelector('.reload').addEventListener('click', () => { this.img.src = this.imgUrl + '?t=' + Date.now(); });

      top.querySelectorAll('input[name="zone-type"]').forEach(r => r.addEventListener('change', () => {
        const isState = top.querySelector('input[name="zone-type"]:checked').value === 'state';
        top.querySelector('.state-labels-row').style.display = isState ? '' : 'none';
      }));
    }

    setExistingPolygons(polys) {
      this.polys = polys.map(p => p.slice());
      this._redraw();
    }

    onSave(cb) { this._saveCb = cb; }

    _onImg() {
      this.natW = this.img.naturalWidth;
      this.natH = this.img.naturalHeight;
      this.canvas.width = this.img.clientWidth;
      this.canvas.height = this.img.clientHeight;
      window.addEventListener('resize', () => this._resize());
      this._redraw();
    }

    _resize() {
      this.canvas.width = this.img.clientWidth;
      this.canvas.height = this.img.clientHeight;
      this._redraw();
    }

    _pt(e) {
      const r = this.canvas.getBoundingClientRect();
      const x = (e.clientX - r.left) / r.width;
      const y = (e.clientY - r.top) / r.height;
      return [Math.max(0, Math.min(1, x)), Math.max(0, Math.min(1, y))];
    }

    _hit(nx, ny) {
      const r = this.canvas.getBoundingClientRect();
      for (let i = 0; i < this.polys.length; i++) {
        for (let j = 0; j < this.polys[i].length; j++) {
          const [px, py] = this.polys[i][j];
          if (Math.hypot((px - nx) * r.width, (py - ny) * r.height) < 8) return [i, j];
        }
      }
      return null;
    }

    _onClick(e) {
      if (this.dragIdx) return;
      this.current.push(this._pt(e));
      this._redraw();
    }

    _onDblClick(e) {
      e.preventDefault();
      if (this.current.length > 0) this.current.pop(); // second click of dblclick adds a spurious vertex
      this._commit();
    }

    _onDown(e) {
      const [nx, ny] = this._pt(e);
      const hit = this._hit(nx, ny);
      if (hit) this.dragIdx = hit;
    }

    _onMove(e) {
      if (!this.dragIdx) return;
      const [nx, ny] = this._pt(e);
      this.polys[this.dragIdx[0]][this.dragIdx[1]] = [nx, ny];
      this._redraw();
    }

    _onKey(e) {
      if (e.key === 'z' && this.current.length) { this.current.pop(); this._redraw(); }
      if (e.key === 'Escape') { this.current = []; this._redraw(); }
    }

    _commit() {
      if (this.current.length < 3) return;
      this.polys.push(this.current);
      this.current = [];
      this._redraw();
    }

    _redraw() {
      const ctx = this.ctx;
      const W = this.canvas.width;
      const H = this.canvas.height;
      ctx.clearRect(0, 0, W, H);
      for (const poly of this.polys) this._drawPoly(poly, 'rgba(126,226,184,0.28)', '#7ee2b8');
      if (this.current.length) this._drawPoly(this.current, 'rgba(255,200,80,0.28)', '#ffc850', true);
    }

    _drawPoly(poly, fill, stroke, open = false) {
      const ctx = this.ctx;
      const W = this.canvas.width;
      const H = this.canvas.height;
      ctx.beginPath();
      poly.forEach(([nx, ny], i) => {
        const x = nx * W, y = ny * H;
        if (i === 0) ctx.moveTo(x, y); else ctx.lineTo(x, y);
      });
      if (!open) ctx.closePath();
      ctx.fillStyle = fill; ctx.fill();
      ctx.strokeStyle = stroke; ctx.lineWidth = 2; ctx.stroke();
      ctx.fillStyle = stroke;
      poly.forEach(([nx, ny]) => {
        ctx.beginPath();
        ctx.arc(nx * W, ny * H, 4, 0, Math.PI * 2);
        ctx.fill();
      });
    }

    _save() {
      if (this.polys.length === 0) { alert('Draw at least one polygon first.'); return; }
      const name = this.top.querySelector('.zone-name').value.trim() || 'zone';
      const poly = this.polys[this.polys.length - 1];
      const zone_type = this.top.querySelector('input[name="zone-type"]:checked').value;
      let state_labels = null;
      if (zone_type === 'state') {
        const raw = this.top.querySelector('.state-labels-input').value;
        state_labels = raw.split(',').map(s => s.trim()).filter(Boolean);
        if (state_labels.length === 0) { alert('Enter at least one label for a state zone.'); return; }
      }
      if (this._saveCb) {
        this._saveCb({ name, polygon: poly, snapshot_w: this.natW, snapshot_h: this.natH, zone_type, state_labels });
      }
    }

    resetCurrent() { this.polys = []; this.current = []; this._redraw(); }
  }

  return { create: (host, imgUrl) => new Editor(host, imgUrl) };
})();
