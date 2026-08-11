/* ============================================================
   Reliance Asset FieldOps — Shell, router & bootstrap
   ============================================================ */
(function (RA) {
  'use strict';
  var U = RA.ui, S = RA.store, D = RA.data;

  RA.filters = RA.filters || {};
  RA.focusId = null;

  /* ---------------- Navigation model ---------------- */
  var NAV = [
    { key: 'myday',     icon: '🏠', label: 'My Day' },
    { key: 'dashboard', icon: '📊', label: 'Dashboard' },
    { key: 'sites',     icon: '📍', label: 'Sites' },
    { key: 'scan',      icon: '🔍', label: 'Scan / Find' },
    { key: 'serials',   icon: '🔢', label: 'Serial register' },
    { key: 'approvals', icon: '✅', label: 'Approvals' },
    { key: 'pricing',   icon: '💰', label: 'Commercial' },
    { key: 'packing',   icon: '📦', label: 'Packing' },
    { key: 'pickup',    icon: '🚚', label: 'Pickup' },
    { key: 'courier',   icon: '📮', label: 'Courier / AWB' },
    { key: 'warehouse', icon: '🏭', label: 'Warehouse' },
    { key: 'reports',   icon: '📈', label: 'Reports / MIS' },
    { key: 'alerts',    icon: '🔔', label: 'Alerts' },
    { key: 'audit',     icon: '🧾', label: 'Audit log' },
    { key: 'admin',     icon: '⚙️', label: 'Admin' },
    { key: 'profile',   icon: '👤', label: 'Profile' }
  ];
  function navFor() { return NAV.filter(function (n) { return S.can(n.key); }); }

  /* Bottom bar: role-tuned shortlist */
  var BAR = {
    fe:         ['myday', 'scan', 'packing', 'alerts', 'profile'],
    coord:      ['sites', 'approvals', 'packing', 'alerts', 'profile'],
    pmo:        ['dashboard', 'sites', 'reports', 'alerts', 'profile'],
    spoc:       ['sites', 'approvals', 'dashboard', 'alerts', 'profile'],
    approver:   ['approvals', 'dashboard', 'sites', 'alerts', 'profile'],
    commercial: ['pricing', 'dashboard', 'reports', 'alerts', 'profile'],
    packer:     ['packing', 'pickup', 'sites', 'alerts', 'profile'],
    courier:    ['courier', 'pickup', 'alerts', 'reports', 'profile'],
    warehouse:  ['warehouse', 'reports', 'alerts', 'dashboard', 'profile'],
    admin:      ['dashboard', 'admin', 'reports', 'alerts', 'profile']
  };

  /* ---------------- Router ---------------- */
  function route() {
    var h = (location.hash || '').replace(/^#\/?/, '');
    var parts = h.split('/').filter(Boolean);
    return { name: parts[0] || '', params: parts.slice(1) };
  }

  RA.render = function () {
    var app = document.getElementById('app');
    var me = S.me();
    var r = route();

    /* not signed in */
    if (!me) {
      if (r.name !== 'login') { location.hash = '#/login'; }
      document.body.classList.add('login-mode');
      app.innerHTML = RA.screens.login.render();
      bind(app);
      return;
    }
    document.body.classList.remove('login-mode');

    if (!r.name || r.name === 'login') { location.hash = D.ROLES[me.role].home; return; }

    var screen = RA.screens[r.name];
    if (!screen) { app.innerHTML = shell(r, '<div class="pad">' + U.empty('🚧', 'Screen not found', r.name) + '</div>'); bind(app); return; }
    if (!S.can(r.name)) {
      app.innerHTML = shell(r, '<div class="pad">' + U.empty('🔒', 'Access restricted',
        D.ROLES[me.role].label + ' does not have access to this module (FR-002 RBAC).') + '</div>');
      bind(app); return;
    }

    var body;
    try { body = screen.render(r.params); }
    catch (e) {
      body = '<div class="pad">' + U.empty('⚠️', 'Something went wrong', e.message) + '</div>';
      if (window.console) console.error(e);
    }
    app.innerHTML = shell(r, body);
    bind(app);
    if (screen.mount) try { screen.mount(r.params); } catch (e) { console.error(e); }
    restoreFocus();
    var main = document.getElementById('screen-body');
    if (main && RA.lastRoute !== location.hash) main.scrollTop = 0;
    RA.lastRoute = location.hash;
  };

  /* Connection + shared-store state, always visible on every screen */
  function netBanner(online, pending) {
    var sync = RA.sync;
    var queued = sync ? sync.dirtyCount() : pending;
    if (!online) {
      return '<div class="net-banner offline">⚠️ <span><b>Offline.</b> Capture continues; ' +
        queued + ' change(s) will sync on reconnect.</span></div>';
    }
    if (sync && sync.state.available === false) {
      return '<div class="net-banner offline">📴 <span><b>This device only.</b> ' +
        'The shared store is not reachable' + (queued ? ' · ' + queued + ' change(s) held' : '') +
        '.</span><button class="link-btn" data-act="sync-now">Retry</button></div>';
    }
    if (sync && sync.state.last_error) {
      return '<div class="net-banner offline">⚠️ <span>' + U.esc(sync.state.last_error) + '</span>' +
        '<button class="link-btn" data-act="sync-now">Retry</button></div>';
    }
    if (queued) {
      return '<div class="net-banner online">🔄 <span>Syncing · ' + queued +
        ' change(s) queued</span><button class="link-btn" data-act="sync-now">Sync now</button></div>';
    }
    var when = sync && sync.state.last_ok
      ? ' · shared store updated ' + U.dt(sync.state.last_ok).split(' ').slice(-1)[0]
      : '';
    return '<div class="net-banner online">🟢 <span>Online · all changes shared' + when +
      '</span><button class="link-btn" data-act="sync-now">Sync now</button></div>';
  }

  function titleOf(screen, params) {
    return typeof screen.title === 'function' ? screen.title(params) : (screen.title || '');
  }

  function shell(r, body) {
    var me = S.me();
    var screen = RA.screens[r.name] || {};
    var nav = navFor();
    var bar = (BAR[me.role] || ['dashboard', 'alerts', 'profile']).filter(function (k) { return S.can(k); });
    var unread = S.notifications().filter(function (n) { return !n.read; }).length;
    var badge = screen.badge ? screen.badge() : null;
    var pending = S.pendingSync().length;
    var online = navigator.onLine !== false;

    return '' +
    '<div class="layout">' +
      /* ---- desktop sidebar ---- */
      '<aside class="sidebar">' +
        '<div class="brand"><span class="brand-logo">📦</span>' +
        '<div><div class="brand-name">FieldOps</div>' +
        '<div class="brand-sub">Reliance Asset QC</div></div></div>' +
        '<nav class="side-nav">' + nav.map(function (n) {
          return '<a class="side-item' + (n.key === r.name ? ' on' : '') + '" href="#/' + n.key + '">' +
            '<span class="si-icon">' + n.icon + '</span>' + U.esc(n.label) +
            (n.key === 'alerts' && unread ? '<span class="dot-badge">' + unread + '</span>' : '') + '</a>';
        }).join('') + '</nav>' +
        '<div class="side-foot">' +
          '<div class="small">' + U.esc(me.name) + '</div>' +
          '<div class="small muted">' + U.esc(D.ROLES[me.role].label) + '</div>' +
          '<button class="btn btn-outline xs mt8" data-act="logout">Sign out</button>' +
        '</div>' +
      '</aside>' +

      /* ---- phone / main column ---- */
      '<main class="main">' +
        '<header class="app-header">' +
          (screen.back || r.params.length
            ? '<button class="icon-btn" data-act="back">←</button>'
            : '<button class="icon-btn only-mobile" data-act="drawer">☰</button>') +
          '<h1>' + U.esc(titleOf(screen, r.params)) + '</h1>' +
          (badge ? '<span class="hdr-badge">' + U.esc(badge) + '</span>' : '') +
          '<a class="icon-btn bell" href="#/alerts">🔔' + (unread ? '<span class="dot-badge">' + unread + '</span>' : '') + '</a>' +
        '</header>' +
        netBanner(online, pending) +
        '<div class="screen-body" id="screen-body">' + body + '<div class="tail"></div></div>' +
        '<nav class="bottom-nav">' + bar.map(function (k) {
          var n = NAV.filter(function (x) { return x.key === k; })[0];
          if (!n) return '';
          return '<a class="nav-item' + (n.key === r.name ? ' on' : '') + '" href="#/' + n.key + '">' +
            '<span class="icon">' + n.icon + '</span>' + U.esc(n.label.split(' ')[0]) +
            (n.key === 'alerts' && unread ? '<span class="dot-badge sm">' + unread + '</span>' : '') + '</a>';
        }).join('') + '</nav>' +
      '</main>' +
    '</div>' +
    '<div class="drawer" id="drawer"><div class="drawer-panel">' +
      '<div class="brand"><span class="brand-logo">📦</span><div><div class="brand-name">FieldOps</div>' +
      '<div class="brand-sub">' + U.esc(me.name) + ' · ' + U.esc(D.ROLES[me.role].label) + '</div></div></div>' +
      nav.map(function (n) {
        return '<a class="side-item' + (n.key === r.name ? ' on' : '') + '" href="#/' + n.key + '" data-act="drawer-close">' +
          '<span class="si-icon">' + n.icon + '</span>' + U.esc(n.label) + '</a>';
      }).join('') +
      '<button class="btn btn-outline block mt10" data-act="logout">Sign out</button>' +
      '</div><div class="drawer-back" data-act="drawer-close"></div></div>';
  }

  /* ---------------- Event delegation ---------------- */
  function bind(root) {
    root.querySelectorAll('[data-act]').forEach(function (el) {
      if (el.__bound) return;
      el.__bound = true;
      el.addEventListener('click', function (ev) {
        var act = el.getAttribute('data-act');
        var fn = RA.actions[act];
        if (!fn) return;
        /* A link that also carries an action — the drawer's menu items — must
           still follow its href. Suppressing the default killed navigation:
           the menu closed and went nowhere. */
        var navigates = el.tagName === 'A' && el.getAttribute('href');
        if (!navigates) ev.preventDefault();
        fn(el, ev);
      });
    });
    root.querySelectorAll('[data-live]').forEach(function (el) {
      if (el.__bound) return;
      el.__bound = true;
      el.addEventListener('input', function () {
        RA.filters[el.getAttribute('data-live')] = el.value;
        RA.focusId = el.id;
        clearTimeout(RA.liveT);
        RA.liveT = setTimeout(RA.render, 220);
      });
    });
  }

  function restoreFocus() {
    if (!RA.focusId) return;
    var el = document.getElementById(RA.focusId);
    if (el) { el.focus(); try { el.setSelectionRange(el.value.length, el.value.length); } catch (e) { } }
    RA.focusId = null;
  }

  /* global actions */
  RA.actions.back = function () { history.back(); };
  RA.actions.drawer = function () { document.getElementById('drawer').classList.add('open'); };
  RA.actions['drawer-close'] = function () { document.getElementById('drawer').classList.remove('open'); };
  RA.actions['modal-close'] = function () { U.closeModal(); };
  RA.actions['apply-update'] = function () {
    U.closeModal();
    if ('serviceWorker' in navigator) {
      navigator.serviceWorker.getRegistrations().then(function (regs) {
        regs.forEach(function (r) { if (r.waiting) r.waiting.postMessage('skipWaiting'); });
        setTimeout(function () { location.reload(); }, 200);
      });
    } else location.reload();
  };

  /* modal host is outside #app — bind separately */
  document.addEventListener('click', function (ev) {
    var el = ev.target.closest && ev.target.closest('#modal-host [data-act]');
    if (!el) return;
    var fn = RA.actions[el.getAttribute('data-act')];
    if (fn && !el.__bound) { ev.preventDefault(); fn(el, ev); }
  });
  document.addEventListener('keydown', function (e) {
    if (e.key === 'Escape') U.closeModal();
  });

  /* ---------------- Bootstrap ---------------- */
  function boot() {
    S.load();
    window.addEventListener('hashchange', function () {
      var d = document.getElementById('drawer');
      if (d) d.classList.remove('open');
      RA.render();
    });
    window.addEventListener('online', function () {
      U.toast('Back online — syncing queued records', 'success');
      S.syncNow(); RA.render();
    });
    window.addEventListener('offline', function () {
      U.toast('Offline — QC capture continues locally', 'warn'); RA.render();
    });
    window.addEventListener('beforeinstallprompt', function (e) {
      e.preventDefault(); RA.deferredPrompt = e;
    });
    /* Identity comes from the server session, not from this device. */
    var ready = RA.session ? RA.session.boot() : Promise.resolve({ mode: 'standalone' });

    ready.then(function (res) {
      if (res && res.mode === 'redirecting') return;   // heading to the sign-in page

      var me = S.me();
      if (!location.hash || location.hash === '#/' || location.hash === '#/login') {
        location.hash = me ? D.ROLES[me.role].home : '#/login';
      }
      RA.render();

      /* An administrator has reset this password — nothing else until it changes. */
      if (me && RA.session && RA.session.state.user &&
          RA.session.state.user.must_change_password && RA.actions['change-password']) {
        RA.actions['change-password']({ getAttribute: function () { return 'forced'; } });
      }

      /* Shared store: push what this device changed, pull what others did. */
      if (RA.sync) RA.sync.start();
    });

    /* service worker — offline shell + update prompt */
    if ('serviceWorker' in navigator && location.protocol.indexOf('http') === 0) {
      navigator.serviceWorker.register('sw.js').then(function (reg) {
        reg.addEventListener('updatefound', function () {
          var sw = reg.installing;
          if (!sw) return;
          sw.addEventListener('statechange', function () {
            if (sw.state === 'installed' && navigator.serviceWorker.controller) {
              U.modal({
                title: 'Update available',
                body: '<p class="small">A newer version of FieldOps has been published. ' +
                      'Reload to apply it — queued records and captured QC stay on this device.</p>',
                footer: '<button class="btn btn-outline" data-act="modal-close">Later</button>' +
                        '<button class="btn btn-primary" data-act="apply-update">Reload now</button>'
              });
            }
          });
        });
        /* check for a new build whenever the app is brought back to the foreground */
        document.addEventListener('visibilitychange', function () {
          if (!document.hidden) reg.update().catch(function () { });
        });
      }).catch(function () { });
    }
  }

  if (document.readyState === 'loading') document.addEventListener('DOMContentLoaded', boot);
  else boot();

})(window.RA = window.RA || {});
