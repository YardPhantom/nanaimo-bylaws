const CACHE = "nbt-static-0.13.1";
const CORE = [
  "./style.min.css?v=0.13.1",
  "./shared-header.min.js?v=0.13.1",
  "./shared-footer.min.js?v=0.13.1",
  "./cloud-data.min.js?v=0.13.1",
  "./assets/brand-icon.svg?v=0.13.1",
  "./favicon.svg?v=0.13.1",
  "./data/index.min.js?v=0.13.1"
];
self.addEventListener("install", event => {
  event.waitUntil(caches.open(CACHE).then(cache => cache.addAll(CORE)).catch(() => undefined));
  self.skipWaiting();
});
self.addEventListener("activate", event => {
  event.waitUntil(caches.keys().then(keys => Promise.all(keys.filter(key => key.startsWith("nbt-static-") && key !== CACHE).map(key => caches.delete(key)))));
  self.clients.claim();
});
self.addEventListener("fetch", event => {
  const request = event.request;
  if (request.method !== "GET") return;
  const url = new URL(request.url);
  if (url.origin !== location.origin) return;
  const isRuntime = url.pathname.includes("/data/") && url.pathname.endsWith(".json");
  const isCloudConfig = url.pathname.endsWith("/cloud-config.js");
  const isPage = request.mode === "navigate" || url.pathname.endsWith(".html") || url.pathname.endsWith("/");
  if (isRuntime || isCloudConfig || isPage) {
    event.respondWith(fetch(request).then(response => {
      if (!isRuntime && !isCloudConfig && response.ok) caches.open(CACHE).then(cache => cache.put(request, response.clone()));
      return response;
    }).catch(() => caches.match(request)));
    return;
  }
  if (/\.(?:css|js|svg|png|ico|webp|jpg|jpeg)$/i.test(url.pathname)) {
    event.respondWith(caches.match(request).then(cached => cached || fetch(request).then(response => {
      if (response.ok) caches.open(CACHE).then(cache => cache.put(request, response.clone()));
      return response;
    })));
  }
});
