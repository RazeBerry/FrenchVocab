import { el, ignoreCancelled, makeButton, markScrollable, setBusy, setMessage } from "./ui.js";

export class ToolsView {
  constructor(api, onChanged) {
    this.api = api;
    this.onChanged = onChanged;
    this.loaded = false;
    this.provider = "gemini";
    this.message = el("provider-message");
    this.wire();
  }

  reset() {
    this.loaded = false;
    el("anki-download").hidden = true;
    el("provider-key").value = "";
    setMessage(el("anki-message"), "");
    setMessage(this.message, "");
  }

  async activate() {
    if (this.loaded) return;
    await this.refresh();
    this.loaded = true;
  }

  async refreshIfLoaded() { if (this.loaded) await this.refresh(); }

  async refresh() {
    await Promise.allSettled([this.loadAnki(), this.loadSettings(), this.loadStorage()]);
  }

  async loadAnki() {
    try {
      const status = await this.api.request("/api/anki", {}, { scope: "anki-status" });
      this.renderAnki(status);
    } catch (error) {
      if (!ignoreCancelled(error)) setMessage(el("anki-message"), error.message);
    }
  }

  // Words waiting to be exported are the normal state, not a fault; only stale
  // tracking needs a decision. Clauses with a count of zero are left out
  // rather than printed as "0 stale tracking records".
  renderAnki(status) {
    const pending = Number(status.pending_count || 0);
    const stale = Number(status.stale_count || 0);
    el("anki-status").textContent = stale
      ? "Needs attention"
      : (pending ? "Ready to export" : "In sync");
    el("anki-status").classList.toggle("is-ok", stale === 0);
    const clauses = [];
    if (pending) {
      clauses.push(`${pending} entr${pending === 1 ? "y is" : "ies are"} not in the deck yet`);
    }
    if (stale) {
      clauses.push(`${stale} tracking record${stale === 1 ? "" : "s"} point${stale === 1 ? "s" : ""} at words you have removed`);
    }
    el("anki-copy").textContent = clauses.length
      ? `${clauses.join(" · ")}.`
      : "Every vocabulary entry is represented in the export ledger.";
    el("anki-remove-stale").hidden = stale === 0;
  }

  async exportAnki(mode, button) {
    setBusy(button, true, "Building…");
    setMessage(el("anki-message"), "");
    try {
      const selected = el("anki-selected").value
        .split(",")
        .map((word) => word.trim())
        .filter(Boolean);
      if (mode === "selected" && !selected.length) {
        throw new Error("List at least one vocabulary word for a selected export.");
      }
      const result = await this.api.request("/api/anki/export", {
        method: "POST",
        body: JSON.stringify({
          mode,
          selected_words: mode === "selected" ? selected : [],
          include_mistakes: el("anki-mistakes").checked,
        }),
      }, { scope: "anki-export", timeout: 130000 });
      const link = el("anki-download");
      link.href = result.download_url;
      link.textContent = `Download ${formatBytes(result.size)}`;
      link.hidden = false;
      setMessage(el("anki-message"), "Deck created. Download it before leaving this page.", { ok: true });
      await Promise.allSettled([this.loadAnki(), this.onChanged()]);
    } catch (error) {
      if (!ignoreCancelled(error)) setMessage(el("anki-message"), error.message);
    } finally {
      setBusy(button, false);
    }
  }

  async removeStale() {
    if (!window.confirm("Remove only Anki tracking records for words no longer in the vocabulary file?")) return;
    try {
      const result = await this.api.request("/api/anki/remove-stale", {
        method: "POST",
      }, { scope: "anki-stale" });
      this.renderAnki(result);
      setMessage(el("anki-message"), `Removed ${result.removed} stale tracking record${result.removed === 1 ? "" : "s"}.`, { ok: true });
    } catch (error) {
      setMessage(el("anki-message"), error.message);
    }
  }

  async loadSettings() {
    try {
      const settings = await this.api.request("/api/settings", {}, { scope: "settings" });
      this.renderSettings(settings);
    } catch (error) {
      if (!ignoreCancelled(error)) setMessage(this.message, error.message);
    }
  }

  renderSettings(settings) {
    this.provider = settings.active || settings.providers?.[0]?.id || "gemini";
    // The heading names the provider; the model identifier is reference detail
    // and belongs below it, not wrapping across a display-serif h2 into the
    // status pill.
    const active = (settings.providers || []).find(({ id }) => id === settings.active);
    el("provider-label").textContent = active?.name || settings.label || "AI connection";
    el("provider-model").textContent = settings.model || "";
    el("provider-model").hidden = !settings.model;
    el("provider-status").textContent = settings.available ? "Connected" : "Unavailable";
    el("provider-status").classList.toggle("is-ok", Boolean(settings.available));
    const container = el("provider-options");
    container.replaceChildren();
    (settings.providers || []).forEach((provider) => {
      const suffix = provider.configured ? " · stored" : "";
      const button = makeButton(`${provider.name}${suffix}`, provider.id, provider.id === this.provider);
      button.addEventListener("click", () => {
        this.provider = provider.id;
        container.querySelectorAll("button").forEach((item) => {
          item.setAttribute("aria-pressed", String(item === button));
        });
      });
      container.appendChild(button);
    });
    markScrollable(container);
    if (settings.error && !settings.available) setMessage(this.message, settings.error);
  }

  async loadStorage() {
    try {
      const storage = await this.api.request("/api/storage", {}, { scope: "storage" });
      this.renderDownloads(el("file-list"), storage.current);
      this.renderDownloads(el("backup-list"), storage.backups);
    } catch (error) {
      if (!ignoreCancelled(error)) setMessage(this.message, error.message);
    }
  }

  renderDownloads(container, items) {
    container.replaceChildren();
    (items || []).forEach((item) => {
      const row = document.createElement("div");
      const link = document.createElement("a");
      const meta = document.createElement("span");
      link.href = item.download_url;
      link.textContent = item.filename;
      link.setAttribute("download", item.filename);
      meta.textContent = formatBytes(item.size);
      row.append(link, meta);
      container.appendChild(row);
    });
    if (!items?.length) {
      const empty = document.createElement("p");
      empty.className = "empty-state";
      empty.textContent = "No recovery copies yet.";
      container.appendChild(empty);
    }
  }

  async applyProvider() {
    const button = el("provider-save");
    const keyInput = el("provider-key");
    const key = keyInput.value.trim();
    setBusy(button, true, "Applying…");
    setMessage(this.message, "");
    try {
      const payload = { provider: this.provider };
      if (key) payload.api_key = key;
      const result = await this.api.request("/api/settings/provider", {
        method: "POST",
        body: JSON.stringify(payload),
      }, { scope: "provider-configure", timeout: 130000 });
      keyInput.value = "";
      this.renderSettings(result);
      setMessage(this.message, result.message, { ok: true });
      await this.onChanged();
    } catch (error) {
      setMessage(this.message, error.message);
    } finally {
      keyInput.value = "";
      setBusy(button, false);
    }
  }

  async testProvider() {
    const button = el("provider-test");
    setBusy(button, true, "Testing…");
    try {
      const result = await this.api.request("/api/settings/test", {
        method: "POST",
      }, { scope: "provider-test", timeout: 130000 });
      this.renderSettings(result);
      setMessage(this.message, result.message, { ok: true });
    } catch (error) {
      setMessage(this.message, error.message);
    } finally {
      setBusy(button, false);
    }
  }

  wire() {
    document.querySelectorAll(".anki-export").forEach((button) => {
      button.addEventListener("click", () => this.exportAnki(button.dataset.mode, button));
    });
    el("anki-remove-stale").addEventListener("click", () => this.removeStale());
    el("provider-save").addEventListener("click", () => this.applyProvider());
    el("provider-test").addEventListener("click", () => this.testProvider());
  }
}

function formatBytes(value) {
  const bytes = Number(value || 0);
  if (bytes < 1024) return `${bytes} B`;
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`;
  return `${(bytes / (1024 * 1024)).toFixed(1)} MB`;
}
