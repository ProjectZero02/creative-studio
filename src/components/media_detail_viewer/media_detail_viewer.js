import { LitElement, css, html } from '/ui/vendor/lit-3.2.1.js';
import { SvgIcon } from "../svg_icon/svg_icon.js";
import "../convert_to_gif_button/convert_to_gif_button.js";

class MediaDetailViewer extends LitElement {
  static styles = css`
    :host {
      display: block;
      width: 100%;
      container-type: inline-size;
      color: var(--sys-on-surface, #e3e3e3);
      --tonal: var(--gm-tonal, rgba(255, 255, 255, 0.08));
      --tonal-hover: var(--gm-tonal-hover, rgba(255, 255, 255, 0.14));
      --muted: var(--sys-on-surface-variant, #a8adb7);
      --line: var(--gm-border, rgba(255, 255, 255, 0.1));
    }
    .container {
      display: grid;
      grid-template-columns: minmax(0, 1.65fr) minmax(260px, 1fr);
      gap: 28px;
      align-items: start;
    }
    @container (max-width: 760px) {
      .container { grid-template-columns: minmax(0, 1fr); gap: 20px; }
      .left-column .stage { height: min(44vh, 380px); min-height: 200px; }
      .right-column .fields { max-height: none; }
      .right-column .panel-head { padding-inline-end: 0; }
    }
    .left-column, .right-column { display: flex; flex-direction: column; gap: 16px; min-width: 0; }

    /* The media sits on a dark stage that keeps one size whatever its shape. */
    .stage {
      position: relative;
      display: flex;
      align-items: center;
      justify-content: center;
      height: min(62vh, 620px);
      min-height: 260px;
      border-radius: 16px;
      background: rgba(0, 0, 0, 0.28);
      overflow: hidden;
    }
    .stage img, .stage video {
      max-width: 100%;
      max-height: 100%;
      object-fit: contain;
      display: block;
    }
    .stage audio { width: min(480px, 90%); }
    .empty {
      display: flex;
      flex-direction: column;
      align-items: center;
      gap: 10px;
      padding: 24px;
      text-align: center;
      color: var(--muted);
      font-size: 14px;
    }
    .empty svg-icon { width: 48px; height: 48px; opacity: 0.7; }
    .carousel-btn {
      position: absolute;
      top: 50%;
      transform: translateY(-50%);
      background: rgba(0, 0, 0, 0.5);
      color: white;
      border: none;
      border-radius: 50%;
      width: 40px;
      height: 40px;
      cursor: pointer;
      font-size: 24px;
      display: flex;
      align-items: center;
      justify-content: center;
    }
    .carousel-btn:hover { background: rgba(0, 0, 0, 0.8); }
    .carousel-btn[disabled] { opacity: 0.35; cursor: default; }
    .prev-btn { inset-inline-start: 10px; }
    .next-btn { inset-inline-end: 10px; }

    /* Actions: one row of quiet tonal pills, all the same height. */
    .actions { display: flex; flex-wrap: wrap; gap: 8px; }
    .act {
      display: inline-flex;
      align-items: center;
      gap: 8px;
      height: 36px;
      padding: 0 14px;
      border: 0;
      border-radius: 999px;
      background: var(--tonal);
      color: inherit;
      font: inherit;
      font-size: 14px;
      font-weight: 500;
      cursor: pointer;
      white-space: nowrap;
      transition: background 0.15s, color 0.15s;
    }
    .act:hover { background: var(--tonal-hover); }
    .act[disabled] { opacity: 0.5; cursor: default; }
    .act svg-icon, .act svg { width: 18px; height: 18px; flex: none; fill: currentColor; }
    .act.on { color: #fbbc04; }
    .act-error { color: var(--sys-error, #f28b82); font-size: 12px; }

    .sources { display: flex; gap: 8px; flex-wrap: wrap; }
    .sources img { width: 100px; height: 100px; object-fit: cover; border-radius: 8px; }
    h3 { margin: 0 0 8px 0; font-size: 1rem; font-weight: 600; }

    /* Right column: tabs and the star on one line, then the fields. */
    .panel-head {
      display: flex;
      align-items: center;
      justify-content: space-between;
      gap: 12px;
      border-bottom: 1px solid var(--line);
      padding-bottom: 8px;
      padding-inline-end: 48px; /* room for the dialog close button */
    }
    .tabs { display: flex; }
    .tab {
      padding: 8px 14px;
      cursor: pointer;
      border-radius: 999px;
      color: var(--muted);
      font-weight: 500;
    }
    .tab[active] { background: var(--tonal); color: inherit; }
    .fields { display: flex; flex-direction: column; gap: 14px; max-height: min(58vh, 600px); overflow-y: auto; }
    .metadata-item { display: flex; flex-direction: column; gap: 4px; }
    .metadata-key { font-size: 12px; font-weight: 500; color: var(--muted); }
    .metadata-value { font-size: 15px; line-height: 1.45; white-space: pre-wrap; overflow-wrap: anywhere; }
    .metadata-item.error .metadata-value { color: var(--sys-error, #f28b82); }
    .raw-json {
      margin: 0;
      background: rgba(0, 0, 0, 0.25);
      border-radius: 12px;
      padding: 14px;
      font-family: "Google Sans Code", monospace;
      white-space: pre-wrap;
      overflow-wrap: anywhere;
      font-size: 12px;
    }
  `;

  static get properties() {
    return {
      mediaType: { type: String },
      primaryUrlsJson: { type: String },
      sourceUrlsJson: { type: String },
      metadataJson: { type: String },
      rawMetadataJson: { type: String },
      id: { type: String },
      editClickEvent: { type: String },
      veoClickEvent: { type: String },
      omniClickEvent: { type: String },
      extendClickEvent: { type: String },
      lang: { type: String },
      stringsJson: { type: String }, // English -> shown text, from Python
      starred: { type: Boolean },
      starClickEvent: { type: String },
      _downloading: { state: true },
      _downloadError: { state: true },
      _currentIndex: { state: true },
      _activeTab: { state: true },
    };
  }

  constructor() {
    super();
    this.mediaType = "";
    this.primaryUrlsJson = "[]";
    this.sourceUrlsJson = "[]";
    this.metadataJson = "{}";
    this.rawMetadataJson = "{}";
    this.id = "";
    this.editClickEvent = "";
    this.veoClickEvent = "";
    this.omniClickEvent = "";
    this.extendClickEvent = "";
    this.lang = "";
    this.stringsJson = "{}";
    this._currentIndex = 0;
    this._activeTab = "details";
    this.starred = false;
    this.starClickEvent = "";
    this._downloading = false;
    this._downloadError = "";
  }

  /** Download through a signed URL (the API the old download button used). */
  async _download(gcsUri, filename) {
    this._downloading = true;
    this._downloadError = "";
    try {
      const res = await fetch(`/api/get_signed_url?gcs_uri=${encodeURIComponent(gcsUri)}`);
      const data = await res.json();
      if (!res.ok || data.error || !data.signed_url) throw new Error(data.error || `HTTP ${res.status}`);
      const blob = await (await fetch(data.signed_url)).blob();
      const link = document.createElement("a");
      link.href = URL.createObjectURL(blob);
      link.download = filename || "download";
      document.body.appendChild(link);
      link.click();
      link.remove();
      URL.revokeObjectURL(link.href);
    } catch (e) {
      console.error("Download failed:", e);
      this._downloadError = this._t("Download failed.");
    } finally {
      this._downloading = false;
    }
  }

  _toggleStar() {
    if (!this.starClickEvent) return;
    this.starred = !this.starred; // show it now; the server saves it
    this._dispatch(this.starClickEvent, {});
  }

  /** The shown text for an English string (English when no translation). */
  _t(english) {
    try {
      return (JSON.parse(this.stringsJson || "{}") || {})[english] || english;
    } catch (_) {
      return english;
    }
  }

  _navigate(direction) {
    const urls = JSON.parse(this.primaryUrlsJson);
    const newIndex = this._currentIndex + direction;
    if (newIndex >= 0 && newIndex < urls.length) {
      this._currentIndex = newIndex;
    }
  }

  _dispatch(eventName, data) {
    if (!eventName) return;
    this.dispatchEvent(new MesopEvent(eventName, data));
  }

  _handleGifConversion(event) {
    if (event.detail.error)
      console.error('Conversion failed:', event.detail.error);

    const container = this.shadowRoot.getElementById('gif-container');

    const header = document.createElement('h5');
    header.textContent = this._t('Converted GIF');

    container.appendChild(header);

    const gifViewer = document.createElement('img');
    gifViewer.src = event.detail.url;
    gifViewer.id = 'converted-gif-viewer';
    gifViewer.style.width="100%";
    gifViewer.style.maxWidth="480px";
    gifViewer.style.borderRadius=8;

    container.appendChild(gifViewer);
  }

  renderPrimaryAsset() {
    const urls = JSON.parse(this.primaryUrlsJson);
    if (urls.length === 0) {
      return html`<div class="empty"><svg-icon .iconName=${"broken_image"}></svg-icon>${this._t("No media to show.")}</div>`;
    }

    const currentUrl = urls[this._currentIndex];

    let assetHtml;
    switch (this.mediaType) {
      case "image":
        assetHtml = html`<img .src=${currentUrl} />`;
        break;
      case "video":
        assetHtml = html`<video .src=${currentUrl} controls autoplay></video>`;
        break;
      case "audio":
        assetHtml = html`<audio .src=${currentUrl} controls autoplay></audio>`;
        break;
      default:
        assetHtml = html`<p>${this._t('Unknown or unsupported media type.')}</p>`;
    }

    const showButtons = urls.length > 1;
    const rtl = this.lang === "ar";

    return html`
      ${assetHtml}
      ${showButtons
        ? html`
            <button
              class="carousel-btn prev-btn"
              @click=${() => this._navigate(-1)}
              ?disabled=${this._currentIndex === 0}
              aria-label=${this._t('Previous')}
            >
              ${rtl ? html`&#x203A;` : html`&#x2039;`}
            </button>
            <button
              class="carousel-btn next-btn"
              @click=${() => this._navigate(1)}
              ?disabled=${this._currentIndex === urls.length - 1}
              aria-label=${this._t('Next')}
            >
              ${rtl ? html`&#x2039;` : html`&#x203A;`}
            </button>
          `
        : ""}
    `;
  }

  renderSourceImages() {
    try {
      const sourceUrls = JSON.parse(this.sourceUrlsJson);
      if (sourceUrls.length === 0) return html``;

      return html`
        <h3>${this._t('Sources')}</h3>
        <div class="sources">
          ${sourceUrls.map((url) => url.endsWith(".mp4") ? html`<video width="160" height="120" .src=${url} controls autoplay></video>` : html`<img .src=${url} />`)}
        </div>
      `;
    } catch (e) {
      return html`${e}`;
    }
  }

  renderMetadata() {
    try {
      const metadata = JSON.parse(this.metadataJson);
      const rows = Object.entries(metadata).filter(([, v]) => v !== null && v !== undefined && v !== "");
      return rows.map(([key, value]) => {
        let formattedValue = value;
        if (key === 'Generation Time (s)' && !isNaN(parseFloat(value))) {
          formattedValue = Math.round(value * 100) / 100 + ' ' + this._t('seconds');
        } else if (key === 'Timestamp' && value) {
          const date = new Date(value);
          if (!isNaN(date)) {
            formattedValue = this.lang === 'ar' ? date.toLocaleString('ar') : date.toLocaleString();
          }
        }
        return html`
          <div class="metadata-item ${key === "Error" ? "error" : ""}">
            <span class="metadata-key">${this._t(key)}</span>
            <span class="metadata-value">${formattedValue}</span>
          </div>
        `;
      });
    } catch (e) {
      return html`<p>${this._t('Could not parse metadata.')}</p>`;
    }
  }

  renderRawMetadata() {
    try {
      const rawMetadata = JSON.parse(this.rawMetadataJson);
      return html`
        <div class="metadata-item">
          <span class="metadata-key">${this._t('Firestore Document ID')}</span>
          <span class="metadata-value">${this.id}</span>
        </div>
        <pre class="raw-json"><code>${JSON.stringify(rawMetadata, null, 2)}</code></pre>
      `;
    } catch (e) {
      return html`<p>${this._t('Could not parse raw metadata.')}</p>`;
    }
  }

  renderActions() {
    const urls = JSON.parse(this.primaryUrlsJson);
    if (urls.length === 0) return html``;
    const currentUrl = urls[this._currentIndex]; // This is the proxy URL, e.g., /media/bucket/object.png

    // Correctly convert the proxy URL back to a GCS URI for backend functions
    const isProxyUrl = currentUrl.startsWith("/media/");
    const gcsPath = isProxyUrl ? currentUrl.substring(7) : new URL(currentUrl).pathname.substring(1);
    const gcsUri = `gs://${gcsPath}`;

    const isImage = this.mediaType === 'image';
    const isVideo = this.mediaType === 'video';

    const handleCopyLink = () => {
      if (!navigator.clipboard) {
        alert(this._t("Copy to clipboard is only available on secure (HTTPS) sites."));
        return;
      }
      const url = new URL(window.location.href);
      url.searchParams.set("media_id", this.id);
      navigator.clipboard.writeText(url.href).then(() => {
        // Optional: show a temporary success message
        const copyButton = this.shadowRoot.querySelector("#copy-link-btn");
        if (copyButton) {
          const originalText = copyButton.textContent;
          copyButton.textContent = this._t("Copied!");
          setTimeout(() => {
            copyButton.textContent = originalText;
          }, 2000);
        }
      });
    };

    const filename = gcsPath.split("/").pop();
    return html`
      <div class="actions">
        <button class="act" ?disabled=${this._downloading} @click=${() => this._download(gcsUri, filename)}>
          <svg viewBox="0 0 24 24" aria-hidden="true"><path d="M19 9h-4V3H9v6H5l7 7 7-7zM5 18v2h14v-2H5z"/></svg>
          ${this._downloading ? this._t("Downloading...") : this._t("Download")}
        </button>
        ${isImage ? html`<button class="act" @click=${() => this._dispatch(this.editClickEvent, {url: currentUrl})}><svg-icon .iconName=${"edit"}></svg-icon>${this._t("Edit")}</button>` : ""}
        ${isImage ? html`<button class="act" @click=${() => this._dispatch(this.veoClickEvent, {url: currentUrl})}><svg-icon .iconName=${"movie_filter"}></svg-icon>Veo</button>` : ""}
        ${isImage ? html`<button class="act" @click=${() => this._dispatch(this.omniClickEvent, {url: currentUrl})}><svg-icon .iconName=${"spark"}></svg-icon>Omni</button>` : ""}
        ${isVideo ? html`<button class="act" @click=${() => this._dispatch(this.extendClickEvent, {url: currentUrl})}><svg-icon .iconName=${"movie_filter"}></svg-icon>${this._t("Extend")}</button>` : ""}
        <button class="act" id="copy-link-btn" @click=${handleCopyLink}><svg-icon .iconName=${"link"}></svg-icon>${this._t("Copy Link")}</button>
        ${isVideo ? html`<convert-to-gif-button .url=${gcsUri} @conversion-complete=${this._handleGifConversion}></convert-to-gif-button>` : ""}
      </div>
      ${this._downloadError ? html`<span class="act-error">${this._downloadError}</span>` : ""}
    `;
  }

  renderStar() {
    if (!this.starClickEvent) return "";
    const path = this.starred
      ? "m233-120 65-281L80-590l288-25 112-265 112 265 288 25-218 189 65 281-247-149-247 149Z"
      : "m354-287 126-76 126 77-33-144 111-96-146-13-58-136-58 135-146 13 111 97-33 143ZM233-120l65-281L80-590l288-25 112-265 112 265 288 25-218 189 65 281-247-149-247 149Zm247-350Z";
    return html`<button class="act ${this.starred ? "on" : ""}" aria-pressed=${this.starred ? "true" : "false"} @click=${() => this._toggleStar()}>
      <svg viewBox="0 -960 960 960" aria-hidden="true"><path d=${path}/></svg>
      ${this.starred ? this._t("Starred") : this._t("Star")}
    </button>`;
  }

  render() {
    return html`
      <div class="container">
        <div class="left-column">
          <div class="stage">${this.renderPrimaryAsset()}</div>
          ${this.renderActions()}
          ${this.renderSourceImages()}
          <div id='gif-container' display="flex" flex-direction="column" align-items="center" gap="10"></div>
        </div>
        <div class="right-column">
          <div class="panel-head">
            <div class="tabs">
              <div class="tab" ?active=${this._activeTab === 'details'} @click=${() => { this._activeTab = 'details' }}>${this._t('Details')}</div>
              <div class="tab" ?active=${this._activeTab === 'raw'} @click=${() => { this._activeTab = 'raw' }}>${this._t('Raw')}</div>
            </div>
            ${this.renderStar()}
          </div>
          <div class="fields">${this._activeTab === 'details' ? this.renderMetadata() : this.renderRawMetadata()}</div>
        </div>
      </div>
    `;
  }
}

if (!customElements.get("media-detail-viewer")) customElements.define("media-detail-viewer", MediaDetailViewer);
