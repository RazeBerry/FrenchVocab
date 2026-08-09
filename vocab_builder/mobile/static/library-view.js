import { renderEntries, renderEntryCard } from "./entry-list.js";
import { el, ignoreCancelled, makeButton, markScrollable } from "./ui.js";

export class LibraryView {
  constructor(api) {
    this.api = api;
    this.loaded = false;
    this.page = 1;
    this.query = "";
    this.wordType = "";
    this.items = [];
    this.timer = null;
    this.wire();
  }

  reset() {
    this.loaded = false;
    this.page = 1;
    this.items = [];
    this.query = "";
    this.wordType = "";
    el("search-input").value = "";
    el("stats-panel").hidden = true;
    renderEntries(el("entry-list"), []);
  }

  async activate() {
    if (this.loaded) return;
    await Promise.allSettled([this.loadPage(true), this.loadStats()]);
    this.loaded = true;
  }

  async refreshIfLoaded() {
    if (!this.loaded) return;
    await Promise.allSettled([this.loadPage(true), this.loadStats()]);
  }

  async loadPage(reset = false) {
    if (reset) { this.page = 1; this.items = []; }
    const params = new URLSearchParams({
      q: this.query,
      word_type: this.wordType,
      page: String(this.page),
      page_size: "50",
    });
    try {
      const payload = await this.api.request(`/api/library?${params}`, {}, { scope: "library" });
      this.items = reset ? payload.items : [...this.items, ...payload.items];
      renderEntries(el("entry-list"), this.items, { grouped: true });
      el("empty-state").hidden = payload.total > 0;
      el("library-more").hidden = !payload.has_more;
      el("index-foot").hidden = payload.total === 0;
      el("index-foot").textContent = `${this.items.length} of ${payload.total} shown · tap to open`;
      el("library-summary").textContent = this.query || this.wordType
        ? `${payload.total} matching entr${payload.total === 1 ? "y" : "ies"}`
        : `${payload.total} entries, with every meaning and example searchable.`;
    } catch (error) {
      if (!ignoreCancelled(error)) {
        el("library-summary").textContent = error.message;
        el("library-summary").classList.add("is-error");
      }
    }
  }

  async loadStats() {
    try {
      const stats = await this.api.request("/api/library/stats", {}, { scope: "library-stats" });
      this.renderTypeChips(stats.types || []);
      const panel = el("stats-panel");
      panel.replaceChildren(
        metric(stats.total, "entries"),
        metric(stats.with_examples, "with examples"),
        metric(stats.with_multiple_senses, "multi-sense"),
      );
    } catch (error) {
      if (!ignoreCancelled(error)) el("library-summary").textContent = error.message;
    }
  }

  renderTypeChips(types) {
    const container = el("type-chips");
    container.replaceChildren();
    const options = [{ name: "All", count: null, value: "" }, ...types.map((type) => ({
      ...type,
      value: type.name,
    }))];
    options.forEach(({ name, count, value }) => {
      const label = count == null ? name : `${name} ${count}`;
      const button = makeButton(label, value, value === this.wordType);
      button.className = "chip";
      button.addEventListener("click", () => {
        this.wordType = value;
        container.querySelectorAll("button").forEach((item) => {
          item.setAttribute("aria-pressed", String(item === button));
        });
        this.loadPage(true);
      });
      container.appendChild(button);
    });
    markScrollable(container);
  }

  async showRandom() {
    try {
      const entry = await this.api.request("/api/library/random", {}, { scope: "library-random" });
      const panel = el("stats-panel");
      panel.hidden = false;
      panel.classList.add("random-card");
      renderEntryCard(panel, entry);
      panel.scrollIntoView({ behavior: "smooth", block: "nearest" });
    } catch (error) {
      el("library-summary").textContent = error.message;
    }
  }

  wire() {
    el("search-input").addEventListener("input", (event) => {
      window.clearTimeout(this.timer);
      this.query = event.target.value.trim();
      this.timer = window.setTimeout(() => this.loadPage(true), 220);
    });
    el("library-more").addEventListener("click", () => {
      this.page += 1;
      this.loadPage(false);
    });
    el("stats-button").addEventListener("click", () => {
      const panel = el("stats-panel");
      panel.classList.remove("random-card");
      panel.hidden = !panel.hidden;
    });
    el("random-button").addEventListener("click", () => this.showRandom());
  }
}

function metric(value, label) {
  const node = document.createElement("div");
  const number = document.createElement("strong");
  const copy = document.createElement("span");
  number.textContent = Number(value || 0).toLocaleString();
  copy.textContent = label;
  node.append(number, copy);
  return node;
}
