/**
 * <gm-notify>: shows a system notification when a generation finishes.
 *
 * The server bumps `seq` with a title and body (common/notify.py). A notice
 * shows only when the person switched notifications on in the avatar menu
 * (localStorage "gm-notify" = "on"), the browser allowed them, and the tab is
 * in the background: in a visible tab the page already shows the result.
 * The last seq shown is kept per tab so a re-render or a page change never
 * shows the same notice twice.
 */
import { LitElement } from '/ui/vendor/lit-3.2.1.js';

const SEEN = 'gm-notify-seen';

class GmNotify extends LitElement {
  static properties = {
    seq: { type: Number },
    title: { type: String },
    body: { type: String },
  };

  constructor() {
    super();
    this.seq = 0;
    this.title = '';
    this.body = '';
  }

  updated(changed) {
    if (!changed.has('seq') || !this.seq) return;
    let seen = 0;
    try { seen = Number(sessionStorage.getItem(SEEN) || 0); } catch (_) { /* private mode */ }
    if (this.seq <= seen) return;
    try { sessionStorage.setItem(SEEN, String(this.seq)); } catch (_) { /* ignore */ }
    let on = false;
    try { on = localStorage.getItem('gm-notify') === 'on'; } catch (_) { /* ignore */ }
    if (!on || !('Notification' in window) || Notification.permission !== 'granted') return;
    if (!document.hidden) return;
    try {
      const n = new Notification(this.title || 'GenMedia Studio', {
        body: this.body || '',
        tag: 'gm-done',
      });
      n.onclick = () => { window.focus(); n.close(); };
    } catch (_) {
      /* some browsers only allow notifications from a service worker */
    }
  }

  createRenderRoot() {
    return this;  // nothing to draw
  }
}

customElements.define('gm-notify', GmNotify);
