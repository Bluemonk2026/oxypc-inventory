/* Reusable scan/type multi-tag input: auto-checks matching rows in a table
 * and keeps a live selected-count element in sync (both from scanning AND
 * from manual row-checkbox clicks). Used on IQC List, GRN Post-IQC, and
 * Inventory Manager's Inventory Stock table. */
function initTagScanAutocheck({ inputId, tableSelector, rowTagAttr = 'data-tag', countSelector, rowCheckboxSelector = 'input[type="checkbox"]' }) {
  var input = document.getElementById(inputId);
  var table = document.querySelector(tableSelector);
  if (!input || !table) return;

  function updateCount() {
    if (!countSelector) return;
    var countEl = document.querySelector(countSelector);
    if (!countEl) return;
    countEl.textContent = table.querySelectorAll(rowCheckboxSelector + ':checked').length;
  }

  function applyTags() {
    var tags = input.value.split(',').map(function (t) { return t.trim().toUpperCase(); }).filter(Boolean);
    var tagSet = {};
    tags.forEach(function (t) { tagSet[t] = true; });
    table.querySelectorAll('tr[' + rowTagAttr + ']').forEach(function (row) {
      var tag = (row.getAttribute(rowTagAttr) || '').toUpperCase();
      var cb = row.querySelector(rowCheckboxSelector);
      if (cb && tagSet[tag] && !cb.checked) {
        cb.checked = true;
        // Pages often bind their own selected-count logic via a delegated
        // 'change' listener (e.g. jQuery `.on('change', '.rowChk', ...)`) —
        // setting .checked directly doesn't fire that, so dispatch it.
        cb.dispatchEvent(new Event('change', { bubbles: true }));
      }
    });
    updateCount();
  }

  input.addEventListener('input', applyTags);
  input.addEventListener('keydown', function (e) {
    if (e.key === 'Enter') { e.preventDefault(); applyTags(); }
  });
  // Keep the count in sync with manual row-checkbox clicks and "select all" too.
  table.addEventListener('change', function (e) {
    if (e.target.matches(rowCheckboxSelector)) updateCount();
  });
}
