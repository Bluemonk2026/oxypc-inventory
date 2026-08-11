/* Reliance Asset FieldOps — service worker (offline shell) */
var CACHE = 'fieldops-v3.3.1';
var ASSETS = [
  './',
  './index.html',
  './css/app.css?v=3.3.1',
  './js/inventory.js?v=3.3.1',
  './js/data.js?v=3.3.1',
  './js/store.js?v=3.3.1',
  './js/session.js?v=3.3.1',
  './js/sync.js?v=3.3.1',
  './js/ui.js?v=3.3.1',
  './js/screens-field.js?v=3.3.1',
  './js/screens-ops.js?v=3.3.1',
  './js/screens-admin.js?v=3.3.1',
  './js/app.js?v=3.3.1',
  './manifest.webmanifest?v=3.3.1',
  './icons/icon.svg',
  './icons/icon-192.png',
  './icons/icon-512.png'
];

self.addEventListener('install', function (e) {
  e.waitUntil(
    caches.open(CACHE).then(function (c) {
      return Promise.all(ASSETS.map(function (u) {
        return c.add(u).catch(function () { /* tolerate a missing optional asset */ });
      }));
    }).then(function () { return self.skipWaiting(); })
  );
});

self.addEventListener('message', function (e) {
  if (e.data === 'skipWaiting') self.skipWaiting();
});

self.addEventListener('activate', function (e) {
  e.waitUntil(
    caches.keys().then(function (keys) {
      /* Drop every older cache outright — a half-kept previous build is worse
         than no cache at all. */
      return Promise.all(keys.map(function (k) { return k === CACHE ? null : caches.delete(k); }));
    }).then(function () { return self.clients.claim(); })
  );
});

/* Cache-first for app shell, network fallback; navigations fall back to index.html */
self.addEventListener('fetch', function (e) {
  var req = e.request;
  if (req.method !== 'GET') return;
  var url = new URL(req.url);
  if (url.origin !== location.origin) return;

  /* The shell always comes from the network when there is one. A cached
     index.html can otherwise pin a device to an old build after a deploy —
     which looks like screens that "cannot be found" because the page is asking
     for last week's scripts. Cache is the offline fallback, not the default. */
  if (req.mode === 'navigate' || url.pathname.endsWith('/index.html')) {
    e.respondWith(
      fetch(req).then(function (res) {
        if (res && res.ok) {
          var copy = res.clone();
          caches.open(CACHE).then(function (c) { c.put(req, copy); });
        }
        return res;
      }).catch(function () {
        return caches.match(req).then(function (hit) {
          return hit || caches.match('./index.html');
        });
      })
    );
    return;
  }

  e.respondWith(
    caches.match(req).then(function (hit) {
      if (hit) {
        /* refresh in background */
        fetch(req).then(function (res) {
          if (res && res.ok) caches.open(CACHE).then(function (c) { c.put(req, res.clone()); });
        }).catch(function () { });
        return hit;
      }
      return fetch(req).then(function (res) {
        if (res && res.ok) {
          var copy = res.clone();
          caches.open(CACHE).then(function (c) { c.put(req, copy); });
        }
        return res;
      });
    })
  );
});
