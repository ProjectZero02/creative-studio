/**
 * Copyright 2026 Google LLC
 *
 * Licensed under the Apache License, Version 2.0 (the "License");
 * you may not use this file except in compliance with the License.
 * You may obtain a copy of the License at
 *
 *     http://www.apache.org/licenses/LICENSE-2.0
 *
 * Unless required by applicable law or agreed to in writing, software
 * distributed under the License is distributed on an "AS IS" BASIS,
 * WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
 * See the License for the specific language governing permissions and
 * limitations under the License.
 */

/**
 * <gm-chat-nav>: the top of the side menu.
 *
 * Always: New chat and Library. When the menu is open: a search box,
 * Projects (folders of chats) and Recents (chats grouped Today, Yesterday,
 * Previous 7 days, Older), like ChatGPT and Gemini. Data comes from
 * /api/chats and /api/projects (routers/chats_router.py).
 *
 * Talking to the Home chat (<gm-home-chat>) goes through window events, so
 * it works on any page:
 *   gm-open-chat {id}          open a saved chat
 *   gm-new-chat {project_id}   start an empty chat (optionally in a project)
 *   gm-chats-changed           the list changed: reload it
 *   gm-active-chat {id}        the Home chat now shows this chat
 * When Home is not on screen, it asks Mesop to open /home?chat=<id>
 * (or ?new=1&project=<id>) through navEvent.
 */
import { LitElement, css, html, nothing } from 'https://cdn.jsdelivr.net/npm/lit@3.2.1/+esm';

const OPEN_KEY = 'gm-nav-projects-open';
const ICON = {
  newchat: 'M3 17.2V21h3.8l11-11-3.8-3.8zM20.7 7a1 1 0 0 0 0-1.4l-2.3-2.3a1 1 0 0 0-1.4 0l-1.8 1.8 3.8 3.8z',
  library: 'M22 16V4a2 2 0 0 0-2-2H8a2 2 0 0 0-2 2v12a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2zm-11-4 2 2.7 3-3.7 4 5H8zM2 6v14a2 2 0 0 0 2 2h14v-2H4V6z',
  search: 'M15.5 14h-.8l-.3-.3A6.5 6.5 0 1 0 14 15.5l.3.3v.8l5 5 1.5-1.5zm-6 0a4.5 4.5 0 1 1 0-9 4.5 4.5 0 0 1 0 9z',
  folder: 'M10 4H4a2 2 0 0 0-2 2v12a2 2 0 0 0 2 2h16a2 2 0 0 0 2-2V8a2 2 0 0 0-2-2h-8z',
  folderOpen: 'M20 6h-8l-2-2H4a2 2 0 0 0-2 2v12a2 2 0 0 0 2 2h16a2 2 0 0 0 2-2V8a2 2 0 0 0-2-2zm0 12H4V8h16z',
  add: 'M19 13h-6v6h-2v-6H5v-2h6V5h2v6h6z',
  more: 'M6 10a2 2 0 1 0 0 4 2 2 0 0 0 0-4zm6 0a2 2 0 1 0 0 4 2 2 0 0 0 0-4zm6 0a2 2 0 1 0 0 4 2 2 0 0 0 0-4z',
  caret: 'M10 6 8.6 7.4l4.6 4.6-4.6 4.6L10 18l6-6z',
  pin: 'M16 9V4h1V2H7v2h1v5l-2 2v2h5.2v7h1.6v-7H18v-2z',
};
const svg = (d, size = 20) => html`<svg viewBox="0 0 24 24" width=${size} height=${size} aria-hidden="true"><path d=${d}></path></svg>`;

/** "today" | "yesterday" | "week" | "older" for an ISO time. */
export function dateGroup(iso, now = new Date()) {
  const t = new Date(iso || 0);
  if (Number.isNaN(t.getTime())) return 'older';
  const start = new Date(now.getFullYear(), now.getMonth(), now.getDate()).getTime();
  const day = 86400000;
  if (t.getTime() >= start) return 'today';
  if (t.getTime() >= start - day) return 'yesterday';
  if (t.getTime() >= start - 7 * day) return 'week';
  return 'older';
}

async function api(method, url, body) {
  const r = await fetch(url, {
    method,
    credentials: 'same-origin',
    headers: body ? { 'Content-Type': 'application/json' } : {},
    body: body ? JSON.stringify(body) : undefined,
  });
  if (!r.ok) throw new Error(String(r.status));
  return r.status === 204 ? {} : r.json();
}

class GmChatNav extends LitElement {
  static properties = {
    open: { type: Boolean, reflect: true },
    current: { type: String }, // the page route, for the Library highlight
    stringsJson: { type: String },
    navEvent: { type: String },
    _chats: { state: true },
    _projects: { state: true },
    _filter: { state: true },
    _openProjects: { state: true },
    _menu: { state: true }, // {kind: 'chat'|'project', id, x, y}
    _renaming: { state: true }, // {kind, id}
    _adding: { state: true }, // typing a new project name
    _confirm: { state: true }, // id waiting for a second Delete click
    _active: { state: true },
  };

  constructor() {
    super();
    this.open = false;
    this.current = '';
    this.stringsJson = '{}';
    this.navEvent = '';
    this._chats = [];
    this._projects = [];
    this._filter = '';
    this._menu = null;
    this._renaming = null;
    this._adding = false;
    this._confirm = '';
    this._active = '';
    try { this._openProjects = new Set(JSON.parse(localStorage.getItem(OPEN_KEY) || '[]')); } catch (_) { this._openProjects = new Set(); }
    this._onChanged = () => this._load();
    this._onActive = (e) => { this._active = (e.detail && e.detail.id) || ''; };
    this._onDocClick = (e) => { if (this._menu && !e.composedPath().includes(this)) this._menu = null; };
  }

  get _s() {
    try { return JSON.parse(this.stringsJson || '{}'); } catch (_) { return {}; }
  }

  connectedCallback() {
    super.connectedCallback();
    window.addEventListener('gm-chats-changed', this._onChanged);
    window.addEventListener('gm-active-chat', this._onActive);
    document.addEventListener('click', this._onDocClick);
    try { this._active = new URL(window.location.href).searchParams.get('chat') || window.gmActiveChat || ''; } catch (_) { /* ignore */ }
    this._load();
  }

  disconnectedCallback() {
    super.disconnectedCallback();
    window.removeEventListener('gm-chats-changed', this._onChanged);
    window.removeEventListener('gm-active-chat', this._onActive);
    document.removeEventListener('click', this._onDocClick);
  }

  updated(changed) {
    if (changed.has('open') && this.open) this._load();
  }

  async _load() {
    try {
      const [c, p] = await Promise.all([api('GET', '/api/chats'), api('GET', '/api/projects')]);
      this._chats = c.chats || [];
      this._projects = p.projects || [];
    } catch (_) { /* signed out or offline: keep what we have */ }
  }

  _changed() {
    window.dispatchEvent(new CustomEvent('gm-chats-changed'));
  }

  // ------------------------------------------------------------- navigation

  _home() { return document.querySelector('gm-home-chat') || this._findDeep('gm-home-chat'); }

  _findDeep(tag) {
    // Mesop renders web components in the light DOM, but be safe.
    const walk = (root) => {
      const hit = root.querySelector(tag);
      if (hit) return hit;
      for (const el of root.querySelectorAll('*')) if (el.shadowRoot) { const f = walk(el.shadowRoot); if (f) return f; }
      return null;
    };
    try { return walk(document); } catch (_) { return null; }
  }

  _go(url, params) {
    if (this.navEvent) this.dispatchEvent(new MesopEvent(this.navEvent, { url, params: params || {} }));
    else window.location.assign(url + (params ? `?${new URLSearchParams(params)}` : ''));
  }

  _newChat(projectId = '') {
    this._menu = null;
    if (this._home()) window.dispatchEvent(new CustomEvent('gm-new-chat', { detail: { project_id: projectId } }));
    else this._go('/home', projectId ? { new: '1', project: projectId } : { new: '1' });
  }

  _openChat(id) {
    this._active = id;
    if (this._home()) window.dispatchEvent(new CustomEvent('gm-open-chat', { detail: { id } }));
    else this._go('/home', { chat: id });
  }

  // ------------------------------------------------------------- edits

  async _rename(kind, id, name) {
    // Enter saves, then the field leaves the page and blurs: save once.
    if (!this._renaming || this._renaming.id !== id) return;
    this._renaming = null;
    const value = (name || '').trim();
    if (!value) return;
    try {
      if (kind === 'chat') await api('PATCH', `/api/chats/${id}`, { title: value });
      else await api('PATCH', `/api/projects/${id}`, { name: value });
      this._changed();
    } catch (_) { this._load(); }
  }

  async _delete(kind, id) {
    if (this._confirm !== id) { this._confirm = id; return; }
    this._confirm = '';
    this._menu = null;
    try {
      await api('DELETE', kind === 'chat' ? `/api/chats/${id}` : `/api/projects/${id}`);
      if (kind === 'chat' && id === this._active) this._newChat();
      this._changed();
    } catch (_) { this._load(); }
  }

  async _patchChat(id, patch) {
    this._menu = null;
    try { await api('PATCH', `/api/chats/${id}`, patch); this._changed(); } catch (_) { this._load(); }
  }

  async _addProject(name) {
    if (!this._adding) return; // Enter already saved it (the blur follows)
    this._adding = false;
    const value = (name || '').trim();
    if (!value) return;
    try {
      const body = await api('POST', '/api/projects', { name: value });
      const id = body.project && body.project.id;
      if (id) this._toggleProject(id, true);
      this._changed();
    } catch (_) { this._load(); }
  }

  _toggleProject(id, force) {
    const next = new Set(this._openProjects);
    const on = force ?? !next.has(id);
    if (on) next.add(id); else next.delete(id);
    this._openProjects = next;
    try { localStorage.setItem(OPEN_KEY, JSON.stringify([...next])); } catch (_) { /* ignore */ }
  }

  _openMenu(e, kind, id) {
    e.stopPropagation();
    this._confirm = '';
    if (this._menu && this._menu.id === id) { this._menu = null; return; }
    const box = e.currentTarget.getBoundingClientRect();
    const host = this.getBoundingClientRect();
    this._menu = { kind, id, top: box.bottom - host.top + 4 };
  }

  // ------------------------------------------------------------- drag and drop

  _drop(e, projectId) {
    e.preventDefault();
    e.currentTarget.classList.remove('over');
    const id = e.dataTransfer.getData('text/gm-chat');
    if (id) this._patchChat(id, { project_id: projectId });
  }

  // ------------------------------------------------------------- render

  _row({ icon, label, active, onClick, title }) {
    return html`<button type="button" class="row ${active ? 'active' : ''}" @click=${onClick} title=${this.open ? '' : (title || label)} aria-label=${label}>
      ${svg(icon, 22)}<span class="lbl">${label}</span></button>`;
  }

  _editor(kind, id, value) {
    const done = (e) => this._rename(kind, id, e.target.value);
    return html`<input class="edit" .value=${value} maxlength="80" aria-label=${this._s.rename || 'Rename'}
      @keydown=${(e) => { if (e.key === 'Enter') done(e); if (e.key === 'Escape') this._renaming = null; }}
      @blur=${done}>`;
  }

  _chatRow(c, indent = false) {
    const S = this._s;
    const title = c.title || S.untitled || 'New chat';
    if (this._renaming && this._renaming.id === c.id) return html`<div class="chat ${indent ? 'in' : ''}">${this._editor('chat', c.id, title)}</div>`;
    return html`<div class="chat ${indent ? 'in' : ''} ${c.id === this._active ? 'active' : ''} ${this._menu && this._menu.id === c.id ? 'menuing' : ''}"
        draggable="true" @dragstart=${(e) => { e.dataTransfer.setData('text/gm-chat', c.id); e.dataTransfer.effectAllowed = 'move'; }}>
      <button type="button" class="chat-open" @click=${() => this._openChat(c.id)} title=${title}>
        ${c.pinned ? html`<span class="pin">${svg(ICON.pin, 14)}</span>` : nothing}<span class="t">${title}</span></button>
      <button type="button" class="more" @click=${(e) => this._openMenu(e, 'chat', c.id)} aria-label=${(S.options || 'Options') + ': ' + title}>${svg(ICON.more, 18)}</button>
    </div>`;
  }

  _menuView() {
    const m = this._menu;
    if (!m) return nothing;
    const S = this._s;
    const style = `top:${m.top}px`;
    if (m.kind === 'project') {
      const p = this._projects.find((x) => x.id === m.id);
      if (!p) return nothing;
      return html`<div class="menu" style=${style} role="menu">
        <button role="menuitem" @click=${() => this._newChat(p.id)}>${S.new_in_project || 'New chat here'}</button>
        <button role="menuitem" @click=${() => { this._menu = null; this._renaming = { kind: 'project', id: p.id }; }}>${S.rename || 'Rename'}</button>
        <button role="menuitem" class="danger" @click=${() => this._delete('project', p.id)}>${this._confirm === p.id ? (S.confirm_delete_project || 'Delete? Chats stay') : (S.delete || 'Delete')}</button>
      </div>`;
    }
    const c = this._chats.find((x) => x.id === m.id);
    if (!c) return nothing;
    return html`<div class="menu" style=${style} role="menu">
      <button role="menuitem" @click=${() => { this._menu = null; this._renaming = { kind: 'chat', id: c.id }; }}>${S.rename || 'Rename'}</button>
      <button role="menuitem" @click=${() => this._patchChat(c.id, { pinned: !c.pinned })}>${c.pinned ? (S.unpin || 'Unpin') : (S.pin || 'Pin')}</button>
      ${this._projects.length || c.project_id ? html`<div class="menu-label">${S.move || 'Move to project'}</div>
        ${this._projects.filter((p) => p.id !== c.project_id).map((p) => html`<button role="menuitem" class="sub" @click=${() => this._patchChat(c.id, { project_id: p.id })}>${svg(ICON.folder, 16)}${p.name}</button>`)}
        ${c.project_id ? html`<button role="menuitem" class="sub" @click=${() => this._patchChat(c.id, { project_id: '' })}>${S.no_project || 'Remove from project'}</button>` : nothing}` : nothing}
      <button role="menuitem" class="danger" @click=${() => this._delete('chat', c.id)}>${this._confirm === c.id ? (S.confirm_delete || 'Click again to delete') : (S.delete || 'Delete')}</button>
    </div>`;
  }

  _lists() {
    const S = this._s;
    const q = this._filter.trim().toLowerCase();
    const match = (c) => !q || (c.title || '').toLowerCase().includes(q);
    const chats = this._chats.filter(match);
    const groups = [
      ['pinned', S.pinned || 'Pinned'], ['today', S.today || 'Today'], ['yesterday', S.yesterday || 'Yesterday'],
      ['week', S.week || 'Previous 7 days'], ['older', S.older || 'Older'],
    ];
    const loose = chats.filter((c) => !c.project_id || q);
    const byGroup = {};
    loose.forEach((c) => { const g = c.pinned ? 'pinned' : dateGroup(c.updated_at); (byGroup[g] ||= []).push(c); });
    return html`
      <label class="search">${svg(ICON.search, 18)}<input type="search" .value=${this._filter} placeholder=${S.search || 'Search chats'}
        aria-label=${S.search || 'Search chats'} @input=${(e) => { this._filter = e.target.value; }}></label>

      ${q ? nothing : html`<div class="head"><span>${S.projects || 'Projects'}</span>
          <button type="button" class="head-btn" @click=${() => { this._adding = true; this.updateComplete.then(() => this.renderRoot.querySelector('.new-project')?.focus()); }}
            aria-label=${S.new_project || 'New project'} title=${S.new_project || 'New project'}>${svg(ICON.add, 18)}</button></div>
        ${this._adding ? html`<div class="chat"><input class="edit new-project" maxlength="60" placeholder=${S.project_name || 'Project name'}
            @keydown=${(e) => { if (e.key === 'Enter') this._addProject(e.target.value); if (e.key === 'Escape') this._adding = false; }}
            @blur=${(e) => this._addProject(e.target.value)}></div>` : nothing}
        ${!this._projects.length && !this._adding ? html`<p class="empty">${S.projects_empty || 'Group chats for one client or campaign.'}</p>` : nothing}
        ${this._projects.map((p) => {
          const open = this._openProjects.has(p.id);
          const inside = this._chats.filter((c) => c.project_id === p.id);
          return html`<div class="project" @dragover=${(e) => { e.preventDefault(); e.currentTarget.classList.add('over'); }}
              @dragleave=${(e) => e.currentTarget.classList.remove('over')} @drop=${(e) => this._drop(e, p.id)}>
            ${this._renaming && this._renaming.id === p.id ? html`<div class="chat">${this._editor('project', p.id, p.name)}</div>` : html`
            <div class="chat proj ${this._menu && this._menu.id === p.id ? 'menuing' : ''}">
              <button type="button" class="chat-open" @click=${() => this._toggleProject(p.id)} aria-expanded=${open ? 'true' : 'false'}>
                <span class="caret ${open ? 'down' : ''}">${svg(ICON.caret, 16)}</span>${svg(open ? ICON.folderOpen : ICON.folder, 18)}<span class="t">${p.name}</span></button>
              <button type="button" class="more" @click=${(e) => this._openMenu(e, 'project', p.id)} aria-label=${(S.options || 'Options') + ': ' + p.name}>${svg(ICON.more, 18)}</button>
            </div>`}
            ${open ? html`${inside.map((c) => this._chatRow(c, true))}
              <button type="button" class="chat in add-here" @click=${() => this._newChat(p.id)}>${svg(ICON.add, 16)}<span class="t">${S.new_in_project || 'New chat here'}</span></button>` : nothing}
          </div>`;
        })}`}

      <div class="head"><span>${S.recents || 'Recents'}</span></div>
      ${!loose.length ? html`<p class="empty">${q ? (S.no_match || 'No chats match.') : (S.recents_empty || 'Your chats show up here.')}</p>` : nothing}
      ${groups.filter(([g]) => byGroup[g]).map(([g, label]) => html`<div class="group">${label}</div>${byGroup[g].map((c) => this._chatRow(c))}`)}
    `;
  }

  render() {
    const S = this._s;
    return html`
      <nav aria-label=${S.nav || 'Chats'}>
        ${this._row({ icon: ICON.newchat, label: S.new_chat || 'New chat', onClick: () => this._newChat() })}
        ${this._row({ icon: ICON.library, label: S.library || 'Library', active: /library/.test(this.current || ''), onClick: () => this._go('/library_v2') })}
        ${this.open ? html`<div class="lists">${this._lists()}</div>` : nothing}
        ${this._menuView()}
      </nav>`;
  }

  static styles = css`
    :host { display: block; position: relative; font-family: var(--gm-font, 'Google Sans', system-ui, sans-serif); color: var(--sys-on-surface, #e8eaed); }
    * { box-sizing: border-box; }
    button { font: inherit; color: inherit; }
    svg { fill: currentColor; flex: none; }
    nav { display: flex; flex-direction: column; gap: 2px; }
    /* Rows match the rail's Mesop items: 40px, icon at 10px, pill shape. */
    .row { display: flex; align-items: center; gap: 14px; width: 100%; height: 40px; padding: 0 9px; border: 0; border-radius: 20px;
      background: transparent; cursor: pointer; text-align: start; font-size: 14px; color: var(--sys-on-surface, #e8eaed); overflow: hidden; }
    .row svg { color: var(--sys-on-surface-variant, #9aa0a6); }
    .row:hover { background: var(--gm-hover, rgba(127, 127, 127, 0.12)); }
    .row.active { background: var(--gm-active-nav, rgba(127, 127, 127, 0.18)); font-weight: 600; }
    .row.active svg { color: var(--sys-on-surface, #e8eaed); }
    .lbl { white-space: nowrap; overflow: hidden; text-overflow: ellipsis; opacity: 1; transition: opacity 160ms ease 70ms; }
    :host(:not([open])) .lbl { opacity: 0; transition: opacity 70ms ease; }
    .lists { display: flex; flex-direction: column; gap: 1px; margin-top: 8px; animation: fade 220ms ease both; }
    @keyframes fade { from { opacity: 0; transform: translateY(-4px); } to { opacity: 1; transform: none; } }

    .search { display: flex; align-items: center; gap: 8px; height: 36px; padding: 0 12px; margin: 0 0 6px; border-radius: 18px;
      background: var(--gm-tonal, rgba(127, 127, 127, 0.1)); color: var(--sys-on-surface-variant, #9aa0a6); }
    .search input { flex: 1; min-width: 0; border: 0; outline: 0; background: transparent; color: var(--sys-on-surface, #e8eaed); font: inherit; font-size: 13.5px; }
    .search input::-webkit-search-cancel-button { filter: grayscale(1); }
    .search:focus-within { outline: 2px solid var(--sys-primary, #8ab4f8); outline-offset: -2px; }

    .head { display: flex; align-items: center; justify-content: space-between; height: 32px; padding: 10px 6px 0 12px;
      font-size: 11px; font-weight: 600; letter-spacing: 0.06em; text-transform: uppercase; color: var(--sys-on-surface-variant, #9aa0a6); }
    .head-btn { width: 28px; height: 28px; border: 0; border-radius: 50%; background: transparent; cursor: pointer; display: grid; place-items: center; color: var(--sys-on-surface-variant, #9aa0a6); }
    .head-btn:hover { background: var(--gm-hover, rgba(127, 127, 127, 0.12)); color: var(--sys-on-surface, #e8eaed); }
    .group { padding: 10px 12px 2px; font-size: 12px; color: var(--sys-on-surface-variant, #9aa0a6); }
    .empty { margin: 2px 12px 6px; font-size: 12.5px; line-height: 1.4; color: var(--sys-on-surface-variant, #9aa0a6); }

    .chat { position: relative; display: flex; align-items: center; height: 34px; border-radius: 17px; }
    .chat.in { padding-left: 22px; }
    .chat:hover, .chat.menuing { background: var(--gm-hover, rgba(127, 127, 127, 0.12)); }
    .chat.active { background: var(--gm-active-nav, rgba(127, 127, 127, 0.18)); }
    .chat-open { flex: 1; min-width: 0; height: 100%; display: flex; align-items: center; gap: 6px; padding: 0 4px 0 12px; border: 0; background: transparent;
      cursor: pointer; text-align: start; font-size: 13.5px; }
    .chat.in .chat-open { padding-left: 10px; }
    .t { min-width: 0; white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }
    .pin { display: inline-flex; color: var(--sys-on-surface-variant, #9aa0a6); }
    .proj .chat-open { padding-left: 6px; gap: 6px; }
    .proj svg { color: var(--sys-on-surface-variant, #9aa0a6); }
    .caret { display: inline-flex; transition: transform 160ms ease; }
    .caret.down { transform: rotate(90deg); }
    .more { width: 30px; height: 30px; margin-right: 2px; border: 0; border-radius: 50%; background: transparent; cursor: pointer; display: grid; place-items: center;
      color: var(--sys-on-surface-variant, #9aa0a6); opacity: 0; }
    .chat:hover .more, .chat.menuing .more, .more:focus-visible { opacity: 1; }
    .more:hover { color: var(--sys-on-surface, #e8eaed); }
    .add-here { gap: 6px; padding-right: 8px; border: 0; background: transparent; cursor: pointer; font-size: 13px; color: var(--sys-on-surface-variant, #9aa0a6); width: 100%; }
    .add-here svg { margin-left: 10px; }
    .project.over { outline: 2px dashed var(--sys-primary, #8ab4f8); outline-offset: -2px; border-radius: 17px; }
    .edit { width: 100%; height: 30px; margin: 0 2px; padding: 0 10px; border: 0; border-radius: 15px; outline: 2px solid var(--sys-primary, #8ab4f8);
      background: var(--gm-tonal, rgba(127, 127, 127, 0.1)); color: var(--sys-on-surface, #e8eaed); font: inherit; font-size: 13.5px; }

    .menu { position: absolute; right: 4px; z-index: 5; min-width: 190px; max-width: 230px; padding: 6px; border-radius: 14px;
      background: var(--gm-menu-bg, var(--sys-surface-container-high, #2b2f36)); box-shadow: 0 10px 30px rgba(0, 0, 0, 0.35);
      display: flex; flex-direction: column; animation: fade 140ms ease both; }
    .menu button { display: flex; align-items: center; gap: 8px; min-height: 34px; padding: 0 10px; border: 0; border-radius: 9px; background: transparent;
      cursor: pointer; text-align: start; font-size: 13.5px; white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }
    .menu button:hover { background: var(--gm-hover, rgba(127, 127, 127, 0.14)); }
    .menu .sub { padding-left: 14px; color: var(--sys-on-surface, #e8eaed); }
    .menu .sub svg { color: var(--sys-on-surface-variant, #9aa0a6); }
    .menu-label { padding: 8px 10px 2px; font-size: 11px; color: var(--sys-on-surface-variant, #9aa0a6); }
    .menu .danger { color: #f28b82; }
    button:focus-visible, input:focus-visible { outline: 2px solid var(--sys-primary, #8ab4f8); outline-offset: 1px; }
    @media (prefers-reduced-motion: reduce) { .lists, .menu { animation: none; } .lbl, .caret { transition: none; } }
  `;
}

if (!customElements.get('gm-chat-nav')) customElements.define('gm-chat-nav', GmChatNav);
