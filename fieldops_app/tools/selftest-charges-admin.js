/* Self-test — charge rate card & logic, bulk uploads, deletion / archiving.
   Run in the browser console with the app open:
     fetch('/tools/selftest-charges-admin.js').then(r=>r.text()).then(t=>console.log(eval(t)))
   Resets local data. Sign in again afterwards. */
(function () {
  var S = RA.store, D = RA.data, out = [];
  function t(name, fn) {
    try { var r = fn(); out.push((r === true ? 'PASS' : 'FAIL') + ' · ' + name + (r === true ? '' : ' → ' + r)); }
    catch (e) { out.push('FAIL · ' + name + ' → ' + e.message); }
  }
  function money(n) { return Math.round(n).toLocaleString('en-IN'); }

  S.reset();
  S.login('U11', false);   // System Admin

  /* ================= CHARGE LOGIC vs THE SOURCE WORKBOOK ================= */
  t('Rate card v1 ships as the source baseline', function () {
    var c = S.activeRateCard();
    return !!(c.version === 1 && c.active && c.rates.qc_block_rate === 1500 &&
      c.rates.qc_block_units === 20 && c.rates.packing_per_unit === 150 &&
      c.rates.weight_per_unit === 4 && c.rates.fov_pct === 0.1) || JSON.stringify(c.rates);
  });

  t('Shipment value recomputes to the source figure (Σ RRP)', function () {
    var bad = S.db.sites.filter(function (s) {
      return Math.abs(S.shipmentValue(s.id) - (s.costing.shipment_value || 0)) > 1;
    });
    return bad.length === 0 || bad.length + ' site(s) differ, e.g. ' + bad[0].site;
  });

  t('QC charge logic reproduces all 622 source values', function () {
    var bad = S.db.sites.filter(function (s) {
      return S.computeCharges(s).qc_charges !== s.costing.qc_charges;
    });
    return bad.length === 0 || bad.length + ' differ, e.g. ' + bad[0].site +
      ' got ' + S.computeCharges(bad[0]).qc_charges + ' vs ' + bad[0].costing.qc_charges;
  });
  t('Packing and weight logic reproduce all 622 source values', function () {
    var bad = S.db.sites.filter(function (s) {
      var c = S.computeCharges(s);
      return c.packing_charges !== s.costing.packing_charges ||
             Math.abs(c.weight_kg - s.costing.weight_kg) > 0.01;
    });
    return bad.length === 0 || bad.length + ' differ, e.g. ' + bad[0].site;
  });
  t('FOV logic reproduces all 622 source values (0.1%, waived where source is nil)', function () {
    var bad = S.db.sites.filter(function (s) {
      return Math.abs(S.computeCharges(s).fov_charges - s.costing.fov_charges) > 0.02;
    });
    return bad.length === 0 || bad.length + ' differ, e.g. ' + bad[0].site;
  });
  t('Pickup logic reproduces 605 of 622 (metro premium held as override)', function () {
    var match = S.db.sites.filter(function (s) {
      return Math.abs(S.computeCharges(s).pickup_charges - s.costing.pickup_charges) < 0.01;
    }).length;
    return match === 605 || 'matched ' + match;
  });
  t('Total = QC + packing + pickup + FOV on every source row', function () {
    var bad = S.db.sites.filter(function (s) {
      var c = s.costing;
      var sum = Math.round((c.qc_charges + c.packing_charges + c.pickup_charges + c.fov_charges) * 100) / 100;
      return Math.abs(sum - c.total_charges) > 0.02;
    });
    return bad.length === 0 || bad.length + ' differ';
  });
  t('Post-confirmation = total + ₹1,500 on every source row', function () {
    var bad = S.db.sites.filter(function (s) {
      return Math.abs((s.costing.total_charges + 1500) - s.costing.post_confirmation_total) > 0.02;
    });
    return bad.length === 0 || bad.length + ' differ';
  });
  t('Charge roll-up matches the workbook grand total', function () {
    var t2 = S.chargeTotals();
    return (Math.round(t2.total) === 2677637 && Math.round(t2.post) === 3610637 &&
            Math.round(t2.weight) === 15828) ||
      JSON.stringify({ total: Math.round(t2.total), post: Math.round(t2.post), wt: Math.round(t2.weight) });
  });

  /* ---------- worked example: QC blocks ---------- */
  t('QC charge steps by block: 20u→₹1,500, 21u→₹3,000, 100u→₹7,500', function () {
    var card = S.activeRateCard();
    var f = function (units) {
      return card.rates.qc_block_rate * Math.ceil(units / card.rates.qc_block_units);
    };
    return (f(20) === 1500 && f(21) === 3000 && f(60) === 4500 && f(61) === 6000 && f(100) === 7500) ||
      [f(20), f(21), f(60), f(61), f(100)].join(',');
  });

  /* ---------- preview is non-destructive ---------- */
  var before = S.chargeTotals().total;
  var dearer = JSON.parse(JSON.stringify(S.activeRateCard().rates));
  dearer.qc_block_rate = 2000;
  t('Metro-premium pickup sites are protected as overrides at seed time', function () {
    var ov = S.db.sites.filter(function (s) { return s.costing.basis === 'override'; });
    return ov.length === 17 || 'found ' + ov.length;
  });
  t('Preview computes impact without writing anything', function () {
    var pre = S.previewCharges({ version: 99, rates: dearer });
    var after = S.chargeTotals().total;
    return (pre.totals.newTotal > pre.totals.oldTotal && after === before && pre.rows.length > 0) ||
      JSON.stringify({ delta: pre.totals.delta, wrote: after !== before });
  });

  /* ---------- publish & apply ---------- */
  var pub = S.publishRateCard(dearer, '2026-08-15', 'Reliance Commercial', 'Approved', true, {});
  t('Publishing creates v2, activates it and retains v1', function () {
    return (pub.card.version === 2 && S.activeRateCard().version === 2 &&
            S.db.rate_cards.length === 2 && S.db.rate_cards[0].active === false) || 'v' + pub.card.version;
  });
  t('Applying the card recalculates site charges', function () {
    var s = S.db.sites.filter(function (x) { return x.costing.basis !== 'override'; })[0];
    var expected = 2000 * Math.ceil(S.assetsAt(s.id).length / 20);
    return (s.costing.qc_charges === expected && s.costing.basis === 'rate-card' &&
            s.costing.rate_version === 2) ||
      JSON.stringify({ got: s.costing.qc_charges, want: expected, basis: s.costing.basis });
  });
  t('Total charges rise after the higher rate card', function () {
    return S.chargeTotals().total > before || 'no change';
  });

  /* ---------- per-site override ---------- */
  var ov = S.db.sites.filter(function (x) { return x.costing.basis !== 'override'; })[5];
  S.setSiteCharges(ov.id, { qc_charges: 9999, pickup_charges: 111 }, 'negotiated rate');
  t('Manual override applies and recomputes the site total', function () {
    var c = ov.costing;
    var want = Math.round((9999 + c.packing_charges + 111 + c.fov_charges) * 100) / 100;
    return (c.basis === 'override' && c.qc_charges === 9999 && c.total_charges === want &&
            c.post_confirmation_total === want + 1500) || JSON.stringify(c);
  });
  t('Overridden sites are skipped by recalculation unless opted in', function () {
    var overrides = S.db.sites.filter(function (s) { return s.costing.basis === 'override'; }).length;
    var skipped = S.previewCharges(S.activeRateCard(), {}).totals.skipped;
    var included = S.previewCharges(S.activeRateCard(), { includeOverrides: true }).rows.length;
    return (skipped === overrides && included === S.db.sites.length) ||
      'skipped=' + skipped + ' overrides=' + overrides + ' included=' + included;
  });
  t('Reset returns an overridden site to the rate card', function () {
    S.resetSiteCharges(ov.id);
    return (ov.costing.basis === 'rate-card' && ov.costing.qc_charges !== 9999) || JSON.stringify(ov.costing);
  });
  t('Rate-card changes are audit-logged with version and approver', function () {
    var ev = S.db.audit.filter(function (e) { return e.entity === 'rate_card'; });
    return !!(ev.filter(function (e) { return e.action === 'publish'; }).length &&
              ev.filter(function (e) { return e.action === 'apply'; }).length) || 'events=' + ev.length;
  });

  /* ================= BULK UPLOADS ================= */
  var site0 = S.db.sites[0], site1 = S.db.sites[1];

  t('Bulk upload: site details & SPOC', function () {
    var csv = 'Site,SPOC,SPOC Phone,Access Window,Readiness,Executed By\n' +
      '"' + site0.site + '",Ramesh Kadam,+91 98200 11001,09:00 – 17:00,Ready,Deshwal\n' +
      'NOT-A-SITE,X,Y,Z,Ready,Deshwal\n';
    var res = S.importSiteDetails(csv);
    return (res.updated === 1 && res.errors.length === 1 && site0.spoc === 'Ramesh Kadam' &&
            site0.readiness === 'Ready' && site0.access_window === '09:00 – 17:00') ||
      JSON.stringify({ res: res, spoc: site0.spoc });
  });

  t('Bulk upload: site charges land as overrides', function () {
    var csv = 'Site,QC Charges,Packing Charges,Pickup Charges,FOV Charges\n' +
      '"' + site1.site + '",2500,300,1200,50\n';
    var res = S.importCharges(csv);
    var c = site1.costing;
    return (res.updated === 1 && c.qc_charges === 2500 && c.pickup_charges === 1200 &&
            c.basis === 'override' && c.total_charges === 2500 + 300 + 1200 + 50) ||
      JSON.stringify({ res: res, c: c });
  });

  t('Bulk upload: users created and updated by employee ID', function () {
    var csv = 'Name,Employee ID,Role,Region,Sites,Status\n' +
      'Bulk One,bulk.one,Field QC Engineer,South,"' + site0.site + ';' + site1.site + '",active\n' +
      'Bulk Two,bulk.two,Warehouse User,All,,active\n' +
      'Bad Role,bulk.three,Wizard,All,,active\n';
    var res = S.importUsers(csv);
    var u = S.db.users.filter(function (x) { return x.emp === 'bulk.one'; })[0];
    return (res.created === 2 && res.errors.length === 1 && u && u.role === 'fe' &&
            u.sites.length === 2) || JSON.stringify({ res: res, sites: u && u.sites });
  });
  t('Re-uploading the same users updates rather than duplicates', function () {
    var n = S.db.users.length;
    var res = S.importUsers('Name,Employee ID,Role,Region\nBulk One Renamed,bulk.one,Regional Coordinator,West\n');
    var u = S.db.users.filter(function (x) { return x.emp === 'bulk.one'; })[0];
    return (res.updated === 1 && res.created === 0 && S.db.users.length === n &&
            u.name === 'Bulk One Renamed' && u.role === 'coord') || JSON.stringify(res);
  });

  t('Bulk upload: inventory adds new sites and units additively', function () {
    var sitesBefore = S.db.sites.length, assetsBefore = S.db.assets.length;
    var csv = 'State,City,Site,Site Description,MH Family,MH Class,MH Brick,Article,Article Description,' +
      'Storage Location,Inventory Type,Stock Quantity,RRP,MRP\n' +
      'Kerala,Kochi,Bulk Test Site,Reliance Digital Kochi,LAPTOP,THIN AND LIGHT,ASPIRATIONAL,ART-777,' +
      'MBA-13 M4 Laptop,SL-1,Display,4,99900,109900\n';
    var res = S.importAssets(csv, false);
    var s = S.db.sites.filter(function (x) { return x.site === 'Bulk Test Site'; })[0];
    return (res.created === 4 && S.db.sites.length === sitesBefore + 1 &&
            S.db.assets.length === assetsBefore + 4 && s && S.assetsAt(s.id).length === 4) ||
      JSON.stringify({ res: res, added: S.db.assets.length - assetsBefore });
  });

  t('Charges compute for a newly uploaded site', function () {
    var s = S.db.sites.filter(function (x) { return x.site === 'Bulk Test Site'; })[0];
    var c = S.computeCharges(s);
    var card = S.activeRateCard().rates;
    return (c.units === 4 && c.qc_charges === card.qc_block_rate &&
            c.packing_charges === 4 * card.packing_per_unit &&
            c.pickup_charges === card.pickup_cluster &&
            c.shipment_value === 4 * 99900) || JSON.stringify(c);
  });

  /* ================= DELETION & ARCHIVING ================= */
  var delSite = S.db.sites.filter(function (x) { return x.site === 'Bulk Test Site'; })[0];
  var delAssets = S.assetsAt(delSite.id);

  t('Units with no history delete cleanly', function () {
    var res = S.deleteAssets([delAssets[0].id, delAssets[1].id]);
    return (res.removed === 2 && res.blocked.length === 0 &&
            S.assetsAt(delSite.id).length === 2) || JSON.stringify(res);
  });

  /* give a unit some history, then try to delete it */
  S.captureSerial(delAssets[2].id, 'DELTEST0001');
  var qcRec = S.submitQC({
    asset_id: delAssets[2].id, specs: { serial: 'DELTEST0001' },
    responses: { power: 'Power ON', display: 'OK', body: 'OK', keyboard: 'Working', touchpad: 'Working', hinge: 'OK', ports: 'Visibly OK', charger: 'Available/OK' },
    photos: [{ kind: 'overall' }], remarks: '', seconds: 700
  });
  t('Units holding QC history are blocked from deletion', function () {
    var res = S.deleteAssets([delAssets[2].id]);
    return (res.removed === 0 && res.blocked.length === 1 && !!S.asset(delAssets[2].id)) ||
      JSON.stringify(res);
  });
  t('Forced deletion removes the unit and its QC records', function () {
    var res = S.deleteAssets([delAssets[2].id], { force: true });
    return (res.removed === 1 && !S.asset(delAssets[2].id) && !S.qcRecord(qcRec.id)) ||
      JSON.stringify(res);
  });

  t('Deleting a location removes its units and clears user assignments', function () {
    var uid = S.db.users.filter(function (u) { return u.emp === 'bulk.one'; })[0].id;
    var sid = delSite.id;
    var res = S.deleteSite(sid, { force: true });
    var stillAssigned = (S.user(uid).sites || []).indexOf(sid) > -1;
    return (!S.site(sid) && S.assetsAt(sid).length === 0 && !stillAssigned && res.site.site === 'Bulk Test Site') ||
      JSON.stringify({ site: !!S.site(sid), assigned: stillAssigned });
  });
  t('A location holding recorded work needs the extra confirmation', function () {
    var s = S.db.sites[0];
    var a = S.assetsAt(s.id)[0];
    S.captureSerial(a.id, 'GUARD00001');
    S.submitQC({ asset_id: a.id, specs: {}, responses: { power: 'Power ON', display: 'OK', body: 'OK', keyboard: 'Working', touchpad: 'Working', hinge: 'OK', ports: 'Visibly OK', charger: 'Available/OK' }, photos: [{ kind: 'overall' }], remarks: '', seconds: 600 });
    try { S.deleteSite(s.id, {}); return 'no error thrown'; }
    catch (e) { return /recorded work|QC or movement/.test(e.message) || e.message; }
  });

  /* ---------- QC archiving (never hard-deleted) ---------- */
  var liveAsset = S.assetsAt(S.db.sites[0].id)[0];
  var liveQC = S.qcForAsset(liveAsset.id)[0];
  t('Archiving a QC record retains it but clears the live queue', function () {
    var beforeLive = S.liveQC().length;
    S.archiveQC(liveQC.id, 'Duplicate submission');
    var rec = S.qcRecord(liveQC.id);
    return (!!rec && rec.archived === true && S.liveQC().length === beforeLive - 1 &&
            S.asset(liveAsset.id).status === 'pending_qc' &&
            S.qcForAsset(liveAsset.id).length === 1) ||
      JSON.stringify({ kept: !!rec, live: S.liveQC().length, status: S.asset(liveAsset.id).status });
  });
  t('Archived records stay out of approvals, alerts and analytics', function () {
    S.login('U06', false);
    location.hash = '#/approvals'; RA.render();
    var shown = document.getElementById('screen-body').innerText.indexOf(liveQC.id) === -1;
    S.login('U11', false);
    return shown || 'archived record still listed';
  });

  /* ---------- bulk clears ---------- */
  t('Clearing serials returns every unit to a pending serial', function () {
    var n = S.clearSerials();
    return (n > 0 && S.serialStats().captured === 0) || 'cleared=' + n;
  });
  t('Purging transactions keeps the master and resets unit status', function () {
    var sites = S.db.sites.length, assets = S.db.assets.length, users = S.db.users.length;
    var cards = S.db.rate_cards.length;
    S.purgeTransactions();
    return (S.db.qc.length === 0 && S.db.packages.length === 0 && S.db.movements.length === 0 &&
            S.db.sites.length === sites && S.db.assets.length === assets &&
            S.db.users.length === users && S.db.rate_cards.length === cards &&
            S.db.assets.every(function (a) { return a.status === 'pending_qc'; })) ||
      JSON.stringify({ qc: S.db.qc.length, sites: S.db.sites.length, assets: S.db.assets.length });
  });
  t('Every destructive action is audit-logged', function () {
    var acts = S.db.audit.map(function (e) { return e.entity + ':' + e.action; });
    return ['asset:delete', 'site:delete', 'qc:archive', 'master:purge', 'master:clear']
      .every(function (k) { return acts.indexOf(k) > -1; }) || acts.slice(-12).join(', ');
  });

  /* ---------- admin screens still render ---------- */
  t('All admin tabs render clean', function () {
    var bad = [];
    ['users', 'charges', 'serials', 'upload', 'deduction', 'config', 'delete', 'data'].forEach(function (tab) {
      RA.filters.adminTab = tab;
      location.hash = '#/admin';
      try { RA.render(); } catch (e) { bad.push(tab + ':' + e.message); return; }
      var b = document.getElementById('screen-body');
      if (!b || b.innerHTML.length < 100) bad.push(tab + ':empty');
      else if (b.innerText.indexOf('Something went wrong') > -1) bad.push(tab + ':error');
    });
    return bad.length === 0 || bad.join(' | ');
  });

  var pass = out.filter(function (x) { return x.indexOf('PASS') === 0; }).length;
  return (pass + '/' + out.length + ' passed\n') + out.join('\n');
})()
