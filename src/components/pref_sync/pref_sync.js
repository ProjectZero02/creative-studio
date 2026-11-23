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
 * <gm-pref>: keeps one setting in this browser (localStorage "gm-pref:<name>").
 * On load it reports a saved value that differs from the page's; after that,
 * every change the page makes is saved. Non-visual.
 */
import { LitElement } from '/ui/vendor/lit-3.2.1.js';

class GmPref extends LitElement {
  static properties = {
    name: { type: String },
    value: { type: String },
    loadEvent: { type: String },
  };

  constructor() {
    super();
    this.name = '';
    this.value = '';
    this.loadEvent = '';
    this._ready = false;
  }

  createRenderRoot() { return this; }

  _key() { return `gm-pref:${this.name}`; }

  connectedCallback() {
    super.connectedCallback();
    this.style.display = 'none';
  }

  _cookie(val) {
    try {
      document.cookie = `gm_pref_${this.name}=${encodeURIComponent(val)}; Path=/; Max-Age=31536000; SameSite=Lax`;
    } catch (_) { /* ignore */ }
  }

  firstUpdated() {
    let saved = null;
    try { saved = localStorage.getItem(this._key()); } catch (_) { /* ignore */ }
    if (saved !== null) {
      this._cookie(saved);
      if (saved !== this.value && this.loadEvent) {
        this.dispatchEvent(new MesopEvent(this.loadEvent, { name: this.name, value: saved }));
      }
    }
    this._ready = true;
  }

  updated(changed) {
    if (!this._ready || !changed.has('value')) return;
    try { localStorage.setItem(this._key(), this.value); } catch (_) { /* ignore */ }
    this._cookie(this.value);
  }

  render() { return ''; }
}

if (!customElements.get('gm-pref')) customElements.define('gm-pref', GmPref);
