// Service worker: приложение открывается даже без сети.
// Данные (API) не кэшируются — их офлайн-очередь появится на этапе 3.
const CACHE = "crm-shell-v2";
const SHELL = ["/", "/static/app/app.css", "/static/app/app.js", "/static/app/icon.svg",
               "/static/app/icon-192.png", "/manifest.webmanifest"];

self.addEventListener("install", (e) => {
  e.waitUntil(caches.open(CACHE).then((c) => c.addAll(SHELL)).then(() => self.skipWaiting()));
});

self.addEventListener("activate", (e) => {
  e.waitUntil(caches.keys().then((keys) => Promise.all(keys.filter((k) => k !== CACHE).map((k) => caches.delete(k))))
    .then(() => self.clients.claim()));
});

self.addEventListener("fetch", (e) => {
  const url = new URL(e.request.url);
  if (e.request.method !== "GET" || url.origin !== location.origin) return;
  if (url.pathname.startsWith("/api/") || url.pathname.startsWith("/admin/")) return;
  // Сначала сеть (свежая версия), без сети — из кэша
  e.respondWith(
    fetch(e.request).then((resp) => {
      const copy = resp.clone();
      if (resp.ok) caches.open(CACHE).then((c) => c.put(e.request, copy));
      return resp;
    }).catch(() => caches.match(e.request).then((r) => r || caches.match("/")))
  );
});
