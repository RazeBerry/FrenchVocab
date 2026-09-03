import { dayKey, renderEntries } from "./entry-list.js";
import { el, ignoreCancelled, readStorage, setMessage, writeStorage } from "./ui.js";

/* The strip is a day's work, not a fixed eight rows. Ask for the endpoint's
   cap and show all of today, so a heavy session cannot silently drop this
   morning's words, then enough earlier records to keep the strip useful. */
const RECENT_LIMIT = 30;
const RECENT_ROWS = 8;

const HEADWORD_STEPS = [
  { max: 14, className: "hw--s1" },
  { max: 28, className: "hw--s2" },
  { max: Infinity, className: "hw--s3" },
];

export class CaptureView {
  constructor(api, onSaved, onRouteSentence) {
    this.api = api;
    this.onSaved = onSaved;
    this.onRouteSentence = onRouteSentence;
    this.mode = "capture";
    this.preview = null;
    this.displayedEntry = null;
    this.language = "fr";
    this.languageName = "";
    this.expanded = false;
    this.pendingDuplicateText = "";
    this.justSaved = "";
    this.slip = el("slip");
    this.input = el("entry-input");
    this.primary = el("primary-button");
    this.discard = el("discard-button");
    this.more = el("more-button");
    this.message = el("form-message");
    this.ribbon = el("slip-ribbon");
    this.variant = el("variant-button");
    this.wire();
    this.showCapture();
  }

  draftKey() { return `vocabbuilder-capture-draft-${this.language}`; }

  setLanguage(status) {
    const changed = this.language !== status.language;
    this.language = status.language;
    this.languageName = status.language_name;
    el("entry-label").textContent = `${status.language_name} word or phrase`;
    const total = Number(status.entry_count || 0);
    el("library-link").textContent =
      `All ${total.toLocaleString()} ${total === 1 ? "word" : "words"}`;
    if (changed) {
      this.input.value = readStorage(this.draftKey());
      this.showCapture();
    } else if (this.mode === "capture") {
      el("slip-pos").textContent = status.language_name;
    }
  }

  reset() {
    this.preview = null;
    this.pendingDuplicateText = "";
    this.justSaved = "";
    this.input.value = "";
    this.showCapture();
    renderEntries(el("recent-list"), []);
    el("recent-empty").hidden = false;
  }

  async activate() { await this.refresh(); }

  async refresh() {
    try {
      const entries = await this.api.request(
        `/api/recent?limit=${RECENT_LIMIT}`,
        {},
        { scope: "recent" },
      );
      const shown = ledgerWindow(entries);
      renderEntries(el("recent-list"), shown, {
        groupBy: "day",
        justSaved: this.justSaved,
      });
      el("recent-empty").hidden = shown.length > 0;
    } catch (error) {
      if (!ignoreCancelled(error)) this.showMessage(error.message);
    }
  }

  showMessage(text, options) { setMessage(this.message, text, options); }

  showCapture({ preserveMessage = false } = {}) {
    this.mode = "capture";
    this.preview = null;
    this.displayedEntry = null;
    this.expanded = false;
    this.pendingDuplicateText = "";
    this.slip.classList.add("is-capturing");
    this.slip.classList.remove("is-expanded");
    this.ribbon.hidden = true;
    this.input.hidden = false;
    el("preview-word").hidden = true;
    this.discard.hidden = true;
    this.more.hidden = true;
    this.variant.hidden = true;
    el("slip-senses").hidden = true;
    el("slip-examples").hidden = true;
    el("slip-example").replaceChildren();
    el("slip-mean").hidden = false;
    el("slip-mean").textContent = "The meaning will appear here.";
    el("slip-pos").textContent = this.languageName || "\u00a0";
    el("primary-label").textContent = "Look it up";
    this.primary.disabled = !this.input.value.trim() || !navigator.onLine;
    scaleHeadword(this.input, this.input.value);
    autoGrow(this.input);
    if (!preserveMessage) this.showMessage("");
  }

  showPreview(preview) {
    this.mode = "preview";
    this.preview = preview;
    if (preview.duplicate_action === "merge" && preview.existing_entry) {
      this.showMergePreview(preview);
      return;
    }
    if (preview.duplicate_action === "variant" && preview.existing_entry) {
      this.showVariantPreview(preview);
      return;
    }

    this.showStandardPreview(preview);
  }

  showStandardPreview(preview) {
    this.expanded = false;
    this.ribbon.hidden = true;
    this.variant.hidden = true;
    this.renderEntry(preview, preview.word);
    // The solid button always commits the previewed entry and the ghost always
    // offers the alternative to committing it. Routing a sentence to the
    // translator used to sit in the solid slot while the ghost wrote to disk,
    // which read exactly backwards.
    this.discard.hidden = false;
    this.discard.textContent = preview.route_recommended
      ? "Translate instead"
      : (preview.spelling_suggestion ? `Keep “${preview.original_input}”` : "Discard");
    el("primary-label").textContent = preview.route_recommended
      ? "Keep as vocabulary"
      : "Keep it";
    this.primary.disabled = false;
    this.showMessage(
      preview.spelling_suggestion ? `Corrected to “${preview.word}”.` : "",
      { note: true },
    );
  }

  /* The state a duplicate lands in, and the one the glossary opens for a word
     you already hold. `lookupText` is what a further look-up would be asked
     about: the text as typed when a duplicate raised this, and otherwise the
     stored headword. */
  showCollected(existingEntry, lookupText = existingEntry.word) {
    this.mode = "collected";
    this.pendingDuplicateText = lookupText;
    this.preview = null;
    this.expanded = false;
    this.renderEntry(existingEntry, existingEntry.word);
    this.setRibbon(
      "In your collection",
      countLabel(existingEntry.definitions?.length || 0, "sense"),
    );
    this.discard.hidden = false;
    this.discard.textContent = "Add new senses";
    el("primary-label").textContent = "Keep what I have";
    this.primary.disabled = false;
    this.variant.hidden = false;
    this.showMessage(
      "Looking up again asks the model for senses you may be missing. It takes a moment.",
      { note: true },
    );
  }

  showMergePreview(preview) {
    const existing = preview.existing_entry;
    const newDefinitions = preview.new_definitions || [];
    const newExamples = preview.new_examples || [];
    const nothingNew = newDefinitions.length === 0 && newExamples.length === 0;

    this.displayedEntry = existing;
    this.expanded = true;
    this.slip.classList.remove("is-capturing", "is-expanded");
    this.slip.classList.add("is-expanded");
    this.input.hidden = true;
    const word = el("preview-word");
    word.hidden = false;
    word.textContent = existing.word;
    scaleHeadword(word, existing.word);
    el("slip-pos").textContent = existing.word_type || "";
    el("slip-mean").hidden = true;
    const first = el("slip-example");
    first.replaceChildren();
    first.hidden = true;
    this.more.hidden = true;
    this.more.setAttribute("aria-expanded", "false");
    this.variant.hidden = true;

    const senses = el("slip-senses");
    senses.replaceChildren(
      ...(existing.definitions || []).map((definition) => renderSense(definition, "held")),
      ...newDefinitions.map((definition) => renderSense(definition, "new")),
    );
    senses.hidden = false;
    const examples = el("slip-examples");
    examples.replaceChildren();
    (existing.examples || []).forEach((example) => renderExample(examples, example, "held"));
    newExamples.forEach((example) => renderExample(examples, example, "new"));
    examples.hidden = (existing.examples?.length || 0) + newExamples.length === 0;

    if (nothingNew) {
      this.setRibbon("In your collection", "already complete");
      this.discard.hidden = true;
      el("primary-label").textContent = "Keep what I have";
      this.showMessage(
        `Nothing new — your entry already covers all ${countLabel(preview.definitions?.length || 0, "sense")} the model returned.`,
        { note: true },
      );
    } else {
      const addedCount = newDefinitions.length || newExamples.length;
      const addedKind = newDefinitions.length ? "sense" : "example";
      const added = countLabel(addedCount, addedKind);
      this.setRibbon(
        "Merging into your entry",
        `${addedCount} new ${addedKind}${addedCount === 1 ? "" : "s"}`,
      );
      this.discard.hidden = false;
      this.discard.textContent = "Cancel";
      el("primary-label").textContent = `Add ${added}`;
      const correction = preview.spelling_suggestion
        ? `Corrected to “${preview.word}”. `
        : "";
      this.showMessage(
        `${correction}Your ${countLabel(existing.definitions?.length || 0, "existing sense")} stay exactly as they are.`,
        { note: true },
      );
    }
    this.primary.disabled = false;
  }

  showVariantPreview(preview) {
    const existing = preview.existing_entry;
    this.expanded = false;
    this.renderEntry(preview, preview.variant_word || preview.word);
    this.setRibbon("New, separate entry", "yours is untouched");
    this.discard.hidden = false;
    this.discard.textContent = "Cancel";
    this.variant.hidden = true;
    el("primary-label").textContent = "Keep as a variant";
    this.primary.disabled = false;
    this.showMessage(
      `Filed as a second entry. Your original ${existing.word} keeps its ${countLabel(existing.definitions?.length || 0, "sense")}.`,
      { note: true },
    );
  }

  renderEntry(entry, displayWord) {
    this.displayedEntry = entry;
    this.slip.classList.remove("is-capturing", "is-expanded");
    this.input.hidden = true;
    const word = el("preview-word");
    word.hidden = false;
    word.textContent = displayWord;
    scaleHeadword(word, displayWord);
    el("slip-pos").textContent = entry.word_type || "";
    el("slip-mean").hidden = false;
    el("slip-mean").textContent = entry.definitions?.[0] || "";
    const first = el("slip-example");
    first.hidden = false;
    first.replaceChildren();
    if (entry.examples?.length) renderExample(first, entry.examples[0]);
    el("slip-senses").hidden = true;
    el("slip-examples").hidden = true;

    const extraSenses = Math.max(0, (entry.definitions?.length || 0) - 1);
    const extraExamples = Math.max(0, (entry.examples?.length || 0) - 1);
    const labels = [];
    if (extraSenses) labels.push(`${extraSenses} more sense${extraSenses === 1 ? "" : "s"}`);
    if (extraExamples) labels.push(`${extraExamples} more example${extraExamples === 1 ? "" : "s"}`);
    this.collapsedLabel = labels.join(" · ");
    this.more.hidden = labels.length === 0;
    el("more-label").textContent = this.collapsedLabel;
    this.more.setAttribute("aria-expanded", "false");
  }

  setRibbon(label, note) {
    this.ribbon.hidden = false;
    el("ribbon-label").textContent = label;
    el("ribbon-note").textContent = note;
  }

  dismissToBlank({ preserveMessage = false } = {}) {
    this.input.value = "";
    writeStorage(this.draftKey(), "");
    this.showCapture({ preserveMessage });
  }

  async lookUp(duplicateAction = "reject") {
    if (!navigator.onLine) {
      this.showMessage("Reconnect to Tailscale before looking a word up.");
      return;
    }
    const text = this.pendingDuplicateText || this.input.value;
    // The highlight marks the word this visit put there; asking for another
    // one ends that visit.
    this.justSaved = "";
    this.setBusy(true, "Looking it up…");
    this.showMessage("");
    try {
      const preview = await this.api.request("/api/preview", {
        method: "POST",
        body: JSON.stringify({ text, duplicate_action: duplicateAction }),
      }, { scope: "capture-ai", timeout: 130000 });
      this.showPreview(preview);
    } catch (error) {
      if (error.code === "duplicate_entry" && error.details?.existing_entry) {
        this.showCollected(error.details.existing_entry, this.input.value.trim());
      }
      else if (!ignoreCancelled(error)) this.showMessage(error.message);
    } finally {
      this.setBusy(false);
    }
  }

  async save(useOriginal = false) {
    if (!this.preview) return;
    const preview = this.preview;
    this.setBusy(true, "Saving…");
    this.showMessage("");
    try {
      const saved = await this.api.request("/api/save", {
        method: "POST",
        body: JSON.stringify({ token: preview.token, use_original: useOriginal }),
      }, { scope: "capture-save" });
      this.dismissToBlank({ preserveMessage: true });
      // Remembered by word, not by position: the list is re-fetched after the
      // save and another session can have written above this row.
      this.justSaved = saved.word || "";
      const addedDefinitions = saved.added_definitions || 0;
      const addedExamples = saved.added_examples || 0;
      const mergedAddition = addedDefinitions
        ? countLabel(addedDefinitions, "sense")
        : countLabel(addedExamples, "example");
      this.showMessage(
        saved.action === "merged"
          ? `${saved.word} gained ${mergedAddition}.`
          : (saved.action === "unchanged"
            ? `Nothing changed — ${saved.word} already had those senses.`
            : `${saved.word} is in your collection.`),
        { ok: true },
      );
      await this.onSaved();
    } catch (error) {
      if (!ignoreCancelled(error)) this.showMessage(error.message);
    } finally {
      this.setBusy(false);
    }
  }

  toggleExpanded() {
    if (!this.displayedEntry) return;
    // Measure, mutate, then let CSS settle the new layout and measure again.
    // Reading the settled height rather than scrollHeight matters because the
    // expanded body is flex-sized inside the slip; releasing the inline height
    // afterwards lands on exactly the value we animated to, so nothing snaps.
    const body = el("slip-body");
    const from = body.getBoundingClientRect().height;
    this.applyExpandedState();
    body.style.height = "";
    void body.offsetHeight;
    const to = body.getBoundingClientRect().height;

    body.classList.add("is-animating");
    body.style.opacity = "0";
    body.style.height = `${from}px`;
    void body.offsetHeight;
    body.style.opacity = "1";
    body.style.height = `${to}px`;

    // transitionend is not guaranteed: a zero-duration tween under reduced
    // motion, a hidden tab, or a second tap mid-flight can all swallow it, and
    // leaving `is-animating` behind would pin the body at a stale fixed height.
    // Always release, whichever arrives first.
    const release = () => {
      window.clearTimeout(this.expandTimer);
      body.removeEventListener("transitionend", onEnd);
      body.classList.remove("is-animating");
      body.style.height = "";
    };
    const onEnd = (event) => {
      if (event.propertyName !== "height") return;
      release();
    };
    window.clearTimeout(this.expandTimer);
    body.addEventListener("transitionend", onEnd);
    this.expandTimer = window.setTimeout(release, 420);
  }

  applyExpandedState() {
    this.expanded = !this.expanded;
    this.slip.classList.toggle("is-expanded", this.expanded);
    this.more.setAttribute("aria-expanded", String(this.expanded));
    const senses = el("slip-senses");
    const examples = el("slip-examples");
    const first = el("slip-example");
    if (!this.expanded) {
      senses.hidden = true;
      examples.hidden = true;
      el("slip-mean").hidden = false;
      first.hidden = false;
      el("more-label").textContent = this.collapsedLabel;
      return;
    }
    el("slip-mean").hidden = true;
    first.hidden = true;
    senses.replaceChildren(...this.displayedEntry.definitions.map((definition) => renderSense(definition)));
    senses.hidden = false;
    examples.replaceChildren();
    this.displayedEntry.examples.forEach((example) => renderExample(examples, example));
    examples.hidden = this.displayedEntry.examples.length === 0;
    el("more-label").textContent = "Show less";
  }

  // One busy idiom app-wide: the label states what is happening. The spinner
  // this replaces was hidden under prefers-reduced-motion, which left capture
  // with no visible feedback at all across a request that can run two minutes.
  setBusy(busy, busyLabel = "Working…") {
    const label = el("primary-label");
    if (busy) {
      this.idleLabel = label.textContent;
      this.busyLabel = busyLabel;
      label.textContent = busyLabel;
    } else if (label.textContent === this.busyLabel) {
      // A completed save has already written the next idle label itself.
      label.textContent = this.idleLabel;
    }
    this.primary.classList.toggle("is-loading", busy);
    this.primary.setAttribute("aria-busy", String(busy));
    this.primary.disabled = busy || (
      this.mode === "capture" && (!this.input.value.trim() || !navigator.onLine)
    );
    this.discard.disabled = busy;
    this.variant.disabled = busy;
  }

  wire() {
    this.input.addEventListener("input", () => {
      scaleHeadword(this.input, this.input.value);
      autoGrow(this.input);
      writeStorage(this.draftKey(), this.input.value);
      this.primary.disabled = !this.input.value.trim() || !navigator.onLine;
      this.pendingDuplicateText = "";
    });
    // A size step started on that input event has not landed yet, so the
    // scrollHeight just measured belongs to the previous, larger step. Typing
    // hides this because the next keystroke re-measures at the settled size,
    // but a paste delivers one event and would leave the field stuck tall.
    this.input.addEventListener("transitionend", (event) => {
      if (event.propertyName === "font-size") autoGrow(this.input);
    });
    // The whole blank slip is the writing surface. Without this only the
    // textarea's own line box accepts a tap, which is a 39px target inside a
    // card several times its height.
    this.slip.addEventListener("click", (event) => {
      if (this.mode === "capture" && !event.target.closest("button")) this.input.focus();
    });
    this.input.addEventListener("keydown", (event) => {
      if (event.key === "Enter" && !event.shiftKey) {
        event.preventDefault();
        if (this.mode === "capture" && !this.primary.disabled) this.lookUp();
      }
    });
    this.primary.addEventListener("click", () => {
      if (this.mode === "capture") this.lookUp();
      else if (this.mode === "collected" || this.isNothingNew()) this.dismissToBlank();
      else this.save();
    });
    this.discard.addEventListener("click", () => {
      if (this.mode === "collected") this.lookUp("merge");
      else if (this.preview?.duplicate_action === "merge" || this.preview?.duplicate_action === "variant") {
        this.dismissToBlank();
        this.input.focus();
      } else if (this.preview?.route_recommended) this.onRouteSentence(this.preview.original_input);
      else if (this.preview?.spelling_suggestion) this.save(true);
      else { this.showCapture(); this.input.focus(); }
    });
    this.more.addEventListener("click", () => this.toggleExpanded());
    this.variant.addEventListener("click", () => {
      if (this.mode === "collected") this.lookUp("variant");
    });
  }

  isNothingNew() {
    return this.mode === "preview"
      && this.preview?.duplicate_action === "merge"
      && (this.preview.new_definitions?.length || 0) === 0
      && (this.preview.new_examples?.length || 0) === 0;
  }
}

/* Today in full, then earlier records up to the usual eight rows. The list
   arrives newest first, so the window is a prefix of it. */
function ledgerWindow(entries) {
  const today = dayKey(new Date().toISOString());
  const fromToday = entries.filter((entry) => dayKey(entry.timestamp) === today).length;
  return entries.slice(0, Math.max(fromToday, RECENT_ROWS));
}

function scaleHeadword(node, text) {
  HEADWORD_STEPS.forEach(({ className }) => node.classList.remove(className));
  node.classList.add(HEADWORD_STEPS.find(({ max }) => text.trim().length <= max).className);
}

function autoGrow(node) {
  node.style.height = "auto";
  node.style.height = `${node.scrollHeight}px`;
}

function renderSense(definition, marking = "") {
  const item = document.createElement("li");
  item.appendChild(document.createTextNode(definition));
  if (marking) {
    item.classList.add(`is-${marking}`);
    item.appendChild(renderTag(marking));
  }
  return item;
}

function renderExample(container, example, marking = "") {
  const wrapper = document.createElement("div");
  wrapper.className = "example";
  if (marking) {
    wrapper.classList.add(`is-${marking}`);
    wrapper.appendChild(renderTag(marking));
  }
  const source = document.createElement("p");
  source.className = "source";
  source.textContent = `« ${example.source} »`;
  wrapper.appendChild(source);
  if (example.target) {
    const target = document.createElement("p");
    target.className = "target";
    target.textContent = example.target;
    wrapper.appendChild(target);
  }
  container.appendChild(wrapper);
}

function renderTag(marking) {
  const tag = document.createElement("span");
  tag.className = "tag";
  // "Held" is our word, not the reader's. The tag has to say what it means to
  // the person deciding whether to merge.
  tag.textContent = marking === "new" ? "New" : "In your entry";
  return tag;
}

function countLabel(count, singular) {
  return `${count} ${singular}${count === 1 ? "" : "s"}`;
}
