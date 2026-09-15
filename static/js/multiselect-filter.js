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
