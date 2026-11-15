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
 * <gm-chip-menu>: a compact setting chip for the prompt composer.
 *
 * kind="menu"   a chip that opens a listbox (model, aspect ratio, quality...).
 * kind="toggle" an on/off chip (aria-pressed), e.g. "Audio" or "Search".
 * A menu with a single option renders as a static chip (nothing to choose).
 *
 * Keyboard: Enter/Space/ArrowDown opens, arrows move, Home/End jump,
 * Enter selects, Escape or Tab closes and returns focus to the chip.
 * The chip's accessible name is "<label>: <value>", so screen readers hear
 * what the setting is even though only the value is shown.
 */
import { LitElement, css, html, nothing } from 'https://cdn.jsdelivr.net/npm/lit@3.2.1/+esm';

const CARET = 'M16.59 8.59 12 13.17 7.41 8.59 6 10l6 6 6-6z';
const CHECK = 'M9 16.17 4.83 12l-1.42 1.41L9 19 21 7l-1.41-1.41z';

const ICONS = {
  model: 'M12 2 9.5 8.5 3 11l6.5 2.5L12 20l2.5-6.5L21 11l-6.5-2.5z',
  aspect: 'M19 12h-2v3h-3v2h5v-5zM7 9h3V7H5v5h2V9zm14-6H3c-1.1 0-2 .9-2 2v14c0 1.1.9 2 2 2h18c1.1 0 2-.9 2-2V5c0-1.1-.9-2-2-2zm0 16.01H3V4.99h18v14.02z',
  quality: 'M19 3H5c-1.11 0-2 .9-2 2v14c0 1.1.89 2 2 2h14c1.1 0 2-.9 2-2V5c0-1.1-.9-2-2-2zm-8 12H9.5v-2h-2v2H6V9h1.5v2.5h2V9H11v6zm7-1c0 .55-.45 1-1 1h-.75v1.5h-1.5V15H14c-.55 0-1-.45-1-1v-4c0-.55.45-1 1-1h3c.55 0 1 .45 1 1v4zm-3.5-.5h2v-3h-2v3z',
  count: 'M3 5H1v16c0 1.1.9 2 2 2h16v-2H3V5zm18-4H7c-1.1 0-2 .9-2 2v14c0 1.1.9 2 2 2h14c1.1 0 2-.9 2-2V3c0-1.1-.9-2-2-2zm0 16H7V3h14v14z',
  timer: 'M15 1H9v2h6V1zm-4 13h2V8h-2v6zm8.03-6.61 1.42-1.42c-.43-.51-.9-.99-1.41-1.41l-1.42 1.42A8.962 8.962 0 0 0 12 4c-4.97 0-9 4.03-9 9s4.02 9 9 9 9-4.03 9-9c0-2.12-.74-4.07-1.97-5.61zM12 20c-3.87 0-7-3.13-7-7s3.13-7 7-7 7 3.13 7 7-3.13 7-7 7z',
  audio: 'M3 9v6h4l5 5V4L7 9H3zm13.5 3A4.5 4.5 0 0 0 14 7.97v8.05c1.48-.73 2.5-2.25 2.5-4.02zM14 3.23v2.06c2.89.86 5 3.54 5 6.71s-2.11 5.85-5 6.71v2.06c4.01-.91 7-4.49 7-8.77s-2.99-7.86-7-8.77z',
  search: 'M15.5 14h-.79l-.28-.27A6.47 6.47 0 0 0 16 9.5 6.5 6.5 0 1 0 9.5 16c1.61 0 3.09-.59 4.23-1.57l.27.28v.79l5 4.99L20.49 19l-4.99-5zm-6 0C7.01 14 5 11.99 5 9.5S7.01 5 9.5 5 14 7.01 14 9.5 11.99 14 9.5 14z',
  tune: 'M3 17v2h6v-2H3zM3 5v2h10V5H3zm10 16v-2h8v-2h-8v-2h-2v6h2zM7 9v2H3v2h4v2h2V9H7zm14 4v-2H11v2h10zm-6-4h2V7h4V5h-4V3h-2v6z',
  people: 'M16 11c1.66 0 2.99-1.34 2.99-3S17.66 5 16 5c-1.66 0-3 1.34-3 3s1.34 3 3 3zm-8 0c1.66 0 2.99-1.34 2.99-3S9.66 5 8 5C6.34 5 5 6.34 5 8s1.34 3 3 3zm0 2c-2.33 0-7 1.17-7 3.5V19h14v-2.5c0-2.33-4.67-3.5-7-3.5zm8 0c-.29 0-.62.02-.97.05 1.16.84 1.97 1.97 1.97 3.45V19h6v-2.5c0-2.33-4.67-3.5-7-3.5z',
};

const svg = (d, size = 18) =>
  html`<svg viewBox="0 0 24 24" width=${size} height=${size} aria-hidden="true" focusable="false"><path d=${d}></path></svg>`;

let uid = 0;

class GmChipMenu extends LitElement {
  static properties = {
    label: { type: String },
    value: { type: String },
    options: { type: String }, // JSON: [{value, label, hint?}]
    icon: { type: String },
    kind: { type: String }, // "menu" | "toggle"
    checked: { type: Boolean },
    disabled: { type: Boolean },
    changeEvent: { type: String },
    _open: { state: true },
    _active: { state: true },
  };

  constructor() {
    super();
    this.label = '';
    this.value = '';
    this.options = '[]';
    this.icon = '';
    this.kind = 'menu';
    this.checked = false;
    this.disabled = false;
    this.changeEvent = '';
    this._open = false;
    this._active = 0;
    this._id = `gm-chip-${++uid}`;
    this._onDocDown = (e) => {
      if (this._open && !e.composedPath().includes(this)) this._close(false);
    };
  }

  connectedCallback() {
    super.connectedCallback();
    document.addEventListener('pointerdown', this._onDocDown, true);
  }

  disconnectedCallback() {
    document.removeEventListener('pointerdown', this._onDocDown, true);
    super.disconnectedCallback();
  }

  get _opts() {
    try {
      const parsed = JSON.parse(this.options || '[]');
      return Array.isArray(parsed) ? parsed : [];
    } catch (_) {
      return [];
    }
  }

  get _current() {
    return this._opts.find((o) => String(o.value) === String(this.value));
  }

  _emit(value) {
    if (!this.changeEvent) return;
    this.dispatchEvent(new MesopEvent(this.changeEvent, { value: String(value) }));
  }

  _toggleOpen() {
    if (this.disabled) return;
    if (this._open) {
      this._close(true);
      return;
    }
    const idx = this._opts.findIndex((o) => String(o.value) === String(this.value));
    this._active = idx >= 0 ? idx : 0;
    this._open = true;
    this.updateComplete.then(() => {
      // Keep the menu on screen: flip to the chip's right edge near the edge
      // of a narrow window, so it never causes sideways scrolling.
      const menu = this.renderRoot.querySelector('.menu');
      if (menu && menu.getBoundingClientRect().right > window.innerWidth - 8) {
        menu.style.left = 'auto';
        menu.style.right = '0';
      }
      this._focusActive();
    });
  }

  _close(refocus) {
    this._open = false;
    if (refocus) this.updateComplete.then(() => this.renderRoot.querySelector('.chip')?.focus());
  }

  _focusActive() {
    const items = this.renderRoot.querySelectorAll('[role="option"]');
    items[this._active]?.focus();
    items[this._active]?.scrollIntoView({ block: 'nearest' });
  }

  _select(opt) {
    this._close(true);
    if (String(opt.value) !== String(this.value)) {
      this.value = String(opt.value);
      this._emit(opt.value);
    }
  }

  _onChipKey(e) {
    if (this.kind === 'toggle') return;
    if (['ArrowDown', 'ArrowUp'].includes(e.key) && !this._open) {
      e.preventDefault();
      this._toggleOpen();
    }
  }

  _onListKey(e) {
    const n = this._opts.length;
    const move = (i) => {
      e.preventDefault();
      this._active = (i + n) % n;
      this._focusActive();
    };
    switch (e.key) {
      case 'ArrowDown': return move(this._active + 1);
      case 'ArrowUp': return move(this._active - 1);
      case 'Home': return move(0);
      case 'End': return move(n - 1);
      case 'Escape':
        e.preventDefault();
        return this._close(true);
      case 'Tab':
        return this._close(false);
      case 'Enter':
      case ' ':
        e.preventDefault();
        return this._select(this._opts[this._active]);
      default:
        return undefined;
    }
  }

  _onToggle() {
    if (this.disabled) return;
    this.checked = !this.checked;
    this._emit(this.checked ? 'true' : 'false');
  }

  render() {
    const icon = ICONS[this.icon];
    if (this.kind === 'toggle') {
      return html`<button
        class="chip ${this.checked ? 'on' : ''}"
        type="button"
        aria-pressed=${this.checked ? 'true' : 'false'}
        ?disabled=${this.disabled}
        title=${this.label}
        @click=${this._onToggle}
      >
        ${icon ? svg(icon) : nothing}<span class="text">${this.value || this.label}</span>
      </button>`;
    }

    const opts = this._opts;
    const cur = this._current;
    const shown = cur ? cur.label : this.value;
    const isStatic = opts.length <= 1;
    if (isStatic) {
      return html`<span class="chip static" role="note" aria-label="${this.label}: ${shown}" title=${this.label}>
        ${icon ? svg(icon) : nothing}<span class="text">${shown}</span>
      </span>`;
    }
    return html`
      <button
        class="chip ${this._open ? 'open' : ''}"
        type="button"
        aria-haspopup="listbox"
        aria-expanded=${this._open ? 'true' : 'false'}
        aria-controls=${this._id}
        aria-label="${this.label}: ${shown}"
        title=${this.label}
        ?disabled=${this.disabled}
        @click=${this._toggleOpen}
        @keydown=${this._onChipKey}
      >
        ${icon ? svg(icon) : nothing}<span class="text">${shown}</span>${svg(CARET, 18)}
      </button>
      ${this._open
        ? html`<div class="menu" role="listbox" id=${this._id} aria-label=${this.label} @keydown=${this._onListKey}>
            <div class="menu-title" aria-hidden="true">${this.label}</div>
            ${opts.map(
              (o, i) => html`<div
                role="option"
                tabindex=${i === this._active ? '0' : '-1'}
                aria-selected=${String(o.value) === String(this.value) ? 'true' : 'false'}
                class="opt"
                @click=${() => this._select(o)}
                @pointerenter=${() => { this._active = i; }}
              >
                <span class="opt-text"><span>${o.label}</span>${o.hint ? html`<span class="hint">${o.hint}</span>` : nothing}</span>
                ${String(o.value) === String(this.value) ? svg(CHECK, 18) : nothing}
              </div>`,
            )}
          </div>`
        : nothing}
    `;
  }

  static styles = css`
    :host {
      position: relative;
      display: inline-flex;
      font-family: var(--gm-font, 'Google Sans', system-ui, sans-serif);
    }
    .chip {
      all: unset;
      box-sizing: border-box;
      display: inline-flex;
      align-items: center;
      gap: 6px;
      height: 36px;
      padding: 0 10px 0 12px;
      border-radius: 999px;
      border: 1px solid var(--gm-border, #e1e4ea);
      background: var(--sys-surface-container-low, #f4f5f8);
      color: var(--sys-on-surface, #15171c);
      font-size: 14px;
      font-weight: 500;
      line-height: 1;
      white-space: nowrap;
      cursor: pointer;
      transition: background-color 160ms cubic-bezier(0.2, 0, 0, 1), border-color 160ms cubic-bezier(0.2, 0, 0, 1);
    }
    .chip svg { fill: currentColor; flex: none; }
    .chip svg:first-child { color: var(--sys-on-surface-variant, #4b515d); }
    .chip:hover:not([disabled]):not(.static) { background: var(--sys-surface-container-high, #e6e9ee); }
    .chip:focus-visible { outline: 2px solid var(--gm-focus, #1a5fd8); outline-offset: 2px; }
    .chip.open { border-color: var(--sys-primary, #1a5fd8); }
    .chip.static { cursor: default; padding-right: 12px; }
    .chip.on {
      background: var(--sys-primary-container, #dce7fd);
      color: var(--sys-on-primary-container, #0a2a66);
      border-color: transparent;
    }
    .chip.on svg:first-child { color: inherit; }
    .chip[disabled] { opacity: 0.5; cursor: not-allowed; }
    .menu {
      position: absolute;
      top: calc(100% + 6px);
      left: 0;
      z-index: 1000;
      min-width: max(100%, 200px);
      max-height: min(360px, 60vh);
      overflow-y: auto;
      padding: 6px;
      border-radius: 14px;
      border: 1px solid var(--gm-border, #e1e4ea);
      background: var(--sys-surface-container-lowest, #fff);
      color: var(--sys-on-surface, #15171c);
      box-shadow: var(--gm-card-shadow-hover, 0 8px 24px rgba(0, 0, 0, 0.14));
      animation: pop 160ms cubic-bezier(0.2, 0, 0, 1);
      scrollbar-width: thin;
      scrollbar-color: var(--gm-scroll-thumb, rgba(0, 0, 0, 0.2)) transparent;
    }
    .menu-title {
      padding: 6px 10px 8px;
      font-size: 12px;
      font-weight: 500;
      letter-spacing: 0.02em;
      color: var(--sys-on-surface-variant, #4b515d);
    }
    .opt {
      display: flex;
      align-items: center;
      justify-content: space-between;
      gap: 12px;
      min-height: 40px;
      padding: 6px 10px;
      border-radius: 10px;
      font-size: 14px;
      cursor: pointer;
      outline: none;
    }
    .opt:hover, .opt:focus-visible { background: var(--gm-hover, rgba(0, 0, 0, 0.05)); }
    .opt:focus-visible { box-shadow: inset 0 0 0 2px var(--gm-focus, #1a5fd8); }
    .opt[aria-selected='true'] { color: var(--sys-primary, #1a5fd8); font-weight: 500; }
    .opt svg { fill: currentColor; flex: none; }
    .opt-text { display: flex; flex-direction: column; gap: 2px; }
    .hint { font-size: 12px; font-weight: 400; color: var(--sys-on-surface-variant, #4b515d); }
    @keyframes pop {
      from { opacity: 0; transform: translateY(-4px); }
      to { opacity: 1; transform: none; }
    }
    @media (max-width: 600px) {
      .chip { height: 44px; padding: 0 12px 0 14px; }
      .opt { min-height: 44px; }
    }
    @media (prefers-reduced-motion: reduce) {
      .menu { animation: none; }
      .chip { transition: none; }
    }
  `;
}

customElements.define('gm-chip-menu', GmChipMenu);
