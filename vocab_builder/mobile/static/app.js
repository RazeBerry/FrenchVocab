const LANGUAGE_STORAGE_KEY = "vocabbuilder-language";
const THEME_STORAGE_KEY = "vocabbuilder-theme";
const INSTALL_TIP_KEY = "vocabbuilder-install-tip-dismissed";
const RETRY_DELAY_MS = 15000;

// Must match --bg in each theme; iOS paints the status bar with this.
const THEME_BACKGROUND = { light: "#efeae3", dark: "#151310" };

// Headword sizes come from the real distribution of the stored collections:
// of 571 French headwords, 87% are <=14 characters and 2% are long expressions.
const HEADWORD_STEPS = [
  { max: 14, className: "hw--s1" },
  { max: 28, className: "hw--s2" },
  { max: Infinity, className: "hw--s3" },
];

const state = {
  language: "fr",
  languageName: "",
  preview: null,
  searchTimer: null,
  retryTimer: null,
  expanded: false,
  collapsedLabel: "",
  total: 0,
};

const reducedMotion = window.matchMedia("(prefers-reduced-motion: reduce)");
const el = (id) => document.getElementById(id);

const slip = el("slip");
const deck = el("deck");
const entryInput = el("entry-input");
const previewWord = el("preview-word");
const primaryButton = el("primary-button");
const discardButton = el("discard-button");
const moreButton = el("more-button");
const formMessage = el("form-message");
const entryList = el("entry-list");
const emptyState = el("empty-state");

/* ------------------------------ helpers ------------------------------ */

// "a French word" but "an English word".
function withArticle(name) {
  return `${/^[aeiou]/i.test(name) ? "an" : "a"} ${name}`;
}

function headwordClass(text) {
  const length = (text || "").trim().length;
  return HEADWORD_STEPS.find((step) => length <= step.max).className;
}

function applyHeadwordScale(node, text) {
  HEADWORD_STEPS.forEach((step) => node.classList.remove(step.className));
  node.classList.add(headwordClass(text));
}

function autoGrow(node) {
  node.style.height = "auto";
  node.style.height = `${node.scrollHeight}px`;
}

function clearChildren(node) {
  while (node.firstChild) node.removeChild(node.firstChild);
}

function setMessage(text, { ok = false } = {}) {
  formMessage.textContent = text;
  formMessage.classList.toggle("is-ok", Boolean(text) && ok);
}

function setLoading(button, loading) {
  button.disabled = loading;
  button.classList.toggle("is-loading", loading);
}

function languagePath(path, language) {
  if (!language) return path;
  const separator = path.includes("?") ? "&" : "?";
  return `${path}${separator}language=${encodeURIComponent(language)}`;
}

async function api(path, options = {}, language = state.language) {
  const response = await fetch(languagePath(path, language), {
    ...options,
    headers: { "Content-Type": "application/json", ...(options.headers || {}) },
  });
  let payload = null;
  try { payload = await response.json(); } catch (_) { /* handled below */ }
  if (!response.ok) {
    const message = payload?.error?.message || "The server could not complete that request.";
    const error = new Error(message);
    error.code = payload?.error?.code;
    throw error;
  }
  return payload;
}

/* ------------------------------ slip states ------------------------------ */

function showCaptureState() {
  state.preview = null;
  state.expanded = false;
  slip.classList.add("is-capturing");
  slip.classList.remove("is-expanded");
  entryInput.hidden = false;
  previewWord.hidden = true;
  discardButton.hidden = true;
  moreButton.hidden = true;
  moreButton.setAttribute("aria-expanded", "false");
  el("slip-senses").hidden = true;
  el("slip-examples").hidden = true;
  clearChildren(el("slip-example"));
  el("slip-mean").textContent = "The meaning will appear here.";
  el("slip-pos").textContent = state.languageName || " ";
  el("primary-label").textContent = "Look it up";
  primaryButton.disabled = !entryInput.value.trim() || !isOnline();
  applyHeadwordScale(entryInput, entryInput.value);
  autoGrow(entryInput);
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

function showPreviewState(preview) {
  state.preview = preview;
  state.expanded = false;
  slip.classList.remove("is-capturing", "is-expanded");
  entryInput.hidden = true;
  previewWord.hidden = false;
  previewWord.textContent = preview.word;
  applyHeadwordScale(previewWord, preview.word);

  el("slip-pos").textContent = preview.word_type || "";
  el("slip-mean").textContent = preview.definitions[0] || "";

  const firstExample = el("slip-example");
  clearChildren(firstExample);
  if (preview.examples.length) renderExample(firstExample, preview.examples[0]);

  // The rest is deferred, never discarded: save still sends everything.
  const extraSenses = Math.max(0, preview.definitions.length - 1);
  const extraExamples = Math.max(0, preview.examples.length - 1);
  if (extraSenses || extraExamples) {
    const parts = [];
    if (extraSenses) parts.push(`${extraSenses} more sense${extraSenses === 1 ? "" : "s"}`);
    if (extraExamples) parts.push(`${extraExamples} more example${extraExamples === 1 ? "" : "s"}`);
    state.collapsedLabel = parts.join(" · ");
    el("more-label").textContent = state.collapsedLabel;
    moreButton.hidden = false;
    moreButton.setAttribute("aria-expanded", "false");
  } else {
    moreButton.hidden = true;
  }

  // A spelling suggestion still needs a way to be refused, so the ghost button
  // becomes the override rather than a plain discard.
  discardButton.hidden = false;
  discardButton.textContent = preview.spelling_suggestion
    ? `Keep "${preview.original_input}"`
    : "Discard";
  el("primary-label").textContent = "Keep it";
  primaryButton.disabled = false;
  setMessage(
    preview.spelling_suggestion
      ? `Corrected to "${preview.word}".`
      : "",
  );
}

function toggleExpanded() {
  const preview = state.preview;
  if (!preview) return;
  state.expanded = !state.expanded;
  slip.classList.toggle("is-expanded", state.expanded);
  moreButton.setAttribute("aria-expanded", String(state.expanded));

  const senses = el("slip-senses");
  const examples = el("slip-examples");
  const firstExample = el("slip-example");

  if (!state.expanded) {
    senses.hidden = true;
    examples.hidden = true;
    el("slip-mean").hidden = false;
    firstExample.hidden = false;
    el("more-label").textContent = state.collapsedLabel;
    applyHeadwordScale(previewWord, preview.word);
    return;
  }

  el("slip-mean").hidden = true;
  firstExample.hidden = true;

  clearChildren(senses);
  preview.definitions.forEach((definition) => {
    const item = document.createElement("li");
    item.textContent = definition;
    senses.appendChild(item);
  });
  senses.hidden = false;

  clearChildren(examples);
  preview.examples.forEach((example) => renderExample(examples, example));
  examples.hidden = !preview.examples.length;

  el("more-label").textContent = "Show less";
}

/* ------------------------------ theme ------------------------------ */

// The inline script in index.html has already stamped <html> before paint;
// this only keeps the status bar colour and the button label in step.
function applyTheme(theme) {
  document.documentElement.dataset.theme = theme;
  el("theme-color").setAttribute("content", THEME_BACKGROUND[theme]);
  el("theme-label").textContent = theme === "dark"
    ? "Switch to light theme"
    : "Switch to dark theme";
}

function currentTheme() {
  return document.documentElement.dataset.theme === "dark" ? "dark" : "light";
}

function toggleTheme() {
  const next = currentTheme() === "dark" ? "light" : "dark";
  try { localStorage.setItem(THEME_STORAGE_KEY, next); } catch (_) { /* private mode */ }
  applyTheme(next);
}

/* ------------------------------ connection ------------------------------ */

function isOnline() {
  return !el("connection").classList.contains("offline");
}

function setConnection(online, label) {
  const node = el("connection");
  node.classList.toggle("online", online);
  node.classList.toggle("offline", !online);
  el("connection-label").textContent = label;
  node.title = online ? label : `${label} — tap to retry`;
  if (!state.preview) primaryButton.disabled = !online || !entryInput.value.trim();
  window.clearTimeout(state.retryTimer);
  if (!online) {
    state.retryTimer = window.setTimeout(() => { loadStatus(); loadRecent(); }, RETRY_DELAY_MS);
  }
}

/* ------------------------------ data ------------------------------ */

function setEntryCount(count) {
  const total = Number(count);
  state.total = total;
  el("entry-count").textContent = total.toLocaleString();
  // The deck behind the slip is the collection; with nothing collected there is
  // no deck to draw.
  deck.classList.toggle("is-empty", total === 0);
}

async function loadCollections() {
  const payload = await api("/api/collections", {}, null);
  const stored = localStorage.getItem(LANGUAGE_STORAGE_KEY);
  const available = new Set(payload.collections.map(({ language }) => language));
  state.language = available.has(stored) ? stored : payload.default_language;

  const container = el("languages");
  clearChildren(container);
  payload.collections.forEach(({ language, language_name: languageName }) => {
    const button = document.createElement("button");
    button.type = "button";
    button.className = "lang";
    button.dataset.lang = language;
    button.setAttribute("aria-pressed", String(language === state.language));
    const name = document.createElement("span");
    name.className = "sr-only";
    name.textContent = languageName;
    button.appendChild(name);
    button.addEventListener("click", () => selectLanguage(language));
    container.appendChild(button);
  });
  document.documentElement.dataset.language = state.language;
}

async function loadStatus() {
  if (!navigator.onLine) {
    setConnection(false, "Offline");
    return;
  }
  const language = state.language;
  try {
    const status = await api("/api/status", {}, language);
    if (language !== state.language) return;
    state.languageName = status.language_name;
    setEntryCount(status.entry_count);
    el("data-file").textContent = status.data_file;
    el("entry-label").textContent = `${status.language_name} word or phrase`;
    entryInput.placeholder = `Type ${withArticle(status.language_name)} word`;
    if (!state.preview) el("slip-pos").textContent = status.language_name;
    setConnection(true, "Private and connected");
  } catch (error) {
    if (language !== state.language) return;
    setConnection(false, "Server unavailable");
    setMessage(error.message);
  }
}

// Longest match first, so "separable verb" does not collapse to "verb" and
// "adjective/noun" does not collapse to "noun".
const TYPE_ABBREVIATIONS = [
  ["separable verb", "v. sep."],
  ["pronominal verb", "v. pron."],
  ["conjunction", "conj."],
  ["expression", "expr."],
  ["adjective", "adj."],
  ["adverb", "adv."],
  ["pronoun", "pron."],
  ["sentence", "sent."],
  ["noun", "n."],
  ["verb", "v."],
];

function abbreviateType(type) {
  const value = (type || "").trim().toLowerCase();
  if (!value || value === "unknown") return "";
  const match = TYPE_ABBREVIATIONS.find(([full]) => value.startsWith(full));
  if (match) return match[1];
  return value.length <= 5 ? value : `${value.slice(0, 4)}.`;
}

// Group accented forms under their base letter, and file each word under the
// character it is actually sorted by, so the dividers never disagree with the
// order the server returned.
function indexLetter(word) {
  const first = (word || "").trim().charAt(0);
  if (!first) return "#";
  const base = first.normalize("NFD").replace(/[̀-ͯ]/g, "").toUpperCase();
  return /[A-Z]/.test(base) ? base : "#";
}

// height:auto is not animatable, so drive an explicit pixel height and hand it
// back to auto once the transition lands; otherwise a later entry with more
// senses would be clipped to the height captured here.
// A forced reflow rather than requestAnimationFrame: it commits the starting
// height synchronously, so the transition cannot be skipped by a frame that
// never arrives (background tabs, and headless browsers under test).
function pinCurrentHeight(detail) {
  void detail.offsetHeight;
}

function collapseDetail(detail) {
  detail.style.height = `${detail.scrollHeight}px`;
  pinCurrentHeight(detail);
  detail.classList.remove("is-open");
  detail.style.height = "0px";
  // Collapsed content stays in the DOM so it can animate, so take it out of the
  // tab order and the accessibility tree by hand.
  detail.inert = true;
}

function expandDetail(detail) {
  detail.inert = false;
  detail.classList.add("is-open");
  const target = detail.scrollHeight;
  detail.style.height = "0px";
  pinCurrentHeight(detail);
  detail.style.height = `${target}px`;

  const settle = (event) => {
    if (event.propertyName !== "height") return;
    detail.removeEventListener("transitionend", settle);
    detail.style.height = "auto";
    // "nearest" does nothing when the entry already fits, so an in-view row
    // never moves; it only rescues one opened near the bottom of the screen.
    detail.scrollIntoView({
      behavior: reducedMotion.matches ? "auto" : "smooth",
      block: "nearest",
    });
  };
  detail.addEventListener("transitionend", settle);
}

function closeOpenRow() {
  const open = entryList.querySelector('.index-row[aria-expanded="true"]');
  if (!open) return;
  open.setAttribute("aria-expanded", "false");
  collapseDetail(open.nextElementSibling);
}

function buildDetail(entry) {
  const detail = document.createElement("div");
  detail.className = "index-detail";
  detail.inert = true;
  const inner = document.createElement("div");
  inner.className = "index-detail-inner";
  detail.appendChild(inner);

  if (entry.word_type) {
    const type = document.createElement("p");
    type.className = "full-type";
    const senses = entry.definitions?.length || 0;
    type.textContent = senses > 1
      ? `${entry.word_type} · ${senses} senses`
      : entry.word_type;
    inner.appendChild(type);
  }

  if (entry.definitions?.length) {
    const senses = document.createElement("ol");
    entry.definitions.forEach((definition) => {
      const item = document.createElement("li");
      item.textContent = definition;
      senses.appendChild(item);
    });
    inner.appendChild(senses);
  }

  (entry.examples || []).forEach((example) => renderExample(inner, example));
  return detail;
}

function renderEntries(entries, { grouped = false } = {}) {
  clearChildren(entryList);
  closeOpenRow();
  emptyState.hidden = entries.length > 0;

  let letter = null;
  entries.forEach((entry) => {
    if (grouped) {
      const next = indexLetter(entry.word);
      if (next !== letter) {
        letter = next;
        const divider = document.createElement("p");
        divider.className = "index-letter";
        divider.textContent = letter;
        entryList.appendChild(divider);
      }
    }

    const row = document.createElement("button");
    row.type = "button";
    row.className = "index-row";
    row.setAttribute("aria-expanded", "false");

    const word = document.createElement("span");
    word.className = "index-word";
    word.textContent = entry.word;

    const type = document.createElement("span");
    type.className = "index-type";
    type.textContent = abbreviateType(entry.word_type);

    const gloss = document.createElement("span");
    gloss.className = "index-gloss";
    gloss.textContent = entry.definitions?.[0] || "";

    row.append(word, type, gloss);
    const detail = buildDetail(entry);

    row.addEventListener("click", () => {
      const isOpen = row.getAttribute("aria-expanded") === "true";
      closeOpenRow();
      if (isOpen) return;
      row.setAttribute("aria-expanded", "true");
      expandDetail(detail);
    });

    entryList.append(row, detail);
  });

  const foot = el("index-foot");
  if (!entries.length) {
    foot.hidden = true;
    return;
  }
  // The collection total already sits in the top bar, so this line only
  // qualifies what is on screen. It also avoids racing the status request.
  foot.hidden = false;
  foot.textContent = grouped
    ? `${entries.length} match${entries.length === 1 ? "" : "es"} · tap to open`
    : `${entries.length} most recent · tap to open`;
}

async function loadRecent() {
  const language = state.language;
  try {
    const entries = await api("/api/recent?limit=8", {}, language);
    if (language === state.language) renderEntries(entries);
  } catch (_) { /* the connection dot already reports failures */ }
}

async function selectLanguage(language) {
  if (language === state.language) return;
  state.language = language;
  localStorage.setItem(LANGUAGE_STORAGE_KEY, language);
  document.documentElement.dataset.language = language;
  document.querySelectorAll(".lang").forEach((button) => {
    button.setAttribute("aria-pressed", String(button.dataset.lang === language));
  });
  window.clearTimeout(state.searchTimer);
  entryInput.value = "";
  el("search-input").value = "";
  setMessage("");
  showCaptureState();
  renderEntries([]);
  await Promise.all([loadStatus(), loadRecent()]);
}

/* ------------------------------ actions ------------------------------ */

async function lookUp() {
  if (!navigator.onLine) {
    setMessage("Reconnect to Tailscale before looking a word up.");
    return;
  }
  setMessage("");
  setLoading(primaryButton, true);
  const language = state.language;
  try {
    const preview = await api("/api/preview", {
      method: "POST",
      body: JSON.stringify({ text: entryInput.value }),
    }, language);
    if (language === state.language) showPreviewState(preview);
  } catch (error) {
    setMessage(error.message);
  } finally {
    setLoading(primaryButton, false);
  }
}

async function keepIt(useOriginal = false) {
  const preview = state.preview;
  if (!preview) return;
  setLoading(primaryButton, true);
  setMessage("");
  try {
    const saved = await api("/api/save", {
      method: "POST",
      body: JSON.stringify({ token: preview.token, use_original: useOriginal }),
    }, preview.language);
    if (state.language !== preview.language) return;
    setEntryCount(saved.entry_count);
    entryInput.value = "";
    showCaptureState();
    setMessage(`${saved.word} is in your collection.`, { ok: true });
    await loadRecent();
  } catch (error) {
    setMessage(error.message);
  } finally {
    setLoading(primaryButton, false);
  }
}

/* ------------------------------ wiring ------------------------------ */

entryInput.addEventListener("input", () => {
  applyHeadwordScale(entryInput, entryInput.value);
  autoGrow(entryInput);
  primaryButton.disabled = !entryInput.value.trim() || !isOnline();
});

entryInput.addEventListener("keydown", (event) => {
  if (event.key === "Enter" && !event.shiftKey) {
    event.preventDefault();
    if (!primaryButton.disabled) lookUp();
  }
});

primaryButton.addEventListener("click", () => {
  if (state.preview) keepIt(); else lookUp();
});

discardButton.addEventListener("click", () => {
  // With a spelling suggestion on screen this button saves the original instead.
  if (state.preview?.spelling_suggestion) {
    keepIt(true);
    return;
  }
  showCaptureState();
  setMessage("");
  entryInput.focus();
});

moreButton.addEventListener("click", toggleExpanded);

el("theme-toggle").addEventListener("click", toggleTheme);

el("connection").addEventListener("click", () => {
  if (isOnline()) return;
  el("connection-label").textContent = "Reconnecting";
  loadStatus();
  loadRecent();
});

el("search-input").addEventListener("input", (event) => {
  window.clearTimeout(state.searchTimer);
  const query = event.target.value.trim();
  const language = state.language;
  state.searchTimer = window.setTimeout(async () => {
    if (!query) {
      await loadRecent();
      return;
    }
    try {
      const entries = await api(
        `/api/search?q=${encodeURIComponent(query)}&limit=20`,
        {},
        language,
      );
      if (language === state.language && event.target.value.trim() === query) {
        // Search results come back alphabetical, so the letter dividers are true.
        renderEntries(entries, { grouped: true });
      }
    } catch (error) {
      if (language === state.language) setMessage(error.message);
    }
  }, 220);
});

window.addEventListener("online", () => { loadStatus(); loadRecent(); });
window.addEventListener("offline", () => setConnection(false, "Offline"));
document.addEventListener("visibilitychange", () => {
  if (document.visibilityState !== "visible") return;
  loadStatus();
  if (!el("search-input").value.trim()) loadRecent();
});

const installTip = el("install-tip");
const standalone = window.matchMedia("(display-mode: standalone)").matches || window.navigator.standalone;
// The tip describes Safari's share sheet, so only offer it where that flow exists.
const iosDevice = /iPad|iPhone|iPod/.test(navigator.userAgent)
  || (navigator.platform === "MacIntel" && navigator.maxTouchPoints > 1);
const iosSafari = iosDevice && !/CriOS|FxiOS|EdgiOS|OPiOS/.test(navigator.userAgent);
if (iosSafari && !standalone && !localStorage.getItem(INSTALL_TIP_KEY)) {
  window.setTimeout(() => { installTip.hidden = false; }, 1200);
}
el("dismiss-install").addEventListener("click", () => {
  installTip.hidden = true;
  localStorage.setItem(INSTALL_TIP_KEY, "1");
});

if ("serviceWorker" in navigator) {
  navigator.serviceWorker.register("/service-worker.js").catch(() => {});
}

async function bootstrap() {
  applyTheme(currentTheme());
  showCaptureState();
  try {
    await loadCollections();
    await Promise.all([loadStatus(), loadRecent()]);
  } catch (error) {
    setConnection(false, "Server unavailable");
    setMessage(error.message);
  }
}

bootstrap();
