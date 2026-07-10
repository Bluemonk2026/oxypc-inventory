/* OxyPC Trade Partner — minimal service worker.
 *
 * Purpose: satisfy the PWA installability requirement and give a friendly
 * offline fallback. Deliberately NO caching of catalog/booking pages —
 * prices, availability and countdowns must always be live. */
const OFFLINE_HTML = `<!DOCTYPE html><html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>Offline — OxyPC Trade Partner</title>
<style>body{font-family:"Segoe UI",Arial,sans-serif;background:#0f1923;color:#fff;
display:flex;align-items:center;justify-content:center;min-height:100vh;margin:0;text-align:center;padding:24px}
.c{max-width:320px}h1{font-size:22px;margin:0 0 8px}p{opacity:.7;font-size:15px}</style>
</head><body><div class="c"><h1>You're offline</h1>
<p>OxyPC Trade Partner needs a connection — prices and stock are always live.
Reconnect and pull to refresh.</p></div></body></html>`;

self.addEventListener("install", (e) => self.skipWaiting());
self.addEventListener("activate", (e) => e.waitUntil(self.clients.claim()));

self.addEventListener("fetch", (event) => {
  if (event.request.mode === "navigate") {
    event.respondWith(
      fetch(event.request).catch(() =>
        new Response(OFFLINE_HTML, { headers: { "Content-Type": "text/html; charset=utf-8" } })
      )
    );
  }
});
