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
 * <gm-film-compare>: two films side by side with one play button and one
 * scrubber, so the same moment of both is on screen. Sound comes from the
 * side the presenter picks (the other is muted).
 */
import { LitElement, css, html } from '/ui/vendor/lit-3.2.1.js';

class GmFilmCompare extends LitElement {
  static properties = {
    leftUrl: { type: String },
    rightUrl: { type: String },
    leftLabel: { type: String },
    rightLabel: { type: String },
    portrait: { type: Boolean },
    _playing: { state: true },
    _time: { state: true },
    _length: { state: true },
    _sound: { state: true },
  };

  constructor() {
    super();
    this.leftUrl = '';
    this.rightUrl = '';
    this.leftLabel = 'Before';
    this.rightLabel = 'Now';
    this.portrait = false;
    this._playing = false;
    this._time = 0;
    this._length = 0;
    this._sound = 'right';
  }

  get _videos() {
    return [...this.renderRoot.querySelectorAll('video')];
  }

  _toggle() {
    const vids = this._videos;
    if (this._playing) {
      vids.forEach((v) => v.pause());
      this._playing = false;
      return;
    }
    const t = vids[0] ? vids[0].currentTime : 0;
    vids.forEach((v) => {
      if (Math.abs(v.currentTime - t) > 0.05) v.currentTime = Math.min(t, (v.duration || t) - 0.05);
      v.play().catch(() => {});
    });
    this._playing = true;
  }

  _seek(e) {
    const t = Number(e.target.value);
    this._videos.forEach((v) => { v.currentTime = Math.min(t, Math.max(0, (v.duration || t) - 0.05)); });
    this._time = t;
  }

  _tick(e) {
    const vids = this._videos;
    if (e.target !== vids[0]) return;
    this._time = e.target.currentTime;
    // Keep the other film on the same moment (it may drift a little).
    const other = vids[1];
    if (other && this._playing && Math.abs(other.currentTime - this._time) > 0.25
        && this._time < (other.duration || 0)) {
      other.currentTime = this._time;
    }
  }

  _meta() {
    this._length = Math.max(...this._videos.map((v) => v.duration || 0));
  }

  _ended(e) {
    if (e.target === this._videos[0]) { this._videos.forEach((v) => v.pause()); this._playing = false; }
  }

  _fmt(t) {
    const s = Math.max(0, Math.floor(t || 0));
    return `${Math.floor(s / 60)}:${String(s % 60).padStart(2, '0')}`;
  }

  static styles = css`
    :host { display: block; }
    .pair { display: grid; grid-template-columns: 1fr 1fr; gap: 12px; }
    .pair.portrait { grid-template-columns: repeat(2, minmax(0, 260px)); justify-content: center; }
    figure { margin: 0; display: flex; flex-direction: column; gap: 6px; min-width: 0; }
    video { width: 100%; aspect-ratio: 16 / 9; background: #000; border-radius: 12px; display: block; }
    .portrait video { aspect-ratio: 9 / 16; }
    figcaption { font-size: 13px; display: flex; justify-content: space-between; gap: 8px; align-items: center;
      color: var(--sys-on-surface-variant, #44474e); }
    figcaption button { font: inherit; font-size: 12px; border: 1px solid var(--sys-outline-variant, #c4c6d0);
      background: transparent; color: inherit; border-radius: 999px; padding: 2px 10px; cursor: pointer; }
    figcaption button[aria-pressed='true'] { background: var(--sys-primary, #1a5fd8); color: var(--sys-on-primary, #fff);
      border-color: transparent; }
    .bar { display: flex; gap: 10px; align-items: center; margin-top: 10px; }
    .play { width: 40px; height: 40px; border-radius: 50%; border: 0; cursor: pointer; flex: none;
      background: var(--sys-primary, #1a5fd8); color: var(--sys-on-primary, #fff); display: grid; place-items: center; }
    .play svg { width: 20px; height: 20px; fill: currentColor; }
    input[type='range'] { flex: 1; accent-color: var(--sys-primary, #1a5fd8); }
    .time { font-size: 13px; font-variant-numeric: tabular-nums; min-width: 84px; text-align: end; }
    button:focus-visible, input:focus-visible { outline: 2px solid var(--gm-focus, #1a5fd8); outline-offset: 2px; }
    @media (max-width: 600px) { .pair, .pair.portrait { grid-template-columns: 1fr; } }
  `;

  _side(url, label, side) {
    const on = this._sound === side;
    return html`<figure>
      <video
        src=${url}
        playsinline
        preload="metadata"
        .muted=${!on}
        @loadedmetadata=${this._meta}
        @timeupdate=${this._tick}
        @ended=${this._ended}
      ></video>
      <figcaption>
        <span>${label}</span>
        <button type="button" aria-pressed=${on ? 'true' : 'false'} @click=${() => { this._sound = side; }}>
          Sound
        </button>
      </figcaption>
    </figure>`;
  }

  render() {
    const play = '<path d="M8 5v14l11-7z"/>';
    const pause = '<path d="M6 5h4v14H6zM14 5h4v14h-4z"/>';
    return html`
      <div class="pair ${this.portrait ? 'portrait' : ''}">
        ${this._side(this.leftUrl, this.leftLabel, 'left')}
        ${this._side(this.rightUrl, this.rightLabel, 'right')}
      </div>
      <div class="bar">
        <button class="play" type="button" aria-label=${this._playing ? 'Pause both' : 'Play both'} @click=${this._toggle}>
          <svg viewBox="0 0 24 24" aria-hidden="true" .innerHTML=${this._playing ? pause : play}></svg>
        </button>
        <input type="range" min="0" step="0.05" max=${this._length || 0} .value=${String(this._time)}
          aria-label="Position" @input=${this._seek} />
        <span class="time">${this._fmt(this._time)} / ${this._fmt(this._length)}</span>
      </div>`;
  }
}

if (!customElements.get('gm-film-compare')) customElements.define('gm-film-compare', GmFilmCompare);
