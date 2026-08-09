import { renderEntries } from "./entry-list.js";
import { el, ignoreCancelled, readStorage, setMessage, writeStorage } from "./ui.js";

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
    this.preview = null;
    this.language = "fr";
    this.languageName = "";
    this.expanded = false;
    this.pendingDuplicateText = "";
    this.slip = el("slip");
    this.input = el("entry-input");
    this.primary = el("primary-button");
    this.discard = el("discard-button");
    this.more = el("more-button");
    this.message = el("form-message");
    this.duplicateActions = el("duplicate-actions");
    this.wire();
    this.showCapture();
  }

  draftKey() { return `vocabbuilder-capture-draft-${this.language}`; }

  setLanguage(status) {
    const changed = this.language !== status.language;
    this.language = status.language;
    this.languageName = status.language_name;
    el("entry-label").textContent = `${status.language_name} word or phrase`;
    if (changed) {
      this.input.value = readStorage(this.draftKey());
      this.showCapture();
    } else if (!this.preview) {
      el("slip-pos").textContent = status.language_name;
    }
  }

  reset() {
    this.preview = null;
    this.pendingDuplicateText = "";
    this.input.value = "";
    this.showCapture();
    renderEntries(el("recent-list"), []);
    el("recent-empty").hidden = false;
  }

  async activate() { await this.refresh(); }

  async refresh() {
    try {
      const entries = await this.api.request("/api/recent?limit=8", {}, { scope: "recent" });
      renderEntries(el("recent-list"), entries);
      el("recent-empty").hidden = entries.length > 0;
    } catch (error) {
      if (!ignoreCancelled(error)) this.showMessage(error.message);
    }
  }

  showMessage(text, options) { setMessage(this.message, text, options); }

  showCapture({ preserveMessage = false } = {}) {
    this.preview = null;
    this.expanded = false;
    this.pendingDuplicateText = "";
    this.slip.classList.add("is-capturing");
    this.slip.classList.remove("is-expanded");
    this.input.hidden = false;
    el("preview-word").hidden = true;
    this.discard.hidden = true;
    this.more.hidden = true;
    this.duplicateActions.hidden = true;
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
    this.preview = preview;
    this.expanded = false;
    this.duplicateActions.hidden = true;
    this.slip.classList.remove("is-capturing", "is-expanded");
    this.input.hidden = true;
    const word = el("preview-word");
    word.hidden = false;
    word.textContent = preview.word;
    scaleHeadword(word, preview.word);
    el("slip-pos").textContent = preview.word_type || "";
    el("slip-mean").textContent = preview.definitions?.[0] || "";
    const first = el("slip-example");
    first.replaceChildren();
    if (preview.examples?.length) renderExample(first, preview.examples[0]);

    const extraSenses = Math.max(0, (preview.definitions?.length || 0) - 1);
    const extraExamples = Math.max(0, (preview.examples?.length || 0) - 1);
    const labels = [];
    if (extraSenses) labels.push(`${extraSenses} more sense${extraSenses === 1 ? "" : "s"}`);
    if (extraExamples) labels.push(`${extraExamples} more example${extraExamples === 1 ? "" : "s"}`);
    this.collapsedLabel = labels.join(" · ");
    this.more.hidden = labels.length === 0;
    el("more-label").textContent = this.collapsedLabel;
    this.more.setAttribute("aria-expanded", "false");
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
      : (preview.duplicate_action === "merge" ? "Merge senses" : "Keep it");
    this.primary.disabled = false;
    this.showMessage(
      preview.spelling_suggestion ? `Corrected to “${preview.word}”.` : "",
      { note: true },
    );
  }

  showDuplicate(error) {
    this.pendingDuplicateText = this.input.value.trim();
    this.duplicateActions.hidden = false;
    const existing = error.details?.existing_entry;
    if (existing) {
      el("slip-pos").textContent = existing.word_type || "Already collected";
      el("slip-mean").textContent = existing.definitions?.[0] || "Already collected";
    }
    this.showMessage(`${error.message} Add genuinely new senses, keep a separate variant, or leave it unchanged.`);
  }

  async lookUp(duplicateAction = "reject") {
    if (!navigator.onLine) {
      this.showMessage("Reconnect to Tailscale before looking a word up.");
      return;
    }
    const text = this.pendingDuplicateText || this.input.value;
    this.setBusy(true, "Looking it up…");
    this.showMessage("");
    try {
      const preview = await this.api.request("/api/preview", {
        method: "POST",
        body: JSON.stringify({ text, duplicate_action: duplicateAction }),
      }, { scope: "capture-ai", timeout: 130000 });
      this.showPreview(preview);
    } catch (error) {
      if (error.code === "duplicate_entry") this.showDuplicate(error);
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
      this.input.value = "";
      writeStorage(this.draftKey(), "");
      this.showCapture({ preserveMessage: true });
      this.showMessage(
        saved.action === "merged"
          ? `${saved.word} now includes the new senses.`
          : `${saved.word} is in your collection.`,
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
    if (!this.preview) return;
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
    senses.replaceChildren(...this.preview.definitions.map((definition) => {
      const item = document.createElement("li"); item.textContent = definition; return item;
    }));
    senses.hidden = false;
    examples.replaceChildren();
    this.preview.examples.forEach((example) => renderExample(examples, example));
    examples.hidden = this.preview.examples.length === 0;
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
    this.primary.disabled = busy || (!this.preview && !this.input.value.trim());
  }

  wire() {
    this.input.addEventListener("input", () => {
      scaleHeadword(this.input, this.input.value);
      autoGrow(this.input);
      writeStorage(this.draftKey(), this.input.value);
      this.primary.disabled = !this.input.value.trim() || !navigator.onLine;
      this.duplicateActions.hidden = true;
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
      if (!this.preview && !event.target.closest("button")) this.input.focus();
    });
    this.input.addEventListener("keydown", (event) => {
      if (event.key === "Enter" && !event.shiftKey) {
        event.preventDefault();
        if (!this.primary.disabled) this.lookUp();
      }
    });
    this.primary.addEventListener("click", () => {
      if (this.preview) this.save();
      else this.lookUp();
    });
    this.discard.addEventListener("click", () => {
      if (this.preview?.route_recommended) this.onRouteSentence(this.preview.original_input);
      else if (this.preview?.spelling_suggestion) this.save(true);
      else { this.showCapture(); this.input.focus(); }
    });
    this.more.addEventListener("click", () => this.toggleExpanded());
    el("merge-button").addEventListener("click", () => this.lookUp("merge"));
    el("variant-button").addEventListener("click", () => this.lookUp("variant"));
  }
}

function scaleHeadword(node, text) {
  HEADWORD_STEPS.forEach(({ className }) => node.classList.remove(className));
  node.classList.add(HEADWORD_STEPS.find(({ max }) => text.trim().length <= max).className);
}

function autoGrow(node) {
  node.style.height = "auto";
  node.style.height = `${node.scrollHeight}px`;
}

function renderExample(container, example) {
  const wrapper = document.createElement("div");
  wrapper.className = "example";
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
