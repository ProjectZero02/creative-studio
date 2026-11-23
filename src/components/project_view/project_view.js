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
 * <gm-project-view>: the project page (/project?id=<id>).
 *
 * Header: the project's name (click to rename) and New chat. Below: its
 * chats (title and last update; a click opens /home?chat=<id>) and its media
 * (every finished picture, video and sound across those chats). Data comes
 * from GET /api/projects/{id} (routers/chats_router.py).
 *
 * Window events shared with <gm-chat-nav> and <gm-home-chat>:
 *   gm-chats-changed      reload (and sent after a rename or a drop)
 *   gm-active-project {id} this page shows that project ('' when it leaves)
 * A chat dragged from the side menu and dropped here joins the project.
 */
import { LitElement, css, html, nothing } from '/ui/vendor/lit-3.2.1.js';

const ICON = {
  add: 'M19 13h-6v6h-2v-6H5v-2h6V5h2v6h6z',
  edit: 'M3 17.2V21h3.8l11-11-3.8-3.8zM20.7 7a1 1 0 0 0 0-1.4l-2.3-2.3a1 1 0 0 0-1.4 0l-1.8 1.8 3.8 3.8z',
  chat: 'M20 2H4a2 2 0 0 0-2 2v18l4-4h14a2 2 0 0 0 2-2V4a2 2 0 0 0-2-2zm0 14H5.2L4 17.2V4h16z',
  folder: 'M10 4H4a2 2 0 0 0-2 2v12a2 2 0 0 0 2 2h16a2 2 0 0 0 2-2V8a2 2 0 0 0-2-2h-8z',
  play: 'M8 5v14l11-7z',
  music: 'M12 3v10.6A4 4 0 1 0 14 17V7h4V3z',
  close: 'M19 6.4 17.6 5 12 10.6 6.4 5 5 6.4l5.6 5.6L5 17.6 6.4 19l5.6-5.6 5.6 5.6 1.4-1.4-5.6-5.6z',
  download: 'M5 20h14v-2H5zM19 9h-4V3H9v6H5l7 7z',
  media: 'M22 16V4a2 2 0 0 0-2-2H8a2 2 0 0 0-2 2v12a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2zm-11-4 2 2.7 3-3.7 4 5H8zM2 6v14a2 2 0 0 0 2 2h14v-2H4V6z',
};
const svg = (d, size = 20) => html`<svg viewBox="0 0 24 24" width=${size} height=${size} aria-hidden="true"><path d=${d}></path></svg>`;

/** "video" | "audio" | "image" for a media row. */
export function mediaType(m) {
  const mime = m.mime_type || '';
  if (mime.startsWith('video/') || m.kind === 'video' || (m.kind === 'story' && m.has_film)) return 'video';
  if (mime.startsWith('audio/') || m.kind === 'music' || m.kind === 'voice') return 'audio';
  return 'image';
}

/** "5 minutes ago", "yesterday", in the page's language. */
export function ago(iso, lang = 'en', now = Date.now()) {
  const t = new Date(iso || 0).getTime();
  if (!t) return '';
  const secs = Math.round((t - now) / 1000);
  const steps = [[60, 'second'], [3600, 'minute'], [86400, 'hour'], [604800, 'day'], [2629800, 'week'], [31557600, 'month'], [Infinity, 'year']];
  const sizes = { second: 1, minute: 60, hour: 3600, day: 86400, week: 604800, month: 2629800, year: 31557600 };
  const [, unit] = steps.find(([limit]) => Math.abs(secs) < limit);
  try {
    return new Intl.RelativeTimeFormat(lang, { numeric: 'auto' }).format(Math.round(secs / sizes[unit]), unit);
  } catch (_) {
    return new Date(t).toLocaleDateString();
  }
}

class GmProjectView extends LitElement {
  static properties = {
    projectId: { type: String },
    stringsJson: { type: String },
    navEvent: { type: String },
    _project: { state: true },
    _chats: { state: true },
    _media: { state: true },
    _state: { state: true }, // 'loading' | 'ready' | 'missing'
    _renaming: { state: true },
    _over: { state: true },
    _view: { state: true }, // the media row open in the viewer
  };

  constructor() {
    super();
    this.projectId = '';
    this.stringsJson = '{}';
    this.navEvent = '';
    this._project = null;
    this._chats = [];
    this._media = [];
    this._state = 'loading';
    this._renaming = false;
    this._over = 0;
    this._view = null;
    this._onChanged = () => this._load();
  }

  get _s() {
    try { return JSON.parse(this.stringsJson || '{}'); } catch (_) { return {}; }
  }

  connectedCallback() {
    super.connectedCallback();
    window.addEventListener('gm-chats-changed', this._onChanged);
  }

  disconnectedCallback() {
    super.disconnectedCallback();
    window.removeEventListener('gm-chats-changed', this._onChanged);
    this._announce('');
  }

  updated(changed) {
    // The viewer is a modal <dialog>: the top layer covers the side menu too.
    const dialog = this.renderRoot.querySelector('dialog.viewer');
    if (dialog && !dialog.open) dialog.showModal();
    if (changed.has('projectId')) {
      this._project = null;
      this._chats = [];
      this._media = [];
      this._state = 'loading';
      this._renaming = false;
      this._announce(this.projectId);
      this._load();
    }
  }

  _announce(id) {
    window.gmActiveProject = id || '';
    window.dispatchEvent(new CustomEvent('gm-active-project', { detail: { id: id || '' } }));
  }

  async _load() {
    const id = this.projectId;
    if (!id) { this._state = 'missing'; return; }
    try {
      const r = await fetch(`/api/projects/${encodeURIComponent(id)}`, { credentials: 'same-origin' });
      if (id !== this.projectId) return;
      if (r.status === 404) { this._state = 'missing'; return; }
      if (!r.ok) return; // offline or signed out: keep what we have
      const body = await r.json();
      this._project = body.project;
      this._chats = body.chats || [];
      this._media = body.media || [];
      this._state = 'ready';
    } catch (_) { /* keep what we have */ }
  }

  // ------------------------------------------------------------- navigation

  _go(url, params) {
    if (this.navEvent) this.dispatchEvent(new MesopEvent(this.navEvent, { url, params: params || {} }));
    else window.location.assign(url + (params ? `?${new URLSearchParams(params)}` : ''));
  }

  /** A plain link that opens in place through Mesop (new tab still works). */
  _link(e, url, params) {
    if (e.defaultPrevented || e.button !== 0 || e.metaKey || e.ctrlKey || e.shiftKey || e.altKey) return;
    e.preventDefault();
    this._view = null;
    this._go(url, params);
  }

  // ------------------------------------------------------------- edits

  async _rename(value) {
    if (!this._renaming) return; // Enter saved it; the blur follows
    this._renaming = false;
    const name = (value || '').trim();
    if (!name || !this._project || name === this._project.name) return;
    const old = this._project;
    this._project = { ...old, name };
    try {
      const r = await fetch(`/api/projects/${encodeURIComponent(old.id)}`, {
        method: 'PATCH', credentials: 'same-origin', headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ name }),
      });
      if (!r.ok) throw new Error(String(r.status));
      window.dispatchEvent(new CustomEvent('gm-chats-changed'));
    } catch (_) { this._project = old; }
  }

  _startRename() {
    this._renaming = true;
    this.updateComplete.then(() => {
      const input = this.renderRoot.querySelector('.name-edit');
      if (input) { input.focus(); input.select(); }
    });
  }

  _dragOver(e) {
    if (![...(e.dataTransfer?.types || [])].includes('text/gm-chat')) return;
    e.preventDefault();
    e.dataTransfer.dropEffect = 'move';
    if (!this._over) this._over = 1;
  }

  _dragLeave(e) {
    if (!e.relatedTarget || !this.renderRoot.contains(e.relatedTarget)) this._over = 0;
  }

  async _drop(e) {
    const id = e.dataTransfer?.getData('text/gm-chat');
    this._over = 0;
    if (!id || !this.projectId) return;
    e.preventDefault();
    try {
      const r = await fetch(`/api/chats/${encodeURIComponent(id)}`, {
        method: 'PATCH', credentials: 'same-origin', headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ project_id: this.projectId }),
      });
      if (r.ok) window.dispatchEvent(new CustomEvent('gm-chats-changed'));
    } catch (_) { /* nothing moved */ }
  }

  // ------------------------------------------------------------- render

  _newChatButton(cls = '') {
    const S = this._s;
    const params = { new: '1', project: this.projectId };
    return html`<a class="btn primary ${cls}" href=${`/home?${new URLSearchParams(params)}`} @click=${(e) => this._link(e, '/home', params)}>
      ${svg(ICON.add, 20)}<span>${S.new_chat || 'New chat'}</span></a>`;
  }

  _header() {
    const S = this._s;
    const name = (this._project && this._project.name) || '';
    return html`<header class="head">
      <span class="tile">${svg(ICON.folder, 22)}</span>
      ${this._renaming
        ? html`<input class="name-edit" .value=${name} maxlength="60" aria-label=${S.name || 'Project name'}
            @keydown=${(e) => { if (e.key === 'Enter') this._rename(e.target.value); if (e.key === 'Escape') this._renaming = false; }}
            @blur=${(e) => this._rename(e.target.value)}>`
        : html`<h1 class="name"><button type="button" class="name-btn" @click=${() => this._startRename()} title=${S.rename || 'Rename'}>
            <span class="name-text">${name}</span><span class="pen">${svg(ICON.edit, 18)}</span>
            <span class="sr">${S.rename || 'Rename'}</span></button></h1>`}
      ${this._newChatButton()}
    </header>`;
  }

  _chatList() {
    const S = this._s;
    const lang = document.documentElement.lang || 'en';
    return html`<ul class="chats" role="list">
      ${this._chats.map((c) => {
        const title = c.title || S.untitled || 'New chat';
        return html`<li><a class="chat" href=${`/home?chat=${encodeURIComponent(c.id)}`} @click=${(e) => this._link(e, '/home', { chat: c.id })} title=${title}>
          <span class="chat-icon">${svg(ICON.chat, 18)}</span>
          <span class="chat-title">${title}</span>
          <time class="chat-time" datetime=${c.updated_at || ''}>${ago(c.updated_at, lang)}</time>
        </a></li>`;
      })}
    </ul>`;
  }

  _tile(m) {
    const type = mediaType(m);
    const label = m.prompt || m.handle || '';
    if (type === 'audio') {
      return html`<li class="tile-card audio">
        <div class="audio-top"><span class="audio-icon">${svg(ICON.music, 22)}</span><span class="audio-name">${m.handle || m.kind}</span></div>
        ${m.prompt ? html`<p class="audio-prompt">${m.prompt}</p>` : nothing}
        <audio src=${m.display_url} controls preload="none"></audio>
      </li>`;
    }
    return html`<li class="tile-card">
      <button type="button" class="thumb" @click=${() => { this._view = m; }} aria-label=${label} title=${label}>
        ${type === 'video'
          ? html`<video src=${m.display_url} muted playsinline loop preload="metadata"
              @mouseenter=${(e) => e.target.play().catch(() => {})} @mouseleave=${(e) => { e.target.pause(); }}
              @focus=${(e) => e.target.play().catch(() => {})}></video><span class="badge">${svg(ICON.play, 16)}</span>`
          : html`<img src=${m.display_url} alt=${label} loading="lazy" draggable="false">`}
      </button>
    </li>`;
  }

  _viewer() {
    const m = this._view;
    if (!m) return nothing;
    const S = this._s;
    const type = mediaType(m);
    const download = /^(https?:|\/(?!\/))/i.test(m.display_url);
    return html`<dialog class="viewer" aria-label=${m.handle || m.prompt || ''} @close=${() => { this._view = null; }}
        @click=${(e) => { if (e.target === e.currentTarget || e.target.classList.contains('viewer-media')) this._view = null; }}>
      <div class="viewer-box">
        <div class="viewer-media">
          ${type === 'video'
            ? html`<video src=${m.display_url} controls autoplay playsinline></video>`
            : html`<img src=${m.display_url} alt=${m.prompt || m.handle || ''}>`}
        </div>
        <div class="viewer-bar">
          <p class="viewer-prompt">${m.prompt || m.handle || ''}</p>
          <div class="viewer-acts">
            ${m.chat_id ? html`<a class="btn" href=${`/home?chat=${encodeURIComponent(m.chat_id)}`} @click=${(e) => this._link(e, '/home', { chat: m.chat_id })}>
              ${svg(ICON.chat, 18)}<span>${S.open_chat || 'Open chat'}</span></a>` : nothing}
            ${download ? html`<a class="btn icon" href=${m.display_url} download target="_blank" rel="noopener" aria-label=${S.download || 'Download'} title=${S.download || 'Download'}>${svg(ICON.download, 20)}</a>` : nothing}
            <button type="button" class="btn icon" @click=${() => { this._view = null; }} aria-label=${S.close || 'Close'} title=${S.close || 'Close'}>${svg(ICON.close, 20)}</button>
          </div>
        </div>
      </div>
    </dialog>`;
  }

  render() {
    const S = this._s;
    if (this._state === 'missing') {
      return html`<div class="wrap"><div class="empty">
        <span class="empty-icon">${svg(ICON.folder, 28)}</span>
        <h1 class="empty-title">${S.not_found || 'Project not found'}</h1>
        <a class="btn" href="/home" @click=${(e) => this._link(e, '/home')}>${S.go_home || 'Go to Home'}</a>
      </div></div>`;
    }
    if (this._state === 'loading') {
      return html`<div class="wrap" aria-busy="true"><div class="head"><span class="tile"></span><span class="ph"></span></div></div>`;
    }
    const hasChats = this._chats.length > 0;
    return html`<div class="wrap ${this._over ? 'over' : ''}" @dragover=${this._dragOver} @dragleave=${this._dragLeave} @drop=${this._drop}>
      ${this._header()}
      ${hasChats ? html`<div class="cols">
        <section class="col chats-col" aria-labelledby="h-chats">
          <h2 id="h-chats" class="sec">${S.chats || 'Chats'}<span class="count">${this._chats.length}</span></h2>
          ${this._chatList()}
        </section>
        <section class="col" aria-labelledby="h-media">
          <h2 id="h-media" class="sec">${S.media || 'Media'}${this._media.length ? html`<span class="count">${this._media.length}</span>` : nothing}</h2>
          ${this._media.length
            ? html`<ul class="grid" role="list">${this._media.map((m) => this._tile(m))}</ul>`
            : html`<p class="hint">${S.media_empty || 'Pictures, videos and sounds made in these chats show up here.'}</p>`}
        </section>
      </div>` : html`<div class="empty">
        <span class="empty-icon">${svg(ICON.chat, 28)}</span>
        <h2 class="empty-title">${S.empty_title || 'No chats yet'}</h2>
        <p class="empty-text">${S.empty || 'Start a chat here, or drag one in from the side menu.'}</p>
        ${this._newChatButton()}
      </div>`}
      ${this._over ? html`<div class="drop" aria-hidden="true"><span>${S.drop || 'Drop to add to this project'}</span></div>` : nothing}
      ${this._viewer()}
    </div>`;
  }

  static styles = css`
    :host { display: block; font-family: var(--gm-font, 'Google Sans', system-ui, sans-serif); color: var(--sys-on-surface, #1f1f1f); }
    * { box-sizing: border-box; }
    button, input { font: inherit; color: inherit; }
    svg { fill: currentColor; flex: none; }
    a { color: inherit; text-decoration: none; }
    .sr { position: absolute; width: 1px; height: 1px; overflow: hidden; clip: rect(0 0 0 0); white-space: nowrap; }
    .wrap { position: relative; max-width: 1240px; margin-inline: auto; padding-block: 8px 32px; min-height: 60vh; }

    /* Header: one row, every control 40px tall. */
    .head { display: flex; align-items: center; gap: 12px; min-height: 48px; margin-bottom: 24px; }
    .tile { width: 40px; height: 40px; border-radius: 12px; display: grid; place-items: center; flex: none;
      background: var(--gm-tonal, rgba(127, 127, 127, 0.1)); color: var(--sys-on-surface-variant, #5f6368); }
    .ph { width: 220px; height: 24px; border-radius: 8px; background: var(--gm-tonal, rgba(127, 127, 127, 0.1)); }
    .name { flex: 1 1 auto; margin: 0; min-width: 0; font-size: 26px; line-height: 1.2; font-weight: 600; letter-spacing: -0.015em; }
    .name-btn { display: inline-flex; align-items: center; gap: 8px; max-width: 100%; height: 40px; padding: 0 10px; margin-inline-start: -10px;
      border: 0; border-radius: 12px; background: transparent; cursor: text; font-size: inherit; font-weight: inherit; letter-spacing: inherit; }
    .name-btn:hover { background: var(--gm-tonal, rgba(127, 127, 127, 0.1)); }
    .name-text { min-width: 0; white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }
    .pen { display: inline-flex; color: var(--sys-on-surface-variant, #5f6368); opacity: 0; transition: opacity 120ms ease; }
    .name-btn:hover .pen, .name-btn:focus-visible .pen { opacity: 1; }
    .name-edit { flex: 1 1 auto; min-width: 0; max-width: 520px; height: 40px; padding: 0 12px; border: 0; border-radius: 12px; outline: 0;
      background: var(--gm-field-bg, rgba(127, 127, 127, 0.06)); box-shadow: inset 0 0 0 1px var(--gm-field-line, rgba(127, 127, 127, 0.2));
      font-size: 22px; font-weight: 600; }
    .name-edit:focus { box-shadow: inset 0 0 0 2px var(--gm-focus, var(--sys-primary, #1a5fd8)); }

    .btn { display: inline-flex; align-items: center; justify-content: center; gap: 8px; height: 40px; padding: 0 16px; flex: none;
      border: 0; border-radius: 20px; cursor: pointer; font-size: 14px; font-weight: 500; white-space: nowrap;
      background: var(--gm-tonal, rgba(127, 127, 127, 0.1)); color: var(--sys-on-surface, #1f1f1f); }
    .btn:hover { background: var(--gm-tonal-hover, rgba(127, 127, 127, 0.16)); }
    .btn.primary { background: var(--sys-primary, #1a5fd8); color: var(--sys-on-primary, #fff); padding-inline: 14px 18px; }
    .btn.primary:hover { filter: brightness(1.08); }
    .btn.icon { width: 40px; padding: 0; }
    .head .btn.primary { margin-inline-start: auto; }

    /* Chats beside media on wide screens, stacked on narrow ones. */
    .cols { display: grid; grid-template-columns: minmax(0, 1fr); gap: 28px; }
    @media (min-width: 1100px) { .cols { grid-template-columns: 340px minmax(0, 1fr); align-items: start; } }
    .sec { display: flex; align-items: center; gap: 8px; margin: 0 0 10px; font-size: 13px; font-weight: 600; letter-spacing: 0.04em;
      text-transform: uppercase; color: var(--sys-on-surface-variant, #5f6368); }
    .count { min-width: 22px; height: 20px; padding: 0 7px; border-radius: 10px; display: inline-grid; place-items: center;
      background: var(--gm-tonal, rgba(127, 127, 127, 0.1)); font-size: 12px; letter-spacing: 0; text-transform: none; }

    .chats { list-style: none; margin: 0; padding: 6px; border-radius: 16px; background: var(--gm-panel, var(--gm-tonal, rgba(127, 127, 127, 0.06)));
      display: flex; flex-direction: column; gap: 2px; }
    .chat { display: flex; align-items: center; gap: 12px; height: 48px; padding: 0 12px; border-radius: 12px; }
    .chat:hover { background: var(--gm-tonal-hover, rgba(127, 127, 127, 0.12)); }
    .chat-icon { display: inline-flex; color: var(--sys-on-surface-variant, #5f6368); }
    .chat-title { flex: 1; min-width: 0; font-size: 14.5px; white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }
    .chat-time { flex: none; font-size: 12.5px; color: var(--sys-on-surface-variant, #5f6368); }

    .grid { list-style: none; margin: 0; padding: 0; display: grid; gap: 12px; grid-template-columns: repeat(auto-fill, minmax(180px, 1fr)); }
    @media (max-width: 600px) { .grid { grid-template-columns: repeat(2, minmax(0, 1fr)); gap: 8px; } }
    .tile-card { position: relative; border-radius: 14px; overflow: hidden; background: var(--gm-tonal, rgba(127, 127, 127, 0.08)); }
    .thumb { display: block; width: 100%; aspect-ratio: 1; padding: 0; border: 0; background: transparent; cursor: zoom-in; position: relative; }
    .thumb img, .thumb video { display: block; width: 100%; height: 100%; object-fit: cover; transition: transform 200ms ease; }
    .thumb:hover img, .thumb:hover video { transform: scale(1.03); }
    .badge { position: absolute; inset-block-end: 8px; inset-inline-start: 8px; width: 28px; height: 28px; border-radius: 50%;
      display: grid; place-items: center; background: rgba(0, 0, 0, 0.55); color: #fff; pointer-events: none; }
    .audio { grid-column: span 2; display: flex; flex-direction: column; gap: 8px; padding: 14px; justify-content: space-between; min-height: 100%; }
    @media (max-width: 600px) { .audio { grid-column: 1 / -1; } }
    .audio-top { display: flex; align-items: center; gap: 10px; }
    .audio-icon { width: 36px; height: 36px; border-radius: 10px; display: grid; place-items: center; background: var(--gm-tonal-hover, rgba(127, 127, 127, 0.14));
      color: var(--sys-on-surface-variant, #5f6368); }
    .audio-name { font-size: 14px; font-weight: 600; text-transform: capitalize; }
    .audio-prompt { margin: 0; font-size: 13px; line-height: 1.4; color: var(--sys-on-surface-variant, #5f6368);
      display: -webkit-box; -webkit-line-clamp: 2; -webkit-box-orient: vertical; overflow: hidden; }
    .audio audio { width: 100%; height: 40px; }
    .hint { margin: 0; padding: 18px; border-radius: 16px; background: var(--gm-panel, var(--gm-tonal, rgba(127, 127, 127, 0.06)));
      font-size: 14px; color: var(--sys-on-surface-variant, #5f6368); }

    .empty { display: flex; flex-direction: column; align-items: center; text-align: center; gap: 10px; max-width: 460px; margin: 48px auto 0;
      padding: 36px 24px; border-radius: 20px; background: var(--gm-panel, var(--gm-tonal, rgba(127, 127, 127, 0.06))); }
    .empty-icon { width: 56px; height: 56px; border-radius: 16px; display: grid; place-items: center; background: var(--gm-tonal, rgba(127, 127, 127, 0.1));
      color: var(--sys-on-surface-variant, #5f6368); margin-bottom: 4px; }
    .empty-title { margin: 0; font-size: 20px; font-weight: 600; }
    .empty-text { margin: 0 0 8px; font-size: 14.5px; line-height: 1.5; color: var(--sys-on-surface-variant, #5f6368); }

    .drop { position: absolute; inset: 0; z-index: 3; display: grid; place-items: center; border-radius: 20px; pointer-events: none;
      background: color-mix(in srgb, var(--sys-primary, #1a5fd8) 10%, transparent); outline: 2px dashed var(--sys-primary, #1a5fd8); outline-offset: -2px; }
    .drop span { padding: 10px 18px; border-radius: 20px; background: var(--sys-primary, #1a5fd8); color: var(--sys-on-primary, #fff); font-size: 14px; font-weight: 500; }

    .viewer { width: 100vw; height: 100vh; max-width: none; max-height: none; margin: 0; border: 0; place-items: center;
      padding: 24px; background: transparent; color: #fff; animation: fade 160ms ease both; }
    .viewer[open] { display: grid; }
    .viewer::backdrop { background: rgba(0, 0, 0, 0.8); }
    .viewer-box { display: flex; flex-direction: column; gap: 12px; max-width: min(1100px, 100%); max-height: 100%; }
    .viewer-media { display: grid; place-items: center; min-height: 0; }
    .viewer-media img, .viewer-media video { max-width: 100%; max-height: calc(100vh - 140px); border-radius: 12px; display: block; }
    .viewer-bar { display: flex; align-items: center; gap: 12px; color: #fff; }
    .viewer-prompt { flex: 1; min-width: 0; margin: 0; font-size: 14px; line-height: 1.4; opacity: 0.9;
      display: -webkit-box; -webkit-line-clamp: 2; -webkit-box-orient: vertical; overflow: hidden; }
    .viewer-acts { display: flex; gap: 8px; flex: none; }
    .viewer .btn { background: rgba(255, 255, 255, 0.14); color: #fff; }
    .viewer .btn:hover { background: rgba(255, 255, 255, 0.22); }
    @keyframes fade { from { opacity: 0; } to { opacity: 1; } }

    @media (max-width: 600px) {
      .head { flex-wrap: wrap; gap: 10px; margin-bottom: 18px; }
      .name { font-size: 22px; flex: 1 1 0; }
      .head .btn.primary { width: 100%; order: 3; }
      .viewer { padding: 12px; }
      .viewer-bar { flex-wrap: wrap; }
      .viewer-prompt { flex-basis: 100%; }
    }
    button:focus-visible, a:focus-visible, input:focus-visible { outline: 2px solid var(--gm-focus, var(--sys-primary, #1a5fd8)); outline-offset: 2px; }
    @media (prefers-reduced-motion: reduce) { .viewer { animation: none; } .thumb img, .thumb video, .pen { transition: none; } }
  `;
}

if (!customElements.get('gm-project-view')) customElements.define('gm-project-view', GmProjectView);
