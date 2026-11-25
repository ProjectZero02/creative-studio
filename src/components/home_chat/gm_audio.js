/**
 * Copyright 2025 Google LLC
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
 * <gm-audio>: a themed audio player that replaces <audio controls>.
 *
 * One rounded row: play/pause, a waveform that fills with the accent colour
 * as it plays (click or drag to seek, Left/Right to skip 5 s), the time, and
 * optional speed and download buttons. The waveform comes from the decoded
 * file (peaks cached per src); while it loads, or if the file can't be read
 * (CORS, decode error), gentle placeholder bars seeded from the src are shown.
 * Only one <gm-audio> plays at a time.
 *
 * Attributes / properties:
 *   src       audio URL
 *   label     accessible name ("Voice-over", "Track 1"...)
 *   compact   smaller row for narrow panels (reflected)
 *   download  filename; when set, shows a download button
 *   speed     shows a playback-speed button (1x, 1.25x, 1.5x, 0.75x)
 *
 * Events: `gm-audio-play` (bubbles, composed) with detail { src } on play.
 * Methods: play(), pause().
 */

import { LitElement, css, html, nothing } from '/ui/vendor/lit-3.2.1.js';

const BARS = 64;
const BARS_COMPACT = 40;
const SPEEDS = [1, 1.25, 1.5, 0.75];
const SEEK_STEP = 5;
const EXCLUSIVE_EVENT = 'gm-audio-exclusive';

/** src -> Promise<Float32Array> of normalised peaks at PEAK_RES buckets. */
const peakCache = new Map();
const PEAK_RES = 256;

function hashString(s) {
  let h = 2166136261;
  for (let i = 0; i < s.length; i++) {
    h ^= s.charCodeAt(i);
    h = Math.imul(h, 16777619);
  }
  return h >>> 0;
}

/** Fixed, soft pseudo-random bars seeded from the src string. */
function placeholderPeaks(src, n) {
  let a = hashString(src || 'gm-audio') || 1;
  const rand = () => {
    a = (a + 0x6d2b79f5) | 0;
    let t = Math.imul(a ^ (a >>> 15), 1 | a);
    t = (t + Math.imul(t ^ (t >>> 7), 61 | t)) ^ t;
    return ((t ^ (t >>> 14)) >>> 0) / 4294967296;
  };
  const out = new Array(n);
  for (let i = 0; i < n; i++) {
    const wave = 0.5 + 0.25 * Math.sin((i / n) * Math.PI * 3);
    out[i] = Math.min(1, Math.max(0.18, wave * 0.6 + rand() * 0.4));
  }
  return out;
}

async function decodeBuffer(arrayBuf) {
  const Offline = window.OfflineAudioContext || window.webkitOfflineAudioContext;
  if (Offline) {
    try {
      const ctx = new Offline(1, 1, 44100);
      return await ctx.decodeAudioData(arrayBuf.slice(0));
    } catch (_) {
      /* fall through to AudioContext */
    }
  }
  const Ctx = window.AudioContext || window.webkitAudioContext;
  if (!Ctx) throw new Error('no audio context');
  const ctx = new Ctx();
  try {
    return await new Promise((resolve, reject) => {
      const p = ctx.decodeAudioData(arrayBuf, resolve, reject);
      if (p && p.then) p.then(resolve, reject);
    });
  } finally {
    if (ctx.close) ctx.close().catch(() => {});
  }
}

function computePeaks(buffer) {
  const channels = [];
  for (let c = 0; c < buffer.numberOfChannels; c++) channels.push(buffer.getChannelData(c));
  const len = buffer.length;
  const size = Math.max(1, Math.floor(len / PEAK_RES));
  const peaks = new Float32Array(PEAK_RES);
  let max = 0;
  for (let b = 0; b < PEAK_RES; b++) {
    const start = b * size;
    const end = Math.min(len, start + size);
    let sum = 0;
    let count = 0;
    for (const data of channels) {
      // Stride through long buckets; RMS is stable with a sample of points.
      const stride = Math.max(1, Math.floor((end - start) / 2000));
      for (let i = start; i < end; i += stride) {
        sum += data[i] * data[i];
        count++;
      }
    }
    const rms = count ? Math.sqrt(sum / count) : 0;
    peaks[b] = rms;
    if (rms > max) max = rms;
  }
  if (max > 0) for (let b = 0; b < PEAK_RES; b++) peaks[b] /= max;
  return peaks;
}

function loadPeaks(src) {
  if (!peakCache.has(src)) {
    const p = fetch(src)
      .then((r) => {
        if (!r.ok) throw new Error(`HTTP ${r.status}`);
        return r.arrayBuffer();
      })
      .then(decodeBuffer)
      .then(computePeaks);
    p.catch(() => {}); // failures fall back to placeholders; keep cached so we don't refetch
    peakCache.set(src, p);
  }
  return peakCache.get(src);
}

function resample(peaks, n) {
  const out = new Array(n);
  const step = peaks.length / n;
  for (let i = 0; i < n; i++) {
    const a = Math.floor(i * step);
    const b = Math.max(a + 1, Math.floor((i + 1) * step));
    let m = 0;
    for (let j = a; j < b && j < peaks.length; j++) m = Math.max(m, peaks[j]);
    out[i] = Math.max(0.08, m);
  }
  return out;
}

function fmt(t) {
  if (!Number.isFinite(t) || t < 0) t = 0;
  const s = Math.floor(t);
  const h = Math.floor(s / 3600);
  const m = Math.floor((s % 3600) / 60);
  const sec = String(s % 60).padStart(2, '0');
  return h ? `${h}:${String(m).padStart(2, '0')}:${sec}` : `${m}:${sec}`;
}

const ICON_PLAY = html`<svg viewBox="0 0 24 24" width="20" height="20" aria-hidden="true"><path d="M8 5.5v13a1 1 0 0 0 1.52.85l10.4-6.5a1 1 0 0 0 0-1.7L9.52 4.65A1 1 0 0 0 8 5.5z"/></svg>`;
const ICON_PAUSE = html`<svg viewBox="0 0 24 24" width="20" height="20" aria-hidden="true"><rect x="6" y="5" width="4.2" height="14" rx="1.2"/><rect x="13.8" y="5" width="4.2" height="14" rx="1.2"/></svg>`;
const ICON_DOWNLOAD = html`<svg viewBox="0 0 24 24" width="20" height="20" aria-hidden="true"><path d="M12 3a1 1 0 0 1 1 1v9.59l3.3-3.3a1 1 0 1 1 1.4 1.42l-5 5a1 1 0 0 1-1.4 0l-5-5a1 1 0 1 1 1.4-1.42l3.3 3.3V4a1 1 0 0 1 1-1zM5 19a1 1 0 0 1 1-1h12a1 1 0 1 1 0 2H6a1 1 0 0 1-1-1z"/></svg>`;

export class GmAudio extends LitElement {
  static properties = {
    src: { type: String },
    label: { type: String },
    compact: { type: Boolean, reflect: true },
    download: { type: String },
    speed: { type: Boolean },
    strings: { type: Object }, // the Home chat's strings (audio_* keys); English fallback
    _playing: { state: true },
    _time: { state: true },
    _duration: { state: true },
    _peaks: { state: true },
    _rate: { state: true },
  };

  static styles = css`
    :host {
      --_accent: var(--gm-accent, var(--sys-primary, #4c6fff));
      --_on-accent: var(--sys-on-primary, #fff);
      --_surface: var(--gm-tonal, rgba(127, 127, 127, 0.12));
      --_hover: var(--gm-tonal-hover, rgba(127, 127, 127, 0.18));
      --_text: var(--sys-on-surface, currentColor);
      --_muted: var(--sys-on-surface-variant, currentColor);
      --_h: 56px;
      --_btn: 36px;
      display: block;
      min-width: 0;
      font-family: var(--gm-font, inherit);
      color: var(--_text);
    }
    :host([compact]) { --_h: 44px; --_btn: 32px; }
    .row {
      display: flex; align-items: center; gap: 10px;
      height: var(--_h); padding: 0 10px; box-sizing: border-box;
      border-radius: 14px; background: var(--_surface);
    }
    :host([compact]) .row { gap: 8px; padding: 0 6px; }
    button, a.btn {
      flex: none; display: inline-flex; align-items: center; justify-content: center;
      height: var(--_btn); min-width: var(--_btn); padding: 0; border: 0; border-radius: 999px;
      background: transparent; color: var(--_muted); cursor: pointer; font: inherit;
      text-decoration: none; -webkit-tap-highlight-color: transparent;
    }
    button svg, a.btn svg { fill: currentColor; }
    button:hover, a.btn:hover { background: var(--_hover); }
    button:focus-visible, a.btn:focus-visible, .wave:focus-visible {
      outline: 2px solid var(--_accent); outline-offset: 2px;
    }
    .play { width: var(--_btn); background: var(--_accent); color: var(--_on-accent); }
    .play:hover { background: var(--_accent); filter: brightness(1.08); }
    .speed { padding: 0 8px; font-size: 12px; font-weight: 600; font-variant-numeric: tabular-nums; min-width: 44px; }
    .wave {
      position: relative; flex: 1 1 auto; min-width: 40px; height: 60%;
      cursor: pointer; touch-action: none; border-radius: 6px;
      /* Time runs left to right in every language: the seek math, the
         played fill and the arrow keys all assume it. */
      direction: ltr;
    }
    .bars {
      position: absolute; inset: 0; display: flex; align-items: center; gap: 2px;
    }
    .bars i {
      flex: 1 1 0; min-width: 1px; border-radius: 2px;
      background: currentColor;
      transition: height 240ms ease;
    }
    .base { color: var(--_muted); opacity: 0.35; }
    .base.loading i { opacity: 0.6; }
    .played { color: var(--_accent); clip-path: inset(0 calc(100% - var(--_p, 0%)) 0 0); }
    .time {
      flex: none; font-size: 12px; font-variant-numeric: tabular-nums;
      color: var(--_muted); white-space: nowrap;
    }
    :host([compact]) .time { font-size: 11px; }
    audio { display: none; }
    @media (prefers-reduced-motion: reduce) {
      .bars i { transition: none; }
    }
  `;

  constructor() {
    super();
    this.src = '';
    this.label = '';
    this.compact = false;
    this.download = '';
    this.speed = false;
    this.strings = {};
    this._playing = false;
    this._time = 0;
    this._duration = 0;
    this._peaks = null;
    this._rate = 1;
    this._raf = 0;
    this._dragging = false;
    this._loadToken = 0;
    this._onExclusive = (e) => {
      if (e.detail !== this && this._playing) this.pause();
    };
  }

  connectedCallback() {
    super.connectedCallback();
    window.addEventListener(EXCLUSIVE_EVENT, this._onExclusive);
  }

  disconnectedCallback() {
    super.disconnectedCallback();
    window.removeEventListener(EXCLUSIVE_EVENT, this._onExclusive);
    cancelAnimationFrame(this._raf);
    this.pause();
  }

  willUpdate(changed) {
    if (changed.has('src')) {
      this._time = 0;
      this._duration = 0;
      this._playing = false;
      this._peaks = null;
      this._loadPeaks();
    }
  }

  get _audio() {
    return this.renderRoot?.querySelector('audio');
  }

  _loadPeaks() {
    const src = this.src;
    const token = ++this._loadToken;
    if (!src) return;
    loadPeaks(src).then(
      (p) => { if (token === this._loadToken) this._peaks = p; },
      () => {},
    );
  }

  play() {
    const a = this._audio;
    if (!a || !this.src) return;
    const p = a.play();
    if (p && p.catch) p.catch(() => {});
  }

  pause() {
    const a = this._audio;
    if (a && !a.paused) a.pause();
  }

  _toggle() {
    const a = this._audio;
    if (!a) return;
    if (a.paused) this.play();
    else this.pause();
  }

  _onPlay() {
    this._playing = true;
    window.dispatchEvent(new CustomEvent(EXCLUSIVE_EVENT, { detail: this }));
    this.dispatchEvent(new CustomEvent('gm-audio-play', {
      bubbles: true, composed: true, detail: { src: this.src },
    }));
    this._tick();
  }

  _onPause() {
    this._playing = false;
    cancelAnimationFrame(this._raf);
    this._sync();
  }

  _onEnded() {
    this._playing = false;
    cancelAnimationFrame(this._raf);
    this._time = this._duration;
  }

  _sync() {
    const a = this._audio;
    if (!a) return;
    if (!this._dragging) this._time = a.currentTime;
    if (Number.isFinite(a.duration)) this._duration = a.duration;
  }

  _tick() {
    cancelAnimationFrame(this._raf);
    // With reduced motion, rely on timeupdate (about 4 per second) instead of every frame.
    if (window.matchMedia?.('(prefers-reduced-motion: reduce)').matches) return;
    const step = () => {
      this._sync();
      if (this._playing) this._raf = requestAnimationFrame(step);
    };
    this._raf = requestAnimationFrame(step);
  }

  _seekTo(t) {
    const a = this._audio;
    if (!a || !this._duration) return;
    const clamped = Math.max(0, Math.min(this._duration, t));
    a.currentTime = clamped;
    this._time = clamped;
  }

  _ratioFromEvent(e) {
    const r = e.currentTarget.getBoundingClientRect();
    if (!r.width) return 0;
    return Math.max(0, Math.min(1, (e.clientX - r.left) / r.width));
  }

  _onPointerDown(e) {
    if (e.button !== undefined && e.button !== 0) return;
    if (!this._duration) {
      // Nothing loaded yet: a click starts playback.
      this.play();
      return;
    }
    this._dragging = true;
    e.currentTarget.setPointerCapture?.(e.pointerId);
    this._time = this._ratioFromEvent(e) * this._duration;
  }

  _onPointerMove(e) {
    if (!this._dragging) return;
    this._time = this._ratioFromEvent(e) * this._duration;
  }

  _onPointerUp(e) {
    if (!this._dragging) return;
    this._dragging = false;
    e.currentTarget.releasePointerCapture?.(e.pointerId);
    this._seekTo(this._ratioFromEvent(e) * this._duration);
  }

  _onWaveKey(e) {
    const a = this._audio;
    if (!a) return;
    let t = null;
    if (e.key === 'ArrowLeft' || e.key === 'ArrowDown') t = a.currentTime - SEEK_STEP;
    else if (e.key === 'ArrowRight' || e.key === 'ArrowUp') t = a.currentTime + SEEK_STEP;
    else if (e.key === 'Home') t = 0;
    else if (e.key === 'End') t = this._duration;
    else if (e.key === ' ' || e.key === 'Enter') {
      e.preventDefault();
      this._toggle();
      return;
    }
    if (t === null) return;
    e.preventDefault();
    this._seekTo(t);
  }

  _cycleSpeed() {
    const i = SPEEDS.indexOf(this._rate);
    this._rate = SPEEDS[(i + 1) % SPEEDS.length];
    const a = this._audio;
    if (a) a.playbackRate = this._rate;
  }

  _rateLabel(r) {
    return `${r}x`;
  }

  render() {
    const n = this.compact ? BARS_COMPACT : BARS;
    const loading = !this._peaks;
    const bars = loading ? placeholderPeaks(this.src, n) : resample(this._peaks, n);
    const barEls = bars.map((v) => html`<i style="height:${Math.round(v * 100)}%"></i>`);
    const pct = this._duration ? Math.min(100, (this._time / this._duration) * 100) : 0;
    const S = this.strings || {};
    // S.audio_* templates use {name}, {a}, {b}, {rate}; English is the fallback.
    const fill = (tpl, vals) => tpl.replace(/\{(\w+)\}/g, (m, k) => (k in vals ? vals[k] : m));
    const name = this.label || S.audio || 'Audio';
    const now = Math.round(this._time);
    const total = Math.round(this._duration);

    return html`
      <div class="row">
        <button class="play" type="button"
          aria-label=${fill(this._playing ? (S.audio_pause || 'Pause {name}') : (S.audio_play || 'Play {name}'), { name })}
          @click=${this._toggle}>
          ${this._playing ? ICON_PAUSE : ICON_PLAY}
        </button>
        <div class="wave" role="slider" tabindex="0"
          aria-label=${fill(S.audio_position || '{name} position', { name })}
          aria-valuemin="0"
          aria-valuemax=${total}
          aria-valuenow=${now}
          aria-valuetext=${fill(S.audio_of || '{a} of {b}', { a: fmt(this._time), b: fmt(this._duration) })}
          style="--_p:${pct}%"
          @pointerdown=${this._onPointerDown}
          @pointermove=${this._onPointerMove}
          @pointerup=${this._onPointerUp}
          @pointercancel=${this._onPointerUp}
          @keydown=${this._onWaveKey}>
          <div class="bars base ${loading ? 'loading' : ''}" aria-hidden="true">${barEls}</div>
          <div class="bars played" aria-hidden="true">${barEls}</div>
        </div>
        <span class="time">${fmt(this._time)} / ${fmt(this._duration)}</span>
        ${this.speed ? html`
          <button class="speed" type="button"
            aria-label=${fill(S.audio_speed || 'Playback speed {rate}', { rate: this._rateLabel(this._rate) })}
            @click=${this._cycleSpeed}>${this._rateLabel(this._rate)}</button>` : nothing}
        ${this.download ? html`
          <a class="btn" href=${this.src} download=${this.download}
            aria-label=${fill(S.audio_download || 'Download {name}', { name })} title=${S.download || 'Download'}>${ICON_DOWNLOAD}</a>` : nothing}
        <audio preload="metadata" src=${this.src || nothing}
          @play=${this._onPlay}
          @pause=${this._onPause}
          @ended=${this._onEnded}
          @timeupdate=${this._sync}
          @loadedmetadata=${this._onMeta}
          @durationchange=${this._sync}></audio>
      </div>
    `;
  }

  _onMeta() {
    const a = this._audio;
    if (a) a.playbackRate = this._rate;
    this._sync();
  }
}

if (!customElements.get('gm-audio')) customElements.define('gm-audio', GmAudio);
