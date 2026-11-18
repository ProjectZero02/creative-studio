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
 * <story-timeline>: a small video editor for a Story Studio film.
 *
 * Shows a live preview (video, voice, music and titles played from their
 * own files, no render needed) and one lane per track. Clips can be moved,
 * trimmed at either edge, re-ordered (video), turned up or down, and titles
 * can be added and edited. Every finished change sends `changeEvent` with the
 * whole timeline JSON; the server validates and stores it, and "Export"
 * renders it with ffmpeg (services/story_timeline.py).
 */
import { LitElement, html, css, nothing } from 'https://cdn.jsdelivr.net/npm/lit@3.2.1/+esm';
import { repeat } from 'https://cdn.jsdelivr.net/npm/lit@3.2.1/directives/repeat.js/+esm';

const KINDS = ['video', 'voice', 'music', 'text'];
const LANE_LABEL = { video: 'Video', voice: 'Voice', music: 'Music', text: 'Titles' };
const MIN_LEN = 0.3;

const clone = (o) => JSON.parse(JSON.stringify(o));
const clamp = (v, lo, hi) => Math.min(hi, Math.max(lo, v));
const r3 = (v) => Math.round(v * 1000) / 1000;
const uid = () => Math.random().toString(16).slice(2, 10);

function clipLen(c) {
  if (c.dur !== undefined && c.out === undefined) return Math.max(0, +c.dur || 0);
  const tempo = +c.tempo || 1;
  return Math.max(0, ((+c.out || 0) - (+c.in || 0)) / tempo);
}
const clipEnd = (c) => (+c.start || 0) + clipLen(c);

function fmt(t) {
  t = Math.max(0, t || 0);
  const m = Math.floor(t / 60);
  const s = t - m * 60;
  return `${m}:${s < 10 ? '0' : ''}${s.toFixed(1)}`;
}

class StoryTimeline extends LitElement {
  static properties = {
    timelineJson: { type: String },
    mediaJson: { type: String },
    aspect: { type: String },
    busy: { type: Boolean },
    changeEvent: { type: String },
    _tl: { state: true },
    _t: { state: true },
    _playing: { state: true },
    _sel: { state: true },
    _pps: { state: true },
    _drag: { state: true },
  };

  static styles = css`
    :host { display: block; color: var(--sys-on-surface, #111); font: 14px/1.4 inherit; }
    .wrap { display: grid; gap: 12px; }
    .top { display: grid; grid-template-columns: minmax(0, 1fr) 300px; gap: 16px; align-items: start; }
    @media (max-width: 900px) { .top { grid-template-columns: 1fr; } }
    .stage { position: relative; background: #000; border-radius: 12px; overflow: hidden; width: 100%; }
    .stage.ar169 { aspect-ratio: 16 / 9; }
    .stage.ar916 { aspect-ratio: 9 / 16; max-height: 70vh; width: auto; margin: 0 auto; }
    .stage video { position: absolute; inset: 0; width: 100%; height: 100%; object-fit: contain; background: #000; }
    .stage video.hide { visibility: hidden; }
    .title { position: absolute; left: 7%; right: 7%; text-align: center; color: #fff; font-weight: 600;
             text-shadow: 0 2px 6px rgba(0,0,0,.7); pointer-events: none; line-height: 1.25; }
    .title.top { top: 8%; } .title.center { top: 50%; transform: translateY(-50%); } .title.bottom { bottom: 8%; }
    .empty { position: absolute; inset: 0; display: grid; place-items: center; color: #bbb; }
    .bar { display: flex; flex-wrap: wrap; gap: 8px; align-items: center; }
    .bar .time { font-variant-numeric: tabular-nums; min-width: 120px; color: var(--sys-on-surface-variant, #555); }
    .spacer { flex: 1; }
    button { font: inherit; min-height: 40px; padding: 0 14px; border-radius: 20px; cursor: pointer;
             border: 1px solid var(--sys-outline-variant, #c4c7c5); background: var(--sys-surface, #fff);
             color: var(--sys-on-surface, #111); display: inline-flex; align-items: center; gap: 6px; }
    button.primary { background: var(--sys-primary, #1a5fd8); color: var(--sys-on-primary, #fff); border-color: transparent; }
    button.icon { width: 40px; padding: 0; justify-content: center; }
    button:disabled { opacity: .45; cursor: default; }
    button:focus-visible, .clip:focus-visible, input:focus-visible, select:focus-visible, textarea:focus-visible {
      outline: 2px solid var(--gm-focus, var(--sys-primary, #1a5fd8)); outline-offset: 2px; }
    svg { width: 20px; height: 20px; fill: currentColor; }
    .panel { border: 1px solid var(--sys-outline-variant, #c4c7c5); border-radius: 12px; padding: 14px;
             background: var(--sys-surface-container-low, #f7f8fa); display: grid; gap: 10px; }
    .panel h3 { margin: 0; font-size: 15px; }
    .panel p { margin: 0; color: var(--sys-on-surface-variant, #555); font-size: 13px; }
    label { display: grid; gap: 4px; font-size: 13px; color: var(--sys-on-surface-variant, #555); }
    input[type=range] { width: 100%; }
    select, textarea, input[type=number] { font: inherit; padding: 8px; border-radius: 8px;
             border: 1px solid var(--sys-outline-variant, #c4c7c5); background: var(--sys-surface, #fff);
             color: var(--sys-on-surface, #111); }
    textarea { resize: vertical; min-height: 60px; }
    .row { display: flex; gap: 8px; flex-wrap: wrap; }
    .check { display: flex; gap: 8px; align-items: center; color: var(--sys-on-surface, #111); }
    .tracks { border: 1px solid var(--sys-outline-variant, #c4c7c5); border-radius: 12px; overflow: hidden;
              background: var(--sys-surface, #fff); display: grid; grid-template-columns: 76px minmax(0, 1fr); }
    .labels { border-right: 1px solid var(--sys-outline-variant, #c4c7c5); background: var(--sys-surface-container-low, #f7f8fa); }
    .labels div { height: 52px; display: flex; align-items: center; padding: 0 10px; font-size: 13px; font-weight: 600; }
    .labels .rl { height: 28px; }
    .scroll { overflow-x: auto; overflow-y: hidden; position: relative; }
    .inner { position: relative; }
    .ruler { height: 28px; position: relative; cursor: pointer; border-bottom: 1px solid var(--sys-outline-variant, #c4c7c5);
             touch-action: none; user-select: none; }
    .tick { position: absolute; top: 0; height: 100%; border-left: 1px solid var(--sys-outline-variant, #c4c7c5);
            font-size: 11px; padding-left: 3px; color: var(--sys-on-surface-variant, #555); }
    .lane { height: 52px; position: relative; border-bottom: 1px solid var(--sys-surface-container, #eceef1); }
    .clip { position: absolute; top: 6px; height: 40px; border-radius: 8px; box-sizing: border-box; overflow: hidden;
            padding: 0 14px; display: flex; align-items: center; font-size: 12px; font-weight: 600; white-space: nowrap;
            cursor: grab; user-select: none; touch-action: none; border: 2px solid transparent; color: #fff; }
    .clip.video { background: #3d5afe; } .clip.voice { background: #00897b; }
    .clip.music { background: #8e24aa; } .clip.text { background: #ef6c00; }
    .clip.sel { border-color: var(--sys-on-surface, #111); box-shadow: 0 0 0 2px var(--sys-surface, #fff) inset; }
    .clip.drag { opacity: .8; cursor: grabbing; z-index: 2; }
    .clip .fade { position: absolute; left: 0; top: 0; bottom: 0; background: linear-gradient(90deg, rgba(0,0,0,.35), transparent); pointer-events: none; }
    .clip span { overflow: hidden; text-overflow: ellipsis; pointer-events: none; position: relative; }
    .edge { position: absolute; top: 0; bottom: 0; width: 10px; cursor: ew-resize; }
    .edge.l { left: 0; } .edge.r { right: 0; }
    .edge::after { content: ''; position: absolute; top: 12px; bottom: 12px; left: 4px; width: 2px; background: rgba(255,255,255,.7); border-radius: 1px; }
    .head { position: absolute; top: 0; bottom: 0; width: 2px; background: #e53935; pointer-events: none; z-index: 3; }
    .hint { font-size: 12px; color: var(--sys-on-surface-variant, #555); margin: 0; }
    .sr { position: absolute; width: 1px; height: 1px; overflow: hidden; clip: rect(0 0 0 0); }
    @media (prefers-reduced-motion: reduce) { * { transition: none !important; } }
  `;

  constructor() {
    super();
    this.timelineJson = '';
    this.mediaJson = '{}';
    this.aspect = '16:9';
    this.busy = false;
    this.changeEvent = '';
    this._tl = null;
    this._seen = '';
    this._t = 0;
    this._playing = false;
    this._sel = '';
    this._pps = 0;
    this._drag = null;
    this._undo = [];
    this._audio = new Map();
    this._raf = 0;
    this._onMove = (e) => this._dragMove(e);
    this._onUp = (e) => this._dragEnd(e);
    this._onKey = (e) => this._key(e);
  }

  connectedCallback() { super.connectedCallback(); this.addEventListener('keydown', this._onKey); }
  disconnectedCallback() {
    super.disconnectedCallback();
    this.removeEventListener('keydown', this._onKey);
    this._pause();
    for (const a of this._audio.values()) { a.pause(); a.src = ''; }
    this._audio.clear();
  }

  willUpdate(changed) {
    if (changed.has('timelineJson') && this.timelineJson && this.timelineJson !== this._seen) {
      this._seen = this.timelineJson;
      try { this._tl = JSON.parse(this.timelineJson); } catch (e) { this._tl = null; }
      if (this._tl && !this._pps) this._fit();
    }
  }

  // ---------- model helpers ----------
  _track(kind) {
    const t = (this._tl && this._tl.tracks || []).find((x) => x.kind === kind);
    return t || { kind, clips: [] };
  }
  _clips(kind) { return this._track(kind).clips || []; }
  _duration() {
    const v = this._clips('video');
    const ends = (v.length ? v : KINDS.flatMap((k) => this._clips(k))).map(clipEnd);
    return Math.max(0, ...ends, 0);
  }
  _url(src) {
    try { return (JSON.parse(this.mediaJson || '{}'))[src] || ''; } catch (e) { return ''; }
  }
  _find(id) {
    for (const k of KINDS) {
      const c = this._clips(k).find((x) => x.id === id);
      if (c) return { kind: k, clip: c };
    }
    return null;
  }
  _layoutVideo() {
    let t = 0;
    this._clips('video').forEach((c, k) => {
      const len = clipLen(c);
      const fade = k === 0 ? 0 : Math.min(+c.fade_in || 0, len / 2, t);
      c.fade_in = r3(fade);
      c.start = r3(Math.max(0, t - fade));
      t = c.start + len;
    });
  }
  _fit() {
    const w = (this.renderRoot && this.renderRoot.querySelector('.scroll')?.clientWidth) || 800;
    const d = Math.max(4, this._duration());
    this._pps = clamp((w - 24) / d, 8, 400);
  }

  // ---------- changes ----------
  _snapshot() { this._undo.push(JSON.stringify(this._tl)); if (this._undo.length > 50) this._undo.shift(); }
  _commit() {
    this._layoutVideo();
    const json = JSON.stringify(this._tl);
    this._seen = json;
    this._tl = JSON.parse(json);
    if (this.changeEvent) this.dispatchEvent(new MesopEvent(this.changeEvent, { timeline: json }));
  }
  _change(fn) {
    if (this.busy || !this._tl) return;
    this._snapshot();
    fn();
    this._commit();
  }
  _undoLast() {
    if (!this._undo.length || this.busy) return;
    this._tl = JSON.parse(this._undo.pop());
    this._commit();
  }
  _addTitle() {
    this._change(() => {
      const id = uid();
      const start = r3(Math.min(this._t, Math.max(0, this._duration() - 1)));
      this._track('text').clips.push({ id, text: 'New title', start, dur: 3, pos: 'bottom', size: 48 });
      this._sel = id;
    });
  }
  _remove(id) {
    this._change(() => {
      for (const k of KINDS) {
        const tr = this._track(k);
        if (k === 'video' && tr.clips.length <= 1 && tr.clips.some((c) => c.id === id)) return;
        tr.clips = tr.clips.filter((c) => c.id !== id);
      }
      this._sel = '';
    });
  }
  _set(id, key, value) {
    this._change(() => { const f = this._find(id); if (f) f.clip[key] = value; });
  }
  _reorder(id, delta) {
    this._change(() => {
      const v = this._track('video').clips;
      const i = v.findIndex((c) => c.id === id);
      const j = i + delta;
      if (i < 0 || j < 0 || j >= v.length) return;
      [v[i], v[j]] = [v[j], v[i]];
    });
  }

  // ---------- playback ----------
  _togglePlay() { this._playing ? this._pause() : this._play(); }
  _play() {
    if (!this._tl) return;
    if (this._t >= this._duration() - 0.05) this._t = 0;
    this._playing = true;
    this._clock = { wall: performance.now(), t: this._t };
    const tick = () => {
      if (!this._playing) return;
      this._t = this._clock.t + (performance.now() - this._clock.wall) / 1000;
      if (this._t >= this._duration()) { this._t = this._duration(); this._pause(); return; }
      this._sync(true);
      this._raf = requestAnimationFrame(tick);
    };
    this._sync(true, true);
    this._raf = requestAnimationFrame(tick);
  }
  _pause() {
    this._playing = false;
    cancelAnimationFrame(this._raf);
    const v = this.renderRoot && this.renderRoot.querySelector('video');
    if (v) v.pause();
    for (const a of this._audio.values()) a.pause();
  }
  _seek(t) {
    this._t = clamp(t, 0, this._duration());
    if (this._playing) this._clock = { wall: performance.now(), t: this._t };
    this._sync(this._playing, true);
  }
  _activeVideo(t) {
    let found = null;
    for (const c of this._clips('video')) if (t >= c.start && t < clipEnd(c)) found = c;
    return found;
  }
  _speaking(t) {
    const v = this._activeVideo(t);
    if (v && (+v.gain || 0) > 0) return true;
    return this._clips('voice').some((c) => t >= c.start && t < clipEnd(c));
  }
  _sync(playing, force = false) {
    const t = this._t;
    const v = this.renderRoot && this.renderRoot.querySelector('video');
    const clip = this._activeVideo(t);
    if (v) {
      if (!clip) { v.pause(); v.classList.add('hide'); }
      else {
        v.classList.remove('hide');
        const url = this._url(clip.src);
        const want = (+clip.in || 0) + (t - clip.start);
        if (v.dataset.src !== url) {
          v.dataset.src = url;
          v.src = url;
          v.addEventListener('loadedmetadata', () => { v.currentTime = want; if (this._playing) v.play().catch(() => {}); }, { once: true });
        } else if (force || Math.abs(v.currentTime - want) > 0.3) {
          try { v.currentTime = want; } catch (e) { /* not loaded yet */ }
        }
        v.volume = clamp(+clip.gain || 0, 0, 1);
        v.muted = !(+clip.gain > 0);
        if (playing && v.paused && v.readyState >= 2) v.play().catch(() => {});
        if (!playing && !v.paused) v.pause();
      }
    }
    const ducking = (this._track('music').duck !== false) && this._speaking(t);
    const live = new Set();
    for (const kind of ['voice', 'music']) {
      for (const c of this._clips(kind)) {
        if (!(t >= c.start && t < clipEnd(c))) continue;
        live.add(c.id);
        let a = this._audio.get(c.id);
        const url = this._url(c.src);
        if (!a || a.dataset.src !== url) {
          if (a) a.pause();
          a = new Audio();
          a.preload = 'auto';
          a.dataset.src = url;
          a.src = url;
          a.loop = kind === 'music';
          this._audio.set(c.id, a);
        }
        const tempo = +c.tempo || 1;
        a.playbackRate = tempo;
        let want = (+c.in || 0) + (t - c.start) * tempo;
        if (a.loop && a.duration && isFinite(a.duration)) want %= a.duration;
        if (force || Math.abs(a.currentTime - want) > 0.35) { try { a.currentTime = want; } catch (e) { /* loading */ } }
        a.volume = clamp((+c.gain || 0) * (kind === 'music' && ducking ? 0.35 : 1), 0, 1);
        if (playing && a.paused) a.play().catch(() => {});
        if (!playing && !a.paused) a.pause();
      }
    }
    for (const [id, a] of this._audio) if (!live.has(id) && !a.paused) a.pause();
  }

  // ---------- dragging ----------
  _dragStart(e, kind, clip, mode) {
    if (this.busy || e.button > 0) return;
    e.preventDefault();
    e.stopPropagation();
    // Keep keyboard focus on the clip (Space, Delete, arrows, Ctrl+Z).
    const el = e.currentTarget.classList.contains('clip') ? e.currentTarget : e.currentTarget.parentElement;
    el?.focus({ preventScroll: true });
    this._sel = clip.id;
    const tr = this._track(kind);
    this._drag = {
      kind, id: clip.id, mode, x0: e.clientX, moved: false,
      orig: clone(clip), before: JSON.stringify(this._tl),
      // How far a clip's source can be stretched to the right.
      max: kind === 'music' ? 36000 : Math.max(+clip.src_max || 0, +clip.out || 0),
      index: tr.clips.findIndex((c) => c.id === clip.id),
    };
    window.addEventListener('pointermove', this._onMove);
    window.addEventListener('pointerup', this._onUp, { once: true });
  }
  _dragMove(e) {
    const d = this._drag;
    if (!d) return;
    const dt = (e.clientX - d.x0) / this._pps;
    if (Math.abs(e.clientX - d.x0) > 3) d.moved = true;
    if (!d.moved) return;
    const f = this._find(d.id);
    if (!f) return;
    const c = f.clip, o = d.orig;
    const tempo = +o.tempo || 1;
    if (d.kind === 'text') {
      if (d.mode === 'move') c.start = r3(Math.max(0, o.start + dt));
      else if (d.mode === 'r') c.dur = r3(Math.max(MIN_LEN, o.dur + dt));
      else { const s = clamp(o.start + dt, 0, o.start + o.dur - MIN_LEN); c.dur = r3(o.dur - (s - o.start)); c.start = r3(s); }
    } else if (d.mode === 'move') {
      if (d.kind === 'video') c._dx = dt; // re-ordered on drop
      else c.start = r3(Math.max(0, o.start + dt));
    } else if (d.mode === 'r') {
      c.out = r3(clamp(o.out + dt * tempo, o.in + MIN_LEN * tempo, d.max || o.out));
    } else {
      const nin = clamp(o.in + dt * tempo, 0, o.out - MIN_LEN * tempo);
      c.in = r3(nin);
      if (d.kind !== 'video') c.start = r3(Math.max(0, o.start + (nin - o.in) / tempo));
    }
    if (d.kind === 'video' && d.mode !== 'move') this._layoutVideo();
    this.requestUpdate();
  }
  _dragEnd() {
    window.removeEventListener('pointermove', this._onMove);
    const d = this._drag;
    this._drag = null;
    if (!d || !d.moved) { if (d) this.requestUpdate(); return; }
    this._dragEndedAt = Date.now();
    const f = this._find(d.id);
    if (f && d.kind === 'video' && d.mode === 'move') {
      const v = this._track('video').clips;
      const centre = d.orig.start + clipLen(d.orig) / 2 + (f.clip._dx || 0);
      delete f.clip._dx;
      const rest = v.filter((c) => c.id !== d.id);
      let at = rest.findIndex((c) => centre < c.start + clipLen(c) / 2);
      if (at < 0) at = rest.length;
      rest.splice(at, 0, f.clip);
      this._track('video').clips = rest;
    }
    this._undo.push(d.before);
    this._commit();
    this._seek(this._t);
  }
  _rulerDown(e) {
    const scroll = this.renderRoot.querySelector('.scroll');
    const seekAt = (ev) => {
      const r = scroll.getBoundingClientRect();
      this._seek((ev.clientX - r.left + scroll.scrollLeft) / this._pps);
    };
    seekAt(e);
    const mv = (ev) => seekAt(ev);
    window.addEventListener('pointermove', mv);
    window.addEventListener('pointerup', () => window.removeEventListener('pointermove', mv), { once: true });
  }

  _key(e) {
    const tag = (e.composedPath()[0]?.tagName || '').toLowerCase();
    if (['input', 'textarea', 'select'].includes(tag)) return;
    if (e.key === ' ') { e.preventDefault(); this._togglePlay(); }
    else if ((e.ctrlKey || e.metaKey) && e.key.toLowerCase() === 'z') { e.preventDefault(); this._undoLast(); }
    else if ((e.key === 'Delete' || e.key === 'Backspace') && this._sel) { e.preventDefault(); this._remove(this._sel); }
    else if ((e.key === 'ArrowLeft' || e.key === 'ArrowRight') && this._sel) {
      const f = this._find(this._sel);
      if (!f) return;
      e.preventDefault();
      const step = e.key === 'ArrowLeft' ? -1 : 1;
      if (f.kind === 'video') this._reorder(this._sel, step);
      else this._set(this._sel, 'start', r3(Math.max(0, (+f.clip.start || 0) + step * 0.1)));
    }
  }

  // ---------- render ----------
  _zoom(f) { this._pps = clamp(this._pps * f, 4, 400); }

  _clipEl(kind, c) {
    const left = (+c.start || 0) * this._pps + (kind === 'video' && c._dx ? c._dx * this._pps : 0);
    const width = Math.max(14, clipLen(c) * this._pps);
    const label = kind === 'text' ? c.text : (c.label || (kind === 'music' ? 'Music' : kind === 'voice' ? 'Voice line' : 'Clip'));
    const sel = this._sel === c.id;
    const dragging = this._drag && this._drag.id === c.id;
    return html`<div class="clip ${kind} ${sel ? 'sel' : ''} ${dragging ? 'drag' : ''}" tabindex="0" role="button"
        aria-pressed=${sel ? 'true' : 'false'}
        aria-label="${`${LANE_LABEL[kind]}: ${label}, ${fmt(c.start)} to ${fmt(clipEnd(c))}`}"
        style="left:${left}px;width:${width}px"
        @pointerdown=${(e) => this._dragStart(e, kind, c, 'move')}
        @click=${() => { if (Date.now() - (this._dragEndedAt || 0) < 250) return; this._sel = c.id; }}
        @focus=${() => { this._sel = c.id; }}>
      ${kind === 'video' && c.fade_in > 0 ? html`<div class="fade" style="width:${c.fade_in * this._pps}px"></div>` : nothing}
      <span>${label}</span>
      <div class="edge l" @pointerdown=${(e) => this._dragStart(e, kind, c, 'l')}></div>
      <div class="edge r" @pointerdown=${(e) => this._dragStart(e, kind, c, 'r')}></div>
    </div>`;
  }

  _ticks(total) {
    const pps = this._pps;
    const step = [0.5, 1, 2, 5, 10, 15, 30, 60].find((s) => s * pps >= 60) || 120;
    const out = [];
    for (let t = 0; t <= total + step; t += step) {
      out.push(html`<div class="tick" style="left:${t * pps}px">${fmt(t).replace('.0', '')}</div>`);
    }
    return out;
  }

  _inspector() {
    const f = this._sel ? this._find(this._sel) : null;
    if (!f) {
      return html`<div class="panel">
        <h3>Edit your film</h3>
        <p>Select a clip to change it. Drag a clip to move it, drag its edges to trim it. Drag a video clip
          sideways to change the scene order. Space plays, Ctrl+Z undoes, Delete removes the selected clip.</p>
        <button @click=${this._addTitle} ?disabled=${this.busy}>${ICON.title} Add a title at the playhead</button>
      </div>`;
    }
    const { kind, clip: c } = f;
    const pct = Math.round((+c.gain || 0) * 100);
    const vid = this._clips('video');
    const vi = vid.findIndex((x) => x.id === c.id);
    return html`<div class="panel">
      <h3>${kind === 'text' ? 'Title' : kind === 'video' ? (c.label || 'Video clip') : kind === 'voice' ? 'Voice line' : 'Music'}</h3>
      <p>${fmt(c.start)} to ${fmt(clipEnd(c))} (${clipLen(c).toFixed(1)} s)</p>
      ${kind === 'text' ? html`
        <label>Text<textarea .value=${c.text} @change=${(e) => this._set(c.id, 'text', e.target.value.slice(0, 300))}></textarea></label>
        <div class="row">
          <label>Position<select @change=${(e) => this._set(c.id, 'pos', e.target.value)}>
            ${['top', 'center', 'bottom'].map((p) => html`<option value=${p} ?selected=${c.pos === p}>${p[0].toUpperCase() + p.slice(1)}</option>`)}
          </select></label>
          <label>Size<select @change=${(e) => this._set(c.id, 'size', +e.target.value)}>
            ${[[32, 'Small'], [48, 'Medium'], [72, 'Large'], [104, 'Huge']].map(([v, l]) => html`<option value=${v} ?selected=${+c.size === v}>${l}</option>`)}
          </select></label>
          <label>Seconds<input type="number" min="0.5" max="60" step="0.5" .value=${String(c.dur)}
            @change=${(e) => this._set(c.id, 'dur', clamp(+e.target.value || 1, 0.2, 3600))}></label>
        </div>` : html`
        <label>${kind === 'video' ? 'Clip sound (speech and room)' : 'Volume'}: ${pct}%
          <input type="range" min="0" max="200" step="5" .value=${String(pct)}
            aria-label="${kind === 'video' ? 'Clip sound volume' : 'Volume'}"
            @change=${(e) => this._set(c.id, 'gain', +e.target.value / 100)}></label>`}
      ${kind === 'video' ? html`
        <label>Fade in from the clip before<select ?disabled=${vi === 0} @change=${(e) => this._set(c.id, 'fade_in', +e.target.value)}>
          ${[[0, 'Cut (no fade)'], [0.25, '0.25 s'], [0.5, '0.5 s'], [1, '1 s']].map(([v, l]) => html`<option value=${v} ?selected=${+c.fade_in === v}>${l}</option>`)}
        </select></label>
        <div class="row">
          <button ?disabled=${this.busy || vi <= 0} @click=${() => this._reorder(c.id, -1)}>Move earlier</button>
          <button ?disabled=${this.busy || vi >= vid.length - 1} @click=${() => this._reorder(c.id, 1)}>Move later</button>
        </div>` : nothing}
      ${kind === 'music' ? html`<label class="check"><input type="checkbox" .checked=${this._track('music').duck !== false}
          @change=${(e) => this._change(() => { this._track('music').duck = e.target.checked; })}>
          Lower the music while someone speaks</label>` : nothing}
      <div class="row">
        <button @click=${() => this._remove(c.id)} ?disabled=${this.busy || (kind === 'video' && vid.length <= 1)}>${ICON.del} Remove</button>
        <button @click=${() => { this._sel = ''; }}>Done</button>
      </div>
    </div>`;
  }

  render() {
    if (!this._tl) return html`<p class="hint">No timeline yet. Render the film first.</p>`;
    if (!this._pps) this._fit();
    const total = this._duration();
    const width = Math.max(total * this._pps + 120, 200);
    const t = this._t;
    const titles = this._clips('text').filter((c) => t >= c.start && t < clipEnd(c));
    const h = this.renderRoot?.querySelector('.stage')?.clientHeight || 360;
    return html`<div class="wrap">
      <div class="top">
        <div>
          <div class="stage ${this.aspect === '9:16' ? 'ar916' : 'ar169'}">
            <video playsinline preload="auto" aria-label="Preview"></video>
            ${titles.map((c) => html`<div class="title ${c.pos}" style="font-size:${Math.max(10, (+c.size || 48) * h / 720)}px">${c.text}</div>`)}
            ${total ? nothing : html`<div class="empty">Empty timeline</div>`}
          </div>
          <div class="bar" style="margin-top:8px">
            <button class="primary icon" aria-label=${this._playing ? 'Pause' : 'Play'} @click=${this._togglePlay}>${this._playing ? ICON.pause : ICON.play}</button>
            <button class="icon" aria-label="Back to start" @click=${() => this._seek(0)}>${ICON.start}</button>
            <span class="time" aria-live="off">${fmt(t)} / ${fmt(total)}</span>
            <span class="spacer"></span>
            <button @click=${this._addTitle} ?disabled=${this.busy}>${ICON.title} Add title</button>
            <button class="icon" aria-label="Undo" ?disabled=${this.busy || !this._undo.length} @click=${this._undoLast}>${ICON.undo}</button>
            <button class="icon" aria-label="Zoom out" @click=${() => this._zoom(1 / 1.5)}>${ICON.minus}</button>
            <button class="icon" aria-label="Zoom in" @click=${() => this._zoom(1.5)}>${ICON.plus}</button>
          </div>
        </div>
        ${this._inspector()}
      </div>
      <div class="tracks" role="group" aria-label="Timeline">
        <div class="labels"><div class="rl"></div>${KINDS.map((k) => html`<div>${LANE_LABEL[k]}</div>`)}</div>
        <div class="scroll">
          <div class="inner" style="width:${width}px">
            <div class="ruler" @pointerdown=${(e) => this._rulerDown(e)} aria-hidden="true">${this._ticks(total)}</div>
            ${KINDS.map((k) => html`<div class="lane" aria-label="${LANE_LABEL[k]} track">${repeat(this._clips(k), (c) => c.id, (c) => this._clipEl(k, c))}</div>`)}
            <div class="head" style="left:${t * this._pps}px"></div>
          </div>
        </div>
      </div>
    </div>`;
  }

  firstUpdated() {
    // Fit the whole film to the lane width once the lanes exist.
    this._fit();
  }

  updated() {
    if (!this._playing) this._sync(false);
  }
}

const svg = (d) => html`<svg viewBox="0 0 24 24" aria-hidden="true"><path d="${d}"></path></svg>`;
const ICON = {
  play: svg('M8 5v14l11-7z'),
  pause: svg('M6 5h4v14H6zM14 5h4v14h-4z'),
  start: svg('M6 6h2v12H6zm3.5 6 8.5 6V6z'),
  undo: svg('M12.5 8c-2.65 0-5.05 1-6.9 2.6L2 7v9h9l-3.62-3.62A7.95 7.95 0 0 1 20.4 16l2.36-.78A10.5 10.5 0 0 0 12.5 8z'),
  plus: svg('M19 13h-6v6h-2v-6H5v-2h6V5h2v6h6z'),
  minus: svg('M19 13H5v-2h14z'),
  title: svg('M5 4v3h5.5v12h3V7H19V4z'),
  del: svg('M6 19a2 2 0 0 0 2 2h8a2 2 0 0 0 2-2V7H6zM19 4h-3.5l-1-1h-5l-1 1H5v2h14z'),
};

customElements.define('story-timeline', StoryTimeline);
