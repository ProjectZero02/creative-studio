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
 * <gm-generation-progress>: the step-by-step card shown while media is made.
 *
 * Shows named stages (done / now / next), a live elapsed timer with the
 * model's typical duration, an estimated progress bar, and skeleton tiles in
 * the target aspect ratio where the results will land. On error it says what
 * happened, that the prompt is kept, and offers "Try again".
 *
 * The timer runs in the browser, so it keeps ticking while the server is
 * blocked inside a long model call. Stage changes come from the page's
 * generator handler (one `yield` per stage).
 */
import { LitElement, css, html, nothing } from 'https://cdn.jsdelivr.net/npm/lit@3.2.1/+esm';

const P = {
  check: 'M9 16.17 4.83 12l-1.42 1.41L9 19 21 7l-1.41-1.41z',
  error: 'M12 2C6.48 2 2 6.48 2 12s4.48 10 10 10 10-4.48 10-10S17.52 2 12 2zm1 15h-2v-2h2v2zm0-4h-2V7h2v6z',
  retry: 'M17.65 6.35A7.958 7.958 0 0 0 12 4c-4.42 0-7.99 3.58-7.99 8s3.57 8 7.99 8c3.73 0 6.84-2.55 7.73-6h-2.08A5.99 5.99 0 0 1 12 18c-3.31 0-6-2.69-6-6s2.69-6 6-6c1.66 0 3.14.69 4.22 1.78L13 11h7V4l-2.35 2.35z',
};
const icon = (d, s = 16) =>
  html`<svg viewBox="0 0 24 24" width=${s} height=${s} aria-hidden="true" focusable="false"><path d=${d}></path></svg>`;

const fmt = (sec) => {
  const s = Math.max(0, Math.floor(sec));
  return s < 60 ? `${s}s` : `${Math.floor(s / 60)}m ${String(s % 60).padStart(2, '0')}s`;
};

class GmGenerationProgress extends LitElement {
  static properties = {
    stages: { type: String }, // JSON list of stage names
    current: { type: Number }, // index of the running stage
    status: { type: String }, // "running" | "error" | "done"
    runId: { type: String }, // changes for every new run (restarts the timer)
    typicalSeconds: { type: Number },
    workStage: { type: Number }, // the long stage the estimate bar tracks
    message: { type: String },
    heading: { type: String },
    aspect: { type: String }, // "16:9"
    count: { type: Number },
    mediaLabel: { type: String }, // "image" | "video"
    retryEvent: { type: String },
    dismissEvent: { type: String },
    _now: { state: true },
  };

  constructor() {
    super();
    this.stages = '[]';
    this.current = 0;
    this.status = 'running';
    this.runId = '';
    this.typicalSeconds = 0;
    this.workStage = -1;
    this.message = '';
    this.heading = '';
    this.aspect = '1:1';
    this.count = 1;
    this.mediaLabel = 'image';
    this.retryEvent = '';
    this.dismissEvent = '';
    this._t0 = Date.now();
    this._tEnd = 0;
    this._stageT0 = Date.now();
    this._now = Date.now();
    this._timer = 0;
  }

  connectedCallback() {
    super.connectedCallback();
    this._timer = window.setInterval(() => {
      if (this.status === 'running') this._now = Date.now();
    }, 500);
  }

  disconnectedCallback() {
    window.clearInterval(this._timer);
    super.disconnectedCallback();
  }

  willUpdate(changed) {
    if (changed.has('runId') && changed.get('runId') !== undefined) {
      this._t0 = Date.now();
      this._tEnd = 0;
      this._stageT0 = Date.now();
    }
    if (changed.has('current')) this._stageT0 = Date.now();
    if (changed.has('status') && this.status !== 'running' && !this._tEnd) this._tEnd = Date.now();
    if (changed.has('status') && this.status === 'running') this._tEnd = 0;
  }

  get _list() {
    try {
      const v = JSON.parse(this.stages || '[]');
      return Array.isArray(v) ? v : [];
    } catch (_) {
      return [];
    }
  }

  _fraction(list) {
    if (this.status === 'done') return 1;
    const n = Math.max(1, list.length);
    const base = Math.min(this.current, n) / n;
    if (this.status !== 'running') return base;
    // Inside the long stage, creep towards its end using the typical time.
    if (this.current === this.workStage && this.typicalSeconds > 0) {
      const inStage = (Date.now() - this._stageT0) / 1000;
      const within = 1 - Math.exp(-inStage / (this.typicalSeconds * 0.6));
      return base + (Math.min(0.92, within) / n);
    }
    return base + 0.35 / n;
  }

  _ratio() {
    const m = /^(\d+(?:\.\d+)?)\s*[:/x]\s*(\d+(?:\.\d+)?)$/.exec(this.aspect || '');
    return m ? `${m[1]} / ${m[2]}` : '1 / 1';
  }

  _emit(name) {
    if (name) this.dispatchEvent(new MesopEvent(name, {}));
  }

  render() {
    const list = this._list;
    const running = this.status === 'running';
    const failed = this.status === 'error';
    const end = this._tEnd || this._now;
    const elapsed = (end - this._t0) / 1000;
    const pct = Math.round(this._fraction(list) * 100);
    const stageName = list[Math.min(this.current, list.length - 1)] || '';
    const heading = this.heading || (failed
      ? `Couldn't create your ${this.mediaLabel}`
      : running ? `Creating your ${this.mediaLabel}` : 'Done');
    const tiles = Math.max(1, Math.min(4, this.count || 1));

    return html`
      <section class="card ${this.status}" aria-label="Generation progress">
        <div class="top">
          <div class="state-icon" aria-hidden="true">
            ${running ? html`<span class="spinner"></span>` : failed ? icon(P.error, 22) : icon(P.check, 22)}
          </div>
          <div class="titles">
            <h2>${heading}</h2>
            <p class="sub" aria-live="polite">
              ${failed ? html`Your prompt and settings are kept.` : html`${stageName}${running ? '…' : ''}`}
            </p>
          </div>
          <div class="time" aria-label="Elapsed time">
            <span class="elapsed">${fmt(elapsed)}</span>
            ${this.typicalSeconds > 0 && !failed
              ? html`<span class="typical">usually ~${fmt(this.typicalSeconds)}</span>`
              : nothing}
          </div>
        </div>

        <div class="bar" role="progressbar" aria-label="Estimated progress"
             aria-valuemin="0" aria-valuemax="100" aria-valuenow=${pct}>
          <span style="width:${pct}%"></span>
        </div>

        <ol class="stages">
          ${list.map((s, i) => {
            const st = this.status === 'done' || i < this.current ? 'done'
              : i === this.current ? (failed ? 'failed' : 'now') : 'next';
            return html`<li class=${st} aria-current=${st === 'now' ? 'step' : 'false'}>
              <span class="dot" aria-hidden="true">
                ${st === 'done' ? icon(P.check, 14) : st === 'failed' ? icon(P.error, 14) : html`${i + 1}`}
              </span>
              <span class="label">${s}</span>
              <span class="gm-sr">${st === 'done' ? '(done)' : st === 'now' ? '(in progress)' : st === 'failed' ? '(failed)' : ''}</span>
            </li>`;
          })}
        </ol>

        ${failed
          ? html`<div class="error" role="alert">
              <p>${this.message || 'Something went wrong on our side.'}</p>
              <div class="actions">
                ${this.retryEvent ? html`<button class="btn primary" type="button" @click=${() => this._emit(this.retryEvent)}>${icon(P.retry, 18)}Try again</button>` : nothing}
                ${this.dismissEvent ? html`<button class="btn" type="button" @click=${() => this._emit(this.dismissEvent)}>Dismiss</button>` : nothing}
              </div>
            </div>`
          : nothing}
        ${running
          ? html`<div class="tiles" aria-hidden="true">
              ${Array.from({ length: tiles }, () => html`<div class="tile" style="aspect-ratio:${this._ratio()}"><span></span></div>`)}
            </div>`
          : nothing}
      </section>
    `;
  }

  static styles = css`
    :host { display: block; font-family: var(--gm-font, 'Google Sans', system-ui, sans-serif); }
    .card {
      box-sizing: border-box;
      padding: 20px;
      border-radius: 20px;
      border: 1px solid var(--gm-border, #e1e4ea);
      background: var(--sys-surface-container-lowest, #fff);
      color: var(--sys-on-surface, #15171c);
      box-shadow: var(--gm-card-shadow, none);
      animation: enter 220ms cubic-bezier(0.2, 0, 0, 1);
    }
    .card.error { border-color: color-mix(in srgb, var(--sys-error, #b3261e) 45%, transparent); }
    .top { display: flex; align-items: center; gap: 14px; }
    .state-icon {
      width: 40px; height: 40px; flex: none; border-radius: 12px;
      display: grid; place-items: center;
      background: var(--sys-primary-container, #dce7fd);
      color: var(--sys-on-primary-container, #0a2a66);
    }
    .error .state-icon { background: var(--sys-error-container, #f9dedc); color: var(--sys-on-error-container, #410e0b); }
    .state-icon svg { fill: currentColor; }
    .spinner {
      width: 18px; height: 18px; border-radius: 50%;
      border: 2.5px solid currentColor; border-right-color: transparent;
      animation: spin 0.9s linear infinite;
    }
    .titles { flex: 1; min-width: 0; }
    h2 { margin: 0; font-size: 17px; font-weight: 500; line-height: 1.3; }
    .sub { margin: 2px 0 0; font-size: 14px; color: var(--sys-on-surface-variant, #4b515d); }
    .time { display: flex; flex-direction: column; align-items: flex-end; gap: 2px; flex: none; }
    .elapsed { font-size: 17px; font-weight: 500; font-variant-numeric: tabular-nums; }
    .typical { font-size: 12px; color: var(--sys-on-surface-variant, #4b515d); }
    .bar {
      margin: 16px 0 14px; height: 6px; border-radius: 999px; overflow: hidden;
      background: var(--sys-surface-container-high, #e6e9ee);
    }
    .bar span {
      display: block; height: 100%; border-radius: inherit;
      background: var(--sys-primary, #1a5fd8);
      transition: width 500ms cubic-bezier(0.2, 0, 0, 1);
    }
    .error .bar span { background: var(--sys-error, #b3261e); }
    .stages {
      list-style: none; margin: 0; padding: 0;
      display: flex; flex-wrap: wrap; gap: 8px 18px;
    }
    .stages li { display: flex; align-items: center; gap: 8px; font-size: 14px; color: var(--sys-on-surface-variant, #4b515d); }
    .dot {
      width: 22px; height: 22px; border-radius: 50%; flex: none;
      display: grid; place-items: center; font-size: 12px; font-weight: 500;
      border: 1.5px solid var(--sys-outline-variant, #c4c7cf);
      font-variant-numeric: tabular-nums;
    }
    .dot svg { fill: currentColor; }
    li.done { color: var(--sys-on-surface, #15171c); }
    li.done .dot { background: var(--sys-primary, #1a5fd8); border-color: transparent; color: var(--sys-on-primary, #fff); }
    li.now { color: var(--sys-on-surface, #15171c); font-weight: 500; }
    li.now .dot { border-color: var(--sys-primary, #1a5fd8); color: var(--sys-primary, #1a5fd8); animation: pulse 1.6s ease-in-out infinite; }
    li.failed { color: var(--sys-error, #b3261e); font-weight: 500; }
    li.failed .dot { background: var(--sys-error, #b3261e); border-color: transparent; color: var(--sys-on-error, #fff); }
    .gm-sr { position: absolute; width: 1px; height: 1px; overflow: hidden; clip: rect(0 0 0 0); white-space: nowrap; }
    .error { margin-top: 16px; padding: 14px 16px; border-radius: 14px; background: var(--sys-error-container, #f9dedc); color: var(--sys-on-error-container, #410e0b); }
    .error p { margin: 0 0 12px; font-size: 14px; line-height: 1.5; overflow-wrap: anywhere; }
    .actions { display: flex; flex-wrap: wrap; gap: 8px; }
    .btn {
      all: unset; box-sizing: border-box; cursor: pointer;
      display: inline-flex; align-items: center; justify-content: center; gap: 6px;
      height: 40px; padding: 0 16px; border-radius: 12px; font-size: 14px; font-weight: 500;
      border: 1px solid var(--sys-outline, #747880);
    }
    .btn svg { fill: currentColor; }
    .btn.primary { background: var(--sys-primary, #1a5fd8); color: var(--sys-on-primary, #fff); border-color: transparent; }
    .btn:hover { filter: brightness(1.06); }
    .btn:focus-visible { outline: 2px solid var(--gm-focus, #1a5fd8); outline-offset: 2px; }
    .tiles {
      margin-top: 18px; display: grid; gap: 12px;
      grid-template-columns: repeat(auto-fill, minmax(min(100%, 220px), 1fr));
    }
    .tile {
      position: relative; overflow: hidden; border-radius: 14px; max-height: 420px;
      background: var(--sys-surface-container-high, #e6e9ee);
    }
    .tile span {
      position: absolute; inset: 0;
      background: linear-gradient(100deg, transparent 20%, var(--gm-hover, rgba(255,255,255,0.35)) 50%, transparent 80%);
      transform: translateX(-100%);
      animation: shimmer 1.6s ease-in-out infinite;
    }
    @keyframes shimmer { to { transform: translateX(100%); } }
    @keyframes spin { to { transform: rotate(360deg); } }
    @keyframes pulse { 50% { box-shadow: 0 0 0 4px color-mix(in srgb, var(--sys-primary, #1a5fd8) 18%, transparent); } }
    @keyframes enter { from { opacity: 0; transform: translateY(6px); } to { opacity: 1; transform: none; } }
    @media (max-width: 600px) {
      .card { padding: 16px; border-radius: 16px; }
      .stages { flex-direction: column; }
      .btn { height: 44px; }
    }
    @media (prefers-reduced-motion: reduce) {
      .card, .tile span, li.now .dot { animation: none; }
      .spinner { animation-duration: 2.4s; }
      .bar span { transition: none; }
    }
  `;
}

customElements.define('gm-generation-progress', GmGenerationProgress);
