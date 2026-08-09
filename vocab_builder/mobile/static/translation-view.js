import { el, ignoreCancelled, makeButton, markScrollable, readStorage, setBusy, setMessage, writeStorage } from "./ui.js";

export class TranslationView {
  constructor(api, onSaved) {
    this.api = api;
    this.onSaved = onSaved;
    this.loaded = false;
    this.direction = "auto";
    this.preview = null;
    this.directions = [];
    this.autoAvailable = false;
    this.message = el("translation-message");
    this.wire();
  }

  draftKey() { return `vocabbuilder-translation-draft-${document.documentElement.dataset.language}`; }

  reset() {
    this.loaded = false;
    this.preview = null;
    el("translation-result").hidden = true;
    el("translation-pairs").replaceChildren();
    el("translation-input").value = readStorage(this.draftKey());
    setMessage(this.message, "");
  }

  async activate() {
    if (this.loaded) return;
    el("translation-input").value = readStorage(this.draftKey());
    await this.refresh();
    this.loaded = true;
  }

  async refreshIfLoaded() { if (this.loaded) await this.refresh(); }

  async begin(text, direction) {
    if (!this.loaded) {
      await this.activate();
    }
    if (this.directions.some(({ id }) => id === direction)) {
      this.direction = direction;
      this.renderDirections(this.autoAvailable);
    }
    el("translation-input").value = text;
    writeStorage(this.draftKey(), text);
    await this.previewTranslation();
  }

  async refresh() {
    try {
      const payload = await this.api.request("/api/translations", {}, { scope: "translations" });
      this.directions = payload.directions || [];
      this.autoAvailable = Boolean(payload.auto_available);
      const allowed = new Set(this.directions.map(({ id }) => id));
      if (payload.auto_available) allowed.add("auto");
      if (!allowed.has(this.direction)) this.direction = payload.auto_available
        ? "auto"
        : (this.directions[0]?.id || "");
      this.renderDirections(this.autoAvailable);
      await this.loadPairs();
    } catch (error) {
      if (!ignoreCancelled(error)) setMessage(this.message, error.message);
    }
  }

  renderDirections(autoAvailable) {
    const container = el("translation-directions");
    container.replaceChildren();
    const options = [
      ...(autoAvailable ? [{ id: "auto", source_label: "Auto", target_label: "detect" }] : []),
      ...this.directions,
    ];
    options.forEach((direction) => {
      const label = direction.id === "auto"
        ? "Auto detect"
        : `${direction.source_label} → ${direction.target_label}`;
      const button = makeButton(label, direction.id, direction.id === this.direction);
      button.addEventListener("click", () => {
        this.direction = direction.id;
        container.querySelectorAll("button").forEach((item) => {
          item.setAttribute("aria-pressed", String(item === button));
        });
        this.preview = null;
        el("translation-result").hidden = true;
        this.loadPairs();
      });
      container.appendChild(button);
    });
    markScrollable(container);
  }

  async previewTranslation() {
    const text = el("translation-input").value.trim();
    if (!text) { setMessage(this.message, "Type or paste text to translate first."); return; }
    const button = el("translate-button");
    setBusy(button, true, "Translating…");
    setMessage(this.message, "");
    try {
      const preview = await this.api.request("/api/translations/preview", {
        method: "POST",
        body: JSON.stringify({ direction: this.direction, text }),
      }, { scope: "translation-ai", timeout: 130000 });
      this.preview = preview;
      el("translation-route").textContent = `${preview.source_label} → ${preview.target_label}`;
      el("translation-source").textContent = preview.source_text;
      el("translation-target").textContent = preview.target_text;
      const warnings = [
        preview.notes,
        preview.suspicious ? "Review this result carefully; the source may contain mixed-language text." : "",
        preview.dropped_fragment ? `Ignored fragment: ${preview.dropped_fragment}` : "",
        preview.existing_entry ? "This source already exists; saving leaves the stored pair unchanged." : "",
      ].filter(Boolean);
      el("translation-note").hidden = warnings.length === 0;
      el("translation-note").textContent = warnings.join(" ");
      el("translation-result").hidden = false;
      el("translation-result").scrollIntoView({ behavior: "smooth", block: "nearest" });
    } catch (error) {
      if (!ignoreCancelled(error)) setMessage(this.message, error.message);
    } finally {
      setBusy(button, false);
    }
  }

  async saveTranslation() {
    if (!this.preview) return;
    const button = el("translation-save");
    setBusy(button, true, "Saving…");
    try {
      const receipt = await this.api.request("/api/translations/save", {
        method: "POST",
        body: JSON.stringify({ token: this.preview.token }),
      }, { scope: "translation-save" });
      setMessage(this.message, receipt.status === "duplicate"
        ? "That translation pair was already saved."
        : "Translation pair saved.", { ok: true });
      el("translation-input").value = "";
      writeStorage(this.draftKey(), "");
      el("translation-result").hidden = true;
      this.preview = null;
      await Promise.allSettled([this.loadPairs(), this.onSaved()]);
    } catch (error) {
      if (!ignoreCancelled(error)) setMessage(this.message, error.message);
    } finally {
      setBusy(button, false);
    }
  }

  async loadPairs() {
    const direction = this.direction === "auto" ? this.directions[0]?.id : this.direction;
    if (!direction) { el("translation-pairs").replaceChildren(); return; }
    try {
      const payload = await this.api.request(
        `/api/translations/pairs?direction=${encodeURIComponent(direction)}&page_size=20`,
        {},
        { scope: "translation-pairs" },
      );
      const container = el("translation-pairs");
      container.replaceChildren();
      // The studied language is the display face everywhere else in the app.
      // Styling by column position instead demoted it to dim sans whenever the
      // direction ran target -> English.
      const studiedIsSource = direction.startsWith("target");
      payload.items.forEach((pair) => {
        const row = document.createElement("article");
        const source = document.createElement("p");
        const target = document.createElement("p");
        source.className = studiedIsSource ? "pair-term" : "pair-gloss";
        target.className = studiedIsSource ? "pair-gloss" : "pair-term";
        source.textContent = pair.source;
        target.textContent = pair.target;
        row.append(source, target);
        container.appendChild(row);
      });
      if (!payload.items.length) {
        const empty = document.createElement("p");
        empty.className = "empty-state";
        empty.textContent = "Saved pairs will appear here.";
        container.appendChild(empty);
      }
    } catch (error) {
      if (!ignoreCancelled(error)) setMessage(this.message, error.message);
    }
  }

  wire() {
    el("translation-input").addEventListener("input", (event) => {
      writeStorage(this.draftKey(), event.target.value);
    });
    el("translate-button").addEventListener("click", () => this.previewTranslation());
    el("translation-save").addEventListener("click", () => this.saveTranslation());
    el("translation-discard").addEventListener("click", () => {
      this.preview = null;
      el("translation-result").hidden = true;
      setMessage(this.message, "");
    });
  }
}
