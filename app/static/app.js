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

// ---- Mehrfarb-3MF (Bambu) ----
async function threemfExport(body, btn){
  if(btn) btn.disabled=true;
  toast('3MF wird erstellt…');
  try{
    const j = await api('/v1/airlocks:threemf',{method:'POST',body});
    download(j.download_url, 'airlocks_'+j.count+'.3mf');
    const grid = `Raster ${j.cols}×${j.rows}`;
    if(!j.fits_on_plate) toast(`3MF: ${j.count} Airlock(s), ${grid} — passt NICHT auf eine ${j.plate}-mm-Platte!`,'err');
    else toast(`3MF: ${j.count} Airlock(s), ${grid} · Download gestartet`,'ok');
  }catch(e){ toast('3MF-Fehler: '+e.message,'err'); }
  finally{ if(btn) btn.disabled=false; }
}
function selectedCodes(){ return Array.from(document.querySelectorAll('.tmfChk:checked')).map(c=>c.dataset.code); }
function updateTmfSel(){ const n=selectedCodes().length; $('#tmfSelCount').textContent = n?(n+' markiert'):'';
  const b=$('#tmfSelBtn'); if(b) b.disabled = n===0; }

function pill(status){
  const c = STATUS_COLORS[status]||'var(--muted)';
  return `<span class="pill" style="background:${c}">${status}</span>`;
}
function fmtDate(s){ if(!s) return '—'; try{return new Date(s).toLocaleString('de-DE')}catch(e){return s} }

// ---- Ansichts-Umschaltung (Dashboard / Updates) ----
function showView(name){
  const dash = name!=='updates';
  $('#viewDashboard').style.display = dash?'':'none';
  $('#viewUpdates').style.display = dash?'none':'';
  $('#navDashboard').classList.toggle('active', dash);
  $('#navUpdates').classList.toggle('active', !dash);
  if(!dash){ if(window._lastUpd) renderUpdatesPage(window._lastUpd); refreshUpdates(); }
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
        <button class="secondary tmf" data-batch="${r.batch_id}" title="Mehrfarb-3MF (Bambu) für diesen Batch">3MF</button>
      </td>
    </tr>`).join('') : `<tr><td colspan="6" class="muted">keine Batches</td></tr>`;
    bindRowActions();
  }catch(e){ $('#batchRows').innerHTML=`<tr><td colspan="6" class="err">${e.message}</td></tr>`; }
}

function bindRowActions(){
  document.querySelectorAll('.dl').forEach(b=>b.onclick=()=>download(b.dataset.path,b.dataset.file));
  document.querySelectorAll('.view').forEach(b=>b.onclick=()=>viewSTL(b.dataset.path,b.dataset.title));
  document.querySelectorAll('.tmf').forEach(b=>b.onclick=()=>threemfExport({batch_id:b.dataset.batch}, b));
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
      + ` <button class="secondary tmf" data-batch="${r.batch_id}">3MF (Mehrfarbe)</button>`;
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
$('#navDashboard').onclick = ()=>showView('dashboard');
$('#navUpdates').onclick = ()=>showView('updates');
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
