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
 * <session-renew token="...">: once given a token, POSTs it to /account/renew
 * as a normal form submit (a full page load), so the server can set a fresh
 * session cookie after the user changed their own password. The token travels
 * in the request body, never in the URL. Renders nothing.
 */
import { LitElement } from 'https://cdn.jsdelivr.net/npm/lit@3.2.1/+esm';

class SessionRenew extends LitElement {
  static properties = {
    token: { type: String },
  };

  constructor() {
    super();
    this.token = '';
    this._sent = '';
  }

  createRenderRoot() {
    return this;
  }

  updated() {
    if (!this.token || this.token === this._sent) return;
    this._sent = this.token;
    const form = document.createElement('form');
    form.method = 'post';
    form.action = '/account/renew';
    form.style.display = 'none';
    const input = document.createElement('input');
    input.type = 'hidden';
    input.name = 'token';
    input.value = this.token;
    form.appendChild(input);
    document.body.appendChild(form);
    form.submit();
  }
}

customElements.define('session-renew', SessionRenew);
