// Shared wiring for the checkbox multiselect dropdown filter
// (templates/_multiselect_filter.html). Each dropdown writes a
// comma-separated value into its hidden input, so the GET form still
// submits one parameter per field and the server keeps a plain string
// signature. Clicking inside the menu must not close it — the whole point
// is ticking several boxes before searching.
(function () {
  function sync(wrap) {
    var name = wrap.getAttribute('data-ms');
    var boxes = wrap.querySelectorAll('.ms-opt');
    var picked = [];
    boxes.forEach(function (b) { if (b.checked) picked.push(b.value); });
    document.getElementById('ms_val_' + name).value = picked.join(',');
    var label = wrap.querySelector('.ms-label');
    label.textContent = picked.length
      ? picked.length + ' selected'
      : label.getAttribute('data-all') || label.textContent;
  }
  document.querySelectorAll('.ms-filter').forEach(function (wrap) {
    // Filter bars that scroll horizontally (overflow-auto/overflow-x:auto,
    // e.g. WorkID Status's one-row filter bar) clip Bootstrap's dropdown-menu
    // vertically because Popper's default 'absolute' strategy is measured
    // against that scrollable ancestor. 'fixed' positions the menu relative
    // to the viewport instead, so it escapes the clip and overlaps the card
    // like every other dropdown. Harmless on non-scrolling filter bars too.
    var toggle = wrap.querySelector('[data-bs-toggle="dropdown"]');
    var menu = wrap.querySelector('.dropdown-menu');
    if (toggle && window.bootstrap && window.bootstrap.Dropdown) {
      window.bootstrap.Dropdown.getOrCreateInstance(toggle, {
        popperConfig: function (defaultConfig) {
          return Object.assign({}, defaultConfig, { strategy: 'fixed' });
        }
      });
      // The menu's `min-width:100%` (see _multiselect_filter.html) resolves
      // against the toggle's own width under the default 'absolute' strategy,
      // but against the viewport once Popper switches to 'fixed' — blowing
      // the menu out to full page width. Pin it to the toggle's actual
      // rendered width on every open instead.
      toggle.addEventListener('show.bs.dropdown', function () {
        var w = toggle.getBoundingClientRect().width;
        menu.style.width = w + 'px';
        menu.style.minWidth = w + 'px';
      });
    }
    var label = wrap.querySelector('.ms-label');
    if (!label.getAttribute('data-all') && !wrap.querySelectorAll('.ms-opt:checked').length) {
      label.setAttribute('data-all', label.textContent.trim());
    } else if (!label.getAttribute('data-all')) {
      // Something is already selected on load, so recover the "All X" wording
      // from the button id rather than the current "n selected" text.
      label.setAttribute('data-all', 'All');
    }
    wrap.addEventListener('change', function (e) {
      if (e.target.classList.contains('ms-opt')) sync(wrap);
    });
    wrap.querySelector('.ms-all').addEventListener('click', function () {
      wrap.querySelectorAll('.ms-opt').forEach(function (b) { b.checked = true; });
      sync(wrap);
    });
    wrap.querySelector('.ms-none').addEventListener('click', function () {
      wrap.querySelectorAll('.ms-opt').forEach(function (b) { b.checked = false; });
      sync(wrap);
    });
    wrap.querySelector('.dropdown-menu').addEventListener('click', function (e) {
      e.stopPropagation();
    });
  });
})();
