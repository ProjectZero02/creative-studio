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
 * <home-prompt>: the home page's one main action.
 *
 * Type an idea once, pick what to make (image, video, film, voice, music) and
 * press Enter: Mesop gets {prompt, mode} and opens that studio with the idea
 * already filled in. The mode switch is a real radio group (arrow keys work).
 * Glass values come from --gm-glass-* on .gm-home (light and dark), with a
 * solid fallback when the browser can't blur or the user asks for less
 * transparency.
 */
import { LitElement, css, html } from 'https://cdn.jsdelivr.net/npm/lit@3.2.1/+esm';

const MAX_LEN = 2000;

class HomePrompt extends LitElement {
  static properties = {
    modes: { type: Array }, // [{id, label, action, icon, placeholder, examples: []}]
    strings: { type: Object }, // {what, describe, try} in the page language
    submitEvent: { type: String },
    _mode: { state: true },
    _text: { state: true },
  };

  constructor() {
    super();
    this.modes = [];
    this.strings = {};
    this.submitEvent = '';
    this._mode = '';
    this._text = '';
  }

  get _current() {
    return this.modes.find((m) => m.id === this._mode) || this.modes[0] || {};
  }

  _pick(id) {
    this._mode = id;
  }

  _onRadioKey(e, index) {
    const keys = { ArrowRight: 1, ArrowDown: 1, ArrowLeft: -1, ArrowUp: -1 };
    if (!(e.key in keys)) return;
    e.preventDefault();
    const next = (index + keys[e.key] + this.modes.length) % this.modes.length;
    this._pick(this.modes[next].id);
    this.updateComplete.then(() => {
      const btn = this.renderRoot.querySelectorAll('[role="radio"]')[next];
      if (btn) btn.focus();
    });
  }

  _onInput(e) {
    this._text = e.target.value.slice(0, MAX_LEN);
    this._autosize(e.target);
  }

  _autosize(el) {
    el.style.height = 'auto';
    el.style.height = Math.min(el.scrollHeight, 220) + 'px';
  }

  _onKey(e) {
    if (e.key === 'Enter' && !e.shiftKey && !e.isComposing) {
      e.preventDefault();
      this._submit();
    }
  }

  _useExample(text) {
    this._text = text;
    const ta = this.renderRoot.querySelector('textarea');
    if (ta) {
      ta.value = text;
      this._autosize(ta);
      ta.focus();
    }
  }

  _submit() {
    const mode = this._current.id;
    if (!mode || !this.submitEvent) return;
    this.dispatchEvent(
      new MesopEvent(this.submitEvent, { prompt: this._text.trim(), mode }),
    );
  }

  static styles = css`
    :host {
      display: block;
      width: 100%;
      font-family: var(--gm-font, 'Google Sans', system-ui, sans-serif);
      color: var(--sys-on-surface, #15171c);
    }
    .panel {
      position: relative;
      border-radius: 28px;
      padding: 10px;
      background: var(--gm-glass-solid, rgba(255, 255, 255, 0.95));
      border: 1px solid var(--gm-glass-border, rgba(255, 255, 255, 0.7));
      box-shadow: var(--gm-glass-highlight, inset 0 1.5px 0 rgba(255, 255, 255, 0.85)),
        var(--gm-glass-shadow, 0 8px 32px rgba(20, 20, 60, 0.12));
    }
    @supports ((backdrop-filter: blur(1px)) or (-webkit-backdrop-filter: blur(1px))) {
      @media (prefers-reduced-transparency: no-preference) {
        .panel {
          background: var(--gm-glass-fill, rgba(255, 255, 255, 0.55));
          -webkit-backdrop-filter: blur(20px) saturate(170%);
          backdrop-filter: blur(20px) saturate(170%);
        }
      }
    }
    @media (prefers-contrast: more) {
      .panel { border-width: 2px; border-color: var(--sys-outline, #6b7280); }
    }

    .modes {
      display: flex;
      flex-wrap: wrap;
      gap: 4px;
      padding: 4px;
      border-radius: 999px;
      width: fit-content;
      max-width: 100%;
      background: var(--gm-glass-well, rgba(15, 20, 40, 0.06));
    }
    .mode {
      display: inline-flex;
      align-items: center;
      gap: 6px;
      height: 40px;
      padding: 0 16px;
      border: 0;
      border-radius: 999px;
      background: transparent;
      color: var(--sys-on-surface-variant, #4b515d);
      font: inherit;
      font-size: 14px;
      font-weight: 500;
      cursor: pointer;
      transition: background 160ms ease, color 160ms ease, box-shadow 160ms ease;
    }
    .mode:hover { color: var(--sys-on-surface, #15171c); }
    .mode[aria-checked='true'] {
      background: var(--gm-glass-chip, #fff);
      color: var(--sys-on-surface, #15171c);
      box-shadow: 0 1px 2px rgba(0, 0, 0, 0.08), 0 2px 8px rgba(0, 0, 0, 0.06);
    }
    .mode:focus-visible,
    textarea:focus-visible,
    .go:focus-visible,
    .ex:focus-visible {
      outline: 2px solid var(--gm-focus, #1a5fd8);
      outline-offset: 2px;
    }
    .ico {
      font-family: 'Material Symbols Rounded', 'Material Icons';
      font-size: 20px;
      line-height: 1;
      font-feature-settings: 'liga';
    }

    .row {
      display: flex;
      align-items: flex-end;
      gap: 10px;
      padding: 6px 6px 4px 14px;
    }
    textarea {
      flex: 1;
      min-width: 0;
      min-height: 56px;
      max-height: 220px;
      resize: none;
      border: 0;
      border-radius: 12px;
      background: transparent;
      color: inherit;
      font: inherit;
      font-size: 18px;
      line-height: 1.45;
      padding: 14px 4px 10px;
      box-sizing: border-box;
    }
    textarea::placeholder { color: var(--sys-on-surface-variant, #5f6673); opacity: 1; }
    textarea:focus { outline: none; }
    textarea:focus-visible { outline: 2px solid var(--gm-focus, #1a5fd8); outline-offset: 0; }
    .go {
      flex-shrink: 0;
      display: inline-flex;
      align-items: center;
      gap: 6px;
      height: 52px;
      padding: 0 22px 0 18px;
      border: 0;
      border-radius: 999px;
      cursor: pointer;
      font: inherit;
      font-size: 15px;
      font-weight: 600;
      color: #fff;
      background: linear-gradient(135deg, #1a5fd8 0%, #6a3de8 100%);
      box-shadow: 0 6px 20px rgba(60, 70, 220, 0.35);
      transition: transform 160ms ease, box-shadow 160ms ease;
    }
    /* Right-to-left: the arrow points the reading way. */
    .go:dir(rtl) .ico { transform: scaleX(-1); }
    .go:hover { transform: translateY(-1px); box-shadow: 0 10px 28px rgba(60, 70, 220, 0.42); }

    .examples {
      display: flex;
      flex-wrap: wrap;
      align-items: center;
      justify-content: center;
      gap: 8px;
      margin-top: 14px;
    }
    .examples-label {
      font-size: 13px;
      color: var(--sys-on-surface-variant, #4b515d);
    }
    .ex {
      min-height: 36px;
      padding: 6px 14px;
      border-radius: 999px;
      border: 1px solid var(--gm-glass-border, rgba(255, 255, 255, 0.7));
      background: var(--gm-glass-solid, rgba(255, 255, 255, 0.9));
      color: var(--sys-on-surface, #15171c);
      font: inherit;
      font-size: 13px;
      cursor: pointer;
      transition: background 160ms ease, transform 160ms ease;
    }
    @supports ((backdrop-filter: blur(1px)) or (-webkit-backdrop-filter: blur(1px))) {
      @media (prefers-reduced-transparency: no-preference) {
        .ex {
          background: var(--gm-glass-fill, rgba(255, 255, 255, 0.55));
          -webkit-backdrop-filter: blur(12px);
          backdrop-filter: blur(12px);
        }
      }
    }
    .ex:hover { transform: translateY(-1px); }
    .sr { position: absolute; width: 1px; height: 1px; overflow: hidden; clip: rect(0 0 0 0); }

    @media (max-width: 600px) {
      .panel { border-radius: 22px; padding: 8px; }
      .modes { width: 100%; box-sizing: border-box; display: grid; grid-template-columns: repeat(5, minmax(0, 1fr)); }
      .mode { padding: 0 4px; justify-content: center; min-width: 0; }
      .mode .ico { display: none; }
      .mode .lbl { font-size: 13px; overflow: hidden; text-overflow: ellipsis; }
      .row { flex-direction: column; align-items: stretch; padding: 4px; }
      textarea { font-size: 16px; padding: 12px 8px 6px; }
      .go { justify-content: center; height: 48px; }
    }
    @media (max-width: 420px) {
      .mode .ico { display: none; }
    }
    @media (prefers-reduced-motion: reduce) {
      .mode, .go, .ex { transition: none; }
      .go:hover, .ex:hover { transform: none; }
    }
  `;

  render() {
    const cur = this._current;
    const examples = cur.examples || [];
    return html`
      <div class="panel">
        <div class="modes" role="radiogroup" aria-label=${this.strings.what || 'What to make'}>
          ${this.modes.map(
            (m, i) => html`<button
              type="button"
              class="mode"
              role="radio"
              aria-checked=${m.id === cur.id ? 'true' : 'false'}
              tabindex=${m.id === cur.id ? '0' : '-1'}
              @click=${() => this._pick(m.id)}
              @keydown=${(e) => this._onRadioKey(e, i)}
            >
              <span class="ico" aria-hidden="true">${m.icon}</span><span class="lbl">${m.label}</span>
            </button>`,
          )}
        </div>
        <div class="row">
          <label class="sr" for="idea">${this.strings.describe || 'Describe your idea'}</label>
          <textarea
            id="idea"
            rows="1"
            maxlength=${MAX_LEN}
            .value=${this._text}
            placeholder=${cur.placeholder || this.strings.describe || 'Describe your idea'}
            @input=${this._onInput}
            @keydown=${this._onKey}
          ></textarea>
          <button type="button" class="go" @click=${this._submit}>
            <span class="ico" aria-hidden="true">arrow_forward</span>
            ${cur.action || 'Create ' + (cur.label || '').toLowerCase()}
          </button>
        </div>
      </div>
      ${examples.length
        ? html`<div class="examples">
            <span class="examples-label">${this.strings.try || 'Try:'}</span>
            ${examples.map(
              (t) => html`<button type="button" class="ex" @click=${() => this._useExample(t)}>${t}</button>`,
            )}
          </div>`
        : ''}
    `;
  }
}

customElements.define('home-prompt', HomePrompt);
