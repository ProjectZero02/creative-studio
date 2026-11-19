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
 * Live voice agent, browser side.
 *
 * window.gmLive is created once and attached to document.body, outside the
 * Mesop render tree, so a call keeps going while the agent moves between
 * pages. It owns the WebSocket to /api/live, the microphone (16 kHz PCM16),
 * the speaker (24 kHz PCM16), and the overlays: call dock, captions, job tray,
 * result viewer and the on-screen cursor.
 *
 * <live-agent-bridge> (one per page) turns "go to page" and "fill these
 * fields" into Mesop events, and carries the page's fillable fields.
 *
 * A call is "Fill only" (the agent only fills the page; the presenter presses
 * Generate) or "Do it for me" (the agent also runs jobs). The dock's switch
 * picks it; the choice is remembered in this browser.
 * <live-call-button> is the big call button on the home page.
 */
import { LitElement, html, css } from 'https://cdn.jsdelivr.net/npm/lit@3.2.1/+esm';

const DEFAULT_STRINGS = {
  talk: 'Talk to the studio',
  hint: 'Ask for images, videos, music, voice or stories by voice. Jobs run side by side.',
  connecting: 'Connecting…',
  listening: 'Listening',
  speaking: 'Speaking',
  offline: 'Offline mode (typed)',
  type: 'Type a request…',
  mute: 'Mute microphone',
  unmute: 'Unmute microphone',
  hangup: 'End call',
  jobs: 'Jobs',
  download: 'Download',
  close: 'Close',
  nomic: 'No microphone access. You can still type.',
  fill: 'Fill only',
  act: 'Do it for me',
  modeHint: 'Fill only: the agent fills the page and you press Generate. Do it for me: it also runs the jobs.',
};
const MODE_KEY = 'gm-live-mode';
function savedMode() {
  try { return localStorage.getItem(MODE_KEY) === 'act' ? 'act' : 'fill'; } catch (e) { return 'fill'; }
}

const sleep = (ms) => new Promise((r) => setTimeout(r, ms));
const isAudioJob = (job) =>
  String(job.mime_type || '').startsWith('audio/') ||
  job.kind === 'music' ||
  job.kind === 'voice';
const isVideoJob = (job) =>
  String(job.mime_type || '').startsWith('video/') || job.kind === 'video';
const ICON_AUDIO =
  '<svg viewBox="0 0 24 24" aria-hidden="true"><path d="M12 3v10.55A4 4 0 1 0 14 17V7h4V3h-6z"/></svg>';
const ICON_STORY =
  '<svg viewBox="0 0 24 24" aria-hidden="true"><path d="M18 4l2 4h-3l-2-4h-2l2 4h-3l-2-4H8l2 4H7L5 4H4a2 2 0 0 0-2 2v12a2 2 0 0 0 2 2h16a2 2 0 0 0 2-2V4h-4z"/></svg>';

function b64FromInt16(int16) {
  const bytes = new Uint8Array(int16.buffer);
  let bin = '';
  for (let i = 0; i < bytes.length; i += 0x8000) {
    bin += String.fromCharCode.apply(null, bytes.subarray(i, i + 0x8000));
  }
  return btoa(bin);
}

function int16FromB64(b64) {
  const bin = atob(b64);
  const bytes = new Uint8Array(bin.length);
  for (let i = 0; i < bin.length; i++) bytes[i] = bin.charCodeAt(i);
  return new Int16Array(bytes.buffer);
}

const STYLE = `
.gml-root { position: fixed; inset: 0; pointer-events: none; z-index: 2147483000;
  font-family: "Google Sans", "Google Sans Text", Roboto, Arial, sans-serif;
  color: var(--sys-on-surface, #1b1c1f); }
.gml-root * { box-sizing: border-box; }
.gml-glass { background: var(--gm-glass-fill, rgba(255,255,255,.82));
  backdrop-filter: blur(var(--gm-glass-blur, 18px)); -webkit-backdrop-filter: blur(var(--gm-glass-blur, 18px));
  border: 1px solid var(--gm-glass-border, rgba(0,0,0,.08));
  box-shadow: var(--gm-glass-shadow, 0 8px 30px rgba(0,0,0,.12)); }
.gml-btn { pointer-events: auto; border: 0; cursor: pointer; font: inherit; border-radius: 999px;
  display: inline-flex; align-items: center; justify-content: center; gap: 8px; }
.gml-btn:focus-visible { outline: 2px solid var(--sys-primary, #1a5fd8); outline-offset: 2px; }
.gml-launch { position: fixed; inset-inline-end: 20px; bottom: 20px; height: 48px; padding: 0 18px 0 14px;
  background: var(--sys-primary, #1a5fd8); color: var(--sys-on-primary, #fff); font-weight: 500;
  box-shadow: 0 6px 20px rgba(26,95,216,.35); }
.gml-launch svg, .gml-dock svg { width: 20px; height: 20px; fill: currentColor; }
/* A round mic that shows its label on hover or keyboard focus: the wide pill
   sat on top of the bottom-right primary action (Fashion "Try it on", Brand
   kit "Create brand kit") on a 1440 x 900 screen. */
.gml-launch { min-width: 48px; padding: 0 14px; }
.gml-launch span { display: none; }
.gml-launch:hover span, .gml-launch:focus-visible span { display: inline; }
.gml-launch:hover, .gml-launch:focus-visible { padding: 0 18px 0 14px; }
.gml-dock { position: fixed; left: 50%; bottom: 20px; transform: translateX(-50%);
  width: min(640px, calc(100vw - 32px)); border-radius: 24px; padding: 10px 10px 10px 16px;
  display: flex; align-items: center; gap: 10px; pointer-events: auto; }
.gml-state { display: flex; align-items: center; gap: 8px; min-width: 112px; font-size: 13px;
  color: var(--sys-on-surface-variant, #44474e); white-space: nowrap; }
.gml-dot { width: 10px; height: 10px; border-radius: 50%; background: #9aa0a6; flex: none; }
.gml-dot[data-s="live"] { background: #1e8e3e; box-shadow: 0 0 0 0 rgba(30,142,62,.5); animation: gml-pulse 1.6s infinite; }
.gml-dot[data-s="speaking"] { background: var(--sys-primary, #1a5fd8); }
.gml-dot[data-s="offline"] { background: #f29900; }
@keyframes gml-pulse { 0% { box-shadow: 0 0 0 0 rgba(30,142,62,.45); } 70% { box-shadow: 0 0 0 8px rgba(30,142,62,0); } 100% { box-shadow: 0 0 0 0 rgba(30,142,62,0); } }
.gml-level { width: 46px; height: 6px; border-radius: 3px; background: var(--sys-surface-container-high, #e6e8ec); overflow: hidden; flex: none; }
.gml-level i { display: block; height: 100%; width: 0; background: #1e8e3e; transition: width .08s; }
.gml-input { flex: 1; min-width: 0; height: 40px; border-radius: 20px; padding: 0 14px; font: inherit; font-size: 14px;
  border: 1px solid var(--sys-outline-variant, #c4c6cf); background: var(--sys-surface-container-lowest, #fff);
  color: inherit; pointer-events: auto; }
.gml-mode { height: 32px; padding: 0 12px; flex: none; font-size: 13px; font-weight: 500;
  background: var(--sys-surface-container-high, #e6e8ec); color: inherit; white-space: nowrap; }
.gml-mode[data-mode="act"] { background: var(--sys-primary-container, #d8e2ff); color: var(--sys-on-primary-container, #001a41); }
.gml-icon { width: 40px; height: 40px; flex: none; background: var(--sys-surface-container-high, #e6e8ec); color: inherit; }
.gml-icon[aria-pressed="true"] { background: #fce8e6; color: #c5221f; }
.gml-hang { width: 40px; height: 40px; flex: none; background: #d93025; color: #fff; }
.gml-captions { position: fixed; left: 50%; bottom: 84px; transform: translateX(-50%);
  width: min(640px, calc(100vw - 32px)); display: flex; flex-direction: column; gap: 6px; align-items: center; }
.gml-cap { max-width: 100%; padding: 8px 14px; border-radius: 16px; font-size: 15px; line-height: 1.35;
  text-align: center; transition: opacity .3s; }
.gml-cap.user { font-size: 13px; color: var(--sys-on-surface-variant, #44474e); }
.gml-cap:empty { display: none; }
.gml-notice { font-size: 12px; color: #b06000; }
.gml-tray { position: fixed; top: 76px; inset-inline-end: 16px; width: 248px; max-height: calc(100vh - 200px);
  overflow-y: auto; display: flex; flex-direction: column; gap: 8px; pointer-events: auto; border-radius: 18px; padding: 10px; }
.gml-tray h2 { margin: 2px 4px 2px; font-size: 12px; font-weight: 600; letter-spacing: .04em; text-transform: uppercase;
  color: var(--sys-on-surface-variant, #44474e); }
.gml-job { display: flex; flex-wrap: wrap; gap: 8px 10px; align-items: center; padding: 6px; border-radius: 12px; cursor: pointer;
  background: var(--sys-surface-container-lowest, #fff); border: 1px solid var(--sys-outline-variant, #dfe1e6);
  text-align: left; width: 100%; color: inherit; font: inherit; animation: gml-in .35s ease-out; }
.gml-job audio { width: 100%; height: 32px; display: block; }
.gml-job:hover { border-color: var(--sys-primary, #1a5fd8); }
.gml-job.flash { box-shadow: 0 0 0 3px rgba(26,95,216,.35); }
@keyframes gml-in { from { opacity: 0; transform: translateX(20px); } to { opacity: 1; transform: none; } }
.gml-thumb { width: 52px; height: 52px; border-radius: 9px; flex: none; overflow: hidden; display: grid; place-items: center;
  background: var(--sys-surface-container-high, #e6e8ec); }
.gml-thumb img, .gml-thumb video { width: 100%; height: 100%; object-fit: cover; }
.gml-thumb svg { width: 24px; height: 24px; fill: var(--sys-primary, #1a5fd8); }
.gml-spin { width: 22px; height: 22px; border-radius: 50%; border: 3px solid rgba(26,95,216,.2);
  border-top-color: var(--sys-primary, #1a5fd8); animation: gml-rot .9s linear infinite; }
@keyframes gml-rot { to { transform: rotate(360deg); } }
.gml-meta { min-width: 0; flex: 1; }
.gml-meta b { display: block; font-size: 13px; font-weight: 600; text-transform: capitalize; }
.gml-meta span { display: block; font-size: 12px; color: var(--sys-on-surface-variant, #44474e);
  white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }
.gml-meta em { font-style: normal; font-size: 11px; color: var(--sys-on-surface-variant, #44474e); }
.gml-meta em.failed { color: #c5221f; }
.gml-viewer { position: fixed; top: 76px; inset-inline-end: 280px; width: min(560px, calc(100vw - 320px));
  border-radius: 20px; padding: 14px; pointer-events: auto; animation: gml-pop .3s ease-out; }
@keyframes gml-pop { from { opacity: 0; transform: scale(.96); } to { opacity: 1; transform: none; } }
.gml-viewer img, .gml-viewer video { width: 100%; max-height: 62vh; object-fit: contain; border-radius: 12px; display: block;
  background: var(--sys-surface-container-high, #e6e8ec); }
.gml-viewer audio { width: 100%; display: block; margin: 12px 0 4px; }
.gml-vhead { display: flex; align-items: center; gap: 8px; margin-bottom: 10px; }
.gml-vhead b { flex: 1; text-transform: capitalize; font-size: 15px; }
.gml-vprompt { margin: 10px 2px 2px; font-size: 13px; color: var(--sys-on-surface-variant, #44474e); }
.gml-small { height: 34px; padding: 0 14px; font-size: 13px; background: var(--sys-surface-container-high, #e6e8ec); color: inherit; }
.gml-small.primary { background: var(--sys-primary, #1a5fd8); color: var(--sys-on-primary, #fff); }
.gml-cursor { position: fixed; left: 0; top: 0; width: 26px; height: 26px; margin: -13px 0 0 -13px; border-radius: 50%;
  background: radial-gradient(circle, rgba(66,133,244,.95) 0 30%, rgba(66,133,244,.35) 31% 100%);
  box-shadow: 0 0 18px rgba(66,133,244,.8); opacity: 0;
  transition: transform .7s cubic-bezier(.22,.8,.26,1), opacity .25s; }
.gml-cursor.on { opacity: 1; }
.gml-ring { position: fixed; border-radius: 12px; border: 3px solid rgba(66,133,244,.9); box-shadow: 0 0 0 6px rgba(66,133,244,.18);
  pointer-events: none; animation: gml-ring 1.2s ease-out forwards; }
@keyframes gml-ring { 0% { opacity: 0; transform: scale(1.06); } 20% { opacity: 1; transform: scale(1); } 100% { opacity: 0; } }
.gml-hidden { display: none !important; }
@media (max-width: 760px) {
  .gml-tray { top: auto; bottom: 150px; inset-inline-end: 8px; width: 180px; max-height: 40vh; }
  .gml-viewer { inset-inline: 8px; width: auto; top: 64px; }
  .gml-state { min-width: 0; } .gml-state span { display: none; }
}
/* Phones: a round mic button instead of the wide pill, so it covers less of
   the page (the label stays as aria-label). */
@media (max-width: 600px) {
  .gml-launch { width: 52px; height: 52px; padding: 0; inset-inline-end: 16px; bottom: 16px; }
  .gml-launch span { display: none; }
  .gml-launch svg { width: 22px; height: 22px; }
}
@media (prefers-reduced-motion: reduce) {
  .gml-cursor, .gml-job, .gml-viewer { transition: none; animation: none; }
}
`;

const ICON_MIC = '<svg viewBox="0 0 24 24" aria-hidden="true"><path d="M12 14a3 3 0 0 0 3-3V5a3 3 0 0 0-6 0v6a3 3 0 0 0 3 3zm5-3a5 5 0 0 1-10 0H5a7 7 0 0 0 6 6.92V21h2v-3.08A7 7 0 0 0 19 11z"/></svg>';
const ICON_MIC_OFF = '<svg viewBox="0 0 24 24" aria-hidden="true"><path d="M19 11h-2c0 .74-.16 1.43-.43 2.05l1.47 1.47A6.9 6.9 0 0 0 19 11zM15 11V5a3 3 0 0 0-5.94-.6L15 10.34zM4.27 3 3 4.27l6 6V11a3 3 0 0 0 4.38 2.65l1.55 1.55A5 5 0 0 1 7 11H5a7 7 0 0 0 6 6.92V21h2v-3.08a6.9 6.9 0 0 0 2.98-1.06L19.73 21 21 19.73z"/></svg>';
const ICON_HANG = '<svg viewBox="0 0 24 24" aria-hidden="true"><path d="M12 9c-1.6 0-3.15.25-4.6.72v3.1c0 .39-.23.74-.56.9-.98.49-1.87 1.12-2.66 1.85-.18.18-.43.28-.7.28-.28 0-.53-.11-.71-.29L.29 13.08a1 1 0 0 1 0-1.41C3.34 8.78 7.46 7 12 7s8.66 1.78 11.71 4.67c.18.18.29.43.29.71 0 .28-.11.53-.29.71l-2.48 2.48c-.18.18-.43.29-.71.29-.27 0-.52-.11-.7-.28a11.27 11.27 0 0 0-2.67-1.85.99.99 0 0 1-.56-.9v-3.1C15.15 9.25 13.6 9 12 9z"/></svg>';

class GmLive {
  constructor() {
    this.strings = { ...DEFAULT_STRINGS };
    this.state = 'idle'; // idle | connecting | live | offline
    this.ws = null;
    this.muted = false;
    this.jobs = new Map();
    this.bridge = null;
    this.playing = [];
    this.nextPlay = 0;
    this.agentLine = '';
    this.userLine = '';
    this._buildUi();
  }

  // ---------------------------------------------------------------- UI ---

  _el(tag, cls, parent, htmlText) {
    const el = document.createElement(tag);
    if (cls) el.className = cls;
    if (htmlText !== undefined) el.innerHTML = htmlText;
    if (parent) parent.appendChild(el);
    return el;
  }

  _buildUi() {
    const style = document.createElement('style');
    style.textContent = STYLE;
    document.head.appendChild(style);
    const root = this._el('div', 'gml-root', document.body);
    root.setAttribute('data-gm-live', '');
    this.root = root;

    this.launch = this._el('button', 'gml-btn gml-launch', root, ICON_MIC + '<span></span>');
    this.launch.addEventListener('click', () => this.start());

    this.captions = this._el('div', 'gml-captions gml-hidden', root);
    this.capUser = this._el('div', 'gml-cap user gml-glass', this.captions);
    this.capAgent = this._el('div', 'gml-cap gml-glass', this.captions);
    this.capAgent.setAttribute('aria-live', 'polite');

    this.dock = this._el('div', 'gml-dock gml-glass gml-hidden', root);
    this.dock.setAttribute('role', 'region');
    const st = this._el('div', 'gml-state', this.dock);
    this.dot = this._el('i', 'gml-dot', st);
    this.stateText = this._el('span', '', st);
    this.level = this._el('div', 'gml-level', this.dock, '<i></i>');
    this.input = this._el('input', 'gml-input', this.dock);
    this.input.type = 'text';
    this.input.addEventListener('keydown', (e) => {
      if (e.key === 'Enter' && this.input.value.trim()) {
        this.sendText(this.input.value.trim());
        this.input.value = '';
      }
    });
    this.mode = savedMode();
    this.modeBtn = this._el('button', 'gml-btn gml-mode', this.dock);
    this.modeBtn.type = 'button';
    this.modeBtn.addEventListener('click', () => this.setMode(this.mode === 'fill' ? 'act' : 'fill'));
    this.muteBtn = this._el('button', 'gml-btn gml-icon', this.dock, ICON_MIC);
    this.muteBtn.addEventListener('click', () => this.toggleMute());
    this.hangBtn = this._el('button', 'gml-btn gml-hang', this.dock, ICON_HANG);
    this.hangBtn.addEventListener('click', () => this.stop());

    this.tray = this._el('div', 'gml-tray gml-glass gml-hidden', root);
    this.trayTitle = this._el('h2', '', this.tray);

    this.viewer = this._el('div', 'gml-viewer gml-glass gml-hidden', root);
    this.cursor = this._el('div', 'gml-cursor', root);
    this._applyStrings();
  }

  setStrings(strings) {
    if (!strings) return;
    Object.assign(this.strings, strings);
    this._applyStrings();
  }

  _applyStrings() {
    const s = this.strings;
    this.launch.querySelector('span').textContent = s.talk;
    this.launch.setAttribute('aria-label', s.talk);
    this._renderMode();
    this.input.placeholder = s.type;
    this.input.setAttribute('aria-label', s.type);
    this.hangBtn.setAttribute('aria-label', s.hangup);
    this.hangBtn.title = s.hangup;
    this.dock.setAttribute('aria-label', s.talk);
    this.trayTitle.textContent = s.jobs;
    this._renderMute();
    this._renderState();
  }

  _renderMute() {
    const label = this.muted ? this.strings.unmute : this.strings.mute;
    this.muteBtn.innerHTML = this.muted ? ICON_MIC_OFF : ICON_MIC;
    this.muteBtn.setAttribute('aria-pressed', String(this.muted));
    this.muteBtn.setAttribute('aria-label', label);
    this.muteBtn.title = label;
  }

  _renderState(speaking) {
    const active = this.state !== 'idle';
    this.launch.classList.toggle('gml-hidden', active || this._heroVisible());
    this.dock.classList.toggle('gml-hidden', !active);
    this.captions.classList.toggle('gml-hidden', !active);
    const s = this.strings;
    let label = '';
    let key = this.state;
    if (this.state === 'connecting') label = s.connecting;
    else if (this.state === 'offline') label = s.offline;
    else if (this.state === 'live') {
      label = speaking ? s.speaking : s.listening;
      if (speaking) key = 'speaking';
    }
    this.dot.dataset.s = key;
    this.stateText.textContent = label;
    this.muteBtn.classList.toggle('gml-hidden', !this.micStream);
    this.level.classList.toggle('gml-hidden', !this.micStream);
  }

  _heroVisible() {
    return !!document.querySelector('live-call-button, home-prompt[live]');
  }

  refreshLauncher() { this._renderState(); }

  _caption(who, text, final) {
    const el = who === 'user' ? this.capUser : this.capAgent;
    const key = who === 'user' ? 'userLine' : 'agentLine';
    if (final) this[key] = text;
    else this[key] = (this[key] + text).slice(-280);
    el.textContent = this[key];
  }

  // ------------------------------------------------------------ jobs -----

  _job(job) {
    const known = this.jobs.get(job.id);
    this.jobs.set(job.id, job);
    this.tray.classList.remove('gml-hidden');
    let card = this.tray.querySelector(`[data-job="${job.id}"]`);
    if (!card) {
      card = this._el('button', 'gml-job');
      card.dataset.job = job.id;
      card.addEventListener('click', () => this.openViewer(this.jobs.get(job.id)));
      this.tray.insertBefore(card, this.trayTitle.nextSibling);
    }
    let thumb = '<i class="gml-spin"></i>';
    if (job.status === 'failed') {
      thumb = '!';
    } else if (job.status === 'done') {
      if (isAudioJob(job)) thumb = ICON_AUDIO;
      else if (isVideoJob(job) && job.display_url) {
        thumb = `<video src="${job.display_url}" muted playsinline preload="metadata"></video>`;
      } else if (job.display_url) {
        thumb = `<img src="${job.display_url}" alt="">`;
      } else {
        thumb = ICON_STORY;
      }
    }
    const label = job.is_edit ? `edit of ${job.source_job}` : job.prompt;
    const status = job.status === 'failed' ? (job.error || 'failed') : job.status;
    card.innerHTML = `<span class="gml-thumb">${thumb}</span><span class="gml-meta"><b></b><span></span><em></em></span>`;
    card.querySelector('b').textContent = job.handle;
    card.querySelector('.gml-meta span').textContent = label;
    const em = card.querySelector('em');
    em.textContent = status;
    em.classList.toggle('failed', job.status === 'failed');
    if (job.status === 'done' && isAudioJob(job) && job.display_url) {
      const audio = this._el('audio', '', card);
      audio.src = job.display_url;
      audio.controls = true;
      audio.preload = 'metadata';
      audio.addEventListener('click', (e) => e.stopPropagation());
    }
    card.setAttribute('aria-label', `${job.handle}: ${status}`);
    if (known && known.status !== job.status && job.status === 'done') {
      card.classList.add('flash');
      setTimeout(() => card.classList.remove('flash'), 1600);
    }
    if (this.viewerJob === job.id) this.openViewer(job);
  }

  openViewer(job) {
    if (!job) return;
    this.viewerJob = job.id;
    const v = this.viewer;
    v.classList.remove('gml-hidden');
    v.innerHTML = '';
    const head = this._el('div', 'gml-vhead', v);
    this._el('b', '', head).textContent = job.handle;
    if (job.status === 'done' && (job.display_url || job.gcs_uri)) {
      const dl = this._el('button', 'gml-btn gml-small primary', head);
      dl.textContent = this.strings.download;
      dl.addEventListener('click', () => this.download(job));
    }
    const close = this._el('button', 'gml-btn gml-small', head);
    close.textContent = this.strings.close;
    close.addEventListener('click', () => this.closeViewer());
    if (job.status === 'done') {
      if (isAudioJob(job) && job.display_url) {
        const audio = this._el('audio', '', v);
        audio.src = job.display_url; audio.controls = true; audio.autoplay = true;
      } else if (isVideoJob(job) && job.display_url) {
        const video = this._el('video', '', v);
        video.src = job.display_url; video.controls = true; video.autoplay = true; video.muted = true; video.loop = true;
        video.playsInline = true;
      } else if (job.display_url) {
        const img = this._el('img', '', v);
        img.src = job.display_url; img.alt = job.prompt;
      } else {
        const info = this._el('div', 'gml-thumb', v);
        info.style.cssText = 'width:100%;height:120px;border-radius:12px';
        info.innerHTML = ICON_STORY;
      }
    } else {
      const wait = this._el('div', 'gml-thumb', v);
      wait.style.cssText = 'width:100%;height:240px;border-radius:12px';
      wait.innerHTML = job.status === 'failed' ? (job.error || 'Failed') : '<i class="gml-spin"></i>';
    }
    this._el('p', 'gml-vprompt', v).textContent = job.prompt;
  }

  closeViewer() {
    this.viewerJob = null;
    this.viewer.classList.add('gml-hidden');
  }

  // ---------------------------------------------------------- screen -----

  async navigate(route, params) {
    const hasParams = params && Object.keys(params).length > 0;
    if (location.pathname === route && !hasParams) return true;
    if (!this.bridge || !this.bridge.actionEvent) {
      const qs = hasParams ? '?' + new URLSearchParams(params).toString() : '';
      location.assign(route + qs); // fallback: full load (call reconnects)
      return false;
    }
    this.bridge.dispatchEvent(new MesopEvent(this.bridge.actionEvent, { action: 'navigate', page: route, params: params || {} }));
    for (let i = 0; i < 40 && location.pathname !== route; i++) await sleep(100);
    await sleep(450); // let the page render
    return location.pathname === route;
  }

  async _waitFor(selector, ms = 3000) {
    const end = Date.now() + ms;
    while (Date.now() < end) {
      const el = document.querySelector(selector);
      if (el && el.getBoundingClientRect().width > 0) return el;
      await sleep(120);
    }
    return null;
  }

  async pointAt(el) {
    if (!el) return;
    el.scrollIntoView({ block: 'center', behavior: 'smooth' });
    await sleep(250);
    const r = el.getBoundingClientRect();
    const c = this.cursor;
    if (!c.classList.contains('on')) {
      c.style.transform = `translate(${window.innerWidth / 2}px, ${window.innerHeight - 120}px)`;
      c.classList.add('on');
      await sleep(30);
    }
    c.style.transform = `translate(${r.left + r.width / 2}px, ${r.top + Math.min(r.height / 2, 28)}px)`;
    await sleep(720);
    const ring = this._el('div', 'gml-ring', this.root);
    ring.style.cssText = `left:${r.left - 4}px;top:${r.top - 4}px;width:${r.width + 8}px;height:${r.height + 8}px`;
    setTimeout(() => ring.remove(), 1300);
    clearTimeout(this._cursorTimer);
    this._cursorTimer = setTimeout(() => c.classList.remove('on'), 2500);
  }

  async compose(args) {
    await this.navigate(args.page, args.params);
    const box = await this._waitFor('.gm-page textarea');
    if (box) {
      await this.pointAt(box);
      // Show the prompt being typed. Display only: the job already runs on the
      // server, and the studio's own Generate button is never pressed.
      const text = String(args.prompt || '');
      const step = Math.max(1, Math.ceil(text.length / 70));
      box.focus({ preventScroll: true });
      for (let i = step; i <= text.length + step - 1; i += step) {
        box.value = text.slice(0, i);
        await sleep(22);
      }
      box.value = text;
      box.blur();
      const buttons = [...document.querySelectorAll('.gm-page button')];
      const go = buttons.find((b) => /generate|create|make/i.test(b.textContent || b.getAttribute('aria-label') || ''));
      if (go) await this.pointAt(go);
    }
    const card = this.tray.querySelector(`[data-job="${args.job && args.job.id}"]`);
    if (card) await this.pointAt(card);
  }

  /** The page's fillable fields, as the bridge carries them. */
  readPage() {
    let fields = [];
    try { fields = JSON.parse((this.bridge && this.bridge.fieldsJson) || '[]'); } catch (e) { fields = []; }
    return { ok: true, page: location.pathname, fields };
  }

  /** Fill fields through the page's own state (a Mesop event), wait for the
   * page to answer, then point at what changed. Never presses Generate. */
  async fill(args) {
    const bridge = this.bridge;
    if (!bridge || !bridge.actionEvent) return { ok: false, error: 'This page cannot be filled.' };
    const before = this.readPage().fields;
    const id = Math.random().toString(36).slice(2, 10);
    bridge.dispatchEvent(new MesopEvent(bridge.actionEvent, { action: 'fill', id, page: bridge.page || '', fields: args.fields || {} }));
    let result = null;
    for (let i = 0; i < 50 && !result; i++) {
      await sleep(100);
      try {
        const last = JSON.parse((this.bridge && this.bridge.lastFillJson) || '{}');
        if (last.id === id) result = last;
      } catch (e) { /* not yet */ }
    }
    if (!result) return { ok: false, error: 'The page did not answer in time.' };
    for (const name of Object.keys(result.changed || {})) {
      const f = before.find((x) => x.name === name);
      const el = f && this._fieldEl(f.label);
      if (el) await this.pointAt(el);
    }
    return { ok: !result.error, changed: result.changed || {}, refused: result.refused || {}, error: result.error };
  }

  /** The on-screen control whose label reads `label` (best effort). */
  _fieldEl(label) {
    const want = String(label || '').trim().toLowerCase();
    if (!want) return null;
    const nodes = document.querySelectorAll('.gm-page label, .gm-page mat-label, .gm-page [aria-label]');
    for (const n of nodes) {
      const text = (n.getAttribute('aria-label') || n.textContent || '').trim().toLowerCase();
      if (text === want || text.startsWith(want)) {
        const box = n.closest('.mat-mdc-form-field, mat-form-field, button, [role="button"]') || n;
        if (box.getBoundingClientRect().width > 0) return box;
      }
    }
    return null;
  }

  async showJob(args) {
    await this.navigate(args.page, args.params);
    const job = this.jobs.get(args.job.id) || args.job;
    const card = this.tray.querySelector(`[data-job="${job.id}"]`);
    if (card) await this.pointAt(card);
    this.openViewer(job);
    return { ok: true };
  }

  async download(job) {
    const ext = isAudioJob(job)
      ? 'wav'
      : (isVideoJob(job) ? 'mp4' : (job.mime_type === 'image/svg+xml' ? 'svg' : 'png'));
    const name = `genmedia-${job.handle.replace(/\s+/g, '-')}.${ext}`;
    try {
      let url = job.display_url;
      if (job.gcs_uri) {
        const r = await fetch(`/api/get_signed_url?gcs_uri=${encodeURIComponent(job.gcs_uri)}`);
        const data = await r.json();
        if (!r.ok || !data.signed_url) throw new Error(data.error || 'No signed URL');
        url = data.signed_url;
      }
      let href = url;
      if (!url.startsWith('data:')) {
        const blob = await (await fetch(url)).blob();
        href = URL.createObjectURL(blob);
      }
      const a = document.createElement('a');
      a.href = href; a.download = name;
      document.body.appendChild(a); a.click(); a.remove();
      if (href.startsWith('blob:')) setTimeout(() => URL.revokeObjectURL(href), 4000);
      return { ok: true, file: name };
    } catch (e) {
      console.error('Live download failed', e);
      window.open(job.display_url, '_blank', 'noopener');
      return { ok: false, error: 'Opened the file in a new tab instead.' };
    }
  }

  async _ui(msg) {
    const a = msg.args || {};
    let result = { ok: true };
    try {
      if (msg.action === 'navigate') result = { ok: await this.navigate(a.page, a.params) };
      else if (msg.action === 'compose') { this.compose(a); return; }
      else if (msg.action === 'show_job') result = await this.showJob(a);
      else if (msg.action === 'read_page') result = this.readPage();
      else if (msg.action === 'fill') result = await this.fill(a);
      else if (msg.action === 'download') {
        const job = this.jobs.get(a.job.id) || a.job;
        const card = this.tray.querySelector(`[data-job="${job.id}"]`);
        if (card) await this.pointAt(card);
        result = await this.download(job);
      } else if (msg.action === 'end_call') {
        setTimeout(() => this.stop(), Math.max(1200, (this.nextPlay - (this.outCtx ? this.outCtx.currentTime : 0)) * 1000 + 400));
        return;
      }
    } catch (e) {
      result = { ok: false, error: String(e && e.message || e) };
    }
    this._send({ type: 'ui_result', id: msg.id, result });
  }

  // ------------------------------------------------------------ call -----

  toggle() { return this.state === 'idle' ? this.start() : this.stop(); }

  /** Switch Fill only / Do it for me. A call in progress reconnects, since
   * the agent's tools are set when it connects. */
  async setMode(mode) {
    this.mode = mode === 'act' ? 'act' : 'fill';
    try { localStorage.setItem(MODE_KEY, this.mode); } catch (e) { /* not kept */ }
    this._renderMode();
    if (this.state !== 'idle') {
      this.stop();
      await sleep(250);
      this.start();
    }
  }

  _renderMode() {
    if (!this.modeBtn) return;
    const s = this.strings || DEFAULT_STRINGS;
    const fill = this.mode !== 'act';
    this.modeBtn.textContent = fill ? (s.fill || DEFAULT_STRINGS.fill) : (s.act || DEFAULT_STRINGS.act);
    this.modeBtn.setAttribute('aria-pressed', fill ? 'false' : 'true');
    this.modeBtn.title = s.modeHint || DEFAULT_STRINGS.modeHint;
    this.modeBtn.dataset.mode = this.mode;
  }

  async start() {
    if (this.state !== 'idle') return;
    this.state = 'connecting';
    this.agentLine = ''; this.userLine = '';
    this.capAgent.textContent = ''; this.capUser.textContent = '';
    this._renderState();
    // Audio contexts must start inside the click.
    try {
      this.outCtx = new AudioContext({ sampleRate: 24000 });
      this.nextPlay = 0;
    } catch (e) { this.outCtx = null; }
    try {
      this.micStream = await navigator.mediaDevices.getUserMedia({
        audio: { channelCount: 1, echoCancellation: true, noiseSuppression: true, autoGainControl: true },
      });
      this._startMic();
    } catch (e) {
      this.micStream = null;
      this._caption('user', this.strings.nomic, true);
    }
    const proto = location.protocol === 'https:' ? 'wss' : 'ws';
    const params = new URLSearchParams({ agent: this.mode === 'act' ? 'act' : 'fill' });
    if (new URLSearchParams(location.search).get('live') === 'offline') params.set('mode', 'offline');
    const ws = new WebSocket(`${proto}://${location.host}/api/live?${params}`);
    this.ws = ws;
    ws.onopen = () => this._sendScreen();
    ws.onmessage = (e) => { try { this._onMessage(JSON.parse(e.data)); } catch (err) { console.error(err); } };
    ws.onclose = (e) => {
      if (this.ws !== ws) return;
      if (e.code === 4403) this._caption('agent', 'Sign in again to use the voice agent.', true);
      if (e.code === 4404) this._caption('agent', 'The voice agent is turned off on this server.', true);
      this._teardown();
    };
    this._renderState();
  }

  stop() {
    this._send({ type: 'hangup' });
    const ws = this.ws;
    this.ws = null;
    if (ws) try { ws.close(); } catch (e) { /* closed */ }
    this._teardown();
  }

  _teardown() {
    this.ws = null;
    this._stopPlayback();
    if (this.micProc) { this.micProc.disconnect(); this.micProc.onaudioprocess = null; this.micProc = null; }
    if (this.micStream) { this.micStream.getTracks().forEach((t) => t.stop()); this.micStream = null; }
    if (this.inCtx) { this.inCtx.close().catch(() => {}); this.inCtx = null; }
    if (this.outCtx) { this.outCtx.close().catch(() => {}); this.outCtx = null; }
    this.state = 'idle';
    this.cursor.classList.remove('on');
    this._renderState();
  }

  toggleMute() {
    this.muted = !this.muted;
    if (this.muted) this._send({ type: 'audio_end' });
    this._renderMute();
  }

  _send(msg) {
    if (this.ws && this.ws.readyState === WebSocket.OPEN) this.ws.send(JSON.stringify(msg));
  }

  _sendScreen() {
    const fields = this.readPage().fields.map((f) => ({ name: f.name, value: f.value }));
    this._send({ type: 'screen', path: location.pathname, fields });
  }

  sendText(text) { this._send({ type: 'text', text }); }

  _startMic() {
    const ctx = new AudioContext({ sampleRate: 16000 });
    this.inCtx = ctx;
    const src = ctx.createMediaStreamSource(this.micStream);
    const proc = ctx.createScriptProcessor(2048, 1, 1);
    const sink = ctx.createGain();
    sink.gain.value = 0;
    const bar = this.level.querySelector('i');
    proc.onaudioprocess = (e) => {
      const input = e.inputBuffer.getChannelData(0);
      let peak = 0;
      const pcm = new Int16Array(input.length);
      for (let i = 0; i < input.length; i++) {
        const s = Math.max(-1, Math.min(1, input[i]));
        pcm[i] = s < 0 ? s * 0x8000 : s * 0x7fff;
        peak = Math.max(peak, Math.abs(s));
      }
      bar.style.width = `${this.muted ? 0 : Math.min(100, peak * 160)}%`;
      if (!this.muted && this.state === 'live') this._send({ type: 'audio', data: b64FromInt16(pcm) });
    };
    src.connect(proc); proc.connect(sink); sink.connect(ctx.destination);
    this.micProc = proc;
  }

  _play(b64) {
    const ctx = this.outCtx;
    if (!ctx) return;
    const pcm = int16FromB64(b64);
    const buf = ctx.createBuffer(1, pcm.length, 24000);
    const ch = buf.getChannelData(0);
    for (let i = 0; i < pcm.length; i++) ch[i] = pcm[i] / 0x8000;
    const node = ctx.createBufferSource();
    node.buffer = buf;
    node.connect(ctx.destination);
    const at = Math.max(ctx.currentTime + 0.02, this.nextPlay);
    node.start(at);
    this.nextPlay = at + buf.duration;
    this.playing.push(node);
    node.onended = () => {
      this.playing = this.playing.filter((n) => n !== node);
      if (!this.playing.length) this._renderState(false);
    };
    this._renderState(true);
  }

  _stopPlayback() {
    this.playing.forEach((n) => { try { n.stop(); } catch (e) { /* done */ } });
    this.playing = [];
    this.nextPlay = 0;
  }

  _onMessage(m) {
    switch (m.type) {
      case 'status':
        if (m.state === 'live') this.state = 'live';
        else if (m.state === 'offline') this.state = 'offline';
        else if (m.state === 'connecting') this.state = 'connecting';
        this._renderState();
        break;
      case 'audio': this._play(m.data); break;
      case 'interrupted': this._stopPlayback(); this._renderState(false); break;
      case 'transcript':
        if (m.who === 'user' && !m.final && this._lastWho !== 'user') this.userLine = '';
        if (m.who === 'agent' && !m.final && this._lastWho !== 'agent') this.agentLine = '';
        this._lastWho = m.who;
        this._caption(m.who, m.text, !!m.final);
        break;
      case 'turn_complete': this._lastWho = 'turn'; break;
      case 'job': this._job(m.job); break;
      case 'ui': this._ui(m); break;
      case 'error': this._caption('agent', m.message, true); break;
      default: break;
    }
  }
}

function gmLive() {
  if (!window.gmLive) window.gmLive = new GmLive();
  return window.gmLive;
}

class LiveAgentBridge extends LitElement {
  static properties = {
    actionEvent: { type: String },
    stringsJson: { type: String },
    page: { type: String },
    fieldsJson: { type: String },
    lastFillJson: { type: String },
  };

  connectedCallback() {
    super.connectedCallback();
    const live = gmLive();
    live.bridge = this;
    // Report the new page to the agent and refresh the launcher once the page has rendered.
    setTimeout(() => { live._sendScreen(); live.refreshLauncher(); }, 300);
  }

  disconnectedCallback() {
    super.disconnectedCallback();
    const live = window.gmLive;
    if (live && live.bridge === this) live.bridge = null;
  }

  updated(changed) {
    if (changed.has('stringsJson') && this.stringsJson) {
      try { gmLive().setStrings(JSON.parse(this.stringsJson)); } catch (e) { /* keep defaults */ }
    }
  }

  render() { return null; }
}

class LiveCallButton extends LitElement {
  static properties = { stringsJson: { type: String } };

  static styles = css`
    :host { display: block; }
    button { display: inline-flex; align-items: center; gap: 12px; height: 56px; padding: 0 26px 0 20px;
      border: 0; border-radius: 999px; cursor: pointer; font: 500 16px "Google Sans", Roboto, Arial, sans-serif;
      background: var(--sys-primary, #1a5fd8); color: var(--sys-on-primary, #fff);
      box-shadow: 0 8px 28px rgba(26, 95, 216, 0.35); transition: transform .15s, box-shadow .15s; }
    button:hover { transform: translateY(-1px); box-shadow: 0 10px 32px rgba(26, 95, 216, 0.45); }
    button:focus-visible { outline: 3px solid var(--sys-primary, #1a5fd8); outline-offset: 3px; }
    svg { width: 22px; height: 22px; fill: currentColor; }
    p { margin: 10px 0 0; font: 13px "Google Sans Text", Roboto, Arial, sans-serif; color: var(--sys-on-surface-variant, #44474e); }
  `;

  connectedCallback() {
    super.connectedCallback();
    setTimeout(() => gmLive().refreshLauncher(), 50);
  }

  disconnectedCallback() {
    super.disconnectedCallback();
    setTimeout(() => window.gmLive && window.gmLive.refreshLauncher(), 50);
  }

  render() {
    let s = DEFAULT_STRINGS;
    try { if (this.stringsJson) s = { ...s, ...JSON.parse(this.stringsJson) }; } catch (e) { /* defaults */ }
    return html`
      <button type="button" @click=${() => gmLive().toggle()} aria-label=${s.talk}>
        <svg viewBox="0 0 24 24" aria-hidden="true"><path d="M12 14a3 3 0 0 0 3-3V5a3 3 0 0 0-6 0v6a3 3 0 0 0 3 3zm5-3a5 5 0 0 1-10 0H5a7 7 0 0 0 6 6.92V21h2v-3.08A7 7 0 0 0 19 11z"/></svg>
        ${s.talk}
      </button>`;
  }
}

if (!customElements.get('live-agent-bridge')) customElements.define('live-agent-bridge', LiveAgentBridge);
if (!customElements.get('live-call-button')) customElements.define('live-call-button', LiveCallButton);
