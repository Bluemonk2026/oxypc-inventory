/* ============================================================
   Reliance Asset FieldOps — UI helpers & shared components
   ============================================================ */
(function (RA) {
  'use strict';
  var U = {};
  RA.ui = U;

  /* ---------- escaping & formatting ---------- */
  U.esc = function (s) {
    return String(s === null || s === undefined ? '' : s)
      .replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;')
      .replace(/"/g, '&quot;').replace(/'/g, '&#39;');
  };
  U.money = function (n) {
    n = +n || 0;
    return '₹' + n.toLocaleString('en-IN', { maximumFractionDigits: 0 });
  };
  U.pct = function (n, d) { return (+n || 0).toFixed(d === undefined ? 1 : d) + '%'; };
  U.dt = function (iso) {
    if (!iso) return '—';
    var d = new Date(iso);
    return d.toLocaleDateString('en-IN', { day: '2-digit', month: 'short' }) + ' ' +
           d.toLocaleTimeString('en-IN', { hour: '2-digit', minute: '2-digit' });
  };
  U.date = function (iso) {
    if (!iso) return '—';
    return new Date(iso).toLocaleDateString('en-IN', { day: '2-digit', month: 'short', year: 'numeric' });
  };
  U.mmss = function (sec) {
    sec = Math.max(0, Math.floor(sec || 0));
    var m = Math.floor(sec / 60), s = sec % 60;
    return m + ':' + (s < 10 ? '0' + s : s);
  };

  /* ---------- status vocabulary ---------- */
  var STATUS = {
    pending_qc:            { label: 'Pending QC',        cls: 'gray' },
    qc_submitted:          { label: 'Awaiting Approval', cls: 'blue' },
    accepted:              { label: 'Accepted',          cls: 'ok' },
    disputed:              { label: 'Disputed',          cls: 'fail' },
    packed:                { label: 'Packed',            cls: 'blue' },
    dispatched:            { label: 'In Transit',        cls: 'warn' },
    received:              { label: 'WH Received',       cls: 'ok' },
    received_discrepancy:  { label: 'WH Discrepancy',    cls: 'fail' },
    closed:                { label: 'Closed',            cls: 'ok' },
    pending:               { label: 'Pending',           cls: 'warn' },
    re_qc:                 { label: 'Re-QC Required',    cls: 'warn' },
    hold:                  { label: 'Hold',              cls: 'warn' },
    in_transit:            { label: 'In Transit',        cls: 'warn' },
    delivered:             { label: 'Delivered',         cls: 'ok' },
    sealed:                { label: 'Sealed',            cls: 'blue' }
  };
  U.status = function (key) { return STATUS[key] || { label: key || '—', cls: 'gray' }; };
  U.statusPill = function (key) {
    var s = U.status(key);
    return '<span class="pill pill-' + s.cls + '">' + U.esc(s.label) + '</span>';
  };
  U.pill = function (text, cls) { return '<span class="pill pill-' + (cls || 'gray') + '">' + U.esc(text) + '</span>'; };

  /* ---------- toast ---------- */
  U.toast = function (msg, type, ms) {
    var wrap = document.getElementById('toasts');
    if (!wrap) return;
    var el = document.createElement('div');
    el.className = 'toast toast-' + (type || 'info');
    el.innerHTML = U.esc(msg);
    wrap.appendChild(el);
    setTimeout(function () { el.classList.add('out'); setTimeout(function () { el.remove(); }, 300); }, ms || 3200);
  };

  /* ---------- modal / sheet ---------- */
  U.modal = function (opts) {
    var host = document.getElementById('modal-host');
    host.innerHTML =
      '<div class="modal-backdrop" data-act="modal-close"></div>' +
      '<div class="modal" role="dialog" aria-modal="true">' +
        '<div class="modal-head"><h3>' + U.esc(opts.title || '') + '</h3>' +
        '<button class="icon-btn" data-act="modal-close" aria-label="Close">✕</button></div>' +
        '<div class="modal-body">' + (opts.body || '') + '</div>' +
        (opts.footer ? '<div class="modal-foot">' + opts.footer + '</div>' : '') +
      '</div>';
    host.classList.add('open');
    if (opts.onOpen) opts.onOpen(host);
  };
  U.closeModal = function () {
    var host = document.getElementById('modal-host');
    host.classList.remove('open'); host.innerHTML = '';
  };
  U.confirm = function (title, message, onYes, yesLabel, danger) {
    U.modal({
      title: title,
      body: '<p class="muted">' + U.esc(message) + '</p>',
      footer: '<button class="btn btn-outline" data-act="modal-close">Cancel</button>' +
              '<button class="btn ' + (danger ? 'btn-red' : 'btn-primary') + '" id="confirm-yes">' +
              U.esc(yesLabel || 'Confirm') + '</button>',
      onOpen: function (host) {
        host.querySelector('#confirm-yes').addEventListener('click', function () {
          U.closeModal(); onYes();
        });
      }
    });
  };

  /* ---------- progress bar ---------- */
  U.bar = function (pctVal, cls) {
    var w = Math.max(0, Math.min(100, +pctVal || 0));
    return '<div class="pb"><div class="pb-fill ' + (cls || 'green') + '" style="width:' + w + '%"></div></div>';
  };

  /* ---------- empty state ---------- */
  U.empty = function (icon, title, sub) {
    return '<div class="empty"><div class="empty-icon">' + icon + '</div>' +
      '<div class="empty-title">' + U.esc(title) + '</div>' +
      (sub ? '<div class="empty-sub">' + U.esc(sub) + '</div>' : '') + '</div>';
  };

  /* ---------- photo capture & compression ---------- */
  U.pickPhoto = function (kind, cb) {
    var cfg = RA.store.db.config.photo;
    var input = document.createElement('input');
    input.type = 'file';
    input.accept = 'image/*';
    input.setAttribute('capture', 'environment');
    input.style.display = 'none';
    document.body.appendChild(input);
    input.addEventListener('change', function () {
      var f = input.files && input.files[0];
      if (!f) { input.remove(); return; }
      var reader = new FileReader();
      reader.onload = function (ev) {
        var img = new Image();
        img.onload = function () {
          var scale = Math.min(1, cfg.max_px / Math.max(img.width, img.height));
          var w = Math.round(img.width * scale), h = Math.round(img.height * scale);
          var c = document.createElement('canvas'); c.width = w; c.height = h;
          c.getContext('2d').drawImage(img, 0, 0, w, h);
          var data = c.toDataURL('image/jpeg', cfg.quality);
          cb({ id: 'P' + Date.now() + Math.floor(Math.random() * 1000), kind: kind, data: data, at: new Date().toISOString(), name: f.name });
          input.remove();
        };
        img.onerror = function () { U.toast('Could not read that image.', 'error'); input.remove(); };
        img.src = ev.target.result;
      };
      reader.readAsDataURL(f);
    });
    input.click();
  };

  /* ---------- barcode / QR scan (BRD FR-005) ---------- */
  U.scan = function (cb) {
    var supported = 'BarcodeDetector' in window;
    U.modal({
      title: 'Scan asset',
      body:
        '<div class="scan-wrap">' +
          '<video id="scan-video" playsinline muted></video>' +
          '<div class="scan-frame"></div>' +
        '</div>' +
        '<p class="muted small" id="scan-msg">' +
          (supported ? 'Point the camera at the QR / barcode.' :
           'Live barcode decoding is not supported by this browser — type the serial or asset tag below.') + '</p>' +
        '<label class="input-label">Serial / Asset tag</label>' +
        '<input class="input-field" id="scan-manual" placeholder="e.g. LT8K2M9QAX or REL-S01-004" autocomplete="off" />',
      footer: '<button class="btn btn-outline" data-act="modal-close">Cancel</button>' +
              '<button class="btn btn-primary" id="scan-go">Open Asset</button>',
      onOpen: function (host) {
        var stream = null, stop = false;
        var video = host.querySelector('#scan-video');
        var input = host.querySelector('#scan-manual');
        setTimeout(function () { input.focus(); }, 120);

        function cleanup() {
          stop = true;
          if (stream) stream.getTracks().forEach(function (t) { t.stop(); });
        }
        host.querySelectorAll('[data-act="modal-close"]').forEach(function (b) {
          b.addEventListener('click', cleanup);
        });
        host.querySelector('#scan-go').addEventListener('click', function () {
          cleanup(); U.closeModal(); cb((input.value || '').trim());
        });
        input.addEventListener('keydown', function (e) {
          if (e.key === 'Enter') { cleanup(); U.closeModal(); cb((input.value || '').trim()); }
        });

        if (navigator.mediaDevices && navigator.mediaDevices.getUserMedia) {
          navigator.mediaDevices.getUserMedia({ video: { facingMode: 'environment' } })
            .then(function (s) {
              stream = s; video.srcObject = s; video.play();
              if (!supported) return;
              var det = new window.BarcodeDetector({
                formats: ['qr_code', 'code_128', 'code_39', 'ean_13', 'data_matrix']
              });
              (function loop() {
                if (stop) return;
                det.detect(video).then(function (codes) {
                  if (codes && codes.length) {
                    cleanup(); U.closeModal(); cb(codes[0].rawValue);
                  } else setTimeout(loop, 320);
                }).catch(function () { setTimeout(loop, 600); });
              })();
            })
            .catch(function () {
              host.querySelector('#scan-msg').textContent = 'Camera unavailable — type the serial or asset tag below.';
              host.querySelector('.scan-wrap').style.display = 'none';
            });
        } else {
          host.querySelector('.scan-wrap').style.display = 'none';
        }
      }
    });
  };

  /* ---------- file download ---------- */
  U.download = function (filename, content, mime) {
    var blob = new Blob([content], { type: mime || 'text/plain;charset=utf-8' });
    var url = URL.createObjectURL(blob);
    var a = document.createElement('a');
    a.href = url; a.download = filename;
    document.body.appendChild(a); a.click();
    setTimeout(function () { URL.revokeObjectURL(url); a.remove(); }, 500);
  };
  U.exportCSV = function (name, headers, rows) {
    U.download(name + '_' + new Date().toISOString().slice(0, 10) + '.csv',
      RA.store.toCSV(headers, rows), 'text/csv;charset=utf-8');
    RA.store.audit('export', name, 'csv', { rows: rows.length });
    RA.store.persist();
    U.toast('Exported ' + rows.length + ' rows', 'success');
  };

  /* ---------- printable report (PDF via browser print) ---------- */
  U.printReport = function (title, html) {
    var w = window.open('', '_blank');
    if (!w) { U.toast('Pop-up blocked — allow pop-ups to export PDF.', 'warn'); return; }
    w.document.write(
      '<!doctype html><html><head><meta charset="utf-8"><title>' + U.esc(title) + '</title>' +
      '<style>' +
      'body{font-family:"Segoe UI",Arial,sans-serif;color:#1F2937;margin:28px;}' +
      'h1{font-size:19px;color:#17365D;margin:0 0 2px;}h2{font-size:14px;color:#17365D;margin:20px 0 6px;}' +
      '.sub{font-size:11px;color:#6B7280;margin-bottom:14px;}' +
      'table{width:100%;border-collapse:collapse;font-size:11px;margin-bottom:12px;}' +
      'th,td{border:1px solid #D1D5DB;padding:5px 7px;text-align:left;}' +
      'th{background:#F0F4FA;color:#17365D;}' +
      '.kv{display:flex;gap:24px;flex-wrap:wrap;font-size:11px;margin-bottom:10px;}' +
      '.foot{margin-top:22px;font-size:10px;color:#6B7280;border-top:1px solid #D1D5DB;padding-top:8px;}' +
      '@media print{.noprint{display:none}}' +
      '</style></head><body>' + html +
      '<div class="foot">Reliance Asset FieldOps · ' + U.esc(title) + ' · Generated ' +
      new Date().toLocaleString('en-IN') + ' by ' + U.esc((RA.store.me() || {}).name || '') +
      ' · Confidential</div>' +
      '<script>setTimeout(function(){window.print();},350);<\/script></body></html>');
    w.document.close();
  };

  /* ---------- small helpers ---------- */
  U.field = function (label, html) {
    return '<div class="fld"><div class="input-label">' + U.esc(label) + '</div>' + html + '</div>';
  };
  U.input = function (id, placeholder, value, type) {
    return '<input class="input-field" id="' + id + '" type="' + (type || 'text') + '" placeholder="' +
      U.esc(placeholder || '') + '" value="' + U.esc(value || '') + '" />';
  };
  U.select = function (id, options, value) {
    return '<select class="input-field" id="' + id + '">' + options.map(function (o) {
      var v = typeof o === 'string' ? o : o.v, l = typeof o === 'string' ? o : o.l;
      return '<option value="' + U.esc(v) + '"' + (String(v) === String(value) ? ' selected' : '') + '>' + U.esc(l) + '</option>';
    }).join('') + '</select>';
  };
  U.val = function (id) { var e = document.getElementById(id); return e ? e.value.trim() : ''; };

  U.table = function (headers, rows, opts) {
    opts = opts || {};
    if (!rows.length) return U.empty(opts.icon || '📋', opts.emptyTitle || 'Nothing here yet', opts.emptySub || '');
    return '<div class="table-wrap"><table class="tbl"><thead><tr>' +
      headers.map(function (h) { return '<th>' + U.esc(h) + '</th>'; }).join('') +
      '</tr></thead><tbody>' +
      rows.map(function (r) {
        var attrs = r.__attrs || '';
        var cells = r.__cells || r;
        return '<tr ' + attrs + '>' + cells.map(function (c) { return '<td>' + c + '</td>'; }).join('') + '</tr>';
      }).join('') +
      '</tbody></table></div>';
  };

})(window.RA = window.RA || {});
