import { LitElement } from '/ui/vendor/lit-3.2.1.js';

function _setCookie(name, value) {
  try {
    document.cookie = `${name}=${encodeURIComponent(value)}; Path=/; Max-Age=31536000; SameSite=Lax`;
  } catch (_) { /* ignore */ }
}

function _applyDomTheme(mode) {
  if (mode !== 'light' && mode !== 'dark') return;
  document.body?.classList.toggle('dark-theme', mode === 'dark');
  if (document.documentElement) document.documentElement.style.colorScheme = mode;
}

function _syncSidenavDom(open) {
  const val = open ? 'open' : 'closed';
  if (document.documentElement) document.documentElement.dataset.sidenav = val;
  document.querySelectorAll('user-menu[rail]').forEach((el) => {
    el.expanded = open;
  });
}

if (!window.__gmShellBound) {
  window.__gmShellBound = true;
  let initialOpen = false;
  try {
    const saved = localStorage.getItem('gm-sidenav');
    initialOpen = saved === '1';
    if (saved === '1' || saved === '0') _setCookie('gm_sidenav', saved);
  } catch (_) { /* ignore */ }
  _syncSidenavDom(initialOpen);

  document.addEventListener('click', (e) => {
    const toggle = e.target?.closest?.('.gm-nav-toggle button');
    if (!toggle) return;
    e.preventDefault();
    e.stopImmediatePropagation();
    const next = document.documentElement?.dataset.sidenav !== 'open';
    try { localStorage.setItem('gm-sidenav', next ? '1' : '0'); } catch (_) { /* ignore */ }
    _setCookie('gm_sidenav', next ? '1' : '0');
    _syncSidenavDom(next);
  }, true);
}

class ThemeManager extends LitElement {
  static get properties() {
    return {
      theme: { type: String },
      themeLoaded: { type: String },
    };
  }

  constructor() {
    super();
    this.theme = '';
  }

  firstUpdated() {
    let storedTheme = '';
    try { storedTheme = localStorage.getItem('theme') || ''; } catch (_) { /* ignore */ }
    if (storedTheme === 'light' || storedTheme === 'dark') {
      _setCookie('gm_theme', storedTheme);
      _applyDomTheme(storedTheme);
      if (storedTheme !== this.theme && this.themeLoaded) {
        this.dispatchEvent(new MesopEvent(this.themeLoaded, { theme: storedTheme }));
      }
    }
    try {
      const open = localStorage.getItem('gm-sidenav') === '1';
      _syncSidenavDom(open);
    } catch (_) { /* ignore */ }
  }

  updated(changedProperties) {
    if (changedProperties.has('theme') && (this.theme === 'light' || this.theme === 'dark')) {
      try { localStorage.setItem('theme', this.theme); } catch (_) { /* ignore */ }
      _setCookie('gm_theme', this.theme);
      _applyDomTheme(this.theme);
    }
  }

  render() {
    // This component is non-visual
    return '';
  }
}

if (!customElements.get('theme-manager')) customElements.define('theme-manager', ThemeManager);