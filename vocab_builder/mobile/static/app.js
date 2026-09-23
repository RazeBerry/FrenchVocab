import { ApiClient, StaleRequestError } from "./api.js";
import { CaptureView } from "./capture-view.js";
import { LibraryView } from "./library-view.js";
import { TranslationView } from "./translation-view.js";
import { PracticeView } from "./practice-view.js";
import { ToolsView } from "./tools-view.js";
import { el, languageButton, readStorage, trackKeyboardInset, writeStorage } from "./ui.js";

const LANGUAGE_KEY = "vocabbuilder-language";
const THEME_KEY = "vocabbuilder-theme";
const INSTALL_TIP_KEY = "vocabbuilder-install-tip-dismissed";
const THEME_BACKGROUND = { light: "#efeae3", dark: "#151310" };

const state = {
  language: "fr",
  languageName: "",
  activeView: "capture",
  retryTimer: null,
};

const api = new ApiClient(() => state.language);
const views = {};
/* Each collection's last status, painted at once on a switch while the fresh
   one is a round trip away. Display only; nothing is decided from it. */
const statusCache = new Map();

function currentTheme() {
  return document.documentElement.dataset.theme === "dark" ? "dark" : "light";
}

function applyTheme(theme) {
  document.documentElement.dataset.theme = theme;
  el("theme-color").setAttribute("content", THEME_BACKGROUND[theme]);
  el("theme-label").textContent = theme === "dark"
    ? "Switch to light theme"
    : "Switch to dark theme";
}

function setConnection(online, label) {
  const node = el("connection");
  node.classList.toggle("online", online);
  node.classList.toggle("offline", !online);
  el("connection-label").textContent = label;
  node.title = online ? label : `${label} — tap to retry`;
  window.clearTimeout(state.retryTimer);
  if (!online) state.retryTimer = window.setTimeout(refresh, 15000);
}

function setEntryCount(count) {
  const total = Number(count || 0);
  el("entry-count").textContent = total.toLocaleString();
  el("entry-noun").textContent = total === 1 ? "word" : "words";
  el("deck").classList.toggle("is-empty", total === 0);
}

async function loadCollections() {
  const payload = await api.request("/api/collections", {}, {
    language: null,
    scope: "collections",
  });
  const available = new Set(payload.collections.map(({ language }) => language));
  const stored = readStorage(LANGUAGE_KEY);
  state.language = available.has(stored) ? stored : payload.default_language;

  const container = el("languages");
  container.replaceChildren();
  payload.collections.forEach(({ language, language_name: name }) => {
    const button = languageButton(language, name, language === state.language);
    button.addEventListener("click", () => selectLanguage(language));
    container.appendChild(button);
  });
  document.documentElement.dataset.language = state.language;
  return payload.collections.map(({ language }) => language);
}

function applyStatus(status) {
  state.languageName = status.language_name;
  setEntryCount(status.entry_count);
  el("data-file").textContent = status.data_file;
  views.capture.setLanguage(status);
  document.documentElement.dataset.translation = String(status.supports_translation);
  const translateTab = document.querySelector('.tab[data-tab="translate"]');
  translateTab.hidden = !status.supports_translation;
}

async function loadStatus() {
  if (!navigator.onLine) {
    setConnection(false, "Offline");
    return null;
  }
  const language = state.language;
  try {
    const status = await api.request("/api/status", {}, { scope: "status" });
    if (language !== state.language) return null;
    statusCache.set(language, status);
    applyStatus(status);
    if (!status.supports_translation && state.activeView === "translate") {
      await showView("capture");
    }
    setConnection(true, status.sync_pending
      ? `Connected · repairing ${status.sync_pending}`
      : "Private and connected");
    return status;
  } catch (error) {
    if (error instanceof StaleRequestError || error.code === "request_aborted") return null;
    setConnection(false, "Server unavailable");
    views.capture.showMessage(error.message);
    return null;
  }
}

async function dataChanged() {
  await Promise.allSettled([
    loadStatus(),
    views.capture.refresh(),
    views.library.refreshIfLoaded(),
    views.translate.refreshIfLoaded(),
    views.practice.refreshIfLoaded(),
    views.tools.refreshIfLoaded(),
  ]);
}

async function selectLanguage(language) {
  if (language === state.language) return;
  api.abortAll();
  state.language = language;
  writeStorage(LANGUAGE_KEY, language);
  document.documentElement.dataset.language = language;
  document.querySelectorAll(".lang").forEach((button) => {
    button.setAttribute("aria-pressed", String(button.dataset.lang === language));
  });
  // Paint the pressed collection before rendering it: its rows in the same
  // task held back the tap's own feedback. A later tap supersedes this one.
  await new Promise((resolve) => requestAnimationFrame(() => setTimeout(resolve, 0)));
  if (state.language !== language) return;
  Object.values(views).forEach((view) => view.reset?.());
  const known = statusCache.get(language);
  if (known) applyStatus(known);
  // The view paints from memory beside the status request, not after it. Only
  // the translator waits, since status may close it (English has none), and
  // capture's refresh is already one of the two.
  const view = state.activeView;
  const beside = view === "capture" || view === "translate" ? null : views[view].activate?.();
  await Promise.allSettled([loadStatus(), views.capture.refresh(), beside]);
  if (view === "translate" && state.activeView === "translate") await views.translate.activate();
}

async function showView(name) {
  state.activeView = name;
  document.querySelectorAll(".view").forEach((section) => {
    const active = section.dataset.view === name;
    section.hidden = !active;
    section.classList.toggle("is-active", active);
  });
  document.querySelectorAll(".tab").forEach((button) => {
    const active = button.dataset.tab === name;
    button.classList.toggle("is-active", active);
    button.setAttribute("aria-current", active ? "page" : "false");
  });
  await views[name].activate?.();
  window.scrollTo({ top: 0, behavior: "instant" });
}

function wireShell() {
  document.querySelectorAll("[data-tab]").forEach((button) => {
    button.addEventListener("click", () => showView(button.dataset.tab));
  });
  document.querySelectorAll("[data-go]").forEach((button) => {
    button.addEventListener("click", () => showView(button.dataset.go));
  });
  el("theme-toggle").addEventListener("click", () => {
    const next = currentTheme() === "dark" ? "light" : "dark";
    writeStorage(THEME_KEY, next);
    applyTheme(next);
  });
  el("connection").addEventListener("click", refresh);
  window.addEventListener("online", refresh);
  window.addEventListener("offline", () => setConnection(false, "Offline"));
  document.addEventListener("visibilitychange", () => {
    if (document.visibilityState === "visible") refresh();
  });
}

function showInstallTip() {
  const standalone = window.matchMedia("(display-mode: standalone)").matches
    || window.navigator.standalone;
  const ios = /iPad|iPhone|iPod/.test(navigator.userAgent)
    || (navigator.platform === "MacIntel" && navigator.maxTouchPoints > 1);
  const safari = ios && !/CriOS|FxiOS|EdgiOS|OPiOS/.test(navigator.userAgent);
  if (safari && !standalone && !readStorage(INSTALL_TIP_KEY)) {
    window.setTimeout(() => { el("install-tip").hidden = false; }, 1200);
  }
  el("dismiss-install").addEventListener("click", () => {
    el("install-tip").hidden = true;
    writeStorage(INSTALL_TIP_KEY, "1");
  });
}

async function refresh() {
  const active = views[state.activeView];
  const seen = statusCache.get(state.language)?.collection_version;
  const first = active === views.capture || active.loaded ? null : active.activate?.();
  const [status] = await Promise.all([loadStatus(), views.capture.refresh(), first]);
  // The glossary re-reads only when the collection file changed (a save on
  // the Mac, say): a fresh index is about 94 kB over the tailnet.
  if (active === views.library && active.loaded && status?.collection_version !== seen) {
    await active.refreshIfLoaded();
  }
}

async function bootstrap() {
  applyTheme(currentTheme());
  // The glossary hands an entry over; capture owns what happens to a word you
  // already hold, so no vocabulary rule crosses into the glossary.
  views.library = new LibraryView(api, async (entry) => {
    views.capture.showCollected(entry);
    await showView("capture");
  });
  views.translate = new TranslationView(api, dataChanged);
  views.capture = new CaptureView(api, dataChanged, async (text) => {
    await showView("translate");
    await views.translate.begin(text, "target_to_eng");
  });
  views.practice = new PracticeView(api, dataChanged);
  views.tools = new ToolsView(api, dataChanged);
  wireShell();
  trackKeyboardInset();
  showInstallTip();
  try {
    const languages = await loadCollections();
    await Promise.all([loadStatus(), views.capture.activate()]);
    const others = languages.filter((language) => language !== state.language);
    api.prefetch("/api/status", others, (language, status) => statusCache.set(language, status));
    views.capture.prefetchRecent(others);
  } catch (error) {
    setConnection(false, "Server unavailable");
    views.capture.showMessage(error.message);
  }
  if ("serviceWorker" in navigator) {
    navigator.serviceWorker.register("/service-worker.js").catch(() => {});
  }
}

bootstrap();
