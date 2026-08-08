const SHELL_CACHE = "vocabbuilder-shell";
const SHELL_FILES = [
  "/",
  "/static/styles.css",
  "/static/app.js",
  "/static/api.js",
  "/static/ui.js",
  "/static/entry-list.js",
  "/static/capture-view.js",
  "/static/library-view.js",
  "/static/translation-view.js",
  "/static/practice-view.js",
  "/static/tools-view.js",
  "/static/icon.svg",
  "/manifest.webmanifest",
];

self.addEventListener("install", (event) => {
  event.waitUntil(caches.open(SHELL_CACHE).then((cache) => cache.addAll(SHELL_FILES)));
  self.skipWaiting();
});

self.addEventListener("activate", (event) => {
  event.waitUntil(
    caches.keys().then((keys) => Promise.all(
      keys.filter((key) => key !== SHELL_CACHE).map((key) => caches.delete(key))
    ))
  );
  self.clients.claim();
});

self.addEventListener("fetch", (event) => {
  if (event.request.method !== "GET" || event.request.url.includes("/api/")) return;
  event.respondWith(
    fetch(event.request)
      .then((response) => {
        const copy = response.clone();
        caches.open(SHELL_CACHE).then((cache) => cache.put(event.request, copy));
        return response;
      })
      .catch(() => caches.match(event.request))
  );
});
