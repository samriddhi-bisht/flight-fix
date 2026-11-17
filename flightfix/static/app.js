/* FlightFix front end: hash-routed single page app, no build step. Mobile-first for the technician view. */
const $ = (s, r = document) => r.querySelector(s), view = $('#view');
const esc = s => String(s ?? '').replace(/[&<>"']/g, c => ({'&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;'}[c]));
const inr = n => new Intl.NumberFormat('en-IN', {style: 'currency', currency: 'INR', maximumFractionDigits: 0}).format(n || 0);
const chip = t => `<span class="chip ${esc(t)}">${esc(String(t).replace('_', ' '))}</span>`;
let tech = Number(localStorage.getItem('tech') || 0), timer;

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
const run = fn => async (...a) => { try { await fn(...a); } catch (e) { toast(e.message, true); } };
const table = (head, rows, empty = 'Nothing here yet.') => rows.length
  ? `<div class="tw"><table><thead><tr>${head.map(h => `<th${/^#/.test(h) ? ' class="num"' : ''}>${h.replace(/^#/, '')}</th>`).join('')}</tr></thead><tbody>${rows.join('')}</tbody></table></div>`
  : `<div class="empty">${empty}</div>`;
const heading = (eyebrow, title, lede) => `<p class="eyebrow">${eyebrow}</p><h1 class="page">${title}</h1><p class="lede">${lede}</p>`;

const pages = {
  async dashboard() {
    const [k, items, orders, fleet] = await Promise.all([api('/reports/kpis'), api('/plan'), api('/work-orders'), api('/aircraft')]);
    const grounded = new Set(items.filter(i => i.state === 'OVERDUE').map(i => i.tail));
    fleet.forEach(a => { if (a.status === 'IN_MAINTENANCE') grounded.add(a.tail); });
    const list = (arr, fn, none, max = 4) => arr.length
      ? `<ul class="fc-list">${arr.slice(0, max).map(fn).join('')}</ul>${arr.length > max ? `<small class="more">+${arr.length - max} more</small>` : ''}`
      : `<p class="fc-none">${none}</p>`;
    const card = (cls, label, big, sub, back, i) => `<div class="fc ${cls}" role="button" tabindex="0" aria-pressed="false" style="--i:${i}">
      <div class="fc-in"><div class="face front"><span class="lab">${label}</span><div class="val ${cls === 'hot' ? 'hot' : ''}">${big}</div><small class="hint"><span>${sub}</span></small></div>
      <div class="face back"><span class="lab">${label}</span>${back}</div></div></div>`;
    const due = s => items.filter(i => i.state === s);
    const row = i => `<li><span class="mono">${esc(i.tail)} ${esc(i.code)}</span><span>${i.remaining} ${esc(i.limit)}</span></li>`;
    const live = orders.filter(w => ['OPEN', 'IN_PROGRESS'].includes(w.status));
    view.innerHTML = heading('Overview', 'Fleet at a <em>glance</em>', 'Tap any card to turn it over for the detail behind the number.') + `
      <section class="deck">
        ${card('hero', 'Fleet availability', `${Math.round(k.availabilityPct)}<sup>%</sup>`, `${k.availableAircraft} of ${k.fleetSize} ready to fly`,
          list(fleet, a => `<li><span class="mono">${esc(a.tail)}<small> ${esc(a.model)}</small></span><span>${grounded.has(a.tail) ? 'grounded' : 'ready'}</span></li>`, 'No aircraft registered.', 8), 0)}
        ${card(k.overdueTasks ? 'hot' : '', 'Overdue tasks', k.overdueTasks, 'limit already passed', list(due('OVERDUE'), row, 'Nothing overdue.'), 1)}
        ${card('', 'Due soon', k.dueSoonTasks, 'within the warning window', list(due('DUE_SOON'), row, 'Nothing due soon.'), 2)}
        ${card('', 'Open orders', k.openWorkOrders, `${k.inProgressWorkOrders} in progress`,
          list(live, w => `<li><span class="mono">${esc(w.wo_number)} ${esc(w.tail)}</span><span>${esc(w.priority)}</span></li>`, 'No live work orders.'), 3)}
        ${card(k.partsOutOfStock ? 'hot' : '', 'Out of stock', k.partsOutOfStock, `${k.partsBelowReorder} more below reorder`,
          list(k.alerts, a => `<li><span>${esc(a.name)}</span><span>${a.onHand} left</span></li>`, 'Stores are healthy.'), 4)}
        ${card('wide', 'ERP waiting', k.erpPending, 'postings not yet sent',
          k.erpPending ? `<p class="fc-none">${k.erpPending} cost posting${k.erpPending > 1 ? 's' : ''} queued.</p><a href="#/erp">Open the ERP queue &rarr;</a>` : '<p class="fc-none">Everything is posted.</p>', 5)}
        ${card('wide', 'Stock value', inr(k.inventoryValue), `${k.completedWorkOrders} jobs signed off`,
          `<ul class="fc-list"><li><span>Parts issued to jobs</span><span>${inr(k.partsIssuedCost)}</span></li><li><span>Avg labour per job</span><span>${k.avgLabourHoursPerWO} h</span></li><li><span>Fleet size</span><span>${k.fleetSize}</span></li></ul>`, 6)}
      </section>
      <h2>Parts to reorder</h2>
      ${table(['Part', '#On hand', '#Reorder at', '#Order', 'Supplier'], k.alerts.map(a => `<tr>
        <td><span class="t">${esc(a.name)}</span><br><small>${esc(a.partNo)}</small></td>
        <td class="num">${a.onHand === 0 ? `<span class="chip out">0</span>` : a.onHand}</td><td class="num">${a.reorderLevel}</td>
        <td class="num"><b>${a.suggestedQty}</b></td><td>${esc(a.supplier)}<br><small>${a.leadDays} day lead time</small></td></tr>`),
        'Every part is above its reorder level.')}
      <h2>Recent stock movements</h2>
      ${table(['Part', '#Change', 'Reason'], k.recentMovements.map(m => `<tr><td class="mono">${esc(m.part_no)}</td>
        <td class="num">${m.delta > 0 ? '+' : ''}${m.delta}</td><td>${esc(m.reason)}</td></tr>`))}`;
  },

  async plan() {
    const items = await api('/plan');
    view.innerHTML = `<div class="bar"><div>${heading('Maintenance plan', 'What is <em>due</em>, in order', 'Every task is due on whichever limit arrives first: hours, cycles or calendar days.')}</div>
      <button id="gen">Generate work orders</button></div>` +
      table(['Aircraft', 'Task', 'Status', 'Life left', 'Limit', '#Remaining'], items.map(i => {
        const pct = Math.max(0, Math.min(100, i.fraction_left * 100));
        return `<tr><td class="mono">${esc(i.tail)}</td><td><span class="t">${esc(i.title)}</span><br><small>${esc(i.code)}</small></td>
          <td>${chip(i.state)}</td><td><span class="life ${esc(i.state)}"><i style="width:${pct}%"></i></span></td>
          <td class="mono">${esc(i.limit)}</td><td class="num">${i.remaining}</td></tr>`;
      }));
    $('#gen').onclick = run(async () => {
      const r = await api('/plan/generate', 'POST');
      toast(r.length ? `${r.length} work order${r.length > 1 ? 's' : ''} raised` : 'Nothing new to raise'); route();
    });
  },

  async orders() {
    const [list, fleet] = await Promise.all([api('/work-orders'), api('/aircraft')]);
    view.innerHTML = heading('Work orders', 'Every job, <em>one</em> ledger', 'Scheduled jobs come from the plan. Defects can be raised here at any time.') +
      `<form class="inline" id="defect" style="margin-bottom:24px">
        <select name="aircraftId" aria-label="Aircraft">${fleet.map(a => `<option value="${a.id}">${esc(a.tail)}</option>`).join('')}</select>
        <input name="title" placeholder="Describe the defect" aria-label="Defect" style="flex:1 1 220px" required>
        <select name="priority" aria-label="Priority"><option>NORMAL</option><option>LOW</option><option>HIGH</option><option>AOG</option></select>
        <button>Raise defect</button></form>` +
      table(['Order', 'Aircraft', 'Job', 'Priority', 'Status', 'Technician', ''], list.map(w => `<tr>
        <td class="mono">${esc(w.wo_number)}</td><td class="mono">${esc(w.tail)}</td><td>${esc(w.title)}</td>
        <td>${chip(w.priority)}</td><td>${chip(w.status)}</td><td>${esc(w.technician || '')}</td>
        <td>${['OPEN', 'IN_PROGRESS'].includes(w.status) ? `<button class="ghost sm" data-cancel="${w.id}">Cancel</button>` : ''}</td></tr>`),
        'No work orders yet. Generate them from the plan.');
    $('#defect').onsubmit = run(async e => {
      e.preventDefault(); const f = new FormData(e.target);
      await api('/work-orders', 'POST', {aircraftId: Number(f.get('aircraftId')), title: f.get('title'), priority: f.get('priority')});
      toast('Defect raised'); route();
    });
  },

  async parts() {
    const q = view.dataset.q || '';
    const list = await api('/parts?q=' + encodeURIComponent(q));
    view.innerHTML = heading('Stores', 'Spare parts, <em>never</em> below zero', 'Every change is logged. A request that would take stock negative is refused.') +
      `<div class="bar"><input id="q" type="search" placeholder="Search part, name or category" value="${esc(q)}" aria-label="Search parts" style="flex:1 1 260px">
        <form class="inline" id="receipt"><input name="partNo" placeholder="Part no" aria-label="Part number" style="width:120px" required>
        <input name="qty" type="number" min="1" placeholder="Qty" aria-label="Quantity" class="adj" required>
        <button class="ghost">Receive goods</button></form></div>` +
      table(['Part', 'Category', '#Cost', '#On hand', '#Reorder at', 'Adjust'], list.map(p => `<tr>
        <td><span class="t">${esc(p.name)}</span><br><small>${esc(p.part_no)}</small></td><td>${esc(p.category)}</td>
        <td class="num">${inr(p.unit_cost)}</td>
        <td class="num"><span class="chip ${p.qty === 0 ? 'out' : p.qty <= p.reorder_level ? 'low' : 'OK'}">${p.qty}</span></td>
        <td class="num">${p.reorder_level}</td>
        <td><div class="row"><input class="adj" type="number" value="1" aria-label="Change for ${esc(p.part_no)}" data-delta="${p.id}">
          <button class="ghost sm" data-adjust="${p.id}" data-sign="1">Add</button><button class="ghost sm" data-adjust="${p.id}" data-sign="-1">Remove</button></div></td></tr>`),
        'No parts match that search.');
    const search = $('#q'); search.oninput = () => { clearTimeout(search.t); search.t = setTimeout(() => { view.dataset.q = search.value; route(); $('#q')?.focus(); }, 250); };
    $('#receipt').onsubmit = run(async e => {
      e.preventDefault(); const f = new FormData(e.target);
      const r = await api('/erp/receipts', 'POST', {partNo: f.get('partNo'), qty: Number(f.get('qty')), poRef: 'MANUAL'});
      toast(`${r.name} now ${r.qty} on hand`); route();
    });
  },

  async tech() {
    const techs = await api('/technicians');
    if (!tech || !techs.some(x => x.id === tech)) tech = techs[0].id;
    const t = await api(`/technicians/${tech}/tasks`);
    const wo = (w, mine) => `<article class="job"><header><b class="mono">${esc(w.wo_number)} &middot; ${esc(w.tail)}</b>${chip(w.priority)}</header>
      <h3>${esc(w.title)}</h3>
      ${w.parts.length ? `<ul class="parts-used">${w.parts.map(p => `<li>${p.qty} &times; ${esc(p.part_no)} ${esc(p.name)}</li>`).join('')}</ul>` : ''}
      <div class="row">${mine
        ? `<input data-scan="${w.id}" placeholder="Scan part no or barcode" aria-label="Part code" autocomplete="off">
           <input data-qty="${w.id}" type="number" min="1" value="1" aria-label="Quantity">
           <button class="ghost" data-issue="${w.id}">Issue part</button>
           <input data-hrs="${w.id}" type="number" min="0.5" step="0.5" placeholder="Labour hrs" aria-label="Labour hours">
           <button data-done="${w.id}">Sign off</button>`
        : `<button data-start="${w.id}">Start job</button>`}</div></article>`;
    view.innerHTML = heading('Technician', 'Your <em>hangar</em> list', 'Start a job, scan what you use, sign off. Cost goes to the ERP on its own.') +
      `<select class="who" id="who" aria-label="Technician">${techs.map(x => `<option value="${x.id}" ${x.id === tech ? 'selected' : ''}>${esc(x.name)} (${esc(x.skill || '')})</option>`).join('')}</select>
      <h2>My jobs</h2>${t.mine.map(w => wo(w, true)).join('') || '<div class="empty">No jobs in progress.</div>'}
      <h2>Open queue</h2>${t.openQueue.map(w => wo(w, false)).join('') || '<div class="empty">Queue is clear.</div>'}`;
    $('#who').onchange = e => { tech = Number(e.target.value); localStorage.setItem('tech', tech); route(); };
  },

  async erp() {
    const list = await api('/erp/outbox');
    view.innerHTML = `<div class="bar"><div>${heading('ERP outbox', 'Posted once, <em>never twice</em>', 'Sign-offs queue here in the same commit. Failures wait and retry with the same idempotency key.')}</div>
      <button id="sync">Sync with ERP</button></div>` +
      table(['Event', 'Reference', 'Status', 'ERP document', '#Tries'], list.map(e => `<tr><td>${esc(e.event)}</td>
        <td class="mono">${esc(e.idem_key)}</td><td>${chip(e.status)}</td><td class="mono">${esc(e.erp_doc || e.last_error || '')}</td>
        <td class="num">${e.attempts}</td></tr>`), 'Nothing queued. Sign off a job to create a posting.');
    $('#sync').onclick = run(async () => {
      const r = await api('/erp/sync', 'POST');
      toast(`${r.sent} sent, ${r.failed} failed`); route();
    });
  }
};

document.addEventListener('click', run(async e => {
  const b = e.target.closest('button'); if (!b) return;
  const d = b.dataset;
  if (d.start) { await api(`/work-orders/${d.start}/start`, 'POST', {technicianId: tech}); toast('Job started'); route(); }
  if (d.cancel) { await api(`/work-orders/${d.cancel}/cancel`, 'POST'); toast('Work order cancelled'); route(); }
  if (d.adjust) {
    const n = Number($(`[data-delta="${d.adjust}"]`).value) * Number(d.sign);
    const p = await api(`/parts/${d.adjust}/adjust`, 'POST', {delta: n, reason: 'Manual adjustment'});
    toast(`${p.name}: ${p.qty} on hand`); route();
  }
  if (d.issue) {
    const p = await api('/parts/lookup/' + encodeURIComponent($(`[data-scan="${d.issue}"]`).value.trim()));
    await api(`/work-orders/${d.issue}/issue-part`, 'POST',
      {items: [{partId: p.id, qty: Number($(`[data-qty="${d.issue}"]`).value)}]});
    toast(p.name + ' issued'); route();
  }
  if (d.done) {
    await api(`/work-orders/${d.done}/complete`, 'POST', {labourHours: Number($(`[data-hrs="${d.done}"]`).value)});
    toast('Signed off. Cost queued for ERP.'); route();
  }
}));

const flip = c => { c.classList.toggle('flip'); c.setAttribute('aria-pressed', c.classList.contains('flip')); };
document.addEventListener('click', e => { const c = e.target.closest('.fc'); if (c && !e.target.closest('a')) flip(c); });
document.addEventListener('keydown', e => { const c = e.target.closest?.('.fc'); if (c && (e.key === 'Enter' || e.key === ' ')) { e.preventDefault(); flip(c); } });

async function route() {
  const page = (location.hash.split('/')[1] || 'dashboard');
  const key = pages[page] ? page : 'dashboard';
  if (key !== 'parts') delete view.dataset.q;
  document.querySelectorAll('#nav a').forEach(a => a.classList.toggle('on', a.hash === '#/' + key));
  try { await pages[key](); } catch (e) { view.innerHTML = `<div class="empty">${esc(e.message)}</div>`; }
}
window.addEventListener('hashchange', route);
route();
