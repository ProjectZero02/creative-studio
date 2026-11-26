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
import { LitElement, css, html, nothing, svg as svgPart } from '/ui/vendor/lit-3.2.1.js';
import { detectKind } from './detect_kind.js';
import './gm_audio.js';

const STORE = 'gm-home-chat';
const SETTINGS = 'gm-home-settings';
const HISTORY = 'gm-prompts:home';
const POLL_MS = 2000;
const MAX_FILES = 14;
const Recognition = window.SpeechRecognition || window.webkitSpeechRecognition;
const reduceMotion = () => window.matchMedia && window.matchMedia('(prefers-reduced-motion: reduce)').matches;

const ICON = {
  send: 'M4 12l1.4 1.4L11 7.8V20h2V7.8l5.6 5.6L20 12l-8-8z',
  mic: 'M12 14a3 3 0 0 0 3-3V5a3 3 0 0 0-6 0v6a3 3 0 0 0 3 3zm5-3a5 5 0 0 1-10 0H5a7 7 0 0 0 6 6.92V21h2v-3.08A7 7 0 0 0 19 11z',
  stop: 'M7 7h10v10H7z',
  undo: 'M12.5 8c-2.65 0-5.05.99-6.9 2.6L2 7v9h9l-3.62-3.62c1.39-1.16 3.16-1.88 5.12-1.88 3.54 0 6.55 2.31 7.6 5.5l2.37-.78C21.08 11.03 17.15 8 12.5 8z',
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
  check: 'M9 16.2 4.8 12l-1.4 1.4L9 19 21 7l-1.4-1.4z',
  chevron: 'M10 6 8.6 7.4 13.2 12l-4.6 4.6L10 18l6-6z',
  caret: 'M7 10l5 5 5-5z',
  tune: 'M3 17v2h6v-2zM3 5v2h10V5zm10 16v-2h8v-2h-8v-2h-2v6zM7 9v2H3v2h4v2h2V9zm14 4v-2H11v2zm-6-4h2V7h4V5h-4V3h-2z',
  attach: 'M16.5 6v11.5a4 4 0 0 1-8 0V5a2.5 2.5 0 0 1 5 0v10.5a1 1 0 0 1-2 0V6H10v9.5a2.5 2.5 0 0 0 5 0V5a4 4 0 0 0-8 0v12.5a5.5 5.5 0 0 0 11 0V6z',
  voice: 'M9 13a4 4 0 1 0 0-8 4 4 0 0 0 0 8zm0-6a2 2 0 1 1 0 4 2 2 0 0 1 0-4zm0 8c-2.7 0-8 1.3-8 4v2h16v-2c0-2.7-5.3-4-8-4zm-6 4c.2-.7 3.3-2 6-2s5.8 1.3 6 2zM16 5.1a6 6 0 0 1 0 7.8l1.4 1.4a8 8 0 0 0 0-10.6z',
  // Enhance: three sparkles (Material "auto_awesome"), as the studios use.
  enhance: 'M19 9l1.25-2.75L23 5l-2.75-1.25L19 1l-1.25 2.75L15 5l2.75 1.25L19 9zm-7.5.5L9 4 6.5 9.5 1 12l5.5 2.5L9 20l2.5-5.5L17 12l-5.5-2.5zM19 15l-1.25 2.75L15 19l2.75 1.25L19 23l1.25-2.75L23 19l-2.75-1.25L19 15z',
  text: 'M5 4v3h5.5v12h3V7H19V4z',
  library: 'M22 16V4a2 2 0 0 0-2-2H8a2 2 0 0 0-2 2v12a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2zm-11-4 2 2.7 3-3.7 4 5H8zM2 6v14a2 2 0 0 0 2 2h14v-2H4V6z',
};
// The send arrow: drawn with round strokes so it reads crisply at 20px.
const SEND = html`<svg viewBox="0 0 24 24" width="20" height="20" aria-hidden="true" class="stroke"><path d="M12 19.5V5M5.5 11.25 12 4.75l6.5 6.5"></path></svg>`;
// Media behind each type card: a still at rest, a moving sample on hover.
const CARD_MEDIA = {
  image: { still: '/ui/posters/gemini-image__page-cover.webp' },
  video: { still: '/ui/posters/gemini-omni__page-cover__hero.webp', moving: '/ui/home/word-video.webp' },
  music: { still: '/ui/posters/lyria_header.webp' },
  voice: { still: '/ui/posters/capability__native-audio_16-9.webp' },
  film: { still: '/ui/posters/veo__cover_s0RKXWX.webp', moving: '/ui/home/word-film.webp' },
};
// Words the box completes as you type (Tab accepts), per type.
const VOCAB = {
  any: ['cinematic', 'golden hour', 'photorealistic', 'minimalist', 'dramatic', 'soft light', 'close-up', 'wide shot',
    'studio light', 'background', 'reflection', 'shallow depth of field', 'aerial', 'portrait', 'landscape', 'vibrant', 'moody'],
  image: ['85mm lens', 'macro', 'flat lay', 'product shot', 'bokeh', 'film grain', 'overhead shot', 'illustration', 'watercolor', 'isometric'],
  video: ['slow motion', 'dolly in', 'tracking shot', 'drone shot', 'handheld', 'timelapse', 'orbit', 'crane shot', 'pan left', 'pan right'],
  music: ['instrumental', 'piano', 'strings', 'acoustic guitar', 'synthwave', 'orchestral', 'percussion', 'ambient', 'lo-fi', 'uplifting', 'melancholic'],
  voice: [],
};
// What a good prompt names, in order; after a comma the box offers the next missing part.
const NEXT_PART = {
  image: [[/\b(light|lit|sun|glow|shadow|neon|lamp|dusk|dawn|night)\b/i, 'soft natural light'],
    [/\b(mm|lens|close-?up|wide|macro|shot|angle|overhead)\b/i, '50mm lens, shallow depth of field'],
    [/\b(photo|realistic|illustration|render|painting|style|cinematic)\b/i, 'photorealistic']],
  video: [[/\b(dolly|pan|track|orbit|drone|zoom|handheld|crane|static|shot)\b/i, 'slow dolly in'],
    [/\b(light|lit|sun|glow|neon|dusk|dawn|night|golden)\b/i, 'golden hour light'],
    [/\b(mood|calm|tense|epic|dreamy|cinematic|energetic)\b/i, 'cinematic mood']],
  music: [[/\b(piano|guitar|strings|synth|drums|bass|orchestra|violin|sax)\b/i, 'soft piano and warm bass'],
    [/\b(\d+\s?bpm|tempo|slow|fast|upbeat)\b/i, '90 bpm'],
    [/\b(calm|happy|sad|epic|relaxed|uplifting|dark|dreamy|mood)\b/i, 'relaxed and uplifting']],
  voice: [],
};
// Samples shown inside the type tiles on hover (animated webp for video and film).
// Bar heights (0-1) of the loading placeholder for music and voice results.
const EQ = [0.35, 0.6, 0.9, 0.55, 1, 0.7, 0.45, 0.8, 0.5, 0.3, 0.65, 0.4];
// Music tile: a spectrum of thin lines rising from one baseline, each at its
// own speed (like a "now playing" equaliser). [peak 0-1, period ms, delay ms]
const MUSIC_BARS = [
  [0.45, 820, -120], [0.7, 640, -480], [0.55, 900, -260], [0.9, 700, -90], [0.65, 560, -400],
  [1, 760, -620], [0.75, 610, -180], [0.85, 880, -540], [0.6, 520, -300], [0.95, 740, -40],
  [0.7, 660, -700], [0.8, 590, -220], [0.5, 840, -460], [0.65, 700, -330], [0.4, 600, -150],
];
// Voice tile: three thin flowing waves, like a voice assistant speaking.
// Each path is a sine wave longer than the 200-wide view; sliding it left by
// one period loops seamlessly. [period, amplitude, seconds, class]
const VOICE_WAVES = [[80, 7, 2.6, 'w3'], [56, 10, 1.9, 'w2'], [64, 14, 1.4, 'w1']];
const sineWave = (period, amp) => {
  let d = 'M0 20';
  for (let x = 0, up = true; x < 200 + 2 * period; x += period / 2, up = !up) {
    d += ` Q${x + period / 4} ${up ? 20 - 2 * amp : 20 + 2 * amp} ${x + period / 2} 20`;
  }
  return d;
};
const VOICE_SVG = html`<svg viewBox="0 0 200 40" preserveAspectRatio="none">${VOICE_WAVES.map(([p, a, s, c]) =>
  svgPart`<g class="breathe ${c}"><path class="flow" d=${sineWave(p, a)} style="--p:${-p}px;--s:${s}s"></path></g>`)}</svg>`;
// The five types use the side menu's stroke icons (chat_nav.js), so a type
// looks the same in the menu, on its card, in the mode pill and in the path.
const KIND_STROKE = {
  image: ['M3.75 6.5a2.75 2.75 0 0 1 2.75-2.75h11a2.75 2.75 0 0 1 2.75 2.75v11a2.75 2.75 0 0 1-2.75 2.75h-11a2.75 2.75 0 0 1-2.75-2.75z',
    'M9 7.6a1.5 1.5 0 1 1 0 3 1.5 1.5 0 0 1 0-3z', 'm20.25 15-4.5-4.5L7 19.25'],
  video: ['M3.25 8A2.75 2.75 0 0 1 6 5.25h7.5A2.75 2.75 0 0 1 16.25 8v8a2.75 2.75 0 0 1-2.75 2.75H6A2.75 2.75 0 0 1 3.25 16z',
    'm16.25 10.25 4.5-2.75v9l-4.5-2.75'],
  music: ['M9 17.5V5.75l11-2V15.5', 'M6.5 15a2.5 2.5 0 1 1 0 5 2.5 2.5 0 0 1 0-5z', 'M17.5 13a2.5 2.5 0 1 1 0 5 2.5 2.5 0 0 1 0-5z'],
  voice: ['M10 4.75a3.5 3.5 0 1 1 0 7 3.5 3.5 0 0 1 0-7z', 'M3.75 20.25c0-3.2 2.7-5.5 6.25-5.5s6.25 2.3 6.25 5.5',
    'M17.25 6.5a4.5 4.5 0 0 1 0 5.5', 'M19.75 4.25a8 8 0 0 1 0 10'],
  film: ['M3.75 9.75h16.5v8a2.5 2.5 0 0 1-2.5 2.5H6.25a2.5 2.5 0 0 1-2.5-2.5z',
    'M3.9 9.6 3.4 7.4a2.5 2.5 0 0 1 1.85-3l10.5-2.5a2.5 2.5 0 0 1 3 1.85l.5 2.2z', 'm8.3 4.3 2.7 3.6', 'm13.6 3.05 2.7 3.6'],
};
// A path string draws a filled glyph; an array of paths draws a stroke icon.
const svg = (d, size = 20) => (Array.isArray(d)
  ? html`<svg class="stroke-i" viewBox="0 0 24 24" width=${size} height=${size} aria-hidden="true">${d.map((p) => svgPart`<path d=${p}></path>`)}</svg>`
  : html`<svg viewBox="0 0 24 24" width=${size} height=${size} aria-hidden="true"><path d=${d}></path></svg>`);
const kindIcon = (kind) => KIND_STROKE[kind] || ICON[kind] || ICON.spark;

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
    inputsJson: { type: String },
    talkJson: { type: String },
    live: { type: Boolean, reflect: true },
    navEvent: { type: String },
    _msgs: { state: true },
    _jobs: { state: true },
    _busy: { state: true },
    _listening: { state: true },
    _files: { state: true },
    _hasText: { state: true },
    _lock: { state: true },
    _auto: { state: true },
    _dismissed: { state: true },
    _enhancing: { state: true },
    _undo: { state: true },
    _panel: { state: true },
    _settings: { state: true },
    _dragOver: { state: true },
    _menu: { state: true },
    _adv: { state: true },
    _thinking: { state: true },
    _sug: { state: true },
    _armed: { state: true },
    panelOpen: { type: Boolean, reflect: true, attribute: 'panel' },
    // Mirrors body.dark-theme, so the headline repaints on a theme switch
    // (gradient text does not always repaint when only a variable changes).
    dark: { type: Boolean, reflect: true },
  };

  constructor() {
    super();
    this.stringsJson = '{}';
    this.kindsJson = '[]';
    this.optionsJson = '{}';
    this.inputsJson = '{}';
    // Settings picked under the box, per type; kept between visits.
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
    this._files = []; // [{ id, name, preview, handle, url, busy, error, slot, video }]
    this._hasText = false;
    // The mode: picked by hand (side menu, the mode pill) it stays until
    // removed; read from the text (detect_kind.js) it follows the words.
    this._lock = '';
    this._auto = null; // { kind, word } from the text
    this._dismissed = ''; // a detected mode the person turned off for this message
    this._enhancing = false;
    this._undo = null; // { before, after } until the enhanced text is edited
    this._menu = null; // open dropdown: { id, x, y, w, up, items }
    this._adv = false; // the Advanced panel behind "+"
    this._thinking = null; // live steps while the chat works: { steps, start }
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
    this._onPickKind = (e) => this._setLock((e.detail && e.detail.kind) || '');
    this._onDown = (e) => {
      if (!this._menu && !this._adv) return;
      const path = e.composedPath();
      const inside = (sel) => { const el = this.renderRoot.querySelector(sel); return !!el && path.includes(el); };
      if (this._menu && !inside('.pop') && !inside(`[data-menu="${this._menu.id}"]`)) this._menu = null;
      else if (this._adv && !this._menu && !inside('.adv') && !inside('.plus') && !inside('.pop')) this._adv = false;
    };
    this._onKeyDoc = (e) => {
      if (e.key !== 'Escape') return;
      if (this._menu) {
        const id = this._menu.id;
        this._menu = null;
        this.updateComplete.then(() => this.renderRoot.querySelector(`[data-menu="${id}"]`)?.focus());
      } else if (this._adv) this._adv = false;
    };
    this._onViewport = () => { if (this._menu) this._menu = null; };
    this._sug = ''; // the ghost text after the cursor (Tab accepts)
    this._sugOff = ''; // text the person dismissed a suggestion for (Esc)
    this.dark = !!document.body?.classList.contains('dark-theme');
  }

  get _kinds() {
    try { return JSON.parse(this.kindsJson || '[]'); } catch (_) { return []; }
  }

  /** The type controls' fields: {image: [field], video: [...], ...}. */
  get _options() {
    try { return JSON.parse(this.optionsJson || '{}') || {}; } catch (_) { return {}; }
  }

  /** File slots per type: {video: [{name, label, accept, max, show_if}], ...}. */
  get _inputs() {
    try { return JSON.parse(this.inputsJson || '{}') || {}; } catch (_) { return {}; }
  }

  /** The type the next message makes ('' = chat). */
  get _mode() {
    if (this._lock) return this._lock;
    const k = this._auto && this._auto.kind;
    return k && k !== this._dismissed && this._options[k] ? k : '';
  }

  _setLock(kind) {
    // A film has its own screen (Story Studio): open it with what is typed.
    if (kind === 'film') {
      const k = this._kinds.find((x) => x.kind === 'film');
      if (k) { this._menu = null; this._openFull(k); return; }
    }
    this._lock = kind && this._options[kind] ? kind : '';
    this._sug = '';
    this._dismissed = '';
    this._menu = null;
    this._adv = false;
    this.updateComplete.then(() => { if (this._ta) { this._ta.focus(); this._armed = true; } });
  }

  /** Clear the mode: a picked one unlocks, a detected one is dismissed. */
  _clearMode() {
    if (this._lock) this._lock = '';
    else if (this._auto) this._dismissed = this._auto.kind;
    this._menu = null;
    this._adv = false;
  }

  /** Does a field (or file slot) apply, given the other values ({show_if}). */
  static _shown(f, values) {
    const cond = f.show_if || {};
    return Object.keys(cond).every((k) => (cond[k] || []).includes(values[k]));
  }

  /** The fields shown for a type, each with its current value and choices. */
  _fields(kind) {
    const list = this._options[kind] || [];
    const mine = this._settings[kind] || {};
    const out = [];
    const picked = {};
    list.forEach((f) => {
      const choice = (f.by_model && f.by_model[picked.model]) || f;
      const type = f.type || 'select';
      const dflt = choice.default ?? f.default;
      let value;
      if (type === 'select') {
        const values = (choice.options || []).map((o) => o.value);
        value = values.includes(mine[f.name]) ? mine[f.name] : dflt;
      } else if (type === 'toggle') {
        value = mine[f.name] === 'on' || mine[f.name] === 'off' ? mine[f.name] : (dflt || 'off');
      } else {
        value = mine[f.name] !== undefined ? mine[f.name] : (dflt ?? '');
      }
      picked[f.name] = value;
      out.push({ ...f, type, tier: f.tier || 'main', options: choice.options || [], value, dflt });
    });
    return out.filter((f) => GmHomeChat._shown(f, picked));
  }

  _values(kind) {
    const out = {};
    this._fields(kind).forEach((f) => { out[f.name] = f.value; });
    return out;
  }

  /** File slots that apply to a type right now. */
  _slots(kind) {
    const values = this._values(kind);
    return (this._inputs[kind] || []).filter((s) => GmHomeChat._shown(s, values));
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
    window.addEventListener('gm-pick-kind', this._onPickKind);
    window.addEventListener('pointerdown', this._onDown, true);
    window.addEventListener('keydown', this._onKeyDoc);
    window.addEventListener('resize', this._onViewport);
    if (document.body) {
      this._themeObs = new MutationObserver(() => { this.dark = document.body.classList.contains('dark-theme'); });
      this._themeObs.observe(document.body, { attributes: true, attributeFilter: ['class'] });
      this.dark = document.body.classList.contains('dark-theme');
    }
    // Fetch the moving card samples once the page is idle, so hover is instant.
    const warm = () => Object.values(CARD_MEDIA).forEach((m) => { if (m.moving) { const i = new Image(); i.src = m.moving; } });
    if (window.requestIdleCallback) window.requestIdleCallback(warm, { timeout: 4000 }); else setTimeout(warm, 2500);
    let params = new URLSearchParams();
    try { params = new URL(window.location.href).searchParams; } catch (_) { /* ignore */ }
    const askedChat = params.get('chat') || '';
    if (params.get('new')) this._newChat(params.get('project') || '');
    else if (askedChat && askedChat !== this._chatId) this._openChat(askedChat);
    else this._announce();
    const mode = params.get('mode') || '';
    if (mode) {
      this.updateComplete.then(() => this._setLock(mode));
      try {
        const u = new URL(window.location.href);
        u.searchParams.delete('mode');
        window.history.replaceState(window.history.state, '', u.pathname + u.search);
      } catch (_) { /* ignore */ }
    }
    if (this._pending().length) this._poll();
    // Elapsed time on running jobs and on the thinking steps.
    this._tick = setInterval(() => { if (this._pending().length || this._thinking) this.requestUpdate(); }, 1000);
    setTimeout(() => window.gmLive && window.gmLive.refreshLauncher && window.gmLive.refreshLauncher(), 60);
  }

  disconnectedCallback() {
    super.disconnectedCallback();
    window.removeEventListener('gm-open-chat', this._onOpenChat);
    window.removeEventListener('gm-new-chat', this._onNewChat);
    window.removeEventListener('gm-pick-kind', this._onPickKind);
    window.removeEventListener('pointerdown', this._onDown, true);
    window.removeEventListener('keydown', this._onKeyDoc);
    window.removeEventListener('resize', this._onViewport);
    this._themeObs?.disconnect();
    clearInterval(this._tick);
    if (this._saveTimer) { clearTimeout(this._saveTimer); this._persist(); }
    clearTimeout(this._timer);
    if (this._rec) try { this._rec.stop(); } catch (_) { /* ignore */ }
    window.gmKind = '';
    window.dispatchEvent(new CustomEvent('gm-kind-changed', { detail: { kind: '' } }));
    setTimeout(() => window.gmLive && window.gmLive.refreshLauncher && window.gmLive.refreshLauncher(), 60);
  }

  _afterUpdate(changed) {
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
    const mode = this._mode;
    if (mode) {
      await this._make(mode, typed, files);
      return;
    }
    this._hist = -1;
    if (this._ta) { this._ta.value = ''; this._fit(); }
    this._hasText = false;
    this._sug = '';
    this._auto = null;
    this._dismissed = '';
    const said = typed || this._s.attach_default || 'What can you make from this?';
    const message = files.length ? `[Attached: ${files.map((f) => f.handle).join(', ')}] ${said}` : said;
    this._files = [];
    this._msgs = [...this._msgs, { role: 'user', text: said, images: files.map((f) => f.url) }];
    this._busy = true;
    const start = Date.now();
    this._thinking = { steps: [], start };
    let reply = '';
    let jobs = [];
    let trace = [];
    try {
      const r = await fetch('/api/chat', {
        method: 'POST',
        credentials: 'same-origin',
        headers: { 'Content-Type': 'application/json', Accept: 'application/x-ndjson, application/json' },
        body: JSON.stringify({ message, stream: true }),
      });
      if (!r.ok) throw new Error(String(r.status));
      const type = r.headers.get('content-type') || '';
      if (type.includes('ndjson') && r.body) {
        // The chat's steps arrive one line at a time while it works.
        const reader = r.body.getReader();
        const dec = new TextDecoder();
        let buf = '';
        let done = false;
        const take = (line) => {
          if (!line.trim()) return;
          let ev;
          try { ev = JSON.parse(line); } catch (_) { return; }
          if (ev.type === 'step') {
            this._thinking = { ...this._thinking, steps: [...this._thinking.steps, { label: ev.label || '', detail: ev.detail || '' }] };
          } else if (ev.type === 'done') {
            reply = ev.reply || '';
            jobs = Array.isArray(ev.jobs) ? ev.jobs : [];
            trace = Array.isArray(ev.trace) ? ev.trace : this._thinking.steps;
          } else if (ev.type === 'error') {
            throw new Error(ev.message || '');
          }
        };
        while (!done) {
          const chunk = await reader.read();
          done = chunk.done;
          buf += dec.decode(chunk.value || new Uint8Array(), { stream: !done });
          const lines = buf.split('\n');
          buf = lines.pop();
          lines.forEach(take);
        }
        take(buf);
        if (!trace.length) trace = this._thinking.steps;
      } else {
        const body = await r.json();
        reply = body.reply || '';
        jobs = Array.isArray(body.jobs) ? body.jobs : [];
        trace = Array.isArray(body.trace) ? body.trace : [];
      }
    } catch (err) {
      reply = (err && err.message && !/^\d+$/.test(err.message) ? err.message : '') || this._s.error || 'Something went wrong. Please try again.';
      trace = this._thinking ? this._thinking.steps : [];
    }
    const next = { ...this._jobs };
    jobs.forEach((j) => { next[j.id] = j; });
    this._jobs = next;
    this._thinking = null;
    this._msgs = [...this._msgs, {
      role: 'assistant', text: reply, jobs: jobs.map((j) => j.id), ask: message,
      trace: trace.map((t) => ({ label: t.label || '', detail: t.detail || '' })), took: Math.round((Date.now() - start) / 1000),
    }];
    this._busy = false;
    if (jobs.length && !this._panelClosed && !this._phone()) this._panel = true;
    if (jobs.length) this._poll();
    this.updateComplete.then(() => this._ta && this._ta.focus());
  }

  /** A mode is on: start that job with exactly the settings shown (no chat model). */
  async _make(kind, typed, files) {
    const S = this._s;
    const label = this._kindLabel(kind);
    if (!typed && kind !== 'video') {
      this._flash(S.need_prompt || 'Write what to make first.');
      return;
    }
    const settings = this._values(kind);
    const fields = this._fields(kind);
    // Files go to their slots; a named earlier result ("animate image 2") is the source.
    const inputs = {};
    files.forEach((f) => {
      const slot = f.slot || this._defaultSlot(kind, f);
      if (!slot) return;
      (inputs[slot] = inputs[slot] || []).push(f.handle);
    });
    const named = (typed.match(/\b(image|upload|video) \d+\b/i) || [])[0] || '';
    const source = (kind === 'image' || kind === 'video') ? ((files.find((f) => !f.video) || {}).handle || named.toLowerCase()) : '';
    const detected = !this._lock && this._auto ? this._auto.word : '';
    const start = Date.now();
    // What the page decided, shown as the first thinking steps.
    const steps = [
      { label: S.t_read || 'Reading your prompt', detail: '' },
      {
        label: `${S.t_mode || 'Making'}: ${label}`,
        detail: detected ? (S.t_detected || 'You wrote “{word}”').replace('{word}', detected) : (S.t_picked || 'Picked by you'),
      },
      { label: S.t_settings || 'Settings', detail: fields.filter((f) => f.value !== '' && f.value !== undefined).map((f) => `${f.label}: ${this._show(f)}`).join(' · ') },
    ];
    if (Object.keys(inputs).length) {
      steps.push({ label: S.t_files || 'Files', detail: Object.entries(inputs).map(([k, v]) => `${this._slotLabel(kind, k)}: ${v.join(', ')}`).join(' · ') });
    }
    this._hist = -1;
    if (this._ta) { this._ta.value = ''; this._fit(); }
    this._hasText = false;
    this._sug = '';
    this._auto = null;
    this._dismissed = '';
    this._files = [];
    this._adv = false;
    this._msgs = [...this._msgs, { role: 'user', text: typed, images: files.filter((f) => !f.video).map((f) => f.url) }];
    this._busy = true;
    this._thinking = { steps, start };
    let reply = '';
    let meta = '';
    let job = null;
    let trace = steps;
    try {
      const r = await fetch('/api/chat/job', {
        method: 'POST', credentials: 'same-origin',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ kind, prompt: typed, settings, source, inputs }),
      });
      const body = await r.json().catch(() => ({}));
      if (!r.ok) throw new Error(body.detail || '');
      reply = body.reply || '';
      meta = [label, body.summary].filter(Boolean).join(' · ');
      job = body.job || null;
      const extra = (Array.isArray(body.trace) ? body.trace : []).map((t) => (typeof t === 'string' ? { label: t, detail: '' } : t));
      // The server names the model and settings itself: keep ours only when it doesn't.
      trace = extra.length ? [...steps.filter((t) => t.label !== (S.t_settings || 'Settings')), ...extra] : steps;
    } catch (err) {
      reply = (err && err.message) || S.error || 'Something went wrong. Please try again.';
    }
    if (job) this._jobs = { ...this._jobs, [job.id]: job };
    this._thinking = null;
    this._msgs = [...this._msgs, { role: 'assistant', text: reply, jobs: job ? [job.id] : [], meta, trace, took: Math.round((Date.now() - start) / 1000) }];
    this._busy = false;
    if (job && !this._panelClosed && !this._phone()) this._panel = true;
    if (job) this._poll();
    this.updateComplete.then(() => this._ta && this._ta.focus());
  }

  _kindLabel(kind) {
    const k = this._kinds.find((x) => x.kind === kind);
    return (k && k.label) || kind;
  }

  /** A field's value as people read it. */
  _show(f) {
    if (f.type === 'toggle') return f.value === 'on' ? (this._s.on || 'On') : (this._s.off || 'Off');
    if (f.type === 'select') {
      const o = (f.options || []).find((x) => x.value === f.value);
      return o ? o.label : String(f.value ?? '');
    }
    const v = String(f.value ?? '');
    return v.length > 40 ? `${v.slice(0, 40)}…` : v;
  }

  _slotLabel(kind, name) {
    const s = (this._inputs[kind] || []).find((x) => x.name === name);
    return (s && s.label) || name;
  }

  /** Where a file goes when the person didn't pick a slot. */
  _defaultSlot(kind, f) {
    const slots = this._slots(kind);
    const fits = slots.filter((s) => (f.video ? /video/ : /image/).test(s.accept || 'image/*'));
    const taken = (name) => this._files.filter((x) => x.slot === name).length;
    const model = this._values(kind).model;
    const free = fits.find((s) => taken(s.name) < ((s.by_model && s.by_model[model]) || s.max || 1));
    return (free || fits[0] || {}).name || '';
  }

  // ---------------------------------------------------------------- films

  /** Where a film is: Scenario, Set, Storyboard, Film, with this job's step lit. */
  _storySteps(j) {
    const S = this._s;
    const p = j.params || {};
    const steps = [['scenario', S.step_scenario || 'Scenario'], ['set', S.step_set || 'Set'],
      ['storyboard', S.step_storyboard || 'Storyboard'], ['video', S.step_film || 'Film']];
    const at = { editor: 'storyboard', stories: 'scenario', create: 'scenario' }[p.story_step] || p.story_step || 'scenario';
    let idx = Math.max(0, steps.findIndex(([id]) => id === at));
    const running = j.status !== 'done' && j.status !== 'failed';
    if (p.has_film) idx = steps.length;
    return html`<ol class="steps" aria-label=${S.film_steps || 'Film steps'}>
      ${steps.map(([id, label], i) => {
        const state = i < idx || (i === idx && j.status === 'done') ? 'done' : i === idx && running ? 'now' : i === idx && j.status === 'failed' ? 'bad' : '';
        return html`<li class="step ${state}" aria-current=${state === 'now' ? 'step' : 'false'}><i aria-hidden="true"></i>${label}</li>`;
      })}
    </ol>`;
  }

  /** Next step and Whole film, on a finished step of a film that isn't done. */
  _filmButtons(j, cls) {
    const S = this._s;
    const p = j.params || {};
    if (j.status !== 'done' || p.has_film || !p.story_id) return nothing;
    // Only the film's latest step offers the next one.
    const same = Object.values(this._jobs).filter((x) => x.params && x.params.story_id === p.story_id);
    if (same.length && same[same.length - 1].id !== j.id) return nothing;
    return html`<button class="${cls}" type="button" ?disabled=${this._busy} @click=${() => this._filmNext(p.story_id, false)}>${svg(ICON.send, 16)}${S.next_step || 'Next step'}</button>
      <button class="${cls}" type="button" ?disabled=${this._busy} @click=${() => this._filmNext(p.story_id, true)} title=${S.whole_film_tip || 'Run every remaining step'}>${svg(ICON.film, 16)}${S.whole_film || 'Whole film'}</button>`;
  }

  async _filmNext(storyId, all) {
    if (this._busy) return;
    const S = this._s;
    this._busy = true;
    let reply = '';
    let job = null;
    try {
      const r = await fetch('/api/chat/film', {
        method: 'POST', credentials: 'same-origin',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ story_id: storyId, all }),
      });
      const body = await r.json().catch(() => ({}));
      if (!r.ok) throw new Error(body.detail || '');
      reply = body.reply || '';
      job = body.job || null;
    } catch (err) {
      reply = (err && err.message) || S.error || 'Something went wrong. Please try again.';
    }
    if (job) this._jobs = { ...this._jobs, [job.id]: job };
    this._msgs = [...this._msgs, { role: 'assistant', text: reply, jobs: job ? [job.id] : [] }];
    this._busy = false;
    if (job && !this._panelClosed && !this._phone()) this._panel = true;
    if (job) this._poll();
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
    // Repeated clicks while a reset is running are one reset.
    if (this._resetting) return;
    this._resetting = true;
    clearTimeout(this._timer);
    // Clear the box at once, so the click shows straight away: the text,
    // files, open menus and the mode (a new chat always starts in Auto).
    this._hist = -1;
    if (this._ta) { this._ta.value = ''; this._fit(); }
    this._hasText = false;
    this._sug = '';
    this._undo = null;
    this._files = [];
    this._lock = '';
    this._auto = null;
    this._dismissed = '';
    this._menu = null;
    this._adv = false;
    try {
      if (this._saveTimer) { clearTimeout(this._saveTimer); this._saveTimer = null; await this._persist(); }
      else if (this._saving) { try { await this._saving; } catch (_) { /* ignore */ } }
    } finally {
      this._resetting = false;
    }
    this._loading = true;
    this._msgs = [];
    this._jobs = {};
    this._chatId = '';
    this._newId = '';
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
      params: { story_id: p.story_id, story_step: p.story_step, has_film: p.has_film, settings: p.settings },
      stages: j.stages, stage: j.stage, started_at: j.started_at, finished_at: j.finished_at,
    };
  }

  _queueSave() {
    clearTimeout(this._saveTimer);
    this._saveTimer = setTimeout(() => { this._saveTimer = null; this._persist(); }, 700);
  }

  /** Save the chat. One save at a time, so two quick saves can't both create it. */
  _persist() {
    const run = async () => {
      try { await this._saving; } catch (_) { /* the last one failed; try again */ }
      await this._persistNow();
    };
    this._saving = run();
    return this._saving;
  }

  async _persistNow() {
    if (!this._msgs.length) return;
    const messages = this._msgs.map((m) => ({
      role: m.role, text: m.text || '', images: (m.images || []).filter((u) => u && !String(u).startsWith('blob:')),
      jobs: (m.jobs || []).map((id) => this._snapshot(typeof id === 'string' ? id : id.id)), ask: m.ask || null, meta: m.meta || '', trace: m.trace || [], took: m.took || 0,
    }));
    const job_ids = Object.keys(this._jobs);
    try {
      if (!this._chatId) {
        // Our own id, so a repeated create updates the same chat.
        if (!this._newId) this._newId = [...crypto.getRandomValues(new Uint8Array(6))].map((b) => b.toString(16).padStart(2, '0')).join('');
        const r = await fetch('/api/chats', {
          method: 'POST', credentials: 'same-origin', headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ id: this._newId, messages, job_ids, project_id: this._projectId }),
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
    else if (this._saving) { try { await this._saving; } catch (_) { /* ignore */ } }
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
      return { role: m.role, text: m.text, images: m.images || [], jobs: ids, ask: m.ask || undefined, meta: m.meta || '', trace: m.trace || [], took: m.took || 0 };
    });
    this._chatId = chat.id;
    this._newId = '';
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
    this._sug = '';
    ta.focus();
    ta.setSelectionRange(text.length, text.length);
  }

  // ---------------------------------------------------------------- suggestions

  /** The example prompt for the current type (the placeholder; Tab uses it). */
  _example() {
    const S = this._s;
    return S[`ex_${this._mode || 'auto'}`] || '';
  }

  /**
   * Ghost text after the cursor, all local and instant: the end of a past
   * prompt that starts the same way, the rest of a word being typed, or,
   * after a comma, the next part a good prompt names (light, lens, mood...).
   */
  _suggest(text) {
    if (!text || !text.trim() || /\n$/.test(text) || text === this._sugOff) return '';
    const low = text.toLowerCase();
    const past = readHistory().find((h) => h.length > text.length + 1 && h.toLowerCase().startsWith(low));
    if (past) return past.slice(text.length);
    if (/[؀-ۿ]/.test(text)) return '';
    const mode = this._mode;
    const word = (/(?:^|[\s,])([a-z][a-z-]{2,})$/i.exec(text) || [])[1];
    if (word) {
      const w = word.toLowerCase();
      const pool = [...(VOCAB[mode] || []), ...VOCAB.any];
      const hit = pool.find((v) => v.startsWith(w) && v !== w);
      return hit ? hit.slice(w.length) : '';
    }
    if (/,\s?$/.test(text) && text.trim().split(/\s+/).length >= 3) {
      const parts = NEXT_PART[mode] || NEXT_PART.image;
      const next = parts.find(([re]) => !re.test(text));
      if (next) return (text.endsWith(' ') ? '' : ' ') + next[1];
    }
    return '';
  }

  _acceptSug() {
    const ta = this._ta;
    if (!ta || !this._sug) return false;
    const text = ta.value + this._sug;
    this._prefill(text);
    this._onInput();
    return true;
  }

  /** Keep the ghost layer scrolled with the text. */
  _syncGhost() {
    const g = this.renderRoot.querySelector(".gh");
    const ta = this._ta;
    if (g && ta) g.scrollTop = ta.scrollTop;
  }

  // ---------------------------------------------------------------- menus

  /**
   * Open a dropdown under (or above) its button. items: [{ label, value?,
   * checked?, icon?, hint?, run }]. One menu at a time; Esc, a click outside
   * or a scroll closes it. Arrow keys move between items.
   */
  _openMenu(e, id, items, opts = {}) {
    e.stopPropagation();
    if (this._menu && this._menu.id === id) { this._menu = null; return; }
    const r = e.currentTarget.getBoundingClientRect();
    const h = Math.min(360, items.length * 40 + 16);
    const below = window.innerHeight - r.bottom;
    const up = below < h + 12 && r.top > below;
    const w = Math.max(opts.width || 220, r.width);
    const x = Math.min(Math.max(8, opts.alignEnd ? r.right - w : r.left), window.innerWidth - w - 8);
    this._menu = { id, items, x, w, y: up ? window.innerHeight - r.top + 6 : r.bottom + 6, up, title: opts.title || '' };
    this.updateComplete.then(() => {
      const pop = this.renderRoot.querySelector('.pop');
      (pop?.querySelector('[aria-checked="true"]') || pop?.querySelector('button'))?.focus();
    });
  }

  _menuKey(e) {
    const items = [...this.renderRoot.querySelectorAll('.pop button:not(:disabled)')];
    const at = items.indexOf(this.renderRoot.activeElement);
    let next = -1;
    if (e.key === 'ArrowDown') next = (at + 1) % items.length;
    else if (e.key === 'ArrowUp') next = (at - 1 + items.length) % items.length;
    else if (e.key === 'Home') next = 0;
    else if (e.key === 'End') next = items.length - 1;
    else if (e.key === 'Tab') { this._menu = null; return; }
    else if (this._isTypeKey(e)) { e.preventDefault(); next = this._typeahead(e.key, items.map((b) => b.dataset.l || b.textContent), at); }
    if (next >= 0) { e.preventDefault(); items[next].focus(); items[next].scrollIntoView({ block: 'nearest' }); }
  }

  _isTypeKey(e) {
    if (e.ctrlKey || e.metaKey || e.altKey || e.isComposing || e.key.length !== 1) return false;
    // Space presses the item, unless it is part of a word being typed ("New Y…").
    return e.key !== ' ' || (Date.now() - (this._typedAt || 0) < 700 && !!this._typed);
  }

  /**
   * Type to jump, like a native select: "f" goes to the next item starting
   * with F (again moves on through the F's), "fre" typed quickly goes to
   * "French". Case and accents are ignored. Returns the index or -1.
   */
  _typeahead(key, labels, at) {
    const fold = (s) => String(s ?? '').trim().normalize('NFD').replace(/\p{M}/gu, '').toLocaleLowerCase();
    const c = fold(key) || key;
    const now = Date.now();
    this._typed = now - (this._typedAt || 0) < 700 ? (this._typed || '') + c : c;
    this._typedAt = now;
    const repeat = [...this._typed].every((x) => x === c);
    const prefix = repeat ? c : this._typed;
    const start = Math.max(0, repeat ? at + 1 : at);
    const n = labels.length;
    for (let k = 0; k < n; k++) {
      const i = (start + k) % n;
      if (fold(labels[i]).startsWith(prefix)) return i;
    }
    return -1;
  }

  _popover() {
    const m = this._menu;
    if (!m) return nothing;
    const pos = `left:${m.x}px;width:${m.w}px;${m.up ? `bottom:${m.y}px` : `top:${m.y}px`}`;
    return html`<div class="pop ${m.up ? 'up' : ''}" role="menu" aria-label=${m.title} style=${pos} @keydown=${this._menuKey}>
      ${m.title ? html`<div class="pop-title">${m.title}</div>` : nothing}
      ${m.items.map((it) => (it.sep ? html`<div class="pop-sep" role="separator"></div>` : html`
        <button type="button" data-l=${typeof it.label === 'string' ? it.label : nothing} role=${it.checked === undefined ? 'menuitem' : 'menuitemradio'} aria-checked=${it.checked === undefined ? nothing : String(!!it.checked)}
          ?disabled=${!!it.disabled} @click=${() => { const keep = it.keep; if (!keep) this._menu = null; it.run && it.run(); }}>
          ${it.icon ? svg(it.icon, 18) : nothing}
          <span class="pop-l">${it.label}${it.hint ? html`<small>${it.hint}</small>` : nothing}</span>
          ${it.checked ? svg(ICON.check, 18) : it.more ? svg(ICON.chevron, 18) : nothing}
        </button>`))}
    </div>`;
  }

  /** A select field as a pill that opens our own menu (no native <select>). */
  _pill(kind, f, cls = '') {
    const id = `f-${kind}-${f.name}`;
    if (f.type === 'toggle') {
      const on = f.value === 'on';
      return html`<button type="button" class="pill ${cls} ${on ? 'on' : ''}" role="switch" aria-checked=${on ? 'true' : 'false'}
        @click=${() => this._setField(kind, f.name, on ? 'off' : 'on')} title=${f.help || f.label}>
        <span class="pl">${f.label}</span><b>${this._show(f)}</b></button>`;
    }
    const items = f.options.map((o) => ({ label: o.label, checked: o.value === f.value, run: () => this._setField(kind, f.name, o.value) }));
    return html`<button type="button" class="pill ${cls}" data-menu=${id} aria-haspopup="menu" aria-expanded=${this._menu && this._menu.id === id ? 'true' : 'false'}
      @click=${(e) => this._openMenu(e, id, items, { title: f.label, alignEnd: cls.includes('end') })} title=${f.help || f.label}>
      <span class="pl">${f.label}</span><b>${this._show(f)}</b>${svg(ICON.caret, 16)}</button>`;
  }

  /** The row under the box: mode, the type's main settings, Model at the end. */
  _settingsRow() {
    const S = this._s;
    const mode = this._mode;
    const kinds = this._kinds.filter((k) => this._options[k.kind]);
    const modeItems = [
      { label: S.auto || 'Auto', hint: S.auto_tip || 'The chat picks what to make', icon: ICON.spark, checked: !mode, run: () => { this._lock = ''; this._dismissed = this._auto ? this._auto.kind : ''; } },
      ...kinds.map((k) => ({ label: k.label, hint: k.desc, icon: kindIcon(k.kind), checked: mode === k.kind, run: () => this._setLock(k.kind) })),
    ];
    const detected = mode && !this._lock;
    const fields = mode ? this._fields(mode).filter((f) => f.tier !== 'advanced' && (f.type !== 'select' || f.options.length > 1)) : [];
    const model = fields.find((f) => f.name === 'model');
    const rest = fields.filter((f) => f !== model && (f.type === 'select' || f.type === 'toggle'))
      .sort((a, b) => (b.name === 'mode') - (a.name === 'mode'));
    return html`<div class="under" role="group" aria-label=${S.settings || 'Settings'}>
      <span class="mode-wrap">
        <button type="button" class="pill mode ${mode ? 'set' : ''}" data-menu="mode" aria-haspopup="menu"
          @click=${(e) => this._openMenu(e, 'mode', modeItems, { title: S.kinds || 'What to make', width: 260 })}
          title=${detected ? (S.t_detected || 'You wrote “{word}”').replace('{word}', this._auto.word) : (S.kinds || 'What to make')}>
          ${svg(mode ? kindIcon(mode) : ICON.spark, 16)}<b>${mode ? this._kindLabel(mode) : (S.auto || 'Auto')}</b>
          ${detected ? html`<span class="auto-tag">${S.detected || 'auto'}</span>` : nothing}${svg(ICON.caret, 16)}
        </button>
        ${mode ? html`<button type="button" class="pill-x" @click=${() => this._clearMode()} aria-label=${S.clear_mode || 'Back to chat'} title=${S.clear_mode || 'Back to chat'}>${svg(ICON.close, 14)}</button>` : nothing}
      </span>
      ${rest.map((f) => this._pill(mode, f))}
      ${model ? html`<span class="grow"></span>${this._pill(mode, model, 'end')}` : nothing}
    </div>`;
  }

  // ---------------------------------------------------------------- + menu

  _plusMenu(e) {
    const S = this._s;
    const mode = this._mode;
    const items = [{ label: S.add_files || 'Add files or photos', icon: ICON.attach, hint: 'Ctrl+U', run: () => this._pick('') }];
    if (mode) {
      this._slots(mode).forEach((s) => items.push({ label: `${S.add || 'Add'} ${s.label.toLowerCase()}`, icon: /video/.test(s.accept || '') ? ICON.video : ICON.image, run: () => this._pick(s.name) }));
    }
    const done = Object.values(this._jobs).filter((j) => j.status === 'done' && j.kind === 'image' && j.display_url).slice(-4).reverse();
    if (done.length) {
      items.push({ sep: true });
      done.forEach((j) => items.push({ label: `${S.use || 'Use'} ${j.handle}`, hint: j.prompt ? j.prompt.slice(0, 48) : '', icon: ICON.image, run: () => this._useRef(j) }));
    }
    const adv = mode ? this._fields(mode).filter((f) => f.tier === 'advanced') : [];
    items.push({ sep: true });
    if (adv.length) items.push({ label: S.advanced || 'Advanced settings', icon: ICON.tune, more: true, hint: this._advChanged(mode) ? (S.changed || 'Changed') : '', run: () => { this._adv = true; } });
    const k = this._kinds.find((x) => x.kind === mode);
    if (k && k.href) items.push({ label: S.open_studio || 'Open full studio', icon: ICON.open, run: () => this._openFull(k) });
    this._openMenu(e, 'plus', items, { width: 280 });
  }

  _advChanged(kind) {
    return !!kind && this._fields(kind).some((f) => f.tier === 'advanced' && f.dflt !== undefined && String(f.value) !== String(f.dflt));
  }

  _openFull(k) {
    const prompt = (this._ta?.value || '').trim();
    const params = prompt ? { prompt } : {};
    // Fade out at once while the next page loads (about a second).
    this.toggleAttribute('leaving', true);
    clearTimeout(this._leaveTimer);
    // Back in view if the page did not change (offline, an error).
    this._leaveTimer = setTimeout(() => this.removeAttribute('leaving'), 4000);
    if (this.navEvent) this.dispatchEvent(new MesopEvent(this.navEvent, { route: k.href, params }));
    else window.location.assign(k.href + (prompt ? `?prompt=${encodeURIComponent(prompt)}` : ''));
  }

  /** Advanced settings for the mode: a panel above the box. */
  _advPanel() {
    const mode = this._mode;
    if (!this._adv || !mode) return nothing;
    const S = this._s;
    const fields = this._fields(mode).filter((f) => f.tier === 'advanced');
    return html`<div class="adv" role="dialog" aria-label=${S.advanced || 'Advanced settings'}>
      <div class="adv-head"><b>${S.advanced || 'Advanced settings'}</b><span>${this._kindLabel(mode)}</span>
        <button type="button" class="icon sm" @click=${() => { this._adv = false; }} aria-label=${S.close || 'Close'}>${svg(ICON.close, 18)}</button></div>
      <div class="adv-list">${fields.map((f) => this._advField(mode, f))}</div>
      ${this._advChanged(mode) ? html`<button type="button" class="act reset" @click=${() => this._resetAdv(mode)}>${svg(ICON.retry, 16)}${S.reset || 'Reset'}</button>` : nothing}
    </div>`;
  }

  _advField(kind, f) {
    const set = (v) => this._setField(kind, f.name, v);
    let control;
    if (f.type === 'toggle') {
      control = html`<button type="button" class="switch ${f.value === 'on' ? 'on' : ''}" role="switch" aria-checked=${f.value === 'on' ? 'true' : 'false'}
        aria-label=${f.label} @click=${() => set(f.value === 'on' ? 'off' : 'on')}><i></i></button>`;
    } else if (f.type === 'select') {
      control = this._pill(kind, f, 'in-adv');
    } else if (f.type === 'textarea') {
      control = html`<textarea class="field" rows="3" .value=${String(f.value ?? '')} placeholder=${f.placeholder || ''} aria-label=${f.label}
        @change=${(e) => set(e.target.value)}></textarea>`;
    } else {
      control = html`<input class="field" type=${f.type === 'number' ? 'number' : 'text'} .value=${String(f.value ?? '')} placeholder=${f.placeholder || ''}
        min=${f.min ?? nothing} max=${f.max ?? nothing} aria-label=${f.label} @change=${(e) => set(e.target.value)}>`;
    }
    const wide = f.type === 'textarea' || f.type === 'text';
    return html`<div class="adv-row ${wide ? 'wide' : ''}"><span class="adv-l">${f.label}${f.help ? html`<small>${f.help}</small>` : nothing}</span>${control}</div>`;
  }

  _resetAdv(kind) {
    const mine = { ...(this._settings[kind] || {}) };
    this._fields(kind).filter((f) => f.tier === 'advanced').forEach((f) => { delete mine[f.name]; });
    this._settings = { ...this._settings, [kind]: mine };
    try { localStorage.setItem(SETTINGS, JSON.stringify(this._settings)); } catch (_) { /* ignore */ }
  }

  // ---------------------------------------------------------------- enhance

  /** Replace the whole box as one undoable edit, so Ctrl+Z brings the old text back. */
  _replaceUndoable(text) {
    const ta = this._ta;
    if (!ta) return;
    ta.focus();
    ta.select();
    let ok = false;
    try { ok = document.execCommand('insertText', false, text); } catch (_) { ok = false; }
    if (!ok || ta.value !== text) { this._prefill(text); return; }
    ta.setSelectionRange(text.length, text.length);
  }

  async _enhance() {
    const ta = this._ta;
    if (!ta || this._enhancing) return;
    // Second press: put their own words back (Ctrl+Z does the same).
    if (this._undo && ta.value === this._undo.after) {
      const { before } = this._undo;
      this._undo = null;
      this._replaceUndoable(before);
      return;
    }
    const before = ta.value;
    const text = before.trim();
    if (!text) return;
    this._enhancing = true;
    try {
      const r = await fetch('/api/prompts/enhance', {
        method: 'POST',
        credentials: 'same-origin',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ prompt: text, kind: this._mode }),
      });
      if (r.ok) {
        const body = await r.json();
        // Replace only what was enhanced (the person may have kept typing).
        if (body.prompt && this._ta && this._ta.value === before && body.prompt !== before) {
          this._replaceUndoable(body.prompt);
          this._undo = { before, after: this._ta.value };
        }
      }
    } catch (_) { /* keep their words */ }
    this._enhancing = false;
  }

  // ---------------------------------------------------------------- attach

  /** Open the file picker; slot ('' = let the page choose) says where files go. */
  _pick(slot = '') {
    const input = this.renderRoot.querySelector('input[type=file]');
    if (!input) return;
    this._pickSlot = slot;
    const s = slot && this._mode ? this._slots(this._mode).find((x) => x.name === slot) : null;
    const anyVideo = this._mode && this._slots(this._mode).some((x) => /video/.test(x.accept || ''));
    input.accept = s ? (s.accept || 'image/*') : `image/png,image/jpeg,image/webp${anyVideo ? ',video/mp4,video/webm,video/quicktime' : ''}`;
    input.click();
  }

  _onFiles(e) {
    this._addFiles([...(e.target.files || [])], this._pickSlot || '');
    this._pickSlot = '';
    e.target.value = '';
  }

  _onPaste(e) {
    const files = [...(e.clipboardData?.files || [])].filter((f) => f.type.startsWith('image/'));
    if (files.length) { e.preventDefault(); this._addFiles(files); }
  }

  _addFiles(list, slot = '') {
    const room = MAX_FILES - this._files.length;
    list.filter((f) => /^image\/(png|jpeg|webp)$/.test(f.type) || /^video\/(mp4|webm|quicktime)$/.test(f.type))
      .slice(0, Math.max(0, room)).forEach((file) => {
        const id = Math.random().toString(36).slice(2, 9);
        const video = file.type.startsWith('video/');
        const item = { id, name: file.name, preview: URL.createObjectURL(file), busy: true, video, slot };
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

  /** Move an attachment to another slot (first frame, reference...). */
  _slotMenu(e, f) {
    const mode = this._mode;
    const slots = mode ? this._slots(mode).filter((s) => (f.video ? /video/ : /image/).test(s.accept || 'image/*')) : [];
    if (slots.length < 2) return;
    const cur = f.slot || this._defaultSlot(mode, f);
    this._openMenu(e, `slot-${f.id}`, slots.map((s) => ({
      label: s.label, checked: s.name === cur,
      run: () => { this._files = this._files.map((x) => (x.id === f.id ? { ...x, slot: s.name } : x)); },
    })), { title: this._s.use_as || 'Use as' });
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
    const mode = this._mode;
    return html`<div class="files">${this._files.map((f) => {
      const slot = mode ? (f.slot || this._defaultSlot(mode, f)) : '';
      const many = mode && this._slots(mode).filter((s) => (f.video ? /video/ : /image/).test(s.accept || 'image/*')).length > 1;
      return html`
      <div class="file ${f.error ? 'bad' : ''}" title=${f.error || f.name}>
        ${f.video ? html`<video src=${f.preview} muted playsinline preload="metadata"></video>` : html`<img src=${f.preview} alt=${f.name}>`}
        ${f.busy ? html`<span class="file-spin" aria-hidden="true"></span>` : nothing}
        ${slot ? html`<button type="button" class="file-slot" data-menu=${`slot-${f.id}`} ?disabled=${!many}
            @click=${(e) => this._slotMenu(e, f)} title=${this._s.use_as || 'Use as'}>${this._slotLabel(mode, slot)}</button>` : nothing}
        <button type="button" class="file-x" @click=${() => this._unattach(f.id)} aria-label=${(this._s.remove || 'Remove') + ' ' + f.name}>${svg(ICON.close, 14)}</button>
      </div>`;
    })}</div>`;
  }

  // ---------------------------------------------------------------- keys

  _onInput() {
    this._fit();
    if (this._undo && this._ta && this._ta.value !== this._undo.after) this._undo = null;
    this._armed = true;
    const text = this._ta?.value || '';
    const has = !!text.trim();
    if (has !== this._hasText) this._hasText = has;
    // Only offer a completion with the cursor at the end of the text.
    const ta = this._ta;
    const atEnd = ta && ta.selectionStart === ta.selectionEnd && ta.selectionEnd === text.length;
    this._sug = atEnd ? this._suggest(text) : '';
    if (this._sug) this.requestUpdate(); // the ghost copies the typed text
    this.updateComplete.then(() => this._syncGhost());
    // Read the mode from the words as they are typed (detect_kind.js).
    clearTimeout(this._detectTimer);
    this._detectTimer = setTimeout(() => this._detect(), 120);
  }

  _detect() {
    const text = this._ta?.value || '';
    const found = detectKind(text);
    const before = this._auto ? this._auto.kind : '';
    this._auto = found;
    if (!text.trim()) this._dismissed = '';
    if ((found ? found.kind : '') !== before && this._dismissed && found && found.kind !== this._dismissed) this._dismissed = '';
  }

  _fit() {
    const ta = this._ta;
    if (!ta) return;
    ta.style.height = 'auto';
    ta.style.height = `${Math.min(ta.scrollHeight, 220)}px`;
  }

  _onKey(e) {
    const ta = e.target;
    if ((e.ctrlKey || e.metaKey) && (e.key === 'u' || e.key === 'U')) {
      e.preventDefault();
      this._pick('');
      return;
    }
    if (e.key === 'Enter' && !e.shiftKey && !e.isComposing) {
      e.preventDefault();
      this._send();
      return;
    }
    // Tab: take the suggestion, or put the example prompt in an empty box.
    // Shift+Tab and a box with nothing to offer keep normal focus moves.
    if (e.key === 'Tab' && !e.shiftKey && !e.altKey && !e.ctrlKey && !e.metaKey) {
      if (this._sug) { e.preventDefault(); this._acceptSug(); return; }
      // Only once the person is working in the box (clicked, typed or picked
      // a type), so tabbing through the page never drops text in it.
      if (this._armed && !ta.value.trim() && this._example()) { e.preventDefault(); this._prefill(this._example()); this._detect(); return; }
      return;
    }
    if (e.key === 'ArrowRight' && this._sug && ta.selectionEnd === ta.value.length) {
      e.preventDefault();
      this._acceptSug();
      return;
    }
    if (e.key === 'Escape' && this._sug) {
      e.preventDefault();
      e.stopPropagation();
      this._sugOff = ta.value;
      this._sug = '';
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
    const mode = this._mode;
    const sendLabel = mode ? `${S.send || 'Send'}: ${this._kindLabel(mode)}` : (S.send || 'Send');
    const example = this._example();
    const holder = example || (mode && S[`ph_${mode}`]) || S.placeholder || 'Ask me anything';
    // One round slot: Live while empty, Send once there is something to send.
    // Both stay in the page and cross-fade, so typing never makes it jump.
    const showLive = this.live && !ready && !this._busy;
    const enhanceLabel = this._enhancing ? (S.enhancing || 'Enhancing…') : this._undo ? (S.undo_enhance || 'Undo enhance') : (S.enhance || 'Enhance prompt');
    const empty = !this._hasText && !this._files.length;
    const how = S[`how_${mode || 'auto'}`] || '';
    // Read out the whole word being completed ("cinematic"), not only its tail.
    const word = this._sug && !/^\s/.test(this._sug) ? ((this._ta?.value || '').match(/[^\s,]*$/) || [''])[0] : '';
    const sugText = this._sug ? (S.suggestion || 'Suggestion: {text}. Press Tab to accept.').replace('{text}', (word + this._sug).trim()) : '';
    // Once the person is in the box, the example is drawn in the ghost layer
    // (not the placeholder) so the Tab key can sit at the end of it.
    const exGhost = this._armed && empty && !!example;
    const tabKey = html`<kbd class="g-key">Tab</kbd>`;
    return html`
      <div class="box ${this._busy ? 'busy' : ''} ${this._dragOver ? 'drop' : ''}"
        @dragover=${this._onDragOver} @dragleave=${this._onDragLeave} @drop=${this._onDrop}>
        ${this._attachments()}
        <input type="file" accept="image/png,image/jpeg,image/webp" multiple hidden @change=${this._onFiles}>
        <div class="ta-wrap">
          <div class="gh" aria-hidden="true">${exGhost
            ? html`<span class="g-ex">${example}</span>${tabKey}`
            : html`<span class="g-typed">${this._ta ? this._ta.value : ''}</span><span class="g-sug">${this._sug}</span>${this._sug ? tabKey : nothing}`}</div>
          <textarea rows="1" @paste=${this._onPaste} .placeholder=${exGhost ? '' : holder}
            aria-label=${S.placeholder || 'Ask me anything'} aria-describedby="sug-live"
            @keydown=${this._onKey} @input=${this._onInput} @scroll=${this._syncGhost}
            @pointerdown=${() => { this._armed = true; }}
            @click=${() => this._onInput()} @blur=${() => { this._sug = ''; this._armed = false; }}></textarea>
        </div>
        <span id="sug-live" class="sr" aria-live="polite">${sugText}</span>
        <div class="row">
          <button class="icon plus ${this._advChanged(mode) ? 'dot-on' : ''}" type="button" data-menu="plus" aria-haspopup="menu"
            @click=${(e) => this._plusMenu(e)} aria-label=${S.more || 'Add files and more'} title=${S.more || 'Add files and more'}>${svg(ICON.plus, 22)}</button>
          <span class="hint ${empty && how ? 'shown' : ''}" aria-hidden="true">
            <span class="hl">${mode ? (S.format_label || 'Format:') : (S.hint_label || 'Hint:')}</span><span class="how">${how}</span>
          </span>
          <span class="grow"></span>
          <div class="tools">
            <button class="icon enh ${this._hasText ? 'shown' : ''} ${this._enhancing ? 'working' : ''} ${this._undo ? 'undo' : ''}" type="button" @click=${this._enhance}
              @mousedown=${(e) => e.preventDefault()}
              ?disabled=${this._enhancing || !this._hasText} tabindex=${this._hasText ? '0' : '-1'} aria-hidden=${this._hasText ? 'false' : 'true'}
              aria-label=${enhanceLabel} title=${enhanceLabel}>${svg(this._undo ? ICON.undo : ICON.enhance, 20)}</button>
            ${Recognition ? html`<button class="icon ${this._listening ? 'on' : ''}" type="button" @click=${this._toggleMic}
                aria-pressed=${this._listening ? 'true' : 'false'}
                aria-label=${this._listening ? (S.dictate_stop || 'Stop dictation') : (S.dictate || 'Dictate')}
                title=${this._listening ? (S.dictate_stop || 'Stop dictation') : (S.dictate || 'Dictate')}>
                ${svg(this._listening ? ICON.stop : ICON.mic, 20)}</button>` : nothing}
            <div class="slot ${showLive ? 'live-on' : 'send-on'}">
              <button class="send ${ready || this._busy ? '' : 'off'}" type="button" @click=${() => this._send()} ?disabled=${!ready || this._busy}
                tabindex=${showLive ? '-1' : '0'} aria-hidden=${showLive ? 'true' : 'false'}
                aria-label=${sendLabel} title=${sendLabel}>${this._busy ? html`<span class="spin" aria-hidden="true"></span>` : SEND}</button>
              ${this.live ? html`<live-call-button class="live" pill filled .stringsJson=${talk} ?inert=${!showLive} aria-hidden=${showLive ? 'false' : 'true'}></live-call-button>` : nothing}
            </div>
          </div>
        </div>
        ${this._note ? html`<div class="note" role="status">${this._note}</div>` : nothing}
      </div>`;
  }

  _media(j) {
    const url = j.display_url || '';
    const mime = j.mime_type || '';
    if (!url) return nothing;
    if (mime.startsWith('video/') || j.kind === 'video' || (j.kind === 'story' && j.params && j.params.has_film)) {
      return html`<div class="stage"><video class="media" src=${url} controls playsinline preload="metadata"></video></div>`;
    }
    if (mime.startsWith('audio/') || j.kind === 'music' || j.kind === 'voice') {
      return html`<gm-audio class="audio" .src=${url} .label=${j.handle || ''} .strings=${this._s} ?speed=${j.kind === 'voice'}></gm-audio>`;
    }
    if (mime.startsWith('image/') || j.kind === 'image') {
      return html`<div class="stage"><a href=${url} target="_blank" rel="noopener"><img class="media" src=${url} alt=${j.prompt || j.handle} loading="lazy"></a></div>`;
    }
    return nothing;
  }

  _studio(j) {
    if (j.kind === 'story') {
      const p = j.params || {};
      return p.story_id ? `/story?id=${encodeURIComponent(p.story_id)}&step=${encodeURIComponent(p.story_step || 'scenario')}` : '/story';
    }
    return '/library';
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
        ${running ? this._skeleton(j) : nothing}
        ${j.status === 'done' ? this._media(j) : nothing}
        ${isStory ? this._storySteps(j) : nothing}
        ${this._progress(j)}
        ${j.status === 'failed' ? html`<p class="job-error">${j.error || ''}</p>` : nothing}
        ${j.status === 'done' || j.status === 'failed' ? html`<div class="job-actions">
          ${isStory ? this._filmButtons(j, 'act') : nothing}
          ${j.status === 'done' && j.display_url && !isStory ? html`<a class="act" href=${j.display_url} download target="_blank" rel="noopener">${svg(ICON.download, 18)}${S.download || 'Download'}</a>` : nothing}
          ${j.status === 'done' && j.kind === 'image' ? html`<button class="act" type="button" @click=${() => this._prefill(`${S.edit_prefix || 'Edit'} ${j.handle}: `)}>${svg(ICON.edit, 18)}${S.edit || 'Edit'}</button>` : nothing}
          ${j.status === 'done' && j.kind === 'image' ? html`<button class="act" type="button" @click=${() => this._animate(j)}>${svg(ICON.spark, 18)}${S.animate || 'Animate'}</button>` : nothing}
          ${j.status === 'done' ? (() => { const href = this._studio(j); return html`<a class="act" href=${href} @click=${(e) => this._openStudio(e, href)}>${svg(ICON.open, 18)}${isStory ? (S.open_film || 'Open in Film Studio') : (S.open || 'Open in Library')}</a>`; })() : nothing}
          ${j.status === 'failed' ? html`<button class="act" type="button" @click=${() => this._retry(j)}>${svg(ICON.retry, 18)}${S.retry || 'Try again'}</button>` : nothing}
        </div>` : nothing}
      </div>`;
  }

  /** Try a failed job again: same type and prompt when the type has settings. */
  _retry(j) {
    if (this._busy) return;
    if (j.kind && this._options[j.kind] && j.kind !== 'story') this._make(j.kind, j.prompt || '', []);
    else this._send(j.prompt);
  }

  /** A placeholder in the shape being made (from the job's settings). */
  _skeleton(j) {
    const set = (j.params && j.params.settings) || {};
    const m = /^(\d+(?:\.\d+)?):(\d+(?:\.\d+)?)$/.exec(String(set.aspect || set.aspect_ratio || set.shape || ''));
    const ratio = m ? `${m[1]} / ${m[2]}` : (j.kind === 'image' ? '1 / 1' : '16 / 9');
    if (j.kind === 'music' || j.kind === 'voice') return html`<div class="shimmer audio-sk" aria-hidden="true">${EQ.concat(EQ).map((h) => html`<i style="--h:${h}"></i>`)}</div>`;
    if (j.kind === 'story') return nothing;
    return html`<div class="stage"><div class="shimmer" style="aspect-ratio:${ratio}" aria-hidden="true"></div></div>`;
  }

  /**
   * The job's steps as they happen (live_jobs stages): done ✓, the current one
   * pulsing, the rest waiting; an elapsed timer and an estimate bar. Film jobs
   * list their own tasks.
   */
  _progress(j) {
    const S = this._s;
    const stages = Array.isArray(j.stages) ? j.stages : [];
    const tasks = Array.isArray(j.tasks) ? j.tasks : [];
    const running = j.status !== 'done' && j.status !== 'failed';
    if (!stages.length && !tasks.length) return nothing;
    const at = Math.max(0, Math.min(stages.length - 1, Number(j.stage) || 0));
    const started = Number(j.started_at) || 0;
    const ended = Number(j.finished_at) || 0;
    const secs = started ? Math.max(0, Math.round(((running ? Date.now() / 1000 : (ended || Date.now() / 1000)) - started))) : 0;
    const typical = Number(j.typical_seconds) || 0;
    const pct = running && typical ? Math.min(95, Math.round((secs / typical) * 100)) : 100;
    const state = (i) => {
      if (j.status === 'done') return 'done';
      if (i < at) return 'done';
      if (i === at) return j.status === 'failed' ? 'bad' : 'now';
      return '';
    };
    const dur = secs < 60
      ? (S.secs || '{n} s').replace('{n}', secs)
      : (S.mins || '{m} min {n} s').replace('{m}', Math.floor(secs / 60)).replace('{n}', secs % 60);
    const time = secs ? `${dur}${running && typical ? ` · ${(S.about || 'about {n} s').replace('{n}', typical)}` : ''}` : '';
    const shownTasks = tasks.slice(0, 8);
    const doneTasks = tasks.filter((t) => t.status === 'done').length;
    return html`<details class="prog ${running ? 'live' : ''}" ?open=${running || j.status === 'failed'}>
      <summary>
        <span class="prog-t">${running ? (stages[at] || S.making || 'Making…') : j.status === 'failed' ? (S.failed || 'Failed') : (S.steps_done || 'Steps')}</span>
        ${tasks.length ? html`<span class="prog-n">${doneTasks} / ${tasks.length}</span>` : nothing}
        <span class="prog-time">${time}</span>
      </summary>
      ${running ? html`<div class="bar" role="progressbar" aria-valuemin="0" aria-valuemax="100" aria-valuenow=${pct}><i style="width:${pct}%"></i></div>` : nothing}
      ${stages.length ? html`<ol class="stages">${stages.map((s, i) => html`<li class="st ${state(i)}">${state(i) === 'done' ? svg(ICON.check, 14) : html`<i aria-hidden="true"></i>`}<span>${s}</span></li>`)}</ol>` : nothing}
      ${shownTasks.length ? html`<ol class="stages tasks">${shownTasks.map((t) => html`<li class="st ${t.status === 'done' ? 'done' : t.status === 'running' ? 'now' : t.status === 'failed' ? 'bad' : ''}">
          ${t.status === 'done' ? svg(ICON.check, 14) : html`<i aria-hidden="true"></i>`}<span>${t.label}</span></li>`)}
        ${tasks.length > shownTasks.length ? html`<li class="st more">+${tasks.length - shownTasks.length}</li>` : nothing}</ol>` : nothing}
    </details>`;
  }

  /** The chat's thinking: live while it works, folded into one line after. */
  _think(steps, live, took) {
    const S = this._s;
    if (!steps || (!steps.length && !live)) return nothing;
    const secs = live ? Math.max(1, Math.round((Date.now() - live) / 1000)) : took;
    const head = live ? (S.thinking || 'Thinking') : (S.thought || 'Thought for {n} s').replace('{n}', String(secs || 1));
    return html`<details class="think ${live ? 'live' : ''}" ?open=${!!live}>
      <summary>${svg(ICON.spark, 16)}<span>${head}</span>${live ? html`<span class="think-dots"><i></i><i></i><i></i></span>` : html`<span class="think-n">${steps.length}</span>`}${svg(ICON.caret, 16)}</summary>
      <ol class="think-list">
        ${steps.map((s, i) => html`<li class=${live && i === steps.length - 1 ? 'now' : 'done'}>
          ${live && i === steps.length - 1 ? html`<i aria-hidden="true"></i>` : svg(ICON.check, 14)}
          <span><b>${s.label}</b>${s.detail ? html`<small>${s.detail}</small>` : nothing}</span></li>`)}
        ${live && !steps.length ? html`<li class="now"><i aria-hidden="true"></i><span><b>${S.t_read || 'Reading your message'}</b></span></li>` : nothing}
      </ol>
    </details>`;
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
      return html`<gm-audio class="pj-audio" compact .src=${url} .label=${j.handle || ""} .strings=${this._s}></gm-audio>`;
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
        ${isStory ? this._storySteps(j) : nothing}
        ${j.status === 'failed' && j.error ? html`<p class="pj-error">${j.error}</p>` : nothing}
        ${done || j.status === 'failed' ? html`<div class="pj-acts">
          ${isStory ? this._filmButtons(j, 'pa') : nothing}
          ${done && j.kind === 'image' ? html`<button class="pa" type="button" @click=${() => this._animate(j)}>${svg(ICON.spark, 16)}${S.animate || 'Animate'}</button>
            <button class="pa" type="button" @click=${() => this._useRef(j)} title=${S.reference_tip || 'Use as a reference in your next message'}>${svg(ICON.plus, 16)}${S.reference || 'Reference'}</button>` : nothing}
          ${done && j.display_url && !isStory ? html`<a class="pa icon" href=${j.display_url} download target="_blank" rel="noopener" aria-label=${S.download || 'Download'} title=${S.download || 'Download'}>${svg(ICON.download, 18)}</a>` : nothing}
          ${done ? html`<a class="pa ${isStory ? '' : 'icon'}" href=${href} @click=${(e) => this._openStudio(e, href)}
              aria-label=${isStory ? (S.open_film || 'Open in Film Studio') : (S.open || 'Open in Library')}
              title=${isStory ? (S.open_film || 'Open in Film Studio') : (S.open || 'Open in Library')}>${svg(ICON.open, 18)}${isStory ? (S.open_short || 'Open') : nothing}</a>` : nothing}
          ${j.status === 'failed' ? html`<button class="pa" type="button" @click=${() => this._retry(j)}>${svg(ICON.retry, 16)}${S.retry || 'Try again'}</button>` : nothing}
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
    const live = this._thinking;
    return html`<div class="thread" role="log" aria-label=${this._s.thread || 'Conversation'}>
      ${this._msgs.map((m) => m.role === 'user'
        ? html`<div class="msg user"><div class="user-col">
            ${(m.images || []).length ? html`<div class="sent">${m.images.map((u) => html`<img src=${u} alt="">`)}</div>` : nothing}
            ${m.text ? html`<div class="bubble">${m.text}</div>` : nothing}</div></div>`
        : html`<div class="msg bot"><span class="avatar" aria-hidden="true">${svg(ICON.spark, 18)}</span>
            <div class="bot-body">${this._think(m.trace, 0, m.took)}${m.text ? html`<div class="text">${m.text}</div>` : nothing}${m.meta ? html`<div class="meta">${m.meta}</div>` : nothing}${(m.jobs || []).map((id) => this._job(id))}</div></div>`)}
      ${this._busy ? html`<div class="msg bot"><span class="avatar busy" aria-hidden="true">${svg(ICON.spark, 18)}</span>
          <div class="bot-body">${this._think(live ? live.steps : [], live ? live.start : Date.now(), 0)}</div></div>` : nothing}
      <div class="end"></div>
    </div>`;
  }

  /**
   * The type cards on the empty page: a still behind each name that comes
   * alive on hover (a moving clip, a picture, a sound wave). A click puts the
   * box in that type; Film opens Story Studio. The picked card stays lit.
   */
  _cards() {
    const S = this._s;
    const mode = this._mode;
    const list = this._kinds;
    if (!list.length) return nothing;
    return html`<div class="cards" role="group" aria-label=${S.kinds || 'What to make'}>
      ${list.map((k) => {
        const m = CARD_MEDIA[k.kind] || {};
        const on = mode === k.kind;
        return html`<button type="button" class="card k-${k.kind} ${on ? 'on' : ''}" aria-pressed=${on ? 'true' : 'false'}
            @click=${() => (on ? this._clearMode() : this._setLock(k.kind))}>
          <span class="card-media" aria-hidden="true">
            <span class="still" style="background-image:url('${m.still || ''}')"></span>
            ${m.moving ? html`<span class="moving" style="background-image:url('${m.moving}')"></span>` : nothing}
            ${k.kind === 'music' ? html`<span class="viz eq">${MUSIC_BARS.map(([h, d, o]) => html`<i style="--h:${h};--d:${d}ms;--o:${o}ms"></i>`)}</span>` : nothing}
            ${k.kind === 'voice' ? html`<span class="viz wave">${VOICE_SVG}</span>` : nothing}
          </span>
          <span class="card-text">
            <span class="card-name">${svg(kindIcon(k.kind), 18)}${k.label}${k.kind === 'film' ? svg(ICON.open, 14) : nothing}</span>
            <span class="card-desc">${k.desc}</span>
          </span>
        </button>`;
      })}
    </div>`;
  }

  /**
   * How the prompt becomes the result, above the box while a type is picked
   * and nothing is sent yet: your prompt → the model with its settings → the
   * result, saved to the Library. It follows the pills under the box.
   */
  _path() {
    const mode = this._mode;
    if (!mode || mode === 'film') return nothing;
    const S = this._s;
    const fields = this._fields(mode).filter((f) => f.tier !== 'advanced' && (f.type === 'select' || f.type === 'toggle'));
    const model = fields.find((f) => f.name === 'model');
    const rest = fields.filter((f) => f !== model && f.type === 'select').slice(0, 3).map((f) => this._show(f));
    const files = this._files.filter((f) => f.handle).length;
    const steps = [
      { icon: mode === 'voice' ? ICON.text : ICON.edit, label: mode === 'voice' ? (S.p_text || 'Your text') : (S.p_prompt || 'Your prompt'),
        detail: files ? (S.p_files || '+ {n} files').replace('{n}', files) : '' },
      { icon: ICON.enhance, label: model ? this._show(model) : this._kindLabel(mode), detail: rest.join(' · '), main: true },
      { icon: kindIcon(mode), label: S[`p_out_${mode}`] || this._kindLabel(mode), detail: '' },
      { icon: ICON.library, label: S.p_saved || 'Saved to Library', detail: '' },
    ];
    return html`<ol class="path" aria-label=${S.path || 'How this is made'}>
      ${steps.map((s, i) => html`${i ? html`<li class="link" aria-hidden="true"><i></i></li>` : nothing}
        <li class="pstep ${s.main ? 'main' : ''}" style="--i:${i}">
          <span class="pdot">${svg(s.icon, 16)}</span>
          <span class="ptext"><b>${s.label}</b>${s.detail ? html`<small>${s.detail}</small>` : nothing}</span>
        </li>`)}
    </ol>`;
  }

  render() {
    const S = this._s;
    const chatting = this._msgs.length > 0;
    const mode = this._mode;
    const title = (mode && S[`title_${mode}`]) || S.title || "Google's creative AI, in one studio";
    return html`
      <div class="wrap ${chatting ? 'chat' : 'empty'}">
        ${chatting ? this._thread() : html`
          <section class="hero">
            <h1 class="title ${mode ? 'moded' : ''}">${title}</h1>
          </section>`}
        <div class="dock">
          ${chatting ? html`<div class="dock-top">${this._jobsPill('inline')}<button class="ghost newchat" type="button" @click=${() => this._newChat(this._projectId)} title=${S.new_chat_tip || 'Start over with an empty chat'}>
              ${svg(ICON.newchat, 18)}<span>${S.new_chat || 'New chat'}</span></button></div>` : nothing}
          ${chatting ? nothing : this._path()}
          ${this._advPanel()}
          ${this._box()}
          ${this._settingsRow()}
          ${chatting ? nothing : this._cards()}
        </div>
      </div>
      ${this._jobsPanel()}
      ${this._popover()}`;
  }

  updated(changed) {
    this._afterUpdate(changed);
    // Tell the side menu which type is on, so its row lights up.
    const mode = this._mode;
    if (mode !== this._shownMode) {
      const first = this._shownMode === undefined;
      this._shownMode = mode;
      window.gmKind = mode;
      window.dispatchEvent(new CustomEvent('gm-kind-changed', { detail: { kind: mode } }));
      // The headline and the path change with a short fade, not a jump.
      if (!first && !reduceMotion()) {
        const t = this.renderRoot.querySelector('.title');
        t && t.animate([{ opacity: 0, transform: 'translateY(8px)', filter: 'blur(4px)' }, { opacity: 1, transform: 'none', filter: 'none' }],
          { duration: 360, easing: 'cubic-bezier(0.2, 0.8, 0.2, 1)' });
      }
    }
  }

  willUpdate() {
    // The host makes room for the open panel (wide screens only, in CSS).
    this.panelOpen = this._panel && Object.keys(this._jobs).length > 0;
  }

  static styles = css`
    :host { display: block; font-family: var(--gm-font, 'Google Sans', system-ui, sans-serif); color: var(--sys-on-surface, #15171c); }
    * { box-sizing: border-box; }
    .wrap { display: flex; flex-direction: column; align-items: center; width: 100%; margin: 0 auto; }
    /* Opening Film Studio: fade out at once while the next page loads. */
    :host([leaving]) .wrap { opacity: 0; transform: translateY(-6px); transition: opacity 160ms ease, transform 160ms ease; pointer-events: none; }
    @media (prefers-reduced-motion: reduce) { :host([leaving]) .wrap { transform: none; transition: none; } }
    /* Empty: everything centred on the screen (topbar 60px, frame padding). */
    .wrap.empty { min-height: var(--gm-home-fit, calc(100dvh - 84px)); justify-content: center; gap: clamp(28px, 5vh, 48px); padding-bottom: 8vh; }
    .wrap.chat { min-height: var(--gm-home-fit, calc(100dvh - 84px)); justify-content: flex-end; max-width: 820px; }

    .hero { display: flex; flex-direction: column; align-items: center; text-align: center; gap: clamp(8px, 1.6vh, 14px); }
    /* Gradient headline. The padding keeps the first letter and the
       descenders (g, y) inside the painted box, so nothing is cut. Light and
       dark each name their colours, keyed on [dark], which this element sets
       from body.dark-theme. */
    .title {
      margin: 0; max-width: 16em; font-size: clamp(2rem, 1rem + 2.2vw, 3.25rem); line-height: 1.16;
      padding: 0.04em 0.08em 0.1em; font-weight: 600; letter-spacing: -0.03em; text-wrap: balance;
      background: linear-gradient(100deg, #15171c 0%, #15171c 38%, #1a5fd8 72%, #7b3fe4 100%);
      -webkit-background-clip: text; background-clip: text; color: transparent; -webkit-text-fill-color: transparent;
    }
    :host([dark]) .title { background-image: linear-gradient(100deg, #fff 0%, #fff 38%, #8ab4f8 72%, #c58af9 100%); }
    .title.moded { background-image: linear-gradient(100deg, #15171c 0%, #15171c 20%, #1a5fd8 60%, #7b3fe4 100%); }
    :host([dark]) .title.moded { background-image: linear-gradient(100deg, #fff 0%, #fff 20%, #8ab4f8 60%, #c58af9 100%); }

    /* The prompt box (same glass as the studios' composer). */
    .dock { width: 100%; max-width: 820px; display: flex; flex-direction: column; gap: 12px; align-items: center; }
    .wrap.empty .dock { gap: 10px; }
    /* Results line up with the box: the card spans the column, not just the reply. */
    .bot-body > .job { margin-inline-start: -44px; width: calc(100% + 44px); }
    .wrap.chat .dock { position: sticky; bottom: 0; padding: 18px 0 12px;
      background: linear-gradient(to bottom, transparent 0, color-mix(in srgb, var(--sys-background, #0d0e11) 92%, transparent) 26px); }
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
    /* Like Claude's box: the text on top, then one row with + on the left and
       Enhance, Dictate, Live/Send on the right. */
    .row { display: flex; align-items: center; gap: 4px; }
    .grow { flex: 1 1 auto; }
    textarea {
      display: block; width: 100%; min-width: 0; height: 52px; min-height: 52px; max-height: 220px; resize: none; border: 0; outline: 0;
      background: transparent; color: inherit; font: inherit; font-size: 17px; line-height: 24px; padding: 14px 14px 4px;
      /* Typed text reads in its own direction (dir="auto"), in either UI language. */
      unicode-bidi: plaintext;
    }
    textarea::placeholder { color: var(--sys-on-surface-variant, #6b7280); opacity: 0.9; }
    .tools { flex: none; display: flex; align-items: center; gap: 6px; }
    .row { padding-block: 0; padding-inline: 0 2px; }
    button { font: inherit; }
    .icon, .send {
      width: 40px; height: 40px; flex: none; display: inline-flex; align-items: center; justify-content: center; padding: 0;
      border: 0; border-radius: 50%; cursor: pointer; color: var(--sys-on-surface-variant, #4b515d); background: transparent;
      transition: background-color 140ms ease, color 140ms ease;
    }
    .icon svg, .send svg, .act svg, .ghost svg { fill: currentColor; }
    .icon:hover:not(:disabled) { background: var(--gm-tonal-hover, rgba(127, 127, 127, 0.14)); color: var(--sys-on-surface, #15171c); }
    .icon.on { background: #d93025; color: #fff; }
    .icon.undo { color: var(--sys-primary, #1a73e8); }
    .send { color: var(--sys-on-primary, #fff); background: var(--sys-primary, #1a73e8);
      box-shadow: 0 2px 10px color-mix(in srgb, var(--sys-primary, #1a73e8) 35%, transparent); }
    .send:hover:not(:disabled) { filter: brightness(1.08); }
    .send:disabled { cursor: default; }
    .send.off { background: var(--gm-tonal, rgba(127, 127, 127, 0.14)); color: var(--sys-on-surface-variant, #6b7280); box-shadow: none; }
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

    /* Conversation */
    .thread { width: 100%; display: flex; flex-direction: column; gap: 18px; padding: 12px 0 8px; }
    .msg { display: flex; gap: 12px; align-items: flex-start; }
    .msg.user { justify-content: flex-end; }
    .bubble {
      max-width: 78%; padding: 12px 16px; border-radius: 20px; border-end-end-radius: 6px; font-size: 16px; line-height: 1.5; white-space: pre-wrap;
      unicode-bidi: plaintext;
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
      display: flex; flex-direction: column; gap: 10px; padding: 12px; border-radius: 18px; width: 100%;
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
      .shimmer, .typing i, .spin, .icon.working svg, .audio-sk i, .think li.now i, .st.now i, .think-dots i, .bar i { animation: none !important; }
      .pop, .adv { animation: none !important; }
    }
    /* Results fill the card, which is as wide as the box; the picture sits
       centred at its own shape on a quiet stage. */
    .stage { display: flex; justify-content: center; align-items: center; width: 100%; border-radius: 14px; overflow: hidden;
      background: color-mix(in srgb, var(--sys-on-surface, #15171c) 5%, transparent); }
    .stage > a { line-height: 0; max-width: 100%; }
    .media { display: block; width: auto; height: auto; max-width: 100%; max-height: 440px; border-radius: 0; margin: 0 auto; }
    .stage .shimmer { height: 320px; width: auto; max-width: 100%; border-radius: 0; }
    .audio { display: block; width: 100%; }
    .audio-sk { height: 56px; display: flex; align-items: center; gap: 4px; padding: 0 18px; border-radius: 14px; }
    .audio-sk i { flex: 1; height: calc(var(--h) * 70%); border-radius: 3px; background: rgba(127, 127, 127, 0.28);
      animation: sound 900ms ease-in-out infinite alternate; transform-origin: 50% 50%; }
    .audio-sk i:nth-child(3n) { animation-delay: -300ms; } .audio-sk i:nth-child(3n+1) { animation-delay: -600ms; }
    @keyframes sound { from { transform: scaleY(0.35); } to { transform: scaleY(1); } }
    .job-note, .job-error { margin: 0 4px; font-size: 14px; line-height: 1.5; color: var(--sys-on-surface-variant, #6b7280); }
    .job-error { color: #d93025; }
    .job-actions { display: flex; flex-wrap: wrap; gap: 8px; }
    .act {
      display: inline-flex; align-items: center; gap: 6px; height: 36px; padding: 0 14px 0 10px; border: 0; border-radius: 999px;
      background: var(--gm-tonal, rgba(127, 127, 127, 0.1)); color: var(--sys-on-surface, #15171c); text-decoration: none; font-size: 13.5px; font-weight: 500; cursor: pointer;
    }
    .act:hover { background: var(--gm-tonal-hover, rgba(127, 127, 127, 0.16)); }
    .note { margin: 0 14px 4px; font-size: 13px; color: var(--sys-on-surface-variant, #6b7280); }
    .meta { font-size: 13px; color: var(--sys-on-surface-variant, #6b7280); margin-top: -6px; }

    /* Under the box, like Claude's row: quiet pills that open our own menus.
       Mode first, the type's main settings, Model at the end. */
    /* The settings under the box stay inside its width: centred on it, and
       a second centred line when they do not fit (Voice has six). */
    .under { width: 100%; box-sizing: border-box; display: flex; flex-wrap: wrap; align-items: center; justify-content: center;
      gap: 4px 6px; padding: 0 6px; min-height: 34px; }
    .under > .grow { display: none; }
    .pill {
      display: inline-flex; align-items: center; gap: 6px; height: 32px; padding: 0 8px 0 12px; border: 0; border-radius: 999px; flex: none;
      background: transparent; color: var(--sys-on-surface-variant, #5f6368); font-size: 13px; cursor: pointer; white-space: nowrap; max-width: 260px;
      transition: background 140ms ease, color 140ms ease;
    }
    .pill svg { fill: currentColor; opacity: 0.75; flex: none; }
    .pill b { font-weight: 500; color: var(--sys-on-surface, #15171c); overflow: hidden; text-overflow: ellipsis; }
    .pill .pl { opacity: 0.85; }
    .pill:hover, .pill[aria-expanded='true'] { background: var(--gm-tonal, rgba(127, 127, 127, 0.12)); }
    .pill[role='switch'] { padding-inline-end: 12px; }
    .pill[role='switch'].on b { color: var(--sys-primary, #1a73e8); }
    .pill.mode { background: var(--gm-tonal, rgba(127, 127, 127, 0.12)); padding-inline-start: 10px; }
    .pill.mode.set { background: color-mix(in srgb, var(--sys-primary, #1a73e8) 16%, transparent); color: var(--sys-on-surface, #15171c); }
    .pill.mode.set svg { opacity: 1; color: var(--sys-primary, #1a73e8); }
    .mode-wrap { display: inline-flex; align-items: center; gap: 2px; flex: none; }
    .pill-x { width: 26px; height: 26px; border: 0; border-radius: 50%; display: grid; place-items: center; cursor: pointer; padding: 0;
      background: transparent; color: var(--sys-on-surface-variant, #5f6368); }
    .pill-x svg { fill: currentColor; }
    .pill-x:hover { background: var(--gm-tonal, rgba(127, 127, 127, 0.14)); }
    .auto-tag { font-size: 11px; padding: 1px 6px; border-radius: 999px; background: color-mix(in srgb, var(--sys-primary, #1a73e8) 22%, transparent);
      color: var(--sys-on-surface, #15171c); animation: tag-in 260ms ease; }
    @keyframes tag-in { from { opacity: 0; transform: scale(0.8); } to { opacity: 1; transform: none; } }
    .pill.in-adv { background: var(--gm-tonal, rgba(127, 127, 127, 0.12)); max-width: 220px; }
    .pill.in-adv .pl { display: none; }

    /* Our dropdown: one at a time, under or above its pill, on the panel fill. */
    .pop {
      position: fixed; z-index: 60; max-height: min(360px, 60vh); overflow-y: auto; padding: 6px; border-radius: 16px;
      background: var(--gm-panel, #1d1f25); color: var(--sys-on-surface, #e8eaed);
      box-shadow: 0 16px 44px rgba(0, 0, 0, 0.32), 0 0 0 1px color-mix(in srgb, var(--sys-on-surface, #e8eaed) 8%, transparent);
      animation: pop-in 140ms ease-out;
    }
    /* Slim rounded scrollbars with no arrow buttons, kept clear of rounded corners. */
    .pop::-webkit-scrollbar, .jobs-list::-webkit-scrollbar { width: 10px; }
    .pop::-webkit-scrollbar-button, .jobs-list::-webkit-scrollbar-button { display: none; width: 0; height: 0; }
    .pop::-webkit-scrollbar-track, .jobs-list::-webkit-scrollbar-track { background: transparent; margin-block: 12px; }
    .pop::-webkit-scrollbar-thumb, .jobs-list::-webkit-scrollbar-thumb { border: 3px solid transparent; border-radius: 999px;
      background: var(--gm-scroll-thumb, rgba(127, 127, 127, 0.35)) padding-box; }
    @supports not selector(::-webkit-scrollbar) { .pop, .jobs-list { scrollbar-width: thin; } }
    .pop.up { animation-name: pop-up; }
    @keyframes pop-in { from { opacity: 0; transform: translateY(-4px); } to { opacity: 1; transform: none; } }
    @keyframes pop-up { from { opacity: 0; transform: translateY(4px); } to { opacity: 1; transform: none; } }
    .pop-title { padding: 6px 10px 4px; font-size: 12px; color: var(--sys-on-surface-variant, #9aa0a6); }
    .pop button {
      width: 100%; display: flex; align-items: center; gap: 10px; min-height: 38px; padding: 6px 10px; border: 0; border-radius: 10px;
      background: transparent; color: inherit; text-align: start; cursor: pointer; font-size: 14px;
    }
    .pop button svg { fill: currentColor; flex: none; opacity: 0.8; }
    .pop button:hover, .pop button:focus-visible { background: var(--gm-tonal, rgba(127, 127, 127, 0.14)); outline: none; }
    .pop button:disabled { opacity: 0.45; cursor: default; }
    .pop-l { flex: 1; min-width: 0; display: flex; flex-direction: column; }
    .pop-l small { font-size: 12px; color: var(--sys-on-surface-variant, #9aa0a6); overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
    .pop-sep { height: 1px; margin: 5px 8px; background: color-mix(in srgb, var(--sys-on-surface, #e8eaed) 10%, transparent); }
    .plus { position: relative; }
    .plus.dot-on::after { content: ''; position: absolute; top: 9px; inset-inline-end: 9px; width: 8px; height: 8px; border-radius: 50%; background: var(--sys-primary, #1a73e8); }

    /* Advanced settings: a card above the box. */
    .adv {
      width: 100%; display: flex; flex-direction: column; gap: 4px; padding: 10px 12px 12px; border-radius: 22px;
      background: var(--gm-panel, #1d1f25); box-shadow: 0 10px 34px rgba(0, 0, 0, 0.22); animation: pop-up 180ms ease-out;
    }
    .adv-head { display: flex; align-items: center; gap: 8px; padding: 0 2px 4px 6px; font-size: 14px; }
    .adv-head span { flex: 1; color: var(--sys-on-surface-variant, #6b7280); font-size: 13px; }
    .adv-list { display: grid; grid-template-columns: repeat(auto-fill, minmax(240px, 1fr)); gap: 4px 12px; }
    .adv-row { display: flex; align-items: center; justify-content: space-between; gap: 10px; min-height: 44px; padding: 4px 6px; border-radius: 12px; }
    .adv-row.wide { grid-column: 1 / -1; flex-direction: column; align-items: stretch; }
    .adv-l { display: flex; flex-direction: column; font-size: 14px; }
    .adv-l small { font-size: 12px; color: var(--sys-on-surface-variant, #6b7280); }
    .field { width: 100%; border: 0; border-radius: 12px; padding: 9px 12px; font: inherit; font-size: 14px; color: inherit; resize: vertical;
      background: var(--gm-field-bg, var(--gm-tonal, rgba(127, 127, 127, 0.12))); }
    .adv-row:not(.wide) .field { width: 120px; }
    .field:focus { outline: 2px solid var(--sys-primary, #1a5fd8); outline-offset: 0; }
    .switch { position: relative; width: 40px; height: 24px; flex: none; border: 0; border-radius: 999px; padding: 0; cursor: pointer;
      background: var(--gm-tonal-hover, rgba(127, 127, 127, 0.28)); transition: background 160ms ease; }
    .switch i { position: absolute; top: 3px; left: 3px; width: 18px; height: 18px; border-radius: 50%; background: #fff; transition: transform 160ms ease; }
    .switch.on { background: var(--sys-primary, #1a73e8); }
    .switch.on i { transform: translateX(16px); }
    :host-context([dir='rtl']) .switch.on i { transform: translateX(-16px); }
    .reset { align-self: flex-start; margin: 4px 0 0 4px; height: 32px; }

    /* Attachments show which slot they fill (first frame, reference...). */
    .file video { width: 100%; height: 100%; object-fit: cover; display: block; }
    .file-slot { position: absolute; left: 3px; right: 3px; bottom: 3px; height: 18px; border: 0; border-radius: 6px; padding: 0 4px;
      font-size: 10.5px; line-height: 18px; color: #fff; background: rgba(0, 0, 0, 0.62); cursor: pointer; white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }
    .file-slot:disabled { cursor: default; }

    /* Type cards on the empty page: media behind the name, alive on hover. */
    .cards { width: 100%; display: grid; grid-template-columns: repeat(5, minmax(0, 1fr)); gap: 10px; margin-top: clamp(10px, 2.4vh, 22px); }
    .card {
      position: relative; isolation: isolate; overflow: hidden; height: 112px; padding: 0; border: 0; border-radius: 20px; cursor: pointer;
      text-align: start; color: #fff; background: #15171c;
      box-shadow: 0 0 0 1px color-mix(in srgb, var(--sys-on-surface, #e8eaed) 8%, transparent), 0 6px 20px rgba(0, 0, 0, 0.12);
      transition: transform 220ms cubic-bezier(0.2, 0.8, 0.2, 1), box-shadow 220ms ease;
    }
    .card-media, .card-media > span { position: absolute; inset: 0; }
    .card-media { z-index: -1; }
    .card-media > span { background-size: cover; background-position: center; transition: opacity 320ms ease, transform 600ms cubic-bezier(0.2, 0.8, 0.2, 1); }
    .still { opacity: 0.55; transform: scale(1.02); }
    .moving { opacity: 0; }
    .k-image .still { background-position: 90% 10%; background-size: 260%; }
    /* A scrim keeps the white name readable on any picture. */
    .card-media::after { content: ''; position: absolute; inset: 0;
      background: linear-gradient(180deg, rgba(0, 0, 0, 0.05) 0%, rgba(0, 0, 0, 0.25) 45%, rgba(0, 0, 0, 0.72) 100%); }
    .card:hover, .card:focus-visible { transform: translateY(-2px);
      box-shadow: 0 0 0 1px color-mix(in srgb, var(--sys-on-surface, #e8eaed) 14%, transparent), 0 14px 32px rgba(0, 0, 0, 0.24); }
    .card:hover .still, .card:focus-visible .still, .card.on .still { opacity: 1; transform: scale(1.08); }
    .card:hover .moving, .card:focus-visible .moving, .card.on .moving { opacity: 1; }
    .card.on { box-shadow: 0 0 0 2px var(--sys-primary, #8ab4f8), 0 14px 32px rgba(0, 0, 0, 0.24); }
    .card:focus-visible { outline: 2px solid var(--sys-primary, #8ab4f8); outline-offset: 3px; }
    /* Sound tiles, each its own thin-line style (Live keeps its five centred bars):
       Music = a spectrum rising from one baseline, Voice = flowing waves. */
    .viz { opacity: 0; }
    .card:hover .viz, .card:focus-visible .viz, .card.on .viz { opacity: 1; }
    .eq { display: flex; align-items: flex-end; justify-content: center; gap: 4px; padding: 18px 14% 50px; }
    .eq i { flex: none; width: 2px; height: calc(var(--h) * 100%); border-radius: 2px; background: rgba(255, 255, 255, 0.92);
      transform-origin: 50% 100%; transform: scaleY(0.2); }
    .card:hover .eq i, .card:focus-visible .eq i, .card.on .eq i { animation: eq-rise var(--d) ease-in-out var(--o) infinite alternate; }
    @keyframes eq-rise { from { transform: scaleY(0.15); } to { transform: scaleY(1); } }
    .wave { padding: 14px 6% 46px; -webkit-mask-image: linear-gradient(90deg, transparent, #000 22%, #000 78%, transparent);
      mask-image: linear-gradient(90deg, transparent, #000 22%, #000 78%, transparent); }
    .wave svg { display: block; width: 100%; height: 100%; overflow: hidden; }
    .wave path { fill: none; stroke-width: 2; stroke-linecap: round; vector-effect: non-scaling-stroke; }
    .wave .w1 path { stroke: rgba(255, 255, 255, 0.95); }
    .wave .w2 path { stroke: #8ab4f8; opacity: 0.75; }
    .wave .w3 path { stroke: #c58af9; opacity: 0.6; }
    .wave .breathe { transform-box: view-box; transform-origin: 50% 50%; transform: scaleY(0.25); }
    .card:hover .wave .flow, .card:focus-visible .wave .flow, .card.on .wave .flow { animation: wave-flow var(--s) linear infinite; }
    .card:hover .wave .breathe, .card:focus-visible .wave .breathe, .card.on .wave .breathe { animation: wave-breathe 2.4s ease-in-out infinite; }
    .wave .w2 { animation-delay: -0.8s !important; } .wave .w3 { animation-delay: -1.6s !important; }
    @keyframes wave-flow { to { transform: translateX(var(--p)); } }
    @keyframes wave-breathe { 0%, 100% { transform: scaleY(0.35); } 50% { transform: scaleY(1); } }
    .card-text { position: absolute; inset: auto 0 0 0; display: flex; flex-direction: column; gap: 1px; padding: 12px 14px; }
    .card-name { display: inline-flex; align-items: center; gap: 7px; font-size: 15px; font-weight: 600; letter-spacing: -0.005em; }
    .card-name svg { fill: currentColor; flex: none; }
    .card-name svg:last-child:not(:first-child) { opacity: 0.7; margin-inline-start: auto; }
    .card-desc { font-size: 12.5px; color: rgba(255, 255, 255, 0.78); white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }

    /* How it is made: four steps above the box, joined by moving dots. */
    .path { list-style: none; margin: 0 0 2px; padding: 0 6px; width: 100%; display: flex; align-items: center; justify-content: center; gap: 0; }
    .pstep { display: inline-flex; align-items: center; gap: 8px; min-width: 0; padding: 6px 12px 6px 6px; border-radius: 999px;
      background: color-mix(in srgb, var(--gm-panel, #1d1f25) 72%, transparent); box-shadow: 0 0 0 1px color-mix(in srgb, var(--sys-on-surface, #e8eaed) 7%, transparent);
      animation: step-in 320ms cubic-bezier(0.2, 0.8, 0.2, 1) both; animation-delay: calc(var(--i) * 70ms); }
    .pstep.main { background: color-mix(in srgb, var(--sys-primary, #8ab4f8) 14%, var(--gm-panel, #1d1f25)); }
    .pdot { width: 26px; height: 26px; flex: none; display: grid; place-items: center; border-radius: 50%;
      background: var(--gm-tonal, rgba(127, 127, 127, 0.14)); color: var(--sys-on-surface-variant, #9aa0a6); }
    .pstep.main .pdot { background: linear-gradient(135deg, #4f8df7, #9b6cf6); color: #fff; }
    .pdot svg { fill: currentColor; }
    .ptext { display: flex; flex-direction: column; min-width: 0; line-height: 1.2; }
    .ptext b { font-size: 12.5px; font-weight: 500; color: var(--sys-on-surface, #15171c); white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }
    .ptext small { font-size: 11.5px; color: var(--sys-on-surface-variant, #6b7280); white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }
    .link { flex: 0 1 34px; min-width: 14px; height: 2px; position: relative; overflow: hidden;
      background: color-mix(in srgb, var(--sys-on-surface, #e8eaed) 12%, transparent); }
    .link i { position: absolute; inset: 0; width: 40%; background: linear-gradient(90deg, transparent, var(--sys-primary, #8ab4f8), transparent);
      animation: flow 1.6s linear infinite; }
    :host-context([dir='rtl']) .link i { animation-direction: reverse; }
    @keyframes flow { from { transform: translateX(-100%); } to { transform: translateX(250%); } }

    /* Ghost text: a copy of the text behind the box, with the suggestion. */
    .ta-wrap { position: relative; }
    .gh, .ta-wrap textarea { font: inherit; font-size: 17px; line-height: 24px; padding: 14px 14px 4px; letter-spacing: normal; }
    .gh { position: absolute; inset: 0; overflow: hidden; white-space: pre-wrap; overflow-wrap: break-word; pointer-events: none; color: transparent; unicode-bidi: plaintext; }
    .ta-wrap textarea { position: relative; z-index: 1; }
    .g-typed { color: transparent; }
    .g-sug { color: var(--sys-on-surface-variant, #6b7280); opacity: 0.75; }
    .sr { position: absolute; width: 1px; height: 1px; margin: -1px; overflow: hidden; clip: rect(0 0 0 0); white-space: nowrap; }
    /* "Hint: Say what to make…" / "Format: Subject · setting · light" beside the + button. */
    .hint { display: inline-flex; align-items: center; gap: 5px; min-width: 0; margin-inline-start: 4px; font-size: 12.5px;
      color: var(--sys-on-surface-variant, #6b7280); opacity: 0; transform: translateY(2px); transition: opacity 180ms ease, transform 180ms ease; white-space: nowrap; overflow: hidden; }
    .hint.shown { opacity: 1; transform: none; }
    .hint .hl { font-weight: 600; flex: none; }
    .hint .how { overflow: hidden; text-overflow: ellipsis; opacity: 0.8; }
    /* The example (or suggestion) ends in a quiet Tab key, same tone as the text. */
    .g-ex { color: var(--sys-on-surface-variant, #6b7280); opacity: 0.9; }
    .g-key { display: inline-block; vertical-align: 2px; margin-inline-start: 8px; padding: 0 6px; border-radius: 6px;
      font: inherit; font-size: 11px; font-weight: 600; line-height: 18px; letter-spacing: 0.02em;
      color: var(--sys-on-surface-variant, #6b7280); opacity: 0.9;
      background: color-mix(in srgb, var(--sys-on-surface-variant, #6b7280) 16%, transparent);
      animation: key-in 260ms cubic-bezier(0.2, 0.8, 0.2, 1) both; }
    .g-sug + .g-key { opacity: 0.75; }
    @keyframes key-in { from { opacity: 0; transform: translateY(4px) scale(0.9); } }

    /* Enhance slides in once there is text; Live and Send share one slot. */
    .enh { transition: width 220ms cubic-bezier(0.2, 0.8, 0.2, 1), opacity 180ms ease, transform 220ms cubic-bezier(0.2, 0.8, 0.2, 1), margin 220ms ease; }
    .enh:not(.shown) { width: 0; opacity: 0; transform: scale(0.5); margin-inline-end: -6px; pointer-events: none; overflow: hidden; }
    .slot { position: relative; width: 40px; height: 40px; flex: none; }
    .slot > .send, .slot > .live { position: absolute; inset: 0; transition: opacity 200ms ease, transform 260ms cubic-bezier(0.2, 0.8, 0.2, 1); }
    .slot.live-on > .send { opacity: 0; transform: scale(0.6) rotate(-45deg); pointer-events: none; }
    .slot.send-on > .live { opacity: 0; transform: scale(0.6); pointer-events: none; }
    svg.stroke-i { fill: none !important; stroke: currentColor; stroke-width: 1.8; stroke-linecap: round; stroke-linejoin: round; }
    svg.stroke, svg.stroke path { fill: none !important; stroke: currentColor; stroke-width: 2.2; stroke-linecap: round; stroke-linejoin: round; }
    @media (prefers-reduced-motion: reduce) {
      .enh, .slot > .send, .slot > .live, .hint, .card, .card-media > span { transition: none !important; }
      .link i, .eq i, .wave .flow, .wave .breathe, .pstep, .g-key { animation: none !important; }
      .eq i { transform: scaleY(0.6); } .wave .breathe { transform: scaleY(0.7); }
    }

    /* The chat's thinking: live steps, folded to one line when done. */
    .think { font-size: 14px; color: var(--sys-on-surface-variant, #6b7280); }
    .think summary { display: inline-flex; align-items: center; gap: 8px; cursor: pointer; list-style: none; padding: 4px 10px 4px 8px; margin-inline-start: -8px;
      border-radius: 999px; user-select: none; }
    .think summary::-webkit-details-marker { display: none; }
    .think summary:hover { background: var(--gm-tonal, rgba(127, 127, 127, 0.1)); }
    .think summary svg { fill: currentColor; }
    .think summary svg:last-child { transition: transform 160ms ease; opacity: 0.7; }
    .think[open] summary svg:last-child { transform: rotate(180deg); }
    .think.live summary span:first-of-type { background: linear-gradient(90deg, var(--sys-on-surface-variant, #6b7280) 0%, var(--sys-on-surface, #15171c) 50%, var(--sys-on-surface-variant, #6b7280) 100%);
      background-size: 200% 100%; -webkit-background-clip: text; background-clip: text; color: transparent; animation: shim 1.6s linear infinite; }
    .think-n { min-width: 20px; height: 20px; padding: 0 6px; border-radius: 999px; display: grid; place-items: center; font-size: 11.5px; background: var(--gm-tonal, rgba(127, 127, 127, 0.14)); }
    .think-dots { display: inline-flex; gap: 3px; }
    .think-dots i { width: 4px; height: 4px; border-radius: 50%; background: currentColor; animation: blink 1.2s infinite both; }
    .think-dots i:nth-child(2) { animation-delay: 0.15s; } .think-dots i:nth-child(3) { animation-delay: 0.3s; }
    .think-list { list-style: none; margin: 6px 0 2px; padding: 0 0 0 4px; display: flex; flex-direction: column; gap: 8px;
      border-inline-start: 2px solid var(--gm-tonal, rgba(127, 127, 127, 0.16)); padding-inline-start: 12px; }
    .think-list li { display: flex; gap: 8px; align-items: flex-start; animation: step-in 240ms ease-out; }
    @keyframes step-in { from { opacity: 0; transform: translateY(4px); } to { opacity: 1; transform: none; } }
    .think-list li svg { fill: #1e8e3e; flex: none; margin-top: 3px; }
    .think-list li > i { width: 10px; height: 10px; margin: 5px 2px 0; border-radius: 50%; flex: none; background: var(--sys-primary, #1a73e8); animation: pulse 900ms ease-in-out infinite alternate; }
    .think-list span { display: flex; flex-direction: column; gap: 2px; min-width: 0; }
    .think-list b { font-weight: 500; color: var(--sys-on-surface, #15171c); }
    .think-list small { font-size: 13px; line-height: 1.45; white-space: pre-wrap; overflow-wrap: anywhere; }

    /* A job's steps (the studios' progress card): stages, timer, estimate bar. */
    .prog { font-size: 13.5px; color: var(--sys-on-surface-variant, #6b7280); padding: 0 4px; }
    .prog summary { display: flex; align-items: center; gap: 10px; cursor: pointer; list-style: none; padding: 2px 0; }
    .prog summary::-webkit-details-marker { display: none; }
    .prog-t { flex: 1; color: var(--sys-on-surface, #15171c); font-weight: 500; }
    .prog.live .prog-t { animation: pulse 900ms ease-in-out infinite alternate; }
    .prog-time, .prog-n { font-variant-numeric: tabular-nums; font-size: 12.5px; }
    .bar { height: 4px; margin: 6px 0 8px; border-radius: 999px; overflow: hidden; background: var(--gm-tonal, rgba(127, 127, 127, 0.16)); }
    .bar i { display: block; height: 100%; border-radius: inherit; background: var(--sys-primary, #1a73e8); transition: width 900ms linear;
      background-image: linear-gradient(90deg, transparent, rgba(255, 255, 255, 0.35), transparent); background-size: 60% 100%; background-repeat: no-repeat;
      animation: bar-glint 1.6s linear infinite; }
    @keyframes bar-glint { from { background-position: -60% 0; } to { background-position: 160% 0; } }
    .stages { list-style: none; margin: 4px 0 2px; padding: 0; display: flex; flex-wrap: wrap; gap: 6px 16px; }
    .stages.tasks { flex-direction: column; gap: 4px; }
    .st { display: inline-flex; align-items: center; gap: 6px; }
    .st i { width: 8px; height: 8px; border-radius: 50%; background: rgba(127, 127, 127, 0.35); flex: none; margin: 0 3px; }
    .st svg { fill: #1e8e3e; flex: none; }
    .st.done { color: var(--sys-on-surface, #15171c); }
    .st.now { color: var(--sys-on-surface, #15171c); font-weight: 500; }
    .st.now i { background: var(--sys-primary, #1a73e8); animation: pulse 900ms ease-in-out infinite alternate; }
    .st.bad i { background: #d93025; }
    .st.more { opacity: 0.7; padding-inline-start: 20px; }
    .avatar.busy { animation: pulse 900ms ease-in-out infinite alternate; }

    @media (max-width: 600px) {
      .under { flex-wrap: nowrap; justify-content: flex-start; overflow-x: auto; scrollbar-width: none; padding: 0 2px; }
      .under::-webkit-scrollbar { display: none; }
      .note { margin-inline-start: 8px; }
      .adv-row:not(.wide) .field { width: 96px; }
    }
    /* The buttons above the box float over the thread: give them the box's fill. */
    .dock-top .ghost, .dock-top .jobs-pill { background: var(--gm-panel, #1d1f25); box-shadow: 0 4px 14px rgba(0, 0, 0, 0.14); }
    .dock-top .ghost:hover, .dock-top .jobs-pill:hover { filter: brightness(1.06); }
    /* Film steps on a story job's card. */
    .steps { list-style: none; margin: 0; padding: 0 4px; display: flex; flex-wrap: wrap; gap: 4px 14px; font-size: 13px; color: var(--sys-on-surface-variant, #6b7280); }
    .step { display: inline-flex; align-items: center; gap: 6px; }
    .step i { width: 8px; height: 8px; border-radius: 50%; background: rgba(127, 127, 127, 0.35); flex: none; }
    .step.done { color: var(--sys-on-surface, #15171c); }
    .step.done i { background: #1e8e3e; }
    .step.now { color: var(--sys-on-surface, #15171c); font-weight: 500; }
    .step.now i { background: var(--sys-primary, #1a73e8); animation: pulse 900ms ease-in-out infinite alternate; }
    .step.bad i { background: #d93025; }
    .act:disabled, .pa:disabled { opacity: 0.5; cursor: default; }
    /* In the thread, results stay small; the jobs panel holds the rest. */

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
    .jobs-list { list-style: none; margin: 0; padding: 4px 10px 12px; overflow-y: auto; display: flex; flex-direction: column; gap: 10px; flex: 1; }
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
      .gh, .ta-wrap textarea { font-size: 16px; padding: 10px 8px 4px; }
      .hint { font-size: 12px; }
      .cards { display: flex; overflow-x: auto; scroll-snap-type: x mandatory; scrollbar-width: none; padding: 2px 2px 6px; margin-inline: -2px; }
      .cards::-webkit-scrollbar { display: none; }
      /* No soft shadow in the scrolling row: it gets clipped into a grey band. */
      .card, .card:hover, .card:focus-visible { flex: 0 0 42%; height: 96px; scroll-snap-align: start;
        box-shadow: 0 0 0 1px color-mix(in srgb, var(--sys-on-surface, #e8eaed) 10%, transparent); transform: none; }
      .card.on { box-shadow: 0 0 0 2px var(--sys-primary, #8ab4f8); }
      /* The path fits a phone: the model step keeps its words, the rest are icons. */
      .pstep:not(.main) { padding: 4px; }
      .pstep:not(.main) .ptext { position: absolute; width: 1px; height: 1px; overflow: hidden; clip: rect(0 0 0 0); white-space: nowrap; }
      .link { flex-basis: 18px; }
      .bubble { max-width: 88%; }
    }
  `;
}

if (!customElements.get('gm-home-chat')) customElements.define('gm-home-chat', GmHomeChat);
