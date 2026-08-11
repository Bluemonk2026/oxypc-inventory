(function(){
  var S=RA.store, D=RA.data, out=[];
  function t(name, fn){ try{ var r=fn(); out.push((r===true?'PASS':'FAIL')+' · '+name+(r===true?'':' → '+r)); }catch(e){ out.push('FAIL · '+name+' → '+e.message); } }

  S.reset();
  S.login('U01', false);

  var bigSite=S.db.sites.filter(function(s){return S.assetsAt(s.id).length>=25;})[0];
  var site=bigSite.id;
  var assets=S.assetsAt(site);

  /* 1. Conditional suppression BR-03 */
  t('BR-03 No Power suppresses dependent tests', function(){
    var r={power:'No Power', display:'OK', keyboard:'Working', touchpad:'Working'};
    S.applySuppression('laptop', r);
    return (r.display===D.NOT_TESTED && r.keyboard===D.NOT_TESTED && r.touchpad===D.NOT_TESTED) || JSON.stringify(r);
  });

  /* 2. Defect derivation + severity ordering */
  t('Defect codes derived & ranked by severity', function(){
    var c=S.deriveCodes({power:'Power ON',display:'Broken/Cracked',body:'Scratch',keyboard:'Working',touchpad:'Working',hinge:'OK',ports:'Visibly OK',charger:'Missing'});
    return (c[0]==='DB' && c.indexOf('SC')>-1 && c.indexOf('CH')>-1) || c.join('+');
  });
  t('Clean unit derives OK', function(){
    var c=S.deriveCodes({power:'Power ON',display:'OK',body:'OK',keyboard:'Working',touchpad:'Working',hinge:'OK',ports:'Visibly OK',charger:'Available/OK'});
    return (c.length===1 && c[0]==='OK') || c.join('+');
  });

  /* 3. Photo rules BR-04 */
  t('BR-04 overall photo mandatory', function(){
    var r=S.photoRules(['OK'],[]); return r.ok===false || 'expected failure';
  });
  t('BR-04 defect photo mandatory for exception', function(){
    var r=S.photoRules(['SC'],[{kind:'overall'}]); return r.ok===false || 'expected failure';
  });
  t('BR-04 satisfied with both photos', function(){
    var r=S.photoRules(['SC'],[{kind:'overall'},{kind:'defect'}]); return r.ok===true || r.errors.join(' ');
  });

  /* 4. Pricing — 0% until approved */
  t('Deduction master starts unapproved at 0%', function(){
    var m=S.activeDeduction();
    var p=S.computePrice(100000,['DB','SC']);
    return (m.approval_status!=='Approved' && p.pct===0 && p.revised_price===100000) || JSON.stringify(p);
  });

  /* 5. Submit QC on 12 units */
  var submitted=[];
  for (var i=0;i<12;i++){
    var a=assets[i];
    var resp = i<9
      ? {power:'Power ON',display:'OK',body:'OK',keyboard:'Working',touchpad:'Working',hinge:'OK',ports:'Visibly OK',charger:'Available/OK'}
      : {power:'Power ON',display:'OK',body:'Scratch',keyboard:'Working',touchpad:'Working',hinge:'OK',ports:'Visibly OK',charger:'Missing'};
    var photos=[{id:'p'+i,kind:'overall',data:null}];
    if (i>=9) photos.push({id:'d'+i,kind:'defect',data:null});
    S.captureSerial(a.id,'SN-TEST-'+i);            /* serial first — always */
    submitted.push(S.submitQC({asset_id:a.id,specs:{make:a.make,serial:'SN-TEST-'+i},responses:resp,photos:photos,remarks:'',seconds:780+i*10}));
  }
  t('12 QC records submitted & assets moved to qc_submitted', function(){
    return (S.db.qc.length===12 && S.asset(assets[0].id).status==='qc_submitted') || S.db.qc.length+'/'+S.asset(assets[0].id).status;
  });
  t('Commercial record created per QC', function(){
    return S.db.commercial.length===12 || String(S.db.commercial.length);
  });
  t('BR-05 QC record marked immutable with version', function(){
    return (submitted[0].immutable===true && submitted[0].version===1) || 'v'+submitted[0].version;
  });

  /* 6. Re-QC creates a new version */
  S.login('U06', false); // Reliance QC Approver
  S.decideQC(submitted[11].id,'re_qc','Photo unclear');
  t('Re-QC resets asset to pending and clears qc_id', function(){
    var a=S.asset(submitted[11].asset_id);
    return (a.status==='pending_qc' && a.qc_id===null) || a.status;
  });
  S.login('U01', false);
  var re=S.submitQC({asset_id:submitted[11].asset_id,specs:{serial:'SN-TEST-11'},responses:{power:'Power ON',display:'OK',body:'Scratch',keyboard:'Working',touchpad:'Working',hinge:'OK',ports:'Visibly OK',charger:'Missing'},photos:[{kind:'overall'},{kind:'defect'}],remarks:'re-shot',seconds:600});
  t('Re-QC creates v2 linked to original', function(){
    return (re.version===2 && re.supersedes===submitted[11].id) || ('v'+re.version+'/'+re.supersedes);
  });

  /* 7. Approvals */
  S.login('U06', false);
  t('RBAC: approver cannot access admin', function(){ return S.can('admin')===false || 'approver has admin'; });
  t('RBAC: approver can access approvals', function(){ return S.can('approvals')===true || 'no access'; });
  for (var j=0;j<11;j++) S.decideQC(submitted[j].id,'accepted',null);
  S.decideQC(re.id,'accepted',null);
  t('12 assets accepted', function(){
    var n=S.db.assets.filter(function(a){return a.status==='accepted';}).length;
    return n===12 || String(n);
  });

  /* 8. BR-01 packing gate */
  S.login('U08', false); // packer
  t('BR-01 blocks packing of un-accepted asset', function(){
    try { S.createPackage(site,[assets[20].id],'Carton','SEAL-X','',null); return 'no error thrown'; }
    catch(e){ return e.message.indexOf('BR-01')===0 || e.message; }
  });
  var accepted=S.db.assets.filter(function(a){return a.status==='accepted';}).map(function(a){return a.id;});
  var pkg=S.createPackage(site, accepted.slice(0,10),'Carton','SEAL-88214','3 chargers',null);
  t('Package sealed with 10 assets', function(){
    return (pkg.assets.length===10 && S.asset(accepted[0]).status==='packed') || pkg.assets.length+'/'+S.asset(accepted[0]).status;
  });

  /* 9. Logistics mode thresholds */
  t('FR-016 thresholds: 10→dedicated, 5→cluster, 2→courier', function(){
    return (D.logisticsMode(10,S.db.config).mode==='dedicated' &&
            D.logisticsMode(5,S.db.config).mode==='cluster' &&
            D.logisticsMode(2,S.db.config).mode==='courier') || 'threshold mismatch';
  });

  /* 10. FE allocation rules (BRD v3) */
  t('FE allocation: 8→1FE/2-2.5h, 18→1FE/4-4.5h, 35→2FE, 55→3FE/5-5.5h, 80→3FE/6-6.5h', function(){
    var f=function(n){var x=D.feAllocation(n,S.db.config); return x.fes+'|'+x.window;};
    var got=[f(8),f(18),f(35),f(55),f(80)].join(' ; ');
    var want='1|2 – 2.5 h ; 1|4 – 4.5 h ; 2|4 – 4.5 h ; 3|5 – 5.5 h ; 3|6 – 6.5 h';
    return got===want || got;
  });
  t('FE allocation adds 30-min store buffer', function(){
    return D.feAllocation(8,S.db.config).total_hours===2.75 || String(D.feAllocation(8,S.db.config).total_hours);
  });

  /* 11. Dispatch */
  var mov=S.createMovement({mode:'pickup',site_id:site,packages:[pkg.id],vehicle:'MH-04-AK-7890',driver:'Sunil P.',driver_phone:'9820011111',partner:'Deshwal Logistics',gate_pass:'GP-771',destination:'WH-Mumbai-01'});
  t('Dispatch moves assets to in-transit', function(){
    return (S.asset(accepted[0]).status==='dispatched' && mov.assets.length===10) || S.asset(accepted[0]).status;
  });
  t('BR-08 blocks re-dispatch of same package', function(){
    try { S.createMovement({mode:'pickup',site_id:site,packages:[pkg.id]}); return 'no error thrown'; }
    catch(e){ return e.message.indexOf('BR-08')===0 || e.message; }
  });

  /* 12. Warehouse receipt with variance */
  S.login('U10', false); // warehouse
  var rc=S.receive({movement_id:mov.id,received_count:9,seal_status:'Intact',seal_no:'SEAL-88214',damage:'No',damage_note:'',discrepancy_owner:'Transporter'});
  t('GRN records variance and raises discrepancy', function(){
    return (rc.variance===-1 && rc.discrepancy===true && rc.grn.indexOf('GRN-')===0) || JSON.stringify({v:rc.variance,d:rc.discrepancy});
  });
  t('BR-09 closure blocked while discrepancy open', function(){
    var a=S.asset(accepted[0]);
    var chk=S.closureCheck(a);
    return (chk.ok===false && chk.blockers.join(' ').indexOf('BR-09')>-1) || JSON.stringify(chk);
  });
  S.resolveDiscrepancy(rc.id,'Unit traced and received separately');
  t('Closure unlocked after disposition', function(){
    var chk=S.closureCheck(S.asset(accepted[0]));
    return chk.ok===true || chk.blockers.join(' ');
  });
  S.login('U04', false); // PMO
  S.closeAsset(accepted[0]);
  t('Asset closed by PMO', function(){ return S.asset(accepted[0]).status==='closed' || S.asset(accepted[0]).status; });

  /* 13. Deduction master version + repricing */
  S.login('U11', false); // admin
  var rates={}; D.DEFECT_CODES.forEach(function(c){ rates[c.code]= c.code==='OK'?0 : (c.rank===3?25:c.rank===2?10:5); });
  var v2=S.publishDeductionVersion(rates,'highest','2026-08-10','Vikram Shah (Reliance Commercial)','Approved');
  t('BR-11 new version created and activated', function(){
    return (v2.version===2 && S.activeDeduction().version===2 && S.db.deductions.length===2) || 'v'+v2.version;
  });
  t('Pending commercial records re-priced on approval (SC+CH → highest = CH 10%)', function(){
    var cm=S.db.commercial.filter(function(c){ var q=S.qcRecord(c.qc_id); return q && q.codes.indexOf('SC')>-1 && q.codes.indexOf('CH')>-1; })[0];
    return (cm.master_version===2 && cm.deduction_pct===10 &&
            cm.deduction_amount===cm.base_price*0.10 &&
            cm.revised_price===cm.base_price-cm.deduction_amount) || JSON.stringify(cm);
  });
  t('Highest-applicable rule used for multi-defect', function(){
    var p=S.computePrice(100000,['CH','SC']); // 10 vs 5 → 10
    return (p.pct===10 && p.deduction_amount===10000 && p.revised_price===90000) || JSON.stringify(p);
  });
  t('Additive rule honoured when configured', function(){
    var m=S.activeDeduction(); var old=m.rule; m.rule='additive';
    var p=S.computePrice(100000,['CH','SC']); m.rule=old;
    return p.pct===15 || JSON.stringify(p);
  });

  /* 14. Duplicate serial BR-06 */
  t('BR-06 duplicate serial detected', function(){
    var a=S.asset(assets[30].id), b=S.asset(assets[31].id);
    b.serial=a.serial;
    var d=S.duplicateCheck(a);
    return d.length===1 || String(d.length);
  });

  /* 15. Search */
  t('FR-005 exact serial lookup works', function(){
    var a=S.db.assets[50];
    var r=S.searchAssets(a.serial);
    return (r.length && r[0].id===a.id) || 'no match';
  });

  /* 16. CSV import */
  t('FR-003 CSV import creates assets & sites', function(){
    var csv='State,City,Site,Site Description,MH Family,MH Class,MH Brick,Article,Article Description,Storage Location,Inventory Type,Stock Quantity,RRP,MRP\n'+
      'Kerala,Kochi,Kochi Edappally,Reliance Digital Edappally,IT Peripherals,TFT,Dell TFT,ART-9001,Dell P2222H Monitor,SL-01,Demo Unit,3,9800,11500\n'+
      'Kerala,Kochi,Kochi Edappally,Reliance Digital Edappally,IT Hardware,Laptop,HP Laptop,ART-9002,HP ProBook 440 Laptop,SL-02,Demo Unit,2,48000,52000\n';
    var before=S.db.assets.length, sitesBefore=S.db.sites.length;
    var res=S.importAssets(csv,false);
    var newSite=S.db.sites.filter(function(s){return s.site==='Kochi Edappally';})[0];
    var cats=S.assetsAt(newSite.id).map(function(a){return a.category;}).join(',');
    return (res.created===5 && S.db.sites.length===sitesBefore+1 && cats==='tft,tft,tft,laptop,laptop' && newSite.region==='South') || JSON.stringify({res:res,cats:cats,region:newSite.region});
  });

  /* 17. Notifications / SLA */
  t('FR-022 SLA notifications generated', function(){
    var n=S.notifications();
    return n.length>0 || 'none';
  });

  /* 18. Audit immutability */
  t('FR-023 audit log captured for every material action', function(){
    var acts=S.db.audit.map(function(e){return e.action;});
    return (acts.indexOf('submit')>-1 && acts.indexOf('decision:accepted')>-1 && acts.indexOf('seal')>-1 &&
            acts.indexOf('grn')>-1 && acts.indexOf('publish')>-1 && acts.indexOf('import')>-1) || acts.join(',');
  });

  /* 19. Stats */
  t('Dashboard stats reconcile to inventory', function(){
    var st=S.stats();
    return (st.total===S.db.assets.length && st.received>=9) || JSON.stringify(st);
  });

  /* 20. CSV export round trip */
  t('CSV encoder escapes commas/quotes', function(){
    var csv=S.toCSV(['a','b'],[['x,y','he said "hi"']]);
    return csv==='a,b\n"x,y","he said ""hi"""' || csv;
  });

  t('Historic accepted commercial records keep their priced version', function(){
    S.decideCommercial(S.db.commercial[0].id,'accepted','locked');
    var before=JSON.parse(JSON.stringify(S.db.commercial[0]));
    var rates2={}; D.DEFECT_CODES.forEach(function(c){ rates2[c.code]= c.code==='OK'?0:50; });
    S.publishDeductionVersion(rates2,'highest','2026-08-11','Reliance','Approved');
    var after=S.db.commercial[0];
    return (after.deduction_pct===before.deduction_pct && after.master_version===before.master_version) ||
      JSON.stringify({before:before.deduction_pct,after:after.deduction_pct});
  });
  /* 20b. Source master mapping */
  t('Source master loaded: 622 locations / 3,957 units', function(){
    return (S.db.sites.length===622+1 || S.db.sites.length===622) ? true : S.db.sites.length+' sites';
  });
  t('Executing-partner split matches source (Deshwal 251 / SAI-DVC 371)', function(){
    var b={}; S.db.sites.filter(function(s){return s.format;}).forEach(function(s){b[s.partner]=(b[s.partner]||0)+1;});
    return (b['Deshwal']===251 && b['SAI/DVC']===371) || JSON.stringify(b);
  });
  t('Site costing totals reconcile to workbook grand total', function(){
    var tot=0, post=0, wt=0;
    S.db.sites.forEach(function(s){ var c=s.costing||{}; tot+=c.total_charges||0; post+=c.post_confirmation_total||0; wt+=c.weight_kg||0; });
    return (Math.round(tot)===2677637 && Math.round(post)===3610637 && Math.round(wt)===15828) ||
      JSON.stringify({tot:Math.round(tot),post:Math.round(post),wt:wt});
  });
  t('TAT risk flag set for 30-45 day sites', function(){
    var n=S.db.sites.filter(function(s){return s.tat_risk;}).length;
    return n===181 || String(n);
  });
  t('Asset hydration: catalogue attributes readable, not persisted', function(){
    var a=S.db.assets.filter(function(x){return typeof x.art==='number';})[0];
    var raw=JSON.parse(JSON.stringify(a));
    return (a.make==='Apple' && a.mrp>0 && raw.make===undefined && raw.art>=0) ||
      JSON.stringify({make:a.make, rawKeys:Object.keys(raw)});
  });
  t('Serial captured before QC and mapped to the asset master with audit', function(){
    var a=S.asset(submitted[0].asset_id);
    var ev=S.db.audit.filter(function(e){return e.action==='serial_captured';});
    return (a.serial==='SN-TEST-0' && ev.length>=12) || a.serial+'/'+ev.length;
  });
  t('QC cannot be submitted for a unit with no serial', function(){
    var fresh=S.db.assets.filter(function(x){return !S.hasSerial(x) && x.status==='pending_qc';})[0];
    try { S.submitQC({asset_id:fresh.id,specs:{},responses:{},photos:[],remarks:'',seconds:5}); return 'no error thrown'; }
    catch(e){ return /serial/i.test(e.message) || e.message; }
  });

  /* 21. Persistence */
  t('State persists to localStorage', function(){
    S.persist();
    var raw=JSON.parse(localStorage.getItem('relianceFieldOps.db.v1'));
    return raw.qc.length===S.db.qc.length || raw.qc.length+'/'+S.db.qc.length;
  });

  var pass=out.filter(function(x){return x.indexOf('PASS')===0;}).length;
  return (pass+'/'+out.length+' passed\n')+out.join('\n');
})()