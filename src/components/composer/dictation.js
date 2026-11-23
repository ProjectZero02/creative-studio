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
 * <gm-dictation>: the mic button next to Send in the composer.
 *
 * Plain speech-to-text with the browser's SpeechRecognition: what you say is
 * typed into the composer's prompt box. The box is a Mesop native textarea, so
 * after each final phrase we fire `input` and `blur` on it; Mesop's blur
 * handler then stores the text in page state like a normal edit. Browsers
 * without speech recognition (Firefox) get no button.
 */
import { LitElement, css, html } from '/ui/vendor/lit-3.2.1.js';

const Recognition = window.SpeechRecognition || window.webkitSpeechRecognition;

class GmDictation extends LitElement {
  static properties = {
    label: { type: String },
    stopLabel: { type: String },
    _on: { state: true },
  };

  constructor() {
    super();
    this.label = 'Dictate';
    this.stopLabel = 'Stop dictation';
    this._on = false;
    this._rec = null;
  }

  disconnectedCallback() {
    super.disconnectedCallback();
    this._stop();
  }

  _field() {
    const card = this.closest('.gm-composer');
    return card ? card.querySelector('.gm-composer-field textarea') : null;
  }

  _write(text, commit) {
    const ta = this._field();
    if (!ta) return;
    ta.value = text;
    ta.dispatchEvent(new Event('input', { bubbles: true }));
    ta.style.height = 'auto';
    ta.style.height = ta.scrollHeight + 'px';
    if (commit) ta.dispatchEvent(new FocusEvent('blur'));
  }

  _start() {
    const ta = this._field();
    if (!Recognition || !ta) return;
    const base = ta.value.trimEnd();
    const rec = new Recognition();
    rec.lang = document.documentElement.lang || navigator.language || 'en-US';
    rec.continuous = true;
    rec.interimResults = true;
    let finalText = '';
    rec.onresult = (e) => {
      let interim = '';
      for (let i = e.resultIndex; i < e.results.length; i++) {
        const piece = e.results[i][0].transcript;
        if (e.results[i].isFinal) finalText += piece;
        else interim += piece;
      }
      const spoken = (finalText + interim).trim();
      const joined = base && spoken ? base + ' ' + spoken : base || spoken;
      this._write(joined, !interim);
    };
    rec.onend = () => {
      this._on = false;
      this._rec = null;
      const field = this._field();
      if (field) {
        field.dispatchEvent(new FocusEvent('blur'));
        field.focus();
      }
    };
    rec.onerror = () => {
      this._on = false;
    };
    this._rec = rec;
    this._on = true;
    rec.start();
  }

  _stop() {
    if (this._rec) this._rec.stop();
  }

  _toggle() {
    if (this._on) this._stop();
    else this._start();
  }

  static styles = css`
    :host { display: inline-flex; }
    button {
      width: 40px;
      height: 40px;
      padding: 0;
      border: 0;
      border-radius: 50%;
      display: inline-flex;
      align-items: center;
      justify-content: center;
      cursor: pointer;
      background: transparent;
      color: var(--sys-on-surface-variant, #4b515d);
      transition: background 160ms ease, color 160ms ease;
    }
    button:hover { background: var(--gm-hover, rgba(0, 0, 0, 0.06)); color: var(--sys-on-surface, #15171c); }
    button:focus-visible { outline: 2px solid var(--gm-focus, #1a5fd8); outline-offset: 2px; }
    button[aria-pressed='true'] {
      color: #fff;
      background: #d93025;
      animation: pulse 1.4s ease-in-out infinite;
    }
    svg { width: 22px; height: 22px; fill: currentColor; display: block; }
    @keyframes pulse {
      0%, 100% { box-shadow: 0 0 0 0 rgba(217, 48, 37, 0.45); }
      50% { box-shadow: 0 0 0 6px rgba(217, 48, 37, 0); }
    }
    @media (max-width: 600px) { button { width: 44px; height: 44px; } }
    @media (prefers-reduced-motion: reduce) { button { transition: none; animation: none !important; } }
  `;

  render() {
    if (!Recognition) return html``;
    const label = this._on ? this.stopLabel : this.label;
    return html`<button
      type="button"
      title=${label}
      aria-label=${label}
      aria-pressed=${this._on ? 'true' : 'false'}
      @click=${this._toggle}
    >
      <svg viewBox="0 0 24 24" aria-hidden="true"><path d="M12 14a3 3 0 0 0 3-3V5a3 3 0 0 0-6 0v6a3 3 0 0 0 3 3zm5-3a5 5 0 0 1-10 0H5a7 7 0 0 0 6 6.92V21h2v-3.08A7 7 0 0 0 19 11z"/></svg>
    </button>`;
  }
}

if (!customElements.get('gm-dictation')) customElements.define('gm-dictation', GmDictation);
