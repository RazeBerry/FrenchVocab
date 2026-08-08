const LANGUAGE_STORAGE_KEY = "vocabbuilder-language";
const RETRY_DELAY_MS = 15000;
const state = { language: "fr", preview: null, searchTimer: null, retryTimer: null };
const reducedMotion = window.matchMedia("(prefers-reduced-motion: reduce)");

const el = (id) => document.getElementById(id);
const captureForm = el("capture-form");
const entryInput = el("entry-input");
const previewButton = el("preview-button");
const saveButton = el("save-button");
const previewCard = el("preview-card");
const successCard = el("success-card");
const formMessage = el("form-message");
const entryList = el("entry-list");
const emptyState = el("empty-state");

// "a French word" but "an English word" — the language list is user-visible copy.
function withArticle(name) {
  return `${/^[aeiou]/i.test(name) ? "an" : "a"} ${name}`;
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

async function loadCollections() {
  const payload = await api("/api/collections", {}, null);
  const select = el("language-select");
  const stored = localStorage.getItem(LANGUAGE_STORAGE_KEY);
  const available = new Set(payload.collections.map(({ language }) => language));
  state.language = available.has(stored) ? stored : payload.default_language;

  clearChildren(select);
  payload.collections.forEach(({ language, language_name: languageName }) => {
    const option = document.createElement("option");
    option.value = language;
    option.textContent = languageName;
    select.appendChild(option);
  });
  select.value = state.language;
}

function setLoading(button, loading) {
  button.disabled = loading;
  button.classList.toggle("is-loading", loading);
}

function setConnection(online, label) {
  const node = el("connection");
  node.classList.toggle("online", online);
  node.classList.toggle("offline", !online);
  el("connection-label").textContent = label;
  node.title = online ? "" : "Tap to retry";
  previewButton.disabled = !online;
  window.clearTimeout(state.retryTimer);
  if (!online) {
    state.retryTimer = window.setTimeout(() => { loadStatus(); loadRecent(); }, RETRY_DELAY_MS);
  }
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
    setEntryCount(status.entry_count);
    el("data-file").textContent = status.data_file;
    el("active-language").textContent = status.language_name;
    el("entry-label").textContent = `${status.language_name} word or phrase`;
    entryInput.placeholder = `Type ${withArticle(status.language_name)} word or phrase…`;
    setConnection(true, "Private & connected");
  } catch (error) {
    if (language !== state.language) return;
    setConnection(false, "Server unavailable");
    formMessage.textContent = error.message;
  }
}

function clearChildren(node) {
  while (node.firstChild) node.removeChild(node.firstChild);
}

function setEntryCount(count) {
  const total = Number(count);
  el("entry-count").textContent = total.toLocaleString();
  el("entry-noun").textContent = total === 1 ? "entry" : "entries";
}

function renderPreview(preview) {
  state.preview = preview;
  successCard.classList.add("hidden");
  el("preview-word").textContent = preview.word;
  el("preview-type").textContent = preview.word_type;
  el("preview-kind").textContent = preview.input_type === "word" ? "Word preview" : "Phrase preview";

  const correctionRow = el("correction-row");
  if (preview.spelling_suggestion) {
    correctionRow.classList.remove("hidden");
    el("suggested-word").textContent = preview.spelling_suggestion;
    el("use-suggestion").checked = true;
  } else {
    correctionRow.classList.add("hidden");
  }

  const definitions = el("preview-definitions");
  clearChildren(definitions);
  preview.definitions.forEach((definition) => {
    const item = document.createElement("li");
    item.textContent = definition;
    definitions.appendChild(item);
  });

  const examples = el("preview-examples");
  clearChildren(examples);
  const examplesSection = el("examples-section");
  examplesSection.classList.toggle("hidden", !preview.examples.length);
  preview.examples.forEach(({ source, target }) => {
    const wrapper = document.createElement("div");
    wrapper.className = "example";
    const sourceNode = document.createElement("p");
    sourceNode.textContent = source;
    const targetNode = document.createElement("p");
    targetNode.className = "translation";
    targetNode.textContent = target;
    wrapper.append(sourceNode, targetNode);
    examples.appendChild(wrapper);
  });

  previewCard.classList.remove("hidden");
  previewCard.scrollIntoView({
    behavior: reducedMotion.matches ? "auto" : "smooth",
    block: "start",
  });
}

function hidePreview() {
  state.preview = null;
  previewCard.classList.add("hidden");
}

captureForm.addEventListener("submit", async (event) => {
  event.preventDefault();
  formMessage.textContent = "";
  successCard.classList.add("hidden");
  hidePreview();
  if (!navigator.onLine) {
    formMessage.textContent = "Reconnect to Tailscale before creating an entry.";
    return;
  }
  setLoading(previewButton, true);
  const language = state.language;
  try {
    const preview = await api("/api/preview", {
      method: "POST",
      body: JSON.stringify({ text: entryInput.value }),
    }, language);
    if (language === state.language) renderPreview(preview);
  } catch (error) {
    formMessage.textContent = error.message;
  } finally {
    setLoading(previewButton, false);
  }
});

el("discard-button").addEventListener("click", () => {
  hidePreview();
  entryInput.focus();
});

saveButton.addEventListener("click", async () => {
  if (!state.preview) return;
  const preview = state.preview;
  setLoading(saveButton, true);
  formMessage.textContent = "";
  try {
    const hasSuggestion = Boolean(preview.spelling_suggestion);
    const useOriginal = hasSuggestion && !el("use-suggestion").checked;
    const saved = await api("/api/save", {
      method: "POST",
      body: JSON.stringify({ token: preview.token, use_original: useOriginal }),
    }, preview.language);
    if (state.language !== preview.language) return;
    el("saved-word").textContent = saved.word;
    setEntryCount(saved.entry_count);
    hidePreview();
    successCard.classList.remove("hidden");
    entryInput.value = "";
    entryInput.focus();
    await loadRecent();
  } catch (error) {
    formMessage.textContent = error.message;
  } finally {
    setLoading(saveButton, false);
  }
});

function renderEntries(entries) {
  clearChildren(entryList);
  emptyState.classList.toggle("hidden", entries.length > 0);
  entries.forEach((entry) => {
    const wrapper = document.createElement("article");
    wrapper.className = "entry-item";
    const meta = document.createElement("div");
    meta.className = "entry-meta";
    const word = document.createElement("strong");
    word.className = "entry-word";
    word.textContent = entry.word;
    const type = document.createElement("span");
    type.className = "entry-type";
    type.textContent = entry.word_type || "";
    meta.append(word, type);
    wrapper.appendChild(meta);
    if (entry.definitions?.length) {
      const definition = document.createElement("p");
      definition.className = "entry-definition";
      definition.textContent = entry.definitions[0];
      wrapper.appendChild(definition);
    }
    entryList.appendChild(wrapper);
  });
}

async function loadRecent() {
  const language = state.language;
  try {
    const entries = await api("/api/recent?limit=8", {}, language);
    if (language === state.language) renderEntries(entries);
  } catch (_) { /* status surface already reports connection failures */ }
}

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
        renderEntries(entries);
      }
    } catch (error) {
      if (language === state.language) formMessage.textContent = error.message;
    }
  }, 220);
});

el("language-select").addEventListener("change", async (event) => {
  state.language = event.target.value;
  localStorage.setItem(LANGUAGE_STORAGE_KEY, state.language);
  window.clearTimeout(state.searchTimer);
  hidePreview();
  successCard.classList.add("hidden");
  formMessage.textContent = "";
  entryInput.value = "";
  el("search-input").value = "";
  renderEntries([]);
  await Promise.all([loadStatus(), loadRecent()]);
  entryInput.focus();
});

window.addEventListener("online", () => { loadStatus(); loadRecent(); });
window.addEventListener("offline", () => setConnection(false, "Offline"));

el("connection").addEventListener("click", () => {
  if (el("connection").classList.contains("online")) return;
  el("connection-label").textContent = "Reconnecting";
  loadStatus();
  loadRecent();
});

const installTip = el("install-tip");
const standalone = window.matchMedia("(display-mode: standalone)").matches || window.navigator.standalone;
// The tip describes Safari's share sheet, so only offer it where that flow exists.
const iosDevice = /iPad|iPhone|iPod/.test(navigator.userAgent)
  || (navigator.platform === "MacIntel" && navigator.maxTouchPoints > 1);
const iosSafari = iosDevice && !/CriOS|FxiOS|EdgiOS|OPiOS/.test(navigator.userAgent);
if (iosSafari && !standalone && !localStorage.getItem("vocabbuilder-install-tip-dismissed")) {
  window.setTimeout(() => installTip.classList.remove("hidden"), 1200);
}
el("dismiss-install").addEventListener("click", () => {
  installTip.classList.add("hidden");
  localStorage.setItem("vocabbuilder-install-tip-dismissed", "1");
});

if ("serviceWorker" in navigator) {
  navigator.serviceWorker.register("/service-worker.js").catch(() => {});
}

async function bootstrap() {
  try {
    await loadCollections();
    await Promise.all([loadStatus(), loadRecent()]);
  } catch (error) {
    setConnection(false, "Server unavailable");
    formMessage.textContent = error.message;
  }
}

bootstrap();
