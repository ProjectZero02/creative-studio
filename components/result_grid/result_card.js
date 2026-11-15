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
 * <gm-result-card>: one generated image or video in a results grid.
 *
 * The thumbnail opens the item (lightbox); an action bar shows on hover or
 * keyboard focus (always on touch screens): download, open, reuse prompt,
 * and per-type actions such as "Make a video" (image) or "Extend" (video).
 * Videos load metadata only and play muted on hover.
 * kind="audio" draws a compact card with a native player and an always-visible
 * action row (no thumbnail, nothing to open).
 */
import { LitElement, css, html, nothing } from 'https://cdn.jsdelivr.net/npm/lit@3.2.1/+esm';

const P = {
  download: 'M5 20h14v-2H5v2zM19 9h-4V3H9v6H5l7 7 7-7z',
  open: 'M21 11V3h-8l3.29 3.29-10 10L3 13v8h8l-3.29-3.29 10-10z',
  reuse: 'M12 5V1L7 6l5 5V7c3.31 0 6 2.69 6 6s-2.69 6-6 6-6-2.69-6-6H4c0 4.42 3.58 8 8 8s8-3.58 8-8-3.58-8-8-8z',
  video: 'M18 4l2 4h-3l-2-4h-2l2 4h-3l-2-4H8l2 4H7L5 4H4c-1.1 0-1.99.9-1.99 2L2 18c0 1.1.9 2 2 2h16c1.1 0 2-.9 2-2V4h-4z',
  extend: 'M4 18l8.5-6L4 6v12zm9-12v12l8.5-6L13 6z',
  edit: 'M3 17.25V21h3.75L17.81 9.94l-3.75-3.75L3 17.25zM20.71 7.04a1 1 0 0 0 0-1.41l-2.34-2.34a1 1 0 0 0-1.41 0l-1.83 1.83 3.75 3.75 1.83-1.83z',
  play: 'M8 5v14l11-7z',
  wave: 'M7 18h2V6H7v12zm4 4h2V2h-2v20zm-8-8h2v-4H3v4zm12 4h2V6h-2v12zm4-8v4h2v-4h-2z',
};

const LABELS = {
  download: 'Download',
  open: 'Open larger',
  reuse: 'Reuse prompt',
  video: 'Make a video from this image',
  extend: 'Extend this video',
  edit: 'Edit this image',
};

const icon = (d) =>
  html`<svg viewBox="0 0 24 24" width="20" height="20" aria-hidden="true" focusable="false"><path d=${d}></path></svg>`;

class GmResultCard extends LitElement {
  static properties = {
    mediaUrl: { type: String },
    kind: { type: String }, // "image" | "video" | "audio"
    prompt: { type: String },
    meta: { type: String },
    aspect: { type: String },
    actions: { type: String }, // comma list of action ids
    selected: { type: Boolean },
    actionEvent: { type: String },
  };

  constructor() {
    super();
    this.mediaUrl = '';
    this.kind = 'image';
    this.prompt = '';
    this.meta = '';
    this.aspect = '1:1';
    this.actions = 'open,download,reuse';
    this.selected = false;
    this.actionEvent = '';
  }

  _ratio() {
    const m = /^(\d+(?:\.\d+)?)\s*[:/x]\s*(\d+(?:\.\d+)?)$/.exec(this.aspect || '');
    return m ? `${m[1]} / ${m[2]}` : '1 / 1';
  }

  _act(action) {
    if (this.actionEvent) {
      this.dispatchEvent(new MesopEvent(this.actionEvent, { action, src: this.mediaUrl }));
    }
  }

  _hover(on) {
    const v = this.renderRoot.querySelector('video');
    if (!v) return;
    if (on && !window.matchMedia('(prefers-reduced-motion: reduce)').matches) {
      v.play().catch(() => {});
    } else {
      v.pause();
    }
  }

  _actionButtons(list) {
    return list.filter((a) => a !== 'open').map((a) => a === 'download'
      ? html`<a class="act" href=${this.mediaUrl} download target="_blank" rel="noopener"
           aria-label=${LABELS[a]} title=${LABELS[a]}>${icon(P[a])}</a>`
      : html`<button class="act" type="button" aria-label=${LABELS[a] || a} title=${LABELS[a] || a}
           @click=${() => this._act(a)}>${icon(P[a] || P.open)}</button>`);
  }

  _renderAudio(list) {
    const name = this.prompt ? this.prompt.slice(0, 80) : 'Generated audio';
    return html`
      <figure class="card audio ${this.selected ? 'selected' : ''}">
        <div class="audio-head">
          <span class="audio-icon" aria-hidden="true">${icon(P.wave)}</span>
          <figcaption>
            ${this.prompt ? html`<span class="prompt">${this.prompt}</span>` : nothing}
            ${this.meta ? html`<span class="meta">${this.meta}</span>` : nothing}
          </figcaption>
        </div>
        <audio controls preload="metadata" src=${this.mediaUrl} aria-label="Play: ${name}"></audio>
        <div class="bar inline" role="toolbar" aria-label="Actions">${this._actionButtons(list)}</div>
      </figure>
    `;
  }

  render() {
    const list = (this.actions || '').split(',').map((a) => a.trim()).filter(Boolean);
    if (this.kind === 'audio') return this._renderAudio(list);
    const name = this.prompt ? this.prompt.slice(0, 80) : `Generated ${this.kind}`;
    return html`
      <figure class="card ${this.selected ? 'selected' : ''}"
        @pointerenter=${() => this._hover(true)} @pointerleave=${() => this._hover(false)}>
        <button class="media" type="button" style="aspect-ratio:${this._ratio()}"
          aria-label="Open ${this.kind}: ${name}" @click=${() => this._act('open')}
          @focus=${() => this._hover(true)} @blur=${() => this._hover(false)}>
          ${this.kind === 'video'
            ? html`<video src=${this.mediaUrl} muted loop playsinline preload="metadata"></video>
                   <span class="badge" aria-hidden="true">${icon(P.play)}</span>`
            : html`<img src=${this.mediaUrl} alt="" loading="lazy" decoding="async" />`}
        </button>
        <div class="bar" role="toolbar" aria-label="Actions">
          ${list.filter((a) => a !== 'open').map((a) => a === 'download'
            ? html`<a class="act" href=${this.mediaUrl} download target="_blank" rel="noopener"
                 aria-label=${LABELS[a]} title=${LABELS[a]}>${icon(P[a])}</a>`
            : html`<button class="act" type="button" aria-label=${LABELS[a] || a} title=${LABELS[a] || a}
                 @click=${() => this._act(a)}>${icon(P[a] || P.open)}</button>`)}
        </div>
        ${this.prompt || this.meta
          ? html`<figcaption>
              ${this.prompt ? html`<span class="prompt">${this.prompt}</span>` : nothing}
              ${this.meta ? html`<span class="meta">${this.meta}</span>` : nothing}
            </figcaption>`
          : nothing}
      </figure>
    `;
  }

  static styles = css`
    :host { display: block; font-family: var(--gm-font, 'Google Sans', system-ui, sans-serif); }
    .card {
      position: relative; margin: 0; padding: 0;
      border-radius: 16px; overflow: hidden;
      background: var(--sys-surface-container-lowest, #fff);
      border: 1px solid var(--gm-border, #e1e4ea);
      box-shadow: var(--gm-card-shadow, none);
      transition: box-shadow 200ms cubic-bezier(0.2, 0, 0, 1), transform 200ms cubic-bezier(0.2, 0, 0, 1);
      animation: enter 220ms cubic-bezier(0.2, 0, 0, 1);
    }
    .card:hover { box-shadow: var(--gm-card-shadow-hover, 0 8px 24px rgba(0, 0, 0, 0.12)); transform: translateY(-2px); }
    .card.selected { border-color: var(--sys-primary, #1a5fd8); box-shadow: 0 0 0 1px var(--sys-primary, #1a5fd8); }
    .media {
      all: unset; box-sizing: border-box; display: block; width: 100%; cursor: zoom-in;
      position: relative; max-height: 520px;
      background: var(--sys-surface-container-high, #e6e9ee);
    }
    .media:focus-visible { outline: 2px solid var(--gm-focus, #1a5fd8); outline-offset: -2px; }
    .media img, .media video { display: block; width: 100%; height: 100%; object-fit: cover; }
    .badge {
      position: absolute; left: 10px; bottom: 10px; width: 30px; height: 30px; border-radius: 50%;
      display: grid; place-items: center; background: rgba(0, 0, 0, 0.55); color: #fff;
    }
    .badge svg { fill: currentColor; width: 18px; height: 18px; }
    .bar {
      position: absolute; top: 10px; right: 10px; display: flex; gap: 6px;
      opacity: 0; transform: translateY(-4px);
      transition: opacity 160ms cubic-bezier(0.2, 0, 0, 1), transform 160ms cubic-bezier(0.2, 0, 0, 1);
    }
    .card:hover .bar, .card:focus-within .bar { opacity: 1; transform: none; }
    @media (hover: none) { .bar { opacity: 1; transform: none; } }
    .act {
      all: unset; box-sizing: border-box; cursor: pointer;
      width: 36px; height: 36px; border-radius: 10px;
      display: grid; place-items: center;
      background: rgba(18, 20, 24, 0.66); color: #fff;
      backdrop-filter: blur(6px);
      transition: background-color 160ms cubic-bezier(0.2, 0, 0, 1);
    }
    .act:hover { background: rgba(18, 20, 24, 0.86); }
    .act:focus-visible { outline: 2px solid #fff; outline-offset: 1px; box-shadow: 0 0 0 4px var(--gm-focus, #1a5fd8); }
    .act svg { fill: currentColor; }
    figcaption { display: flex; flex-direction: column; gap: 4px; padding: 10px 12px 12px; }
    .prompt {
      font-size: 14px; line-height: 1.4; color: var(--sys-on-surface, #15171c);
      display: -webkit-box; -webkit-line-clamp: 2; -webkit-box-orient: vertical; overflow: hidden;
    }
    .meta { font-size: 12px; color: var(--sys-on-surface-variant, #4b515d); }
    @keyframes enter { from { opacity: 0; transform: translateY(6px); } to { opacity: 1; transform: none; } }
    .card.audio { display: flex; flex-direction: column; gap: 10px; padding: 14px; }
    .card.audio:hover { transform: none; }
    .audio-head { display: flex; gap: 12px; align-items: flex-start; min-width: 0; }
    .audio-head figcaption { padding: 0; min-width: 0; }
    .audio-icon {
      flex: 0 0 auto; width: 40px; height: 40px; border-radius: 12px;
      display: grid; place-items: center;
      background: var(--sys-primary-container, #dbe6ff); color: var(--sys-on-primary-container, #0b2a66);
    }
    .audio-icon svg { fill: currentColor; }
    .card.audio audio { width: 100%; height: 40px; }
    .bar.inline { position: static; opacity: 1; transform: none; justify-content: flex-end; }
    .bar.inline .act {
      background: var(--sys-surface-container-high, #e6e9ee); color: var(--sys-on-surface, #15171c);
      backdrop-filter: none;
    }
    .bar.inline .act:hover { background: var(--sys-surface-container-highest, #dde1e7); }
    .bar.inline .act:focus-visible { outline: 2px solid var(--gm-focus, #1a5fd8); box-shadow: none; }
    @media (max-width: 600px) { .act { width: 44px; height: 44px; } }
    @media (prefers-reduced-motion: reduce) {
      .card, .bar { transition: none; animation: none; }
      .card:hover { transform: none; }
    }
  `;
}

customElements.define('gm-result-card', GmResultCard);
