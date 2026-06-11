/* OxyPC Telecalling Mobile — page bootstrap + helpers.
   Each template loads this; per-page logic lives in inline <script> at the bottom.
*/
(function(){
  // ── Service worker registration ───────────────────────────────────────
  if ('serviceWorker' in navigator) {
    navigator.serviceWorker.register('/static/m/telecalling/sw.js',
      { scope: '/m/telecalling' }).catch(() => {});
  }

  // ── Stable device id (UUID kept in localStorage) ──────────────────────
  let did = localStorage.getItem('oxytc_device_id');
  if (!did) {
    did = 'd-' + (crypto.randomUUID ? crypto.randomUUID() : Math.random().toString(36).slice(2));
    localStorage.setItem('oxytc_device_id', did);
  }
  window.OxyTC = { deviceId: did };

  // ── Toast helper ──────────────────────────────────────────────────────
  window.OxyTC.toast = function(msg, kind){
    let t = document.getElementById('oxytc-toast');
    if (!t){
      t = document.createElement('div'); t.id = 'oxytc-toast'; t.className = 'tc-toast';
      document.body.appendChild(t);
    }
    t.className = 'tc-toast show ' + (kind || '');
    t.textContent = msg;
    clearTimeout(t._h); t._h = setTimeout(() => t.classList.remove('show'), 2400);
  };

  // ── JSON helper with CSRF + credentials ───────────────────────────────
  window.OxyTC.api = async function(path, opts){
    opts = opts || {};
    opts.headers = Object.assign({
      'Content-Type': 'application/json',
      'X-Device-Id': did,
    }, opts.headers || {});
    opts.credentials = 'include';
    const res = await fetch('/api/v1/telecalling' + path, opts);
    if (!res.ok && res.status >= 400) {
      const t = await res.text().catch(() => '');
      throw new Error(res.status + ' ' + t.slice(0, 120));
    }
    return res.json();
  };

  // ── Online/offline indicator ──────────────────────────────────────────
  function refreshOfflineBanner(){
    const el = document.getElementById('tc-offline-banner');
    if (!el) return;
    if (!navigator.onLine) {
      el.style.display = '';
      if (window.OxyTCQueue) {
        OxyTCQueue.count().then(n => {
          el.innerHTML = '⚠ Offline · ' + n + ' calls queued to sync';
        });
      } else {
        el.textContent = '⚠ Offline';
      }
    } else {
      el.style.display = 'none';
    }
  }
  window.addEventListener('online', refreshOfflineBanner);
  window.addEventListener('offline', refreshOfflineBanner);
  document.addEventListener('DOMContentLoaded', refreshOfflineBanner);
})();
