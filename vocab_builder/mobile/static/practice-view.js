import { el, ignoreCancelled, makeButton, paragraph, setBusy, setMessage } from "./ui.js";

export class PracticeView {
  constructor(api, onChanged) {
    this.api = api;
    this.onChanged = onChanged;
    this.loaded = false;
    this.mode = "use_words";
    this.prompt = null;
    this.usedKeys = [];
    this.sessionId = null;
    this.message = el("practice-message");
    this.wire();
  }

  reset() {
    this.loaded = false;
    this.prompt = null;
    this.usedKeys = [];
    this.sessionId = null;
    el("practice-card").hidden = true;
    el("practice-feedback").hidden = true;
    el("practice-next").hidden = true;
    setMessage(this.message, "");
  }

  async activate() {
    if (this.loaded) return;
    await this.refresh();
    this.loaded = true;
  }

  async refreshIfLoaded() { if (this.loaded) await this.refresh(); }

  async refresh() {
    try {
      const status = await this.api.request("/api/practice", {}, { scope: "practice-status" });
      if (!status.available) {
        el("practice-debt").textContent = "Composition practice is disabled for this collection.";
        el("practice-modes").replaceChildren();
        return;
      }
      const noun = status.debt_count === 1 ? "word" : "words";
      const attempts = status.set_size === 1 ? "attempt" : "attempts";
      el("practice-debt").textContent = `${status.debt_count} ${noun} still waiting to be produced · ${status.set_size} ${attempts} per set.`;
      this.renderModes(status.modes);
    } catch (error) {
      if (!ignoreCancelled(error)) setMessage(this.message, error.message);
    }
  }

  renderModes(modes) {
    const container = el("practice-modes");
    container.replaceChildren();
    modes.forEach(({ id, label }) => {
      const button = makeButton(label, id, id === this.mode);
      button.className = "mode-button";
      button.addEventListener("click", () => {
        this.mode = id;
        container.querySelectorAll("button").forEach((item) => {
          item.setAttribute("aria-pressed", String(item === button));
        });
        this.newPrompt();
      });
      container.appendChild(button);
    });
  }

  async newPrompt() {
    setMessage(this.message, "");
    el("practice-feedback").hidden = true;
    el("practice-next").hidden = true;
    try {
      const prompt = await this.api.request("/api/practice/prompt", {
        method: "POST",
        body: JSON.stringify({
          mode: this.mode,
          exclude_keys: this.usedKeys,
          session_id: this.sessionId,
        }),
      }, { scope: "practice-prompt" });
      this.prompt = prompt;
      this.sessionId = prompt.session_id;
      prompt.words.forEach((word) => {
        if (!this.usedKeys.includes(word.key)) this.usedKeys.push(word.key);
      });
      this.renderPrompt(prompt);
    } catch (error) {
      if (!ignoreCancelled(error)) setMessage(this.message, error.message);
    }
  }

  renderPrompt(prompt) {
    el("practice-mode-label").textContent = prompt.mode === "reverse" ? "Recall" : "Use these words";
    const body = el("practice-prompt");
    body.replaceChildren();
    if (prompt.mode === "reverse") {
      body.append(
        paragraph("practice-source", prompt.source_english),
        paragraph("practice-instruction", `Write a natural translation using “${prompt.words[0].word}”.`),
      );
    } else {
      const words = document.createElement("div");
      words.className = "target-words";
      prompt.words.forEach((word) => {
        const card = document.createElement("div");
        card.append(
          paragraph("target-word", word.word),
          paragraph("target-definition", `${word.word_type || "Unknown"} · ${word.first_definition || "No definition"}`),
        );
        words.appendChild(card);
      });
      body.append(
        words,
        paragraph("practice-instruction", "Write a natural passage that uses every target word."),
      );
    }
    el("practice-input").value = "";
    el("practice-card").hidden = false;
    el("practice-card").scrollIntoView({ behavior: "smooth", block: "nearest" });
  }

  async grade() {
    const text = el("practice-input").value.trim();
    if (!text) { setMessage(this.message, "Write your answer before asking the coach."); return; }
    const button = el("practice-submit");
    setBusy(button, true, "Coaching…");
    try {
      const feedback = await this.api.request("/api/practice/grade", {
        method: "POST",
        body: JSON.stringify({ token: this.prompt.token, text }),
      }, { scope: "practice-ai", timeout: 130000 });
      this.renderFeedback(feedback);
      el("practice-next").hidden = false;
      await this.onChanged();
    } catch (error) {
      if (!ignoreCancelled(error)) setMessage(this.message, error.message);
    } finally {
      setBusy(button, false);
    }
  }

  renderFeedback(feedback) {
    const card = el("practice-feedback");
    card.replaceChildren();
    card.append(
      paragraph("eyebrow", "Coach’s version"),
      paragraph("corrected-text", feedback.corrected_text || "No corrected text returned."),
    );
    if (feedback.english_gloss) card.append(paragraph("english-gloss", feedback.english_gloss));
    const verdicts = document.createElement("div");
    verdicts.className = "verdicts";
    Object.entries(feedback.word_verdicts || {}).forEach(([word, verdict]) => {
      const chip = paragraph(`verdict verdict-${verdict}`, `${word} · ${verdict.replace("_", " ")}`);
      verdicts.appendChild(chip);
    });
    if (verdicts.childElementCount) card.appendChild(verdicts);
    if (feedback.corrections?.length) {
      const list = document.createElement("div");
      list.className = "corrections";
      feedback.corrections.forEach((correction) => {
        const item = document.createElement("article");
        item.append(
          paragraph("correction-change", `${correction.original} → ${correction.replacement}`),
          paragraph("correction-why", correction.why),
        );
        list.appendChild(item);
      });
      card.appendChild(list);
    }
    if (feedback.register) card.append(paragraph("register", `Register: ${feedback.register}`));
    if (feedback.unknown_candidates?.length) {
      card.append(paragraph("note", `Worth collecting next: ${feedback.unknown_candidates.map(({ word, gloss }) => gloss ? `${word} (${gloss})` : word).join(", ")}`));
    }
    if (feedback.history_pending) card.append(paragraph("note", "The feedback is safe; its history record is queued for automatic repair."));
    card.hidden = false;
    card.scrollIntoView({ behavior: "smooth", block: "nearest" });
    el("practice-card").hidden = true;
  }

  wire() {
    el("practice-submit").addEventListener("click", () => this.grade());
    el("practice-next").addEventListener("click", () => this.newPrompt());
  }
}
