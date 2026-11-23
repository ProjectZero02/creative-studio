/**
 * Copyright 2025 Google LLC
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
 * <gm-home-chat>: the Home page. One prompt box that does everything.
 *
 * Empty: the headline, the prompt box and five type tiles (Image, Video,
 * Music, Voice, Film), centred with room around them. Hovering a tile plays a
 * sample inside it. A tile fills the box with a sample prompt; sending it
 * opens that studio with ?prompt=&go=1, which starts making it. Once there is
 * text or a conversation, the tiles shrink into a row of buttons under the
 * box. Without a picked type the box is a chat.
 *
 * Messages go to POST /api/chat (services/studio_chat.py), which answers in
 * text and starts jobs; GET /api/chat/jobs is polled until they finish, and
 * each job's result (image, video, audio, film step) shows in the thread.
 * Each chat is saved (POST/PATCH /api/chats, services/chat_store.py) after
 * every exchange and job update, with a snapshot of its jobs, so it shows in
 * the side menu's Recents and reopens later. sessionStorage keeps the open
 * chat for quick returns between pages. The side menu (<gm-chat-nav>) opens
 * and starts chats through window events: gm-open-chat {id}, gm-new-chat
 * {project_id}; this element answers with gm-active-chat and
 * gm-chats-changed. URL: /home?chat=<id> opens a chat, ?new=1 starts one.
 *
 * Box: one row like ChatGPT's: "+" on the left, then on the right Enhance
 * (rewrites the prompt with Gemini, shown once there is text), the dictation
 * mic, and one round slot that is Live (voice agent) while the box is empty
 * and Send once you type. Enter sends, Shift+Enter adds a line, Up/Down
 * recall past prompts.
 */
import { LitElement, css, html, nothing } from '/ui/vendor/lit-3.2.1.js';

const STORE = 'gm-home-chat';
const SETTINGS = 'gm-home-settings';
const HISTORY = 'gm-prompts:home';
const POLL_MS = 2000;
const MAX_FILES = 3;
const Recognition = window.SpeechRecognition || window.webkitSpeechRecognition;
const reduceMotion = () => window.matchMedia && window.matchMedia('(prefers-reduced-motion: reduce)').matches;

const ICON = {
  send: 'M4 12l1.4 1.4L11 7.8V20h2V7.8l5.6 5.6L20 12l-8-8z',
  mic: 'M12 14a3 3 0 0 0 3-3V5a3 3 0 0 0-6 0v6a3 3 0 0 0 3 3zm5-3a5 5 0 0 1-10 0H5a7 7 0 0 0 6 6.92V21h2v-3.08A7 7 0 0 0 19 11z',
  stop: 'M7 7h10v10H7z',
  plus: 'M19 13h-6v6h-2v-6H5v-2h6V5h2v6h6z',
  close: 'M19 6.4 17.6 5 12 10.6 6.4 5 5 6.4 10.6 12 5 17.6 6.4 19 12 13.4 17.6 19 19 17.6 13.4 12z',
  newchat: 'M3 17.2V21h3.8l11-11-3.8-3.8zM20.7 7a1 1 0 0 0 0-1.4l-2.3-2.3a1 1 0 0 0-1.4 0l-1.8 1.8 3.8 3.8z',
  spark: 'M12 2l2.2 6.8L21 11l-6.8 2.2L12 20l-2.2-6.8L3 11l6.8-2.2z',
  download: 'M5 20h14v-2H5zM12 16l5-5-1.4-1.4-2.6 2.6V4h-2v8.2L8.4 9.6 7 11z',
  open: 'M14 3v2h3.6l-9.8 9.8 1.4 1.4L19 6.4V10h2V3zM19 19H5V5h7V3H5a2 2 0 0 0-2 2v14a2 2 0 0 0 2 2h14a2 2 0 0 0 2-2v-7h-2z',
  edit: 'M3 17.2V21h3.8l11-11-3.8-3.8zM20.7 7a1 1 0 0 0 0-1.4l-2.3-2.3a1 1 0 0 0-1.4 0l-1.8 1.8 3.8 3.8z',
  retry: 'M17.6 6.4A8 8 0 1 0 19.7 14h-2.1a6 6 0 1 1-1.4-6.2L13 11h7V4z',
  image: 'M19 3H5a2 2 0 0 0-2 2v14a2 2 0 0 0 2 2h14a2 2 0 0 0 2-2V5a2 2 0 0 0-2-2zm0 16H5V5h14zm-5.1-6.7-2.7 3.5-1.9-2.3L6.5 17h11z',
  video: 'M17 10.5V7a1 1 0 0 0-1-1H4a1 1 0 0 0-1 1v10a1 1 0 0 0 1 1h12a1 1 0 0 0 1-1v-3.5l4 4v-11zM15 16H5V8h10z',
  film: 'M18 4l2 4h-3l-2-4h-2l2 4h-3l-2-4H8l2 4H7L5 4H4a2 2 0 0 0-2 2v12a2 2 0 0 0 2 2h16a2 2 0 0 0 2-2V4zm2 14H4V10h16z',
  music: 'M12 3v10.55A4 4 0 1 0 14 17V7h4V3z',
  voice: 'M9 13a4 4 0 1 0 0-8 4 4 0 0 0 0 8zm0-6a2 2 0 1 1 0 4 2 2 0 0 1 0-4zm0 8c-2.7 0-8 1.3-8 4v2h16v-2c0-2.7-5.3-4-8-4zm-6 4c.2-.7 3.3-2 6-2s5.8 1.3 6 2zM16 5.1a6 6 0 0 1 0 7.8l1.4 1.4a8 8 0 0 0 0-10.6z',
};
// Samples shown inside the type tiles on hover (animated webp for video and film).
const HOVER_MEDIA = ['/ui/home/word-video.webp', '/ui/home/word-film.webp', '/ui/posters/gemini-image__page-cover.webp', '/ui/posters/lyria_header.webp', '/ui/posters/capability__native-audio_16-9.webp'];
// Bar heights (0-1) of the sound equaliser shown on the Music and Voice tiles.
const EQ = [0.35, 0.6, 0.9, 0.55, 1, 0.7, 0.45, 0.8, 0.5, 0.3, 0.65, 0.4];
const svg = (d, size = 20) => html`<svg viewBox="0 0 24 24" width=${size} height=${size} aria-hidden="true"><path d=${d}></path></svg>`;

function load(key, fallback) {
  try { return JSON.parse(sessionStorage.getItem(key) || '') ?? fallback; } catch (_) { return fallback; }
}
function save(key, value) {
  try { sessionStorage.setItem(key, JSON.stringify(value)); } catch (_) { /* ignore */ }
}
function readSettings() {
  try { const v = JSON.parse(localStorage.getItem(SETTINGS) || '{}'); return v && typeof v === 'object' ? v : {}; } catch (_) { return {}; }
}
function readHistory() {
  try { const l = JSON.parse(localStorage.getItem(HISTORY) || '[]'); return Array.isArray(l) ? l : []; } catch (_) { return []; }
}
function remember(text) {
  const v = (text || '').trim();
  if (v.length < 2) return;
  const list = readHistory().filter((x) => x.toLowerCase() !== v.toLowerCase());
  list.unshift(v);
  try { localStorage.setItem(HISTORY, JSON.stringify(list.slice(0, 40))); } catch (_) { /* ignore */ }
}

class GmHomeChat extends LitElement {
  static properties = {
    stringsJson: { type: String },
    kindsJson: { type: String },
    optionsJson: { type: String },
    talkJson: { type: String },
    live: { type: Boolean, reflect: true },
    navEvent: { type: String },
    _msgs: { state: true },
    _jobs: { state: true },
    _busy: { state: true },
    _listening: { state: true },
    _files: { state: true },
    _hasText: { state: true },
    _kind: { state: true },
    _enhancing: { state: true },
    _panel: { state: true },
    _settings: { state: true },
    _dragOver: { state: true },
    panelOpen: { type: Boolean, reflect: true, attribute: 'panel' },
  };

  constructor() {
    super();
    this.stringsJson = '{}';
    this.kindsJson = '[]';
    this.optionsJson = '{}';
    // Settings picked in the type controls, per type; kept between visits.
    this._settings = readSettings();
    this.talkJson = '{}';
    this.live = false;
    this.navEvent = '';
    this._msgs = load(STORE, { msgs: [] }).msgs || [];
    this._jobs = load(STORE, { jobs: {} }).jobs || {};
    this._busy = false;
    this._listening = false;
    this._hist = -1;
    this._draft = '';
    this._timer = null;
    this._rec = null;
    this._files = []; // [{ id, name, preview, handle, url, busy, error }]
    this._hasText = false;
    this._kind = ''; // the picked type chip ('' = chat)
    this._sample = {}; // kind -> index of the sample shown last
    this._enhancing = false;
    const kept = load(STORE, {});
    this._chatId = kept.chatId || ''; // saved chat id ('' until the first send)
    this._projectId = kept.projectId || ''; // project for a new chat
    this._saveTimer = null;
    this._loading = false;
    // Jobs panel on the right: opens on the first job of a chat unless the
    // person closed it; closed, a "Jobs" pill brings it back.
    this._panel = !!kept.panel;
    this._panelClosed = !!kept.panelClosed;
    this._dragOver = false;
    this.panelOpen = false;
    this._onOpenChat = (e) => this._openChat((e.detail && e.detail.id) || '');
    this._onNewChat = (e) => this._newChat((e.detail && e.detail.project_id) || '');
  }

  get _kinds() {
    try { return JSON.parse(this.kindsJson || '[]'); } catch (_) { return []; }
  }

  /** The type controls' fields: {image: [field], video: [...], ...}. */
  get _options() {
    try { return JSON.parse(this.optionsJson || '{}') || {}; } catch (_) { return {}; }
  }

  /** The fields shown for a type, each with its current value and choices. */
  _fields(kind) {
    const list = this._options[kind] || [];
    const mine = this._settings[kind] || {};
    const out = [];
    const picked = {};
    list.forEach((f) => {
      const choice = (f.by_model && f.by_model[picked.model]) || f;
      const values = (choice.options || []).map((o) => o.value);
      const value = values.includes(mine[f.name]) ? mine[f.name] : choice.default;
      picked[f.name] = value;
      out.push({ ...f, options: choice.options || [], value });
    });
    return out;
  }

  _values(kind) {
    const out = {};
    this._fields(kind).forEach((f) => { out[f.name] = f.value; });
    return out;
  }

  _setField(kind, name, value) {
    this._settings = { ...this._settings, [kind]: { ...(this._settings[kind] || {}), [name]: value } };
    try { localStorage.setItem(SETTINGS, JSON.stringify(this._settings)); } catch (_) { /* ignore */ }
  }

  get _s() {
    try { return JSON.parse(this.stringsJson || '{}'); } catch (_) { return {}; }
  }

  connectedCallback() {
    super.connectedCallback();
    window.addEventListener('gm-open-chat', this._onOpenChat);
    window.addEventListener('gm-new-chat', this._onNewChat);
    let params = new URLSearchParams();
    try { params = new URL(window.location.href).searchParams; } catch (_) { /* ignore */ }
    const askedChat = params.get('chat') || '';
    if (params.get('new')) this._newChat(params.get('project') || '');
    else if (askedChat && askedChat !== this._chatId) this._openChat(askedChat);
    else this._announce();
    if (this._pending().length) this._poll();
    const warm = () => HOVER_MEDIA.forEach((src) => { const i = new Image(); i.src = src; });
    if (!reduceMotion()) {
      if (window.requestIdleCallback) window.requestIdleCallback(warm, { timeout: 4000 });
      else setTimeout(warm, 2000);
    }
    setTimeout(() => window.gmLive && window.gmLive.refreshLauncher && window.gmLive.refreshLauncher(), 60);
  }

  disconnectedCallback() {
    super.disconnectedCallback();
    window.removeEventListener('gm-open-chat', this._onOpenChat);
    window.removeEventListener('gm-new-chat', this._onNewChat);
    if (this._saveTimer) { clearTimeout(this._saveTimer); this._persist(); }
    clearTimeout(this._timer);
    if (this._rec) try { this._rec.stop(); } catch (_) { /* ignore */ }
    setTimeout(() => window.gmLive && window.gmLive.refreshLauncher && window.gmLive.refreshLauncher(), 60);
  }

  updated(changed) {
    if (changed.has('_msgs') || changed.has('_jobs') || changed.has('_panel')) {
      save(STORE, { msgs: this._msgs, jobs: this._jobs, chatId: this._chatId, projectId: this._projectId, panel: this._panel, panelClosed: this._panelClosed });
      if (!this._loading && this._msgs.length) this._queueSave();
      // Keep the newest message in view: scroll the page's scroller to the end.
      const scroller = this.closest('.gm-page');
      if (scroller && this._msgs.length && changed.has('_msgs')) scroller.scrollTo({ top: scroller.scrollHeight, behavior: reduceMotion() ? 'auto' : 'smooth' });
    }
  }

  get _ta() { return this.renderRoot.querySelector('textarea'); }

  // ---------------------------------------------------------------- sending

  async _send(text) {
    const typed = (text ?? this._ta?.value ?? '').trim();
    const files = this._files.filter((f) => f.handle);
    if ((!typed && !files.length) || this._busy || this._files.some((f) => f.busy)) return;
    if (typed) remember(typed);
    const kind = this._kinds.find((k) => k.kind === this._kind);
    if (kind && this._options[kind.kind]) {
      await this._make(kind, typed, files);
      return;
    }
    if (kind && typed && !files.length) {
      // Type chip: open that studio with the prompt; ?go=1 starts it there.
      this._busy = true;
      if (this.navEvent) {
        this.dispatchEvent(new MesopEvent(this.navEvent, { route: kind.href, params: { prompt: typed, go: '1' } }));
      } else {
        window.location.assign(`${kind.href}?prompt=${encodeURIComponent(typed)}&go=1`);
      }
      return;
    }
    this._hist = -1;
    if (this._ta) { this._ta.value = ''; this._fit(); }
    this._hasText = false;
    const said = typed || this._s.attach_default || 'What can you make from this?';
    const message = files.length ? `[Attached: ${files.map((f) => f.handle).join(', ')}] ${said}` : said;
    this._files = [];
    this._msgs = [...this._msgs, { role: 'user', text: said, images: files.map((f) => f.url) }];
    this._busy = true;
    let reply = '';
    let jobs = [];
    try {
      const r = await fetch('/api/chat', {
        method: 'POST',
        credentials: 'same-origin',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ message }),
      });
      if (!r.ok) throw new Error(String(r.status));
      const body = await r.json();
      reply = body.reply || '';
      jobs = Array.isArray(body.jobs) ? body.jobs : [];
    } catch (_) {
      reply = this._s.error || 'Something went wrong. Please try again.';
    }
    const next = { ...this._jobs };
    jobs.forEach((j) => { next[j.id] = j; });
    this._jobs = next;
    this._msgs = [...this._msgs, { role: 'assistant', text: reply, jobs: jobs.map((j) => j.id), ask: message }];
    this._busy = false;
    if (jobs.length && !this._panelClosed && !this._phone()) this._panel = true;
    if (jobs.length) this._poll();
    this.updateComplete.then(() => this._ta && this._ta.focus());
  }

  /** Type controls: start the job with exactly these settings (no chat model). */
  async _make(kind, typed, files) {
    const S = this._s;
    if (!typed) {
      this._flash(S.need_prompt || 'Write what to make first.');
      return;
    }
    const settings = this._values(kind.kind);
    const source = (kind.kind === 'image' || kind.kind === 'video') && files.length ? files[0].handle : '';
    this._hist = -1;
    if (this._ta) { this._ta.value = ''; this._fit(); }
    this._hasText = false;
    this._files = [];
    this._msgs = [...this._msgs, { role: 'user', text: typed, images: files.map((f) => f.url) }];
    this._busy = true;
    let reply = '';
    let meta = '';
    let job = null;
    try {
      const r = await fetch('/api/chat/job', {
        method: 'POST', credentials: 'same-origin',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ kind: kind.kind, prompt: typed, settings, source }),
      });
      const body = await r.json().catch(() => ({}));
      if (!r.ok) throw new Error(body.detail || '');
      reply = body.reply || '';
      meta = [kind.label, body.summary].filter(Boolean).join(' · ');
      job = body.job || null;
    } catch (err) {
      reply = (err && err.message) || S.error || 'Something went wrong. Please try again.';
    }
    if (job) this._jobs = { ...this._jobs, [job.id]: job };
    this._msgs = [...this._msgs, { role: 'assistant', text: reply, jobs: job ? [job.id] : [], meta }];
    this._busy = false;
    if (job && !this._panelClosed && !this._phone()) this._panel = true;
    if (job) this._poll();
    this.updateComplete.then(() => this._ta && this._ta.focus());
  }

  _flash(text) {
    this._note = text;
    this.requestUpdate();
    clearTimeout(this._noteTimer);
    this._noteTimer = setTimeout(() => { this._note = ''; this.requestUpdate(); }, 2600);
  }

  _pending() {
    return Object.values(this._jobs).filter((j) => j.status !== 'done' && j.status !== 'failed');
  }

  _poll() {
    clearTimeout(this._timer);
    this._timer = setTimeout(async () => {
      try {
        const r = await fetch('/api/chat/jobs', { credentials: 'same-origin' });
        if (r.ok) {
          const body = await r.json();
          const next = { ...this._jobs };
          (body.jobs || []).forEach((j) => { if (next[j.id]) next[j.id] = j; });
          // Jobs the server no longer knows (restart, new chat elsewhere).
          const known = new Set((body.jobs || []).map((j) => j.id));
          Object.values(next).forEach((j) => {
            if (!known.has(j.id) && j.status !== 'done' && j.status !== 'failed') {
              next[j.id] = { ...j, status: 'failed', error: this._s.lost || 'This job was lost. Please try again.' };
            }
          });
          this._jobs = next;
        }
      } catch (_) { /* try again next tick */ }
      if (this._pending().length) this._poll();
    }, POLL_MS);
  }

  async _newChat(projectId = '') {
    clearTimeout(this._timer);
    if (this._saveTimer) { clearTimeout(this._saveTimer); this._saveTimer = null; await this._persist(); }
    this._loading = true;
    this._msgs = [];
    this._jobs = {};
    this._chatId = '';
    this._projectId = projectId || '';
    this._panel = false;
    this._panelClosed = false;
    this._setUrl('');
    this._announce();
    try {
      await fetch('/api/chat/reset', { method: 'POST', credentials: 'same-origin', headers: { 'Content-Type': 'application/json' } });
    } catch (_) { /* local reset is enough */ }
    await this.updateComplete;
    this._loading = false;
    this._ta && this._ta.focus();
  }

  // ---------------------------------------------------------------- saved chats

  _announce() {
    window.gmActiveChat = this._chatId;
    window.dispatchEvent(new CustomEvent('gm-active-chat', { detail: { id: this._chatId } }));
  }

  _setUrl(id) {
    // Keep the address shareable (/home?chat=<id>) without a page load.
    try {
      const url = new URL(window.location.href);
      if (!/^\/(home)?$/.test(url.pathname)) return;
      ['chat', 'new', 'project'].forEach((k) => url.searchParams.delete(k));
      if (id) url.searchParams.set('chat', id);
      window.history.replaceState(window.history.state, '', url.pathname + url.search);
    } catch (_) { /* ignore */ }
  }

  /** A job as stored in the chat: what the thread needs to draw it again. */
  _snapshot(id) {
    const j = this._jobs[id];
    if (!j) return { id };
    const p = j.params || {};
    return {
      id: j.id, kind: j.kind, status: j.status, handle: j.handle, prompt: j.prompt, error: j.error,
      display_url: j.display_url, mime_type: j.mime_type,
      params: { story_id: p.story_id, story_step: p.story_step, has_film: p.has_film },
    };
  }

  _queueSave() {
    clearTimeout(this._saveTimer);
    this._saveTimer = setTimeout(() => { this._saveTimer = null; this._persist(); }, 700);
  }

  async _persist() {
    if (!this._msgs.length) return;
    const messages = this._msgs.map((m) => ({
      role: m.role, text: m.text || '', images: (m.images || []).filter((u) => u && !String(u).startsWith('blob:')),
      jobs: (m.jobs || []).map((id) => this._snapshot(typeof id === 'string' ? id : id.id)), ask: m.ask || null, meta: m.meta || '',
    }));
    const job_ids = Object.keys(this._jobs);
    try {
      if (!this._chatId) {
        const r = await fetch('/api/chats', {
          method: 'POST', credentials: 'same-origin', headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ messages, job_ids, project_id: this._projectId }),
        });
        if (!r.ok) return;
        const body = await r.json();
        this._chatId = (body.chat && body.chat.id) || '';
        save(STORE, { msgs: this._msgs, jobs: this._jobs, chatId: this._chatId, projectId: this._projectId });
        this._setUrl(this._chatId);
        this._announce();
        // The first save has no title yet; this PATCH gives it one.
        await fetch(`/api/chats/${this._chatId}`, {
          method: 'PATCH', credentials: 'same-origin', headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ messages }),
        });
      } else {
        await fetch(`/api/chats/${this._chatId}`, {
          method: 'PATCH', credentials: 'same-origin', headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ messages, job_ids }),
        });
      }
      window.dispatchEvent(new CustomEvent('gm-chats-changed'));
    } catch (_) { /* saved next time */ }
  }

  async _openChat(id) {
    if (!id || id === this._chatId) { this._announce(); return; }
    if (this._saveTimer) { clearTimeout(this._saveTimer); this._saveTimer = null; await this._persist(); }
    let chat = null;
    try {
      const r = await fetch(`/api/chats/${encodeURIComponent(id)}`, { credentials: 'same-origin' });
      if (r.ok) chat = (await r.json()).chat;
    } catch (_) { /* below */ }
    if (!chat) { this._newChat(); return; }
    clearTimeout(this._timer);
    this._loading = true;
    const jobs = {};
    const msgs = (chat.messages || []).map((m) => {
      const ids = (m.jobs || []).map((j) => {
        if (j && typeof j === 'object' && j.id) { jobs[j.id] = { ...j, params: j.params || {} }; return j.id; }
        return String(j);
      });
      return { role: m.role, text: m.text, images: m.images || [], jobs: ids, ask: m.ask || undefined, meta: m.meta || '' };
    });
    this._chatId = chat.id;
    this._projectId = chat.project_id || '';
    this._jobs = jobs;
    this._panelClosed = false;
    this._panel = Object.keys(jobs).length > 0 && !this._phone();
    this._msgs = msgs;
    this._setUrl(chat.id);
    this._announce();
    // Give the studio chat the earlier turns, so "make a video from image 1" still works.
    try {
      await fetch('/api/chat/load', {
        method: 'POST', credentials: 'same-origin', headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ messages: msgs.map((m) => ({ role: m.role, text: m.text || '' })), job_ids: Object.keys(jobs) }),
      });
    } catch (_) { /* the chat still shows */ }
    await this.updateComplete;
    this._loading = false;
    if (this._pending().length) this._poll();
  }

  _prefill(text) {
    const ta = this._ta;
    if (!ta) return;
    ta.value = text;
    this._fit();
    this._hasText = !!text.trim();
    ta.focus();
    ta.setSelectionRange(text.length, text.length);
  }

  // ---------------------------------------------------------------- type chips

  _pickKind(k) {
    const cur = (this._ta?.value || '').trim();
    const isSample = !cur || this._kinds.some((x) => (x.samples || []).includes(cur));
    if (this._kind === k.kind) {
      // Same chip again: next sample; after the last one, back to chat.
      const next = (this._sample[k.kind] ?? 0) + 1;
      if (next >= (k.samples || []).length || !isSample) {
        this._kind = '';
        if (isSample) this._prefill('');
        return;
      }
      this._sample = { ...this._sample, [k.kind]: next };
      this._prefill(k.samples[next]);
      return;
    }
    this._kind = k.kind;
    this._sample = { ...this._sample, [k.kind]: 0 };
    // Fill a sample only over an empty box or another chip's sample.
    if (isSample && (k.samples || []).length) this._prefill(k.samples[0]);
    else this._ta?.focus();
  }

  _kindChips(compact) {
    const list = this._kinds;
    if (!list.length) return nothing;
    return html`<div class="kinds ${compact ? 'compact' : ''}" role="group" aria-label=${this._s.kinds || 'What to make'}>
      ${compact ? html`<button type="button" class="kind k-auto" aria-pressed=${this._kind ? 'false' : 'true'}
          title=${this._s.auto_tip || 'The chat picks what to make'} @click=${() => { this._kind = ''; this._ta?.focus(); }}>
          <span class="kbody">${svg(ICON.spark, 20)}<span class="ktext"><b>${this._s.auto || 'Auto'}</b></span></span></button>` : nothing}
      ${list.map((k) => html`<button type="button" class="kind k-${k.kind}" aria-pressed=${this._kind === k.kind ? 'true' : 'false'}
          title=${k.desc || ''} @click=${() => this._pickKind(k)}>
          <span class="kmedia" aria-hidden="true">${k.kind === 'music' || k.kind === 'voice' ? html`<span class="eq">${EQ.map((h, i) => html`<i style="--h:${h};--d:${i * -97}ms"></i>`)}</span>` : nothing}</span>
          <span class="kbody">${svg(ICON[k.kind] || ICON.spark, 20)}<span class="ktext"><b>${k.label}</b>${k.desc ? html`<small>${k.desc}</small>` : nothing}</span></span>
        </button>`)}
    </div>`;
  }

  // ---------------------------------------------------------------- enhance

  async _enhance() {
    const text = (this._ta?.value || '').trim();
    if (!text || this._enhancing) return;
    this._enhancing = true;
    try {
      const r = await fetch('/api/prompts/enhance', {
        method: 'POST',
        credentials: 'same-origin',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ prompt: text, kind: this._kind }),
      });
      if (r.ok) {
        const body = await r.json();
        // Replace only what was enhanced (the person may have kept typing).
        if (body.prompt && this._ta && this._ta.value.trim() === text) this._prefill(body.prompt);
      }
    } catch (_) { /* keep their words */ }
    this._enhancing = false;
  }

  // ---------------------------------------------------------------- attach

  _pick() { this.renderRoot.querySelector('input[type=file]')?.click(); }

  _onFiles(e) {
    this._addFiles([...(e.target.files || [])]);
    e.target.value = '';
  }

  _onPaste(e) {
    const files = [...(e.clipboardData?.files || [])].filter((f) => f.type.startsWith('image/'));
    if (files.length) { e.preventDefault(); this._addFiles(files); }
  }

  _addFiles(list) {
    const room = MAX_FILES - this._files.length;
    list.filter((f) => /^image\/(png|jpeg|webp)$/.test(f.type)).slice(0, Math.max(0, room)).forEach((file) => {
      const id = Math.random().toString(36).slice(2, 9);
      const item = { id, name: file.name, preview: URL.createObjectURL(file), busy: true };
      this._files = [...this._files, item];
      const reader = new FileReader();
      reader.onload = async () => {
        let patch = { busy: false, error: this._s.attach_failed || 'Could not attach' };
        try {
          const r = await fetch('/api/chat/upload', {
            method: 'POST', credentials: 'same-origin',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ data: reader.result, name: file.name }),
          });
          const body = await r.json();
          if (r.ok && body.job) patch = { busy: false, handle: body.job.handle, url: body.job.display_url };
          else if (body.detail) patch.error = body.detail;
        } catch (_) { /* keeps the error */ }
        this._files = this._files.map((f) => (f.id === id ? { ...f, ...patch } : f));
      };
      reader.readAsDataURL(file);
    });
  }

  _unattach(id) {
    const gone = this._files.find((f) => f.id === id);
    if (gone && gone.preview.startsWith('blob:')) URL.revokeObjectURL(gone.preview);
    this._files = this._files.filter((f) => f.id !== id);
  }

  /** Put a finished picture in the box as a reference ("[Attached: image 2]"). */
  _useRef(j) {
    if (!j || j.status !== 'done' || j.kind !== 'image' || !j.display_url) return false;
    if (!this._files.some((f) => f.handle === j.handle)) {
      if (this._files.length >= MAX_FILES) return false;
      this._files = [...this._files, { id: `job-${j.id}`, name: j.handle, preview: j.display_url, handle: j.handle, url: j.display_url }];
    }
    if (this._phone()) this._panel = false;
    this.updateComplete.then(() => this._ta && this._ta.focus());
    return true;
  }

  /** Animate: the picture goes in the box and the text asks for a video. */
  _animate(j) {
    if (!this._useRef(j)) return;
    const lead = this._s.animate_lead || 'Make a video: ';
    const now = (this._ta?.value || '').trim();
    this.updateComplete.then(() => this._prefill(now ? `${lead}${now}` : lead));
  }

  _phone() {
    return !!(window.matchMedia && window.matchMedia('(max-width: 760px)').matches);
  }

  _togglePanel(open) {
    this._panel = open;
    if (!open) this._panelClosed = true;
  }

  // Drag a finished picture from the jobs panel (or a file) onto the box.
  _onDragOver(e) {
    const types = [...(e.dataTransfer?.types || [])];
    if (!types.includes('application/x-gm-job') && !types.includes('Files')) return;
    e.preventDefault();
    e.dataTransfer.dropEffect = 'copy';
    if (!this._dragOver) this._dragOver = true;
  }

  _onDragLeave(e) {
    if (!e.currentTarget.contains(e.relatedTarget)) this._dragOver = false;
  }

  _onDrop(e) {
    this._dragOver = false;
    const id = e.dataTransfer?.getData('application/x-gm-job');
    const files = [...(e.dataTransfer?.files || [])];
    if (!id && !files.length) return;
    e.preventDefault();
    if (id) this._useRef(this._jobs[id]);
    else this._addFiles(files);
  }

  _attachments() {
    if (!this._files.length) return nothing;
    return html`<div class="files">${this._files.map((f) => html`
      <div class="file ${f.error ? 'bad' : ''}" title=${f.error || f.name}>
        <img src=${f.preview} alt=${f.name}>
        ${f.busy ? html`<span class="file-spin" aria-hidden="true"></span>` : nothing}
        <button type="button" class="file-x" @click=${() => this._unattach(f.id)} aria-label=${(this._s.remove || 'Remove') + ' ' + f.name}>${svg(ICON.close, 14)}</button>
      </div>`)}</div>`;
  }

  // ---------------------------------------------------------------- keys

  _onInput() {
    this._fit();
    const has = !!(this._ta?.value || '').trim();
    if (has !== this._hasText) this._hasText = has;
  }

  _fit() {
    const ta = this._ta;
    if (!ta) return;
    ta.style.height = 'auto';
    ta.style.height = `${Math.min(ta.scrollHeight, 220)}px`;
  }

  _onKey(e) {
    const ta = e.target;
    if (e.key === 'Enter' && !e.shiftKey && !e.isComposing) {
      e.preventDefault();
      this._send();
      return;
    }
    if ((e.key !== 'ArrowUp' && e.key !== 'ArrowDown') || e.shiftKey || e.altKey || e.ctrlKey || e.metaKey) return;
    if (ta.selectionStart !== ta.selectionEnd) return;
    const list = readHistory();
    if (e.key === 'ArrowUp') {
      if (ta.value.slice(0, ta.selectionStart).includes('\n') || this._hist + 1 >= list.length) return;
      e.preventDefault();
      if (this._hist === -1) this._draft = ta.value;
      this._hist += 1;
      this._prefill(list[this._hist]);
    } else {
      if (ta.value.slice(ta.selectionEnd).includes('\n') || this._hist < 0) return;
      e.preventDefault();
      this._hist -= 1;
      this._prefill(this._hist < 0 ? this._draft : list[this._hist]);
    }
  }

  // ---------------------------------------------------------------- dictation

  _toggleMic() {
    if (!Recognition) return;
    if (this._listening) { try { this._rec.stop(); } catch (_) { /* ignore */ } return; }
    const rec = new Recognition();
    rec.lang = document.documentElement.lang === 'ar' ? 'ar-QA' : 'en-US';
    rec.interimResults = false;
    rec.continuous = true;
    rec.onresult = (ev) => {
      let said = '';
      for (let i = ev.resultIndex; i < ev.results.length; i += 1) if (ev.results[i].isFinal) said += ev.results[i][0].transcript;
      if (!said.trim() || !this._ta) return;
      const cur = this._ta.value.trim();
      this._prefill(cur ? `${cur} ${said.trim()}` : said.trim());
    };
    rec.onend = () => { this._listening = false; this._rec = null; };
    rec.onerror = () => { this._listening = false; };
    this._rec = rec;
    this._listening = true;
    try { rec.start(); } catch (_) { this._listening = false; }
  }

  // ---------------------------------------------------------------- render

  _box() {
    const S = this._s;
    const talk = this.talkJson || '{}';
    const ready = this._hasText || this._files.some((f) => f.handle);
    const kind = this._kinds.find((k) => k.kind === this._kind);
    const sendLabel = kind ? `${S.send || 'Send'}: ${kind.label}` : (S.send || 'Send');
    // One round slot: Live while empty, Send once there is something to send.
    let slot;
    if (this._busy) {
      slot = html`<button class="send" type="button" disabled aria-label=${S.send || 'Send'}><span class="spin" aria-hidden="true"></span></button>`;
    } else if (ready || !this.live) {
      slot = html`<button class="send ${ready ? '' : 'off'}" type="button" @click=${() => this._send()} ?disabled=${!ready}
          aria-label=${sendLabel} title=${sendLabel}>${svg(ICON.send, 22)}</button>`;
    } else {
      slot = html`<live-call-button pill .stringsJson=${talk}></live-call-button>`;
    }
    const enhanceLabel = this._enhancing ? (S.enhancing || 'Enhancing…') : (S.enhance || 'Enhance prompt');
    return html`
      <div class="box ${this._busy ? 'busy' : ''} ${this._dragOver ? 'drop' : ''}"
        @dragover=${this._onDragOver} @dragleave=${this._onDragLeave} @drop=${this._onDrop}>
        ${this._attachments()}
        <input type="file" accept="image/png,image/jpeg,image/webp" multiple hidden @change=${this._onFiles}>
        <div class="row">
          <button class="icon" type="button" @click=${this._pick} ?disabled=${this._files.length >= MAX_FILES}
            aria-label=${S.attach || 'Add a picture'} title=${S.attach_tip || 'Add a picture to edit or animate'}>${svg(ICON.plus, 24)}</button>
          <textarea rows="1" @paste=${this._onPaste} .placeholder=${S.placeholder || 'Ask me anything'}
            aria-label=${S.placeholder || 'Ask me anything'}
            @keydown=${this._onKey} @input=${this._onInput}></textarea>
          <div class="tools">
            ${this._hasText ? html`<button class="icon ${this._enhancing ? 'working' : ''}" type="button" @click=${this._enhance}
                ?disabled=${this._enhancing} aria-label=${enhanceLabel} title=${enhanceLabel}>${svg(ICON.spark, 20)}</button>` : nothing}
            ${Recognition ? html`<button class="icon ${this._listening ? 'on' : ''}" type="button" @click=${this._toggleMic}
                aria-pressed=${this._listening ? 'true' : 'false'}
                aria-label=${this._listening ? (S.dictate_stop || 'Stop dictation') : (S.dictate || 'Dictate')}
                title=${this._listening ? (S.dictate_stop || 'Stop dictation') : (S.dictate || 'Dictate')}>
                ${svg(this._listening ? ICON.stop : ICON.mic, 22)}</button>` : nothing}
            ${slot}
          </div>
        </div>
        ${this._controls()}
        ${this._note ? html`<div class="note" role="status">${this._note}</div>` : nothing}
      </div>`;
  }

  /** The picked type's settings, sliding open under the text. */
  _controls() {
    const kind = this._options[this._kind] ? this._kind : '';
    const fields = kind ? this._fields(kind).filter((f) => f.options.length > 1) : [];
    return html`<div class="ctl-wrap ${fields.length ? 'open' : ''}" aria-hidden=${fields.length ? 'false' : 'true'}>
      <div class="ctl-in"><div class="controls" role="group" aria-label=${this._s.settings || 'Settings'}>
        ${fields.map((f) => html`<label class="ctl" title=${f.label}>
          <span class="ctl-l">${f.label}</span>
          <select .value=${f.value} @change=${(e) => this._setField(kind, f.name, e.target.value)} ?disabled=${!fields.length}>
            ${f.options.map((o) => html`<option value=${o.value} ?selected=${o.value === f.value}>${o.label}</option>`)}
          </select>
          <svg class="caret" viewBox="0 0 24 24" width="16" height="16" aria-hidden="true"><path d="M7 10l5 5 5-5z"></path></svg>
        </label>`)}
      </div></div>
    </div>`;
  }

  _media(j) {
    const url = j.display_url || '';
    const mime = j.mime_type || '';
    if (!url) return nothing;
    if (mime.startsWith('video/') || j.kind === 'video' || (j.kind === 'story' && j.params && j.params.has_film)) {
      return html`<video class="media" src=${url} controls playsinline preload="metadata"></video>`;
    }
    if (mime.startsWith('audio/') || j.kind === 'music' || j.kind === 'voice') {
      return html`<audio class="audio" src=${url} controls preload="metadata"></audio>`;
    }
    if (mime.startsWith('image/') || j.kind === 'image') {
      return html`<a href=${url} target="_blank" rel="noopener"><img class="media" src=${url} alt=${j.prompt || j.handle} loading="lazy"></a>`;
    }
    return nothing;
  }

  _studio(j) {
    if (j.kind === 'story') {
      const p = j.params || {};
      return p.story_id ? `/story?id=${encodeURIComponent(p.story_id)}&step=${encodeURIComponent(p.story_step || 'scenario')}` : '/story';
    }
    return '/library_v2';
  }

  _openStudio(e, href) {
    if (!this.navEvent || e.defaultPrevented || e.button !== 0 || e.metaKey || e.ctrlKey || e.shiftKey || e.altKey) {
      return;
    }
    const [route, q] = href.split('?', 2);
    const params = {};
    if (q) {
      new URLSearchParams(q).forEach((v, k) => { params[k] = v; });
    }
    e.preventDefault();
    this.dispatchEvent(new MesopEvent(this.navEvent, { route, params }));
  }

  _job(id) {
    const j = this._jobs[id];
    if (!j) return nothing;
    const S = this._s;
    const name = (j.handle || '').replace(/^./, (c) => c.toUpperCase());
    const running = j.status !== 'done' && j.status !== 'failed';
    const isStory = j.kind === 'story';
    return html`
      <div class="job ${j.status}" aria-live="polite">
        <div class="job-head">
          <span class="job-name">${name}</span>
          <span class="job-state">${running ? (S.making || 'Making…') : j.status === 'failed' ? (S.failed || 'Failed') : (S.ready || 'Ready')}</span>
        </div>
        ${running ? html`<div class="shimmer ${j.kind}" aria-hidden="true"></div>` : nothing}
        ${j.status === 'done' ? this._media(j) : nothing}
        ${j.status === 'done' && isStory && !(j.params && j.params.has_film) ? html`<p class="job-note">${S.story_step || 'This step of your film is ready. Say "next step" to keep going, or open it in Story Studio.'}</p>` : nothing}
        ${j.status === 'failed' ? html`<p class="job-error">${j.error || ''}</p>` : nothing}
        ${j.status === 'done' || j.status === 'failed' ? html`<div class="job-actions">
          ${j.status === 'done' && j.display_url && !isStory ? html`<a class="act" href=${j.display_url} download target="_blank" rel="noopener">${svg(ICON.download, 18)}${S.download || 'Download'}</a>` : nothing}
          ${j.status === 'done' && j.kind === 'image' ? html`<button class="act" type="button" @click=${() => this._prefill(`${S.edit_prefix || 'Edit'} ${j.handle}: `)}>${svg(ICON.edit, 18)}${S.edit || 'Edit'}</button>` : nothing}
          ${j.status === 'done' && j.kind === 'image' ? html`<button class="act" type="button" @click=${() => this._animate(j)}>${svg(ICON.spark, 18)}${S.animate || 'Animate'}</button>` : nothing}
          ${j.status === 'done' ? (() => { const href = this._studio(j); return html`<a class="act" href=${href} @click=${(e) => this._openStudio(e, href)}>${svg(ICON.open, 18)}${isStory ? (S.open_film || 'Open in Story Studio') : (S.open || 'Open in Library')}</a>`; })() : nothing}
          ${j.status === 'failed' ? html`<button class="act" type="button" @click=${() => this._send(j.prompt)}>${svg(ICON.retry, 18)}${S.retry || 'Try again'}</button>` : nothing}
        </div>` : nothing}
      </div>`;
  }

  // ---------------------------------------------------------------- jobs panel

  _thumb(j) {
    const url = j.display_url || '';
    const mime = j.mime_type || '';
    if (j.status !== 'done' || !url) {
      return html`<div class="pj-ph ${j.kind} ${j.status === 'failed' ? '' : 'shim'}">${svg(ICON[j.kind] || ICON.spark, 22)}</div>`;
    }
    if (mime.startsWith('video/') || j.kind === 'video' || (j.kind === 'story' && j.params && j.params.has_film)) {
      return html`<video class="pj-img" src=${url} muted playsinline loop preload="metadata"
        @mouseenter=${(e) => e.target.play().catch(() => {})} @mouseleave=${(e) => e.target.pause()}></video>`;
    }
    if (mime.startsWith('audio/') || j.kind === 'music' || j.kind === 'voice') {
      return html`<audio class="pj-audio" src=${url} controls preload="metadata"></audio>`;
    }
    if (mime.startsWith('image/') || j.kind === 'image') {
      return html`<img class="pj-img" src=${url} alt=${j.prompt || j.handle} loading="lazy" draggable="false">`;
    }
    return html`<div class="pj-ph ${j.kind}">${svg(ICON[j.kind] || ICON.spark, 22)}</div>`;
  }

  _panelJob(j) {
    const S = this._s;
    const name = (j.handle || '').replace(/^./, (c) => c.toUpperCase());
    const running = j.status !== 'done' && j.status !== 'failed';
    const done = j.status === 'done';
    const isStory = j.kind === 'story';
    const canDrag = done && j.kind === 'image' && !!j.display_url;
    const state = running ? (S.making || 'Making…') : j.status === 'failed' ? (S.failed || 'Failed') : (S.ready || 'Ready');
    const href = done ? this._studio(j) : '';
    return html`
      <li class="pj ${j.status} pk-${j.kind}" draggable=${canDrag ? 'true' : 'false'}
        @dragstart=${canDrag ? (e) => { e.dataTransfer.setData('application/x-gm-job', j.id); e.dataTransfer.setData('text/uri-list', j.display_url); e.dataTransfer.effectAllowed = 'copy'; } : null}>
        <div class="pj-media">${this._thumb(j)}</div>
        <div class="pj-head"><b>${name}</b><span class="pj-state">${running ? html`<i class="dot" aria-hidden="true"></i>` : nothing}${state}</span></div>
        ${j.prompt ? html`<p class="pj-prompt" title=${j.prompt}>${j.prompt}</p>` : nothing}
        ${j.status === 'failed' && j.error ? html`<p class="pj-error">${j.error}</p>` : nothing}
        ${done || j.status === 'failed' ? html`<div class="pj-acts">
          ${done && j.kind === 'image' ? html`<button class="pa" type="button" @click=${() => this._animate(j)}>${svg(ICON.spark, 16)}${S.animate || 'Animate'}</button>
            <button class="pa" type="button" @click=${() => this._useRef(j)} title=${S.reference_tip || 'Use as a reference in your next message'}>${svg(ICON.plus, 16)}${S.reference || 'Reference'}</button>` : nothing}
          ${done && j.display_url && !isStory ? html`<a class="pa icon" href=${j.display_url} download target="_blank" rel="noopener" aria-label=${S.download || 'Download'} title=${S.download || 'Download'}>${svg(ICON.download, 18)}</a>` : nothing}
          ${done ? html`<a class="pa ${isStory ? '' : 'icon'}" href=${href} @click=${(e) => this._openStudio(e, href)}
              aria-label=${isStory ? (S.open_film || 'Open in Story Studio') : (S.open || 'Open in Library')}
              title=${isStory ? (S.open_film || 'Open in Story Studio') : (S.open || 'Open in Library')}>${svg(ICON.open, 18)}${isStory ? (S.open_short || 'Open') : nothing}</a>` : nothing}
          ${j.status === 'failed' ? html`<button class="pa" type="button" @click=${() => this._send(j.prompt)}>${svg(ICON.retry, 16)}${S.retry || 'Try again'}</button>` : nothing}
        </div>` : nothing}
      </li>`;
  }

  /** The closed panel's button: floating top-right, or in the dock on phones. */
  _jobsPill(where) {
    const all = Object.values(this._jobs);
    if (!all.length || this._panel) return nothing;
    const S = this._s;
    const running = all.filter((j) => j.status !== 'done' && j.status !== 'failed').length;
    const label = S.jobs || 'Jobs';
    const count = running ? `${running} ${S.jobs_running || 'running'}` : `${all.length}`;
    return html`<button class="jobs-pill ${where}" type="button" @click=${() => this._togglePanel(true)} aria-label=${`${label}: ${count}`}>
      ${running ? html`<i class="dot" aria-hidden="true"></i>` : svg(ICON.image, 18)}<span>${label}</span><span class="n">${running || all.length}</span></button>`;
  }

  _jobsPanel() {
    const S = this._s;
    const all = Object.values(this._jobs);
    if (!all.length) return nothing;
    const running = all.filter((j) => j.status !== 'done' && j.status !== 'failed').length;
    const label = S.jobs || 'Jobs';
    const count = running ? `${running} ${S.jobs_running || 'running'}` : `${all.length}`;
    if (!this._panel) return this._jobsPill('float');
    return html`
      <aside class="jobs" aria-label=${label}>
        <div class="jobs-head">
          <b>${label}</b><span class="jobs-count">${count}</span>
          <button class="icon sm" type="button" @click=${() => this._togglePanel(false)} aria-label=${S.close || 'Close'} title=${S.close || 'Close'}>${svg(ICON.close, 18)}</button>
        </div>
        <ul class="jobs-list">${[...all].reverse().map((j) => this._panelJob(j))}</ul>
      </aside>`;
  }

  _thread() {
    return html`<div class="thread" role="log" aria-label=${this._s.thread || 'Conversation'}>
      ${this._msgs.map((m) => m.role === 'user'
        ? html`<div class="msg user"><div class="user-col">
            ${(m.images || []).length ? html`<div class="sent">${m.images.map((u) => html`<img src=${u} alt="">`)}</div>` : nothing}
            <div class="bubble">${m.text}</div></div></div>`
        : html`<div class="msg bot"><span class="avatar" aria-hidden="true">${svg(ICON.spark, 18)}</span>
            <div class="bot-body"><div class="text">${m.text}</div>${m.meta ? html`<div class="meta">${m.meta}</div>` : nothing}${(m.jobs || []).map((id) => this._job(id))}</div></div>`)}
      ${this._busy ? html`<div class="msg bot"><span class="avatar" aria-hidden="true">${svg(ICON.spark, 18)}</span>
          <div class="typing" aria-label=${this._s.thinking || 'Thinking'}><i></i><i></i><i></i></div></div>` : nothing}
      <div class="end"></div>
    </div>`;
  }

  render() {
    const S = this._s;
    const chatting = this._msgs.length > 0;
    return html`
      <div class="wrap ${chatting ? 'chat' : 'empty'}">
        ${chatting ? this._thread() : html`
          <section class="hero">
            <h1 class="title">${S.title || "Google's creative AI, in one studio"}</h1>
          </section>`}
        <div class="dock">
          ${chatting ? html`<div class="dock-top">${this._jobsPill('inline')}<button class="ghost newchat" type="button" @click=${() => this._newChat(this._projectId)} title=${S.new_chat_tip || 'Start over with an empty chat'}>
              ${svg(ICON.newchat, 18)}<span>${S.new_chat || 'New chat'}</span></button></div>` : nothing}
          ${this._box()}
          ${this._kindChips(chatting || this._hasText)}
        </div>
      </div>
      ${this._jobsPanel()}`;
  }

  willUpdate() {
    // The host makes room for the open panel (wide screens only, in CSS).
    this.panelOpen = this._panel && Object.keys(this._jobs).length > 0;
  }

  static styles = css`
    :host { display: block; font-family: var(--gm-font, 'Google Sans', system-ui, sans-serif); color: var(--sys-on-surface, #15171c); }
    * { box-sizing: border-box; }
    .wrap { display: flex; flex-direction: column; align-items: center; width: 100%; margin: 0 auto; }
    /* Empty: everything centred on the screen (topbar 60px, frame padding). */
    .wrap.empty { min-height: var(--gm-home-fit, calc(100dvh - 84px)); justify-content: center; gap: clamp(28px, 5vh, 48px); padding-bottom: 8vh; }
    .wrap.chat { min-height: var(--gm-home-fit, calc(100dvh - 84px)); justify-content: flex-end; max-width: 860px; }

    .hero { display: flex; flex-direction: column; align-items: center; text-align: center; gap: clamp(8px, 1.6vh, 14px); }
    .title {
      margin: 0; max-width: 16em; font-size: clamp(2rem, 1rem + 2.2vw, 3.25rem); line-height: 1.08;
      font-weight: 600; letter-spacing: -0.035em; text-wrap: balance;
      background: var(--gm-home-title-grad, linear-gradient(100deg, var(--sys-on-surface) 0%, var(--sys-on-surface) 38%, #1a5fd8 72%, #7b3fe4 100%));
      -webkit-background-clip: text; background-clip: text; color: transparent;
    }

    /* The prompt box (same glass as the studios' composer). */
    .dock { width: 100%; max-width: 820px; display: flex; flex-direction: column; gap: 12px; align-items: center; }
    .wrap.empty .dock { gap: clamp(24px, 4vh, 36px); }
    .wrap.chat .dock { position: sticky; bottom: 0; padding: 10px 0 16px; }
    /* A solid box in the open rail's colour (--gm-panel), like Gemini's: it
       stands out from the page instead of blending in as glass. */
    .box {
      width: 100%; display: flex; flex-direction: column; gap: 8px; padding: 10px;
      border-radius: 32px; background: var(--gm-panel, #1d1f25); border: 1px solid transparent;
      box-shadow: 0 10px 34px rgba(0, 0, 0, 0.22);
      transition: border-color 160ms ease, box-shadow 160ms ease;
    }
    .box:focus-within { border-color: color-mix(in srgb, var(--sys-on-surface, #e8eaed) 14%, transparent); }
    .box .files { padding: 4px 8px 0; }
    /* One row: + | text | Enhance, Dictate, Live/Send. The buttons stay on
       the last line when the text grows. */
    .row { display: flex; align-items: flex-end; gap: 4px; }
    textarea {
      flex: 1 1 auto; min-width: 0; height: 44px; min-height: 44px; max-height: 220px; resize: none; border: 0; outline: 0;
      background: transparent; color: inherit; font: inherit; font-size: 18px; line-height: 24px; padding: 10px 8px;
    }
    textarea::placeholder { color: var(--sys-on-surface-variant, #6b7280); opacity: 0.9; }
    .tools { flex: none; display: flex; align-items: center; gap: 4px; }
    button { font: inherit; }
    .icon, .send {
      width: 44px; height: 44px; flex: none; display: inline-flex; align-items: center; justify-content: center;
      border: 0; border-radius: 50%; cursor: pointer; color: var(--sys-on-surface-variant, #4b515d); background: transparent;
    }
    .icon svg, .send svg, .act svg, .ghost svg { fill: currentColor; }
    .icon:hover { background: var(--gm-tonal-hover, rgba(127, 127, 127, 0.14)); }
    .icon.on { background: #d93025; color: #fff; }
    .send { color: var(--sys-on-primary, #fff); background: var(--sys-primary, #1a73e8); }
    .send:hover:not(:disabled) { filter: brightness(1.08); }
    .send:disabled { cursor: default; }
    .send.off { background: var(--gm-tonal, rgba(127, 127, 127, 0.14)); color: var(--sys-on-surface-variant, #6b7280); }
    .icon.working svg { animation: pulse 900ms ease-in-out infinite alternate; }
    @keyframes pulse { from { opacity: 0.35; } to { opacity: 1; } }
    .ghost {
      display: inline-flex; align-items: center; gap: 6px; height: 40px; padding: 0 14px 0 10px; border: 0; border-radius: 999px;
      background: var(--gm-tonal, rgba(127, 127, 127, 0.1)); color: var(--sys-on-surface-variant, #4b515d); cursor: pointer; font-size: 14px; font-weight: 500;
    }
    .newchat { align-self: flex-end; }
    .ghost:hover { background: var(--gm-tonal-hover, rgba(127, 127, 127, 0.16)); }
    .icon:disabled { opacity: 0.4; cursor: default; }
    /* Attached pictures: small previews above the text. */
    .files { display: flex; gap: 8px; padding: 4px 0 2px; }
    .file { position: relative; width: 64px; height: 64px; border-radius: 14px; overflow: hidden; flex: none;
      background: var(--gm-tonal, rgba(127, 127, 127, 0.1)); }
    .file img { width: 100%; height: 100%; object-fit: cover; display: block; }
    .file.bad img { opacity: 0.35; }
    .file-spin { position: absolute; inset: 0; margin: auto; width: 22px; height: 22px; border-radius: 50%;
      border: 2.5px solid rgba(255, 255, 255, 0.45); border-top-color: #fff; animation: rot 800ms linear infinite; }
    .file-x { position: absolute; top: 4px; inset-inline-end: 4px; width: 22px; height: 22px; border: 0; border-radius: 50%; padding: 0;
      display: grid; place-items: center; cursor: pointer; background: rgba(0, 0, 0, 0.6); color: #fff; }
    .file-x svg { fill: currentColor; }
    .user-col { display: flex; flex-direction: column; align-items: flex-end; gap: 6px; max-width: 78%; }
    .user-col .bubble { max-width: 100%; }
    .sent { display: flex; gap: 6px; flex-wrap: wrap; justify-content: flex-end; }
    .sent img { width: 120px; height: 120px; object-fit: cover; border-radius: 16px; display: block; }
    .spin { width: 20px; height: 20px; border-radius: 50%; border: 2.5px solid rgba(255, 255, 255, 0.4); border-top-color: #fff; animation: rot 800ms linear infinite; }
    @keyframes rot { to { transform: rotate(360deg); } }
    button:focus-visible, a:focus-visible { outline: 2px solid var(--sys-primary, #1a5fd8); outline-offset: 2px; }
    textarea:focus, textarea:focus-visible { outline: none; }

    /* Type tiles under the box. Hover plays a sample inside the tile; a
       click fills a sample prompt. With text or a conversation they shrink
       into a row of buttons. */
    .kinds { width: 100%; display: grid; grid-template-columns: repeat(5, minmax(0, 1fr)); gap: 12px; }
    .kind {
      position: relative; overflow: hidden; isolation: isolate; height: 118px; padding: 14px; border: 0; border-radius: 22px;
      display: flex; align-items: flex-end; text-align: start; cursor: pointer; font-size: 14px;
      background: var(--gm-tonal, rgba(127, 127, 127, 0.1)); color: var(--sys-on-surface, #15171c);
      transition: height 280ms cubic-bezier(0.2, 0.8, 0.2, 1), border-radius 280ms ease, background 160ms ease, color 160ms ease, transform 160ms ease;
    }
    .kind:hover { background: var(--gm-tonal-hover, rgba(127, 127, 127, 0.16)); }
    .kbody { position: relative; z-index: 1; display: flex; flex-direction: column; gap: 10px; min-width: 0; }
    .kbody svg { flex: none; fill: currentColor; opacity: 0.85; }
    .ktext { display: flex; flex-direction: column; gap: 2px; min-width: 0; }
    .ktext b { font-size: 15px; font-weight: 600; }
    .ktext small { font-size: 12.5px; color: var(--sys-on-surface-variant, #6b7280); white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }
    /* The sample: hidden at rest, it fades in behind the label on hover. */
    .kmedia { position: absolute; inset: 0; z-index: 0; opacity: 0; transform: scale(1.06); background-size: cover; background-position: center;
      transition: opacity 260ms ease, transform 700ms ease; }
    .kmedia::after { content: ''; position: absolute; inset: 0; background: linear-gradient(180deg, rgba(0, 0, 0, 0.05) 20%, rgba(0, 0, 0, 0.7)); }
    .kinds:not(.compact) .kind:hover .kmedia, .kinds:not(.compact) .kind:focus-visible .kmedia, .kinds:not(.compact) .kind[aria-pressed='true'] .kmedia { opacity: 1; transform: scale(1); }
    .kinds:not(.compact) .kind:hover, .kinds:not(.compact) .kind:focus-visible, .kinds:not(.compact) .kind[aria-pressed='true'] { color: #fff; }
    .kinds:not(.compact) .kind:hover small, .kinds:not(.compact) .kind:focus-visible small, .kinds:not(.compact) .kind[aria-pressed='true'] small { color: rgba(255, 255, 255, 0.82); }
    .kinds:not(.compact) .kind[aria-pressed='true'] { box-shadow: 0 0 0 2px var(--sys-on-surface, #e8eaed); }
    .k-image .kmedia { background-image: url('/ui/posters/gemini-image__page-cover.webp'); background-position: 90% 10%; background-size: 260%; }
    .k-video .kmedia { background-image: url('/ui/posters/gemini-omni__page-cover__hero.webp'); }
    .k-video:hover .kmedia, .k-video[aria-pressed='true'] .kmedia { background-image: url('/ui/home/word-video.webp'); }
    .k-film .kmedia { background-image: url('/ui/posters/veo__cover_s0RKXWX.webp'); }
    .k-film:hover .kmedia, .k-film[aria-pressed='true'] .kmedia { background-image: url('/ui/home/word-film.webp'); }
    .k-music .kmedia { background-image: url('/ui/posters/lyria_header.webp'); }
    .k-voice .kmedia { background-image: url('/ui/posters/capability__native-audio_16-9.webp'); }
    /* Music and Voice: an equaliser that moves like sound over the picture. */
    .eq { position: absolute; z-index: 1; left: 14px; right: 14px; top: 14px; height: 40%; display: flex; align-items: center; justify-content: space-between; }
    .eq i { width: 4px; height: calc(var(--h) * 100%); border-radius: 4px; background: rgba(255, 255, 255, 0.92); transform: scaleY(0.4); transform-origin: 50% 50%; }
    .kind:hover .eq i, .kind:focus-visible .eq i, .kind[aria-pressed='true'] .eq i { animation: sound 640ms ease-in-out var(--d) infinite alternate; }
    .k-voice .eq i { animation-duration: 380ms !important; }
    @keyframes sound { from { transform: scaleY(0.25); } to { transform: scaleY(1); } }

    /* Compact: one row of buttons under the box. */
    .kinds.compact { display: flex; flex-wrap: wrap; justify-content: center; gap: 8px; }
    .kinds.compact .kind { height: 40px; padding: 0 16px 0 12px; border-radius: 999px; align-items: center; font-weight: 500; }
    .kinds.compact .kbody { flex-direction: row; align-items: center; gap: 8px; }
    .kinds.compact .kbody svg { width: 18px; height: 18px; }
    .kinds.compact .ktext b { font-size: 14px; font-weight: 500; }
    .kinds.compact small, .kinds.compact .kmedia { display: none; }
    .kinds.compact .kind[aria-pressed='true'] { background: var(--sys-on-surface, #e8eaed); color: var(--sys-surface, #15171c); }

    /* Conversation */
    .thread { width: 100%; display: flex; flex-direction: column; gap: 18px; padding: 12px 0 8px; }
    .msg { display: flex; gap: 12px; align-items: flex-start; }
    .msg.user { justify-content: flex-end; }
    .bubble {
      max-width: 78%; padding: 12px 16px; border-radius: 20px 20px 6px 20px; font-size: 16px; line-height: 1.5; white-space: pre-wrap;
      background: var(--sys-secondary-container, #dfe6f7); color: var(--sys-on-secondary-container, #1b2433);
    }
    .avatar {
      flex: none; width: 32px; height: 32px; border-radius: 50%; display: flex; align-items: center; justify-content: center;
      color: #fff; background: var(--gm-accent-gradient, linear-gradient(135deg, #1a73e8, #6a4cf0));
    }
    .avatar svg { fill: currentColor; }
    .bot-body { display: flex; flex-direction: column; gap: 12px; min-width: 0; flex: 1 1 auto; padding-top: 4px; }
    .text { font-size: 16px; line-height: 1.6; white-space: pre-wrap; }
    .typing { display: flex; gap: 5px; padding: 12px 4px; }
    .typing i { width: 7px; height: 7px; border-radius: 50%; background: var(--sys-on-surface-variant, #6b7280); animation: blink 1.2s infinite both; }
    .typing i:nth-child(2) { animation-delay: 0.15s; } .typing i:nth-child(3) { animation-delay: 0.3s; }
    @keyframes blink { 0%, 80%, 100% { opacity: 0.25; } 40% { opacity: 1; } }

    .job {
      display: flex; flex-direction: column; gap: 10px; padding: 12px; border-radius: 18px; max-width: 560px;
      background: var(--gm-glass-fill, rgba(30, 33, 48, 0.5)); border: 1px solid var(--gm-glass-border, rgba(255, 255, 255, 0.1));
    }
    .job-head { display: flex; align-items: center; justify-content: space-between; gap: 8px; padding: 0 4px; font-size: 14px; }
    .job-name { font-weight: 600; }
    .job-state { color: var(--sys-on-surface-variant, #6b7280); }
    .job.failed .job-state { color: #d93025; }
    .shimmer {
      width: 100%; aspect-ratio: 16 / 9; border-radius: 12px;
      background: linear-gradient(100deg, rgba(127, 127, 127, 0.10) 20%, rgba(127, 127, 127, 0.22) 40%, rgba(127, 127, 127, 0.10) 60%);
      background-size: 250% 100%; animation: shim 1.4s ease-in-out infinite;
    }
    .shimmer.image { aspect-ratio: 1 / 1; max-width: 360px; }
    .shimmer.music, .shimmer.voice { aspect-ratio: auto; height: 54px; }
    .shimmer.story { aspect-ratio: auto; height: 72px; }
    @keyframes shim { from { background-position: 100% 0; } to { background-position: -150% 0; } }
    @media (prefers-reduced-motion: reduce) {
      .shimmer, .typing i, .spin, .icon.working svg, .eq i { animation: none !important; }
      .kind, .kmedia { transition: none; }
      .k-video:hover .kmedia, .k-video[aria-pressed='true'] .kmedia { background-image: url('/ui/posters/gemini-omni__page-cover__hero.webp'); }
      .k-film:hover .kmedia, .k-film[aria-pressed='true'] .kmedia { background-image: url('/ui/posters/veo__cover_s0RKXWX.webp'); }
    }
    /* The picture at its own shape: no letterbox bars around it. */
    .media { display: block; width: auto; height: auto; max-width: 100%; max-height: 480px; border-radius: 12px; }
    .job > a { align-self: flex-start; line-height: 0; max-width: 100%; }
    .job > .media { align-self: flex-start; }
    .job:has(> a > img.media, > video.media) { width: fit-content; min-width: 300px; }
    .audio { width: 100%; }
    .job-note, .job-error { margin: 0 4px; font-size: 14px; line-height: 1.5; color: var(--sys-on-surface-variant, #6b7280); }
    .job-error { color: #d93025; }
    .job-actions { display: flex; flex-wrap: wrap; gap: 8px; }
    .act {
      display: inline-flex; align-items: center; gap: 6px; height: 36px; padding: 0 14px 0 10px; border: 0; border-radius: 999px;
      background: var(--gm-tonal, rgba(127, 127, 127, 0.1)); color: var(--sys-on-surface, #15171c); text-decoration: none; font-size: 13.5px; font-weight: 500; cursor: pointer;
    }
    .act:hover { background: var(--gm-tonal-hover, rgba(127, 127, 127, 0.16)); }
    /* Type controls: a row of settings that slides open under the text. */
    .ctl-wrap { display: grid; grid-template-rows: 0fr; opacity: 0; transition: grid-template-rows 300ms cubic-bezier(0.2, 0.8, 0.2, 1), opacity 220ms ease; }
    .ctl-wrap.open { grid-template-rows: 1fr; opacity: 1; }
    .ctl-in { overflow: hidden; min-height: 0; }
    .controls { display: flex; flex-wrap: wrap; gap: 6px; padding: 2px 6px 4px 52px; }
    .ctl { position: relative; display: inline-flex; align-items: center; gap: 6px; height: 34px; padding: 0 30px 0 12px; border-radius: 999px;
      background: var(--gm-tonal, rgba(127, 127, 127, 0.12)); font-size: 13px; cursor: pointer; max-width: 100%; }
    .ctl:hover { background: var(--gm-tonal-hover, rgba(127, 127, 127, 0.18)); }
    .ctl:focus-within { outline: 2px solid var(--sys-primary, #1a5fd8); outline-offset: 1px; }
    .ctl-l { color: var(--sys-on-surface-variant, #6b7280); white-space: nowrap; }
    .ctl select { appearance: none; -webkit-appearance: none; border: 0; outline: 0; background: transparent; color: var(--sys-on-surface, #15171c);
      font: inherit; font-weight: 500; cursor: pointer; padding: 0; max-width: 180px; text-overflow: ellipsis; }
    .ctl select option { color: #15171c; background: #fff; }
    .ctl .caret { position: absolute; inset-inline-end: 9px; fill: currentColor; opacity: 0.6; pointer-events: none; }
    :host-context([dir='rtl']) .ctl { padding: 0 12px 0 30px; }
    .note { margin: 0 12px 4px 52px; font-size: 13px; color: var(--sys-on-surface-variant, #6b7280); }
    .meta { font-size: 13px; color: var(--sys-on-surface-variant, #6b7280); margin-top: -6px; }
    @media (max-width: 600px) {
      .controls { flex-wrap: nowrap; overflow-x: auto; scrollbar-width: none; padding-inline-start: 4px; }
      .controls::-webkit-scrollbar { display: none; }
      .ctl { flex: none; }
      .note { margin-inline-start: 8px; }
    }
    /* The buttons above the box float over the thread: give them the box's fill. */
    .dock-top .ghost, .dock-top .jobs-pill { background: var(--gm-panel, #1d1f25); box-shadow: 0 4px 14px rgba(0, 0, 0, 0.14); }
    .dock-top .ghost:hover, .dock-top .jobs-pill:hover { filter: brightness(1.06); }
    @media (prefers-reduced-motion: reduce) { .ctl-wrap { transition: none; } }
    /* In the thread, results stay small; the jobs panel holds the rest. */
    .job .media { max-height: 360px; }

    /* Dropping a picture or a job card on the box. */
    .box.drop { border-color: var(--sys-primary, #1a73e8); box-shadow: 0 0 0 3px color-mix(in srgb, var(--sys-primary, #1a73e8) 30%, transparent); }

    /* Jobs panel: a card floating on the right; the page makes room for it
       on wide screens, it overlays on mid widths, and is a bottom sheet on phones. */
    :host { --gm-jobs-w: 340px; transition: padding 280ms cubic-bezier(0.2, 0.8, 0.2, 1); }
    @media (min-width: 1100px) { :host([panel]) { padding-inline-end: calc(var(--gm-jobs-w) + 16px); } }
    .jobs {
      position: fixed; z-index: 30; top: 12px; bottom: 12px; inset-inline-end: 12px; width: var(--gm-jobs-w);
      display: flex; flex-direction: column; border-radius: 24px; overflow: hidden;
      background: var(--gm-panel, #1d1f25); box-shadow: 0 18px 50px rgba(0, 0, 0, 0.32);
      animation: jobs-in 320ms cubic-bezier(0.2, 0.8, 0.2, 1);
    }
    @keyframes jobs-in { from { transform: translateX(24px); opacity: 0; } to { transform: none; opacity: 1; } }
    :host-context([dir='rtl']) .jobs { animation-name: jobs-in-rtl; }
    @keyframes jobs-in-rtl { from { transform: translateX(-24px); opacity: 0; } to { transform: none; opacity: 1; } }
    .jobs-head { display: flex; align-items: center; gap: 8px; padding: 12px 10px 8px 18px; font-size: 15px; }
    .jobs-count { color: var(--sys-on-surface-variant, #6b7280); font-size: 13.5px; flex: 1; }
    .icon.sm { width: 36px; height: 36px; }
    .jobs-list { list-style: none; margin: 0; padding: 4px 10px 12px; overflow-y: auto; display: flex; flex-direction: column; gap: 10px; flex: 1; scrollbar-width: thin; }
    .pj { display: flex; flex-direction: column; gap: 8px; padding: 8px; border-radius: 18px; background: var(--gm-tonal, rgba(127, 127, 127, 0.08)); }
    .pj[draggable='true'] { cursor: grab; }
    .pj-media { border-radius: 12px; overflow: hidden; line-height: 0; }
    .pj-img { width: 100%; max-height: 220px; object-fit: cover; display: block; background: rgba(0, 0, 0, 0.2); }

    .pj-audio { width: 100%; height: 40px; }
    .pj-ph { height: 96px; display: grid; place-items: center; color: var(--sys-on-surface-variant, #6b7280); background: rgba(127, 127, 127, 0.1); }
    .pj-ph svg { fill: currentColor; opacity: 0.7; }
    .pj-ph.image, .pj-ph.video { height: 150px; }
    .pj-ph.shim { background: linear-gradient(100deg, rgba(127, 127, 127, 0.10) 20%, rgba(127, 127, 127, 0.22) 40%, rgba(127, 127, 127, 0.10) 60%); background-size: 250% 100%; animation: shim 1.4s ease-in-out infinite; }
    .pj-head { display: flex; align-items: center; justify-content: space-between; gap: 8px; padding: 0 4px; font-size: 14px; }
    .pj-state { display: inline-flex; align-items: center; gap: 6px; color: var(--sys-on-surface-variant, #6b7280); font-size: 13px; }
    .pj.failed .pj-state, .pj-error { color: #d93025; }
    .pj-prompt, .pj-error { margin: 0; padding: 0 4px; font-size: 13px; line-height: 1.4; color: var(--sys-on-surface-variant, #6b7280);
      display: -webkit-box; -webkit-line-clamp: 2; -webkit-box-orient: vertical; overflow: hidden; }
    .pj-acts { display: flex; flex-wrap: wrap; gap: 6px; }
    .pa { display: inline-flex; align-items: center; justify-content: center; gap: 5px; height: 34px; padding: 0 12px 0 9px; border: 0; border-radius: 999px;
      background: var(--gm-tonal, rgba(127, 127, 127, 0.12)); color: var(--sys-on-surface, #15171c); text-decoration: none; font-size: 13px; font-weight: 500; cursor: pointer; }
    .pa.icon { width: 34px; padding: 0; }
    .pa svg { fill: currentColor; flex: none; }
    .pa:hover { background: var(--gm-tonal-hover, rgba(127, 127, 127, 0.18)); }
    .dot { width: 8px; height: 8px; border-radius: 50%; background: var(--sys-primary, #1a73e8); animation: pulse 900ms ease-in-out infinite alternate; flex: none; }
    .jobs-pill {
      position: fixed; z-index: 30; top: 16px; inset-inline-end: 16px; display: inline-flex; align-items: center; gap: 8px; height: 40px; padding: 0 8px 0 14px;
      border: 0; border-radius: 999px; cursor: pointer; font-size: 14px; font-weight: 500;
      background: var(--gm-panel, #1d1f25); color: var(--sys-on-surface, #15171c); box-shadow: 0 8px 24px rgba(0, 0, 0, 0.25);
    }
    .jobs-pill svg { fill: currentColor; }
    .jobs-pill .n { min-width: 24px; height: 24px; padding: 0 7px; border-radius: 999px; display: grid; place-items: center; font-size: 12.5px;
      background: var(--gm-tonal, rgba(127, 127, 127, 0.16)); }
    .jobs-pill:hover { filter: brightness(1.08); }
    .jobs-pill.inline { display: none; position: static; box-shadow: none; background: var(--gm-tonal, rgba(127, 127, 127, 0.1)); }
    .dock-top { align-self: stretch; display: flex; justify-content: flex-end; gap: 8px; }
    .job .shimmer { width: 420px; max-width: 100%; }
    .job .shimmer.image { width: 300px; }
    .job:has(> .shimmer) { width: fit-content; max-width: 100%; }
    @media (max-width: 760px) {
      .jobs { top: auto; bottom: 0; inset-inline: 0; width: auto; max-height: 72dvh; border-radius: 24px 24px 0 0; animation-name: sheet-in; }
      @keyframes sheet-in { from { transform: translateY(40px); opacity: 0; } to { transform: none; opacity: 1; } }
      .jobs-pill.float { display: none; }
      .jobs-pill.inline { display: inline-flex; margin-inline-end: auto; }
    }
    @media (prefers-reduced-motion: reduce) {
      .jobs, :host { animation: none !important; transition: none !important; }
      .dot, .pj-ph.shim { animation: none !important; }
    }

    @media (max-width: 600px) {
      .wrap.empty { gap: 18px; padding-bottom: 0; }
      .box { padding: 6px; border-radius: 26px; }
      textarea { font-size: 16px; padding: 10px 4px; }
      .kinds:not(.compact) { display: flex; overflow-x: auto; scrollbar-width: none; gap: 10px; padding-bottom: 2px; }
      .kinds:not(.compact) .kind { flex: 0 0 132px; height: 104px; }
      .kinds.compact { gap: 6px; }
      .kinds.compact .kind { padding: 0 12px 0 10px; }
      .bubble { max-width: 88%; }
    }
  `;
}

if (!customElements.get('gm-home-chat')) customElements.define('gm-home-chat', GmHomeChat);
