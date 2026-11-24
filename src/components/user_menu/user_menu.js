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
 * <user-menu>: light/dark, language and the account menu.
 *
 * Two layouts: the top bar (phones) and `rail`, a column at the bottom of
 * the side rail (wider screens), like Gemini. In the rail each control is an
 * icon with a label that shows when the rail is `expanded`; the account panel
 * opens beside the rail.
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
import { LitElement, css, html, nothing } from '/ui/vendor/lit-3.2.1.js';


// Light/dark icons drawn with even round strokes on the 24px grid, so the
// sun's eight rays are the same length and centred (the filled glyph was not).
const MOON = html`<svg class="stroke" viewBox="0 0 24 24" aria-hidden="true"><path d="M20 14.5A8 8 0 1 1 9.5 4a6.5 6.5 0 0 0 10.5 10.5z"/></svg>`;
const SUN = html`<svg class="stroke" viewBox="0 0 24 24" aria-hidden="true"><circle cx="12" cy="12" r="4"/><path d="M12 2.75v1.5M12 19.75v1.5M2.75 12h1.5M19.75 12h1.5M5.46 5.46l1.06 1.06M17.48 17.48l1.06 1.06M5.46 18.54l1.06-1.06M17.48 6.52l1.06-1.06"/></svg>`;
// The language switch shows the current language as a two-letter chip.
const langChip = (lang) => html`<span class="lang-chip" aria-hidden="true">${lang === 'ar' ? 'AR' : 'EN'}</span>`;

class UserMenu extends LitElement {
  static properties = {
    name: { type: String },
    email: { type: String },
    role: { type: String },
    dark: { type: Boolean },
    showSignOut: { type: Boolean },
    showUsers: { type: Boolean },
    showSettings: { type: Boolean },
    showAccount: { type: Boolean },
    lang: { type: String },
    labels: { type: String },
    themeEvent: { type: String },
    langEvent: { type: String },
    navEvent: { type: String },
    rail: { type: Boolean, reflect: true },
    expanded: { type: Boolean, reflect: true },
    _open: { state: true },
    _pos: { state: true },
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
    this.showAccount = false;
    this.lang = 'en';
    this.labels = '{}';
    this.themeEvent = '';
    this.langEvent = '';
    this.navEvent = '';
    this.rail = false;
    this.expanded = false;
    this._open = false;
    this._pos = null;
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
      border: 0;
      border-radius: 999px;
      background: transparent;
      color: inherit;
      font: inherit;
      font-size: 14px;
      font-weight: 500;
      cursor: pointer;
    }
    .lang-btn:hover, .theme-btn:hover { background: var(--gm-tonal-hover, rgba(21, 23, 28, 0.10)); }
    .lang-btn svg, .theme-btn svg { width: 18px; height: 18px; flex: none; fill: currentColor; opacity: 0.85; }
    /* Light/dark switch: a round button the same height as the language one. */
    .theme-btn {
      display: inline-flex;
      align-items: center;
      justify-content: center;
      width: 40px;
      height: 40px;
      padding: 0;
      border: 0;
      border-radius: 50%;
      background: transparent;
      color: inherit;
      cursor: pointer;
    }
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

    /* ---- Rail: icons in the side rail's column, labels when it is open. */
    :host([rail]) { display: flex; flex-direction: column; align-items: stretch; gap: 0; width: 100%; }
    .rail-item {
      display: flex; align-items: center; gap: 14px; width: 100%; height: 40px; padding: 0 10px; margin-bottom: 2px;
      border: 0; border-radius: 20px; background: transparent; color: var(--sys-on-surface, #15171c);
      font: inherit; font-size: 14px; text-align: start; cursor: pointer; white-space: nowrap; overflow: hidden; box-sizing: border-box;
    }
    .rail-item { transition: background-color 140ms ease, color 140ms ease; }
    .rail-item:hover { background: var(--gm-hover, rgba(127, 127, 127, 0.1)); }
    .rail-item:hover svg { stroke: var(--sys-on-surface, #15171c); }
    .rail-item[aria-expanded="true"] { background: var(--gm-active-nav, rgba(127, 127, 127, 0.16)); }
    .rail-item svg { width: 20px; height: 20px; flex: none; fill: var(--sys-on-surface-variant, #4b515d); }
    /* Stroke icons (sun, moon): no fill, even 1.8px lines. */
    svg.stroke { fill: none !important; stroke: var(--sys-on-surface-variant, #4b515d); stroke-width: 1.8; stroke-linecap: round; stroke-linejoin: round; }
    .item svg.stroke, .theme-btn svg.stroke { stroke: currentColor; }
    /* EN / AR: a small chip the same width as the icons beside it. */
    .lang-chip { width: 22px; height: 18px; flex: none; margin: 0 -1px; display: inline-grid; place-items: center; border-radius: 5px;
      font-size: 10px; font-weight: 700; letter-spacing: 0.04em; line-height: 1; font-family: var(--gm-font, 'Google Sans', system-ui, sans-serif);
      color: var(--sys-on-surface-variant, #4b515d); box-shadow: inset 0 0 0 1.6px currentColor; }
    .rail-item:hover .lang-chip { color: var(--sys-on-surface, #15171c); }
    .lang-btn .lang-chip { color: inherit; }
    /* The focus ring sits inside the row, so the rail's clipping never cuts it. */
    .rail-item:focus-visible { outline: 2px solid var(--sys-primary, #1a5fd8); outline-offset: -2px; }
    .rail-item .avatar { width: 26px; height: 26px; font-size: 11px; margin: 0 -3px; }
    .rail-item .lbl { min-width: 0; overflow: hidden; text-overflow: ellipsis; opacity: 1; transition: opacity 160ms ease 60ms; }
    :host([rail]:not([expanded])) .rail-item .lbl { opacity: 0; transition: opacity 80ms ease; }
    :host([rail]) .panel { position: fixed; top: auto; inset-inline-end: auto; }
    /* Short screens (a 768p laptop): theme and language move into the account
       panel so the rail fits without scrolling. */
    .short-only { display: none; }
    @media (max-height: 720px) {
      :host([rail]) .rail-item.opt { display: none; }
      :host([rail]) .rail-item { height: 36px; }
      :host([rail]) .panel .short-only { display: flex; }
    }
    @media (prefers-reduced-motion: reduce) { .rail-item .lbl { transition: none; } }
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

  updated(changed) {
    // Lets page CSS lift the top bar over the page only while the panel is
    // open (studio.src.css, .gm-page > :has(user-menu[data-open])).
    if (changed.has('_open')) this.toggleAttribute('data-open', this._open);
  }

  async _openPanel() {
    if (this.rail) {
      const r = this.renderRoot.querySelector('.trigger, .rail-item.account')?.getBoundingClientRect();
      if (r) {
        const rtl = document.documentElement.dir === 'rtl';
        this._pos = rtl
          ? `right:${Math.round(window.innerWidth - r.left + 10)}px;bottom:${Math.round(window.innerHeight - r.bottom)}px`
          : `left:${Math.round(r.right + 10)}px;bottom:${Math.round(window.innerHeight - r.bottom)}px`;
      }
    }
    this._open = true;
    await this.updateComplete;
    const first = this.renderRoot.querySelector('.panel .item');
    if (first) first.focus();
  }

  _close(returnFocus) {
    this._open = false;
    if (returnFocus) {
      this.updateComplete.then(() => this.renderRoot.querySelector('.trigger, .rail-item.account')?.focus());
    }
  }

  _theme() {
    if (!this.themeEvent) return;
    const nextDark = !this.dark;
    const mode = nextDark ? 'dark' : 'light';
    // Apply optimistically so switching light/dark feels instant (<16ms).
    this.dark = nextDark;
    try { localStorage.setItem('theme', mode); } catch (_) { /* ignore */ }
    try { document.cookie = `gm_theme=${mode}; Path=/; Max-Age=31536000; SameSite=Lax`; } catch (_) { /* ignore */ }
    document.body?.classList.toggle('dark-theme', nextDark);
    if (document.documentElement) document.documentElement.style.colorScheme = mode;
    this.dispatchEvent(new MesopEvent(this.themeEvent, { dark: nextDark }));
  }

  _nav(e, route) {
    if (!this.navEvent || e.defaultPrevented || e.button !== 0 || e.metaKey || e.ctrlKey || e.shiftKey || e.altKey) {
      return;
    }
    e.preventDefault();
    this._close(false);
    this.dispatchEvent(new MesopEvent(this.navEvent, { route }));
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
    const themeLabel = this.dark
      ? (L.theme_to_light || 'Switch to light mode')
      : (L.theme_to_dark || 'Switch to dark mode');
    if (this.rail) {
      const themeName = this.dark ? (L.light_mode || 'Light mode') : (L.dark_mode || 'Dark mode');
      return html`
        ${this.themeEvent ? html`
          <button class="rail-item opt" type="button" @click=${this._theme} aria-label=${themeLabel} title=${this.expanded ? '' : themeLabel}>
            ${this.dark ? SUN : MOON}<span class="lbl">${themeName}</span>
          </button>` : nothing}
        <button class="rail-item opt" type="button" @click=${this._lang} aria-label=${switchLabel} title=${this.expanded ? '' : switchLabel}>
          ${langChip(this.lang)}<span class="lbl" lang=${other}>${otherName}</span>
        </button>
        <button class="rail-item account" type="button" aria-haspopup="true"
          aria-expanded=${this._open ? 'true' : 'false'} aria-label=${accountLabel}
          title=${this.expanded ? '' : accountLabel} @click=${this._toggle}>
          <span class="avatar" aria-hidden="true">${initials}</span><span class="lbl">${label}</span>
        </button>
        ${this._open ? this._panel(initials, isAdmin, L) : nothing}`;
    }
    return html`
      ${this.themeEvent ? html`
        <button class="theme-btn" type="button" @click=${this._theme}
          aria-label=${themeLabel} title=${themeLabel}>
          ${this.dark ? SUN : MOON}
        </button>` : nothing}
      ${html`
        <button class="lang-btn" type="button" @click=${this._lang}
          aria-label=${switchLabel} title=${switchLabel}>
          ${langChip(this.lang)}<span lang=${other}>${otherName}</span>
        </button>`}
      <button class="trigger" type="button" aria-haspopup="true"
        aria-expanded=${this._open ? 'true' : 'false'}
        aria-label=${accountLabel} @click=${this._toggle}>
        <span class="avatar" aria-hidden="true">${initials}</span>
      </button>
      ${this._open ? this._panel(initials, isAdmin, L) : nothing}
    `;
  }

  _panel(initials, isAdmin, L) {
    return html`
        <div class="panel" role="group" aria-label=${L.account || 'Account'} style=${this.rail && this._pos ? this._pos : ''}>
          <div class="who">
            <span class="avatar" aria-hidden="true">${initials}</span>
            <div class="who-text">
              ${this.name ? html`<span class="name">${this.name}</span>` : nothing}
              <span class="email">${this.email}</span>
              ${this.role ? html`<span class="badge ${isAdmin ? 'admin' : ''}">${isAdmin ? (L.admin || 'Admin') : (L.user || 'User')}</span>` : nothing}
            </div>
          </div>
          <hr>
          ${this.rail ? html`
            <button class="item short-only" type="button" @click=${this._theme}>
              ${this.dark ? SUN : MOON}
              <span class="grow">${this.dark ? (L.light_mode || 'Light mode') : (L.dark_mode || 'Dark mode')}</span>
            </button>
            <button class="item short-only" type="button" @click=${this._lang}>
              ${langChip(this.lang)}<span class="grow" lang=${this.lang === 'ar' ? 'en' : 'ar'}>${L[`name.${this.lang === 'ar' ? 'en' : 'ar'}`] || (this.lang === 'ar' ? 'English' : 'العربية')}</span>
            </button>` : nothing}
          <a class="item" href="/brand" @click=${(e) => this._nav(e, '/brand')}>
            <svg viewBox="0 0 24 24" aria-hidden="true"><path d="M12 3a9 9 0 0 0 0 18 1.5 1.5 0 0 0 1.1-2.5 1.5 1.5 0 0 1 1.1-2.5H16a5 5 0 0 0 5-5c0-4.4-4-8-9-8zm-5.5 9A1.5 1.5 0 1 1 8 10.5 1.5 1.5 0 0 1 6.5 12zm3-4A1.5 1.5 0 1 1 11 6.5 1.5 1.5 0 0 1 9.5 8zm5 0A1.5 1.5 0 1 1 16 6.5 1.5 1.5 0 0 1 14.5 8zm3 4a1.5 1.5 0 1 1 1.5-1.5 1.5 1.5 0 0 1-1.5 1.5z"/></svg>
            <span class="grow">${L.brand || 'My brand'}</span>
          </a>
          ${this.showAccount ? html`
            <a class="item" href="/account" @click=${(e) => this._nav(e, '/account')}>
              <svg viewBox="0 0 24 24" aria-hidden="true"><path d="M18 8h-1V6a5 5 0 0 0-10 0v2H6a2 2 0 0 0-2 2v10a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V10a2 2 0 0 0-2-2zM9 6a3 3 0 0 1 6 0v2H9zm3 11a2 2 0 1 1 2-2 2 2 0 0 1-2 2z"/></svg>
              <span class="grow">${L.account_settings || 'Account settings'}</span>
            </a>` : nothing}
          ${this.showSettings ? html`
            <a class="item" href="/settings" @click=${(e) => this._nav(e, '/settings')}>
              <svg viewBox="0 0 24 24" aria-hidden="true"><path d="M19.4 13a7.5 7.5 0 0 0 0-2l2.1-1.6-2-3.5-2.5 1a7.6 7.6 0 0 0-1.7-1L15 3h-4l-.4 2.9a7.6 7.6 0 0 0-1.7 1l-2.5-1-2 3.5L6.6 11a7.5 7.5 0 0 0 0 2l-2.1 1.6 2 3.5 2.5-1a7.6 7.6 0 0 0 1.7 1L11 21h4l.4-2.9a7.6 7.6 0 0 0 1.7-1l2.5 1 2-3.5zM13 15.5a3.5 3.5 0 1 1 3.5-3.5 3.5 3.5 0 0 1-3.5 3.5z"/></svg>
              <span class="grow">${L.settings || 'Settings'}</span>
            </a>` : nothing}
          ${this.showSignOut ? html`
            <hr>
            <form method="post" action="/logout">
              <button class="item" type="submit">
                <svg viewBox="0 0 24 24" aria-hidden="true"><path d="M10 17l1.4-1.4-2.6-2.6H20v-2H8.8l2.6-2.6L10 7l-5 5zM4 5h8V3H4a2 2 0 0 0-2 2v14a2 2 0 0 0 2 2h8v-2H4z"/></svg>
                <span class="grow">${L.sign_out || 'Sign out'}</span>
              </button>
            </form>` : nothing}
        </div>`;
  }
}

if (!customElements.get('user-menu')) customElements.define('user-menu', UserMenu);
