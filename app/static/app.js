const STATUS_COLORS = {
  reserved:'var(--reserved)', generated:'var(--generated)', printed:'var(--printed)',
  registered:'var(--registered)', active:'var(--active)', retired:'var(--retired)', voided:'var(--voided)'
};
const STATUSES = Object.keys(STATUS_COLORS);
let BASE = '', KEY = '';

const $ = s => document.querySelector(s);
function toast(msg, kind){ const t=$('#toast'); t.textContent=msg; t.className='toast show '+(kind||'');
  clearTimeout(t._t); t._t=setTimeout(()=>t.className='toast',3200); }

async function api(path, opts){
  opts = opts||{};
  const headers = Object.assign({'X-API-Key':KEY}, opts.headers||{});
  if(opts.body) headers['Content-Type']='application/json';
  const res = await fetch(BASE+path, {method:opts.method||'GET', headers,
    body: opts.body?JSON.stringify(opts.body):undefined});
  if(!res.ok){ let d; try{d=await res.json()}catch(e){d=await res.text()}
    throw new Error((d && d.detail) ? JSON.stringify(d.detail) : (typeof d==='string'?d:res.status)); }
  const ct = res.headers.get('content-type')||'';
  return ct.includes('application/json') ? res.json() : res;
}

async function download(path, filename){
  try{
    const res = await fetch(BASE+path,{headers:{'X-API-Key':KEY}});
    if(!res.ok) throw new Error(res.status);
    const blob = await res.blob();
    const url = URL.createObjectURL(blob);
    const a = document.createElement('a'); a.href=url; a.download=filename; a.click();
    setTimeout(()=>URL.revokeObjectURL(url), 4000);
  }catch(e){ toast('Download fehlgeschlagen: '+e.message,'err'); }
}

async function viewSTL(path, title){
  if(!window.openSTLViewer){ toast('Viewer nicht geladen','err'); return; }
  try{
    const res = await fetch(BASE+path,{headers:{'X-API-Key':KEY}});
    if(!res.ok) throw new Error(res.status);
    const buf = await res.arrayBuffer();
    window.openSTLViewer(buf, title);
  }catch(e){ toast('Viewer-Fehler: '+e.message,'err'); }
}

// ---- Mehrfarb-Export (Bambu): 3MF / OBJ ----
async function threemfExport(body, btn){
  const fmt = ($('#tmfFormat') && $('#tmfFormat').value) || '3mf';
  body = Object.assign({format: fmt}, body);
  if(btn) btn.disabled=true;
  toast('Export wird erstellt…');
  try{
    const j = await api('/v1/airlocks:threemf',{method:'POST',body});
    const f = (j.format||fmt);
    download(j.download_url, 'airlocks_'+j.count+'.'+f);
    const grid = `Raster ${j.cols}×${j.rows}`;
    const F = f.toUpperCase();
    if(!j.fits_on_plate) toast(`${F}: ${j.count} Airlock(s), ${grid} — passt NICHT auf eine ${j.plate}-mm-Platte!`,'err');
    else toast(`${F}: ${j.count} Airlock(s), ${grid} · Download gestartet`,'ok');
  }catch(e){ toast('Export-Fehler: '+e.message,'err'); }
  finally{ if(btn) btn.disabled=false; }
}
function selectedCodes(){ return Array.from(document.querySelectorAll('.tmfChk:checked')).map(c=>c.dataset.code); }
function updateTmfSel(){ const n=selectedCodes().length; $('#tmfSelCount').textContent = n?(n+' markiert'):'';
  const b=$('#tmfSelBtn'); if(b) b.disabled = n===0; }

// ---- NFC-Tag (signierter Token gebunden an Tag-UID) ----
let _nfcCode=null, _nfcBusy=false;
function closeNfc(){ $('#nfcModal').style.display='none'; }
window.closeNfc=closeNfc;
function openNfcModal(code, boundUid){
  _nfcCode=code;
  $('#nfcTitle').textContent='NFC-Tag · '+code;
  $('#nfcUid').value=''; $('#nfcNdef').value=''; $('#nfcCommitBtn').disabled=true;
  const web = ('NDEFReader' in window);
  $('#nfcWebRow').style.display = web?'':'none';
  let s = boundUid ? `Gebunden an UID <span class="mono">${boundUid}</span> — erneutes Schreiben überschreibt die Bindung.`
                   : 'Noch kein Tag gebunden.';
  if(!web) s += ' <span class="err">Web NFC hier nicht verfügbar — Fallback nutzen.</span>';
  $('#nfcState').innerHTML = s;
  $('#nfcModal').style.display='flex';
}
async function nfcPrepare(uid){ return api(`/v1/airlocks/${_nfcCode}/nfc/prepare`,{method:'POST',body:{uid}}); }
async function nfcCommit(uid){ return api(`/v1/airlocks/${_nfcCode}/nfc/commit`,{method:'POST',body:{uid}}); }
async function nfcWebWrite(){
  if(!('NDEFReader' in window)){ toast('Web NFC nicht verfügbar','err'); return; }
  try{
    const reader = new NDEFReader();
    $('#nfcState').textContent='Tag ans Gerät halten…';
    await reader.scan();
    reader.onreadingerror = ()=>toast('Tag nicht lesbar','err');
    reader.onreading = async (ev)=>{
      if(_nfcBusy) return; _nfcBusy=true;
      try{
        const uid = ev.serialNumber;
        if(!uid){ toast('Keine UID vom Tag','err'); return; }
        const p = await nfcPrepare(uid);
        if(!p.secret_configured) toast('Warnung: NFC-Secret ist noch Default!','err');
        await reader.write({records:[{recordType:'text', data:p.ndef_text, lang:'de'}]});
        await nfcCommit(p.uid);
        toast('Tag geschrieben & gebunden ✓ ('+p.uid+')','ok');
        closeNfc(); refreshAirlocks();
      }catch(e){ toast('Schreiben fehlgeschlagen: '+e.message,'err'); }
      finally{ _nfcBusy=false; }
    };
  }catch(e){ toast('Web-NFC-Fehler: '+e.message,'err'); }
}

function pill(status){
  const c = STATUS_COLORS[status]||'var(--muted)';
  return `<span class="pill" style="background:${c}">${status}</span>`;
}
function fmtDate(s){ if(!s) return '—'; try{return new Date(s).toLocaleString('de-DE')}catch(e){return s} }
function fmtTime(s){ if(!s) return '—'; try{return new Date(s).toLocaleTimeString('de-DE')}catch(e){return s} }

// ---- Ansichts-Umschaltung (Dashboard / KG-Tracker / Updates) ----
function showView(name){
  const views = {dashboard:'#viewDashboard', kg:'#viewKg', updates:'#viewUpdates'};
  Object.entries(views).forEach(([n,sel])=>{ const el=$(sel); if(el) el.style.display = (n===name)?'':'none'; });
  $('#navDashboard').classList.toggle('active', name==='dashboard');
  const nk=$('#navKg'); if(nk) nk.classList.toggle('active', name==='kg');
  $('#navUpdates').classList.toggle('active', name==='updates');
  if(name==='updates'){ if(window._lastUpd) renderUpdatesPage(window._lastUpd); refreshUpdates(); }
  if(name==='kg'){ refreshNfcSecret(); refreshKgKeys(); refreshKgLog(); startKgAuto(); } else { stopKgAuto(); }
}

async function refreshStats(){
  try{
    const h = await fetch(BASE+'/healthz').then(r=>r.json()).catch(()=>({status:'?'}));
    const ok = h.status==='ok';
    $('#healthDot').className='dot '+(ok?'ok':'err');
    $('#tHealth').textContent = ok?'OK':'?'; $('#tHealth').className='v '+(ok?'ok':'err');
    const s = await api('/v1/stats');
    $('#tplName').textContent = s.template; $('#tTpl').textContent = s.template;
    $('#tUsed').textContent = s.used.toLocaleString('de-DE');
    $('#tFree').textContent = s.free.toLocaleString('de-DE');
    $('#tPct').textContent = s.usage_pct+'%';
    $('#tMax').textContent = s.max_batch;
    $('#statusChips').innerHTML = STATUSES.map(st=>
      `<span class="chip"><span class="c" style="background:${STATUS_COLORS[st]}"></span>${st}: <b>${s.by_status[st]||0}</b></span>`).join('');
    if(!s.template_ready) toast('Warnung: Basis-Vorlage nicht gefunden!','err');
  }catch(e){ $('#healthDot').className='dot err'; throw e; }
}

async function refreshConfig(){
  try{
    const c = await api('/v1/config'); const p=c.profile;
    $('#configBox').innerHTML = [
      ['API-Key', c.api_key_masked],['Max Batch', c.max_batch],['Code-Länge', c.code_length],
      ['Output-Verzeichnis', c.output_dir],['OpenSCAD', c.openscad_bin],['Render-Timeout', c.render_timeout+' s'],
      ['Profil', p.name],['Schrift', p.font],['Größe / xscale', p.size+' / '+p.xscale],
      ['Prägehöhe / sink', p.depth+' / '+p.sink+' mm'],['Textposition (tx,ty)', p.tx+', '+p.ty],
      ['Deckfläche z', p.topz],['Rotation °', p.rotate_deg.join(', ')],
      ['Translate', p.translate.map(v=>(+v).toFixed(3)).join(', ')],
    ].map(([k,v])=>`<span class="kk">${k}</span><span class="mono">${v}</span>`).join('');
  }catch(e){ $('#configBox').innerHTML=`<span class="err">${e.message}</span>`; }
}

async function refreshAirlocks(){
  const f = $('#filterStatus').value;
  try{
    const rows = await api('/v1/airlocks?limit=500'+(f?('&status='+f):''));
    $('#airlockCount').textContent = rows.length+' Einträge';
    $('#airlockRows').innerHTML = rows.length ? rows.map(r=>{
      const sel = `<select data-code="${r.code}" class="statusSel">`+
        STATUSES.map(s=>`<option ${s===r.status?'selected':''}>${s}</option>`).join('')+`</select>`;
      return `<tr>
        <td><input type="checkbox" class="tmfChk" data-code="${r.code}"></td>
        <td class="mono"><b>${r.code}</b></td>
        <td>${sel}</td>
        <td class="muted">${r.source||''}</td>
        <td class="mono muted">${r.batch_id||''}</td>
        <td class="muted">${fmtDate(r.created_at)}</td>
        <td class="row" style="gap:6px">
          <button class="secondary view" data-path="/v1/airlocks/${r.code}/stl" data-title="${r.code}">3D</button>
          <button class="secondary dl" data-path="/v1/airlocks/${r.code}/stl" data-file="${r.template||'lock'}_${r.code}.stl">STL</button>
          <button class="secondary nfc" data-code="${r.code}" data-uid="${r.nfc_uid||''}" title="${r.nfc_uid?('Tag gebunden: '+r.nfc_uid):'NFC-Tag beschreiben'}">${r.nfc_uid?'NFC ✓':'NFC'}</button>
        </td>
      </tr>`;}).join('') : `<tr><td colspan="7" class="muted">keine Einträge</td></tr>`;
    bindRowActions();
    if($('#tmfAll')) $('#tmfAll').checked=false;
    document.querySelectorAll('.tmfChk').forEach(c=>c.onchange=updateTmfSel);
    updateTmfSel();
  }catch(e){ $('#airlockRows').innerHTML=`<tr><td colspan="7" class="err">${e.message}</td></tr>`; }
}

async function refreshBatches(){
  try{
    const rows = await api('/v1/batches?limit=500');
    $('#batchRows').innerHTML = rows.length ? rows.map(r=>`<tr>
      <td class="mono">${r.batch_id}</td><td>${r.count}</td><td>${pill(r.status)}</td>
      <td class="muted">${r.requested_by||''}</td><td class="muted">${fmtDate(r.created_at)}</td>
      <td class="row" style="gap:6px">
        ${r.zip_url?`<button class="secondary dl" data-path="${r.zip_url}" data-file="${r.batch_id}.zip">ZIP</button>`:''}
        <button class="secondary tmf" data-batch="${r.batch_id}" title="Mehrfarb-Export (Bambu) für diesen Batch – Format über die Auswahl oben">Farbe</button>
      </td>
    </tr>`).join('') : `<tr><td colspan="6" class="muted">keine Batches</td></tr>`;
    bindRowActions();
  }catch(e){ $('#batchRows').innerHTML=`<tr><td colspan="6" class="err">${e.message}</td></tr>`; }
}

function bindRowActions(){
  document.querySelectorAll('.dl').forEach(b=>b.onclick=()=>download(b.dataset.path,b.dataset.file));
  document.querySelectorAll('.view').forEach(b=>b.onclick=()=>viewSTL(b.dataset.path,b.dataset.title));
  document.querySelectorAll('.tmf').forEach(b=>b.onclick=()=>threemfExport({batch_id:b.dataset.batch}, b));
  document.querySelectorAll('.nfc').forEach(b=>b.onclick=()=>openNfcModal(b.dataset.code, b.dataset.uid));
  document.querySelectorAll('.statusSel').forEach(sel=>sel.onchange=async()=>{
    try{ await api('/v1/airlocks/'+sel.dataset.code,{method:'PATCH',body:{status:sel.value}});
      toast('Status → '+sel.value,'ok'); refreshStats(); }
    catch(e){ toast('Fehler: '+e.message,'err'); refreshAirlocks(); }
  });
}

async function generate(){
  const mode = document.querySelector('input[name=mode]:checked').value;
  let body;
  if(mode==='auto'){ body={count: parseInt($('#genCount').value||'0',10)}; }
  else{ const codes=($('#genCodes').value||'').split(/[\s,]+/).filter(Boolean); body={codes}; }
  $('#genBtn').disabled=true; $('#genHint').textContent='läuft…';
  try{
    const r = await api('/v1/airlocks:generate',{method:'POST',body});
    const links = r.airlocks.map(a=>`<span class="row" style="gap:4px;display:inline-flex;margin:0 4px 4px 0">`+
      `<button class="secondary dl" data-path="/v1/airlocks/${a.code}/stl" data-file="${a.code}.stl">${a.code}</button>`+
      `<button class="secondary view" data-path="/v1/airlocks/${a.code}/stl" data-title="${a.code}">3D</button></span>`).join(' ');
    const zip = (r.zip_url?` &nbsp;·&nbsp; <button class="dl" data-path="${r.zip_url}" data-file="${r.batch_id}.zip">ZIP</button>`:'')
      + ` <button class="secondary tmf" data-batch="${r.batch_id}">Mehrfarbe</button>`;
    const conf = (r.conflicts&&r.conflicts.length)?`<div class="err" style="margin-top:6px">Konflikte: ${r.conflicts.join(', ')}</div>`:'';
    $('#genResult').innerHTML=`<div>Batch <span class="mono">${r.batch_id}</span> — ${pill(r.status)} — ${r.count} Airlock(s):</div>
      <div class="row" style="margin-top:8px">${links}${zip}</div>${conf}`;
    bindRowActions();
    toast('Batch erstellt: '+r.batch_id,'ok');
    refreshStats(); refreshAirlocks(); refreshBatches();
  }catch(e){ $('#genResult').innerHTML=`<div class="err">${e.message}</div>`; toast('Fehler: '+e.message,'err'); }
  finally{ $('#genBtn').disabled=false; $('#genHint').textContent=''; }
}

async function refreshVersion(){
  try{
    const v = await api('/v1/version');
    $('#versionBadge').textContent = 'v'+v.version + (v.git_sha && v.git_sha!=='unknown' ? (' · '+v.git_sha) : '');
  }catch(e){ $('#versionBadge').textContent=''; }
}

// ---- Updates & Changelog ----
function esc(s){ return (s||'').replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;'); }
function notesToHtml(notes){
  if(!notes) return '<div class="muted">Keine Notes hinterlegt.</div>';
  let html='', inUl=false; const closeUl=()=>{ if(inUl){html+='</ul>';inUl=false;} };
  for(const raw of notes.split('\n')){
    const l=raw.trim();
    if(l.startsWith('### ')){ closeUl(); html+='<h4>'+esc(l.slice(4))+'</h4>'; }
    else if(l.startsWith('- ')||l.startsWith('* ')){ if(!inUl){html+='<ul>';inUl=true;} html+='<li>'+esc(l.slice(2))+'</li>'; }
    else if(l){ closeUl(); html+='<div>'+esc(l)+'</div>'; }
  }
  closeUl(); return '<div class="notes">'+html+'</div>';
}
function renderUpdatesPage(u){
  $('#uCurrent').textContent = 'v'+(u.current||'?');
  $('#uLatest').textContent  = u.latest ? ('v'+u.latest) : '—';
  $('#updateChecked').textContent = u.checked_at ? ('geprüft '+fmtDate(u.checked_at))
    : (u.watcher_active ? '' : 'Watcher noch nicht aktiv');
  let s;
  if(u.applying) s='<span class="pill" style="background:var(--warn)">Update läuft…</span>';
  else if(u.requested) s='<span class="pill" style="background:var(--warn)">angefordert…</span>';
  else if(u.update_available) s='<span class="pill" style="background:var(--generated)">Update verfügbar</span>';
  else s='<span class="pill" style="background:var(--active)">aktuell</span>';
  if(u.last_result) s += ` <small class="hint">zuletzt: v${u.last_result.version} ${u.last_result.ok?'✓':'✗'}</small>`;
  $('#updPageStatus').innerHTML = s;
  $('#applyUpdateBtn').disabled = !u.update_available || u.applying || u.requested;
  const hist = u.history||[];
  $('#updPageBody').innerHTML = hist.length ? hist.map(h=>`<div class="verblock">
      <div class="vh"><span class="vv">v${h.version}</span><span class="muted">${h.date||''}</span>
        ${(h.version===u.latest && u.update_available)?'<span class="badge-new">neu</span>':''}</div>
      ${h.subject?('<div class="muted" style="margin:3px 0 6px">'+esc(h.subject)+'</div>'):''}
      ${notesToHtml(h.notes)}</div>`).join('')
    : '<div class="muted">keine Versionen</div>';
}

async function refreshUpdates(){
  try{
    const u = await api('/v1/update/status');
    window._lastUpd = u;
    const hint = $('#updHint');
    if(u.update_available){ hint.style.display=''; hint.textContent='⬆ Update v'+u.latest+' verfügbar'; }
    else hint.style.display='none';
    if($('#viewUpdates').style.display !== 'none') renderUpdatesPage(u);
    if((u.applying||u.requested) && !window._updPoll) window._updPoll=setInterval(refreshUpdates,5000);
    if(!(u.applying||u.requested) && window._updPoll){ clearInterval(window._updPoll); window._updPoll=null; refreshVersion(); }
  }catch(e){ /* stiller Fehler; Status bleibt */ }
}

async function applyUpdate(){
  if(!confirm('Update jetzt anwenden? Der Dienst wird neu gebaut und ist dabei kurz nicht erreichbar.')) return;
  $('#applyUpdateBtn').disabled=true; $('#uApplyHint').textContent='angefordert…';
  try{ await api('/v1/update/apply',{method:'POST'}); toast('Update angefordert','ok'); refreshUpdates(); }
  catch(e){ toast('Fehler: '+e.message,'err'); $('#applyUpdateBtn').disabled=false; $('#uApplyHint').textContent=''; }
}

// ---- NFC-Secret verwalten ----
async function refreshNfcSecret(){
  try{
    const s = await api('/v1/nfc/secret/status');
    let t;
    if(s.source==='env') t = '<span class="ok">gesetzt (ENV-Override)</span>';
    else if(s.source==='db') t = '<span class="ok">gesetzt (im Dashboard)</span>';
    else t = '<span class="err">NICHT gesetzt — Default!</span>';
    t += ` · ${s.bound_tags} Tag(s) gebunden`;
    $('#nfcSecStatus').innerHTML = t;
    const lock = !!s.env_override;
    if($('#nfcSecGenBtn')){ $('#nfcSecGenBtn').disabled = lock;
      $('#nfcSecGenBtn').title = lock ? 'Per ENV gesetzt — DB-Verwaltung deaktiviert' : ''; }
    if($('#nfcSecRestoreBtn')) $('#nfcSecRestoreBtn').disabled = lock;
  }catch(e){ if($('#nfcSecStatus')) $('#nfcSecStatus').innerHTML = `<span class="err">${esc(e.message)}</span>`; }
}
async function generateNfcSecret(){
  let s={}; try{ s = await api('/v1/nfc/secret/status'); }catch(e){}
  const warn = (s.bound_tags>0)
    ? `ACHTUNG: ${s.bound_tags} Tag(s) sind bereits gebunden. Ein neues Secret macht ALLE bereits beschriebenen Tags UNGÜLTIG! Trotzdem fortfahren?`
    : 'Neues NFC-Secret erzeugen und setzen?';
  if(!confirm(warn)) return;
  try{ const j=await api('/v1/nfc/secret/generate',{method:'POST',body:{confirm:true}});
    $('#nfcSecNew').value=j.secret; $('#nfcSecNewBox').style.display='';
    toast('Secret gesetzt — jetzt Backup exportieren!','ok'); refreshNfcSecret();
  }catch(e){ toast('Fehler: '+e.message,'err'); }
}
async function exportNfcBackup(){
  const pw = $('#nfcSecBkPw').value;
  if(!pw){ toast('Backup-Passwort eingeben','err'); return; }
  try{ const j=await api('/v1/nfc/secret/backup',{method:'POST',body:{password:pw}});
    const blob = new Blob([j.backup], {type:'application/json'});
    const url = URL.createObjectURL(blob);
    const a=document.createElement('a'); a.href=url; a.download=j.filename||'airlock-nfc-secret.backup.json'; a.click();
    setTimeout(()=>URL.revokeObjectURL(url),4000);
    $('#nfcSecBkPw').value=''; toast('Backup exportiert — sicher ablegen','ok');
  }catch(e){ toast('Fehler: '+e.message,'err'); }
}
async function restoreNfcBackup(){
  const f = ($('#nfcSecFile').files||[])[0]; const pw = $('#nfcSecRsPw').value;
  if(!f){ toast('Backup-Datei wählen','err'); return; }
  if(!pw){ toast('Passwort eingeben','err'); return; }
  if(!confirm('Secret aus Backup wiederherstellen? Das ersetzt das aktuelle Secret.')) return;
  try{
    const text = await f.text();
    await api('/v1/nfc/secret/restore',{method:'POST',body:{password:pw, backup:text, confirm:true}});
    $('#nfcSecRsPw').value=''; $('#nfcSecFile').value='';
    toast('Secret wiederhergestellt','ok'); refreshNfcSecret();
  }catch(e){ toast('Fehler: '+e.message,'err'); }
}

// ---- KG-Tracker: eingeschränkte Keys + Debug-Log ----
async function refreshKgKeys(){
  try{
    const rows = await api('/v1/kg/keys');
    $('#kgKeyRows').innerHTML = rows.length ? rows.map(r=>`<tr>
      <td>${esc(r.name)}</td>
      <td class="mono">${esc(r.key_prefix)}…</td>
      <td class="muted">${fmtDate(r.created_at)}</td>
      <td class="muted">${r.last_used_at?fmtDate(r.last_used_at):'—'}</td>
      <td>${r.active?'<span class="pill" style="background:var(--active)">aktiv</span>':'<span class="pill" style="background:var(--retired)">widerrufen</span>'}</td>
      <td class="row" style="gap:6px">${r.active?
        `<button class="secondary kgReg" data-id="${r.id}">Regenerate</button>
         <button class="secondary kgRev" data-id="${r.id}">Widerrufen</button>`:'—'}</td>
    </tr>`).join('') : `<tr><td colspan="6" class="muted">keine Keys</td></tr>`;
    document.querySelectorAll('.kgRev').forEach(b=>b.onclick=()=>revokeKgKey(b.dataset.id));
    document.querySelectorAll('.kgReg').forEach(b=>b.onclick=()=>regenerateKgKey(b.dataset.id));
  }catch(e){ $('#kgKeyRows').innerHTML=`<tr><td colspan="6" class="err">${esc(e.message)}</td></tr>`; }
}
function showNewKgKey(j){ $('#kgNewKey').value=j.key; $('#kgNewKeyBox').style.display=''; toast('Key erzeugt — nur jetzt sichtbar','ok'); }
async function createKgKey(){
  const name=($('#kgKeyName').value||'').trim()||'KG-Tracker';
  try{ const j=await api('/v1/kg/keys',{method:'POST',body:{name}}); $('#kgKeyName').value=''; showNewKgKey(j); refreshKgKeys(); }
  catch(e){ toast('Fehler: '+e.message,'err'); }
}
async function revokeKgKey(id){
  if(!confirm('Diesen Key widerrufen? Die KG-Tracker-App kann sich damit nicht mehr verbinden.')) return;
  try{ await api('/v1/kg/keys/'+id+'/revoke',{method:'POST'}); toast('Key widerrufen','ok'); refreshKgKeys(); }
  catch(e){ toast('Fehler: '+e.message,'err'); }
}
async function regenerateKgKey(id){
  if(!confirm('Neuen Key erzeugen? Der bisherige wird sofort ungültig.')) return;
  try{ const j=await api('/v1/kg/keys/'+id+'/regenerate',{method:'POST'}); showNewKgKey(j); refreshKgKeys(); }
  catch(e){ toast('Fehler: '+e.message,'err'); }
}
function kgNoteCls(n){ if(!n) return ''; if(n.indexOf('True')>=0) return 'ok';
  if(n.indexOf('False')>=0||n.indexOf('auth_failed')>=0) return 'err'; return ''; }
async function refreshKgLog(){
  try{
    const j = await api('/v1/kg/log?limit=200'); const rows=j.entries||[];
    $('#kgLogCount').textContent = rows.length+' Einträge';
    $('#kgLogRows').innerHTML = rows.length ? rows.map(e=>`<tr>
      <td class="mono muted" style="white-space:nowrap">${fmtTime(e.ts)}</td>
      <td class="mono">${esc(e.method)}</td>
      <td class="mono" style="word-break:break-all">${esc(e.path)}</td>
      <td class="mono">${esc(e.key_prefix||'—')}…${e.key_name?(' <span class="muted">'+esc(e.key_name)+'</span>'):''}</td>
      <td class="mono ${e.status>=400?'err':'ok'}">${e.status}</td>
      <td class="mono ${kgNoteCls(e.note)}">${esc(e.note||'')}</td>
    </tr>`).join('') : `<tr><td colspan="6" class="muted">keine Einträge</td></tr>`;
  }catch(e){ $('#kgLogRows').innerHTML=`<tr><td colspan="6" class="err">${esc(e.message)}</td></tr>`; }
}
async function clearKgLog(){
  try{ await api('/v1/kg/log:clear',{method:'POST'}); refreshKgLog(); toast('Log geleert','ok'); }
  catch(e){ toast('Fehler: '+e.message,'err'); }
}
function startKgAuto(){ stopKgAuto();
  if($('#kgAuto') && $('#kgAuto').checked){ window._kgPoll=setInterval(()=>{ if($('#viewKg').style.display!=='none') refreshKgLog(); }, 4000); } }
function stopKgAuto(){ if(window._kgPoll){ clearInterval(window._kgPoll); window._kgPoll=null; } }

async function connect(){
  BASE = $('#baseUrl').value.trim().replace(/\/$/,'');
  KEY = $('#apiKey').value.trim();
  localStorage.setItem('airlock_base', BASE); localStorage.setItem('airlock_key', KEY);
  try{
    await refreshStats();
    await Promise.all([refreshConfig(), refreshAirlocks(), refreshBatches(), refreshVersion(), refreshUpdates()]);
    toast('Verbunden','ok');
  }catch(e){ toast('Verbindung/Key fehlgeschlagen: '+e.message,'err'); }
}

// init
$('#filterStatus').innerHTML = '<option value="">alle Status</option>'+STATUSES.map(s=>`<option>${s}</option>`).join('');
document.querySelectorAll('input[name=mode]').forEach(r=>r.onchange=()=>{
  const auto = document.querySelector('input[name=mode]:checked').value==='auto';
  $('#autoBox').style.display = auto?'':'none'; $('#codesBox').style.display = auto?'none':'';
});
$('#connectBtn').onclick = connect;
$('#genBtn').onclick = generate;
$('#reloadAirlocks').onclick = refreshAirlocks;
$('#reloadBatches').onclick = refreshBatches;
$('#tmfSelBtn').onclick = ()=>{ const codes=selectedCodes();
  if(!codes.length){ toast('Keine Airlocks markiert','err'); return; }
  threemfExport({codes}, $('#tmfSelBtn')); };
$('#tmfAll').onclick = ()=>{ const on=$('#tmfAll').checked;
  document.querySelectorAll('.tmfChk').forEach(c=>c.checked=on); updateTmfSel(); };
$('#reloadUpdates').onclick = refreshUpdates;
$('#applyUpdateBtn').onclick = applyUpdate;
$('#nfcWebBtn').onclick = nfcWebWrite;
$('#nfcPrepBtn').onclick = async ()=>{ const uid=$('#nfcUid').value.trim();
  if(!uid){ toast('Tag-UID eingeben','err'); return; }
  try{ const p=await nfcPrepare(uid); $('#nfcNdef').value=p.ndef_text; $('#nfcCommitBtn').disabled=false;
    if(!p.secret_configured) toast('Warnung: NFC-Secret ist noch Default!','err');
    else toast('Payload erzeugt — auf den Tag schreiben, dann bestätigen','ok');
  }catch(e){ toast('Fehler: '+e.message,'err'); } };
$('#nfcCopy').onclick = ()=>{ const t=$('#nfcNdef').value;
  if(t && navigator.clipboard){ navigator.clipboard.writeText(t); toast('Kopiert','ok'); } };
$('#nfcCommitBtn').onclick = async ()=>{ const uid=$('#nfcUid').value.trim();
  try{ await nfcCommit(uid); toast('Tag gebunden ✓','ok'); closeNfc(); refreshAirlocks(); }
  catch(e){ toast('Fehler: '+e.message,'err'); } };
$('#navDashboard').onclick = ()=>showView('dashboard');
$('#navUpdates').onclick = ()=>showView('updates');
if($('#navKg')) $('#navKg').onclick = ()=>showView('kg');
if($('#kgCreateBtn')) $('#kgCreateBtn').onclick = createKgKey;
if($('#kgKeyName')) $('#kgKeyName').addEventListener('keydown',e=>{if(e.key==='Enter')createKgKey();});
if($('#kgNewKeyCopy')) $('#kgNewKeyCopy').onclick = ()=>{ const t=$('#kgNewKey').value;
  if(t && navigator.clipboard){ navigator.clipboard.writeText(t); toast('Kopiert','ok'); } };
if($('#kgNewKeyHide')) $('#kgNewKeyHide').onclick = ()=>{ $('#kgNewKeyBox').style.display='none'; $('#kgNewKey').value=''; };
if($('#kgLogReload')) $('#kgLogReload').onclick = refreshKgLog;
if($('#kgLogClear')) $('#kgLogClear').onclick = clearKgLog;
if($('#kgAuto')) $('#kgAuto').onchange = startKgAuto;
if($('#nfcSecGenBtn')) $('#nfcSecGenBtn').onclick = generateNfcSecret;
if($('#nfcSecBackupBtn')) $('#nfcSecBackupBtn').onclick = exportNfcBackup;
if($('#nfcSecRestoreBtn')) $('#nfcSecRestoreBtn').onclick = restoreNfcBackup;
if($('#nfcSecNewCopy')) $('#nfcSecNewCopy').onclick = ()=>{ const t=$('#nfcSecNew').value;
  if(t && navigator.clipboard){ navigator.clipboard.writeText(t); toast('Kopiert','ok'); } };
if($('#nfcSecNewHide')) $('#nfcSecNewHide').onclick = ()=>{ $('#nfcSecNewBox').style.display='none'; $('#nfcSecNew').value=''; };
$('#filterStatus').onchange = refreshAirlocks;
$('#apiKey').addEventListener('keydown',e=>{if(e.key==='Enter')connect();});
$('#baseUrl').value = localStorage.getItem('airlock_base')||'';
$('#apiKey').value = localStorage.getItem('airlock_key')||'';
// Vom Server injizierter Key (AIRLOCK_UI_AUTOKEY=1) hat Vorrang -> Auto-Verbinden.
if(window.__AIRLOCK_KEY__){
  $('#apiKey').value = window.__AIRLOCK_KEY__;
  $('#connControls').style.display = 'none';
}
if($('#apiKey').value) connect();
