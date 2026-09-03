import { detailInner, refit, renderEntries, renderEntryCard } from "./entry-list.js";
import {
  el,
  ignoreCancelled,
  makeButton,
  markScrollable,
  paragraph,
  setMessage,
} from "./ui.js";

/* A-Z plus the bucket everything else falls into. The server's letter census
   uses the same keys, so a letter is offered exactly when it holds words. */
const RAIL_LETTERS = [..."ABCDEFGHIJKLMNOPQRSTUVWXYZ", "#"];
const SEARCH_DEBOUNCE = 120;
/* The search endpoint's own ceiling. Nothing is dropped quietly: when a query
   matches more than this, the foot says so and asks for a narrower one. */
const SEARCH_PAGE_SIZE = 200;
/* The width at which the row becomes a table and a keyboard is likely. */
const WIDE = "(min-width: 560px)";

export class LibraryView {
  constructor(api, onLookUp) {
    this.api = api;
    this.onLookUp = onLookUp;
    this.loaded = false;
    this.sort = "alpha";
    this.query = "";
    this.wordType = "";
    this.index = [];
    this.addedIndex = [];
    this.letters = {};
    this.total = 0;
    this.results = [];
    this.searchTotal = 0;
    /* Detail fetched on open, kept for the life of the collection: reopening a
       word must not pay for the same request twice. */
    this.entries = new Map();
    this.rows = [];
    this.cursor = -1;
    this.timer = null;
    this.scrubbing = false;
    this.scrubLetter = "";
    this.wide = window.matchMedia(WIDE);
    this.wire();
  }

  reset() {
    this.loaded = false;
    this.sort = "alpha";
    this.query = "";
    this.wordType = "";
    this.index = [];
    this.addedIndex = [];
    this.letters = {};
    this.total = 0;
    this.results = [];
    this.entries.clear();
    el("search-input").value = "";
    this.setAuxiliaryPanel();
    this.showMessage("");
    this.render();
  }

  async activate() {
    if (this.loaded) return;
    this.renderSort();
    await Promise.allSettled([this.loadIndex(), this.loadStats()]);
    this.loaded = true;
  }

  async refreshIfLoaded() {
    if (!this.loaded) return;
    this.entries.clear();
    await Promise.allSettled([
      this.loadIndex(),
      this.loadStats(),
      this.query ? this.runSearch() : Promise.resolve(),
    ]);
  }

  /* One request for the whole collection. The rail has to know where every
     letter begins, which a page cannot say, and the rows are slim enough that
     asking again per page would cost more than asking once. */
  async loadIndex() {
    try {
      const payload = await this.api.request(
        "/api/library/index",
        {},
        { scope: "library-index" },
      );
      this.index = payload.items;
      // Acquisition rank is a server-owned fact shipped with the finder row.
      // The source is alphabetical, so stable sorting naturally leaves unknown
      // entries alphabetical after all ranked entries.
      this.addedIndex = [...this.index].sort(
        (left, right) => (right.added ?? -1) - (left.added ?? -1),
      );
      this.letters = payload.letters;
      this.total = payload.total;
      this.showMessage("");
      this.render();
    } catch (error) {
      if (!ignoreCancelled(error)) this.showMessage(error.message);
    }
  }

  async runSearch() {
    const query = this.query;
    const params = new URLSearchParams({ q: query, limit: String(SEARCH_PAGE_SIZE) });
    try {
      const payload = await this.api.request(
        `/api/library/search?${params}`,
        {},
        { scope: "library-search" },
      );
      if (query !== this.query) return;
      this.results = payload.items;
      this.searchTotal = payload.total;
      this.showMessage("");
      this.render();
    } catch (error) {
      if (!ignoreCancelled(error)) this.showMessage(error.message);
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
      if (!ignoreCancelled(error)) this.showMessage(error.message);
    }
  }

  render() {
    const searching = Boolean(this.query);
    const ordered = this.sort === "added" ? this.addedIndex : this.index;
    const rows = this.visibleRows(searching ? this.results : ordered);
    this.rows = renderEntries(el("entry-list"), rows, {
      // Letter dividers over search results or acquisition order would
      // contradict the order the rows are in.
      grouped: !searching && this.sort === "alpha",
      highlight: searching ? this.query : "",
      loadDetail: (entry, detail) => this.fillDetail(entry, detail),
    });
    // Roving tabindex: one stop for the whole list, then the arrow keys move
    // inside it, so Tab never has to walk 573 rows to reach the footer.
    this.rows.forEach((row, at) => { row.tabIndex = at === 0 ? 0 : -1; });
    this.cursor = -1;
    el("empty-state").hidden = rows.length > 0;
    this.renderRail();
    this.renderFoot(rows.length, searching);
  }

  /* A chip is a category from the stats census, so it keeps exactly the rows
     that census counted: "verb 162" shows 162 rows, not every type that
     contains the word. Applied to rows already in hand, because a round trip
     would drop the letter census and truncate at a page. */
  visibleRows(rows) {
    const filter = this.wordType.trim().toLowerCase();
    if (!filter) return rows;
    return rows.filter((row) => (row.word_type || "").trim().toLowerCase() === filter);
  }

  renderSort() {
    const container = el("library-sort");
    container.replaceChildren();
    [["alpha", "A–Z"], ["added", "Added"]].forEach(([value, label]) => {
      const button = makeButton(label, value, value === this.sort);
      button.addEventListener("click", () => {
        if (this.sort === value) return;
        this.sort = value;
        container.querySelectorAll("button").forEach((item) => {
          item.setAttribute("aria-pressed", String(item === button));
        });
        this.render();
      });
      container.appendChild(button);
    });
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
        this.render();
      });
      container.appendChild(button);
    });
    markScrollable(container);
  }

  /* The rail is shown exactly when the rows on screen are the whole collection
     in alphabetical order, because that is the only state in which its census
     and its jumps are both true. */
  railApplies() {
    return this.sort === "alpha" && !this.query && !this.wordType;
  }

  renderRail() {
    const rail = el("letter-rail");
    rail.hidden = !this.railApplies();
    if (rail.hidden) {
      rail.replaceChildren();
      return;
    }
    rail.replaceChildren(...RAIL_LETTERS.map((letter) => {
      const button = document.createElement("button");
      button.type = "button";
      button.className = "rail-letter";
      button.dataset.letter = letter;
      // 27 tab stops in front of the list would bury it, and the same jump is
      // on the A-Z keys. A screen reader still reaches these.
      button.tabIndex = -1;
      button.textContent = letter;
      button.setAttribute("aria-disabled", String(!(this.letters[letter] > 0)));
      button.addEventListener("click", () => this.jumpToLetter(letter, "smooth"));
      return button;
    }));
  }

  renderFoot(shown, searching) {
    const foot = el("index-foot");
    // With nothing on screen the empty state is the whole message.
    foot.hidden = shown === 0;
    // At a desktop width the keyboard is the faster instrument; on a phone the
    // rail is, and it is only there when it is true.
    const tail = this.wide.matches
      ? "tap a row, or press / to search"
      : (this.railApplies() ? "tap a row, or drag the rail" : "tap a row");
    if (searching) {
      const capped = this.searchTotal > shown
        ? `showing ${shown} of ${count(this.searchTotal, "match", "matches")}`
        : count(shown, "match", "matches");
      foot.textContent = `${capped} · ${tail}`;
      return;
    }
    const letters = Object.values(this.letters).filter((value) => value > 0).length;
    const scope = shown === this.total
      ? count(this.total, "word", "words")
      : `${shown} of ${count(this.total, "word", "words")}`;
    const order = this.sort === "added"
      ? "newest first"
      : count(letters, "letter", "letters");
    foot.textContent = `${scope} · ${order} · ${tail}`;
  }

  /* The row is a finder; the record behind it arrives when it is opened. */
  fillDetail(entry, detail) {
    const cached = this.entries.get(entryKey(entry.word));
    if (cached) {
      this.paintDetail(detail, cached);
      return;
    }
    detail.firstElementChild.replaceChildren(paragraph("index-loading", "Opening…"));
    this.api
      .request(
        `/api/library/entry?word=${encodeURIComponent(entry.word)}`,
        {},
        { scope: "library-entry" },
      )
      .then((record) => {
        this.entries.set(entryKey(record.word), record);
        this.paintDetail(detail, record);
      })
      .catch((error) => {
        if (ignoreCancelled(error)) return;
        // Nothing to show, so the row closes and the message line says why
        // rather than leaving an open panel that reads as still loading.
        detail.previousElementSibling.click();
        this.showMessage(error.message);
      });
  }

  paintDetail(detail, entry) {
    const inner = detailInner(entry);
    inner.appendChild(this.entryActions(entry));
    // A closed panel just takes the content; an open one grows to fit it,
    // whether the record landed mid-tween or after the panel had settled.
    if (!detail.classList.contains("is-open")) {
      detail.replaceChildren(inner);
      return;
    }
    refit(detail, () => detail.replaceChildren(inner));
  }

  /* The one action a glossary can offer without owning a vocabulary rule: it
     hands the entry to capture, which already knows what to do with a word you
     hold. Practice and Anki selection wait for their own views to be shown. */
  entryActions(entry) {
    const actions = document.createElement("div");
    actions.className = "entry-actions";
    const button = document.createElement("button");
    button.type = "button";
    button.className = "ghost-button";
    button.textContent = "Look up more senses";
    button.addEventListener("click", () => this.onLookUp(entry));
    actions.appendChild(button);
    return actions;
  }

  jumpToLetter(letter, behavior) {
    /* The heading is the destination, so its presence is the only test that is
       right in every state: the census counts the whole collection, and a type
       chip can empty a letter out of the rendered list. */
    const heading = el("entry-list").querySelector(`.index-letter[data-letter="${letter}"]`);
    if (!heading) return;
    window.scrollTo({
      top: heading.getBoundingClientRect().top + window.scrollY,
      behavior: reducedMotion() ? "auto" : behavior,
    });
  }

  /* Dragging the rail scrubs the list. The letter under the finger is read
     from the rail's own geometry, so the pitch is whatever CSS gives it. */
  scrub(event) {
    const rail = el("letter-rail");
    const rect = rail.getBoundingClientRect();
    const step = rect.height / RAIL_LETTERS.length;
    const at = Math.floor((event.clientY - rect.top) / step);
    const letter = RAIL_LETTERS[Math.min(Math.max(at, 0), RAIL_LETTERS.length - 1)];
    // A letter with no words is not a destination, so the finger passes over it
    // and the list holds where it was.
    if (!(this.letters[letter] > 0) || letter === this.scrubLetter) return;
    this.scrubLetter = letter;
    rail.querySelectorAll(".rail-letter").forEach((button) => {
      button.classList.toggle("is-current", button.dataset.letter === letter);
    });
    const bubble = el("rail-bubble");
    bubble.hidden = false;
    bubble.textContent = letter;
    // Beside the rail wherever the rail is: at a desktop width the app column
    // is centred, so a fixed offset from the window edge would strand it.
    bubble.style.top = `${Math.round(event.clientY)}px`;
    bubble.style.left = `${Math.round(rect.left - 66)}px`;
    this.jumpToLetter(letter, "auto");
  }

  endScrub() {
    this.scrubbing = false;
    this.scrubLetter = "";
    el("rail-bubble").hidden = true;
    el("letter-rail").querySelectorAll(".is-current").forEach((button) => {
      button.classList.remove("is-current");
    });
  }

  moveCursor(step) {
    if (this.rows.length === 0) return;
    const next = Math.min(Math.max(this.cursor + step, 0), this.rows.length - 1);
    this.setCursor(next);
    this.rows[next].focus();
  }

  setCursor(next) {
    if (next === this.cursor) return;
    const previous = this.rows[this.cursor];
    if (previous) {
      previous.tabIndex = -1;
      previous.classList.remove("is-cursor");
    }
    const current = this.rows[next];
    if (current) {
      current.tabIndex = 0;
      current.classList.add("is-cursor");
    }
    this.cursor = next;
  }

  /* The CLI is arrow-driven and the desktop frame is a real surface, so the
     glossary answers the same keys. Focus stays on the list. */
  onKeyDown(event) {
    if (el("view-library").hidden) return;
    if (event.metaKey || event.ctrlKey || event.altKey) return;
    const search = el("search-input");
    const typing = event.target instanceof HTMLInputElement
      || event.target instanceof HTMLTextAreaElement;
    if (event.key === "Escape") {
      this.escape(search);
      return;
    }
    if (event.key === "/" && !typing) {
      event.preventDefault();
      search.focus();
      search.select();
      return;
    }
    if (typing) return;
    if (event.key === "ArrowDown" || event.key === "ArrowUp") {
      event.preventDefault();
      this.moveCursor(event.key === "ArrowDown" ? 1 : -1);
      return;
    }
    if (/^[a-z]$/i.test(event.key)) this.jumpToLetter(event.key.toUpperCase(), "smooth");
  }

  escape(search) {
    const open = el("entry-list").querySelector('.index-row[aria-expanded="true"]');
    if (open) {
      open.click();
      open.focus();
      return;
    }
    if (!this.query) return;
    window.clearTimeout(this.timer);
    search.value = "";
    this.query = "";
    this.results = [];
    this.render();
  }

  async showRandom() {
    try {
      const entry = await this.api.request("/api/library/random", {}, { scope: "library-random" });
      const panel = el("random-panel");
      renderEntryCard(panel, entry);
      this.setAuxiliaryPanel("random-panel");
      panel.scrollIntoView({ behavior: "smooth", block: "nearest" });
    } catch (error) {
      if (!ignoreCancelled(error)) this.showMessage(error.message);
    }
  }

  /* Each action owns its content; this only coordinates which disclosure is
     open. That keeps a random card from ever replacing the cached statistics
     and keeps the buttons' accessible state aligned with the visible panel. */
  setAuxiliaryPanel(openPanel = "") {
    [
      ["random-button", "random-panel"],
      ["stats-button", "stats-panel"],
    ].forEach(([buttonId, panelId]) => {
      const expanded = panelId === openPanel;
      el(panelId).hidden = !expanded;
      el(buttonId).setAttribute("aria-expanded", String(expanded));
    });
  }

  showMessage(text, options) { setMessage(el("library-message"), text, options); }

  wire() {
    el("search-input").addEventListener("input", (event) => {
      window.clearTimeout(this.timer);
      this.query = event.target.value.trim();
      if (!this.query) {
        this.results = [];
        this.searchTotal = 0;
        this.render();
        return;
      }
      this.timer = window.setTimeout(() => this.runSearch(), SEARCH_DEBOUNCE);
    });
    el("stats-button").addEventListener("click", () => {
      const panel = el("stats-panel");
      this.setAuxiliaryPanel(panel.hidden ? "stats-panel" : "");
    });
    el("random-button").addEventListener("click", () => this.showRandom());
    el("entry-list").addEventListener("focusin", (event) => {
      if (event.target === this.rows[this.cursor]) return;
      const at = this.rows.indexOf(event.target);
      if (at >= 0) this.setCursor(at);
    });

    const rail = el("letter-rail");
    rail.addEventListener("pointerdown", (event) => {
      event.preventDefault();
      rail.setPointerCapture(event.pointerId);
      this.scrubbing = true;
      this.scrubLetter = "";
      this.scrub(event);
    });
    rail.addEventListener("pointermove", (event) => {
      if (this.scrubbing) this.scrub(event);
    });
    rail.addEventListener("pointerup", () => this.endScrub());
    rail.addEventListener("pointercancel", () => this.endScrub());

    document.addEventListener("keydown", (event) => this.onKeyDown(event));
    // The hint names the instrument the reader actually has.
    this.wide.addEventListener("change", () => {
      if (this.loaded) this.renderFoot(this.rows.length, Boolean(this.query));
    });
  }
}

function entryKey(word) {
  return (word || "").trim().toLocaleLowerCase();
}

function count(value, singular, plural) {
  return `${Number(value || 0).toLocaleString()} ${value === 1 ? singular : plural}`;
}

function reducedMotion() {
  return window.matchMedia("(prefers-reduced-motion: reduce)").matches;
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
