/* Global Table behavior — one call layers the standard OxyPC heavy-table UX
 * onto a server-side DataTables instance:
 *
 *   1. Headers stay on a single line; DataTables' own autoWidth then sizes
 *      each column around that (plus clamped body content) instead of
 *      wrapping headers and squashing the grid.
 *   2. Horizontal scroll (scrollX) with the first column frozen via CSS
 *      position:sticky — see .gtable-scroll-wrap in app.css. No FixedColumns
 *      plugin needed: DataTables' own scrollX split (cloned header table +
 *      body table, kept in sync) already gives sticky positioning something
 *      to stick to in both halves. If the first column is a checkbox
 *      (auto-detected), the second column freezes too — a lone frozen
 *      checkbox does nothing to keep the row identifiable while scrolled,
 *      so its neighbor (usually the Tag Number) comes along with it. The
 *      second column's stick offset is measured from the real rendered
 *      width of column 1, not assumed, since that varies per table.
 *   3. Table fills the card at 100% width; scrollX takes over once real
 *      column widths exceed that instead of squashing them.
 *   4. Page length defaults to 12 (matches the site-wide DataTables default
 *      already set in base.html — restated here so this module works even
 *      if that default ever changes).
 *   5. Any cell at or over 32 characters of plain text (no markup — badges, links,
 *      and buttons are left alone) gets wrapped to 2 lines with the full
 *      value in a native title= tooltip — cheap at any row count, unlike a
 *      Bootstrap Tooltip instance per cell. Applies to every column by
 *      default; opts.clampColumns restricts it to specific columns instead.
 *   6. Table-top toolbar, left side: "Page view" (length) dropdown + a
 *      warning-badge filtered-row-count, then (optional, caller-added via a
 *      dom override) entity/category breakdown badges right after the count.
 *      Right side: search/scan box + pagination, then (optional, same
 *      mechanism) any buttons or checkboxes this table needs in its own
 *      toolbar — e.g. Cosmetic Received's admin-only Assign button and its
 *      Failed-from-Final-QC filter checkbox, prepended into .dataTables_filter.
 *      14px default text size (down from the 16px browser default); the
 *      last (Action) column is always centered, and the first column
 *      centers too but ONLY when it's a checkbox (.gtable-checkbox-first,
 *      set below from the rendered first body cell) — a real first column
 *      (a name, a tag number, ...) stays left-aligned. See app.css.
 *   7. Optional scan-to-select: hijacks DataTables' own search box (so
 *      "Scan or Search" is one field, not two) and wires the existing
 *      initScanSelect / initTagScanAutocheck helpers from
 *      tag-scan-autocheck.js onto it.
 *   8. Cross-browser by construction, not by browser-specific CSS: the
 *      frozen-column sticky header (point 2) relies only on standard
 *      position:sticky plus border-collapse:separate (already forced by
 *      DataTables' own bootstrap5 CSS on table.dataTable) — both work
 *      identically in Chrome, Edge, Safari, and Firefox, so no vendor
 *      prefixes or per-browser overrides exist or should be added here.
 *      The one real cross-browser failure mode found in production
 *      (2026-09-03) wasn't a rendering gap at all: this file is cache-
 *      busted via base.html's ?v={{ ASSET_VERSION }} stamp, and that
 *      stamp is computed in templates_config.py's _VERSIONED_ASSETS list
 *      — editing this file without also touching one of the other listed
 *      assets used to leave the stamp unchanged, so a browser that had
 *      already cached an older copy kept running it indefinitely (seen
 *      as the sticky header working in one browser but not another,
 *      both on the same deployed HEAD). global-table.js is now itself
 *      one of the files that stamp is derived from — see
 *      templates_config.py and tests/test_asset_version_cache_busting.py
 *      — so any future edit here always reaches every browser on next
 *      load. Keep it there if this file is ever renamed or split.
 *   9. Button labels never wrap to a 2nd line, icon or no icon — enforced
 *      in app.css, not here: `.gtable tbody td:last-child` (the Action
 *      column) inherits white-space:nowrap down onto every button inside
 *      it, and `.gtable-top .btn, .gtable-top button` covers the table-top
 *      toolbar (Assign, the admin bulk-Assign button, any caller-injected
 *      control prepended into .dataTables_filter) the same way — both
 *      areas are flex-wrap rows a narrow viewport can otherwise shrink a
 *      button below its own label's width. The caller-authored card-header
 *      convention below is a different piece of markup (outside what
 *      initGlobalTable touches) — give its own buttons a `text-nowrap`
 *      class if they're ever long enough to be at risk.
 *
 * Convention (not enforced here — the title text and any buttons/filters are
 * page-specific, so this is markup the caller writes, not something
 * initGlobalTable can inject): wrap the table in a plain Bootstrap card and
 * give it a
 * `card-header bg-transparent d-flex justify-content-between align-items-center`
 * with an icon + title on the left (e.g. "All Tags Inventory") and, only if
 * this table has action buttons and/or filter controls of its own, those on
 * the right — action buttons (e.g. Devices' Delete Selected/Customise/
 * Upload Tags/Export CSV, same header shape as
 * templates/cosmetic/received.html's "Devices in {{ stage_label }}" bar) OR
 * filter controls (e.g. L1/L2's whole Search/CPU/RAM/Hard Drive/Lot/PNA/
 * Failed-from-Final-QC bar, or QC's single Failed-from-Final-QC checkbox —
 * both server-rendered directly rather than JS-injected into
 * .dataTables_filter, moved there 2026-09-03 for exactly this reason) OR
 * both together. Never a plain count badge here — the table-top toolbar's
 * own row-count badge (point 6 above) already covers that; a repeated
 * number in the header adds nothing. Every page adopting the Global Table
 * module should follow this.
 *
 * Every plain DataTables option (ajax, columns, order, drawCallback, ...)
 * still passes straight through via dtOptions — this only supplies shared
 * defaults and never overwrites a caller's own columnDefs/drawCallback.
 *
 *   tableSelector      - e.g. '#devicesTable'
 *   dtOptions          - DataTables options; overrides the defaults below
 *                        (a caller-supplied `dom` or `language` fully/partly
 *                        replaces the corresponding default — see $.extend).
 *   opts.clampColumns  - column indices to restrict the >32-character
 *                        clamp+tooltip to (default: every column).
 *   opts.clampLength   - character threshold before a cell clamps+tooltips
 *                        (default: 32).
 *   opts.freeze        - pass false to opt out of scrollX + the frozen
 *                        first column (default: on).
 *   opts.scan          - { inputId, selection, checkboxSelector, onChange, placeholder }
 *                        if given, wires scan-to-select onto the table's own
 *                        search box. `selection` is the caller's Set of
 *                        selected row values (server-side tables only keep
 *                        the current page in the DOM, so selection state
 *                        has to live outside it) and `onChange` is called
 *                        after the Set changes, to refresh count badges.
 *
 * Returns the DataTables API instance.
 */

// Custom page-number pattern (2026-09-03), registered once at load: near
// either end shows only the first/last 2 pages before the ellipsis (down
// from DataTables' own default of 5), and away from both ends shows just
// the current page between two ellipses — no "current-1 / current+1"
// neighbors. Not achievable by tuning DataTables' built-in
// $.fn.dataTable.ext.pager.numbers_length alone: that single value drives
// both the edge-page count AND the middle window size together, and the
// only setting that gives edge-count 2 (numbers_length=4) also has a real
// gap — landing exactly on page 3 of a large table falls in DataTables'
// own "near start" branch, whose window ([1,2]) doesn't include page 3, so
// the active page is never highlighted at all. This custom pager avoids
// that by switching to the "current page alone" pattern as soon as the
// current page falls outside the 2-page edge window, instead of at a
// fixed page-index threshold.
$.fn.dataTable.ext.pager.gtable_numbers = function (page, pages) {
  var LEADING = 2;
  var nums;
  if (pages <= LEADING + 2) {
    // Small enough that ellipsis wouldn't save anything — show every page.
    nums = [];
    for (var i = 0; i < pages; i++) nums.push(i);
  } else if (page < LEADING) {
    nums = [];
    for (var j = 0; j < LEADING; j++) nums.push(j);
    nums.push('ellipsis');
    nums.push(pages - 1);
  } else if (page >= pages - LEADING) {
    nums = [0, 'ellipsis'];
    for (var k = pages - LEADING; k < pages; k++) nums.push(k);
  } else {
    nums = [0, 'ellipsis', page, 'ellipsis', pages - 1];
  }
  nums.DT_el = 'span';
  return ['previous', nums, 'next'];
};

function initGlobalTable(tableSelector, dtOptions, opts) {
  opts = opts || {};
  dtOptions = dtOptions || {};
  var $table = $(tableSelector);
  $table.addClass('gtable');

  var clampLength = opts.clampLength || 32;
  var columnDefs = (dtOptions.columnDefs || []).slice();
  columnDefs.push({
    // No clampColumns given → every column. HTML-bearing cells (badges,
    // links, buttons — the norm for id/status/action columns) are always
    // left untouched regardless of length; only cells DataTables would
    // otherwise render as bare text are candidates for clamping.
    targets: (opts.clampColumns && opts.clampColumns.length) ? opts.clampColumns : '_all',
    render: function (data, type) {
      if (type !== 'display' || data === null || data === undefined) return data;
      var text = String(data);
      // < not <= : a value of exactly clampLength characters (e.g. a CPU
      // string landing right at 32) still clamps — "at or over" the
      // threshold, not strictly "over" it. Found 2026-09-02: real CPU values
      // cluster right around this boundary ("Intel Core i7-10810U @ 1.61 GHz"
      // is exactly 32 chars) and were silently slipping through untouched.
      if (text.length < clampLength || text.indexOf('<') !== -1) return data;
      var escaped = $('<div>').text(text).html().replace(/"/g, '&quot;');
      return '<span class="gtable-clamp2" title="' + escaped + '">' + text + '</span>';
    },
  });

  var freeze = opts.freeze !== false;
  var base = {
    pageLength: 12,
    pagingType: 'gtable_numbers',
    dom: '<"gtable-top d-flex justify-content-between align-items-center flex-wrap gap-2 mb-2"' +
           '<"d-flex align-items-center flex-wrap gap-2"li>' +
           '<"d-flex align-items-center flex-wrap gap-2"fp>' +
         '>rt',
    language: {
      search: '',
      lengthMenu: 'Page view: _MENU_',
      info: '<span class="badge text-bg-warning gtable-count-badge">_TOTAL_</span>',
      infoEmpty: '<span class="badge text-bg-warning gtable-count-badge">0</span>',
      infoFiltered: '',
      // Chevron icons instead of "Previous"/"Next" text — the page-number
      // links (1, 2, ..., last) are untouched, this only swaps the two
      // end buttons.
      paginate: {
        previous: '<i class="bi bi-chevron-left"></i>',
        next: '<i class="bi bi-chevron-right"></i>',
      },
    },
  };
  if (freeze) base.scrollX = true;

  var merged = $.extend(true, {}, base, dtOptions);
  merged.columnDefs = columnDefs; // set post-merge — array-of-objects deep-extend would merge by index, not append

  var dt = $table.DataTable(merged);

  // Column 1 centers (app.css .gtable-checkbox-first) only when it's
  // actually a checkbox — every other table's first column is real content
  // (a name, a tag number, ...) and stays left-aligned like any other
  // column. Detected from the rendered cell, not assumed, so this works
  // regardless of whether the caller mentions checkboxes at all. Runs
  // independently of opts.freeze so the alignment rule doesn't depend on
  // scrollX being enabled.
  var markCheckboxFirstColumn = function () {
    var $firstBodyCell = $table.find('tbody tr:first-child td:first-child');
    var isCheckbox = $firstBodyCell.find('input[type="checkbox"]').length > 0;
    $table.toggleClass('gtable-checkbox-first', isCheckbox);
    return isCheckbox;
  };
  dt.on('draw.dt', markCheckboxFirstColumn);
  markCheckboxFirstColumn();

  if (freeze) {
    var $scrollWrap = $table.closest('.dataTables_scroll').addClass('gtable-scroll-wrap');
    // Freeze 2 columns when the first is a checkbox (a lone frozen checkbox
    // can't identify the row on its own), otherwise just the 1st. Reuses
    // the same checkbox check above rather than re-detecting it.
    var applyFreezeWidth = function () {
      var twoCols = $table.hasClass('gtable-checkbox-first');
      $scrollWrap.attr('data-freeze-cols', twoCols ? 2 : 1);
      if (twoCols) {
        var $firstBodyCell = $table.find('tbody tr:first-child td:first-child');
        var width = $firstBodyCell.outerWidth() || 0;
        $scrollWrap.get(0).style.setProperty('--gtable-col2-left', width + 'px');
      }
    };
    dt.on('draw.dt', applyFreezeWidth);
    applyFreezeWidth();
  }

  if (opts.scan && opts.scan.inputId) {
    var checkboxSelector = opts.scan.checkboxSelector || '.rowChk';
    $(dt.table().container()).find('input[type="search"]').first()
      .attr({ id: opts.scan.inputId, placeholder: opts.scan.placeholder || 'Scan Tag Number, or search…', autocomplete: 'off' })
      .addClass('font-monospace')
      .off();
    initScanSelect({
      inputId: opts.scan.inputId, dt: dt,
      tableSelector: tableSelector, checkboxSelector: checkboxSelector,
      selection: opts.scan.selection, onChange: opts.scan.onChange,
    });
    initTagScanAutocheck({
      inputId: opts.scan.inputId, tableSelector: tableSelector,
      rowCheckboxSelector: checkboxSelector,
    });
  }

  return dt;
}
