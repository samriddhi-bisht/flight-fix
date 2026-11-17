/* FlightFix front end: hash-routed single page app, no build step, no external requests. */
const $ = (s, r = document) => r.querySelector(s);
const view = $('#view');
const esc = s => String(s ?? '').replace(/[&<>"']/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
const inr = n => new Intl.NumberFormat('en-IN', {style:'currency', currency:'INR', maximumFractionDigits:0}).format(n || 0);
const num = n => new Intl.NumberFormat('en-IN').format(n ?? 0);
const UNIT = {hours:'h', cycles:'cyc', days:'d'};
const store = { get: k => { try { return localStorage.getItem(k); } catch (e) { return null; } },
                set: (k, v) => { try { localStorage.setItem(k, v); } catch (e) { /* private mode */ } } };
let tech = Number(store.get('ff.tech') || 0), woFilter = 'ALL', timer;

async function api(path, method = 'GET', body) {
  const r = await fetch('/api' + path, {method, headers: {'Content-Type': 'application/json'},
    body: body ? JSON.stringify(body) : undefined});
  if (!r.ok) throw new Error((await r.json().catch(() => ({}))).message || 'Something went wrong.');
  return r.json();
}
function toast(m, bad) {
  const t = $('#toast'); t.textContent = m; t.className = 'show' + (bad ? ' bad' : '');
  clearTimeout(timer); timer = setTimeout(() => t.className = '', 3200);
}
const guard = fn => async (...a) => { try { await fn(...a); } catch (e) { toast(e.message, true); } };
const stamp = s => `<span class="stamp s-${esc(s)}">${esc(String(s).replace('_', ' '))}</span>`;
const table = (head, rows, cls = []) => `<div class="tw"><table><thead><tr>${head.map((h, i) =>
  `<th class="${cls[i] || ''}">${h}</th>`).join('')}</tr></thead><tbody>${rows.join('')}</tbody></table></div>`;
const empty = t => `<div class="empty">${esc(t)}</div>`;

/* life gauge: how much of the interval is used up; hatched when the limit has been passed */
const gauge = t => {
  const used = Math.max(0, Math.min(1, 1 - t.fraction_left));
  return `<div class="g s-${t.state}" title="${esc(t.title)}: ${t.remaining} ${UNIT[t.limit]} left (limit: ${t.limit})">
    <b>${esc(t.code)}<span>${t.remaining} ${UNIT[t.limit]}</span></b><i style="--w:${(used * 100).toFixed(0)}%"></i></div>`;
};
const movements = list => list.length ? `<ul class="log">${list.map(m => `<li><span class="delta ${m.delta > 0 ? 'up' : 'down'}">${m.delta > 0 ? '+' : ''}${m.delta}</span>
  <span>${esc(m.part_no)}<small> ${esc(m.reason)}</small></span></li>`).join('')}</ul>` : empty('No stock movements yet.');

function openForm({title, fields, submit = 'Save', onSubmit}) {
  const d = $('#dlg');
  d.innerHTML = `<form class="f" id="f"><h3>${esc(title)}</h3>${fields.map(f => `<label>${esc(f.label)}${f.options
    ? `<select name="${f.name}">${f.options.map(o => `<option value="${esc(o.v)}">${esc(o.l)}</option>`).join('')}</select>`
    : `<input name="${f.name}" type="${f.type || 'text'}" value="${esc(f.value ?? '')}" ${f.step ? `step="${f.step}"` : ''} ${f.required === false ? '' : 'required'}>`}</label>`).join('')}
    <div class="err" id="ferr"></div><div class="end"><button type="button" class="ghost" data-close>Cancel</button><button>${esc(submit)}</button></div></form>`;
  $('[data-close]', d).onclick = () => d.close();
  $('#f').onsubmit = async e => {
    e.preventDefault();
    try { await onSubmit(Object.fromEntries(new FormData(e.target))); d.close(); route(); }
    catch (err) { $('#ferr').textContent = err.message; }
  };
  d.showModal();
}

/* ------------------------------------------------------------------ pages */
const pages = {
  async dashboard() {
    const [k, fleet, plan] = await Promise.all([api('/reports/kpis'), api('/aircraft'), api('/plan')]);
    const ro = (l, v, c = '') => `<div class="ro ${c}"><small>${l}</small><strong>${v}</strong></div>`;
    const strips = fleet.map(a => {
      const tasks = plan.filter(t => t.aircraft_id === a.id).sort((x, y) => x.code.localeCompare(y.code));
      const late = tasks.filter(t => t.state === 'OVERDUE').length;
      const st = late ? 'GROUNDED' : a.status === 'IN_MAINTENANCE' ? 'HANGAR' : 'SERVICEABLE';
      return `<article class="strip s-${st}"><div><div class="tail">${esc(a.tail)}</div><small>${esc(a.model)}</small>
        <small>${num(a.flight_hours)} FH &middot; ${num(a.cycles)} cyc</small>${stamp(late ? 'GROUNDED' : st)}</div>
        <div class="gauges">${tasks.map(gauge).join('')}</div></article>`;
    }).join('');
    view.innerHTML = `<div class="readouts">${ro('Fleet available', k.availabilityPct + '%', k.availabilityPct < 70 ? 'bad' : 'good')}
      ${ro('Overdue tasks', k.overdueTasks, k.overdueTasks ? 'bad' : '')}${ro('Due soon', k.dueSoonTasks)}
      ${ro('Open job cards', k.openWorkOrders)}${ro('Parts out of stock', k.partsOutOfStock, k.partsOutOfStock ? 'bad' : '')}
      ${ro('Stores value', inr(k.inventoryValue))}${ro('ERP waiting', k.erpPending)}</div>
      <h2>Fleet board<small>bar = share of interval used</small></h2>${strips}
      <h2>Parts to reorder<small>suggested order quantity</small></h2>
      <div class="ruled">${k.alerts.length ? k.alerts.map(a => `<div class="line"><span><b>${esc(a.name)}</b>
        <small>${esc(a.partNo)} &middot; ${a.onHand} on hand, reorder at ${a.reorderLevel} &middot; ${esc(a.supplier)}, ${a.leadDays} d lead</small></span>
        <span class="order-qty">ORDER ${a.suggestedQty}</span></div>`).join('') : empty('Everything is above its reorder level.')}</div>
      <h2>Latest stock movements</h2><div class="ruled">${movements(k.recentMovements)}</div>`;
  },

  async plan() {
    const items = await api('/plan');
    view.innerHTML = `<h2>Maintenance plan<small>${items.filter(i => i.state === 'OVERDUE').length} overdue &middot; ${items.filter(i => i.state === 'DUE_SOON').length} due soon</small></h2>
      <p class="lede">Each task is due on whichever limit comes first: flight hours, landing cycles or calendar days. Most urgent first.</p>
      <div class="bar"><button id="gen">Generate job cards</button></div>` +
      table(['Aircraft', 'Task', 'Status', 'Limit', 'Left', 'Est. labour'], items.map(i => `<tr><td><b class="mono">${esc(i.tail)}</b></td>
        <td>${esc(i.code)}<small>${esc(i.title)}</small></td><td>${stamp(i.state)}</td><td>${i.limit}</td>
        <td class="num">${i.remaining} ${UNIT[i.limit]}</td><td class="num">${i.est_hours} h</td></tr>`), ['', '', '', '', 'num', 'num']);
    $('#gen').onclick = guard(async () => {
      const r = await api('/plan/generate', 'POST');
      toast(r.length ? r.length + ' job cards raised' : 'Nothing new to raise: every due task already has a card.'); route();
    });
  },

  async orders() {
    const all = await api('/work-orders'), fleet = await api('/aircraft');
    const list = all.filter(w => woFilter === 'ALL' || w.status === woFilter);
    const chips = ['ALL', 'OPEN', 'IN_PROGRESS', 'COMPLETED', 'CANCELLED'].map(f =>
      `<button class="sm ${woFilter === f ? 'on' : 'ghost'}" data-filter="${f}">${f.replace('_', ' ')}</button>`).join('');
    view.innerHTML = `<div class="bar">${chips}<span class="grow"></span><button id="defect">Report defect</button></div>
      ${list.length ? `<div class="cards">${list.map(w => `<article class="job"><span class="no">${esc(w.wo_number)} &middot; ${esc(w.kind)}</span>
        <h3>${esc(w.title)}</h3><p><b class="mono">${esc(w.tail)}</b> ${esc(w.model)}</p>
        <div class="meta">${stamp(w.status)} ${stamp(w.priority)}</div>
        ${w.technician ? `<p class="parts">Technician: ${esc(w.technician)}</p>` : ''}
        ${w.parts.length ? `<p class="parts">${w.parts.map(p => `${p.qty} x ${esc(p.part_no)}`).join(' &middot; ')} = ${inr(w.parts_cost)}</p>` : ''}
        ${w.status === 'OPEN' || w.status === 'IN_PROGRESS' ? `<div class="row"><button class="ghost sm" data-cancel="${w.id}">Cancel card</button></div>` : ''}</article>`).join('')}</div>`
        : empty('No job cards here. Generate them from the Plan, or report a defect.')}`;
    $('#defect').onclick = () => openForm({title: 'Report a defect', submit: 'Raise job card', fields: [
      {name: 'aircraftId', label: 'Aircraft', options: fleet.map(a => ({v: a.id, l: a.tail + ' ' + a.model}))},
      {name: 'title', label: 'What is wrong?'},
      {name: 'priority', label: 'Priority', options: ['NORMAL', 'LOW', 'HIGH', 'AOG'].map(p => ({v: p, l: p}))}],
      onSubmit: async v => { const w = await api('/work-orders', 'POST', {...v, aircraftId: Number(v.aircraftId)}); toast(w.wo_number + ' raised'); }});
  },

  async parts() {
    const list = await api('/parts');
    view.innerHTML = `<div class="bar"><form id="scan" class="bar" style="margin:0"><input name="c" placeholder="Scan or type part no / barcode" aria-label="Part code" autocomplete="off">
      <button>Look up</button></form></div><div id="found"></div>` +
      table(['Part', 'Category', 'Cost', 'Stock', 'Reorder', 'Supplier', ''], list.map(p => {
        const st = p.qty === 0 ? 'out' : p.qty <= p.reorder_level ? 'low' : 'OK';
        const w = Math.min(100, p.qty / Math.max(1, p.reorder_level * 3) * 100);
        return `<tr><td><b>${esc(p.name)}</b><small>${esc(p.part_no)} &middot; ${esc(p.barcode)}</small></td><td>${esc(p.category)}</td>
          <td class="num">${inr(p.unit_cost)}</td><td class="num"><span class="lvl s-${st}" style="--w:${w}%"></span>${p.qty}</td>
          <td class="num">${p.reorder_level}</td><td>${esc(p.supplier)}<small>${p.lead_days} d lead</small></td>
          <td><button class="ghost sm" data-adjust="${p.id}" data-name="${esc(p.name)}">Adjust</button></td></tr>`; }), ['', '', 'num', 'num', 'num', '', '']);
    $('#scan').onsubmit = guard(async e => {
      e.preventDefault();
      const code = new FormData(e.target).get('c').trim(); if (!code) return;
      try { const p = await api('/parts/lookup/' + encodeURIComponent(code));
        $('#found').innerHTML = `<div class="found"><b>${esc(p.name)}</b> &middot; ${esc(p.part_no)} &middot; ${p.qty} in stores &middot; ${inr(p.unit_cost)} each</div>`;
      } catch (err) { $('#found').innerHTML = `<div class="found">${esc(err.message)}</div>`; }
    });
  },

  async tech() {
    const techs = await api('/technicians');
    if (!tech) tech = techs[0].id;
    const t = await api(`/technicians/${tech}/tasks`);
    const card = (w, mine) => `<article class="job"><span class="no">${esc(w.wo_number)}</span><h3>${esc(w.title)}</h3>
      <p><b class="mono">${esc(w.tail)}</b> ${stamp(w.priority)}</p>
      ${w.parts.length ? `<p class="parts">${w.parts.map(p => `${p.qty} x ${esc(p.part_no)}`).join(' &middot; ')}</p>` : ''}
      <div class="row">${mine ? `<input data-scan="${w.id}" placeholder="Scan part no / barcode" aria-label="Part code">
        <input data-qty="${w.id}" type="number" min="1" value="1" aria-label="Quantity" style="max-width:90px">
        <button data-issue="${w.id}">Issue part</button>
        <input data-hrs="${w.id}" type="number" min="0.5" step="0.5" placeholder="Labour hours" aria-label="Labour hours">
        <button data-done="${w.id}">Sign off</button>` : `<button data-start="${w.id}">Start job</button>`}</div></article>`;
    view.innerHTML = `<div class="bar"><label>Signed in as<select id="who">${techs.map(x =>
      `<option value="${x.id}" ${x.id === tech ? 'selected' : ''}>${esc(x.name)} (${esc(x.licence_no)})</option>`).join('')}</select></label></div>
      <h2>My jobs</h2>${t.mine.length ? `<div class="cards">${t.mine.map(w => card(w, true)).join('')}</div>` : empty('Nothing in progress. Start a job from the queue.')}
      <h2>Open queue<small>highest priority first</small></h2>${t.openQueue.length ? `<div class="cards">${t.openQueue.map(w => card(w, false)).join('')}</div>` : empty('Queue is clear.')}`;
    $('#who').onchange = e => { tech = Number(e.target.value); store.set('ff.tech', tech); route(); };
  },

  async erp() {
    const list = await api('/erp/outbox');
    view.innerHTML = `<h2>ERP ledger<small>sign-off costs waiting to post</small></h2>
      <p class="lede">Costs are written when a job is signed off and delivered with retry. A repeat can never create a second ERP document.</p>
      <div class="bar"><button id="sync">Sync with ERP</button><span class="grow"></span><button class="ghost" id="receipt">Goods receipt from ERP</button></div>` +
      (list.length ? table(['Event', 'Reference', 'Status', 'ERP document / error', 'Tries'], list.map(e => `<tr><td>${esc(e.event)}</td>
        <td class="mono">${esc(e.idem_key)}</td><td>${stamp(e.status)}</td><td>${esc(e.erp_doc || e.last_error || '')}</td><td class="num">${e.attempts}</td></tr>`), ['', '', '', '', 'num'])
        : empty('Nothing queued yet. Sign off a job to create a posting.'));
    $('#sync').onclick = guard(async () => { const r = await api('/erp/sync', 'POST'); toast(`${r.sent} sent, ${r.failed} failed`, r.failed > 0); route(); });
    $('#receipt').onclick = () => openForm({title: 'Goods receipt', submit: 'Receive into stores', fields: [
      {name: 'partNo', label: 'Part number', value: 'FF-P-'}, {name: 'qty', label: 'Quantity', type: 'number', value: 1},
      {name: 'poRef', label: 'PO reference', value: 'PO-', required: false}],
      onSubmit: async v => { const p = await api('/erp/receipts', 'POST', {...v, qty: Number(v.qty)}); toast(`${p.part_no} now ${p.qty} in stores`); }});
  }
};

/* ------------------------------------------------------------------ actions */
document.addEventListener('click', guard(async e => {
  const d = e.target.closest('button')?.dataset || {};
  if (d.filter) { woFilter = d.filter; route(); }
  if (d.cancel) { await api(`/work-orders/${d.cancel}/cancel`, 'POST'); toast('Job card cancelled'); route(); }
  if (d.start) { await api(`/work-orders/${d.start}/start`, 'POST', {technicianId: tech}); toast('Job started'); route(); }
  if (d.issue) {
    const p = await api('/parts/lookup/' + encodeURIComponent($(`[data-scan="${d.issue}"]`).value.trim()));
    await api(`/work-orders/${d.issue}/issue-part`, 'POST', {items: [{partId: p.id, qty: Number($(`[data-qty="${d.issue}"]`).value)}]});
    toast(p.name + ' issued'); route();
  }
  if (d.done) {
    await api(`/work-orders/${d.done}/complete`, 'POST', {labourHours: Number($(`[data-hrs="${d.done}"]`).value)});
    toast('Signed off. Cost queued for the ERP.'); route();
  }
  if (d.adjust) openForm({title: 'Adjust: ' + d.name, submit: 'Save adjustment', fields: [
    {name: 'delta', label: 'Change in units (negative removes)', type: 'number', value: 1}, {name: 'reason', label: 'Reason', required: false}],
    onSubmit: async v => { await api(`/parts/${d.adjust}/adjust`, 'POST', {delta: Number(v.delta), reason: v.reason}); toast('Stock updated'); }});
}));

async function route() {
  const page = location.hash.split('/')[1] || 'dashboard';
  const key = pages[page] ? page : 'dashboard';
  document.querySelectorAll('#nav a').forEach(a => a.classList.toggle('on', a.hash === '#/' + key));
  $('#today').textContent = new Date().toLocaleDateString('en-IN', {weekday: 'long', day: 'numeric', month: 'long', year: 'numeric'});
  try { await pages[key](); } catch (e) { view.innerHTML = empty(e.message); }
}
window.addEventListener('hashchange', () => { route(); window.scrollTo(0, 0); });
route();
