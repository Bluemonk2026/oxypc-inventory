/* ============================================================
   Reliance Asset FieldOps — session & account administration

   Who you are is decided by the server, not by this device. At boot the app
   asks /api/me; no session means the browser goes to the sign-in page. There
   is no role picker — your role, your sites and your rights come from the
   account an administrator created for you.

   Accounts themselves live server-side too: creating users, assigning roles
   and sites, resetting passwords and bulk import/export are all API calls that
   the server authorises. A device cannot make itself an administrator.

   Run without the API (a plain file server, for a demo or the test suites) and
   this module reports "standalone" and leaves the app in local-only mode.
   ============================================================ */
(function (RA) {
  'use strict';

  var S = RA.store;
  var N = {};
  RA.session = N;

  N.state = { mode: null, user: null, error: null };   // mode: server | standalone

  var LOGIN_URL = 'login';        // relative → /fieldops/login

  function api(path, opts) {
    opts = opts || {};
    return fetch(path, {
      method: opts.method || 'GET',
      headers: opts.body ? { 'Content-Type': 'application/json' } : undefined,
      credentials: 'same-origin',
      body: opts.body ? JSON.stringify(opts.body) : undefined
    }).then(function (res) {
      var ct = res.headers.get('content-type') || '';
      if (ct.indexOf('application/json') === -1) {
        var e = new Error('unavailable'); e.unavailable = true; throw e;
      }
      return res.json().then(function (data) {
        if (!res.ok) {
          var err = new Error(data.detail || ('Request failed (' + res.status + ')'));
          err.status = res.status;
          throw err;
        }
        return data;
      });
    });
  }
  N.api = api;

  N.toLogin = function () { location.href = LOGIN_URL; };

  /* Mirror the server's account into the local user list so every screen that
     looks up a name, role or site assignment keeps working unchanged. */
  function upsertLocalUser(u) {
    var list = S.db.users || (S.db.users = []);
    var found = null;
    for (var i = 0; i < list.length; i++) {
      if (list[i].id === u.id) { found = list[i]; break; }
    }
    var record = {
      id: u.id, name: u.name, emp: u.emp, role: u.role, region: u.region,
      sites: u.sites || [], perms: u.perms || { allow: [], deny: [] },
      status: u.status, has_password: u.has_password,
      must_change_password: u.must_change_password, last_login: u.last_login
    };
    if (found) { for (var k in record) found[k] = record[k]; return found; }
    list.push(record);
    return record;
  }
  N.upsertLocalUser = upsertLocalUser;

  /* ---------------- boot ---------------- */
  N.boot = function () {
    return api('api/me').then(function (out) {
      N.state.mode = 'server';
      N.state.user = out.user;
      upsertLocalUser(out.user);
      S.login(out.user.id, true);          // adopt the server's identity locally
      S.persist();
      return { mode: 'server', user: out.user };
    }).catch(function (err) {
      if (err.status === 401 || err.status === 403) {
        N.toLogin();
        return { mode: 'redirecting' };
      }
      /* No API at all — a file server, or the route is not deployed. The app
         still runs; it simply has no shared store and no server accounts. */
      N.state.mode = 'standalone';
      N.state.error = err.message;
      return { mode: 'standalone' };
    });
  };

  N.logout = function () {
    if (N.state.mode !== 'server') {
      S.logout();
      location.hash = '#/login';
      RA.render();
      return Promise.resolve();
    }
    return api('api/auth/logout', { method: 'POST' })
      .catch(function () { /* sign out locally regardless */ })
      .then(function () {
        S.logout();
        N.toLogin();
      });
  };

  N.changePassword = function (currentPassword, newPassword) {
    return api('api/auth/password', {
      method: 'POST',
      body: { current_password: currentPassword, new_password: newPassword }
    });
  };

  /* ---------------- administration (server-authorised) ---------------- */
  N.listUsers = function () {
    return api('api/admin/users').then(function (out) {
      /* Replace the local list wholesale so a user deleted on the server
         disappears here too. */
      S.db.users = [];
      out.users.forEach(upsertLocalUser);
      S.persist();
      return out.users;
    });
  };

  N.saveUser = function (payload) {
    return api('api/admin/users', { method: 'POST', body: payload })
      .then(function (out) { upsertLocalUser(out.user); S.persist(); return out.user; });
  };

  N.resetPassword = function (userId, newPassword) {
    return api('api/admin/users/reset-password', {
      method: 'POST', body: { user_id: userId, new_password: newPassword }
    });
  };

  N.deleteUser = function (userId) {
    return api('api/admin/users/' + encodeURIComponent(userId), { method: 'DELETE' })
      .then(function (out) {
        S.db.users = (S.db.users || []).filter(function (u) { return u.id !== userId; });
        S.persist();
        return out;
      });
  };

  N.exportAll = function () { return api('api/admin/export'); };

  N.importAll = function (records, replace) {
    return api('api/admin/import', {
      method: 'POST', body: { records: records, replace: !!replace }
    });
  };

  N.adminAudit = function (limit) {
    return api('api/admin/audit?limit=' + (limit || 200));
  };

  N.isServer = function () { return N.state.mode === 'server'; };
  N.isAdmin = function () {
    var me = S.me();
    return !!me && me.role === 'admin';
  };

})(window.RA = window.RA || {});
