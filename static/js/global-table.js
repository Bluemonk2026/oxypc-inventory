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
 *      14px default text size (down from the 16px browser default) and the
 *      first/last (checkbox/Action) columns centered — see app.css.
 *   7. Optional scan-to-select: hijacks DataTables' own search box (so
 *      "Scan or Search" is one field, not two) and wires the existing
 *      initScanSelect / initTagScanAutocheck helpers from
 *      tag-scan-autocheck.js onto it.
 *
 * Convention (not enforced here — the title text and any buttons are
 * page-specific, so this is markup the caller writes, not something
 * initGlobalTable can inject): wrap the table in a plain Bootstrap card and
 * give it a
 * `card-header bg-transparent d-flex justify-content-between align-items-center`
 * with an icon + title on the left (e.g. "All Tags Inventory") and, only if
 * this table has action buttons of its own (e.g. Devices' Delete Selected/
 * Customise/Upload Tags/Export CSV), those on the right — same header shape
 * as templates/cosmetic/received.html's "Devices in {{ stage_label }}" bar.
 * Never a plain count badge here — the table-top toolbar's own row-count
 * badge (point 6 above) already covers that; a repeated number in the
 * header adds nothing. Every page adopting the Global Table module should
 * follow this.
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
    },
  };
  if (freeze) base.scrollX = true;

  var merged = $.extend(true, {}, base, dtOptions);
  merged.columnDefs = columnDefs; // set post-merge — array-of-objects deep-extend would merge by index, not append

  var dt = $table.DataTable(merged);

  if (freeze) {
    var $scrollWrap = $table.closest('.dataTables_scroll').addClass('gtable-scroll-wrap');
    // Freeze 2 columns when the first is a checkbox (a lone frozen checkbox
    // can't identify the row on its own), otherwise just the 1st. Detected
    // from the rendered cell, not assumed, so this works for any table
    // regardless of whether the caller mentions checkboxes at all.
    var applyFreezeWidth = function () {
      var $firstBodyCell = $table.find('tbody tr:first-child td:first-child');
      var twoCols = $firstBodyCell.find('input[type="checkbox"]').length > 0;
      $scrollWrap.attr('data-freeze-cols', twoCols ? 2 : 1);
      if (twoCols) {
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
