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
 * Empty: the headline, a line whose media words show what they make
 * (hover plays them; click opens that studio), the prompt box and a few
 * examples, centred on the screen. After the first message the hero steps
 * aside and the conversation fills the page with the box at the bottom.
 *
 * Messages go to POST /api/chat (services/studio_chat.py), which answers in
 * text and starts jobs; GET /api/chat/jobs is polled until they finish, and
 * each job's result (image, video, audio, film step) shows in the thread.
 * The thread is kept in sessionStorage so it survives moving between pages.
 *
 * Box: Enter sends, Shift+Enter adds a line, Up/Down recall past prompts,
 * the mic dictates (browser speech-to-text), and "Talk to the studio" starts
 * the Live voice agent (<live-call-button>, components/live_agent).
 */
import { LitElement, css, html, nothing } from 'https://cdn.jsdelivr.net/npm/lit@3.2.1/+esm';

const STORE = 'gm-home-chat';
const HISTORY = 'gm-prompts:home';
const POLL_MS = 2000;
const Recognition = window.SpeechRecognition || window.webkitSpeechRecognition;
const reduceMotion = () => window.matchMedia && window.matchMedia('(prefers-reduced-motion: reduce)').matches;

const ICON = {
  send: 'M4 12l1.4 1.4L11 7.8V20h2V7.8l5.6 5.6L20 12l-8-8z',
  mic: 'M12 14a3 3 0 0 0 3-3V5a3 3 0 0 0-6 0v6a3 3 0 0 0 3 3zm5-3a5 5 0 0 1-10 0H5a7 7 0 0 0 6 6.92V21h2v-3.08A7 7 0 0 0 19 11z',
  stop: 'M7 7h10v10H7z',
  plus: 'M19 13h-6v6h-2v-6H5v-2h6V5h2v6h6z',
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
const svg = (d, size = 20) => html`<svg viewBox="0 0 24 24" width=${size} height=${size} aria-hidden="true"><path d=${d}></path></svg>`;

function load(key, fallback) {
  try { return JSON.parse(sessionStorage.getItem(key) || '') ?? fallback; } catch (_) { return fallback; }
}
function save(key, value) {
  try { sessionStorage.setItem(key, JSON.stringify(value)); } catch (_) { /* ignore */ }
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
    ledeJson: { type: String },
    examplesJson: { type: String },
    talkJson: { type: String },
    live: { type: Boolean, reflect: true },
    _msgs: { state: true },
    _jobs: { state: true },
    _busy: { state: true },
    _listening: { state: true },
  };

  constructor() {
    super();
    this.stringsJson = '{}';
    this.ledeJson = '[]';
    this.examplesJson = '[]';
    this.talkJson = '{}';
    this.live = false;
    this._msgs = load(STORE, { msgs: [] }).msgs || [];
    this._jobs = load(STORE, { jobs: {} }).jobs || {};
    this._busy = false;
    this._listening = false;
    this._hist = -1;
    this._draft = '';
    this._timer = null;
    this._rec = null;
  }

  get _s() {
    try { return JSON.parse(this.stringsJson || '{}'); } catch (_) { return {}; }
  }

  connectedCallback() {
    super.connectedCallback();
    if (this._pending().length) this._poll();
    // Fetch the hover clips once the page is idle, so the first hover plays.
    const warm = () => ['/ui/home/word-video.webp', '/ui/home/word-film.webp'].forEach((src) => { const i = new Image(); i.src = src; });
    if (!reduceMotion()) (window.requestIdleCallback || setTimeout)(warm, 1500);
    setTimeout(() => window.gmLive && window.gmLive.refreshLauncher && window.gmLive.refreshLauncher(), 60);
  }

  disconnectedCallback() {
    super.disconnectedCallback();
    clearTimeout(this._timer);
    if (this._rec) try { this._rec.stop(); } catch (_) { /* ignore */ }
    setTimeout(() => window.gmLive && window.gmLive.refreshLauncher && window.gmLive.refreshLauncher(), 60);
  }

  updated(changed) {
    if (changed.has('_msgs') || changed.has('_jobs')) {
      save(STORE, { msgs: this._msgs, jobs: this._jobs });
      // Keep the newest message in view: scroll the page's scroller to the end.
      const scroller = this.closest('.gm-page');
      if (scroller && this._msgs.length && changed.has('_msgs')) scroller.scrollTo({ top: scroller.scrollHeight, behavior: reduceMotion() ? 'auto' : 'smooth' });
    }
  }

  get _ta() { return this.renderRoot.querySelector('textarea'); }

  // ---------------------------------------------------------------- sending

  async _send(text) {
    const message = (text ?? this._ta?.value ?? '').trim();
    if (!message || this._busy) return;
    remember(message);
    this._hist = -1;
    if (this._ta) { this._ta.value = ''; this._fit(); }
    this._msgs = [...this._msgs, { role: 'user', text: message }];
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
    if (jobs.length) this._poll();
    this.updateComplete.then(() => this._ta && this._ta.focus());
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

  async _newChat() {
    clearTimeout(this._timer);
    this._msgs = [];
    this._jobs = {};
    try {
      await fetch('/api/chat/reset', { method: 'POST', credentials: 'same-origin', headers: { 'Content-Type': 'application/json' } });
    } catch (_) { /* local reset is enough */ }
    this.updateComplete.then(() => this._ta && this._ta.focus());
  }

  _prefill(text) {
    const ta = this._ta;
    if (!ta) return;
    ta.value = text;
    this._fit();
    ta.focus();
    ta.setSelectionRange(text.length, text.length);
  }

  // ---------------------------------------------------------------- keys

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

  _word(seg) {
    const cls = `w w-${seg.kind}`;
    return html`<a class=${cls} href=${seg.href} title=${seg.tip || ''} aria-label=${seg.tip ? `${seg.text}: ${seg.tip}` : seg.text}><span>${seg.text}</span></a>`;
  }

  _lede() {
    let segs = [];
    try { segs = JSON.parse(this.ledeJson || '[]'); } catch (_) { segs = []; }
    return html`<p class="lede">${segs.map((s) => (s.kind ? this._word(s) : s.text))}</p>`;
  }

  _box() {
    const S = this._s;
    let talk = '{}';
    try { talk = this.talkJson || '{}'; } catch (_) { talk = '{}'; }
    const chatting = this._msgs.length > 0;
    return html`
      <div class="box ${this._busy ? 'busy' : ''}">
        <textarea rows="1" .placeholder=${S.placeholder || 'Describe what you want to make'}
          aria-label=${S.placeholder || 'Describe what you want to make'}
          @keydown=${this._onKey} @input=${this._fit}></textarea>
        <div class="bar">
          ${chatting ? html`<button class="ghost" type="button" @click=${this._newChat} title=${S.new_chat_tip || 'Start over with an empty chat'}>
              ${svg(ICON.plus, 18)}<span>${S.new_chat || 'New chat'}</span></button>` : nothing}
          <span class="grow"></span>
          ${this.live ? html`<live-call-button pill .stringsJson=${talk}></live-call-button>` : nothing}
          ${Recognition ? html`<button class="icon ${this._listening ? 'on' : ''}" type="button" @click=${this._toggleMic}
              aria-pressed=${this._listening ? 'true' : 'false'}
              aria-label=${this._listening ? (S.dictate_stop || 'Stop dictation') : (S.dictate || 'Dictate')}
              title=${this._listening ? (S.dictate_stop || 'Stop dictation') : (S.dictate || 'Dictate: type with your voice')}>
              ${svg(this._listening ? ICON.stop : ICON.mic, 22)}</button>` : nothing}
          <button class="send" type="button" @click=${() => this._send()} ?disabled=${this._busy}
            aria-label=${S.send || 'Send'} title=${S.send || 'Send'}>
            ${this._busy ? html`<span class="spin" aria-hidden="true"></span>` : svg(ICON.send, 22)}</button>
        </div>
      </div>`;
  }

  _examples() {
    let ex = [];
    try { ex = JSON.parse(this.examplesJson || '[]'); } catch (_) { ex = []; }
    if (!ex.length) return nothing;
    return html`<ul class="try" aria-label=${this._s.try || 'Try'}>
      ${ex.map((e) => {
        const text = typeof e === 'string' ? e : e.text;
        const kind = (typeof e === 'string' ? '' : e.kind) || 'spark';
        return html`<li><button type="button" class="starter" @click=${() => this._send(text)}>
          ${svg(ICON[kind] || ICON.spark, 20)}<span>${text}</span></button></li>`;
      })}</ul>`;
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
          ${j.status === 'done' && j.kind === 'image' ? html`<button class="act" type="button" @click=${() => this._prefill(`${S.animate_prefix || 'Make a video from'} ${j.handle}: `)}>${svg(ICON.spark, 18)}${S.animate || 'Animate'}</button>` : nothing}
          ${j.status === 'done' ? html`<a class="act" href=${this._studio(j)}>${svg(ICON.open, 18)}${isStory ? (S.open_film || 'Open in Story Studio') : (S.open || 'Open in Library')}</a>` : nothing}
          ${j.status === 'failed' ? html`<button class="act" type="button" @click=${() => this._send(j.prompt)}>${svg(ICON.retry, 18)}${S.retry || 'Try again'}</button>` : nothing}
        </div>` : nothing}
      </div>`;
  }

  _thread() {
    return html`<div class="thread" role="log" aria-label=${this._s.thread || 'Conversation'}>
      ${this._msgs.map((m) => m.role === 'user'
        ? html`<div class="msg user"><div class="bubble">${m.text}</div></div>`
        : html`<div class="msg bot"><span class="avatar" aria-hidden="true">${svg(ICON.spark, 18)}</span>
            <div class="bot-body"><div class="text">${m.text}</div>${(m.jobs || []).map((id) => this._job(id))}</div></div>`)}
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
            ${this._lede()}
          </section>`}
        <div class="dock">
          ${this._box()}
          ${chatting ? nothing : this._examples()}
        </div>
      </div>`;
  }

  static styles = css`
    :host { display: block; font-family: var(--gm-font, 'Google Sans', system-ui, sans-serif); color: var(--sys-on-surface, #15171c); }
    * { box-sizing: border-box; }
    .wrap { display: flex; flex-direction: column; align-items: center; width: 100%; margin: 0 auto; }
    /* Empty: everything centred on the screen (topbar 60px, frame padding). */
    .wrap.empty { min-height: var(--gm-home-fit, calc(100dvh - 84px)); justify-content: center; gap: clamp(18px, 3.2vh, 32px); padding-bottom: 4vh; }
    .wrap.chat { min-height: var(--gm-home-fit, calc(100dvh - 84px)); justify-content: flex-end; max-width: 860px; }

    .hero { display: flex; flex-direction: column; align-items: center; text-align: center; gap: clamp(8px, 1.6vh, 14px); }
    .title {
      margin: 0; max-width: 16em; font-size: clamp(2rem, 1rem + 2.2vw, 3.25rem); line-height: 1.08;
      font-weight: 600; letter-spacing: -0.035em; text-wrap: balance;
      background: var(--gm-home-title-grad, linear-gradient(100deg, var(--sys-on-surface) 0%, var(--sys-on-surface) 38%, #1a5fd8 72%, #7b3fe4 100%));
      -webkit-background-clip: text; background-clip: text; color: transparent;
    }
    .lede {
      margin: 0; max-width: 36em; font-size: clamp(16px, 0.85rem + 0.35vw, 19px); line-height: 1.5; font-weight: 400;
      color: var(--sys-on-surface-variant, #4b515d); text-wrap: balance;
    }

    /* Media words: the word is a window onto what it makes. */
    .w {
      display: inline-block; font-weight: 700; letter-spacing: 0; text-decoration: none;
      background-size: cover; background-position: center; -webkit-background-clip: text; background-clip: text;
      color: transparent; padding: 0 0.04em; cursor: pointer; transition: transform 160ms ease, filter 160ms ease;
      -webkit-text-stroke: 0.4px rgba(255, 255, 255, 0.08);
    }
    .w:hover, .w:focus-visible { transform: translateY(-1px) scale(1.06); filter: saturate(1.25) brightness(1.08); }
    .w:focus-visible { outline: 2px solid var(--sys-primary, #1a5fd8); outline-offset: 3px; border-radius: 6px; }
    /* Images: the red roses corner of the Nano Banana cover, readable on light and dark. */
    .w-image {
      background-image: linear-gradient(rgba(255, 170, 150, 0.35), rgba(255, 120, 160, 0.35)), url('/ui/posters/gemini-image__page-cover.webp');
      background-size: 100% 100%, 900%; background-position: 0 0, 96% 4%; filter: saturate(1.3) brightness(1.25);
    }
    .w-image:hover, .w-image:focus-visible { background-position: 0 0, 80% 30%; transition: transform 160ms ease, filter 160ms ease, background-position 1.4s ease; }
    .w-video, .w-film { background-image: url('/ui/posters/gemini-omni__page-cover__hero.webp'); background-size: 220%; }
    .w-video:hover, .w-video:focus-visible { background-image: url('/ui/home/word-video.webp'); }
    .w-film:hover, .w-film:focus-visible { background-image: url('/ui/home/word-film.webp'); }
    .w-voice {
      background-image: repeating-linear-gradient(90deg, #5bd2f0 0 3px, #4f7cf7 3px 6px, #8f6cf6 6px 9px);
      background-size: 18px 100%;
    }
    .w-voice:hover, .w-voice:focus-visible { animation: wave 900ms linear infinite; }
    .w-music { background-image: linear-gradient(90deg, #f472b6, #a855f7, #60a5fa, #f472b6); background-size: 300% 100%; }
    .w-music:hover, .w-music:focus-visible { animation: hue 1.6s linear infinite; }
    @keyframes wave { 0% { background-size: 18px 100%; background-position: 0 0; } 50% { background-size: 12px 100%; } 100% { background-size: 18px 100%; background-position: 36px 0; } }
    @keyframes hue { to { background-position: 300% 0; } }
    @media (prefers-reduced-motion: reduce) {
      .w-voice:hover, .w-music:hover { animation: none; }
      .w-video:hover, .w-film:hover { background-image: url('/ui/posters/gemini-omni__page-cover__hero.webp'); }
    }

    /* The prompt box (same glass as the studios' composer). */
    .dock { width: 100%; max-width: 860px; display: flex; flex-direction: column; gap: 14px; align-items: center; }
    .wrap.chat .dock { position: sticky; bottom: 0; padding: 10px 0 16px; }
    .wrap.chat .box { background: var(--gm-glass-solid, rgba(24, 26, 38, 0.94)); }
    .box {
      width: 100%; display: flex; flex-direction: column; gap: 6px; padding: 14px 14px 12px 20px;
      border-radius: 26px; background: var(--gm-glass-fill, rgba(30, 33, 48, 0.5)); border: 1px solid var(--gm-glass-border, rgba(255, 255, 255, 0.1));
      box-shadow: var(--gm-glass-shadow, 0 12px 40px rgba(0, 0, 0, 0.35)); backdrop-filter: var(--gm-glass-blur, blur(20px)); -webkit-backdrop-filter: var(--gm-glass-blur, blur(20px));
      transition: border-color 160ms ease, box-shadow 160ms ease;
    }
    .box:focus-within { border-color: color-mix(in srgb, var(--sys-primary, #8ab4f8) 55%, transparent); }
    textarea {
      width: 100%; min-height: 32px; max-height: 220px; resize: none; border: 0; outline: 0; background: transparent;
      color: inherit; font: inherit; font-size: 17px; line-height: 1.55; padding: 6px 0;
    }
    textarea::placeholder { color: var(--sys-on-surface-variant, #6b7280); opacity: 0.9; }
    .bar { display: flex; align-items: center; gap: 8px; }
    .grow { flex: 1 1 auto; }
    button { font: inherit; }
    .icon, .send {
      width: 44px; height: 44px; flex: none; display: inline-flex; align-items: center; justify-content: center;
      border: 0; border-radius: 50%; cursor: pointer; color: var(--sys-on-surface-variant, #4b515d); background: transparent;
    }
    .icon svg, .send svg, .act svg, .ghost svg { fill: currentColor; }
    .icon:hover { background: var(--gm-tonal-hover, rgba(127, 127, 127, 0.14)); }
    .icon.on { background: #d93025; color: #fff; }
    .send { color: #fff; background: var(--gm-accent-gradient, linear-gradient(135deg, #1a73e8, #6a4cf0)); box-shadow: 0 6px 18px rgba(26, 95, 216, 0.35); }
    .send:disabled { opacity: 0.7; cursor: default; }
    .ghost {
      display: inline-flex; align-items: center; gap: 6px; height: 40px; padding: 0 14px 0 10px; border: 0; border-radius: 999px;
      background: var(--gm-tonal, rgba(127, 127, 127, 0.1)); color: var(--sys-on-surface-variant, #4b515d); cursor: pointer; font-size: 14px; font-weight: 500;
    }
    .ghost:hover { background: var(--gm-tonal-hover, rgba(127, 127, 127, 0.16)); }
    .spin { width: 20px; height: 20px; border-radius: 50%; border: 2.5px solid rgba(255, 255, 255, 0.4); border-top-color: #fff; animation: rot 800ms linear infinite; }
    @keyframes rot { to { transform: rotate(360deg); } }
    button:focus-visible, a:focus-visible { outline: 2px solid var(--sys-primary, #1a5fd8); outline-offset: 2px; }
    textarea:focus, textarea:focus-visible { outline: none; }

    /* Starters: icon + text, left-aligned under the box (like Gemini's home). */
    .try { list-style: none; margin: 4px 0 0; padding: 0 8px; width: 100%; display: flex; flex-direction: column; gap: 2px; }
    .starter {
      display: inline-flex; align-items: center; gap: 14px; min-height: 44px; padding: 8px 14px; border: 0; border-radius: 999px;
      background: transparent; color: var(--sys-on-surface, #15171c); cursor: pointer; font: inherit; font-size: 15px; text-align: start;
    }
    .starter svg { flex: none; fill: var(--sys-on-surface-variant, #6b7280); }
    .starter:hover, .starter:focus-visible { background: var(--gm-tonal, rgba(127, 127, 127, 0.1)); outline: 0; }

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
    @media (prefers-reduced-motion: reduce) { .shimmer, .typing i, .spin { animation: none; } }
    .media { display: block; width: 100%; max-height: 480px; object-fit: contain; border-radius: 12px; background: rgba(0, 0, 0, 0.25); }
    .audio { width: 100%; }
    .job-note, .job-error { margin: 0 4px; font-size: 14px; line-height: 1.5; color: var(--sys-on-surface-variant, #6b7280); }
    .job-error { color: #d93025; }
    .job-actions { display: flex; flex-wrap: wrap; gap: 8px; }
    .act {
      display: inline-flex; align-items: center; gap: 6px; height: 36px; padding: 0 14px 0 10px; border: 0; border-radius: 999px;
      background: var(--gm-tonal, rgba(127, 127, 127, 0.1)); color: var(--sys-on-surface, #15171c); text-decoration: none; font-size: 13.5px; font-weight: 500; cursor: pointer;
    }
    .act:hover { background: var(--gm-tonal-hover, rgba(127, 127, 127, 0.16)); }

    @media (max-width: 600px) {
      .wrap.empty { gap: 18px; padding-bottom: 0; }
      .starter { font-size: 14px; min-height: 40px; }
      .box { padding: 10px 10px 8px 14px; border-radius: 22px; }
      textarea { min-height: 58px; font-size: 16px; }
      .bubble { max-width: 88%; }
    }
  `;
}

if (!customElements.get('gm-home-chat')) customElements.define('gm-home-chat', GmHomeChat);
