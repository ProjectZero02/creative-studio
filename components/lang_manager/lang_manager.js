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
 * <lang-manager>: non-visual. Mirrors <theme-manager> for the language.
 *
 * - Always sets <html lang> and <html dir> ("rtl" for Arabic) from `current`.
 * - When the user picked a language (`chosen`), saves it in localStorage and in
 *   the `gm_lang` cookie (read by the server for the first render and /login).
 * - On load, sends the saved language to the server, or (until the user picks)
 *   the browser language, if it differs from what the server rendered.
 */
import { LitElement } from 'https://cdn.jsdelivr.net/npm/lit@3.2.1/+esm';

const LANGS = ['en', 'ar'];
const RTL = new Set(['ar']);
const KEY = 'lang';
const COOKIE = 'gm_lang';

function readStored() {
  try {
    const v = localStorage.getItem(KEY);
    return LANGS.includes(v) ? v : '';
  } catch (_) {
    return '';
  }
}

function browserLang() {
  const nav = (navigator.languages && navigator.languages[0]) || navigator.language || '';
  return nav.toLowerCase().startsWith('ar') ? 'ar' : 'en';
}

// Material icons whose glyph points along the reading direction. In RTL they
// get .gm-flip (assets/ui/rtl.css mirrors them). Media "play" stays as is.
const DIRECTIONAL_ICONS = new Set([
  'arrow_forward', 'arrow_back', 'arrow_forward_ios', 'arrow_back_ios', 'arrow_back_ios_new',
  'arrow_right_alt', 'arrow_left', 'arrow_right', 'chevron_right', 'chevron_left',
  'navigate_next', 'navigate_before', 'keyboard_arrow_right', 'keyboard_arrow_left',
  'east', 'west', 'trending_flat', 'first_page', 'last_page', 'menu_open', 'read_more',
  'send', 'redo', 'undo', 'reply', 'forward', 'login', 'logout', 'exit_to_app',
  'keyboard_double_arrow_right', 'keyboard_double_arrow_left', 'start', 'subdirectory_arrow_right',
]);
const ICON_SELECTOR = 'mat-icon, .material-icons, .material-symbols-outlined, .material-symbols-rounded';
let flipObserver = null;
let flipQueued = false;

function markIcons(root) {
  root.querySelectorAll(ICON_SELECTOR).forEach((el) => {
    const name = (el.getAttribute('fonticon') || el.textContent || '').trim();
    el.classList.toggle('gm-flip', DIRECTIONAL_ICONS.has(name));
  });
}

function clearIcons() {
  document.querySelectorAll('.gm-flip').forEach((el) => el.classList.remove('gm-flip'));
}

function watchIcons(rtl) {
  if (!rtl) {
    if (flipObserver) flipObserver.disconnect();
    flipObserver = null;
    clearIcons();
    return;
  }
  markIcons(document);
  if (flipObserver) return;
  flipObserver = new MutationObserver(() => {
    if (flipQueued) return;
    flipQueued = true;
    requestAnimationFrame(() => {
      flipQueued = false;
      markIcons(document);
    });
  });
  flipObserver.observe(document.body, { childList: true, subtree: true, characterData: true });
}

export function applyDocumentLang(lang) {
  const root = document.documentElement;
  const dir = RTL.has(lang) ? 'rtl' : 'ltr';
  if (root.getAttribute('lang') !== lang) root.setAttribute('lang', lang);
  if (root.getAttribute('dir') !== dir) root.setAttribute('dir', dir);
  if (document.body && document.body.getAttribute('dir') !== dir) document.body.setAttribute('dir', dir);
  if (document.body) watchIcons(dir === 'rtl');
}

class LangManager extends LitElement {
  static properties = {
    current: { type: String },
    chosen: { type: Boolean },
    langLoaded: { type: String },
  };

  constructor() {
    super();
    this.current = 'en';
    this.chosen = false;
    this.langLoaded = '';
  }

  connectedCallback() {
    super.connectedCallback();
    applyDocumentLang(this.current);
    const stored = readStored();
    let want = '';
    let chosen = false;
    if (stored) {
      want = stored;
      chosen = true;
    } else if (!this.chosen) {
      want = browserLang();
    }
    if (want && (want !== this.current || chosen !== this.chosen) && this.langLoaded) {
      this.dispatchEvent(new MesopEvent(this.langLoaded, { lang: want, chosen }));
    }
  }

  updated(changed) {
    if (changed.has('current')) applyDocumentLang(this.current);
    if ((changed.has('current') || changed.has('chosen')) && this.chosen && LANGS.includes(this.current)) {
      try {
        localStorage.setItem(KEY, this.current);
      } catch (_) { /* private mode: the cookie still works */ }
      document.cookie = `${COOKIE}=${this.current}; path=/; max-age=31536000; samesite=lax`;
    }
  }

  render() {
    return '';
  }
}

customElements.define('lang-manager', LangManager);
