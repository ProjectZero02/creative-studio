import { LitElement, css, html } from '/ui/vendor/lit-3.2.1.js';
import { SvgIcon } from "../svg_icon/svg_icon.js";

class MediaTile extends LitElement {
  static styles = css`
    :host {
      display: block;
      position: relative;
      border-radius: 12px;
      overflow: hidden;
      cursor: pointer;
      border: 1px solid var(--mesop-outline-variant-color);
      height: 250px;
      background-color: rgba(255, 255, 255, 0.05);
    }

    .preview {
      width: 100%;
      height: 100%;
      display: flex;
      align-items: center;
      justify-content: center;
    }

    .preview img,
    .preview video {
      width: 100%;
      height: 100%;
      object-fit: cover;
    }

    .preview .icon {
      width: 64px;
      height: 64px;
      color: var(--mesop-on-surface-variant-color);
    }

    .overlay {
      position: absolute;
      top: 0;
      left: 0;
      right: 0;
      bottom: 0;
      background: linear-gradient(
        to top,
        rgba(0, 0, 0, 0.7) 0%,
        rgba(0, 0, 0, 0.3) 50%,
        transparent 100%
      );
      display: flex;
      flex-direction: column;
      justify-content: flex-end;
      padding: 12px;
      pointer-events: none;
      opacity: 0;
      transition: opacity 0.2s ease-in-out;
    }

    .overlay > * {
      pointer-events: auto;
    }

    :host(:hover) .overlay {
      opacity: 1;
    }

    .pills-container {
      display: flex;
      flex-wrap: wrap;
      gap: 4px;
    }

    .pill {
      background-color: rgba(255, 255, 255, 0.8);
      color: #202124;
      padding: 4px 8px;
      border-radius: 6px;
      font-size: 12px;
      font-weight: 500;
    }

    /* Star: an empty star on hover that fills in gold under the pointer;
       a filled one stays when starred. No backdrop: a soft shadow keeps it
       readable on light pictures. */
    .star {
      position: absolute;
      top: 6px;
      inset-inline-end: 6px;
      width: 48px;
      height: 48px;
      padding: 6px;
      border: 0;
      background: none;
      color: #fff;
      cursor: pointer;
      opacity: 0;
      transition: opacity 0.2s ease-in-out;
      z-index: 2;
      -webkit-tap-highlight-color: transparent;
    }
    .star svg {
      width: 36px;
      height: 36px;
      display: block;
      overflow: visible;
      filter: drop-shadow(0 1px 3px rgba(0, 0, 0, 0.55));
    }
    .star .outline { fill: currentColor; transition: fill 0.2s ease; }
    .star .fill {
      fill: #fbbc04;
      transform: scale(0);
      transform-box: fill-box;
      transform-origin: center;
      transition: transform 0.28s cubic-bezier(0.34, 1.56, 0.64, 1);
    }
    .star:hover .fill,
    .star:focus-visible .fill,
    .star.on .fill { transform: scale(1); }
    .star:hover .outline,
    .star.on .outline { fill: #fbbc04; }
    .star:focus-visible { opacity: 1; outline: 2px solid #fff; outline-offset: -2px; border-radius: 8px; }
    .star.on { opacity: 1; }
    .star.pop svg { animation: star-pop 0.4s cubic-bezier(0.34, 1.56, 0.64, 1); }
    @keyframes star-pop {
      0% { transform: scale(1); }
      35% { transform: scale(1.35); }
      100% { transform: scale(1); }
    }
    :host(:hover) .star { opacity: 1; }

    @media (prefers-reduced-motion: reduce) {
      .star .fill, .star .outline { transition: none; }
      .star.pop svg { animation: none; }
    }

    .creator {
      position: absolute;
      top: 10px;
      inset-inline-start: 10px;
      max-width: calc(100% - 72px);
      padding: 6px 10px;
      border-radius: 999px;
      background: rgba(0, 0, 0, 0.55);
      color: #fff;
      font-size: 12px;
      font-weight: 500;
      white-space: nowrap;
      overflow: hidden;
      text-overflow: ellipsis;
      opacity: 0;
      transition: opacity 0.2s ease-in-out;
      pointer-events: none;
      z-index: 2;
    }
    :host(:hover) .creator { opacity: 1; }

    audio {
      width: 100%;
      margin-bottom: 8px;
      filter: invert(1) grayscale(1) contrast(1.5);
    }
  `;

  static get properties() {
    return {
      mediaType: { type: String },
      thumbnailSrc: { type: String },
      audioSrc: { type: String },
      pillsJson: { type: String },
      clickEvent: { type: String }, // Added to receive the event handler ID
      creator: { type: String },
      starred: { type: Boolean },
      starLabel: { type: String },
      starEvent: { type: String },
    };
  }

  constructor() {
    super();
    this.mediaType = "";
    this.thumbnailSrc = "";
    this.audioSrc = "";
    this.pillsJson = "[]";
    this.clickEvent = ""; // Initialize
    this.creator = "";
    this.starred = false;
    this.starLabel = "Star";
    this.starEvent = "";
    this.addEventListener("click", this.handleClick);
  }

  disconnectedCallback() {
    super.disconnectedCallback();
    this.removeEventListener("click", this.handleClick);
  }

  handleClick(e) {
    console.log("media-tile clicked, dispatching MesopEvent");
    if (!this.clickEvent) {
      console.error("Mesop event handler ID for clickEvent is not set.");
      return;
    }
    // Use the correct MesopEvent to communicate back to the server
    this.dispatchEvent(new MesopEvent(this.clickEvent, {}));
  }

  renderPreview() {
    // Failed or empty generations have no media URL: show a clean fallback icon
    // instead of an <img>/<video> with an empty src.
    if (
      (this.mediaType === "image" || this.mediaType === "video") &&
      !this.thumbnailSrc
    ) {
      return html`<div class="icon"><svg-icon .iconName=${'broken_image'}></svg-icon></div>`;
    }
    switch (this.mediaType) {
      case "image":
        return html`<img .src=${this.thumbnailSrc} />`;
      case "video":
        return html`<video
          .src=${this.thumbnailSrc}
          muted
          autoplay
          loop
          playsinline
        ></video>`;
      case "audio":
        return html`<div class="icon"><svg-icon .iconName=${'music_note'}></svg-icon></div>`;
      default:
        return html`<div class="icon"><svg-icon .iconName=${'help'}></svg-icon></div>`;
    }
  }

  handleStar(e) {
    // The star must not also open the item.
    e.stopPropagation();
    if (!this.starEvent) return;
    this.starred = !this.starred; // show it now; the server saves it
    if (this.starred) this.celebrate(e.currentTarget);
    this.dispatchEvent(new MesopEvent(this.starEvent, {}));
  }

  /** Pop the star and throw confetti out of it. */
  celebrate(button) {
    if (window.matchMedia("(prefers-reduced-motion: reduce)").matches) return;
    button.classList.remove("pop");
    void button.offsetWidth; // restart the animation
    button.classList.add("pop");
    // On the page, not in the tile: the tile clips its rounded corners.
    const star = button.getBoundingClientRect();
    const cx = star.left + star.width / 2;
    const cy = star.top + star.height / 2;
    const colors = ["#fbbc04", "#ea4335", "#4285f4", "#34a853", "#a142f4", "#ffffff"];
    const count = 18;
    for (let i = 0; i < count; i++) {
      const bit = document.createElement("span");
      Object.assign(bit.style, {
        position: "fixed",
        left: cx - 3.5 + "px",
        top: cy - 3.5 + "px",
        width: "7px",
        height: "7px",
        borderRadius: i % 3 === 0 ? "50%" : "2px",
        background: colors[i % colors.length],
        pointerEvents: "none",
        zIndex: "10000",
      });
      document.body.appendChild(bit);
      const angle = (Math.PI * 2 * i) / count + (Math.random() - 0.5) * 0.5;
      const dist = 34 + Math.random() * 34;
      const dx = Math.cos(angle) * dist;
      const dy = Math.sin(angle) * dist;
      const spin = (Math.random() - 0.5) * 540;
      bit.animate(
        [
          { transform: "translate(0, 0) rotate(0deg) scale(0.6)", opacity: 1 },
          { transform: `translate(${dx}px, ${dy}px) rotate(${spin / 2}deg) scale(1)`, opacity: 1, offset: 0.6 },
          { transform: `translate(${dx * 1.15}px, ${dy * 1.15 + 18}px) rotate(${spin}deg) scale(0.8)`, opacity: 0 },
        ],
        { duration: 750 + Math.random() * 250, easing: "cubic-bezier(0.22, 1, 0.36, 1)" },
      ).finished.finally(() => bit.remove());
    }
  }

  renderStar() {
    if (!this.starEvent) return "";
    const filled = "m233-120 65-281L80-590l288-25 112-265 112 265 288 25-218 189 65 281-247-149-247 149Z";
    const outline = "m354-287 126-76 126 77-33-144 111-96-146-13-58-136-58 135-146 13 111 97-33 143ZM233-120l65-281L80-590l288-25 112-265 112 265 288 25-218 189 65 281-247-149-247 149Zm247-350Z";
    return html`<button
      class="star ${this.starred ? "on" : ""}"
      aria-label=${this.starLabel}
      aria-pressed=${this.starred ? "true" : "false"}
      title=${this.starLabel}
      @click=${(e) => this.handleStar(e)}
    ><svg viewBox="0 -960 960 960" aria-hidden="true"><path class="fill" d=${filled}/><path class="outline" d=${outline}/></svg></button>`;
  }

  renderPills() {
    try {
      const pills = JSON.parse(this.pillsJson);
      return pills.map((pill) => html`<div class="pill">${pill.label}</div>`);
    } catch (e) {
      console.error("Error parsing pillsJson:", e);
      return html``;
    }
  }

  render() {
    return html`
      <div class="preview">${this.renderPreview()}</div>
      ${this.creator ? html`<div class="creator" title=${this.creator}>${this.creator}</div>` : ""}
      ${this.renderStar()}
      <div class="overlay">
        ${this.mediaType === "audio"
          ? html`<audio controls .src=${this.audioSrc}></audio>`
          : ""}
        <div class="pills-container">${this.renderPills()}</div>
      </div>
    `;
  }
}

if (!customElements.get("media-tile")) customElements.define("media-tile", MediaTile);