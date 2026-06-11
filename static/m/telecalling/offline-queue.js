/* IndexedDB outbox for offline call POSTs. Loaded by call.html.
 * Public API:
 *   await OxyTCQueue.enqueue({payload, idempotency_key, device_id})
 *   await OxyTCQueue.count()    // pending offline calls
 *   await OxyTCQueue.drain()    // manual replay
 */
window.OxyTCQueue = (function () {
  function open() {
    return new Promise((res, rej) => {
      const r = indexedDB.open('oxytc', 1);
      r.onupgradeneeded = () => {
        r.result.createObjectStore('tc_outbox', { keyPath: 'id', autoIncrement: true });
      };
      r.onsuccess = () => res(r.result);
      r.onerror = () => rej(r.error);
    });
  }

  async function enqueue(row) {
    const db = await open();
    return new Promise((res, rej) => {
      const tx = db.transaction('tc_outbox', 'readwrite');
      const r = tx.objectStore('tc_outbox').add({ ...row, queued_at: Date.now() });
      r.onsuccess = () => res(r.result);
      r.onerror = () => rej(r.error);
    });
  }

  async function count() {
    const db = await open();
    return new Promise((res, rej) => {
      const r = db.transaction('tc_outbox').objectStore('tc_outbox').count();
      r.onsuccess = () => res(r.result);
      r.onerror = () => rej(r.error);
    });
  }

  async function drain() {
    const db = await open();
    const all = await new Promise((res, rej) => {
      const r = db.transaction('tc_outbox').objectStore('tc_outbox').getAll();
      r.onsuccess = () => res(r.result);
      r.onerror = () => rej(r.error);
    });
    for (const row of all) {
      try {
        const resp = await fetch('/api/v1/telecalling/calls', {
          method: 'POST',
          credentials: 'include',
          headers: {
            'Content-Type': 'application/json',
            'Idempotency-Key': row.idempotency_key,
            'X-Device-Id': row.device_id || '',
          },
          body: JSON.stringify(row.payload),
        });
        if (resp.ok || resp.status === 200) {
          await new Promise((res) => {
            const tx = db.transaction('tc_outbox', 'readwrite');
            tx.objectStore('tc_outbox').delete(row.id);
            tx.oncomplete = res;
          });
        }
      } catch (e) { /* retry next online event */ }
    }
  }

  window.addEventListener('online', () => { drain(); });
  return { enqueue, count, drain };
})();
