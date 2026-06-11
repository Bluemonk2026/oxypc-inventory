// OxyPC Inventory — General JS

// Auto-dismiss alerts after 4 seconds
document.addEventListener('DOMContentLoaded', function () {
  setTimeout(function () {
    document.querySelectorAll('.alert.alert-success, .alert.alert-info').forEach(function (el) {
      var bsAlert = bootstrap.Alert.getOrCreateInstance(el);
      if (bsAlert) bsAlert.close();
    });
  }, 4000);

  // Sidebar toggle
  var toggleBtn = document.getElementById('sidebarToggle');
  var sidebar = document.getElementById('sidebar');
  if (toggleBtn && sidebar) {
    toggleBtn.addEventListener('click', function () {
      sidebar.classList.toggle('collapsed');
    });
  }

  // Currency formatting helper (Indian Rupees)
  window.formatINR = function (amount) {
    return '₹' + Number(amount).toLocaleString('en-IN', { maximumFractionDigits: 0 });
  };

  // Confirm destructive actions
  document.querySelectorAll('[data-confirm]').forEach(function (el) {
    el.addEventListener('click', function (e) {
      if (!confirm(el.dataset.confirm || 'Are you sure?')) {
        e.preventDefault();
      }
    });
  });

  // Initialize all DataTables not already initialized
  if (typeof $.fn.DataTable !== 'undefined') {
    $('table.auto-datatable').DataTable({ pageLength: 25 });
  }

  // Highlight active nav
  var path = window.location.pathname;
  document.querySelectorAll('#sidebar .nav-link').forEach(function (link) {
    if (link.getAttribute('href') === path) {
      link.classList.add('active');
    }
  });
});
