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
 * <gm-prompt-tools>: the same prompt buttons as Home's box, for any textarea.
 *
 *   [Enhance] [Mic] [Live | Send]
 *
 * - Enhance slides in once there is text. It rewrites the prompt through
 *   /api/prompts/enhance and types the result in with insertText, so Ctrl+Z
 *   brings the old prompt back. Until the text is edited again the button
 *   turns into Undo, which does the same.
 * - Mic: browser speech-to-text, typed in the same undoable way.
 * - Live shows while the box is empty. With `send`, the Send button takes its
 *   place once there is text (one round slot, cross-faded); without it, Live
 *   just fades out.
 *
 * It renders in the light DOM so the composer's prompt_keys.js sees the Send
 * button (.gm-composer-send) and sends the typed value. Mesop's on_blur stores
 * the edits as usual; Story Studio's idea watcher reads the input events.
 */
import { LitElement, html, nothing } from '/ui/vendor/lit-3.2.1.js';

const Recognition = window.SpeechRecognition || window.webkitSpeechRecognition;

const P = {
  enhance: 'M19 9l1.25-2.75L23 5l-2.75-1.25L19 1l-1.25 2.75L15 5l2.75 1.25L19 9zm-7.5.5L9 4 6.5 9.5 1 12l5.5 2.5L9 20l2.5-5.5L17 12l-5.5-2.5zM19 15l-1.25 2.75L15 19l2.75 1.25L19 23l1.25-2.75L23 19l-2.75-1.25L19 15z',
  undo: 'M12.5 8c-2.65 0-5.05.99-6.9 2.6L2 7v9h9l-3.62-3.62c1.39-1.16 3.16-1.88 5.12-1.88 3.54 0 6.55 2.31 7.6 5.5l2.37-.78C21.08 11.03 17.15 8 12.5 8z',
  mic: 'M12 14a3 3 0 0 0 3-3V5a3 3 0 0 0-6 0v6a3 3 0 0 0 3 3zm5-3a5 5 0 0 1-10 0H5a7 7 0 0 0 6 6.92V21h2v-3.08A7 7 0 0 0 19 11z',
  stop: 'M7 7h10v10H7z',
};
const icon = (d) => html`<svg viewBox="0 0 24 24" width="20" height="20" aria-hidden="true"><path d=${d}></path></svg>`;
const SEND = html`<svg viewBox="0 0 24 24" width="20" height="20" aria-hidden="true" class="gpt-stroke"><path d="M12 19.5V5M5.5 11.25 12 4.75l6.5 6.5"></path></svg>`;

const CSS = `
gm-prompt-tools { display: inline-flex; flex: none; }
.gpt { display: flex; align-items: center; gap: 6px; }
.gpt-btn, .gpt .gpt-send {
  width: 40px; height: 40px; flex: none; display: inline-flex; align-items: center; justify-content: center; padding: 0;
  border: 0; border-radius: 50%; cursor: pointer; font: inherit; color: var(--sys-on-surface-variant, #4b515d); background: transparent;
  transition: background-color 140ms ease, color 140ms ease;
}
.gpt-btn svg, .gpt-send svg { fill: currentColor; display: block; }
.gpt-btn:hover:not(:disabled) { background: var(--gm-tonal-hover, rgba(127, 127, 127, 0.14)); color: var(--sys-on-surface, #15171c); }
.gpt-btn:focus-visible, .gpt-send:focus-visible { outline: 2px solid var(--sys-primary, #1a5fd8); outline-offset: 2px; }
.gpt-btn.on { background: #d93025; color: #fff; }
.gpt-btn.undo { color: var(--sys-primary, #1a5fd8); }
.gpt-btn.working svg { animation: gpt-pulse 900ms ease-in-out infinite alternate; }
@keyframes gpt-pulse { from { opacity: 0.35; } to { opacity: 1; } }
.gpt .gpt-send { color: var(--sys-on-primary, #fff); background: var(--sys-primary, #1a73e8);
  box-shadow: 0 2px 10px color-mix(in srgb, var(--sys-primary, #1a73e8) 35%, transparent); }
.gpt .gpt-send:hover:not(:disabled) { filter: brightness(1.08); }
.gpt .gpt-send.off { background: var(--gm-tonal, rgba(127, 127, 127, 0.14)); color: var(--sys-on-surface-variant, #6b7280); box-shadow: none; cursor: default; }
.gpt-stroke, .gpt-stroke path { fill: none !important; stroke: currentColor; stroke-width: 2.2; stroke-linecap: round; stroke-linejoin: round; }
.gpt-spin { width: 20px; height: 20px; border-radius: 50%; border: 2.5px solid rgba(255, 255, 255, 0.4); border-top-color: #fff;
  animation: gpt-rot 800ms linear infinite; box-sizing: border-box; }
@keyframes gpt-rot { to { transform: rotate(360deg); } }
/* Enhance (and Live without Send) slide in and out instead of jumping. */
.gpt-fold { transition: width 220ms cubic-bezier(0.2, 0.8, 0.2, 1), opacity 180ms ease, transform 220ms cubic-bezier(0.2, 0.8, 0.2, 1), margin 220ms ease; }
.gpt-fold.gone { width: 0 !important; opacity: 0; transform: scale(0.5); margin-inline-end: -6px; pointer-events: none; overflow: hidden; }
.gpt-slot { position: relative; width: 40px; height: 40px; flex: none; }
.gpt-slot > .gpt-send, .gpt-slot > live-call-button { position: absolute; inset: 0; transition: opacity 200ms ease, transform 260ms cubic-bezier(0.2, 0.8, 0.2, 1); }
.gpt-slot.live-on > .gpt-send { opacity: 0; transform: scale(0.6) rotate(-45deg); pointer-events: none; }
.gpt-slot.send-on > live-call-button { opacity: 0; transform: scale(0.6); pointer-events: none; }
.gpt live-call-button.gpt-fold { width: 40px; height: 40px; }
@media (max-width: 600px) {
  .gpt-btn, .gpt .gpt-send, .gpt-slot { width: 44px; height: 44px; }
}
@media (prefers-reduced-motion: reduce) {
  .gpt-fold, .gpt-slot > *, .gpt-btn { transition: none !important; }
  .gpt-btn.working svg, .gpt-spin { animation: none !important; }
}
`;

function injectStyles() {
  if (document.getElementById('gm-prompt-tools-css')) return;
  const s = document.createElement('style');
  s.id = 'gm-prompt-tools-css';
  s.textContent = CSS;
  document.head.appendChild(s);
}

/** Replace the whole box with `text` as one undoable edit (Ctrl+Z restores). */
export function replaceText(ta, text) {
  ta.focus();
  ta.select();
  let ok = false;
  try { ok = document.execCommand('insertText', false, text); } catch (_) { ok = false; }
  if (!ok || ta.value !== text) {
    ta.value = text;
    ta.dispatchEvent(new Event('input', { bubbles: true }));
  }
  ta.setSelectionRange(text.length, text.length);
}

class GmPromptTools extends LitElement {
  static properties = {
    scope: { type: String }, // ancestor that holds the textarea
    field: { type: String }, // the textarea inside it
    kind: { type: String }, // image | video | music | voice | film
    live: { type: Boolean },
    send: { type: Boolean },
    enhance: { type: Boolean },
    dictation: { type: Boolean },
    busy: { type: Boolean },
    stringsJson: { type: String },
    talkJson: { type: String },
    _hasText: { state: true },
    _enhancing: { state: true },
    _listening: { state: true },
    _undo: { state: true },
  };

  constructor() {
    super();
    this.scope = '.gm-composer';
    this.field = 'textarea';
    this.kind = '';
    this.live = false;
    this.send = false;
    this.enhance = true;
    this.dictation = true;
    this.busy = false;
    this.stringsJson = '{}';
    this.talkJson = '{}';
    this._hasText = false;
    this._enhancing = false;
    this._listening = false;
    this._undo = null; // { before, after } while the enhanced text is untouched
    this._rec = null;
    this._sync = () => this._check();
  }

  createRenderRoot() {
    injectStyles();
    return this;
  }

  connectedCallback() {
    super.connectedCallback();
    this._root = this.closest(this.scope) || this.parentElement;
    if (this._root) {
      this._root.addEventListener('input', this._sync);
      this._root.addEventListener('focusin', this._sync);
    }
    // Mesop can set the value without an input event (history, page reloads).
    this._timer = setInterval(this._sync, 500);
    requestAnimationFrame(this._sync);
  }

  disconnectedCallback() {
    super.disconnectedCallback();
    if (this._root) {
      this._root.removeEventListener('input', this._sync);
      this._root.removeEventListener('focusin', this._sync);
    }
    clearInterval(this._timer);
    if (this._rec) try { this._rec.stop(); } catch (_) { /* ignore */ }
  }

  get _s() {
    try { return JSON.parse(this.stringsJson || '{}'); } catch (_) { return {}; }
  }

  _ta() {
    return this._root ? this._root.querySelector(this.field) : null;
  }

  _check() {
    const ta = this._ta();
    const v = ta ? ta.value : '';
    const has = !!v.trim();
    if (has !== this._hasText) this._hasText = has;
    // Any edit after an enhance ends the Undo state (Ctrl+Z still works).
    if (this._undo && v !== this._undo.after) this._undo = null;
  }

  async _onEnhance() {
    const ta = this._ta();
    if (!ta || this._enhancing) return;
    if (this._undo && ta.value === this._undo.after) {
      const { before } = this._undo;
      this._undo = null;
      replaceText(ta, before);
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
        body: JSON.stringify({ prompt: text, kind: this.kind || '' }),
      });
      if (r.ok) {
        const body = await r.json();
        // Only if they didn't keep typing while it worked.
        if (body.prompt && ta.value === before && body.prompt !== before) {
          replaceText(ta, body.prompt);
          this._undo = { before, after: ta.value };
        }
      }
    } catch (_) { /* keep their words */ }
    this._enhancing = false;
  }

  _onMic() {
    if (!Recognition) return;
    if (this._listening) { try { this._rec.stop(); } catch (_) { /* ignore */ } return; }
    const ta = this._ta();
    if (!ta) return;
    const rec = new Recognition();
    rec.lang = document.documentElement.lang === 'ar' ? 'ar-QA' : (navigator.language || 'en-US');
    rec.interimResults = false;
    rec.continuous = true;
    rec.onresult = (ev) => {
      let said = '';
      for (let i = ev.resultIndex; i < ev.results.length; i += 1) if (ev.results[i].isFinal) said += ev.results[i][0].transcript;
      said = said.trim();
      if (!said) return;
      ta.focus();
      const end = ta.value.length;
      ta.setSelectionRange(end, end);
      const piece = ta.value.trim() ? ` ${said}` : said;
      let ok = false;
      try { ok = document.execCommand('insertText', false, piece); } catch (_) { ok = false; }
      if (!ok) { ta.value += piece; ta.dispatchEvent(new Event('input', { bubbles: true })); }
    };
    rec.onend = () => {
      this._listening = false;
      this._rec = null;
      // Let Mesop store what was said, as if the box had been left.
      ta.dispatchEvent(new FocusEvent('blur'));
    };
    rec.onerror = () => { this._listening = false; };
    this._rec = rec;
    this._listening = true;
    try { rec.start(); } catch (_) { this._listening = false; }
  }

  render() {
    const S = this._s;
    const has = this._hasText;
    const undo = !!this._undo;
    const enhLabel = this._enhancing ? (S.enhancing || 'Enhancing…') : undo ? (S.undo_enhance || 'Undo enhance') : (S.enhance || 'Enhance prompt');
    const micLabel = this._listening ? (S.dictate_stop || 'Stop dictation') : (S.dictate || 'Dictate');
    const sendLabel = this.busy ? (S.generating || 'Generating') : (S.send || 'Send');
    const showLive = this.live && !has && !this.busy;
    const keep = (e) => e.preventDefault(); // keep focus (and the undo history) in the box
    const enh = this.enhance ? html`<button type="button" class="gpt-btn gpt-fold ${has ? '' : 'gone'} ${this._enhancing ? 'working' : ''} ${undo ? 'undo' : ''}"
        @mousedown=${keep} @click=${this._onEnhance} ?disabled=${this._enhancing || !has}
        tabindex=${has ? '0' : '-1'} aria-hidden=${has ? 'false' : 'true'} aria-label=${enhLabel} title=${enhLabel}>
        ${icon(undo ? P.undo : P.enhance)}</button>` : nothing;
    const mic = this.dictation && Recognition ? html`<button type="button" class="gpt-btn ${this._listening ? 'on' : ''}"
        @mousedown=${keep} @click=${this._onMic} aria-pressed=${this._listening ? 'true' : 'false'}
        aria-label=${micLabel} title=${micLabel}>${icon(this._listening ? P.stop : P.mic)}</button>` : nothing;
    let tail = nothing;
    if (this.send) {
      tail = html`<div class="gpt-slot ${showLive ? 'live-on' : 'send-on'}">
        <button type="button" class="gpt-send gm-composer-send ${has || this.busy ? '' : 'off'}"
          ?disabled=${this.busy || !has} tabindex=${showLive ? '-1' : '0'} aria-hidden=${showLive ? 'true' : 'false'}
          aria-label=${sendLabel} title=${sendLabel}>${this.busy ? html`<span class="gpt-spin" aria-hidden="true"></span>` : SEND}</button>
        ${this.live ? html`<live-call-button pill filled .stringsJson=${this.talkJson} ?inert=${!showLive} aria-hidden=${showLive ? 'false' : 'true'}></live-call-button>` : nothing}
      </div>`;
    } else if (this.live) {
      tail = html`<live-call-button class="gpt-fold ${showLive ? '' : 'gone'}" pill filled .stringsJson=${this.talkJson}
        ?inert=${!showLive} aria-hidden=${showLive ? 'false' : 'true'}></live-call-button>`;
    }
    return html`<div class="gpt">${enh}${mic}${tail}</div>`;
  }
}

if (!customElements.get('gm-prompt-tools')) customElements.define('gm-prompt-tools', GmPromptTools);
