// Shared wiring for the checkbox multiselect dropdown filter
// (templates/_multiselect_filter.html). Each dropdown writes a
// comma-separated value into its hidden input, so the GET form still
// submits one parameter per field and the server keeps a plain string
// signature. Clicking inside the menu must not close it — the whole point
// is ticking several boxes before searching.
(function () {
  // app.css sets `zoom: var(--app-zoom)` (0.9) on <body> for its compact-UI
  // scale. getBoundingClientRect() on the toggle already returns the final,
  // post-zoom viewport position — but the menu we're about to position is
  // ALSO appended into that same zoomed <body>, so Chromium re-applies the
  // zoom to its own left/top a second time (e.g. left:439px renders at
  // 439*0.9=395px). Dividing by the zoom factor before assigning left/top
  // cancels that second application out. Confirmed empirically: with zoom
  // active, an unadjusted menu opened ~10% up-and-left of its own toggle —
  // "flying onto another dropdown" for filter bars with several toggles in
  // a row, since 10% of the row width lands roughly on the neighboring one.
  function zoomFactor() {
    var v = parseFloat(getComputedStyle(document.documentElement).getPropertyValue('--app-zoom'));
    return v > 0 ? v : 1;
  }
  function sync(wrap, menu) {
    var name = wrap.getAttribute('data-ms');
    var boxes = menu.querySelectorAll('.ms-opt');
    var picked = [];
    boxes.forEach(function (b) { if (b.checked) picked.push(b.value); });
    document.getElementById('ms_val_' + name).value = picked.join(',');
    var label = wrap.querySelector('.ms-label');
    label.textContent = picked.length
      ? picked.length + ' selected'
      : label.getAttribute('data-all') || label.textContent;
  }
  document.querySelectorAll('.ms-filter').forEach(function (wrap) {
    var toggle = wrap.querySelector('[data-bs-toggle="dropdown"]');
    var menu = wrap.querySelector('.dropdown-menu');
    if (toggle && menu && window.bootstrap && window.bootstrap.Dropdown) {
      // Filter bars that scroll horizontally (overflow-auto, e.g. WorkID
      // Status's one-row filter bar) clip a normally-positioned
      // dropdown-menu — content overflowing an overflow:auto ancestor gets
      // clipped no matter how the child itself is positioned. `display:
      // 'static'` tells Bootstrap to skip Popper's own positioning (Popper
      // still runs internally but never writes styles to the menu), which
      // leaves us free to move the menu to <body> and position it ourselves
      // with position:fixed, computed straight off the toggle's own rect —
      // escaping the clip and lining up with the field exactly like every
      // dropdown outside a scrolling container (e.g. /devices' filters).
      window.bootstrap.Dropdown.getOrCreateInstance(toggle, { display: 'static' });
      toggle.addEventListener('show.bs.dropdown', function () {
        var r = toggle.getBoundingClientRect();
        var z = zoomFactor();
        menu.style.position = 'fixed';
        menu.style.margin = '0';
        menu.style.left = (r.left / z) + 'px';
        menu.style.top = ((r.bottom + 2) / z) + 'px';
        menu.style.width = (r.width / z) + 'px';
        menu.style.minWidth = (r.width / z) + 'px';
        document.body.appendChild(menu);
      });
      toggle.addEventListener('hidden.bs.dropdown', function () {
        wrap.appendChild(menu);
        menu.style.position = '';
        menu.style.margin = '';
        menu.style.left = '';
        menu.style.top = '';
        menu.style.width = '';
        menu.style.minWidth = '';
      });
    }
    var label = wrap.querySelector('.ms-label');
    if (!label.getAttribute('data-all') && !menu.querySelectorAll('.ms-opt:checked').length) {
      label.setAttribute('data-all', label.textContent.trim());
    } else if (!label.getAttribute('data-all')) {
      // Something is already selected on load, so recover the "All X" wording
      // from the button id rather than the current "n selected" text.
      label.setAttribute('data-all', 'All');
    }
    // Attached to the menu itself (not `wrap`) since the menu is reparented
    // to <body> while open — a delegated listener on `wrap` would stop
    // seeing bubbled events the moment the checkboxes are no longer its
    // descendants. Listeners stay bound to a node across reparenting, so
    // this keeps working regardless of where the menu currently lives.
    menu.addEventListener('change', function (e) {
      if (e.target.classList.contains('ms-opt')) sync(wrap, menu);
    });
    menu.querySelector('.ms-all').addEventListener('click', function () {
      menu.querySelectorAll('.ms-opt').forEach(function (b) { b.checked = true; });
      sync(wrap, menu);
    });
    menu.querySelector('.ms-none').addEventListener('click', function () {
      menu.querySelectorAll('.ms-opt').forEach(function (b) { b.checked = false; });
      sync(wrap, menu);
    });
    menu.addEventListener('click', function (e) {
      e.stopPropagation();
    });
  });
})();
