// Minimal service worker — enables PWA "Add to Home Screen"
const CACHE = "framelink-v1";
const OFFLINE = ["/", "/static/icon-192.png"];

self.addEventListener("install", e =>
  e.waitUntil(caches.open(CACHE).then(c => c.addAll(OFFLINE)))
);

self.addEventListener("fetch", e => {
  // Network-first for API calls, cache-first for static assets
  if (e.request.url.includes("/api/")) {
    e.respondWith(fetch(e.request).catch(() => new Response("{}", { headers: { "Content-Type": "application/json" }})));
  } else {
    e.respondWith(
      caches.match(e.request).then(r => r || fetch(e.request))
    );
  }
});
