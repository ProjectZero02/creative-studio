/**
 * <gm-notify-toggle>: the "Notify me when done" switch in Settings > General.
 *
 * The setting is browser-only (localStorage "gm-notify", read by <gm-notify>
 * in notify.js) and turning it on needs the browser's permission prompt, which
 * must run straight from the click. So this switch lives in the browser
 * instead of being a Mesop slide toggle that round-trips to the server.
 * It is drawn to match the Material switch next to it.
 */
import { LitElement, html, css } from '/ui/vendor/lit-3.2.1.js';

const KEY = 'gm-notify';

function isOn() {
  try {
    return localStorage.getItem(KEY) === 'on'
      && 'Notification' in window && Notification.permission === 'granted';
  } catch (_) {
    return false;
  }
}

class GmNotifyToggle extends LitElement {
  static properties = {
    label: { type: String },
    _on: { state: true },
  };

  static styles = css`
    /* The end margin lines it up with the Material switch above it. */
    :host { display: inline-flex; flex: none; margin-inline-end: 4px; }
    button {
      position: relative; width: 52px; height: 32px; padding: 0; margin: 0;
      border-radius: 16px; cursor: pointer; box-sizing: border-box;
      border: 2px solid var(--sys-outline, #8e918f);
      background: var(--sys-surface-container-highest, #36393b);
      transition: background-color .15s, border-color .15s;
    }
    button::after {
      content: ''; position: absolute; top: 50%; inset-inline-start: 6px;
      width: 16px; height: 16px; border-radius: 50%;
      background: var(--sys-outline, #8e918f);
      transform: translateY(-50%);
      transition: inset-inline-start .15s, width .15s, height .15s, background-color .15s;
    }
    button[aria-checked='true'] {
      background: var(--sys-primary, #a8c7fa); border-color: var(--sys-primary, #a8c7fa);
    }
    button[aria-checked='true']::after {
      inset-inline-start: 22px; width: 24px; height: 24px;
      background: var(--sys-on-primary, #062e6f);
    }
    button:focus-visible { outline: 2px solid var(--sys-primary, #a8c7fa); outline-offset: 2px; }
    button:disabled { opacity: .38; cursor: default; }
    @media (prefers-reduced-motion: reduce) { button, button::after { transition: none; } }
  `;

  constructor() {
    super();
    this.label = 'Notify me when done';
    this._on = isOn();
  }

  async _toggle() {
    const on = !this._on;
    if (on && Notification.permission !== 'granted') {
      const answer = await Notification.requestPermission();
      if (answer !== 'granted') {
        this._on = false;
        return;
      }
    }
    try { localStorage.setItem(KEY, on ? 'on' : 'off'); } catch (_) { /* private mode */ }
    this._on = on;
  }

  render() {
    const supported = 'Notification' in window;
    const blocked = supported && Notification.permission === 'denied';
    return html`<button type="button" role="switch" aria-label=${this.label}
      aria-checked=${this._on ? 'true' : 'false'} ?disabled=${!supported || blocked}
      title=${blocked ? 'Notifications are blocked in this browser' : ''}
      @click=${this._toggle}></button>`;
  }
}

if (!customElements.get('gm-notify-toggle')) customElements.define('gm-notify-toggle', GmNotifyToggle);
