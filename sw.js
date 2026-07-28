const CACHE = "nbt-static-0.13.2-copy-6";
const CORE = [
  "./style.min.css?v=0.13.2",
  "./shared-header.min.js?v=0.13.2",
  "./shared-footer.min.js?v=0.13.2",
  "./cloud-data.min.js?v=0.13.2",
  "./assets/brand-icon.svg?v=0.13.2",
  "./favicon.svg?v=0.13.2",
  "./data/index.min.js?v=0.13.2"
];
self.addEventListener("install", event => {
  event.waitUntil(
    caches.open(CACHE)
      .then(cache => Promise.all(CORE.map(url =>
        fetch(url, { cache: "reload" }).then(response => {
          if (!response.ok) throw new Error(`Core asset HTTP ${response.status}: ${url}`);
          return cache.put(url, response);
        })
      )))
      .catch(() => undefined)
  );
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
      if (!isRuntime && !isCloudConfig && response.ok) {
        const cacheCopy = response.clone();
        event.waitUntil(caches.open(CACHE).then(cache => cache.put(request, cacheCopy)));
      }
      return response;
    }).catch(() => caches.match(request)));
    return;
  }
  if (/\.(?:css|js|svg|png|ico|webp|jpg|jpeg)$/i.test(url.pathname)) {
    event.respondWith(fetch(request, { cache: "no-cache" }).then(response => {
      if (response.ok) {
        const cacheCopy = response.clone();
        event.waitUntil(caches.open(CACHE).then(cache => cache.put(request, cacheCopy)));
      }
      return response;
    }).catch(() => caches.match(request)));
  }
});
