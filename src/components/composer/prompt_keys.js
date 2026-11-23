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
 * <gm-prompt-keys>: Up / Down arrows step through your recent prompts, like a
 * terminal. Invisible; it sits inside a prompt card (.gm-composer, or any
 * element with [data-prompt-card]) and listens on that card's textarea.
 *
 * - Up on the first line (or in an empty box) shows the previous prompt;
 *   Down on the last line goes forward, then back to what you were typing.
 * - Every prompt you send (Enter, or the send button) is remembered in this
 *   browser, per studio (`page`). Prompts saved in your Library are fetched
 *   once from /api/prompts/<page> and added after the local ones.
 * - The textarea is a Mesop native textarea: after changing it we fire
 *   `input` and `blur`, so Mesop stores the text like a normal edit (the same
 *   path as prompt_tools.js).
 */
import { LitElement } from '/ui/vendor/lit-3.2.1.js';

const MAX = 40;

function storeKey(page) { return `gm-prompts:${page}`; }

function readLocal(page) {
  try {
    const list = JSON.parse(localStorage.getItem(storeKey(page)) || '[]');
    return Array.isArray(list) ? list.filter((x) => typeof x === 'string') : [];
  } catch (_) {
    return [];
  }
}

function remember(page, text) {
  const value = (text || '').trim();
  if (!page || value.length < 2) return;
  const list = readLocal(page).filter((x) => x.toLowerCase() !== value.toLowerCase());
  list.unshift(value);
  try { localStorage.setItem(storeKey(page), JSON.stringify(list.slice(0, MAX))); } catch (_) { /* ignore */ }
}

class GmPromptKeys extends LitElement {
  static properties = {
    page: { type: String },
    value: { type: String },
    sendEvent: { type: String },
  };

  constructor() {
    super();
    this.page = '';
    this.value = '';
    this.sendEvent = '';
    this._synced = '';
    this._index = -1; // -1 = the draft you are typing
    this._draft = '';
    this._list = null;
    this._server = null;
    this._ta = null;
    this._onKey = (e) => this._key(e);
    this._onBlur = (e) => {
      if (!this._ta) return;
      if (this._ta.value === this._synced) {
        e.stopImmediatePropagation();
        return;
      }
      this._synced = this._ta.value;
    };
    this._onPointerDown = (e) => {
      if (e.button === 0 && this.sendEvent && e.target.closest?.('.gm-composer-send, [data-prompt-send]') && !e.target.closest?.('.gm-composer-wait')) {
        // Keep focus on the textarea so click doesn't fire a separate blur POST first.
        e.preventDefault();
      }
    };
    this._onClick = (e) => {
      const sendBtn = e.target.closest && e.target.closest('.gm-composer-send, [data-prompt-send]');
      if (!sendBtn || e.target.closest?.('.gm-composer-wait')) return;
      this._sent();
      if (this.sendEvent && this._ta) {
        e.preventDefault();
        e.stopImmediatePropagation();
        this._synced = this._ta.value;
        this.dispatchEvent(new MesopEvent(this.sendEvent, { value: this._ta.value }));
      }
    };
  }

  createRenderRoot() { return this; }

  connectedCallback() {
    super.connectedCallback();
    this.style.display = 'none';
    this._synced = this.value || '';
    // The textarea renders in the same pass; attach on the next frame.
    requestAnimationFrame(() => this._attach());
  }

  updated(changed) {
    if (changed.has('value')) this._synced = this.value || '';
    requestAnimationFrame(() => this._attach());
  }

  disconnectedCallback() {
    super.disconnectedCallback();
    this._detach();
  }

  _card() {
    return this.closest('.gm-composer, [data-prompt-card]');
  }

  _attach() {
    const card = this._card();
    const ta = card && card.querySelector('textarea');
    if (!ta || ta === this._ta) return;
    this._detach();
    this._ta = ta;
    this._card_ = card;
    this._synced = ta.value ?? this.value ?? '';
    ta.addEventListener('keydown', this._onKey, true);
    ta.addEventListener('blur', this._onBlur, true);
    ta.addEventListener('focus', () => this._loadServer(), { once: true });
    card.addEventListener('pointerdown', this._onPointerDown, true);
    card.addEventListener('mousedown', this._onPointerDown, true);
    card.addEventListener('click', this._onClick, true);
  }

  _detach() {
    if (this._ta) {
      this._ta.removeEventListener('keydown', this._onKey, true);
      this._ta.removeEventListener('blur', this._onBlur, true);
    }
    if (this._card_) {
      this._card_.removeEventListener('pointerdown', this._onPointerDown, true);
      this._card_.removeEventListener('mousedown', this._onPointerDown, true);
      this._card_.removeEventListener('click', this._onClick, true);
    }
    this._ta = null;
    this._card_ = null;
  }

  async _loadServer() {
    if (this._server !== null || !this.page) return;
    this._server = [];
    try {
      const r = await fetch(`/api/prompts/${encodeURIComponent(this.page)}`, { credentials: 'same-origin' });
      if (r.ok) {
        const body = await r.json();
        if (Array.isArray(body.prompts)) this._server = body.prompts.filter((x) => typeof x === 'string');
      }
    } catch (_) { /* offline: local history only */ }
    this._list = null;
  }

  _history() {
    if (this._list) return this._list;
    const seen = new Set();
    const out = [];
    for (const p of [...readLocal(this.page), ...(this._server || [])]) {
      const k = p.trim().toLowerCase();
      if (!k || seen.has(k)) continue;
      seen.add(k);
      out.push(p.trim());
    }
    this._list = out;
    return out;
  }

  _sent() {
    // Re-attach if Mesop re-mounted the textarea (prompt_key bumps).
    this._attach();
    if (this._ta) remember(this.page, this._ta.value);
    this._index = -1;
    this._list = null;
  }

  _set(text) {
    const ta = this._ta;
    ta.value = text;
    ta.dispatchEvent(new Event('input', { bubbles: true }));
    const end = text.length;
    ta.setSelectionRange(end, end);
  }

  _key(e) {
    const ta = this._ta;
    if (!ta || e.altKey || e.ctrlKey || e.metaKey) return;
    if (e.key === 'Enter' && !e.shiftKey) { this._sent(); return; }
    if (e.key !== 'ArrowUp' && e.key !== 'ArrowDown') return;
    if (e.shiftKey || ta.selectionStart !== ta.selectionEnd) return;
    const before = ta.value.slice(0, ta.selectionStart);
    const after = ta.value.slice(ta.selectionEnd);
    if (e.key === 'ArrowUp') {
      if (before.includes('\n')) return; // not on the first line: move the caret
      const list = this._history();
      if (this._index + 1 >= list.length) return;
      e.preventDefault();
      if (this._index === -1) this._draft = ta.value;
      this._index += 1;
      this._set(list[this._index]);
    } else {
      if (after.includes('\n') || this._index < 0) return;
      e.preventDefault();
      this._index -= 1;
      this._set(this._index < 0 ? this._draft : this._history()[this._index]);
    }
    // Store the shown text in page state, then keep typing where we are.
    ta.dispatchEvent(new FocusEvent('blur'));
  }
}

if (!customElements.get('gm-prompt-keys')) customElements.define('gm-prompt-keys', GmPromptKeys);
