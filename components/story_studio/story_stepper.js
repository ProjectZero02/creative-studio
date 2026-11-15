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
 * <story-stepper>: Stories → Create → Scenario → Storyboard → Editor → Video.
 *
 * Each step is a real <button> (keyboard and screen reader friendly) with an
 * icon, a label and a connecting line. States: done, current, upcoming.
 * Upcoming steps that are not reachable yet are disabled. On narrow screens
 * only the current step keeps its label.
 */
import { LitElement, css, html, svg } from 'https://cdn.jsdelivr.net/npm/lit@3.2.1/+esm';

const ICONS = {
  stories: svg`<rect x="3" y="3" width="7.5" height="7.5" rx="2"/><rect x="13.5" y="3" width="7.5" height="7.5" rx="2"/><rect x="3" y="13.5" width="7.5" height="7.5" rx="2"/><rect x="13.5" y="13.5" width="7.5" height="7.5" rx="2"/>`,
  create: svg`<path d="M4 20h4L19 9a2.8 2.8 0 0 0-4-4L4 16z"/><path d="M13.5 6.5l4 4"/>`,
  scenario: svg`<path d="M6 3h9l4 4v14H6z"/><path d="M14.5 3v4.5H19"/><path d="M9 12h7M9 16h7"/>`,
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
      display: flex; align-items: flex-start; width: 100%;
    }
    li { flex: 1 1 0; position: relative; display: flex; justify-content: center; min-width: 0; }
    li + li::before {
      content: ""; position: absolute; top: 22px; height: 2px;
      left: calc(-50% + 30px); right: calc(50% + 30px);
      background: var(--sys-outline-variant, #ccc); border-radius: 2px;
      transition: background 220ms ease;
    }
    li.reached::before { background: var(--sys-primary, #1a5fd8); }
    button {
      all: unset; box-sizing: border-box; cursor: pointer;
      display: flex; flex-direction: column; align-items: center; gap: 8px;
      min-width: 44px; min-height: 44px; padding: 0 4px; border-radius: 12px;
      color: var(--sys-on-surface-variant, #555);
      -webkit-tap-highlight-color: transparent;
    }
    button:focus-visible { outline: 2px solid var(--gm-focus, var(--sys-primary)); outline-offset: 4px; }
    button[disabled] { cursor: default; }
    .dot {
      width: 44px; height: 44px; border-radius: 50%; display: grid; place-items: center;
      border: 2px solid var(--sys-outline-variant, #ccc);
      background: var(--sys-surface-container-low, #f4f4f4);
      transition: background 200ms ease, border-color 200ms ease, transform 200ms ease;
    }
    svg { width: 22px; height: 22px; fill: none; stroke: currentColor; stroke-width: 1.8;
          stroke-linecap: round; stroke-linejoin: round; }
    .label { font-size: 13px; line-height: 1.2; font-weight: 500; white-space: nowrap; }
    .done .dot { background: var(--sys-primary, #1a5fd8); border-color: var(--sys-primary, #1a5fd8);
                 color: var(--sys-on-primary, #fff); }
    .done .label { color: var(--sys-on-surface, #111); }
    .current .dot {
      background: var(--sys-primary-container, #dce7fd); border-color: var(--sys-primary, #1a5fd8);
      color: var(--sys-on-primary-container, #0a2a66);
      box-shadow: 0 0 0 4px color-mix(in srgb, var(--sys-primary, #1a5fd8) 18%, transparent);
    }
    .current .label { color: var(--sys-on-surface, #111); font-weight: 700; }
    .upcoming .dot { color: var(--sys-on-surface-variant, #555); }
    button:not([disabled]):hover .dot { transform: translateY(-1px); border-color: var(--sys-primary, #1a5fd8); }
    @media (max-width: 720px) {
      .dot { width: 36px; height: 36px; }
      svg { width: 18px; height: 18px; }
      button { padding: 0; min-height: 44px; justify-content: flex-start; }
      li + li::before { top: 18px; left: calc(-50% + 18px); right: calc(50% + 18px); }
      .label { font-size: 12px; }
      li:not(.is-current) .label { position: absolute; width: 1px; height: 1px; overflow: hidden; clip: rect(0 0 0 0); }
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
        const reached = s.state === 'done' || s.state === 'current';
        const icon = s.state === 'done' ? ICONS.done : (ICONS[s.id] || ICONS.stories);
        return html`<li class="${reached && i > 0 ? 'reached' : ''} ${s.state === 'current' ? 'is-current' : ''}">
          <button class="${s.state}" ?disabled=${!s.enabled}
            aria-current=${s.state === 'current' ? 'step' : 'false'}
            aria-label="${`Step ${i + 1}: ${s.label}${s.state === 'done' ? ' (done)' : ''}`}"
            @click=${() => this._select(s.id)}>
            <span class="dot"><svg viewBox="0 0 24 24" aria-hidden="true">${icon}</svg></span>
            <span class="label">${s.label}</span>
          </button>
        </li>`;
      })}
    </ol></nav>`;
  }
}

customElements.define('story-stepper', StoryStepper);
