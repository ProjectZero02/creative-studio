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
 * <story-timeline>: the Story Studio film editor.
 *
 * The player plays ONE file: the server's render of the current timeline
 * (`previewUrl`, a fast low-bitrate proxy rebuilt after each edit, or the
 * film itself when nothing changed since it was made), so the preview is
 * the render. Below it, a lean strip: shots in order (drag to reorder, trim
 * handles, split, delete, transition per join), titles, and the voice and
 * music lanes (select to set a level; voice lines follow their scene).
 *
 * Sync: every edit is sent as the whole timeline tagged `rev`
 * ("<editor id>:<n>"). The server echoes it back; an echo carrying this
 * editor's own tag is ignored, so a slow echo never undoes a newer edit.
 * A timeline without this editor's tag (a new render, music, a restored
 * version) replaces the editor's and clears undo.
 *
 * Keys: Space play/pause, F fullscreen, Left/Right seek 1 s (Shift: 5 s),
 * Alt+Left/Right move the selected shot or title, S split, Delete,
 * Ctrl+Z / Ctrl+Shift+Z.
 */
import { LitElement, html, css, nothing } from '/ui/vendor/lit-3.2.1.js';
import { repeat } from '/ui/vendor/lit-3.2.1.js';

const KINDS = ['video', 'voice', 'music', 'text'];
const LANE_LABEL = { video: 'Video', voice: 'Voice', music: 'Music', text: 'Titles' };
const MIN_LEN = 0.3;
const VOICE_GAP = 0.05;

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

/** The clip's "100%": its sound as first levelled (never above it). */
const levelOf = (c) => +c.level || Math.max(1, +c.gain || 0);

/** Voice lines in time order, none running into the next (story_timeline.no_overlap). */
function noOverlap(lines) {
  const out = [];
  for (const line of [...lines].sort((a, b) => (+b.start || 0) - (+a.start || 0))) {
    const next = out[0];
    if (next && clipEnd(line) > (+next.start || 0) - VOICE_GAP + 1e-6) {
      const room = (+next.start || 0) - VOICE_GAP - (+line.start || 0);
      if (room < MIN_LEN) continue;
      line.out = r3((+line.in || 0) + room * (+line.tempo || 1));
    }
    out.unshift(line);
  }
  return out;
}

class StoryTimeline extends LitElement {
  static properties = {
    timelineJson: { type: String },
    mediaJson: { type: String },
    previewUrl: { type: String },
    previewState: { type: String },
    aspect: { type: String },
    busy: { type: Boolean },
    changeEvent: { type: String },
    pointEvent: { type: String },
    _tl: { state: true },
    _playing: { state: true },
    _sel: { state: true },
    _pps: { state: true },
    _drag: { state: true },
    _full: { state: true },
  };

  static styles = css`
    :host {
      display: block; color: var(--sys-on-surface, #e7e9ed); font: 14px/1.4 inherit;
      --tl-h: var(--gm-control-h, 40px);
      --tl-radius: var(--gm-radius-md, 12px);
      --tl-radius-sm: var(--gm-radius-sm, 8px);
      --tl-tonal: var(--gm-tonal, rgba(255,255,255,.08));
      --tl-tonal-hover: var(--gm-tonal-hover, rgba(255,255,255,.12));
      --tl-tonal-press: var(--gm-tonal-press, rgba(255,255,255,.16));
      --tl-field: var(--gm-field-bg, rgba(255,255,255,.05));
      --tl-line: var(--gm-field-line, rgba(255,255,255,.10));
      --tl-panel: var(--sys-surface-container-low, #16181d);
      --tl-base: var(--sys-surface-container-high, #22252c);
      --tl-muted: var(--sys-on-surface-variant, #a6abb5);
      --tl-accent: var(--sys-primary, #8cb4ff);
      --tl-video: color-mix(in srgb, var(--tl-accent) 34%, var(--tl-base));
      --tl-voice: color-mix(in srgb, #3ccf9b 30%, var(--tl-base));
      --tl-music: color-mix(in srgb, #b98cff 30%, var(--tl-base));
      --tl-text: color-mix(in srgb, #ffb35c 30%, var(--tl-base));
    }
    .wrap { display: grid; gap: 12px; }
    /* Preview and inspector share one row height. */
    .top { display: grid; grid-template-columns: minmax(0, 1fr) 300px; gap: 12px; align-items: stretch; }
    @media (max-width: 900px) { .top { grid-template-columns: 1fr; } }
    .viewer { display: grid; gap: 8px; align-content: start; min-width: 0; }
    .stage { position: relative; background: #000; border-radius: var(--tl-radius); overflow: hidden; width: 100%; outline: none; }
    .stage.ar169 { aspect-ratio: 16 / 9; }
    .stage.ar916 { aspect-ratio: 9 / 16; max-height: 64vh; width: auto; margin: 0 auto; }
    .stage video { position: absolute; inset: 0; width: 100%; height: 100%; object-fit: contain; background: #000; }
    .stage:fullscreen { border-radius: 0; aspect-ratio: auto; max-height: none; width: 100%; height: 100%; }
    .stage .poster { position: absolute; inset: 0; width: 100%; height: 100%; object-fit: contain; }
    .badge { position: absolute; top: 10px; left: 10px; z-index: 2; display: inline-flex; align-items: center; gap: 8px;
             padding: 4px 10px; border-radius: 999px; font-size: 12px; font-weight: 500; color: #fff;
             background: rgba(0,0,0,.6); pointer-events: none; }
    .badge .dot { width: 8px; height: 8px; border-radius: 50%; background: var(--tl-accent); animation: pulse 1s ease-in-out infinite alternate; }
    @keyframes pulse { from { opacity: .35; } to { opacity: 1; } }
    .speech { position: absolute; top: 8px; bottom: 8px; border-radius: 6px; box-sizing: border-box; overflow: hidden;
              display: flex; align-items: center; gap: 6px; padding: 0 10px; font-size: 12px; white-space: nowrap; cursor: pointer;
              color: var(--tl-muted); background: color-mix(in srgb, var(--tl-voice) 40%, transparent);
              border: 1px dashed color-mix(in srgb, var(--tl-voice) 90%, var(--tl-line)); outline: 2px solid transparent; outline-offset: -2px; }
    .speech svg { width: 16px; height: 16px; flex: none; fill: currentColor; }
    .speech span { overflow: hidden; text-overflow: ellipsis; }
    .speech.muted { opacity: .55; }
    .speech.sel { outline-color: var(--tl-accent); }
    .transport { display: grid; grid-template-columns: 1fr auto 1fr; align-items: center; height: var(--tl-h); }
    .transport .time { font-variant-numeric: tabular-nums; color: var(--tl-muted); font-size: 13px; }
    .transport .mid { display: flex; gap: 8px; }
    .transport .end { display: flex; justify-content: flex-end; }
    .bar { display: flex; gap: 8px; align-items: center; height: var(--tl-h); }
    .sep { width: 1px; height: 24px; background: var(--tl-line); margin: 0 4px; }
    .spacer { flex: 1; }
    button { font: inherit; font-size: 14px; font-weight: 500; height: var(--tl-h); padding: 0 14px; border-radius: var(--tl-radius);
             cursor: pointer; border: 0; background: var(--tl-tonal); color: var(--sys-on-surface, #e7e9ed);
             display: inline-flex; align-items: center; justify-content: center; gap: 6px; white-space: nowrap;
             transition: background-color 150ms ease, transform 150ms ease; }
    button:hover:not(:disabled) { background: var(--tl-tonal-hover); }
    button:active:not(:disabled) { background: var(--tl-tonal-press); transform: scale(.98); }
    button.primary { background: var(--tl-accent); color: var(--sys-on-primary, #0b1d3f); }
    button.primary:hover:not(:disabled) { background: color-mix(in srgb, var(--tl-accent) 88%, #fff); }
    button.icon { width: var(--tl-h); padding: 0; }
    button.ghost { background: transparent; }
    button.ghost:hover:not(:disabled) { background: var(--tl-tonal); }
    button:disabled { opacity: .4; cursor: default; }
    button:focus-visible, .clip:focus-visible, .stage:focus-visible, input:focus-visible, select:focus-visible, textarea:focus-visible {
      outline: 2px solid var(--gm-focus, var(--tl-accent)); outline-offset: 2px; }
    svg { width: 20px; height: 20px; fill: currentColor; flex: none; }
    .panel { border-radius: var(--tl-radius); padding: 16px; background: var(--tl-panel); display: flex; flex-direction: column;
             gap: 14px; min-height: 0; overflow-y: auto; }
    .panel h3 { margin: 0; font-size: 15px; font-weight: 600; }
    .panel .meta { margin: -10px 0 0; color: var(--tl-muted); font-size: 13px; font-variant-numeric: tabular-nums; }
    .panel .empty { margin: auto; color: var(--tl-muted); text-align: center; }
    .field { display: grid; gap: 6px; font-size: 13px; color: var(--tl-muted); }
    .field .val { float: right; color: var(--sys-on-surface, #e7e9ed); font-variant-numeric: tabular-nums; }
    .grid2 { display: grid; grid-template-columns: 1fr 1fr; gap: 8px; }
    select, textarea { font: inherit; font-size: 14px; color: var(--sys-on-surface, #e7e9ed);
             background: var(--tl-field); border: 1px solid var(--tl-line); border-radius: var(--tl-radius-sm); box-sizing: border-box; width: 100%; }
    select { height: var(--tl-h); padding: 0 10px; }
    select option { background: var(--tl-base); }
    textarea { resize: vertical; min-height: 72px; padding: 10px; }
    input[type=range] { width: 100%; accent-color: var(--tl-accent); height: 20px; margin: 0; }
    .check { display: flex; gap: 8px; align-items: center; font-size: 14px; color: var(--sys-on-surface, #e7e9ed); }
    .check input { width: 18px; height: 18px; accent-color: var(--tl-accent); margin: 0; }
    .zoom { display: flex; align-items: center; gap: 4px; }
    .zoom input { width: 120px; }
    .tracks { border-radius: var(--tl-radius); overflow: hidden; background: var(--tl-panel);
              display: grid; grid-template-columns: 120px minmax(0, 1fr); }
    .heads { border-right: 1px solid var(--tl-line); }
    .heads div { display: flex; align-items: center; gap: 8px; padding: 0 12px; font-size: 13px; font-weight: 500;
                 color: var(--tl-muted); border-bottom: 1px solid var(--tl-line); box-sizing: border-box; }
    .heads svg { width: 18px; height: 18px; }
    .heads .rl { height: 28px; }
    .h-video { height: 64px; } .h-voice, .h-music { height: 44px; } .h-text { height: 40px; }
    .scroll { overflow-x: auto; overflow-y: hidden; position: relative; scrollbar-width: thin; scrollbar-color: var(--tl-line) transparent; }
    .inner { position: relative; }
    .ruler { height: 28px; position: relative; cursor: pointer; border-bottom: 1px solid var(--tl-line); touch-action: none; user-select: none; box-sizing: border-box; }
    .tick { position: absolute; top: 0; height: 100%; border-left: 1px solid var(--tl-line); font-size: 11px; padding: 6px 0 0 4px;
            color: var(--tl-muted); font-variant-numeric: tabular-nums; box-sizing: border-box; }
    .lane { position: relative; border-bottom: 1px solid var(--tl-line); box-sizing: border-box; }
    .clip { position: absolute; top: 4px; bottom: 4px; border-radius: 6px; box-sizing: border-box; overflow: hidden;
            padding: 0 12px; display: flex; align-items: center; font-size: 12px; font-weight: 500; white-space: nowrap;
            cursor: grab; user-select: none; touch-action: none; outline: 2px solid transparent; outline-offset: -2px;
            color: var(--sys-on-surface, #e7e9ed); background-size: auto 100%; background-repeat: repeat-x; }
    .clip.narrow { padding: 0 4px; justify-content: center; }
    .clip.fixed { cursor: pointer; }
    .clip.video { background-color: var(--tl-video); } .clip.voice { background-color: var(--tl-voice); }
    .clip.music { background-color: var(--tl-music); } .clip.text { background-color: var(--tl-text); }
    .clip.thumbs { color: #fff; text-shadow: 0 1px 3px rgba(0,0,0,.8); }
    .clip.thumbs::before { content: ''; position: absolute; inset: 0; background: linear-gradient(0deg, rgba(0,0,0,.55), rgba(0,0,0,0) 70%); }
    .clip.sel { outline-color: var(--tl-accent); }
    .clip.drag { opacity: .85; cursor: grabbing; z-index: 2; }
    .clip .fade { position: absolute; left: 0; top: 0; bottom: 0; background: linear-gradient(90deg, rgba(0,0,0,.45), transparent); pointer-events: none; }
    .clip .fade.fade-black { background: linear-gradient(90deg, rgba(0,0,0,.92), transparent); }
    .clip span { overflow: hidden; text-overflow: ellipsis; pointer-events: none; position: relative; align-self: flex-end; padding-bottom: 6px; }
    .clip.voice span, .clip.music span, .clip.text span { align-self: center; padding: 0; }
    .edge { position: absolute; top: 0; bottom: 0; width: 8px; cursor: ew-resize; z-index: 1; }
    .edge.l { left: 0; } .edge.r { right: 0; }
    .clip.sel .edge { background: var(--tl-accent); }
    .head { position: absolute; top: 0; bottom: 0; width: 2px; margin-left: -1px; background: var(--tl-accent); pointer-events: none; z-index: 3; }
    .head::before { content: ''; position: absolute; top: 0; left: -5px; width: 12px; height: 10px; background: var(--tl-accent); border-radius: 2px 2px 6px 6px; }
    @media (max-width: 600px) {
      .tracks { grid-template-columns: 48px minmax(0, 1fr); }
      .heads div span { display: none; }
      .bar .lbl-hide { display: none; }
      .bar > button { width: var(--tl-h); padding: 0; flex: none; }
      .bar { gap: 6px; }
      .sep { margin: 0; }
      .zoom input { display: none; }
    }
    @media (prefers-reduced-motion: reduce) { * { transition: none !important; animation: none !important; } }
  `;

  constructor() {
    super();
    this.timelineJson = '';
    this.mediaJson = '{}';
    this.previewUrl = '';
    this.previewState = 'film';
    this.aspect = '16:9';
    this.busy = false;
    this.changeEvent = '';
    this.pointEvent = '';
    this._id = uid();
    this._seq = 0;
    this._pointed = -1;
    this._tl = null;
    this._seen = '';
    this._t = 0;
    this._playing = false;
    this._sel = '';
    this._pps = 0;
    this._drag = null;
    this._full = false;
    this._undo = [];
    this._redo = [];
    this._raf = 0;
    this._onMove = (e) => this._dragMove(e);
    this._onUp = (e) => this._dragEnd(e);
    this._onKey = (e) => this._key(e);
    this._onFull = () => { this._full = document.fullscreenElement === this._stage(); };
  }

  connectedCallback() {
    super.connectedCallback();
    this.addEventListener('keydown', this._onKey);
    document.addEventListener('fullscreenchange', this._onFull);
  }
  disconnectedCallback() {
    super.disconnectedCallback();
    this.removeEventListener('keydown', this._onKey);
    document.removeEventListener('fullscreenchange', this._onFull);
    cancelAnimationFrame(this._raf);
    const v = this._video();
    if (v) v.pause();
  }

  /** Accept a timeline from the server unless it is this editor's own echo. */
  willUpdate(changed) {
    if (!changed.has('timelineJson') || !this.timelineJson || this.timelineJson === this._seen) return;
    this._seen = this.timelineJson;
    let next;
    try { next = JSON.parse(this.timelineJson); } catch (e) { return; }
    if (!next) return;
    const rev = String(next.rev || '');
    if (this._tl && rev.startsWith(`${this._id}:`)) return;  // our own edit, maybe an old one
    const hadTl = !!this._tl;
    const oldDur = hadTl ? this._duration() : 0;
    this._tl = next;
    if (hadTl) {
      // Someone else changed the film (a render, music, a restored version):
      // undo would write the old film back over it.
      this._undo = [];
      this._redo = [];
      if (this._sel && !this._find(this._sel)) this._sel = '';
      if (Math.abs(this._duration() - oldDur) > 1) this._pps = 0;
    }
    if (this._t > this._duration()) this._t = this._duration();
    if (!this._pps) this._fit();
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
  _mediaMap() {
    try { return JSON.parse(this.mediaJson || '{}') || {}; } catch (e) { return {}; }
  }
  _thumb(c) {
    if (!c || c.scene === undefined || c.scene < 0) return '';
    return this._mediaMap()[`thumb:${c.scene}`] || '';
  }
  _find(id) {
    for (const k of KINDS) {
      const c = this._clips(k).find((x) => x.id === id);
      if (c) return { kind: k, clip: c };
    }
    return null;
  }
  /** Shot names: "Scene 3", and "Scene 3a", "Scene 3b" for split parts. */
  _labels() {
    const out = {};
    const count = {};
    const seen = {};
    for (const c of this._clips('video')) if (+c.scene >= 0) count[c.scene] = (count[c.scene] || 0) + 1;
    for (const c of this._clips('video')) {
      const base = +c.scene >= 0 ? `Scene ${+c.scene + 1}` : (c.label || 'Clip');
      if (+c.scene >= 0 && count[c.scene] > 1) {
        const n = seen[c.scene] = (seen[c.scene] || 0) + 1;
        const part = String.fromCharCode(96 + Math.min(n, 26));
        out[c.id] = { full: `${base}${part}`, short: `${+c.scene + 1}${part}` };
      } else {
        out[c.id] = { full: base, short: +c.scene >= 0 ? String(+c.scene + 1) : base.slice(0, 3) };
      }
    }
    return out;
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
  _pushUndo(json) {
    this._undo.push(json);
    if (this._undo.length > 50) this._undo.shift();
    this._redo = [];
  }
  _snapshot() { const json = JSON.stringify(this._tl); this._pushUndo(json); return json; }
  /** Voice lines move with their scene's clip (story_timeline.follow_scenes). */
  _follow(prevJson) {
    let prev;
    try { prev = JSON.parse(prevJson); } catch (e) { return; }
    const pv = ((prev.tracks || []).find((t) => t.kind === 'video') || { clips: [] }).clips || [];
    const vids = this._clips('video');
    const linked = (c) => c.scene !== undefined && c.scene !== null && +c.scene >= 0;
    const voice = this._track('voice');
    const keep = [];
    for (const a of voice.clips || []) {
      const at = +a.start || 0;
      const inside = (c) => at >= c.start - 0.001 && at < clipEnd(c);
      let p = linked(a) ? (pv.find((c) => c.scene === +a.scene && inside(c)) || pv.find((c) => c.scene === +a.scene)) : pv.find(inside);
      if (!p || !linked(p)) { keep.push(a); continue; }
      a.scene = +p.scene;
      const src = (+p.in || 0) + (at - p.start);
      const now = vids.filter((c) => c.scene === a.scene);
      if (!now.length) continue;
      const c = now.find((x) => src >= (+x.in || 0) - 0.001 && src < (+x.out || 0)) || now[0];
      a.start = r3(Math.max(0, c.start + (src - (+c.in || 0))));
      keep.push(a);
    }
    voice.clips = noOverlap(keep);
    const oldDur = Math.max(0, ...pv.map(clipEnd));
    const dur = this._duration();
    for (const m of this._clips('music')) {
      if (oldDur > 0 && Math.abs(clipEnd(m) - oldDur) < 0.05 && dur > m.start) m.out = r3((+m.in || 0) + (dur - m.start));
    }
  }
  _keepJoins(joins) {
    this._clips('video').forEach((c, k) => {
      const j = k < joins.length ? joins[k] : { fade_in: 0, join: 'cut' };
      c.fade_in = j.fade_in;
      c.join = j.join;
    });
  }
  _commit(prevJson = '') {
    this._layoutVideo();
    if (prevJson) this._follow(prevJson);
    this._seq += 1;
    this._tl.rev = `${this._id}:${this._seq}`;
    const json = JSON.stringify(this._tl);
    this._tl = JSON.parse(json);
    if (this._t > this._duration()) this._t = this._duration();
    if (this.changeEvent) this.dispatchEvent(new MesopEvent(this.changeEvent, { timeline: json }));
  }
  _change(fn) {
    if (this.busy || !this._tl) return;
    const before = this._snapshot();
    fn();
    this._commit(before);
  }
  _undoLast() {
    if (!this._undo.length || this.busy) return;
    this._redo.push(JSON.stringify(this._tl));
    this._tl = JSON.parse(this._undo.pop());
    if (this._sel && !this._find(this._sel)) this._sel = '';
    this._commit();
  }
  _redoLast() {
    if (!this._redo.length || this.busy) return;
    this._undo.push(JSON.stringify(this._tl));
    this._tl = JSON.parse(this._redo.pop());
    if (this._sel && !this._find(this._sel)) this._sel = '';
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
      const vids = this._track('video');
      const gone = vids.clips.find((c) => c.id === id);
      if (gone && vids.clips.length <= 1) return;
      for (const k of KINDS) {
        const tr = this._track(k);
        tr.clips = tr.clips.filter((c) => c.id !== id);
      }
      // A whole scene deleted stays deleted when the film is made again.
      if (gone && +gone.scene >= 0 && !vids.clips.some((c) => c.scene === gone.scene)) {
        const removed = this._tl.removed || (this._tl.removed = []);
        if (!removed.some((r) => r.scene === gone.scene && r.src === gone.src)) removed.push({ scene: +gone.scene, src: gone.src });
      }
      this._sel = '';
    });
  }
  _set(id, key, value) {
    this._change(() => { const f = this._find(id); if (f) f.clip[key] = value; });
  }
  _setLevel(id, pct) {
    this._change(() => {
      const f = this._find(id);
      if (f) f.clip.gain = r3(levelOf(f.clip) * clamp(pct, 0, 100) / 100);
    });
  }
  _setTransition(id, value) {
    this._change(() => {
      const f = this._find(id);
      if (!f) return;
      if (value === 'fade_black') {
        f.clip.join = 'fade_black';
        f.clip.fade_in = 0.5;
      } else if (value === 'cut') {
        f.clip.join = 'cut';
        f.clip.fade_in = 0;
      } else {
        const secs = +value || 0;
        f.clip.fade_in = secs;
        f.clip.join = secs > 0 ? 'dissolve' : 'cut';
      }
    });
  }
  _reorder(id, delta) {
    this._change(() => {
      const v = this._track('video').clips;
      const i = v.findIndex((c) => c.id === id);
      const j = i + delta;
      if (i < 0 || j < 0 || j >= v.length) return;
      const joins = v.map((c) => ({ fade_in: +c.fade_in || 0, join: c.join || 'cut' }));
      [v[i], v[j]] = [v[j], v[i]];
      this._keepJoins(joins);
    });
  }

  // ---------- the player: one <video> with the rendered preview ----------
  _video() { return this.renderRoot && this.renderRoot.querySelector('video.player'); }
  _stage() { return this.renderRoot && this.renderRoot.querySelector('.stage'); }
  _togglePlay() {
    const v = this._video();
    if (!v || !this.previewUrl) return;
    if (v.paused) {
      if (this._t >= this._duration() - 0.05) this._seek(0);
      v.play().catch(() => {});
    } else {
      v.pause();
      this._point();
    }
  }
  _point() {
    clearTimeout(this._pointTimer);
    this._pointTimer = setTimeout(() => {
      const t = Math.round(this._t * 10) / 10;
      if (this._playing || !this.pointEvent || t <= 0 || t === this._pointed) return;
      this._pointed = t;
      this.dispatchEvent(new MesopEvent(this.pointEvent, { time: t }));
    }, 400);
  }
  _onPlay() {
    this._playing = true;
    const tick = () => {
      const v = this._video();
      if (!this._playing || !v) return;
      this._t = Math.min(v.currentTime, this._duration());
      this._paint(true);
      this._raf = requestAnimationFrame(tick);
    };
    cancelAnimationFrame(this._raf);
    this._raf = requestAnimationFrame(tick);
  }
  _onPause() {
    this._playing = false;
    cancelAnimationFrame(this._raf);
    const v = this._video();
    if (v) this._t = Math.min(v.currentTime, this._duration());
    this.requestUpdate();
  }
  /** A new preview file: keep the place and keep playing. */
  _onLoaded() {
    const v = this._video();
    if (!v) return;
    const want = clamp(this._t, 0, Math.max(0, (v.duration || 0) - 0.05));
    if (Math.abs(v.currentTime - want) > 0.04) { try { v.currentTime = want; } catch (e) { /* loading */ } }
    if (this._resume) { this._resume = false; v.play().catch(() => {}); }
  }
  _seek(t) {
    this._t = clamp(t, 0, this._duration());
    const v = this._video();
    if (v && v.readyState >= 1) { try { v.currentTime = Math.min(this._t, Math.max(0, (v.duration || 0) - 0.05)); } catch (e) { /* loading */ } }
    this.requestUpdate();
    if (!this._playing) this._point();
  }
  _fullscreen() {
    const stage = this._stage();
    if (!stage) return;
    if (document.fullscreenElement) document.exitFullscreen().catch(() => {});
    else if (stage.requestFullscreen) stage.requestFullscreen().catch(() => {});
  }
  /** Playhead and time; while playing, the strip scrolls to keep the playhead in view. */
  _paint(follow = false) {
    const r = this.renderRoot;
    if (!r) return;
    const x = this._t * this._pps;
    const head = r.querySelector('.head');
    if (head) head.style.left = `${x}px`;
    const time = r.querySelector('.time');
    if (time) time.textContent = `${fmt(this._t)} / ${fmt(this._duration())}`;
    const scroll = r.querySelector('.scroll');
    if (follow && scroll && !this._drag) {
      const view = scroll.clientWidth;
      if (x < scroll.scrollLeft || x > scroll.scrollLeft + view - 32) scroll.scrollLeft = Math.max(0, x - 32);
    }
  }

  // ---------- dragging (shots and titles; voice and music stay with their scenes) ----------
  _dragStart(e, kind, clip, mode) {
    if (this.busy || e.button > 0) return;
    e.preventDefault();
    e.stopPropagation();
    const el = e.currentTarget.classList.contains('clip') ? e.currentTarget : e.currentTarget.parentElement;
    el?.focus({ preventScroll: true });
    this._sel = clip.id;
    if (kind === 'voice' || kind === 'music') return;
    const tr = this._track(kind);
    this._drag = {
      kind, id: clip.id, mode, x0: e.clientX, moved: false,
      orig: clone(clip), before: JSON.stringify(this._tl),
      max: Math.max(+clip.src_max || 0, +clip.out || 0),
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
    if (d.kind === 'text') {
      if (d.mode === 'move') c.start = r3(Math.max(0, o.start + dt));
      else if (d.mode === 'r') c.dur = r3(Math.max(MIN_LEN, o.dur + dt));
      else { const s = clamp(o.start + dt, 0, o.start + o.dur - MIN_LEN); c.dur = r3(o.dur - (s - o.start)); c.start = r3(s); }
    } else if (d.mode === 'move') {
      c._dx = dt;
    } else if (d.mode === 'r') {
      c.out = r3(clamp(o.out + dt, o.in + MIN_LEN, d.max || o.out));
    } else {
      c.in = r3(clamp(o.in + dt, 0, o.out - MIN_LEN));
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
      const joins = v.map((c) => ({ fade_in: +c.fade_in || 0, join: c.join || 'cut' }));
      const rest = v.filter((c) => c.id !== d.id);
      let at = rest.findIndex((c) => centre < c.start + clipLen(c) / 2);
      if (at < 0) at = rest.length;
      rest.splice(at, 0, f.clip);
      this._track('video').clips = rest;
      this._keepJoins(joins);
    }
    this._pushUndo(d.before);
    this._commit(d.before);
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
    const k = e.key.toLowerCase();
    const plain = !e.ctrlKey && !e.metaKey && !e.altKey;
    if (e.key === ' ') { e.preventDefault(); this._togglePlay(); }
    else if (plain && k === 'f') { e.preventDefault(); this._fullscreen(); }
    else if ((e.ctrlKey || e.metaKey) && (k === 'y' || (e.shiftKey && k === 'z'))) { e.preventDefault(); this._redoLast(); }
    else if ((e.ctrlKey || e.metaKey) && k === 'z') { e.preventDefault(); this._undoLast(); }
    else if (plain && k === 's') { e.preventDefault(); this._split(); }
    else if ((e.key === 'Delete' || e.key === 'Backspace') && this._sel) { e.preventDefault(); this._remove(this._sel); }
    else if (e.key === 'ArrowLeft' || e.key === 'ArrowRight') {
      e.preventDefault();
      const step = e.key === 'ArrowLeft' ? -1 : 1;
      const f = e.altKey && this._sel ? this._find(this._sel) : null;
      if (f && f.kind === 'video') this._reorder(this._sel, step);
      else if (f && f.kind === 'text') this._set(this._sel, 'start', r3(Math.max(0, (+f.clip.start || 0) + step * 0.1)));
      else if (!e.altKey) this._seek(this._t + step * (e.shiftKey ? 5 : 1));
    }
  }

  // ---------- render ----------
  _zoom(f) { this._pps = clamp(this._pps * f, 4, 400); }

  _clipEl(kind, c, names) {
    const left = (+c.start || 0) * this._pps + (kind === 'video' && c._dx ? c._dx * this._pps : 0);
    const width = Math.max(14, clipLen(c) * this._pps);
    const name = kind === 'video' ? (names[c.id] || { full: c.label || 'Clip', short: '' }) : null;
    const narrow = width < 72;
    const label = kind === 'text' ? c.text
      : kind === 'video' ? (narrow ? name.short : name.full)
      : kind === 'music' ? 'Music' : 'Voice';
    const full = kind === 'video' ? name.full : label;
    const sel = this._sel === c.id;
    const dragging = this._drag && this._drag.id === c.id;
    const thumb = kind === 'video' ? this._thumb(c) : '';
    const fadeCls = c.join === 'fade_black' ? 'fade fade-black' : 'fade';
    const fixed = kind === 'voice' || kind === 'music';
    return html`<div class="clip ${kind} ${thumb ? 'thumbs' : ''} ${sel ? 'sel' : ''} ${dragging ? 'drag' : ''} ${narrow ? 'narrow' : ''} ${fixed ? 'fixed' : ''}" tabindex="0" role="button"
        aria-pressed=${sel ? 'true' : 'false'}
        aria-label="${`${LANE_LABEL[kind]}: ${full}, ${fmt(c.start)} to ${fmt(clipEnd(c))}`}"
        title=${full}
        style="left:${left}px;width:${width}px;${thumb ? `background-image:url('${thumb}')` : ''}"
        @pointerdown=${(e) => this._dragStart(e, kind, c, 'move')}
        @click=${() => { if (Date.now() - (this._dragEndedAt || 0) < 250) return; this._sel = c.id; }}
        @focus=${() => { this._sel = c.id; }}>
      ${kind === 'video' && c.fade_in > 0 ? html`<div class="${fadeCls}" style="width:${c.fade_in * this._pps}px"></div>` : nothing}
      <span>${label}</span>
      ${fixed ? nothing : html`<div class="edge l" @pointerdown=${(e) => this._dragStart(e, kind, c, 'l')}></div>
      <div class="edge r" @pointerdown=${(e) => this._dragStart(e, kind, c, 'r')}></div>`}
    </div>`;
  }

  _speechEl(c, names) {
    const left = (+c.start || 0) * this._pps + (c._dx ? c._dx * this._pps : 0);
    const width = Math.max(14, clipLen(c) * this._pps);
    const muted = !(+c.gain > 0);
    const name = (names[c.id] || {}).full || c.label || 'Clip';
    const label = `${name} speech${muted ? ' (muted)' : ''}`;
    return html`<div class="speech ${this._sel === c.id ? 'sel' : ''} ${muted ? 'muted' : ''}" role="button" tabindex="-1"
        title="Speech recorded in ${name}. It moves with the shot; select it to change its volume."
        style="left:${left}px;width:${width}px"
        @click=${() => { this._sel = c.id; }}>${ICON.wave}<span>${label}</span></div>`;
  }

  _ticks(total) {
    const pps = this._pps;
    const step = [0.5, 1, 2, 5, 10, 15, 30, 60].find((s) => s * pps >= 64) || 120;
    const out = [];
    for (let t = 0; t <= total + step; t += step) {
      out.push(html`<div class="tick" style="left:${t * pps}px">${fmt(t).replace('.0', '')}</div>`);
    }
    return out;
  }

  _transitionValue(c) {
    if (c.join === 'fade_black' && +c.fade_in > 0) return 'fade_black';
    if (!(+c.fade_in > 0)) return 'cut';
    const d = +c.fade_in;
    return String([0.25, 0.5, 1].reduce((best, v) => Math.abs(v - d) < Math.abs(best - d) ? v : best, 0.5));
  }

  _inspector(names) {
    const f = this._sel ? this._find(this._sel) : null;
    if (!f) return html`<aside class="panel" aria-label="Clip settings"><p class="empty">Select a clip to edit it</p></aside>`;
    const { kind, clip: c } = f;
    const pct = Math.min(100, Math.round((+c.gain || 0) / levelOf(c) * 100));
    const vid = this._clips('video');
    const vi = vid.findIndex((x) => x.id === c.id);
    const name = kind === 'text' ? 'Title' : kind === 'video' ? (names[c.id] || {}).full || 'Clip' : kind === 'voice' ? 'Voice' : 'Music';
    const transVal = kind === 'video' ? this._transitionValue(c) : 'cut';
    const transOpts = [
      ['cut', 'Cut'],
      ['0.25', 'Crossfade 0.25 s'],
      ['0.5', 'Crossfade 0.5 s'],
      ['1', 'Crossfade 1 s'],
      ['fade_black', 'Dip to black'],
    ];
    return html`<aside class="panel" aria-label="Clip settings">
      <h3>${name}</h3>
      <p class="meta">${fmt(c.start)} – ${fmt(clipEnd(c))} · ${clipLen(c).toFixed(1)} s</p>
      ${kind === 'text' ? html`
        <label class="field">Text<textarea .value=${c.text} @change=${(e) => this._set(c.id, 'text', e.target.value.slice(0, 300))}></textarea></label>
        <div class="grid2">
          <label class="field">Position<select @change=${(e) => this._set(c.id, 'pos', e.target.value)}>
            ${['top', 'center', 'bottom'].map((p) => html`<option value=${p} ?selected=${c.pos === p}>${p[0].toUpperCase() + p.slice(1)}</option>`)}
          </select></label>
          <label class="field">Size<select @change=${(e) => this._set(c.id, 'size', +e.target.value)}>
            ${[[32, 'Small'], [48, 'Medium'], [72, 'Large'], [104, 'Huge']].map(([v, l]) => html`<option value=${v} ?selected=${+c.size === v}>${l}</option>`)}
          </select></label>
        </div>` : html`
        <label class="field"><span>${kind !== 'video' ? 'Volume' : 'Clip sound'} <span class="val">${pct}%</span></span>
          <input type="range" min="0" max="100" step="5" .value=${String(pct)}
            @change=${(e) => this._setLevel(c.id, +e.target.value)}></label>`}
      ${kind === 'video' ? html`
        <label class="field">Transition in<select ?disabled=${vi === 0} @change=${(e) => this._setTransition(c.id, e.target.value)}>
          ${transOpts.map(([v, l]) => html`<option value=${v} ?selected=${transVal === v}>${l}</option>`)}
        </select></label>
        <div class="grid2">
          <button ?disabled=${this.busy || vi <= 0} @click=${() => this._reorder(c.id, -1)}>${ICON.left} Earlier</button>
          <button ?disabled=${this.busy || vi >= vid.length - 1} @click=${() => this._reorder(c.id, 1)}>Later ${ICON.right}</button>
        </div>` : nothing}
      ${kind === 'music' ? html`<label class="check"><input type="checkbox" .checked=${this._track('music').duck !== false}
          @change=${(e) => this._change(() => { this._track('music').duck = e.target.checked; })}>
          Lower under speech</label>` : nothing}
    </aside>`;
  }

  _canSplit() {
    const f = this._sel ? this._find(this._sel) : null;
    if (!f || f.kind === 'voice' || f.kind === 'music') return false;
    const c = f.clip;
    return this._t > c.start + MIN_LEN && this._t < clipEnd(c) - MIN_LEN;
  }

  _split() {
    if (!this._canSplit()) return;
    this._change(() => {
      const f = this._find(this._sel);
      const { kind, clip: c } = f;
      const tr = this._track(kind);
      const at = this._t - c.start;
      const b = clone(c);
      b.id = uid();
      if (kind === 'text') {
        b.start = r3(this._t); b.dur = r3(c.dur - at); c.dur = r3(at);
      } else {
        const mid = r3((+c.in || 0) + at * (+c.tempo || 1));
        b.in = mid; c.out = mid; b.start = r3(this._t);
        b.fade_in = 0; b.join = 'cut';
      }
      tr.clips.splice(tr.clips.indexOf(c) + 1, 0, b);
      this._sel = b.id;
    });
  }

  _badge() {
    if (this.previewState === 'making') return html`<div class="badge" role="status"><span class="dot"></span>Updating preview</div>`;
    if (this.previewState === 'failed') return html`<div class="badge" role="status">Preview not updated</div>`;
    return nothing;
  }

  render() {
    if (!this._tl) return html`<p class="empty">No timeline yet.</p>`;
    if (!this._pps) this._fit();
    const total = this._duration();
    const width = Math.max(total * this._pps + 120, 200);
    const t = this._t;
    const names = this._labels();
    const zoomVal = Math.round(Math.log(this._pps / 4) / Math.log(100) * 100);
    const poster = this._thumb(this._clips('video')[0]);
    return html`<div class="wrap">
      <div class="top">
        <div class="viewer">
          <div class="stage ${this.aspect === '9:16' ? 'ar916' : 'ar169'}" tabindex="0" aria-label="Preview"
              @dblclick=${this._fullscreen}>
            ${this.previewUrl ? html`<video class="player" src=${this.previewUrl} playsinline preload="auto"
                poster=${poster || nothing}
                @play=${this._onPlay} @pause=${this._onPause} @ended=${this._onPause}
                @loadedmetadata=${this._onLoaded} @click=${this._togglePlay}></video>`
              : poster ? html`<img class="poster" src=${poster} alt="">` : nothing}
            ${this._badge()}
          </div>
          <div class="transport">
            <span class="time" .textContent=${`${fmt(t)} / ${fmt(total)}`}></span>
            <div class="mid">
              <button class="icon ghost" aria-label="Back to start" title="Back to start" @click=${() => this._seek(0)}>${ICON.start}</button>
              <button class="icon primary" aria-label=${this._playing ? 'Pause' : 'Play'} title="Play or pause (Space)"
                ?disabled=${!this.previewUrl} @click=${this._togglePlay}>${this._playing ? ICON.pause : ICON.play}</button>
            </div>
            <span class="end">
              <button class="icon ghost" aria-label=${this._full ? 'Exit full screen' : 'Full screen'} title="Full screen (F)"
                ?disabled=${!this.previewUrl} @click=${this._fullscreen}>${this._full ? ICON.unfull : ICON.full}</button>
            </span>
          </div>
        </div>
        ${this._inspector(names)}
      </div>
      <div class="bar" role="toolbar" aria-label="Edit">
        <button title="Split at playhead (S)" ?disabled=${this.busy || !this._canSplit()} @click=${this._split}>${ICON.split}<span class="lbl-hide">Split</span></button>
        <button title="Delete (Del)" ?disabled=${this.busy || !this._sel} @click=${() => this._remove(this._sel)}>${ICON.del}<span class="lbl-hide">Delete</span></button>
        <button title="Add a title at the playhead" ?disabled=${this.busy} @click=${this._addTitle}>${ICON.title}<span class="lbl-hide">Add title</span></button>
        <span class="sep"></span>
        <button class="icon" title="Undo (Ctrl+Z)" aria-label="Undo" ?disabled=${this.busy || !this._undo.length} @click=${this._undoLast}>${ICON.undo}</button>
        <button class="icon" title="Redo (Ctrl+Shift+Z)" aria-label="Redo" ?disabled=${this.busy || !this._redo.length} @click=${this._redoLast}>${ICON.redo}</button>
        <span class="spacer"></span>
        <div class="zoom">
          <button class="icon ghost" aria-label="Zoom out" @click=${() => this._zoom(1 / 1.5)}>${ICON.minus}</button>
          <input type="range" min="0" max="100" .value=${String(zoomVal)} aria-label="Zoom"
            @input=${(e) => { this._pps = 4 * Math.pow(100, +e.target.value / 100); }}>
          <button class="icon ghost" aria-label="Zoom in" @click=${() => this._zoom(1.5)}>${ICON.plus}</button>
        </div>
      </div>
      <div class="tracks" role="group" aria-label="Timeline">
        <div class="heads" aria-hidden="true"><div class="rl"></div>${KINDS.map((k) => html`<div class="h-${k}">${TRACK_ICON[k]}<span>${LANE_LABEL[k]}</span></div>`)}</div>
        <div class="scroll" @pointerdown=${(e) => { if (e.target.classList.contains('lane')) this._sel = ''; }}>
          <div class="inner" style="width:${width}px">
            <div class="ruler" @pointerdown=${(e) => this._rulerDown(e)} aria-hidden="true">${this._ticks(total)}</div>
            ${KINDS.map((k) => html`<div class="lane h-${k}" aria-label="${LANE_LABEL[k]} track">${k === 'voice' ? repeat(this._clips('video').filter((c) => !c.ambient), (c) => `s-${c.id}`, (c) => this._speechEl(c, names)) : nothing}${repeat(this._clips(k), (c) => c.id, (c) => this._clipEl(k, c, names))}</div>`)}
            <div class="head" style="left:${t * this._pps}px"></div>
          </div>
        </div>
      </div>
    </div>`;
  }

  firstUpdated() {
    this._fit();
  }

  updated(changed) {
    if (changed.has('previewUrl')) {
      // The new file loads from the start: carry on where the viewer was.
      this._resume = this._playing;
    }
    this._paint();
  }
}

const svg = (d) => html`<svg viewBox="0 0 24 24" aria-hidden="true"><path d="${d}"></path></svg>`;
const ICON = {
  play: svg('M8 5v14l11-7z'),
  pause: svg('M6 5h4v14H6zM14 5h4v14h-4z'),
  start: svg('M6 6h2v12H6zm3.5 6 8.5 6V6z'),
  full: svg('M7 14H5v5h5v-2H7zm-2-4h2V7h3V5H5zm12 7h-3v2h5v-5h-2zM14 5v2h3v3h2V5z'),
  unfull: svg('M5 16h3v3h2v-5H5zm3-8H5v2h5V5H8zm6 11h2v-3h3v-2h-5zm2-11V5h-2v5h5V8z'),
  undo: svg('M12.5 8c-2.65 0-5.05 1-6.9 2.6L2 7v9h9l-3.62-3.62A7.95 7.95 0 0 1 20.4 16l2.36-.78A10.5 10.5 0 0 0 12.5 8z'),
  plus: svg('M19 13h-6v6h-2v-6H5v-2h6V5h2v6h6z'),
  minus: svg('M19 13H5v-2h14z'),
  title: svg('M5 4v3h5.5v12h3V7H19V4z'),
  del: svg('M6 19a2 2 0 0 0 2 2h8a2 2 0 0 0 2-2V7H6zM19 4h-3.5l-1-1h-5l-1 1H5v2h14z'),
  redo: svg('M11.5 8c2.65 0 5.05 1 6.9 2.6L22 7v9h-9l3.62-3.62A7.95 7.95 0 0 0 3.6 16l-2.36-.78A10.5 10.5 0 0 1 11.5 8z'),
  left: svg('M15.4 7.4 14 6l-6 6 6 6 1.4-1.4-4.6-4.6z'),
  right: svg('M8.6 16.6 10 18l6-6-6-6-1.4 1.4 4.6 4.6z'),
  wave: svg('M7 18h2V6H7zm4 4h2V2h-2zm-8-8h2v-4H3zm12 4h2V6h-2zm4-8v4h2v-4z'),
  split: svg('M11 2h2v20h-2zM4 7h5v10H4a1 1 0 0 1-1-1V8a1 1 0 0 1 1-1zm11 0h5a1 1 0 0 1 1 1v8a1 1 0 0 1-1 1h-5z'),
};
const TRACK_ICON = {
  video: svg('M17 10.5V7a1 1 0 0 0-1-1H4a1 1 0 0 0-1 1v10a1 1 0 0 0 1 1h12a1 1 0 0 0 1-1v-3.5l4 4v-11z'),
  voice: svg('M12 14a3 3 0 0 0 3-3V5a3 3 0 0 0-6 0v6a3 3 0 0 0 3 3zm5-3a5 5 0 0 1-10 0H5a7 7 0 0 0 6 6.92V21h2v-3.08A7 7 0 0 0 19 11z'),
  music: svg('M12 3v10.55A4 4 0 1 0 14 17V7h4V3z'),
  text: ICON.title,
};

if (!customElements.get('story-timeline')) customElements.define('story-timeline', StoryTimeline);
