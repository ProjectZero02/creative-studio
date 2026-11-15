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
 * <capability-card>: one capability on the home page.
 *
 * Speed: the preview video is only fetched once the card is near the screen
 * (IntersectionObserver), with preload="metadata" so it shows a still frame.
 * It plays on hover or keyboard focus and pauses when the pointer leaves, so a
 * page of cards never streams eight videos at once. Reduced-motion users get
 * the still frame only.
 *
 * Access: the card is a real link (Enter works, focus ring shows); the click is
 * handed to Mesop so navigation stays inside the app.
 */
import { LitElement, css, html, nothing } from 'https://cdn.jsdelivr.net/npm/lit@3.2.1/+esm';

const reduceMotion = () =>
  window.matchMedia && window.matchMedia('(prefers-reduced-motion: reduce)').matches;

class CapabilityCard extends LitElement {
  static properties = {
    label: { type: String },
    description: { type: String },
    route: { type: String },
    icon: { type: String },
    iconFamily: { type: String },
    mode: { type: String },
    videoUrl: { type: String },
    videoObjectPosition: { type: String },
    size: { type: String }, // "media" (video on top) or "compact" (icon tile)
    clickEvent: { type: String },
    _inView: { state: true },
  };

  constructor() {
    super();
    this.label = '';
    this.description = '';
    this.route = '';
    this.icon = '';
    this.iconFamily = '';
    this.mode = '';
    this.videoUrl = '';
    this.videoObjectPosition = 'center';
    this.size = 'media';
    this.clickEvent = '';
    this._inView = false;
    this._observer = null;
  }

  connectedCallback() {
    super.connectedCallback();
    if (!this.videoUrl) return;
    if (!('IntersectionObserver' in window)) {
      this._inView = true;
      return;
    }
    this._observer = new IntersectionObserver(
      (entries) => {
        if (entries.some((e) => e.isIntersecting)) {
          this._inView = true;
          this._observer.disconnect();
        }
      },
      { rootMargin: '200px' },
    );
    this._observer.observe(this);
  }

  disconnectedCallback() {
    super.disconnectedCallback();
    if (this._observer) this._observer.disconnect();
  }

  get _video() {
    return this.renderRoot && this.renderRoot.querySelector('video');
  }

  _play() {
    const v = this._video;
    if (!v || reduceMotion()) return;
    v.play().catch(() => {});
  }

  _pause() {
    const v = this._video;
    if (v) v.pause();
  }

  _onClick(e) {
    // Let new-tab clicks behave like a normal link.
    if (e.metaKey || e.ctrlKey || e.shiftKey || e.button === 1) return;
    e.preventDefault();
    if (this.clickEvent) {
      this.dispatchEvent(new MesopEvent(this.clickEvent, { route: this.route }));
    } else {
      window.location.href = this.route;
    }
  }

  static styles = css`
    :host {
      display: block;
      min-width: 0;
      font-family: var(--gm-font, 'Google Sans', system-ui, sans-serif);
    }
    a {
      display: flex;
      flex-direction: column;
      height: 100%;
      box-sizing: border-box;
      text-decoration: none;
      color: var(--sys-on-surface, #15171c);
      background: var(--sys-surface-container-lowest, #fff);
      border: 1px solid var(--gm-border, #e1e4ea);
      border-radius: 16px;
      overflow: hidden;
      box-shadow: var(--gm-card-shadow, none);
      transition: transform 200ms cubic-bezier(0.2, 0, 0, 1),
        box-shadow 200ms cubic-bezier(0.2, 0, 0, 1),
        border-color 200ms cubic-bezier(0.2, 0, 0, 1);
    }
    a:hover {
      transform: translateY(-2px);
      box-shadow: var(--gm-card-shadow-hover, 0 8px 24px rgba(0, 0, 0, 0.12));
      border-color: var(--sys-outline-variant, #d6dae1);
    }
    a:focus-visible {
      outline: 2px solid var(--gm-focus, #1a5fd8);
      outline-offset: 2px;
    }
    .media {
      position: relative;
      aspect-ratio: 16 / 10;
      background: var(--sys-surface-container-high, #e6e9ee);
      overflow: hidden;
    }
    video {
      position: absolute;
      inset: 0;
      width: 100%;
      height: 100%;
      object-fit: cover;
      transition: transform 400ms cubic-bezier(0.2, 0, 0, 1);
    }
    a:hover video {
      transform: scale(1.03);
    }
    .mode {
      position: absolute;
      left: 10px;
      top: 10px;
      padding: 3px 9px;
      border-radius: 999px;
      font-size: 11px;
      font-weight: 600;
      letter-spacing: 0.02em;
      color: #fff;
      background: rgba(10, 12, 16, 0.62);
      backdrop-filter: blur(6px);
    }
    .body {
      display: flex;
      flex-direction: column;
      gap: 4px;
      padding: 14px 16px 16px;
      flex: 1;
    }
    .title {
      display: flex;
      align-items: center;
      justify-content: space-between;
      gap: 8px;
      font-size: 16px;
      font-weight: 600;
      letter-spacing: -0.01em;
    }
    .arrow {
      font-family: 'Material Symbols Rounded', 'Material Icons';
      font-size: 20px;
      line-height: 1;
      color: var(--sys-on-surface-variant, #4b515d);
      transition: transform 200ms cubic-bezier(0.2, 0, 0, 1), color 200ms;
      font-feature-settings: 'liga';
    }
    a:hover .arrow {
      transform: translateX(3px);
      color: var(--sys-primary, #1a5fd8);
    }
    .desc {
      font-size: 13.5px;
      line-height: 1.45;
      color: var(--sys-on-surface-variant, #4b515d);
      display: -webkit-box;
      -webkit-line-clamp: 2;
      -webkit-box-orient: vertical;
      overflow: hidden;
    }

    /* Compact: icon tile + text, for workflows without a preview video. */
    a.compact {
      flex-direction: row;
      align-items: flex-start;
      gap: 14px;
      padding: 16px;
    }
    a.compact .body {
      padding: 0;
    }
    .icon {
      flex-shrink: 0;
      width: 44px;
      height: 44px;
      border-radius: 12px;
      display: grid;
      place-items: center;
      /* Quiet tile: a light wash of the accent, not a solid block. */
      background: color-mix(in srgb, var(--sys-primary, #1a5fd8) 12%, transparent);
      color: var(--sys-primary, #1a5fd8);
      font-family: 'Material Symbols Rounded', 'Material Icons';
      font-size: 24px;
      font-feature-settings: 'liga';
      line-height: 1;
    }
    .icon.google-symbols {
      font-family: 'Google Symbols', 'Material Symbols Rounded', 'Material Icons';
    }

    @media (prefers-reduced-motion: reduce) {
      a, video, .arrow { transition: none; }
      a:hover { transform: none; }
      a:hover video { transform: none; }
    }
  `;

  render() {
    const compact = this.size === 'compact' || !this.videoUrl;
    const iconClass = this.iconFamily === 'Google Symbols' ? 'icon google-symbols' : 'icon';
    return html`
      <a
        class=${compact ? 'compact' : 'media-card'}
        href=${this.route}
        @click=${this._onClick}
        @mouseenter=${this._play}
        @mouseleave=${this._pause}
        @focus=${this._play}
        @blur=${this._pause}
      >
        ${compact
          ? html`<span class=${iconClass} aria-hidden="true">${this.icon}</span>`
          : html`<div class="media">
              ${this._inView
                ? html`<video
                    muted
                    loop
                    playsinline
                    preload="metadata"
                    aria-hidden="true"
                    style="object-position:${this.videoObjectPosition || 'center'}"
                    src=${this.videoUrl + '#t=0.5'}
                  ></video>`
                : nothing}
              ${this.mode ? html`<span class="mode">${this.mode}</span>` : nothing}
            </div>`}
        <div class="body">
          <div class="title">
            <span>${this.label}</span>
            <span class="arrow" aria-hidden="true">arrow_forward</span>
          </div>
          ${this.description ? html`<div class="desc">${this.description}</div>` : nothing}
        </div>
      </a>
    `;
  }
}

customElements.define('capability-card', CapabilityCard);
