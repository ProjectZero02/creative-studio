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
 * <story-stepper>: 4-stage quiet tonal pill stepper:
 *   Stories -> Setup -> Director's Desk -> Timeline & Export.
 */
import { LitElement, css, html, svg } from '/ui/vendor/lit-3.2.1.js';

const ICONS = {
  stories: svg`<rect x="3" y="3" width="7.5" height="7.5" rx="2"/><rect x="13.5" y="3" width="7.5" height="7.5" rx="2"/><rect x="3" y="13.5" width="7.5" height="7.5" rx="2"/><rect x="13.5" y="13.5" width="7.5" height="7.5" rx="2"/>`,
  create: svg`<path d="M4 20h4L19 9a2.8 2.8 0 0 0-4-4L4 16z"/><path d="M13.5 6.5l4 4"/>`,
  scenario: svg`<path d="M6 3h9l4 4v14H6z"/><path d="M14.5 3v4.5H19"/><path d="M9 12h7M9 16h7"/>`,
  set: svg`<circle cx="9" cy="8" r="3.2"/><path d="M3 19.5c.6-3.3 3-5.2 6-5.2s5.4 1.9 6 5.2"/><circle cx="17" cy="9" r="2.4"/><path d="M16.2 14.4c2.4.1 4.2 1.6 4.8 4.4"/>`,
  storyboard: svg`<rect x="2.5" y="5" width="8.5" height="6.5" rx="1.5"/><rect x="13" y="5" width="8.5" height="6.5" rx="1.5"/><rect x="2.5" y="13.5" width="8.5" height="6.5" rx="1.5"/><rect x="13" y="13.5" width="8.5" height="6.5" rx="1.5"/>`,
  editor: svg`<path d="M4 7h10M18 7h2M4 17h4M12 17h8"/><circle cx="16" cy="7" r="2"/><circle cx="10" cy="17" r="2"/>`,
  video: svg`<rect x="3" y="5" width="18" height="14" rx="3"/><path d="M10 9.2v5.6l4.6-2.8z" fill="currentColor"/>`,
  done: svg`<path d="M5 12.5l4.5 4.5L19 7.5"/>`,
};

class StoryStepper extends LitElement {
  static properties = {
    stepsJson: { type: String },
    selectEvent: { type: String },
  };

  static styles = css`
    :host { display: block; width: 100%; font-family: var(--gm-font, inherit); }
    ol {
      list-style: none; margin: 0; padding: 0;
      display: grid; grid-template-columns: repeat(4, minmax(0, 1fr));
      gap: 8px; width: 100%; align-items: center;
    }
    li { display: flex; min-width: 0; }
    button {
      all: unset; box-sizing: border-box; cursor: pointer;
      display: inline-flex; align-items: center; justify-content: center; gap: 8px;
      width: 100%; height: var(--gm-control-h, 40px); min-width: 0;
      padding: 0 14px; border-radius: 999px; border: 0;
      background: var(--gm-tonal, rgba(127, 127, 127, 0.08));
      color: var(--sys-on-surface-variant, #555);
      font-size: 13.5px; font-weight: 500;
      transition: background-color 160ms ease, color 160ms ease, opacity 160ms ease;
      -webkit-tap-highlight-color: transparent;
    }
    button:focus-visible { outline: 2px solid var(--gm-focus, var(--sys-primary)); outline-offset: 2px; }
    button[disabled] { cursor: default; opacity: 0.45; }
    button:not([disabled]):not(.current):hover {
      background: var(--gm-tonal-hover, rgba(127, 127, 127, 0.14));
      color: var(--sys-on-surface, #111);
    }
    .badge {
      width: 22px; height: 22px; border-radius: 50%; flex: none;
      display: grid; place-items: center;
      background: transparent;
    }
    svg {
      width: 17px; height: 17px; fill: none; stroke: currentColor; stroke-width: 1.9;
      stroke-linecap: round; stroke-linejoin: round;
    }
    .label {
      line-height: 1.2; white-space: nowrap; overflow: hidden; text-overflow: ellipsis;
      min-width: 0;
    }
    .done {
      background: var(--gm-tonal, rgba(127, 127, 127, 0.08));
      color: var(--sys-on-surface, #111);
    }
    .done .badge {
      background: var(--sys-primary, #1a5fd8);
      color: var(--sys-on-primary, #fff);
    }
    .done svg { width: 13px; height: 13px; stroke-width: 2.4; }
    .current {
      background: var(--sys-primary-container, #dce7fd);
      color: var(--sys-on-primary-container, #0a2a66);
      font-weight: 600;
    }
    @media (max-width: 640px) {
      ol { display: flex; gap: 6px; }
      li { flex: 0 0 auto; }
      li.is-current { flex: 1 1 auto; min-width: 0; }
      button { height: var(--gm-control-h, 44px); width: 44px; padding: 0; }
      li.is-current button { width: 100%; padding: 0 14px; }
      li:not(.is-current) .label {
        position: absolute; width: 1px; height: 1px; overflow: hidden; clip: rect(0 0 0 0);
      }
    }
    @media (prefers-reduced-motion: reduce) { * { transition: none !important; } }
  `;

  constructor() {
    super();
    this.stepsJson = '[]';
    this.selectEvent = '';
  }

  _steps() {
    try { return JSON.parse(this.stepsJson || '[]'); } catch (e) { return []; }
  }

  _select(id) {
    if (this.selectEvent) this.dispatchEvent(new MesopEvent(this.selectEvent, { id }));
  }

  render() {
    const steps = this._steps();
    return html`<nav aria-label="Story steps"><ol>
      ${steps.map((s, i) => {
        const icon = s.state === 'done' ? ICONS.done : (ICONS[s.id] || ICONS.stories);
        return html`<li class="${s.state === 'current' ? 'is-current' : ''}">
          <button class="${s.state}" ?disabled=${!s.enabled}
            aria-current=${s.state === 'current' ? 'step' : 'false'}
            aria-label="${`Step ${i + 1}: ${s.label}${s.state === 'done' ? ' (done)' : ''}`}"
            @click=${() => this._select(s.id)}>
            <span class="badge"><svg viewBox="0 0 24 24" aria-hidden="true">${icon}</svg></span>
            <span class="label">${s.label}</span>
          </button>
        </li>`;
      })}
    </ol></nav>`;
  }
}

customElements.define('story-stepper', StoryStepper);
