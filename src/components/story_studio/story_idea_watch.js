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
 * <story-idea-watch>: invisible. Watches the text field inside the element
 * matching `selector` and, once the user pauses typing for `delay` ms, sends
 * a Mesop event with the text ({value}). One event per pause, not per key,
 * so the page can update the film settings live without a server round trip
 * on every keystroke. The page never writes back into the field, so typing
 * is never interrupted.
 */
import { LitElement } from '/ui/vendor/lit-3.2.1.js';

class StoryIdeaWatch extends LitElement {
  static properties = {
    selector: { type: String },
    delay: { type: Number },
    ideaEvent: { type: String },
  };

  constructor() {
    super();
    this.selector = '.ss-idea-field';
    this.delay = 700;
    this.ideaEvent = '';
    this._timer = null;
    this._last = null;
    this._onInput = (e) => {
      const target = e.target;
      if (!target || !target.closest || !target.closest(this.selector)) return;
      if (target.tagName !== 'TEXTAREA' && target.tagName !== 'INPUT') return;
      clearTimeout(this._timer);
      this._timer = setTimeout(() => this._send(target.value), Math.max(250, this.delay || 700));
    };
  }

  connectedCallback() {
    super.connectedCallback();
    document.addEventListener('input', this._onInput, true);
  }

  disconnectedCallback() {
    super.disconnectedCallback();
    document.removeEventListener('input', this._onInput, true);
    clearTimeout(this._timer);
  }

  _send(value) {
    if (!this.ideaEvent || value === this._last) return;
    this._last = value;
    this.dispatchEvent(new MesopEvent(this.ideaEvent, { value }));
  }

  render() { return null; }
}

customElements.define('story-idea-watch', StoryIdeaWatch);
