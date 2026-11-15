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
 * <user-menu>: avatar button at the top right of every page.
 *
 * Opens a small panel with the user's name, email and role, a light/dark
 * switch, a "Users" link for admins and "Sign out" (a real POST form to
 * /logout, so it works without Mesop). Escape or a click outside closes it and
 * focus goes back to the avatar.
 *
 * A globe button sits next to the avatar and switches English / Arabic in one
 * click. It is labelled in the other language ("العربية" while in English,
 * "English" while in Arabic) so a speaker of that language can find it. The
 * panel has the same switch. Text comes from Python (`labels`, JSON).
 */
import { LitElement, css, html, nothing } from 'https://cdn.jsdelivr.net/npm/lit@3.2.1/+esm';

const GLOBE = html`<svg viewBox="0 0 24 24" aria-hidden="true"><path d="M12 2a10 10 0 1 0 10 10A10 10 0 0 0 12 2zm6.9 6h-2.9a15.7 15.7 0 0 0-1.4-3.6A8 8 0 0 1 18.9 8zM12 4a14 14 0 0 1 1.9 4h-3.8A14 14 0 0 1 12 4zM4.3 14a8.2 8.2 0 0 1 0-4h3.4a16.5 16.5 0 0 0 0 4zm.8 2h2.9a15.7 15.7 0 0 0 1.4 3.6A8 8 0 0 1 5.1 16zM8 8H5.1a8 8 0 0 1 4.3-3.6A15.7 15.7 0 0 0 8 8zm4 12a14 14 0 0 1-1.9-4h3.8A14 14 0 0 1 12 20zm2.3-6H9.7a14.7 14.7 0 0 1 0-4h4.6a14.7 14.7 0 0 1 0 4zm.3 5.6a15.7 15.7 0 0 0 1.4-3.6h2.9a8 8 0 0 1-4.3 3.6zm1.7-5.6a16.5 16.5 0 0 0 0-4h3.4a8.2 8.2 0 0 1 0 4z"/></svg>`;

class UserMenu extends LitElement {
  static properties = {
    name: { type: String },
    email: { type: String },
    role: { type: String },
    dark: { type: Boolean },
    showSignOut: { type: Boolean },
    showUsers: { type: Boolean },
    showSettings: { type: Boolean },
    lang: { type: String },
    labels: { type: String },
    themeEvent: { type: String },
    langEvent: { type: String },
    _open: { state: true },
  };

  constructor() {
    super();
    this.name = '';
    this.email = '';
    this.role = '';
    this.dark = false;
    this.showSignOut = false;
    this.showUsers = false;
    this.showSettings = false;
    this.lang = 'en';
    this.labels = '{}';
    this.themeEvent = '';
    this.langEvent = '';
    this._open = false;
    this._onDocClick = (e) => {
      if (this._open && !e.composedPath().includes(this)) this._close(false);
    };
    this._onKey = (e) => {
      if (this._open && e.key === 'Escape') {
        e.preventDefault();
        this._close(true);
      }
    };
  }

  connectedCallback() {
    super.connectedCallback();
    document.addEventListener('click', this._onDocClick, true);
    document.addEventListener('keydown', this._onKey);
  }

  disconnectedCallback() {
    document.removeEventListener('click', this._onDocClick, true);
    document.removeEventListener('keydown', this._onKey);
    super.disconnectedCallback();
  }

  static styles = css`
    :host {
      position: relative;
      display: inline-flex;
      align-items: center;
      gap: 6px;
      font-family: var(--gm-font, 'Google Sans', system-ui, sans-serif);
      color: var(--sys-on-surface, #15171c);
    }
    .avatar {
      display: inline-flex;
      align-items: center;
      justify-content: center;
      flex: none;
      border-radius: 50%;
      background: var(--sys-primary-container, #dce7fd);
      color: var(--sys-on-primary-container, #0a2a66);
      font-weight: 600;
      letter-spacing: 0.02em;
      user-select: none;
    }
    .trigger {
      display: inline-flex;
      align-items: center;
      justify-content: center;
      width: 44px;
      height: 44px;
      padding: 0;
      border: 0;
      border-radius: 50%;
      background: transparent;
      cursor: pointer;
    }
    .trigger .avatar { width: 36px; height: 36px; font-size: 14px; }
    .lang-btn {
      display: inline-flex;
      align-items: center;
      gap: 6px;
      height: 40px;
      min-width: 44px;
      padding: 0 14px;
      border: 1px solid var(--sys-outline-variant, #d6dae1);
      border-radius: 999px;
      background: transparent;
      color: inherit;
      font: inherit;
      font-size: 14px;
      font-weight: 500;
      cursor: pointer;
    }
    .lang-btn:hover { background: var(--sys-surface-container-high, #e6e9ee); }
    .lang-btn svg { width: 18px; height: 18px; flex: none; fill: currentColor; opacity: 0.85; }
    @media (max-width: 420px) {
      .lang-btn { padding: 0 10px; }
    }
    .trigger:hover .avatar { box-shadow: 0 0 0 3px var(--sys-surface-container-high, #e6e9ee); }
    button:focus-visible, a:focus-visible {
      outline: 2px solid var(--sys-primary, #1a5fd8);
      outline-offset: 2px;
    }
    .panel {
      position: absolute;
      top: calc(100% + 6px);
      inset-inline-end: 0;
      z-index: 1000;
      width: 300px;
      max-width: calc(100vw - 24px);
      padding: 8px;
      border: 1px solid var(--sys-outline-variant, #d6dae1);
      border-radius: 16px;
      background: var(--sys-surface-container-low, #fff);
      box-shadow: 0 12px 32px rgb(0 0 0 / 0.18);
    }
    .who {
      display: flex;
      gap: 12px;
      align-items: center;
      padding: 10px 10px 14px;
    }
    .who .avatar { width: 44px; height: 44px; font-size: 16px; }
    .who-text { min-width: 0; display: flex; flex-direction: column; gap: 2px; }
    .name { font-size: 15px; font-weight: 600; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
    .email {
      font-size: 13px;
      color: var(--sys-on-surface-variant, #4b515d);
      overflow: hidden;
      text-overflow: ellipsis;
      white-space: nowrap;
    }
    .badge {
      align-self: flex-start;
      margin-top: 4px;
      padding: 2px 8px;
      border-radius: 999px;
      font-size: 12px;
      font-weight: 600;
      background: var(--sys-secondary-container, #e8ecf2);
      color: var(--sys-on-secondary-container, #1b2230);
    }
    .badge.admin {
      background: var(--sys-primary-container, #dce7fd);
      color: var(--sys-on-primary-container, #0a2a66);
    }
    hr { border: 0; border-top: 1px solid var(--sys-outline-variant, #d6dae1); margin: 4px 0; }
    .item {
      display: flex;
      align-items: center;
      gap: 12px;
      width: 100%;
      min-height: 44px;
      padding: 0 10px;
      border: 0;
      border-radius: 10px;
      background: transparent;
      color: inherit;
      font: inherit;
      font-size: 14px;
      text-align: start;
      text-decoration: none;
      cursor: pointer;
      box-sizing: border-box;
    }
    .item:hover { background: var(--sys-surface-container-high, #e6e9ee); }
    .item svg { width: 20px; height: 20px; flex: none; fill: currentColor; opacity: 0.85; }
    .item .grow { flex: 1; }
    .item .value { font-size: 13px; color: var(--sys-on-surface-variant, #4b515d); white-space: nowrap; }
    .switch {
      position: relative;
      width: 36px;
      height: 20px;
      border-radius: 999px;
      background: var(--sys-outline, #7d8492);
      transition: background 160ms;
      flex: none;
    }
    .switch::after {
      content: '';
      position: absolute;
      top: 2px;
      inset-inline-start: 2px;
      width: 16px;
      height: 16px;
      border-radius: 50%;
      background: var(--sys-surface, #fff);
      transition: inset-inline-start 160ms;
    }
    .switch.on { background: var(--sys-primary, #1a5fd8); }
    .switch.on::after { inset-inline-start: 18px; }
    form { margin: 0; }
    @media (prefers-reduced-motion: reduce) {
      .switch, .switch::after { transition: none; }
    }
  `;

  get _l() {
    try {
      return JSON.parse(this.labels || '{}') || {};
    } catch (_) {
      return {};
    }
  }

  _initials() {
    const source = (this.name || this.email || '?').trim();
    const words = source.split(/[\s@._-]+/).filter(Boolean);
    const letters = words.length > 1 ? words[0][0] + words[1][0] : source.slice(0, 1);
    return letters.toUpperCase();
  }

  _toggle() {
    this._open ? this._close(true) : this._openPanel();
  }

  async _openPanel() {
    this._open = true;
    await this.updateComplete;
    const first = this.renderRoot.querySelector('.panel .item');
    if (first) first.focus();
  }

  _close(returnFocus) {
    this._open = false;
    if (returnFocus) {
      this.updateComplete.then(() => this.renderRoot.querySelector('.trigger')?.focus());
    }
  }

  _theme() {
    if (!this.themeEvent) return;
    this.dispatchEvent(new MesopEvent(this.themeEvent, { dark: !this.dark }));
  }

  _lang() {
    if (!this.langEvent) return;
    this.dispatchEvent(new MesopEvent(this.langEvent, { lang: this.lang === 'ar' ? 'en' : 'ar' }));
  }

  render() {
    const initials = this._initials();
    const label = this.name || this.email;
    const isAdmin = this.role === 'admin';
    const L = this._l;
    const other = this.lang === 'ar' ? 'en' : 'ar';
    const otherName = L[`name.${other}`] || (other === 'ar' ? 'العربية' : 'English');
    const thisName = L[`name.${this.lang}`] || (this.lang === 'ar' ? 'العربية' : 'English');
    const switchLabel = L.switch || 'Switch to Arabic (العربية)';
    const accountLabel = (L.account_of || 'Account: {name}').replace('{name}', label);
    return html`
      ${html`
        <button class="lang-btn" type="button" @click=${this._lang}
          aria-label=${switchLabel} title=${switchLabel}>
          ${GLOBE}<span lang=${other}>${otherName}</span>
        </button>`}
      <button class="trigger" type="button" aria-haspopup="true"
        aria-expanded=${this._open ? 'true' : 'false'}
        aria-label=${accountLabel} @click=${this._toggle}>
        <span class="avatar" aria-hidden="true">${initials}</span>
      </button>
      ${this._open ? html`
        <div class="panel" role="group" aria-label=${L.account || 'Account'}>
          <div class="who">
            <span class="avatar" aria-hidden="true">${initials}</span>
            <div class="who-text">
              ${this.name ? html`<span class="name">${this.name}</span>` : nothing}
              <span class="email">${this.email}</span>
              ${this.role ? html`<span class="badge ${isAdmin ? 'admin' : ''}">${isAdmin ? (L.admin || 'Admin') : (L.user || 'User')}</span>` : nothing}
            </div>
          </div>
          <hr>
          <button class="item" type="button" role="switch"
            aria-checked=${this.dark ? 'true' : 'false'} @click=${this._theme}>
            <svg viewBox="0 0 24 24" aria-hidden="true"><path d="M12 3a9 9 0 1 0 9 9 7 7 0 0 1-9-9z"/></svg>
            <span class="grow">${L.dark_mode || 'Dark mode'}</span>
            <span class="switch ${this.dark ? 'on' : ''}" aria-hidden="true"></span>
          </button>
          ${this.langEvent ? html`
            <button class="item" type="button" @click=${this._lang}
              aria-label=${`${L.label || 'Language'}: ${thisName}. ${switchLabel}`}>
              ${GLOBE}
              <span class="grow">${L.label || 'Language'}</span>
              <span class="value"><span lang="en">English</span> / <span lang="ar">العربية</span></span>
            </button>` : nothing}
          ${this.showUsers ? html`
            <a class="item" href="/admin/users">
              <svg viewBox="0 0 24 24" aria-hidden="true"><path d="M16 11a3 3 0 1 0-3-3 3 3 0 0 0 3 3zm-8 0a3 3 0 1 0-3-3 3 3 0 0 0 3 3zm0 2c-2.3 0-7 1.2-7 3.5V19h14v-2.5C15 14.2 10.3 13 8 13zm8 0c-.3 0-.6 0-1 .1 1.2.8 2 1.9 2 3.4V19h6v-2.5c0-2.3-4.7-3.5-7-3.5z"/></svg>
              <span class="grow">${L.users || 'Users'}</span>
            </a>` : nothing}
          ${this.showSettings ? html`
            <a class="item" href="/config">
              <svg viewBox="0 0 24 24" aria-hidden="true"><path d="M19.4 13a7.5 7.5 0 0 0 0-2l2.1-1.6-2-3.5-2.5 1a7.6 7.6 0 0 0-1.7-1L15 3h-4l-.4 2.9a7.6 7.6 0 0 0-1.7 1l-2.5-1-2 3.5L6.6 11a7.5 7.5 0 0 0 0 2l-2.1 1.6 2 3.5 2.5-1a7.6 7.6 0 0 0 1.7 1L11 21h4l.4-2.9a7.6 7.6 0 0 0 1.7-1l2.5 1 2-3.5zM13 15.5a3.5 3.5 0 1 1 3.5-3.5 3.5 3.5 0 0 1-3.5 3.5z"/></svg>
              <span class="grow">${L.settings || 'Settings'}</span>
            </a>` : nothing}
          <a class="item" href="/about">
            <svg viewBox="0 0 24 24" aria-hidden="true"><path d="M11 17h2v-6h-2zm1-15a10 10 0 1 0 10 10A10 10 0 0 0 12 2zm0 18a8 8 0 1 1 8-8 8 8 0 0 1-8 8zm-1-11h2V7h-2z"/></svg>
            <span class="grow">${L.about || 'About'}</span>
          </a>
          ${this.showSignOut ? html`
            <hr>
            <form method="post" action="/logout">
              <button class="item" type="submit">
                <svg viewBox="0 0 24 24" aria-hidden="true"><path d="M10 17l1.4-1.4-2.6-2.6H20v-2H8.8l2.6-2.6L10 7l-5 5zM4 5h8V3H4a2 2 0 0 0-2 2v14a2 2 0 0 0 2 2h8v-2H4z"/></svg>
                <span class="grow">${L.sign_out || 'Sign out'}</span>
              </button>
            </form>` : nothing}
        </div>` : nothing}
    `;
  }
}

customElements.define('user-menu', UserMenu);
