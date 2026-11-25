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
 * The agent always does the work (it runs the jobs itself). The call window
 * works like a video call: it starts on the right, can be dragged anywhere
 * and minimised to a small pill while the call goes on. Jobs sit in a list
 * inside it; results open in a small viewer window.
 * <live-call-button> is the big call button on the home page.
 */
import { LitElement, html, css } from '/ui/vendor/lit-3.2.1.js';

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
  avatarNoSupport: 'This browser cannot play the avatar, so the call is voice only.',
  minimize: 'Minimize',
  expand: 'Expand',
  restore: 'Restore',
  keyboard: 'Type instead',
  noJobs: 'Things you ask for show up here.',
  avatarOn: 'Turn the avatar off',
  avatarOff: 'Turn the avatar on',
  toolRead: 'Reading the page',
  toolFill: 'Filling the page',
  toolOpen: 'Opening the page',
  toolWatch: 'Watching the film',
  toolFix: 'Starting the fix',
  signin: 'Sign in again to use the voice agent.',
  disabled: 'The voice agent is turned off on this server.',
  failed: 'Failed',
};
const CALL_POS_KEY = 'gm-live-pos';
// What the dock says while the agent runs a tool (instead of "Listening").
// Values are keys of the strings (translated on the server).
const TOOL_ACTIVITY = {
  read_page: 'toolRead',
  fill_fields: 'toolFill',
  open_page: 'toolOpen',
  plan_film_fix: 'toolWatch',
  run_film_fix: 'toolFix',
};
const CAPTION_FADE_MS = 8000;
// Live Avatar: the model streams one fragmented MP4 (H.264 Constrained
// Baseline 704x1280 with the AAC voice inside), played through MediaSource.
const AVATAR_KEY = 'gm-live-avatar';
const AVATAR_MIME = 'video/mp4; codecs="avc1.42C01F, mp4a.40.2"';
// Seconds the avatar may fall behind before it jumps ahead (a background tab).
const AVATAR_MAX_LAG = 20;
function savedAvatar() {
  try { return localStorage.getItem(AVATAR_KEY) === '1'; } catch (e) { return false; }
}
function avatarSupported() {
  return typeof MediaSource !== 'undefined' && MediaSource.isTypeSupported(AVATAR_MIME);
}
// The avatar's MediaSource, run in a dedicated worker (see _openAvatar).
const AVATAR_WORKER = `
let ms = null, sb = null, played = 0;
const queue = [];
function feed() {
  if (!sb || sb.updating) return;
  const b = sb.buffered;
  if (b.length) {
    const end = b.end(b.length - 1);
    postMessage({ end });
    // Drop only what was played long ago, never what is still to come.
    if (played - b.start(0) > 30) { sb.remove(b.start(0), played - 10); return; }
  }
  const next = queue.shift();
  if (next) {
    try { sb.appendBuffer(next); } catch (e) { postMessage({ error: String(e) }); }
  }
}
onmessage = (e) => {
  if (e.data.mime) {
    ms = new MediaSource();
    ms.addEventListener('sourceopen', () => {
      sb = ms.addSourceBuffer(e.data.mime);
      sb.mode = 'sequence';
      sb.addEventListener('updateend', feed);
      feed();
    });
    postMessage({ handle: ms.handle }, [ms.handle]);
  } else if (e.data.bytes) {
    queue.push(e.data.bytes);
    feed();
  } else if (e.data.played !== undefined) {
    played = e.data.played;
  }
};
`;
/** A short line for the viewer: the first clause of the prompt. */
function shortText(prompt) {
  const first = String(prompt || '').split(/[.,;:\n]/)[0].trim();
  if (first.length <= 64) return first;
  return first.slice(0, 64).replace(/\s+\S*$/, '') + '…';
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
.gml-glass { background: var(--gm-glass-solid, rgba(255,255,255,.94));
  backdrop-filter: blur(var(--gm-glass-blur, 18px)); -webkit-backdrop-filter: blur(var(--gm-glass-blur, 18px));
  border: 1px solid var(--gm-glass-border, rgba(0,0,0,.08));
  box-shadow: 0 18px 50px rgba(0,0,0,.28); }
.gml-btn { pointer-events: auto; border: 0; cursor: pointer; font: inherit; border-radius: 999px; padding: 0;
  display: inline-flex; align-items: center; justify-content: center; gap: 8px; color: inherit; }
.gml-btn:focus-visible { outline: 2px solid var(--sys-primary, #1a5fd8); outline-offset: 2px; }
.gml-btn svg { width: 20px; height: 20px; fill: currentColor; flex: none; }
.gml-launch { position: fixed; inset-inline-end: 20px; bottom: 20px; height: 48px; min-width: 48px; padding: 0 14px;
  background: var(--sys-primary, #1a5fd8); color: var(--sys-on-primary, #fff); font-weight: 500;
  box-shadow: 0 6px 20px rgba(26,95,216,.35); }
.gml-launch span { display: none; }
.gml-launch:hover span, .gml-launch:focus-visible span { display: inline; }
.gml-launch:hover, .gml-launch:focus-visible { padding: 0 18px 0 14px; }
@keyframes gml-pop { from { opacity: 0; transform: scale(.96); } to { opacity: 1; transform: none; } }
@keyframes gml-pulse { 0% { box-shadow: 0 0 0 0 rgba(30,142,62,.45); } 70% { box-shadow: 0 0 0 8px rgba(30,142,62,0); } 100% { box-shadow: 0 0 0 0 rgba(30,142,62,0); } }
@keyframes gml-breathe { 50% { transform: scale(1.08); } }
@keyframes gml-rot { to { transform: rotate(360deg); } }
@keyframes gml-ping { 0% { box-shadow: 0 0 0 0 rgba(26,95,216,.6); } 100% { box-shadow: 0 0 0 12px rgba(26,95,216,0); } }

/* ---- Call window: one card, like a video call. Drag it anywhere; it starts on the right. */
.gml-call { position: fixed; top: 20px; right: 20px; width: 280px; border-radius: 24px; overflow: hidden;
  pointer-events: auto; display: flex; flex-direction: column; touch-action: none;
  animation: gml-pop .25s ease-out; transition: width .2s ease, border-radius .2s ease; }
.gml-call.dragging { transition: none; cursor: grabbing; }
.gml-stage { position: relative; height: 156px; display: grid; place-items: center; cursor: grab; overflow: hidden;
  background: radial-gradient(circle at 50% 45%, rgba(79,124,247,.28), transparent 68%), var(--sys-surface-container-high, #262a36); }
.gml-call.has-avatar .gml-stage { height: auto; aspect-ratio: 704 / 1280; max-height: min(440px, 52vh); }
.gml-stage video { position: absolute; inset: 0; width: 100%; height: 100%; object-fit: cover; background: #0b0d12; }
.gml-orb { width: 76px; height: 76px; border-radius: 50%;
  background: radial-gradient(circle at 35% 30%, #a8c7fa, #4f7cf7 55%, #7b3fe4);
  box-shadow: 0 0 0 calc(var(--lvl, 0) * 26px) rgba(79,124,247,.22); transition: box-shadow .1s; }
.gml-call[data-s="speaking"] .gml-orb, .gml-call[data-s="working"] .gml-orb { animation: gml-breathe 1.3s ease-in-out infinite; }
.gml-call.has-avatar .gml-orb { display: none; }
.gml-top { position: absolute; top: 10px; inset-inline: 10px; display: flex; align-items: center; justify-content: space-between; gap: 8px; z-index: 1; }
.gml-state { display: inline-flex; align-items: center; gap: 7px; height: 28px; padding: 0 11px; border-radius: 999px;
  font-size: 12px; font-weight: 500; white-space: nowrap; color: #fff; background: rgba(0,0,0,.42);
  backdrop-filter: blur(8px); -webkit-backdrop-filter: blur(8px); }
.gml-dot { width: 8px; height: 8px; border-radius: 50%; background: #9aa0a6; flex: none; }
.gml-dot[data-s="live"] { background: #34a853; animation: gml-pulse 1.6s infinite; }
.gml-dot[data-s="speaking"], .gml-dot[data-s="working"] { background: #8ab4f8; }
.gml-dot[data-s="offline"] { background: #fbbc04; }
.gml-chip { width: 28px; height: 28px; color: #fff; background: rgba(0,0,0,.42); backdrop-filter: blur(8px); }
.gml-chip svg { width: 18px; height: 18px; }
.gml-chip:hover { background: rgba(0,0,0,.6); }
.gml-caps { padding: 10px 16px 0; display: flex; flex-direction: column; gap: 4px; }
.gml-caps:not(:has(.gml-cap:not(:empty):not(.faded))) { display: none; }
.gml-cap { font-size: 13.5px; line-height: 1.4; overflow: hidden;
  display: -webkit-box; -webkit-line-clamp: 3; -webkit-box-orient: vertical; }
.gml-cap.user { font-size: 12px; color: var(--sys-on-surface-variant, #5f6368); -webkit-line-clamp: 2; }
.gml-cap:empty, .gml-cap.faded { display: none; }
.gml-notice { font-size: 12px; color: #b06000; }
.gml-controls { display: flex; align-items: center; justify-content: center; gap: 8px; padding: 12px; }
.gml-ctl { position: relative; width: 40px; height: 40px; flex: none; background: var(--gm-tonal, rgba(127,127,127,.14)); }
.gml-ctl:hover { background: var(--gm-tonal-hover, rgba(127,127,127,.22)); }
.gml-ctl.on { background: var(--sys-primary-container, #d3e3fd); color: var(--sys-on-primary-container, #041e49); }
.gml-ctl.off { background: #fce8e6; color: #c5221f; }
.gml-ctl.mic:not(.off) { box-shadow: 0 0 0 calc(var(--lvl, 0) * 5px) rgba(52,168,83,.35); }
.gml-ctl.ping { animation: gml-ping 1s ease-out 2; }
.gml-badge { position: absolute; top: -3px; inset-inline-end: -3px; min-width: 18px; height: 18px; padding: 0 5px; border-radius: 9px;
  background: var(--sys-primary, #1a5fd8); color: #fff; font-size: 11px; font-weight: 600; display: grid; place-items: center; }
.gml-badge:empty { display: none; }
.gml-hang { width: 40px; height: 40px; flex: none; background: #d93025; color: #fff; }
.gml-hang:hover { background: #c5221f; }
.gml-restore, .gml-mstate { display: none; }
.gml-typed { padding: 0 12px 12px; }
.gml-input { width: 100%; height: 40px; border-radius: 20px; padding: 0 14px; font: inherit; font-size: 14px; border: 0;
  background: var(--gm-tonal, rgba(127,127,127,.14)); color: inherit; pointer-events: auto; outline: none; }
.gml-input:focus { background: var(--gm-tonal-hover, rgba(127,127,127,.22)); }
.gml-jobs { display: flex; flex-direction: column; gap: 6px; padding: 0 10px 10px; max-height: min(280px, 34vh); overflow-y: auto; }
.gml-jobs h2 { margin: 0 6px 2px; font-size: 11px; font-weight: 600; letter-spacing: .05em; text-transform: uppercase;
  color: var(--sys-on-surface-variant, #5f6368); }
.gml-empty { margin: 0 6px 4px; font-size: 13px; color: var(--sys-on-surface-variant, #5f6368); }
.gml-job { display: flex; flex-wrap: wrap; gap: 8px 10px; align-items: center; padding: 6px; border-radius: 14px; cursor: pointer;
  background: var(--gm-tonal, rgba(127,127,127,.1)); border: 0; text-align: start; width: 100%; color: inherit; font: inherit; }
.gml-job:hover { background: var(--gm-tonal-hover, rgba(127,127,127,.18)); }
.gml-job audio { width: 100%; height: 32px; display: block; }
.gml-job.flash { box-shadow: 0 0 0 2px rgba(26,95,216,.45); }
.gml-thumb { width: 44px; height: 44px; border-radius: 10px; flex: none; overflow: hidden; display: grid; place-items: center;
  background: var(--sys-surface-container-high, #e6e8ec); }
.gml-thumb img, .gml-thumb video { width: 100%; height: 100%; object-fit: cover; }
.gml-thumb svg { width: 22px; height: 22px; fill: var(--sys-primary, #1a5fd8); }
.gml-spin { width: 20px; height: 20px; border-radius: 50%; border: 2.5px solid rgba(26,95,216,.2);
  border-top-color: var(--sys-primary, #1a5fd8); animation: gml-rot .9s linear infinite; }
.gml-meta { min-width: 0; flex: 1; }
.gml-meta b { display: block; font-size: 13px; font-weight: 600; text-transform: capitalize; }
.gml-meta span { display: block; font-size: 12px; color: var(--sys-on-surface-variant, #5f6368);
  white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }
.gml-meta em { font-style: normal; font-size: 11px; color: var(--sys-on-surface-variant, #5f6368); }
.gml-meta em.failed { color: #c5221f; }

/* Minimised: a small pill that keeps the call going. */
.gml-call.min { width: auto; flex-direction: row; align-items: center; border-radius: 999px; padding: 6px; gap: 4px; }
.gml-call.min .gml-stage { width: 44px; height: 44px; aspect-ratio: auto; max-height: none; border-radius: 50%; flex: none; }
.gml-call.min .gml-orb { width: 26px; height: 26px; }
.gml-call.min .gml-top, .gml-call.min .gml-caps, .gml-call.min .gml-typed, .gml-call.min .gml-jobs,
.gml-call.min .gml-ctl.opt { display: none !important; }
.gml-call.min .gml-mstate { display: inline-block; padding: 0 8px 0 6px; font-size: 13px; font-weight: 500; white-space: nowrap; cursor: grab; }
.gml-call.min .gml-restore { display: inline-flex; }
.gml-call.min .gml-controls { padding: 0; gap: 6px; }

/* ---- Result viewer: the picture edge to edge, small window buttons, one line under it. */
.gml-viewer { position: fixed; left: 50%; top: 50%; transform: translate(-50%, -50%); display: flex; flex-direction: column;
  border-radius: 20px; overflow: hidden; pointer-events: auto; max-width: calc(100vw - 32px); touch-action: none;
  animation: gml-pop .22s ease-out; }
.gml-viewer.placed { transform: none; animation: none; }
.gml-vmedia { position: relative; line-height: 0; background: #000; cursor: grab; }
.gml-vmedia img, .gml-vmedia video { display: block; width: auto; height: auto;
  max-width: min(880px, max(min(360px, calc(100vw - 32px)), calc(100vw - 680px))); max-height: 68vh; }
.gml-viewer.big .gml-vmedia img, .gml-viewer.big .gml-vmedia video { max-width: calc(100vw - 48px); max-height: calc(100vh - 120px); }
.gml-vmedia.audio { background: transparent; line-height: normal; padding: 48px 14px 6px; width: min(380px, calc(100vw - 32px)); }
.gml-vmedia.audio audio { width: 100%; display: block; }
.gml-vwait { width: min(420px, calc(100vw - 32px)); height: 260px; display: grid; place-items: center; line-height: normal;
  padding: 24px; text-align: center; font-size: 14px; color: #e8eaed; background: var(--sys-surface-container-high, #262a36); }
.gml-vwait svg { width: 40px; height: 40px; fill: var(--sys-primary, #8ab4f8); }
.gml-vtools { position: absolute; top: 10px; inset-inline-end: 10px; display: flex; gap: 2px; padding: 3px; border-radius: 999px;
  background: rgba(0,0,0,.45); backdrop-filter: blur(8px); -webkit-backdrop-filter: blur(8px); line-height: normal; z-index: 1; }
.gml-vt { width: 28px; height: 28px; color: #fff; background: transparent; }
.gml-vt svg { width: 16px; height: 16px; }
.gml-vt:hover { background: rgba(255,255,255,.18); }
.gml-vfoot { display: flex; align-items: center; gap: 10px; padding: 8px 8px 8px 16px; min-width: 0; cursor: grab; }
.gml-vdesc { flex: 1; min-width: 0; font-size: 13px; white-space: nowrap; overflow: hidden; text-overflow: ellipsis;
  color: var(--sys-on-surface-variant, #5f6368); }
.gml-vdesc b { color: var(--sys-on-surface, #1b1c1f); font-weight: 600; text-transform: capitalize; }
.gml-vdl { width: 34px; height: 34px; flex: none; background: var(--gm-tonal, rgba(127,127,127,.14)); }
.gml-vdl:hover { background: var(--gm-tonal-hover, rgba(127,127,127,.22)); }
.gml-vdl svg { width: 18px; height: 18px; }
.gml-vchip { position: fixed; left: 20px; bottom: 20px; display: inline-flex; align-items: center; gap: 4px; padding: 5px;
  border-radius: 999px; pointer-events: auto; animation: gml-pop .2s ease-out; }
.gml-vchip .gml-thumb { width: 36px; height: 36px; border-radius: 50%; }
.gml-vchip-open { height: 36px; padding: 0 10px 0 4px; gap: 8px; background: transparent; font-size: 13px; font-weight: 500; text-transform: capitalize; }
.gml-vchip .gml-vt { color: inherit; }
.gml-vchip .gml-vt:hover { background: var(--gm-tonal-hover, rgba(127,127,127,.22)); }

.gml-cursor { position: fixed; left: 0; top: 0; width: 26px; height: 26px; margin: -13px 0 0 -13px; border-radius: 50%;
  background: radial-gradient(circle, rgba(66,133,244,.95) 0 30%, rgba(66,133,244,.35) 31% 100%);
  box-shadow: 0 0 18px rgba(66,133,244,.8); opacity: 0;
  transition: transform .7s cubic-bezier(.22,.8,.26,1), opacity .25s; }
.gml-cursor.on { opacity: 1; }
.gml-ring { position: fixed; border-radius: 12px; border: 3px solid rgba(66,133,244,.9); box-shadow: 0 0 0 6px rgba(66,133,244,.18);
  pointer-events: none; animation: gml-ring 1.2s ease-out forwards; }
@keyframes gml-ring { 0% { opacity: 0; transform: scale(1.06); } 20% { opacity: 1; transform: scale(1); } 100% { opacity: 0; } }
.gml-hidden { display: none !important; }
@media (max-width: 600px) {
  .gml-launch { width: 52px; height: 52px; padding: 0; inset-inline-end: 16px; bottom: 16px; }
  .gml-launch span { display: none; }
  .gml-launch svg { width: 22px; height: 22px; }
  .gml-call { width: 232px; }
  .gml-call.has-avatar .gml-stage { max-height: 40vh; }
  .gml-controls { gap: 6px; padding: 10px; }
  .gml-ctl, .gml-hang { width: 36px; height: 36px; }
}
@media (prefers-reduced-motion: reduce) {
  .gml-cursor, .gml-job, .gml-viewer, .gml-call, .gml-orb { transition: none; animation: none !important; }
}
`;

const ICON_MIC = '<svg viewBox="0 0 24 24" aria-hidden="true"><path d="M12 14a3 3 0 0 0 3-3V5a3 3 0 0 0-6 0v6a3 3 0 0 0 3 3zm5-3a5 5 0 0 1-10 0H5a7 7 0 0 0 6 6.92V21h2v-3.08A7 7 0 0 0 19 11z"/></svg>';
const ICON_MIC_OFF = '<svg viewBox="0 0 24 24" aria-hidden="true"><path d="M19 11h-2c0 .74-.16 1.43-.43 2.05l1.47 1.47A6.9 6.9 0 0 0 19 11zM15 11V5a3 3 0 0 0-5.94-.6L15 10.34zM4.27 3 3 4.27l6 6V11a3 3 0 0 0 4.38 2.65l1.55 1.55A5 5 0 0 1 7 11H5a7 7 0 0 0 6 6.92V21h2v-3.08a6.9 6.9 0 0 0 2.98-1.06L19.73 21 21 19.73z"/></svg>';
const icon = (d) => `<svg viewBox="0 0 24 24" aria-hidden="true"><path d="${d}"/></svg>`;
const ICON_MINUS = icon('M5 11h14v2H5z');
const ICON_EXPAND = icon('M4 4h6v2H6v4H4zm10 0h6v6h-2V6h-4zM4 14h2v4h4v2H4zm14 0h2v6h-6v-2h4z');
const ICON_SHRINK = icon('M8 4h2v6H4V8h4zm6 0h2v4h4v2h-6zM4 14h6v6H8v-4H4zm10 0h6v2h-4v4h-2z');
const ICON_CLOSE = icon('M19 6.4 17.6 5 12 10.6 6.4 5 5 6.4 10.6 12 5 17.6 6.4 19 12 13.4 17.6 19 19 17.6 13.4 12z');
const ICON_DOWNLOAD = icon('M5 20h14v-2H5zM12 16l5-5-1.4-1.4-2.6 2.6V4h-2v8.2L8.4 9.6 7 11z');
const ICON_CAM = icon('M17 10.5V7a1 1 0 0 0-1-1H4a1 1 0 0 0-1 1v10a1 1 0 0 0 1 1h12a1 1 0 0 0 1-1v-3.5l4 4v-11z');
const ICON_CAM_OFF = icon('M21 6.5l-4 4V7a1 1 0 0 0-1-1H9.8L21 17.2zM3.3 2 2 3.3 4.7 6H4a1 1 0 0 0-1 1v10a1 1 0 0 0 1 1h12c.2 0 .4-.1.5-.2l3.2 3.2 1.3-1.3z');
const ICON_KEYS = icon('M20 5H4a2 2 0 0 0-2 2v10a2 2 0 0 0 2 2h16a2 2 0 0 0 2-2V7a2 2 0 0 0-2-2zm-9 3h2v2h-2zm0 3h2v2h-2zM8 8h2v2H8zm0 3h2v2H8zm-1 2H5v-2h2zm0-3H5V8h2zm9 7H8v-2h8zm0-4h-2v-2h2zm0-3h-2V8h2zm3 3h-2v-2h2zm0-3h-2V8h2z');
const ICON_JOBS = icon('M4 4h7v7H4zm9 0h7v7h-7zM4 13h7v7H4zm9 0h7v7h-7z');
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

    // The call window: stage (avatar or voice orb), captions, controls, typed
    // input and the jobs list. Dragged by anything that is not a control.
    const call = this._el('div', 'gml-call gml-glass gml-hidden', root);
    call.setAttribute('role', 'region');
    this.call = call;
    this.dock = call; // older code and tests name it the dock
    this.stage = this._el('div', 'gml-stage', call);
    this._el('div', 'gml-orb', this.stage);
    const top = this._el('div', 'gml-top', this.stage);
    const st = this._el('div', 'gml-state', top);
    this.dot = this._el('i', 'gml-dot', st);
    this.stateText = this._el('span', '', st);
    this.minBtn = this._el('button', 'gml-btn gml-chip', top, ICON_MINUS);
    this.minBtn.type = 'button';
    this.minBtn.addEventListener('click', () => this.setMinimized(true));

    this.captions = this._el('div', 'gml-caps', call);
    this.capUser = this._el('div', 'gml-cap user', this.captions);
    this.capAgent = this._el('div', 'gml-cap', this.captions);
    this.capAgent.setAttribute('aria-live', 'polite');

    const controls = this._el('div', 'gml-controls', call);
    this.mstate = this._el('span', 'gml-mstate', controls);
    this.restoreBtn = this._el('button', 'gml-btn gml-ctl gml-restore', controls, ICON_EXPAND);
    this.restoreBtn.type = 'button';
    this.restoreBtn.addEventListener('click', () => this.setMinimized(false));
    this.muteBtn = this._el('button', 'gml-btn gml-ctl mic', controls, ICON_MIC);
    this.muteBtn.type = 'button';
    this.muteBtn.addEventListener('click', () => this.toggleMute());
    this.avatar = savedAvatar();
    this.avatarBtn = this._el('button', 'gml-btn gml-ctl opt', controls, ICON_CAM);
    this.avatarBtn.type = 'button';
    this.avatarBtn.addEventListener('click', () => this.setAvatar(!this.avatar));
    this.typeBtn = this._el('button', 'gml-btn gml-ctl opt', controls, ICON_KEYS);
    this.typeBtn.type = 'button';
    this.typeBtn.addEventListener('click', () => this.setTyping(!this.typing));
    this.jobsBtn = this._el('button', 'gml-btn gml-ctl opt', controls, ICON_JOBS + '<span class="gml-badge"></span>');
    this.jobsBtn.type = 'button';
    this.jobsBtn.addEventListener('click', () => this.setJobsOpen(!this.jobsOpen));
    this.hangBtn = this._el('button', 'gml-btn gml-hang', controls, ICON_HANG);
    this.hangBtn.type = 'button';
    this.hangBtn.addEventListener('click', () => this.stop());

    const typed = this._el('div', 'gml-typed gml-hidden', call);
    this.typedRow = typed;
    this.input = this._el('input', 'gml-input', typed);
    this.input.type = 'text';
    this.input.addEventListener('keydown', (e) => {
      if (e.key === 'Enter' && this.input.value.trim()) {
        this.sendText(this.input.value.trim());
        this.input.value = '';
      }
    });

    this.jobsPanel = this._el('div', 'gml-jobs gml-hidden', call);
    this.trayTitle = this._el('h2', '', this.jobsPanel);
    this.jobsEmpty = this._el('p', 'gml-empty', this.jobsPanel);
    this.tray = this.jobsPanel; // job cards live here

    this._draggable(call, call, () => this._saveCallPos());
    window.addEventListener('resize', () => { if (!this.call.classList.contains('gml-hidden')) this._applyCallPos(); });

    this.viewer = this._el('div', 'gml-viewer gml-glass gml-hidden', root);
    this._draggable(this.viewer, this.viewer);
    document.addEventListener('keydown', (e) => {
      if (e.key === 'Escape' && !this.viewer.classList.contains('gml-hidden')) this.closeViewer();
    });
    this.cursor = this._el('div', 'gml-cursor', root);
    this._applyStrings();
  }

  setStrings(strings) {
    if (!strings) return;
    Object.assign(this.strings, strings);
    this._applyStrings();
  }

  _label(el, text) {
    el.setAttribute('aria-label', text);
    el.title = text;
  }

  _applyStrings() {
    const s = this.strings;
    this.launch.querySelector('span').textContent = s.talk;
    this.launch.setAttribute('aria-label', s.talk);
    this._renderAvatar();
    this.input.placeholder = s.type;
    this.input.setAttribute('aria-label', s.type);
    this._label(this.hangBtn, s.hangup);
    this._label(this.minBtn, s.minimize || DEFAULT_STRINGS.minimize);
    this._label(this.restoreBtn, s.restore || DEFAULT_STRINGS.restore);
    this._label(this.typeBtn, s.keyboard || DEFAULT_STRINGS.keyboard);
    this._label(this.jobsBtn, s.jobs);
    this.call.setAttribute('aria-label', s.talk);
    this.trayTitle.textContent = s.jobs;
    this.jobsEmpty.textContent = s.noJobs || DEFAULT_STRINGS.noJobs;
    this._renderMute();
    this._renderState();
  }

  _renderMute() {
    const label = this.muted ? this.strings.unmute : this.strings.mute;
    this.muteBtn.innerHTML = this.muted ? ICON_MIC_OFF : ICON_MIC;
    this.muteBtn.classList.toggle('off', this.muted);
    this.muteBtn.setAttribute('aria-pressed', String(this.muted));
    this._label(this.muteBtn, label);
  }

  _renderState(speaking) {
    const active = this.state !== 'idle';
    // Live lives in each prompt box now; the floating launcher never shows.
    this.launch.classList.add('gml-hidden');
    const wasHidden = this.call.classList.contains('gml-hidden');
    this.call.classList.toggle('gml-hidden', !active);
    if (active && wasHidden) this._applyCallPos();
    const s = this.strings;
    let label = '';
    let key = this.state;
    if (this.state === 'connecting') label = s.connecting;
    else if (this.state === 'offline') label = s.offline;
    else if (this.state === 'live') {
      label = speaking ? s.speaking : s.listening;
      if (speaking) key = 'speaking';
      else if (this.activity) { label = `${this.activity}…`; key = 'working'; }
    }
    this.dot.dataset.s = key;
    this.call.dataset.s = key;
    this.stateText.textContent = label;
    this.mstate.textContent = label;
    this.muteBtn.classList.toggle('gml-hidden', !this.micStream);
  }

  refreshLauncher() { this._renderState(); }

  /** Show what the agent is doing in the call window; clears itself. */
  _setActivity(label) {
    this.activity = label;
    clearTimeout(this._activityTimer);
    if (label) this._activityTimer = setTimeout(() => this._setActivity(''), 20000);
    this._renderState(false);
  }

  _caption(who, text, final) {
    const el = who === 'user' ? this.capUser : this.capAgent;
    const key = who === 'user' ? 'userLine' : 'agentLine';
    if (final) this[key] = text;
    else this[key] = (this[key] + text).slice(-280);
    el.textContent = this[key];
    // Captions clear after a quiet spell so the window stays small.
    el.classList.remove('faded');
    clearTimeout(el._fade);
    el._fade = setTimeout(() => { el.classList.add('faded'); this._applyCallPos(); }, CAPTION_FADE_MS);
    this._applyCallPos();
  }

  // ------------------------------------------------------ call window ----

  setMinimized(on) {
    this.minimized = !!on;
    this.call.classList.toggle('min', this.minimized);
    this._applyCallPos();
  }

  setTyping(on) {
    this.typing = !!on;
    this.typedRow.classList.toggle('gml-hidden', !this.typing);
    this.typeBtn.classList.toggle('on', this.typing);
    this.typeBtn.setAttribute('aria-pressed', String(this.typing));
    this._applyCallPos();
    if (this.typing) this.input.focus();
  }

  setJobsOpen(on) {
    this.jobsOpen = !!on;
    this.jobsPanel.classList.toggle('gml-hidden', !this.jobsOpen);
    this.jobsBtn.classList.toggle('on', this.jobsOpen);
    this.jobsBtn.setAttribute('aria-pressed', String(this.jobsOpen));
    this.jobsBtn.classList.remove('ping');
    this._applyCallPos();
  }

  /** Drag `el` by `handle`; controls, inputs and media controls still work. */
  _draggable(el, handle, onDone) {
    handle.addEventListener('pointerdown', (e) => {
      if (e.button !== 0 || e.target.closest('button, input, a, video[controls], audio, .gml-jobs')) return;
      const r = el.getBoundingClientRect();
      const dx = e.clientX - r.left;
      const dy = e.clientY - r.top;
      // Pin the current spot first, so nothing jumps when centring stops.
      el.style.left = `${r.left}px`;
      el.style.top = `${r.top}px`;
      el.style.right = 'auto';
      el.classList.add('placed', 'dragging');
      try { handle.setPointerCapture(e.pointerId); } catch (_) { /* old browser */ }
      const move = (ev) => this._moveTo(el, ev.clientX - dx, ev.clientY - dy);
      const up = () => {
        handle.removeEventListener('pointermove', move);
        el.classList.remove('dragging');
        if (onDone) onDone();
      };
      handle.addEventListener('pointermove', move);
      handle.addEventListener('pointerup', up, { once: true });
      handle.addEventListener('pointercancel', up, { once: true });
      e.preventDefault();
    });
  }

  _moveTo(el, x, y) {
    const r = el.getBoundingClientRect();
    const nx = Math.max(8, Math.min(x, window.innerWidth - r.width - 8));
    const ny = Math.max(8, Math.min(y, window.innerHeight - r.height - 8));
    el.style.left = `${nx}px`;
    el.style.top = `${ny}px`;
  }

  /** Remember where the call window sits, anchored to the nearer side so it
   * stays put when it grows or shrinks (avatar, captions, minimise). */
  _saveCallPos() {
    const r = this.call.getBoundingClientRect();
    const right = r.left + r.width / 2 > window.innerWidth / 2;
    this.callPos = { side: right ? 'right' : 'left', inset: right ? window.innerWidth - r.right : r.left, top: r.top };
    try { localStorage.setItem(CALL_POS_KEY, JSON.stringify(this.callPos)); } catch (_) { /* not kept */ }
    this._applyCallPos();
  }

  _applyCallPos() {
    const el = this.call;
    if (!el) return;
    if (!this.callPos) {
      try { this.callPos = JSON.parse(localStorage.getItem(CALL_POS_KEY) || 'null'); } catch (_) { this.callPos = null; }
    }
    const p = this.callPos || { side: 'right', inset: 20, top: window.innerWidth > 600 ? 20 : 72 };
    const r = el.getBoundingClientRect();
    const inset = Math.max(8, Math.min(p.inset, window.innerWidth - r.width - 8));
    const topMax = Math.max(8, window.innerHeight - r.height - 8);
    el.style.top = `${Math.max(8, Math.min(p.top, topMax))}px`;
    el.style.left = p.side === 'left' ? `${inset}px` : 'auto';
    el.style.right = p.side === 'right' ? `${inset}px` : 'auto';
  }

  // ------------------------------------------------------------ jobs -----

  _job(job) {
    const known = this.jobs.get(job.id);
    this.jobs.set(job.id, job);
    this.jobsEmpty.classList.add('gml-hidden');
    let card = this.jobsPanel.querySelector(`[data-job="${job.id}"]`);
    if (!card) {
      card = this._el('button', 'gml-job');
      card.type = 'button';
      card.dataset.job = job.id;
      card.addEventListener('click', () => this.openViewer(this.jobs.get(job.id)));
      this.jobsPanel.insertBefore(card, this.jobsEmpty.nextSibling);
    }
    let thumb = '<i class="gml-spin"></i>';
    if (job.status === 'failed') {
      thumb = '!';
    } else if (job.status === 'done') {
      if (isAudioJob(job)) thumb = ICON_AUDIO;
      else if (isVideoJob(job) && job.display_url) thumb = '<video muted playsinline preload="metadata"></video>';
      else if (job.display_url) thumb = '<img alt="">';
      else thumb = ICON_STORY;
    }
    const label = job.is_edit ? `edit of ${job.source_job}` : job.prompt;
    const status = job.status === 'failed' ? (job.error || 'failed') : job.status;
    card.innerHTML = `<span class="gml-thumb">${thumb}</span><span class="gml-meta"><b></b><span></span><em></em></span>`;
    const media = card.querySelector('.gml-thumb img, .gml-thumb video');
    if (media) media.src = job.display_url;
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
      if (!this.jobsOpen) {
        this.jobsBtn.classList.remove('ping');
        void this.jobsBtn.offsetWidth; // restart the animation
        this.jobsBtn.classList.add('ping');
      }
    }
    const running = [...this.jobs.values()].filter((j) => j.status !== 'done' && j.status !== 'failed').length;
    this.jobsBtn.querySelector('.gml-badge').textContent = running ? String(running) : '';
    if (this.viewerJob === job.id && !this.viewer.classList.contains('gml-hidden')) this.openViewer(job);
    if (this.jobsOpen) this._applyCallPos();
  }

  /** Where the pointer goes for a job: its card when the list is open, else
   * the jobs button. */
  _jobAnchor(id) {
    const card = this.jobsPanel.querySelector(`[data-job="${id}"]`);
    if (card && card.getBoundingClientRect().width > 0) return card;
    if (this.state !== 'idle' && !this.minimized) return this.jobsBtn;
    return null;
  }

  _vtool(parent, icon, label, onClick, cls = 'gml-vt') {
    const b = this._el('button', `gml-btn ${cls}`, parent, icon);
    b.type = 'button';
    this._label(b, label);
    b.addEventListener('click', (e) => { e.stopPropagation(); onClick(); });
    return b;
  }

  openViewer(job) {
    if (!job) return;
    const v = this.viewer;
    const same = this.viewerJob === job.id && !v.classList.contains('gml-hidden');
    this.viewerJob = job.id;
    this._removeChip();
    const s = this.strings;
    if (!same) {
      v.classList.remove('placed', 'big');
      v.style.left = ''; v.style.top = ''; v.style.right = '';
    }
    v.classList.remove('gml-hidden');
    v.innerHTML = '';
    const media = this._el('div', 'gml-vmedia', v);
    const done = job.status === 'done';
    if (done && isAudioJob(job) && job.display_url) {
      media.classList.add('audio');
      const audio = this._el('audio', '', media);
      audio.src = job.display_url; audio.controls = true; audio.autoplay = !same;
    } else if (done && isVideoJob(job) && job.display_url) {
      const video = this._el('video', '', media);
      video.src = job.display_url; video.controls = true; video.autoplay = true; video.muted = true; video.loop = true;
      video.playsInline = true;
    } else if (done && job.display_url) {
      const img = this._el('img', '', media);
      img.src = job.display_url; img.alt = job.prompt || job.handle;
      img.draggable = false;
    } else {
      const wait = this._el('div', 'gml-vwait', media);
      if (job.status === 'failed') wait.textContent = job.error || s.failed || DEFAULT_STRINGS.failed;
      else wait.innerHTML = done ? ICON_STORY : '<i class="gml-spin"></i>';
    }
    const tools = this._el('div', 'gml-vtools', media);
    this._vtool(tools, ICON_MINUS, s.minimize || DEFAULT_STRINGS.minimize, () => this.minimizeViewer());
    this._vtool(tools, v.classList.contains('big') ? ICON_SHRINK : ICON_EXPAND,
      v.classList.contains('big') ? (s.restore || DEFAULT_STRINGS.restore) : (s.expand || DEFAULT_STRINGS.expand),
      () => { v.classList.toggle('big'); this.openViewer(this.jobs.get(job.id) || job); });
    this._vtool(tools, ICON_CLOSE, s.close, () => this.closeViewer());
    const foot = this._el('div', 'gml-vfoot', v);
    const desc = this._el('div', 'gml-vdesc', foot);
    this._el('b', '', desc).textContent = job.handle;
    const short = shortText(job.prompt);
    if (short) desc.appendChild(document.createTextNode(` · ${short}`));
    desc.title = job.prompt || '';
    if (done && (job.display_url || job.gcs_uri)) {
      this._vtool(foot, ICON_DOWNLOAD, s.download, () => this.download(job), 'gml-vdl');
    }
    if (v.classList.contains('placed')) requestAnimationFrame(() => { const r = v.getBoundingClientRect(); this._moveTo(v, r.left, r.top); });
  }

  /** Tuck the viewer into a small chip at the bottom; the chip brings it back. */
  minimizeViewer() {
    const job = this.jobs.get(this.viewerJob);
    this.viewer.classList.add('gml-hidden');
    this._removeChip();
    if (!job) return;
    const chip = this._el('div', 'gml-vchip gml-glass', this.root);
    this.chip = chip;
    const open = this._el('button', 'gml-btn gml-vchip-open', chip);
    open.type = 'button';
    const thumb = this._el('span', 'gml-thumb', open);
    if (job.display_url && !isAudioJob(job) && !isVideoJob(job)) {
      const img = this._el('img', '', thumb); img.src = job.display_url; img.alt = '';
    } else thumb.innerHTML = isAudioJob(job) ? ICON_AUDIO : ICON_STORY;
    this._el('span', '', open).textContent = job.handle;
    this._label(open, `${this.strings.restore || DEFAULT_STRINGS.restore}: ${job.handle}`);
    open.addEventListener('click', () => this.openViewer(this.jobs.get(job.id) || job));
    this._vtool(chip, ICON_CLOSE, this.strings.close, () => this.closeViewer());
  }

  _removeChip() {
    if (this.chip) { this.chip.remove(); this.chip = null; }
  }

  closeViewer() {
    this.viewerJob = null;
    this.viewer.classList.add('gml-hidden');
    this.viewer.innerHTML = '';
    this._removeChip();
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
    const card = this._jobAnchor(args.job && args.job.id);
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
    const card = this._jobAnchor(job.id);
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
        const card = this._jobAnchor(job.id);
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

  /** Turn the Live Avatar on or off (remembered in this browser). */
  async setAvatar(on) {
    this.avatar = !!on;
    this.avatarBlocked = false; // try again when asked
    try { localStorage.setItem(AVATAR_KEY, this.avatar ? '1' : '0'); } catch (e) { /* not kept */ }
    this._renderAvatar();
    await this._reconnect();
  }

  async _reconnect() {
    if (this.state === 'idle') return;
    this.stop();
    await sleep(250);
    this.start();
  }

  _renderAvatar() {
    if (!this.avatarBtn) return;
    const s = this.strings || DEFAULT_STRINGS;
    this.avatarBtn.classList.toggle('gml-hidden', !s.avatarName);
    const on = this.avatar && !this.avatarBlocked;
    this.avatarBtn.innerHTML = on ? ICON_CAM : ICON_CAM_OFF;
    this.avatarBtn.classList.toggle('on', on);
    this.avatarBtn.setAttribute('aria-pressed', on ? 'true' : 'false');
    const label = on ? (s.avatarOn || DEFAULT_STRINGS.avatarOn) : (s.avatarOff || DEFAULT_STRINGS.avatarOff);
    this.avatarBtn.setAttribute('aria-label', label);
    this.avatarBtn.title = s.avatarHint ? `${label}. ${s.avatarHint}` : label;
  }

  /** The avatar card and its player. Made inside the click so the video may
   * play with sound. The MediaSource lives in a worker when the browser can
   * (its handle needs no blob URL and appends stay off the page's thread),
   * else on the page behind a blob URL. */
  _openAvatar() {
    this._closeAvatar();
    // The avatar fills the call window's stage, like the other side of a video call.
    const card = this.stage;
    const video = this._el('video', '', card);
    this.call.classList.add('has-avatar');
    this._applyCallPos();
    video.playsInline = true;
    video.autoplay = true;
    const av = { card, video, queue: [], worker: null, ms: null, sb: null, url: '' };
    this.av = av;
    // The voice is inside the video: if the browser refuses it, go voice only.
    video.addEventListener('error', () => { if (this.av === av) this._avatarFailed(); });
    if (typeof MediaSourceHandle !== 'undefined' && MediaSource.canConstructInDedicatedWorker) {
      try {
        const src = URL.createObjectURL(new Blob([AVATAR_WORKER], { type: 'text/javascript' }));
        av.worker = new Worker(src);
        URL.revokeObjectURL(src);
        av.worker.onmessage = (e) => {
          if (this.av !== av) return;
          if (e.data.handle) { video.srcObject = e.data.handle; video.play().catch(() => {}); }
          if (e.data.end) this._avatarEdge(e.data.end);
          if (e.data.error) { console.error('avatar', e.data.error); this._avatarFailed(); }
        };
        av.worker.postMessage({ mime: AVATAR_MIME });
        return;
      } catch (e) {
        av.worker = null;
      }
    }
    av.ms = new MediaSource();
    av.url = URL.createObjectURL(av.ms);
    video.src = av.url;
    av.ms.addEventListener('sourceopen', () => {
      if (this.av !== av) return;
      av.sb = av.ms.addSourceBuffer(AVATAR_MIME);
      av.sb.mode = 'sequence'; // a resumed session starts its clock again
      av.sb.addEventListener('updateend', () => this._feedAvatar());
      this._feedAvatar();
    });
    video.play().catch(() => { /* starts once data arrives */ });
  }

  _video(b64) {
    const av = this.av;
    if (!av) return;
    const bin = atob(b64);
    const bytes = new Uint8Array(bin.length);
    for (let i = 0; i < bin.length; i++) bytes[i] = bin.charCodeAt(i);
    if (av.worker) av.worker.postMessage({ bytes }, [bytes.buffer]);
    else { av.queue.push(bytes); this._feedAvatar(); }
  }

  /** Keep playing as speech arrives. The model sends a reply faster than
   * real time, so the buffer runs ahead while the avatar talks: that is
   * speech still to play, not lag, and is never skipped (skipping it cut
   * most replies short). Only a far-behind player (a tab in the background)
   * jumps forward; a barge-in skips the rest of the reply (_avatarSkip). */
  _avatarEdge(end) {
    const av = this.av;
    const video = av && av.video;
    if (!video) return;
    av.end = end;
    if (end - video.currentTime > AVATAR_MAX_LAG) video.currentTime = Math.max(0, end - 0.2);
    if (video.paused) video.play().catch(() => {});
    if (av.worker) av.worker.postMessage({ played: video.currentTime });
  }

  /** The presenter talked over the avatar: drop the rest of its reply. */
  _avatarSkip() {
    const av = this.av;
    if (!av || !av.end) return;
    if (av.end > av.video.currentTime) av.video.currentTime = Math.max(0, av.end - 0.05);
  }

  _feedAvatar() {
    const av = this.av;
    if (!av || !av.sb || av.sb.updating) return;
    const b = av.sb.buffered;
    if (b.length) {
      this._avatarEdge(b.end(b.length - 1));
      // Drop what is long played so the buffer stays small.
      if (av.video.currentTime - b.start(0) > 30) {
        av.sb.remove(b.start(0), av.video.currentTime - 10);
        return;
      }
    }
    const next = av.queue.shift();
    if (next) {
      try { av.sb.appendBuffer(next); } catch (e) { console.error('avatar', e); this._avatarFailed(); }
    }
  }

  /** The avatar cannot play here: say so and reconnect voice only (for this
   * call; the saved choice stays, another browser may play it). */
  async _avatarFailed() {
    if (!this.av) return;
    console.warn('avatar', this.av.video.error && this.av.video.error.message);
    this._closeAvatar();
    this.avatarBlocked = true;
    this._renderAvatar();
    await this._reconnect();
    this._caption('agent', this.strings.avatarNoSupport || DEFAULT_STRINGS.avatarNoSupport, true);
  }

  _closeAvatar() {
    const av = this.av;
    this.av = null;
    if (!av) return;
    if (av.worker) av.worker.terminate();
    try { if (av.ms && av.ms.readyState === 'open') av.ms.endOfStream(); } catch (e) { /* closed */ }
    if (av.url) URL.revokeObjectURL(av.url);
    av.video.removeAttribute('src');
    av.video.srcObject = null;
    av.video.remove();
    this.call.classList.remove('has-avatar');
    this._applyCallPos();
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
    const params = new URLSearchParams({ agent: 'act' });
    // Site language: the agent's fallback until the presenter's own shows.
    if (this.strings.lang) params.set('lang', this.strings.lang);
    if (new URLSearchParams(location.search).get('live') === 'offline') params.set('mode', 'offline');
    if (this.avatar && this.strings.avatarName && !this.avatarBlocked) {
      if (avatarSupported()) { params.set('avatar', '1'); this._openAvatar(); }
      else this._caption('agent', this.strings.avatarNoSupport, true);
    }
    const ws = new WebSocket(`${proto}://${location.host}/api/live?${params}`);
    this.ws = ws;
    ws.onopen = () => this._sendScreen();
    ws.onmessage = (e) => { try { this._onMessage(JSON.parse(e.data)); } catch (err) { console.error(err); } };
    ws.onclose = (e) => {
      if (this.ws !== ws) return;
      if (e.code === 4403) this._caption('agent', this.strings.signin || DEFAULT_STRINGS.signin, true);
      if (e.code === 4404) this._caption('agent', this.strings.disabled || DEFAULT_STRINGS.disabled, true);
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
    this._closeAvatar();
    if (this.micProc) { this.micProc.disconnect(); this.micProc.onaudioprocess = null; this.micProc = null; }
    if (this.micStream) { this.micStream.getTracks().forEach((t) => t.stop()); this.micStream = null; }
    if (this.inCtx) { this.inCtx.close().catch(() => {}); this.inCtx = null; }
    if (this.outCtx) { this.outCtx.close().catch(() => {}); this.outCtx = null; }
    this.state = 'idle';
    this.cursor.classList.remove('on');
    if (this.minimized) this.setMinimized(false);
    if (this.call) this.call.style.setProperty('--lvl', '0');
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
    const call = this.call;
    proc.onaudioprocess = (e) => {
      const input = e.inputBuffer.getChannelData(0);
      let peak = 0;
      const pcm = new Int16Array(input.length);
      for (let i = 0; i < input.length; i++) {
        const s = Math.max(-1, Math.min(1, input[i]));
        pcm[i] = s < 0 ? s * 0x8000 : s * 0x7fff;
        peak = Math.max(peak, Math.abs(s));
      }
      call.style.setProperty('--lvl', this.muted ? '0' : Math.min(1, peak * 1.6).toFixed(2));
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
      case 'video': this._video(m.data); break;
      case 'interrupted': this._stopPlayback(); this._avatarSkip(); this._renderState(false); break;
      case 'transcript':
        if (m.who === 'user' && !m.final && this._lastWho !== 'user') this.userLine = '';
        if (m.who === 'agent' && !m.final && this._lastWho !== 'agent') this.agentLine = '';
        this._lastWho = m.who;
        this._caption(m.who, m.text, !!m.final);
        // The avatar's voice is inside the video, so the transcript says when it talks.
        if (this.av && m.who === 'agent') this._renderState(true);
        break;
      case 'turn_complete':
        this._lastWho = 'turn';
        this._setActivity('');
        if (this.av) setTimeout(() => this._renderState(false), 1500);
        break;
      case 'tool': {
        const key = TOOL_ACTIVITY[m.name];
        this._setActivity(key ? (this.strings[key] || DEFAULT_STRINGS[key]) : '');
        break;
      }
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
  static properties = {
    stringsJson: { type: String },
    compact: { type: Boolean, reflect: true },
    pill: { type: Boolean, reflect: true }, // Home prompt box: 44px round icon
    filled: { type: Boolean, reflect: true }, // a filled circle, like the Send button it swaps with
  };

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
    /* compact (studios, 40px) and pill (Home, 44px): a plain round icon
       button with five sound bars. On hover the bars take the Gemini
       gradient and move like a voice wave; at rest they are quiet grey. */
    :host([compact]) button, :host([pill]) button { width: 40px; height: 40px; padding: 0; gap: 0; justify-content: center;
      background: transparent; color: var(--sys-on-surface-variant, #44474e); box-shadow: none; }
    :host([pill]) button { width: 44px; height: 44px; }
    :host([compact]) button:hover, :host([pill]) button:hover { transform: none; box-shadow: none; background: var(--gm-tonal-hover, rgba(127, 127, 127, 0.14)); }
    :host([compact]) button.on { background: var(--sys-primary, #1a5fd8); color: var(--sys-on-primary, #fff); }
    :host([compact]) svg, :host([pill]) svg { width: 22px; height: 22px; overflow: visible; }
    .bar { fill: currentColor; transform-box: fill-box; transform-origin: 50% 50%; transition: fill 160ms ease; }
    button:hover .bar, button:focus-visible .bar { fill: url(#gm-live-grad); animation: gm-wave 900ms ease-in-out infinite; }
    button:hover .b2, button:focus-visible .b2 { animation-delay: -150ms; }
    button:hover .b3, button:focus-visible .b3 { animation-delay: -450ms; }
    button:hover .b4, button:focus-visible .b4 { animation-delay: -300ms; }
    button:hover .b5, button:focus-visible .b5 { animation-delay: -600ms; }
    /* filled: Home's Live button. Same size and shape as Send, on the
       Gemini gradient with white bars, so the two read as one slot. */
    :host([filled]) button { width: 40px; height: 40px; color: #fff;
      background: linear-gradient(135deg, #4f8df7 0%, #7b6cf6 55%, #c06ad8 100%);
      box-shadow: 0 2px 10px rgba(91, 108, 246, 0.35); transition: filter 140ms ease, box-shadow 140ms ease; }
    :host([filled]) button:hover { background: linear-gradient(135deg, #4f8df7 0%, #7b6cf6 55%, #c06ad8 100%); filter: brightness(1.08);
      box-shadow: 0 4px 16px rgba(91, 108, 246, 0.45); }
    :host([filled]) svg { width: 20px; height: 20px; }
    :host([filled]) button:hover .bar, :host([filled]) button:focus-visible .bar { fill: #fff; }
    :host([filled]) button:focus-visible { outline: 2px solid var(--sys-primary, #1a5fd8); outline-offset: 2px; }
    @keyframes gm-wave { 0%, 100% { transform: scaleY(0.45); } 50% { transform: scaleY(1.15); } }
    @media (prefers-reduced-motion: reduce) { button:hover .bar, button:focus-visible .bar { animation: none; } }
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
    if (this.compact || this.pill) {
      // A sound-wave icon, so Live never looks like the Dictate mic beside it.
      // Five separate bars so each can move on its own on hover.
      const wave = html`<svg viewBox="0 0 24 24" aria-hidden="true"><defs><linearGradient id="gm-live-grad" x1="0" y1="0" x2="1" y2="0">
        <stop offset="0" stop-color="#4f8df7"/><stop offset="0.6" stop-color="#9b6cf6"/><stop offset="1" stop-color="#e06aa5"/></linearGradient></defs>
        <rect class="bar b1" x="3" y="10" width="2" height="4" rx="1"/><rect class="bar b2" x="7" y="6" width="2" height="12" rx="1"/>
        <rect class="bar b3" x="11" y="2" width="2" height="20" rx="1"/><rect class="bar b4" x="15" y="6" width="2" height="12" rx="1"/>
        <rect class="bar b5" x="19" y="10" width="2" height="4" rx="1"/></svg>`;
      return html`<button type="button" @click=${() => gmLive().toggle()} aria-label=${s.talk} title=${s.talk}>${wave}</button>`;
    }
    return html`
      <button type="button" @click=${() => gmLive().toggle()} aria-label=${s.talk}>
        <svg viewBox="0 0 24 24" aria-hidden="true"><path d="M12 14a3 3 0 0 0 3-3V5a3 3 0 0 0-6 0v6a3 3 0 0 0 3 3zm5-3a5 5 0 0 1-10 0H5a7 7 0 0 0 6 6.92V21h2v-3.08A7 7 0 0 0 19 11z"/></svg>
        ${s.talk}
      </button>`;
  }
}

if (!customElements.get('live-agent-bridge')) customElements.define('live-agent-bridge', LiveAgentBridge);
if (!customElements.get('live-call-button')) customElements.define('live-call-button', LiveCallButton);
