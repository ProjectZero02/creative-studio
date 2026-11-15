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
 * <story-style-picker>: visual style as image tiles (a radio group).
 * Arrow keys move the choice, like native radio buttons.
 */
import { LitElement, css, html } from 'https://cdn.jsdelivr.net/npm/lit@3.2.1/+esm';

class StoryStylePicker extends LitElement {
  static properties = {
    optionsJson: { type: String },
    value: { type: String },
    label: { type: String },
    changeEvent: { type: String },
  };

  static styles = css`
    :host { display: block; font-family: var(--gm-font, inherit); }
    .legend { font-size: 14px; font-weight: 600; color: var(--sys-on-surface, #111); margin: 0 0 10px; }
    .grid { display: grid; grid-template-columns: repeat(auto-fill, minmax(112px, 1fr)); gap: 12px; }
    button {
      all: unset; box-sizing: border-box; cursor: pointer; display: flex; flex-direction: column; gap: 8px;
      border-radius: 14px; padding: 6px; min-height: 44px;
      background: var(--sys-surface-container-low, #f4f4f4);
      border: 1px solid var(--gm-border, var(--sys-outline-variant, #ddd));
      transition: transform 160ms ease, box-shadow 160ms ease, border-color 160ms ease;
      -webkit-tap-highlight-color: transparent;
    }
    button:hover { transform: translateY(-2px); border-color: var(--sys-outline, #888); }
    button:focus-visible { outline: 2px solid var(--gm-focus, var(--sys-primary)); outline-offset: 3px; }
    .img { position: relative; aspect-ratio: 4 / 3; border-radius: 10px; overflow: hidden; background: var(--sys-surface-container-high, #ddd); }
    img { width: 100%; height: 100%; object-fit: cover; display: block; }
    .name { font-size: 13px; font-weight: 500; text-align: center; color: var(--sys-on-surface, #111); padding: 0 2px 4px; }
    [aria-checked="true"] {
      border-color: transparent;
      box-shadow: 0 0 0 2px var(--story-ring, #fff), 0 0 0 4px var(--sys-primary, #1a5fd8);
    }
    [aria-checked="true"] .name { font-weight: 700; }
    .tick {
      position: absolute; top: 6px; right: 6px; width: 22px; height: 22px; border-radius: 50%;
      background: var(--sys-primary, #1a5fd8); color: var(--sys-on-primary, #fff); display: grid; place-items: center;
    }
    .tick svg { width: 14px; height: 14px; fill: none; stroke: currentColor; stroke-width: 3; stroke-linecap: round; stroke-linejoin: round; }
    @media (max-width: 480px) { .grid { grid-template-columns: repeat(2, 1fr); } }
    @media (prefers-reduced-motion: reduce) { button { transition: none; } button:hover { transform: none; } }
  `;

  constructor() {
    super();
    this.optionsJson = '[]';
    this.value = '';
    this.label = 'Style';
    this.changeEvent = '';
  }

  _options() {
    try { return JSON.parse(this.optionsJson || '[]'); } catch (e) { return []; }
  }

  _pick(id) {
    this.value = id;
    if (this.changeEvent) this.dispatchEvent(new MesopEvent(this.changeEvent, { value: id }));
  }

  _key(e, idx, opts) {
    const next = { ArrowRight: 1, ArrowDown: 1, ArrowLeft: -1, ArrowUp: -1 }[e.key];
    if (!next) return;
    e.preventDefault();
    const j = (idx + next + opts.length) % opts.length;
    this._pick(opts[j].id);
    this.updateComplete.then(() => this.renderRoot.querySelectorAll('button')[j]?.focus());
  }

  render() {
    const opts = this._options();
    return html`
      <p class="legend" id="lbl">${this.label}</p>
      <div class="grid" role="radiogroup" aria-labelledby="lbl">
        ${opts.map((o, i) => {
          const on = o.id === this.value;
          return html`<button role="radio" aria-checked=${on ? 'true' : 'false'} tabindex=${on || (!this.value && i === 0) ? '0' : '-1'}
              @click=${() => this._pick(o.id)} @keydown=${(e) => this._key(e, i, opts)}>
            <span class="img"><img src=${o.src} alt="" loading="lazy" width="160" height="120">
              ${on ? html`<span class="tick"><svg viewBox="0 0 24 24" aria-hidden="true"><path d="M5 12.5l4.5 4.5L19 7.5"/></svg></span>` : ''}
            </span>
            <span class="name">${o.label}</span>
          </button>`;
        })}
      </div>`;
  }
}

customElements.define('story-style-picker', StoryStylePicker);
