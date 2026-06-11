/* OxyPC Telecalling — service worker v1
 * Scope: /m/telecalling
 * Strategies:
 *   - app shell: cache-first
 *   - /api/v1/telecalling/*: network-first, queue POSTs while offline
 *   - static/*: stale-while-revalidate
 */
const VERSION = 'oxytc-v1.0.0';
const APP_SHELL = [
  '/m/telecalling',
  '/m/telecalling/queue',
  '/m/telecalling/followups',
  '/m/telecalling/inbox',
  '/static/m/telecalling/manifest.json',
  '/static/m/telecalling/mobile.css',
  '/static/m/telecalling/offline-queue.js',
  '/static/m/telecalling/app.js',
];

self.addEventListener('install', (e) => {
  e.waitUntil(caches.open(VERSION).then((c) => c.addAll(APP_SHELL)));
  self.skipWaiting();
});

self.addEventListener('activate', (e) => {
  e.waitUntil(
    caches.keys().then((keys) =>
      Promise.all(keys.filter((k) => k !== VERSION).map((k) => caches.delete(k)))
    )
  );
  self.clients.claim();
});

self.addEventListener('fetch', (e) => {
  const req = e.request;
  const url = new URL(req.url);

  // 1. POST /api/v1/telecalling/calls — queue offline, replay on reconnect
  if (req.method === 'POST' && url.pathname.includes('/api/v1/telecalling/calls')) {
    e.respondWith((async () => {
      try {
        return await fetch(req.clone());
      } catch (err) {
        // Stash for background sync; UI shows "queued" toast
        const body = await req.clone().json().catch(() => null);
        const idem = req.headers.get('Idempotency-Key');
        const dev  = req.headers.get('X-Device-Id') || '';
        await self.indexedDB; // ensure import path is loaded
        self.postMessage({ type: 'queued_call', idem, body });
        if ('sync' in self.registration) {
          await self.registration.sync.register('replay-calls');
        }
        return new Response(JSON.stringify({ queued: true, idempotency_key: idem }), {
          status: 202, headers: { 'Content-Type': 'application/json' }
        });
      }
    })());
    return;
  }

  // 2. GET /api/v1/telecalling/* — network-first, fall back to cache
  if (req.method === 'GET' && url.pathname.startsWith('/api/v1/telecalling')) {
    e.respondWith((async () => {
      try {
        const res = await fetch(req);
        const cache = await caches.open(VERSION);
        cache.put(req, res.clone());
        return res;
      } catch (err) {
        return (await caches.match(req)) || new Response('[]', {
          headers: { 'Content-Type': 'application/json' }
        });
      }
    })());
    return;
  }

  // 3. App shell + static — cache-first
  if (req.method === 'GET') {
    e.respondWith(
      caches.match(req).then((hit) => hit || fetch(req).then((res) => {
        if (res.ok && (url.pathname.startsWith('/static') || url.pathname.startsWith('/m/'))) {
          const copy = res.clone();
          caches.open(VERSION).then((c) => c.put(req, copy));
        }
        return res;
      }).catch(() => caches.match('/m/telecalling')))
    );
  }
});

self.addEventListener('sync', (e) => {
  if (e.tag === 'replay-calls') {
    e.waitUntil(replayQueuedCalls());
  }
});

async function replayQueuedCalls() {
  // Drains IndexedDB 'tc_outbox' written by offline-queue.js
  const db = await openDB();
  const tx = db.transaction('tc_outbox', 'readwrite');
  const store = tx.objectStore('tc_outbox');
  const all = await new Promise((res, rej) => {
    const r = store.getAll(); r.onsuccess = () => res(r.result); r.onerror = () => rej(r.error);
  });
  for (const row of all) {
    try {
      const r = await fetch('/api/v1/telecalling/calls', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json',
                   'Idempotency-Key': row.idempotency_key,
                   'X-Device-Id': row.device_id || '' },
        body: JSON.stringify(row.payload), credentials: 'include',
      });
      if (r.ok || r.status === 200) {
        store.delete(row.id);
      }
    } catch (err) { /* retry later */ }
  }
}

function openDB() {
  return new Promise((res, rej) => {
    const r = indexedDB.open('oxytc', 1);
    r.onupgradeneeded = () => {
      r.result.createObjectStore('tc_outbox', { keyPath: 'id', autoIncrement: true });
    };
    r.onsuccess = () => res(r.result);
    r.onerror = () => rej(r.error);
  });
}
