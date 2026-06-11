// OxyPC Inventory — Barcode Scanner Support
// USB barcode scanners act as keyboard: type barcode + Enter
// This script intercepts Enter on .barcode-field inputs and:
//   1. Submits the parent form immediately (no need to click button)
//   2. Optionally fetches device details via AJAX to auto-fill form fields

(function () {
  'use strict';

  var LOOKUP_URL = '/iqc/lookup';

  function lookupDevice(barcode, callback) {
    fetch(LOOKUP_URL + '?barcode=' + encodeURIComponent(barcode))
      .then(function (r) { return r.json(); })
      .then(callback)
      .catch(function () { callback({ found: false }); });
  }

  function autoFillForm(data, form) {
    if (!data.found) return;
    var fields = {
      'brand': data.brand,
      'model': data.model,
      'device_type': data.device_type,
      'serial_no': data.serial_no,
      'ram_gb': data.ram_gb,
      'storage_gb': data.storage_gb,
      'storage_type': data.storage_type,
      'grade': data.grade,
      'lot_id': data.lot_id,
    };
    Object.keys(fields).forEach(function (name) {
      var el = form.querySelector('[name="' + name + '"]');
      if (el && fields[name] !== null && fields[name] !== undefined) {
        el.value = fields[name];
      }
    });

    var infoEl = form.querySelector('.barcode-device-info');
    if (infoEl) {
      infoEl.innerHTML =
        '<span class="badge bg-success me-2">Found</span>' +
        (data.brand || '') + ' ' + (data.model || '') +
        ' &bull; Stage: <strong>' + (data.current_stage || '') + '</strong>' +
        ' &bull; Lot: <strong>' + (data.lot_number || '') + '</strong>';
      infoEl.style.display = 'block';
    }
  }

  document.addEventListener('DOMContentLoaded', function () {
    document.querySelectorAll('.barcode-field').forEach(function (input) {
      // On Enter key: either look up device or submit form
      input.addEventListener('keydown', function (e) {
        if (e.key !== 'Enter') return;
        e.preventDefault();

        var barcode = input.value.trim();
        if (!barcode) return;

        var form = input.closest('form');
        var hasAutoFill = form && form.querySelector('[name="brand"],[name="model"],[name="ram_gb"]');

        if (hasAutoFill) {
          // Auto-fill mode: fetch device details first
          lookupDevice(barcode, function (data) {
            autoFillForm(data, form);
            // Don't auto-submit — let user review and submit
          });
        } else if (form) {
          // Simple submit mode: just submit the form
          form.submit();
        }
      });

      // On change (blur): look up and show info bar
      input.addEventListener('change', function () {
        var barcode = input.value.trim();
        if (!barcode) return;

        var form = input.closest('form');
        if (!form) return;

        lookupDevice(barcode, function (data) {
          if (form.querySelector('[name="brand"]')) {
            autoFillForm(data, form);
          }
          // Show stage info if device-info div exists
          var info = document.getElementById('deviceInfo');
          if (info) {
            if (data.found) {
              info.innerHTML =
                '<span class="badge bg-success me-2">Found</span>' +
                (data.brand || '') + ' ' + (data.model || '') +
                ' — Current Stage: <strong>' + (data.current_stage || '') + '</strong>';
            } else {
              info.innerHTML = '<span class="badge bg-danger">Device not found in system</span>';
            }
          }
        });
      });
    });
  });
})();
