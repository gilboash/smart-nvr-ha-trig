/* ClassPicker: searchable checkbox multi-select for COCO classes.
   Usage:
     const picker = await ClassPicker.create(containerEl, selectedArray);
     picker.selected()  // returns current selected string[]
*/
window.ClassPicker = (function () {
  class Picker {
    constructor(host, allClasses, selected) {
      this.host = host;
      this.all = allClasses;
      this._sel = new Set(selected);
      this._build();
    }

    _build() {
      this.host.innerHTML = `
        <div class="cp-wrap">
          <input class="cp-search" placeholder="Search classes…" autocomplete="off">
          <div class="cp-tags"></div>
          <div class="cp-list"></div>
        </div>
      `;
      this._searchEl = this.host.querySelector('.cp-search');
      this._tagsEl = this.host.querySelector('.cp-tags');
      this._listEl = this.host.querySelector('.cp-list');
      this._searchEl.addEventListener('input', () => this._renderList());
      this._renderTags();
      this._renderList();
    }

    _renderTags() {
      this._tagsEl.innerHTML = '';
      for (const cls of this._sel) {
        const tag = document.createElement('span');
        tag.className = 'cp-tag';
        tag.innerHTML = `${cls} <button type="button" data-cls="${cls}">×</button>`;
        tag.querySelector('button').addEventListener('click', () => {
          this._sel.delete(cls);
          this._renderTags();
          this._renderList();
        });
        this._tagsEl.appendChild(tag);
      }
    }

    _renderList() {
      const q = this._searchEl.value.trim().toLowerCase();
      const filtered = q ? this.all.filter(c => c.includes(q)) : this.all;
      this._listEl.innerHTML = '';
      for (const cls of filtered) {
        const row = document.createElement('label');
        row.className = 'cp-row' + (this._sel.has(cls) ? ' cp-checked' : '');
        row.innerHTML = `<input type="checkbox" ${this._sel.has(cls) ? 'checked' : ''}> ${cls}`;
        row.querySelector('input').addEventListener('change', e => {
          if (e.target.checked) this._sel.add(cls); else this._sel.delete(cls);
          this._renderTags();
          this._renderList();
        });
        this._listEl.appendChild(row);
      }
    }

    selected() { return [...this._sel]; }
  }

  async function create(host, selected = []) {
    const res = await fetch('/api/classes');
    const all = res.ok ? await res.json() : [];
    return new Picker(host, all, selected);
  }

  return { create };
})();
