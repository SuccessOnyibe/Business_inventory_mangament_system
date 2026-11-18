'use strict';

// This frontend uses the same origin as FastAPI. A tab session survives page refresh.
const state = { offline: false, token: null, user: null, branches: [], products: [], users: [], inventory: [],
  sales: [], transfers: [], reconciliations: [], corrections: [], events: [], adjustments: [], receipts: [], customers: [], creditSales: [], repayments: [], posInventory: [], posBranch: '', inventoryCategory:'all', productCategory:'all', posCategory:'all', cart: [], receipt: null, correctionReceipt: null, report: null, reportParams: null,
  receivingDraft: null, lastReceipt: null, createdProductForStock: null, filter: '', salesPage: 0, transfersPage: 0, reconciliationsPage: 0, correctionsPage: 0, eventsPage: 0, adjustmentsPage: 0, receiptsPage: 0, customersPage: 0, creditSalesPage: 0, repaymentsPage: 0, view: 'inventory' };
const $ = selector => document.querySelector(selector);
const $$ = selector => [...document.querySelectorAll(selector)];
const PAGE_SIZE = 100;
const titles = { offline: ['Device & sync', 'Offline preparation, saved sales and upload results.'], receiving: ['Add stock', 'Record goods delivered to one branch.'], inventory: ['Inventory', 'Know what is available at each branch.'],
  sales: ['Sales', 'Record sales, customer discounts, and cash or POS payments.'],
  reconciliations: ['Daily reconciliation', 'Compare recorded sales with actual cash and POS collections.'],
  adjustments: ['Stock adjustments', 'Audited physical counts, damage, expiry, and corrections.'],
  reports: ['Reports & CSV', 'Gross sales, refunds, net totals, and unresolved differences.'],
  transfers: ['Transfers', 'Track dispatches and confirm goods as they arrive.'],
  products: ['Manage products', 'Keep your catalogue and approved selling prices up to date.'],
  credit: ['Customer credit', 'Outstanding invoices, repayments and payment receipts.'],
  customers: ['Customers', 'Customer contacts for each branch.'],
  accounts: ['Accounts', 'Manage your team, roles, and branch assignments.'] };
const dateFormat = new Intl.DateTimeFormat('en-NG', { timeZone: 'Africa/Lagos', dateStyle: 'medium', timeStyle: 'short' });
const date = value => value ? dateFormat.format(new Date(value)) : '—';
const field = (form, name) => form.elements.namedItem(name).value;
const nullable = value => value.trim() || null;
const branchName = id => state.branches.find(branch => branch.id === id)?.name || `Branch #${id}`;
const productName = id => state.products.find(product => product.id === id)?.name || `Product #${id}`;
const manager = () => state.user && state.user.role !== 'salesperson';
const paymentName = value => ({ cash: 'Cash', pos: 'POS terminal', credit: 'Credit / amount owed' }[value] || 'Not recorded');


// Integer kobo arithmetic keeps money exact, including totals larger than JS's safe integer.
function kobo(value) {
  const text = String(value || '0');
  const negative = text.startsWith('-');
  const [whole, fraction = ''] = (negative ? text.slice(1) : text).split('.');
  const result = BigInt(whole || '0') * 100n + BigInt((fraction + '00').slice(0, 2));
  return negative ? -result : result;
}
function money(value) {
  if (value == null) return 'Not priced';
  const signed = kobo(value); const amount = signed < 0n ? -signed : signed;
  return (signed < 0n ? '-₦' : '₦') + new Intl.NumberFormat('en-NG').format(amount / 100n) + '.' + (amount % 100n).toString().padStart(2, '0');
}
function decimal(cents) { const amount = cents < 0n ? -cents : cents; return (cents < 0n ? '-' : '') + (amount / 100n).toString() + '.' + (amount % 100n).toString().padStart(2, '0'); }

function node(tag, text, className) {
  const result = document.createElement(tag);
  if (text != null) result.textContent = String(text); // API content is never inserted as HTML.
  if (className) result.className = className;
  return result;
}
function badge(text, style = '') { return node('span', text, `badge ${style}`); }
function table(target, headers, rows, empty = 'No records to show yet.') {
  const host = $(target);
  host.replaceChildren();
  const result = node('table');
  const head = node('tr');
  headers.forEach(value => head.append(node('th', value)));
  const thead = node('thead'); thead.append(head); result.append(thead);
  const body = node('tbody');
  rows.forEach(values => {
    const row = node('tr');
    values.forEach(value => { const cell = node('td'); cell.append(value instanceof Node ? value : document.createTextNode(String(value ?? '—'))); row.append(cell); });
    body.append(row);
  });
  result.append(body); host.append(result);
  if (!rows.length) host.append(node('p', empty, 'empty'));
}
function notice(text, error = false) {
  $('#notice').textContent = text; $('#notice').className = error ? 'error' : ''; $('#notice').hidden = !text;
}
const SESSION_KEY = 'festy-session-token';
const SESSION_EXPIRY_KEY = 'festy-session-expires';
function savedSessionToken() {
  try { return sessionStorage.getItem(SESSION_KEY); } catch { return null; }
}
function saveSessionToken(token, expiresAt) {
  // Only the opaque session token is stored, never the password or trusted role data.
  try { sessionStorage.setItem(SESSION_KEY, token); if(expiresAt)sessionStorage.setItem(SESSION_EXPIRY_KEY,String(expiresAt)); } catch { /* Memory-only login still works. */ }
}
function showLogin(clearSavedSession = true) {
  if(clearSavedSession) { Offline.signOut().catch(()=>{}); try { sessionStorage.removeItem(SESSION_KEY); sessionStorage.removeItem(SESSION_EXPIRY_KEY); } catch { /* Storage can be blocked. */ } }
  state.token = null; state.user = null; state.offline=false;document.body.dataset.offline='false';hidePosSuggestions();
  $('#offline-sales').replaceChildren();
  state.receivingDraft=null; state.lastReceipt=null; state.createdProductForStock=null;
  for(const id of ['receipt-result','product-receiving-context','created-product-next']) $('#'+id).hidden=true;
  // Clear the previous user's visible data when switching accounts on one browser.
  for (const key of ['branches', 'products', 'users', 'inventory', 'sales', 'transfers', 'reconciliations', 'corrections', 'events', 'adjustments', 'receipts', 'customers', 'creditSales', 'repayments']) state[key] = [];
  $$('#workspace form').forEach(form => { form.reset(); [...form.elements].forEach(input => { input.disabled = false; }); });
  $$('.table-wrap').forEach(host => host.replaceChildren());
  $('#sale-receipt').replaceChildren(node('p', 'Saved sale details will appear here.', 'muted'));
  state.posInventory=[]; state.posBranch=''; state.inventoryCategory='all';state.productCategory='all';state.posCategory='all';
  for(const id of ['inventory-search','pos-search','product-search']) $('#'+id).value='';
  state.cart = []; state.receipt = null; $('#print-latest').disabled = true;
  state.correctionReceipt = null; $('#correction-form').hidden = true; $('#correction-items').replaceChildren();
  state.report = null; state.reportParams = null; $('#export-report').disabled = true; $('#discrepancy-form').hidden = true;
  $('#repayment-void-form').hidden = true;
  $('#customer-update-form').hidden = true;
  choices($('#credit-customer'), [], 'Choose registered customer'); // Do not retain another account's customer options.
  for (const id of ['report-gross', 'report-net', 'report-unresolved']) $(`#${id}`).textContent = '—';
  $('#report-generated').textContent = ''; $('#report-missing').textContent = 'Load a report';
  for(const id of ['inventory-table','products-table','pos-products']) $('#'+id).replaceChildren();
  $('#receipt-paper').replaceChildren(); renderCart();
  $('#reconciliation-summary').replaceChildren(node('p', 'Choose a branch and business date.', 'muted'));
  $('#workspace').hidden = true; $('#login-screen').hidden = false;
  delete document.body.dataset.role;
}
async function api(path, options = {}) {
  if(state.offline && !options.forceOnline && path!=='/auth/me')return Offline.cachedRead(path,options.method||'GET');
  const {forceOnline, ...requestOptions}=options;
  // A stalled connection must release the offline sale screen; its UUID remains retryable.
  if(forceOnline&&!requestOptions.signal&&typeof AbortSignal.timeout==='function')requestOptions.signal=AbortSignal.timeout(15000);
  const headers = { ...options.headers };
  if (state.token) headers.Authorization = `Bearer ${state.token}`;
  if (options.body !== undefined) headers['Content-Type'] = 'application/json';
  let response;
  try { response = await fetch(path, { ...requestOptions, headers, body: options.body === undefined ? undefined : JSON.stringify(options.body) }); }
  catch { const error = new Error('Could not reach the server.'); error.status = 0; throw error; }
  const body = response.status === 204 ? null : await response.json();
  if (!response.ok) {
    const detail = Array.isArray(body.detail) ? body.detail.map(item => `${item.loc.slice(1).join('.')}: ${item.msg}`).join('; ') : body.detail;
    const error = new Error(detail || `Request failed (${response.status}).`); error.status = response.status;
    if (response.status === 429) error.message += ` Retry after ${response.headers.get('Retry-After') || 'a few'} seconds.`;
    if (response.status === 401 && path !== '/auth/login') { showLogin(); $('#login-error').textContent = 'Your session ended. Please sign in again.'; }
    throw error;
  }
  return body;
}
function query(page) {
  const params = new URLSearchParams();
  if (state.filter) params.set('branch_id', state.filter);
  if (page !== undefined) { params.set('limit', PAGE_SIZE); params.set('offset', page * PAGE_SIZE); }
  return params.size ? '?' + params : '';
}
function choices(select, items, placeholder = 'Choose an option') {
  const current = select.value;
  select.replaceChildren(new Option(placeholder, ''), ...items.map(([id, label]) => new Option(label, id)));
  if ([...select.options].some(option => option.value === current)) select.value = current;
}
function fillChoices() {
  const branches = state.branches.map(branch => [branch.id, branch.name]);
  choices($('#branch-filter'), branches, manager() ? 'All branches' : 'Assigned branch');
  $('#branch-filter').value = state.filter;
  $$('.branch-choice').forEach(select => {
    choices(select, branches, 'Choose branch');
    if (state.user.role === 'salesperson') { select.value = state.user.branch_id; select.disabled = true; }
    else if (!select.value && branches.length === 1) select.value = branches[0][0];
  });
  $$('.optional-branch-choice').forEach(select => choices(select, branches, 'No assigned branch'));
  $$('.report-branch-choice').forEach(select => choices(select, branches, 'All branches'));
  const alphabetical = [...state.products].sort(compareProductNames);
  const active = alphabetical.filter(product => product.is_active);
  $$('.active-product-choice').forEach(select => choices(select, active.map(product => [product.id, `${product.name} · ${product.base_unit}`]), 'Choose product'));
  $$('.all-product-choice').forEach(select => choices(select, alphabetical.map(product => [product.id, `${product.name} · ${product.base_unit}`]), 'Choose product'));
  choices($('#sale-product'), active.filter(product => product.selling_price != null).map(product => [product.id, `${product.name} · ${product.base_unit}`]), 'Choose priced product');
  $$('.category-choice').forEach(select=>choices(select,select.form.id==='product-form'?SHOP_CATEGORIES.map(category=>[category.value,category.label]):productCategoryChoices(),'Choose category'));
  choices($('#edit-product'), alphabetical.map(product => [product.id, product.name]), 'Choose product');
  choices($('#edit-account'), state.users.map(user => [user.id, user.username]), 'Choose account');
  updateSalePolicy(false);
  renderCart();
}
function updateSalePolicy(resetPrice = true) {
  const product = state.products.find(item => item.id === Number($('#sale-product').value));
  const input = $('#sale-price');
  if (!product) { $('#price-policy').textContent = 'Choose a priced product to see the permitted discount.'; updateSaleTotal(); return; }
  const minimum = (kobo(product.selling_price) * (10000n - kobo(product.max_discount_percent)) + 9999n) / 10000n;
  input.min = decimal(minimum); input.max = product.selling_price;
  if (resetPrice || !input.value) input.value = product.selling_price;
  $('#price-policy').textContent = `Unit: ${product.base_unit} · Catalogue: ${money(product.selling_price)} · Maximum discount: ${product.max_discount_percent}% · Minimum: ${money(decimal(minimum))}`;
  updateSaleTotal();
}
function updateSaleTotal() {
  try {
    const quantity = field($('#sale-form'), 'quantity');
    const total = state.cart.length ? state.cart.reduce((sum, item) => sum + kobo(item.unit_price) * BigInt(item.quantity || 0), 0n)
      : kobo($('#sale-price').value) * BigInt(quantity || '0');
    $('#sale-total').textContent = money(decimal(total));
  } catch { $('#sale-total').textContent = '—'; }
}
function renderProducts() {
  renderCategoryButtons('#product-categories',state.productCategory,state.products,category=>{state.productCategory=category;renderProducts();});
  const rows=state.products.filter(product=>matchesProduct(product,$('#product-search').value) && (state.productCategory==='all'||categoryOf(product)===state.productCategory));
  groupedTables('#products-table',rows,product=>categoryOf(product),['Product','Category','Barcode / item number','Base unit','Selling price','Max. discount','Status',...(manager()?['Action']:[])],product=>[
    node('strong',product.name),categoryLabel(categoryOf(product)),product.barcode || itemNumber(product.id),product.base_unit,money(product.selling_price),`${product.max_discount_percent}%`,badge(product.is_active?'Active':'Inactive',product.is_active?'':'gray'),...(manager()?[editProductButton(product.id)]:[])]);
}

function render() {
  renderInventoryCategories();
  renderPosProducts();
  $('#stocked-count').textContent = new Set(state.inventory.filter(item => item.quantity > 0).map(item => item.product_id)).size;
  $('#transit-count').textContent = state.transfers.filter(item => item.status === 'in_transit').length + (state.transfers.length === PAGE_SIZE ? '+' : '');
  $('#empty-count').textContent = state.inventory.filter(item => item.quantity === 0).length;
  table('#sales-table', ['Receipt', 'Date & time · WAT', 'Items', 'Branch', 'Total', 'Payment', 'Action'], state.sales.map(sale => {
    const print = node('button', 'Print receipt', 'secondary');
    print.type = 'button';
    print.addEventListener('click', async () => {
      print.disabled = true;
      try {
        const path = sale.receipt_type === 'legacy' ? `/sales/${sale.id}/receipt` : `/checkouts/${sale.id}`;
        const receipt = await api(path); receiptDetails(receipt); printReceipt(receipt);
      } catch (error) { notice(error.message, true); }
      finally { print.disabled = false; }
    });
    const actions = node('div', null, 'row-actions'); actions.append(print);
    if (manager()) {
      const correct = node('button', 'Correct sale', 'secondary'); correct.type = 'button';
      correct.addEventListener('click', async () => {
        correct.disabled = true;
        try { openCorrection(await api(sale.receipt_type === 'legacy' ? `/sales/${sale.id}/receipt` : `/checkouts/${sale.id}`)); }
        catch (error) { notice(error.message, true); }
        finally { correct.disabled = false; }
      });
      actions.append(correct);
    }
    return [sale.receipt_number, date(sale.created_at), sale.description, branchName(sale.branch_id), money(sale.total_amount),
      badge(paymentName(sale.payment_method), sale.payment_method ? '' : 'gray'), actions];
  }));
  table('#transfers-table', ['Transfer', 'Product', 'Route', 'Qty', 'Dispatched · WAT', 'Received · WAT', 'Status', 'Action'], state.transfers.map(transfer => {
    let action = '—';
    if (transfer.status === 'in_transit' && (manager() || transfer.destination_branch_id === state.user.branch_id)) {
      action = node('button', 'Confirm delivery', 'secondary');
      action.addEventListener('click', async () => {
        if (!window.confirm(`Confirm that ${transfer.quantity} units of ${productName(transfer.product_id)} arrived at ${branchName(transfer.destination_branch_id)}?`)) return;
        action.disabled = true;
        try { const result = await api(`/stock-transfers/${transfer.id}/confirm`, { method: 'POST' }); notice(`Transfer #${transfer.id} received on ${date(result.received_at)}.`); await refreshAfterSave(); }
        catch (error) { notice(error.message + ' Confirmation can safely be retried.', true); }
        finally { action.disabled = false; }
      });
    }
    return [`#${transfer.id}`, productName(transfer.product_id), `${branchName(transfer.source_branch_id)} → ${branchName(transfer.destination_branch_id)}`, transfer.quantity, date(transfer.created_at), date(transfer.received_at), badge(transfer.status === 'received' ? 'Received' : 'In transit', transfer.status === 'received' ? '' : 'amber'), action];
  }));
  renderProducts();
  renderReconciliations();
  renderCorrections();
  renderOperationHistory();
  renderCustomers();
  renderCredit();
  // A delivery quantity is historical; sales may already have used that stock.
  table('#receipts-table', ['Delivery', 'Branch', 'Product', 'Quantity received', 'Batch label', 'Expiry label', 'Received by', 'Received at / WAT', 'Notes'], state.receipts.map(record => [
    `#${record.id}`, branchName(record.branch_id), productName(record.product_id), record.quantity_received,
    record.batch_number || 'Unknown', record.expires_on || 'Unknown', record.received_by_name || 'Not recorded', date(record.received_at), record.notes || '']));
  if (state.user.role === 'admin') table('#accounts-table', ['User', 'Role', 'Assigned branch', 'Status'], state.users.map(user => [user.username, user.role, user.branch_id ? branchName(user.branch_id) : 'Not assigned', badge(user.is_active ? 'Active' : 'Inactive', user.is_active ? '' : 'gray')]));
  for (const key of ['sales', 'transfers', 'reconciliations', 'corrections', 'events', 'adjustments', 'receipts', 'customers', 'creditSales', 'repayments']) {
    $(`#${key}-page`).textContent = `Page ${state[`${key}Page`] + 1}`;
    $(`[data-page="${key}:-1"]`).disabled = state[`${key}Page`] === 0;
    $(`[data-page="${key}:1"]`).disabled = state[key].length < PAGE_SIZE;
  }
}
async function refresh() {
  if(state.offline){await Offline.applyCache();return;}
  $('#refresh').disabled = true;
  try {
    const [branches, products] = await Promise.all([api('/branches'), api('/products')]);
    state.branches = branches; state.products = products;
    const [inventory, sales, transfers, users, reconciliations, corrections, events, adjustments, receipts, customers, creditSales, repayments] = await Promise.all([
      api('/inventory' + query()), api('/checkouts' + query(state.salesPage)),
      api('/stock-transfers' + query(state.transfersPage)), state.user.role === 'admin' ? allUsers() : [],
      api('/reconciliations' + query(state.reconciliationsPage)), api('/sale-corrections' + query(state.correctionsPage)),
      api('/discrepancy-events' + query(state.eventsPage)), api('/stock-adjustments' + query(state.adjustmentsPage)),
      api('/stock-receipts' + query(state.receiptsPage)), api('/customers' + query(state.customersPage)), api('/credit-sales' + query(state.creditSalesPage)), api('/credit-repayments' + query(state.repaymentsPage))
    ]);
    Object.assign(state, { inventory, sales, transfers, users, reconciliations, corrections, events, adjustments, receipts, customers, creditSales, repayments });
    fillChoices(); render(); restorePendingForms();
    await loadReconciliationSummary();
    await updateCreditCustomer();
    await updatePosStock();
    try { await Offline.afterRefresh(); } catch { $('#offline-status').textContent='Device data could not be updated. Prepare again before offline selling.'; }
  } catch(error) {
    if((!error.status||error.status>=500) && await Offline.restore(state.token)) {state.offline=true;await Offline.enter();notice('Offline: showing downloaded stock less saved device sales.');}
    else throw error;
  } finally { $('#refresh').disabled = false; renderPosProducts(); }
}
async function allUsers() {
  const users = [];
  for (let offset = 0; ; offset += 500) {
    const page = await api(`/users?limit=500&offset=${offset}`); users.push(...page);
    if (page.length < 500) return users;
  }
}
async function refreshAfterSave() {
  try { await refresh(); }
  catch (error) { notice('Your change was saved, but the lists could not refresh: ' + error.message, true); }
}
function showView(view) {
  if(state.offline && !['inventory','sales','products','customers','offline'].includes(view)){notice('This screen needs an internet connection.',true);return;}
  if (view === 'accounts' && state.user.role !== 'admin') return;
  if (['reports','receiving'].includes(view) && !manager()) return;
  state.view = view; document.body.dataset.view=view;
  $$('.view').forEach(section => { section.hidden = section.id !== `view-${view}`; });
  $$('.nav-item').forEach(button => button.classList.toggle('selected', button.dataset.view === view));
  $('#page-title').textContent = titles[view][0]; $('#page-subtitle').textContent = titles[view][1];
  // A new screen starts at its heading, not the previous screen's deep scroll.
  $$('#view-' + view + ' .table-wrap').forEach(wrapper => { wrapper.scrollLeft = 0; });
  window.scrollTo(0, 0);
  if (view === 'reports') loadFinancialReport().catch(error => notice(error.message, true));
}

// Keep pending request keys (not login tokens) in tab storage so a lost response
// can be retried after a reload without recording a second sale or stock change.
function pendingName(form) { return `family-inventory.pending.${state.user.id}.${form.id}`; }
function readPending(form) { const value = sessionStorage.getItem(pendingName(form)); return value ? JSON.parse(value) : null; }
function lockForm(form, locked) {
  [...form.elements].forEach(input => { if (input.type !== 'submit') input.disabled = locked; });
  if (!locked) {
    if (state.user.role === 'salesperson') form.querySelectorAll('.branch-choice').forEach(select => { select.disabled = true; });
  }
  if(form.id==='sale-form' && state.user) renderPosProducts();
}
function restorePendingForms() {
  let restored = false;
  for (const form of [$('#sale-form'), $('#receipt-form'), $('#transfer-form'), $('#reconciliation-form'), $('#correction-form'), $('#discrepancy-form'), $('#adjustment-form'), $('#customer-form'), $('#customer-update-form'), $('#repayment-form'), $('#repayment-void-form')]) {
    const pending = readPending(form);
    if (!pending) continue;
    restored = true;
    if (form.id === 'repayment-void-form') form.hidden = false;
    if (form.id === 'customer-update-form') { form.hidden = false; $('#customer-edit-label').textContent = 'Saved customer update. Retry to confirm its result.'; }
    if (form.id === 'discrepancy-form') {
      form.hidden = false; $('#discrepancy-panel').open = true;
      $('#discrepancy-label').textContent = 'Saved investigation/resolution decision. Retry to confirm its original result.';
      choices(form.elements.responsible_user_id, [[pending.body.responsible_user_id, `Staff #${pending.body.responsible_user_id}`]]);
    }
    if (form.id === 'adjustment-form') {
      $('#adjustment-panel').open = true;
      form.elements.amount.value = pending.body.mode === 'physical_count' ? pending.body.counted_quantity :
        ['damage', 'expiry'].includes(pending.body.mode) ? -pending.body.quantity_change : pending.body.quantity_change;
    }
    if (form.id === 'correction-form') {
      form.hidden = false; $('#correction-panel').open = true;
      $('#correction-receipt-label').textContent = `Saved ${pending.body.kind} for receipt #${pending.body.receipt_id}. Retry to confirm the original result.`;
      $('#correction-items').replaceChildren(node('p', 'The originally submitted items and restock choices are saved and locked.', 'hint'));
    }
    if (form.id === 'sale-form' && pending.body.items) {
      state.cart = pending.body.items.map(item => ({ ...item,
        unit_price: item.unit_price ?? state.products.find(product => product.id === item.product_id)?.selling_price ?? '0' }));
      renderCart();
    }
    for (const [name, value] of Object.entries(pending.body)) {
      if (form.elements.namedItem(name)) form.elements.namedItem(name).value = value ?? '';
    }
    lockForm(form, true); form.querySelector('[type=submit]').textContent = 'Retry saved request';
  }
  updateSalePolicy(false);
  if (restored && $('#notice').hidden) notice('An earlier sale or stock request needs confirmation. Open its form and retry the saved request.');
}
async function stockSubmit(form, path, buildBody, saved) {
  if(state.offline && form.id!=='sale-form'){notice('This action needs internet.',true);return;}
  const button = form.querySelector('[type=submit]');
  let pending;
  try {
    pending = readPending(form) || { key: crypto.randomUUID(), path, body: buildBody() };
    sessionStorage.setItem(pendingName(form), JSON.stringify(pending));
  } catch { notice('Tab storage is unavailable. Enable browser storage before recording stock or sales.', true); return; }
  lockForm(form, true); button.disabled = true;
  try {
    const result = await api(pending.path, { method: 'POST', body: pending.body, headers: { 'Idempotency-Key': pending.key } });
    sessionStorage.removeItem(pendingName(form)); lockForm(form, false); form.reset();
    if(['sale-form','receipt-form'].includes(form.id)) form.elements.branch_id.value=pending.body.branch_id; // Keep the till on its branch for the next customer.
    button.textContent = { 'sale-form': 'Complete sale', 'receipt-form': 'Add stock to branch', 'transfer-form': 'Dispatch transfer', 'reconciliation-form': 'Submit daily count', 'correction-form': 'Approve correction', 'discrepancy-form': 'Save decision', 'adjustment-form': 'Record adjustment', 'customer-form': 'Add customer', 'customer-update-form': 'Save customer', 'repayment-form':'Record repayment', 'repayment-void-form':'Reverse repayment' }[form.id];
    saved(result); await refreshAfterSave();
    if(form.id==='sale-form') $('#pos-search').focus({preventScroll:true});
  } catch (error) {
    if (error.status && error.status < 500 && error.status !== 401) {
      sessionStorage.removeItem(pendingName(form)); lockForm(form, false);
      notice(error.message, true);
    } else {
      button.textContent = 'Retry saved request';
      notice(error.message + ' The result is not confirmed. Retry this saved request; its details are locked to prevent duplicates.', true);
    }
  } finally { button.disabled = false; }
}
async function ordinarySubmit(form, action, success, afterSaved) {
  const button = form.querySelector('[type=submit]'); button.disabled = true;
  try { const result=await action(); if (state.user) { notice(success); await refreshAfterSave(); if(afterSaved) afterSaved(result); } }
  catch (error) { notice(error.message + (error.status === 0 ? ' Refresh the list before trying again.' : ''), true); }
  finally { button.disabled = false; }
}
function renderCart() {
  const form = $('#sale-form');
  for (const name of ['product_id', 'quantity', 'unit_price']) form.elements.namedItem(name).required = false; // Grid/scanner additions validate these in addCartItem().
  table('#cart-table', ['Product', 'Qty', 'Unit price', 'Amount', ''], state.cart.map((item, index) => {
    const product = state.products.find(product => product.id === item.product_id);
    const quantity = node('input'); quantity.type = 'number'; quantity.min = '1'; quantity.max = '2147483647'; quantity.step = '1'; quantity.required = true; quantity.value = item.quantity;
    quantity.setAttribute('aria-label', `Quantity for ${productName(item.product_id)}`);
    const price = node('input'); price.type = 'number'; price.step = '0.01'; price.required = true; price.value = item.unit_price;
    price.setAttribute('aria-label', `Unit price for ${productName(item.product_id)}`);
    if (product?.selling_price != null) {
      price.max = product.selling_price;
      price.min = decimal((kobo(product.selling_price) * (10000n - kobo(product.max_discount_percent)) + 9999n) / 10000n);
    } else price.min = '0';
    let initialAmount = '—';
    try { initialAmount = money(decimal(kobo(item.unit_price) * BigInt(item.quantity || 0))); } catch { /* An incomplete edit is not a valid total yet. */ }
    const amount = node('span', initialAmount);
    function changed() {
      item.quantity = Number(quantity.value); item.unit_price = price.value;
      try { amount.textContent = money(decimal(kobo(item.unit_price) * BigInt(item.quantity || 0))); } catch { amount.textContent = '—'; }
      updateSaleTotal();
      renderPosProducts();
    }
    quantity.addEventListener('input', changed); price.addEventListener('input', changed);
    const remove = node('button', '\u00d7', 'text-button'); remove.type = 'button'; remove.setAttribute('aria-label',`Remove ${productName(item.product_id)} from basket`);
    remove.addEventListener('click', () => { state.cart.splice(index, 1); renderCart(); });
    return [product ? `${product.name} · ${product.base_unit}` : productName(item.product_id), quantity, price, amount, remove];
  }), 'Add products above. One purchase can contain up to 100 different products.');
  updateSaleTotal();
  renderPosProducts();
}

function addCartItem() {
  const form = $('#sale-form');
  if (!field(form, 'product_id')) { notice('Choose a product to add.', true); return false; }
  for (const name of ['product_id', 'quantity', 'unit_price']) { if(!form.elements.namedItem(name).checkValidity()){ $('#manual-sale-entry').open=true; form.elements.namedItem(name).reportValidity(); return false; } }
  if (!field(form, 'unit_price')) { notice('Enter a unit price.', true); return false; }
  const product_id = Number(field(form, 'product_id')), quantity = Number(field(form, 'quantity')), unit_price = field(form, 'unit_price');
  if (!Number.isInteger(quantity) || quantity < 1) { notice('Enter a positive whole quantity.', true); return false; }
  const existing = state.cart.find(item => item.product_id === product_id);
  if (existing) {
    if (kobo(existing.unit_price) !== kobo(unit_price)) { notice('This product is already in the cart. Edit its price in the cart instead.', true); return false; }
    if (existing.quantity + quantity > 2147483647) { notice('Combined quantity is too large.', true); return false; }
    existing.quantity += quantity;
  } else {
    if (state.cart.length >= 100) { notice('A purchase can contain up to 100 different products.', true); return false; }
    state.cart.push({ product_id, quantity, unit_price });
  }
  form.elements.product_id.value = ''; form.elements.quantity.value = '1'; form.elements.unit_price.value = '';
  updateSalePolicy(false); renderCart(); return true;
}

function receiptContent(receipt) {
  const container = node('div', null, 'receipt-content');
  const correction = receipt.receipt_type === 'correction';
  if(receipt.receipt_type==='offline')container.append(node('p','PROVISIONAL - AWAITING SYNC. Not a server-confirmed receipt.','error'));
  const repayment = receipt.receipt_type === 'repayment';
  container.append(node('h2', 'FESTY AGRIC SERVICES'), node('p', `${repayment ? 'Credit repayment / reversal' : correction ? 'Refund / reversal' : 'Sales receipt'} · ${receipt.receipt_number}`, 'small'));
  if (correction) container.append(node('p', `Original receipt: ${receipt.original_receipt_number} · ${receipt.kind}`, 'small'));
  else if (receipt.status && receipt.status !== 'completed') container.append(badge(receipt.status.replaceAll('_', ' '), 'amber'));
  const list = node('dl');
  for (const [label, value] of [['Branch', receipt.branch_name], [correction ? 'Approved by' : 'Salesperson', receipt.salesperson_name],
    ['Recorded · WAT', date(receipt.created_at)], ['Customer', receipt.customer_name || (repayment ? 'See linked credit invoice' : 'Walk-in customer')],
    [correction ? 'Refund / reversal' : 'Payment', paymentName(receipt.payment_method)]]) list.append(node('dt', label), node('dd', value));
  container.append(list);
  const grid = node('table', null, 'receipt-table'); const head = node('tr');
  for (const title of ['Product', 'Qty', 'Price', 'Amount']) head.append(node('th', title));
  const thead = node('thead'); thead.append(head); grid.append(thead);
  const tbody = node('tbody');
  for (const item of receipt.items) {
    const row = node('tr');
    for (const value of [item.product_name + (correction ? item.restock ? ' (restocked)' : ' (not restocked)' : ''), `${item.quantity} ${item.base_unit}`, money(item.unit_price), money(item.total_amount)]) row.append(node('td', value));
    tbody.append(row);
  }
  grid.append(tbody); const wrap = node('div', null, 'table-wrap'); wrap.append(grid); container.append(wrap);
  const total = node('div', null, 'sale-total'); total.append(node('span', repayment ? 'Collection / reversal amount' : correction ? 'Correction value' : receipt.payment_method === 'credit' ? 'Original credit sale' : 'Original total paid'), node('strong', money(receipt.total_amount))); container.append(total);
  if (!correction && receipt.corrections?.length) {
    const net = node('dl');
    net.append(node('dt', 'Refunded / reversed'), node('dd', money(receipt.refunded_total)), node('dt', 'Net amount'), node('dd', money(receipt.net_total)));
    container.append(net);
    for (const event of receipt.corrections) container.append(node('p', `${event.receipt_number} · ${event.kind} · ${money(event.refund_total)} · ${paymentName(event.refund_method)} · ${event.approved_by_name} · ${date(event.created_at)} · ${event.reason}`, 'small'));
  }
  if (receipt.payment_method === 'credit') {
    const balance = node('dl');
    for (const [label,value] of [['Debt reduced',receipt.debt_reduced],['Net collections',receipt.net_collected],['Outstanding',receipt.outstanding]]) balance.append(node('dt',label),node('dd',money(value || '0')));
    container.append(balance);
    if(receipt.balance_as_of) container.append(node('p',`Balance as of ${date(receipt.balance_as_of)}`,'small'));
  }
  if (correction) container.append(node('p', `Cash/POS refund: ${money(receipt.refund_total)} / Debt reduction: ${money(receipt.debt_reduction || '0')}`, 'small'));
  if (receipt.notes) container.append(node('p', receipt.notes, 'small'));
  return container;
}

function receiptDetails(sale) {
  if (sale.receipt_type === 'correction') sale = { ...sale, total_amount: sale.corrected_total,
    payment_method: sale.refund_method, salesperson_name: sale.approved_by_name, notes: sale.reason };
  // Old pending standalone sales remain printable, without changing their ledger keys.
  state.receipt = { ...sale, items: sale.items || [sale],
    receipt_number: sale.receipt_number || `FAS-S-${String(sale.id).padStart(8, '0')}`,
    branch_name: sale.branch_name || branchName(sale.branch_id),
    salesperson_name: sale.salesperson_name || state.user.username };
  $('#sale-receipt').replaceChildren(receiptContent(state.receipt)); $('#print-latest').disabled = false;
  $('#receipt-preview-title').textContent = sale.receipt_type === 'correction' ? 'Correction recorded' : 'Sale recorded';
}

function printReceipt(receipt) {
  $('#receipt-paper').replaceChildren(receiptContent(receipt));
  window.print(); // The browser provides printer selection and Save as PDF.
}
$('#print-latest').addEventListener('click', () => { if (state.receipt) printReceipt(state.receipt); });
$('#add-sale-item').addEventListener('click', addCartItem);

function openCorrection(receipt) {
  const form = $('#correction-form');
  if (readPending(form)) { $('#correction-panel').open = true; notice('Retry the saved correction before starting another one.', true); return; }
  state.correctionReceipt = null; form.hidden = true;
  if (!receipt.items.some(item => item.remaining_quantity > 0)) { notice('This receipt has no unreturned items.', true); return; }
  state.correctionReceipt = receipt; form.reset(); form.hidden = false; $('#correction-panel').open = true;
  form.elements.receipt_id.value = receipt.id; form.elements.receipt_type.value = receipt.receipt_type;
  form.elements.refund_method.value = ['cash','pos'].includes(receipt.payment_method) ? receipt.payment_method : '';
  form.elements.refund_method.required = receipt.payment_method !== 'credit';
  form.elements.kind.querySelector('[value=void]').disabled = receipt.corrections.length > 0;
  $('#correction-receipt-label').textContent = `${receipt.receipt_number} · ${branchName(receipt.branch_id)} · Original amount ${money(receipt.total_amount)} · Already refunded ${money(receipt.refunded_total)}`;
  table('#correction-items', ['Product', 'Remaining', 'Return qty', 'Condition'], receipt.items.filter(item => item.remaining_quantity > 0).map(item => {
    const quantity = node('input'); quantity.type = 'number'; quantity.min = '0'; quantity.max = item.remaining_quantity;
    quantity.step = '1'; quantity.value = '0'; quantity.required = true;
    quantity.dataset.saleId = item.id; quantity.className = 'correction-quantity';
    quantity.setAttribute('aria-label', `Return quantity for ${item.product_name}`);
    quantity.addEventListener('input', updateCorrectionTotal);
    const condition = node('select'); condition.className = 'correction-restock'; condition.dataset.saleId = item.id;
    condition.setAttribute('aria-label', `Condition of ${item.product_name}`);
    condition.append(new Option('Do not restock', 'false'), new Option('Resellable — restock', 'true'));
    return [item.product_name, `${item.remaining_quantity} ${item.base_unit}`, quantity, condition];
  }));
  $('#correction-items').append(node('p', null, 'hint'));
  $('#correction-items .hint').id = 'correction-total';
  updateCorrectionMode(); $('#correction-panel').scrollIntoView({ behavior: 'smooth', block: 'start' });
}

function updateCorrectionTotal() {
  const receipt = state.correctionReceipt; if (!receipt) return;
  let amount = 0n;
  try {
    if (field($('#correction-form'), 'kind') === 'void') amount = kobo(receipt.total_amount);
    else $$('.correction-quantity').forEach(input => {
      const item = receipt.items.find(item => item.id === Number(input.dataset.saleId));
      amount += kobo(item.unit_price) * BigInt(input.value || '0');
    });
    $('#correction-total').textContent = `Refund / reversal to record: ${money(decimal(amount))}`;
  } catch { $('#correction-total').textContent = 'Enter whole quantities within the remaining amount.'; }
}

function updateCorrectionMode() {
  const voiding = field($('#correction-form'), 'kind') === 'void';
  $$('.correction-quantity, .correction-restock').forEach(input => { input.disabled = voiding; });
  updateCorrectionTotal();
}
$('#correction-kind').addEventListener('change', updateCorrectionMode);
$('#correction-form').addEventListener('submit', event => {
  event.preventDefault(); const form = event.currentTarget;
  if (!readPending(form) && !field(form, 'reason').trim()) { notice('Enter a correction reason.', true); return; }
  const items = $$('.correction-quantity').filter(input => Number(input.value) > 0).map(input => ({
    sale_id: Number(input.dataset.saleId), quantity: Number(input.value),
    restock: $(`.correction-restock[data-sale-id="${input.dataset.saleId}"]`).value === 'true' }));
  if (!readPending(form) && field(form, 'kind') === 'return' && !items.length) { notice('Choose quantities to return.', true); return; }
  stockSubmit(form, '/sale-corrections', () => ({ receipt_type: field(form, 'receipt_type'), receipt_id: Number(field(form, 'receipt_id')),
    kind: field(form, 'kind'), reason: field(form, 'reason').trim(), refund_method: field(form, 'refund_method') || null,
    items: field(form, 'kind') === 'void' ? null : items }), result => {
      state.correctionReceipt = null; form.hidden = true; receiptDetails(result);
      notice(`Correction ${result.receipt_number} recorded · ${money(result.refund_total)} · ${paymentName(result.refund_method)} · ${date(result.created_at)}.`);
    });
});

function renderCorrections() {
  table('#corrections-table', ['Correction', 'Original receipt', 'Type', 'Refund / reversal', 'Method', 'Approved by', 'Recorded · WAT', 'Reason', 'Action'], state.corrections.map(record => {
    const print = node('button', 'Print correction', 'secondary'); print.type = 'button';
    print.addEventListener('click', async () => {
      print.disabled = true;
      try { receiptDetails(await api(`/sale-corrections/${record.id}`)); printReceipt(state.receipt); }
      catch (error) { notice(error.message, true); }
      finally { print.disabled = false; }
    });
    return [record.receipt_number, record.original_receipt_number, badge(record.kind, 'amber'), money(record.refund_total),
      paymentName(record.refund_method), record.approved_by_name, date(record.created_at), node('span', record.reason, 'table-note'), print];
  }));
}

// Refresh uses the existing server session; it does not create another login.
async function openWorkspace() {
  try { state.user = await api('/auth/me',{forceOnline:true});state.offline=false; }
  catch(error) { if((!error.status||error.status>=500) && await Offline.restore(state.token)){await Offline.enter();}else throw error; }
  document.body.dataset.role = state.user.role;
  $('#profile').textContent = `${state.user.username} · ${state.user.role}`;
  $('#login-screen').hidden = true; $('#workspace').hidden = false;
  $('#today').textContent = date(new Date().toISOString());
  state.filter = state.user.role === 'salesperson' && state.user.branch_id ? String(state.user.branch_id) : '';
  state.salesPage = 0; state.transfersPage = 0; state.reconciliationsPage = 0; state.correctionsPage = 0; state.eventsPage = 0; state.adjustmentsPage = 0; state.receiptsPage = 0; state.customersPage = 0; state.creditSalesPage = 0; state.repaymentsPage = 0; notice(''); showView('inventory');
  $$('.admin-only input').forEach(input => { input.disabled = state.user.role !== 'admin'; });
  const unassigned = state.user.role === 'salesperson' && !state.user.branch_id;
  $('#unassigned').hidden = !unassigned;
  if (unassigned) { $$('.view').forEach(view => { view.hidden = true; }); return; }
  await refresh();
  Offline.render();
  if(!state.offline)Offline.sync();
}
async function restoreSession() {
  const token = savedSessionToken();
  if(!token) return;
  state.token = token;
  try { await openWorkspace(); }
  catch(error) {
    if(state.user) { notice(error.message, true); return; }
    // A network failure keeps the saved token so refreshing can retry safely.
    showLogin(error.status === 401);
    $('#login-error').textContent = error.status === 401
      ? 'Your session ended. Please sign in again.'
      : 'Could not restore your session. Refresh to retry, or sign in again.';
  }
}

$('#login-form').addEventListener('submit', async event => {
  event.preventDefault(); const form = event.currentTarget; const button = form.querySelector('[type=submit]'); button.disabled = true; $('#login-error').textContent = '';
  try {
    const result = await api('/auth/login', { method: 'POST', body: { username: field(form, 'username'), password: field(form, 'password') } });
    form.elements.password.value = ''; state.token = result.access_token; saveSessionToken(state.token,Date.now()+result.expires_in*1000);
    await openWorkspace();
  } catch (error) { if (!state.user) { showLogin(error.status === 401); $('#login-error').textContent = error.message; } else notice(error.message, true); }
  finally { button.disabled = false; }
});
$('#logout').addEventListener('click', async () => {
  if(Offline.hasPending()&&!window.confirm('Unsynced sales remain on this device. Sign back in as this account to upload them. Sign out?'))return;
  if(state.offline){await Offline.signOut();showLogin();return;}
  try { await api('/auth/logout', { method: 'POST' }); showLogin(); }
  catch (error) { notice('Could not confirm logout: ' + error.message, true); }
});
$$('[data-view]').forEach(button => button.addEventListener('click', () => button.dataset.view==='receiving'?openStockReceipt():showView(button.dataset.view)));
$('#refresh').addEventListener('click', () => refresh().catch(error => notice(error.message, true)));
$('#branch-filter').addEventListener('change', () => { state.filter = $('#branch-filter').value; state.salesPage = 0; state.transfersPage = 0; state.reconciliationsPage = 0; state.correctionsPage = 0; state.eventsPage = 0; state.adjustmentsPage = 0; state.receiptsPage = 0; state.customersPage = 0; state.creditSalesPage = 0; state.repaymentsPage = 0; refresh().catch(error => notice(error.message, true)); });
$$('[data-page]').forEach(button => button.addEventListener('click', () => {
  const [key, direction] = button.dataset.page.split(':'); state[`${key}Page`] += Number(direction);
  refresh().catch(error => notice(error.message, true));
}));
$('#product-search').addEventListener('input', renderProducts);
$('#sale-product').addEventListener('change', () => updateSalePolicy());
$('#sale-form').addEventListener('input', updateSaleTotal);
$('#sale-form').addEventListener('submit', async event => {
  event.preventDefault(); const form = event.currentTarget;
  if (!readPending(form)) {
    if (!state.cart.length && !addCartItem()) return;
    if (field(form, 'product_id')) { notice('Add the selected product before completing the purchase.', true); return; }
  }
  const checkoutBody=() => ({ branch_id: Number(field(form, 'branch_id')), items: state.cart.map(item => ({ ...item })),
    payment_method: field(form, 'payment_method'), ...(field(form,'payment_method') === 'credit' ? { customer_id:Number(field(form,'customer_id')) } : {}), customer_name: nullable(field(form, 'customer_name')), notes: nullable(field(form, 'notes')) });
  const submit=form.querySelector('[type=submit]');submit.disabled=true;
  try { if(await Offline.checkout(form,checkoutBody))return; }
  catch(error){notice(error.message+' The basket has not been cleared.',true);return;}
  finally{submit.disabled=false;}
  stockSubmit(form, '/checkouts', checkoutBody,
    sale => { state.cart = []; renderCart(); receiptDetails(sale); notice(`Sale #${sale.id} saved · ${paymentName(sale.payment_method)} · ${date(sale.created_at)}.`); });
});
$('#receipt-form').addEventListener('submit', event => {
  event.preventDefault(); const form = event.currentTarget;
  stockSubmit(form, '/stock-receipts', () => ({ branch_id: Number(field(form, 'branch_id')), product_id: Number(field(form, 'product_id')), quantity: Number(field(form, 'quantity')), notes: nullable(field(form, 'notes')), batch_number: nullable(field(form, 'batch_number').trim()), expires_on: nullable(field(form, 'expires_on')) }), result => {
    state.lastReceipt=result; $('#receipt-result').hidden=false;
    $('#receipt-result-text').textContent=`${result.quantity_received} of ${productName(result.product_id)} added to ${branchName(result.branch_id)}. Stock now: ${result.updated_quantity}.`;
    updateReceivingSummary(); notice(`Stock received. ${$('#receipt-result-text').textContent}`);
  });
});
$('#transfer-form').addEventListener('submit', event => {
  event.preventDefault(); const form = event.currentTarget;
  stockSubmit(form, '/stock-transfers', () => ({ source_branch_id: Number(field(form, 'source_branch_id')), destination_branch_id: Number(field(form, 'destination_branch_id')), product_id: Number(field(form, 'product_id')), quantity: Number(field(form, 'quantity')), notes: nullable(field(form, 'notes')) }), result => notice(`Transfer #${result.transfer_id} dispatched on ${date(result.created_at)}. Awaiting receiving confirmation.`));
});
$('#product-form').addEventListener('submit', event => {
  event.preventDefault(); const form = event.currentTarget;
  const body = { name: field(form, 'name'), category: field(form, 'category'), barcode:nullable(field(form,'barcode')), base_unit: field(form, 'base_unit'), selling_price: field(form, 'selling_price') };
  if (state.user.role === 'admin') body.max_discount_percent = field(form, 'max_discount_percent');
  const actor=state.user.id; const draft=state.receivingDraft;
  ordinarySubmit(form, async () => { const product=await api('/products', { method: 'POST', body }); form.reset(); return product; }, 'Product added to the catalogue. Add stock to record its delivered quantity.', product=>{
    if(state.user?.id!==actor) return;
    state.createdProductForStock=product.id; $('#created-product-next').hidden=false;
    if(draft && state.receivingDraft===draft){state.receivingDraft=null; $('#product-receiving-context').hidden=true; openStockReceipt(product.id,draft.branch_id,draft);}
  });
});
function openProductEditor(mode, productId=null, draft=null) {
  if(!manager()){notice('Manager/Admin permission is required to add or edit products.',true);return;}
  state.receivingDraft=draft; $('#product-receiving-context').hidden=!draft;
  if(draft) $('#product-receiving-text').textContent=`Create the product, then return to add stock at ${branchName(Number(draft.branch_id))}. No quantity is saved until you submit Add stock.`;
  showView('products');
  const form=mode==='add'?$('#product-form'):$('#price-form');
  if(productId!==null){form.elements.product_id.value=String(productId);form.elements.product_id.dispatchEvent(new Event('change'));}
  form.closest('.card').scrollIntoView({block:'start',inline:'nearest'});
  (mode==='add'?form.elements.name:productId!==null?form.elements.name:form.elements.product_id).focus({preventScroll:true});
}
// A product is shared by the business; a delivery adds its quantity to one branch.
function updateReceivingSummary(){
  const form=$('#receipt-form'); const product=state.products.find(item=>item.id===Number(field(form,'product_id')));
  $('#receipt-quantity-label').textContent=product?`3. Quantity to add (${product.base_unit})`:'3. Quantity to add';
  $('#receipt-summary').textContent=field(form,'branch_id') && product && Number(field(form,'quantity'))>0
    ? `Add ${field(form,'quantity')} ${product.base_unit} of ${product.name} to ${branchName(Number(field(form,'branch_id')))}.`
    : 'Choose the receiving branch, product and delivered quantity. Creating product details alone does not add stock.';
}
function openStockReceipt(productId=null,branchId=null,draft=null){
  if(!manager()) return;
  const form=$('#receipt-form');
  // An unconfirmed delivery must be retried with its original details and request key.
  if(!readPending(form)){
    if(draft) for(const [name,value] of Object.entries(draft)) if(form.elements.namedItem(name)) form.elements.namedItem(name).value=value;
    const branch=branchId || state.filter || field(form,'branch_id');
    if(branch) form.elements.branch_id.value=String(branch);
    if(productId!==null) form.elements.product_id.value=String(productId);
  }
  showView('receiving'); updateReceivingSummary();
  (field(form,'branch_id')?form.elements.product_id:form.elements.branch_id).focus({preventScroll:true});
}
$$('[data-stock-action]').forEach(button=>button.addEventListener('click',()=>openStockReceipt()));
$('#receipt-form').addEventListener('input',updateReceivingSummary);
$('#receipt-form').addEventListener('change',updateReceivingSummary);
$('#new-receiving-product').addEventListener('click',()=>{
  const form=$('#receipt-form');
  if(readPending(form)){notice('Retry the saved delivery before creating another product.',true);return;}
  if(!field(form,'branch_id')){form.elements.branch_id.reportValidity();return;}
  const draft=Object.fromEntries(new FormData(form)); openProductEditor('add',null,draft);
});
$('#cancel-product-receiving').addEventListener('click',()=>{
  const draft=state.receivingDraft; state.receivingDraft=null; $('#product-receiving-context').hidden=true;
  openStockReceipt(null,draft?.branch_id,draft);
});
$('#stock-created-product').addEventListener('click',()=>openStockReceipt(state.createdProductForStock));
$('#view-received-branch').addEventListener('click',()=>{
  if(!state.lastReceipt) return;
  state.inventoryCategory='all'; $('#inventory-search').value='';
  $('#branch-filter').value=String(state.lastReceipt.branch_id); showView('inventory');
  $('#branch-filter').dispatchEvent(new Event('change'));
});
function editProductButton(productId){
  const button=node('button','Edit product','secondary');button.type='button';
  button.addEventListener('click',()=>openProductEditor('edit',productId));return button;
}
$$('[data-product-action]').forEach(button=>button.addEventListener('click',()=>openProductEditor(button.dataset.productAction)));
$('#edit-product').addEventListener('change', () => {
  const form = $('#price-form'); const product = state.products.find(item => item.id === Number(field(form, 'product_id'))); if (!product) return;
  choices(form.elements.category,productCategoryChoices(),'Choose category');
  for (const name of ['name', 'category', 'base_unit', 'selling_price', 'max_discount_percent', 'is_active', 'barcode']) form.elements.namedItem(name).value = product[name] ?? '';
});
$('#price-form').addEventListener('submit', event => {
  event.preventDefault(); const form = event.currentTarget;
  const body = { name: field(form, 'name'), category: field(form, 'category'), barcode:nullable(field(form,'barcode')), base_unit: field(form, 'base_unit'), is_active: field(form, 'is_active') === 'true' };
  if (field(form, 'selling_price')) body.selling_price = field(form, 'selling_price');
  if (state.user.role === 'admin') body.max_discount_percent = field(form, 'max_discount_percent');
  ordinarySubmit(form, () => api('/products/' + field(form, 'product_id'), { method: 'PATCH', body }), 'Product updated. Historical sales remain unchanged.');
});
function accountBody(form, creating) {
  const body = { role: field(form, 'role'), branch_id: field(form, 'branch_id') ? Number(field(form, 'branch_id')) : null };
  if (creating) { body.username = field(form, 'username'); body.password = field(form, 'password'); }
  else body.is_active = field(form, 'is_active') === 'true';
  return body;
}
$('#account-form').addEventListener('submit', event => {
  event.preventDefault(); const form = event.currentTarget;
  ordinarySubmit(form, async () => { await api('/users', { method: 'POST', body: accountBody(form, true) }); form.reset(); }, 'Account created.');
});
$('#edit-account').addEventListener('change', () => {
  const form = $('#account-update-form'); const user = state.users.find(item => item.id === Number(field(form, 'user_id'))); if (!user) return;
  for (const name of ['role', 'branch_id', 'is_active']) form.elements.namedItem(name).value = user[name] ?? '';
});
$('#account-update-form').addEventListener('submit', event => {
  event.preventDefault(); const form = event.currentTarget;
  ordinarySubmit(form, async () => {
    await api('/users/' + field(form, 'user_id'), { method: 'PATCH', body: accountBody(form, false) });
    // A self-demotion/deactivation should immediately leave the Admin workspace.
    if (Number(field(form, 'user_id')) === state.user.id) {
      const current = await api('/auth/me');
      if (current.role !== 'admin') { await api('/auth/logout', { method: 'POST' }); showLogin(); }
    }
  }, 'Account updated.');
});

function renderReconciliations() {
  table('#reconciliations-table', ['Date', 'Branch', 'Revision', 'Expected cash collections', 'Actual cash collections', 'Cash difference',
    'Expected net POS', 'Actual net POS', 'POS difference', 'Submitted · WAT', 'Staff notes', 'Reviewed · WAT', 'Review notes', 'Status', 'Action'],
  state.reconciliations.map(record => {
    let action = '—';
    if (manager() && record.is_latest && record.status === 'submitted') {
      action = node('button', 'Review', 'secondary');
      action.addEventListener('click', async () => {
        const notes = window.prompt('Review this cash/POS count. Add a note explaining any differences (optional):', '');
        if (notes === null) return;
        action.disabled = true;
        try {
          const result = await api(`/reconciliations/${record.id}/review`, { method: 'POST', body: { notes: nullable(notes) } });
          notice(`Reconciliation #${record.id} reviewed on ${date(result.reviewed_at)}.`);
          await refreshAfterSave();
        } catch (error) { notice(error.message, true); }
        finally { action.disabled = false; }
      });
    }
    const actions = node('div', null, 'row-actions');
    if (action instanceof Node) actions.append(action);
    if (manager() && record.is_latest && (kobo(record.cash_difference) !== 0n || kobo(record.pos_difference) !== 0n)) {
      const decision = node('button', 'Investigate / resolve', 'secondary'); decision.type = 'button';
      decision.addEventListener('click', () => openDiscrepancy(record).catch(error => notice(error.message, true)));
      actions.append(decision);
    }
    const status = !record.is_latest ? 'Older revision' : record.status === 'reviewed' ? 'Reviewed' : 'Awaiting review';
    return [record.business_date, branchName(record.branch_id), `#${record.revision}`, money(record.expected_cash),
      money(record.actual_cash), money(record.cash_difference), money(record.expected_pos), money(record.actual_pos),
      money(record.pos_difference), `Staff #${record.submitted_by} · ${date(record.submitted_at)}`,
      node('span', record.notes || '—', 'table-note'),
      record.reviewed_at ? `Staff #${record.reviewed_by} · ${date(record.reviewed_at)}` : '—',
      node('span', record.review_notes || '—', 'table-note'),
      badge(`${status} · ${record.resolution_state || 'open'}`, !record.is_latest ? 'gray' : record.status === 'reviewed' ? '' : 'amber'), actions];
  }));
}

async function loadReconciliationSummary() {
  const form = $('#reconciliation-form');
  const branch = field(form, 'branch_id'), day = field(form, 'business_date');
  const host = $('#reconciliation-summary');
  if (!branch || !day) { host.replaceChildren(node('p', 'Choose a branch and business date.', 'muted')); return; }
  host.replaceChildren(node('p', 'Loading daily totals…', 'muted'));
  try {
    const summary = await api('/reconciliations/summary?' + new URLSearchParams({ branch_id: branch, business_date: day }));
    // Ignore a slow response if the user has selected a different branch/date meanwhile.
    if (field(form, 'branch_id') !== branch || field(form, 'business_date') !== day) return;
    const list = node('dl');
    for (const [label, value] of [['Branch', branchName(summary.branch_id)], ['Business date', summary.business_date],
      ['Purchases recorded', summary.sales_count], ['Gross cash sales', money(summary.gross_cash)], ['Gross POS sales', money(summary.gross_pos)], ['Credit cash collected', money(summary.repaid_cash)], ['Credit POS collected', money(summary.repaid_pos)],
      ['Cash refunds / reversals', money(summary.refund_cash)], ['POS refunds / reversals', money(summary.refund_pos)],
      ['Expected cash collections', money(summary.expected_cash)], ['Expected net POS', money(summary.expected_pos)]]) {
      list.append(node('dt', label), node('dd', value));
    }
    host.replaceChildren(list);
    if (summary.unclassified_count) host.append(node('p', `${summary.unclassified_count} sale(s) have no payment method (${money(summary.unclassified_amount)}). This day cannot be reconciled until those records are resolved.`, 'error'));
    const latest = summary.latest_submission;
    if (latest) {
      host.append(badge(`Revision ${latest.revision} · ${latest.status}`, summary.is_stale ? 'amber' : ''));
      host.append(node('p', summary.is_stale ? 'Out of date: customer collections changed. Submit updated counts before review.' : 'The latest submission matches current customer collections.', summary.is_stale ? 'error small' : 'muted small'));
    } else host.append(node('p', 'No daily count has been submitted yet.', 'muted'));
  } catch (error) { host.replaceChildren(node('p', error.message, 'error')); }
}

// Set date inputs from Lagos calendar parts, independent of the browser's timezone.
const lagosParts = Object.fromEntries(new Intl.DateTimeFormat('en-GB', {
  timeZone: 'Africa/Lagos', year: 'numeric', month: '2-digit', day: '2-digit'
}).formatToParts(new Date()).map(part => [part.type, part.value]));
$('#reconciliation-date').defaultValue = `${lagosParts.year}-${lagosParts.month}-${lagosParts.day}`;
$('#reconciliation-date').max = $('#reconciliation-date').value;
$('#reconciliation-branch').addEventListener('change', loadReconciliationSummary);
$('#reconciliation-date').addEventListener('change', loadReconciliationSummary);
$('#reconciliation-form').addEventListener('submit', event => {
  event.preventDefault(); const form = event.currentTarget;
  stockSubmit(form, '/reconciliations', () => ({ branch_id: Number(field(form, 'branch_id')),
    business_date: field(form, 'business_date'), actual_cash: field(form, 'actual_cash'),
    actual_pos: field(form, 'actual_pos'), notes: nullable(field(form, 'notes')) }), result => {
      form.elements.branch_id.value = result.branch_id; form.elements.business_date.value = result.business_date;
      notice(`Daily count #${result.id}, revision ${result.revision}, submitted on ${date(result.submitted_at)}. Cash difference: ${money(result.cash_difference)}; POS difference: ${money(result.pos_difference)}.`);
    });
});

function renderOperationHistory() {
  table('#events-table', ['Date / branch', 'Count', 'Decision', 'Responsible', 'Explanation', 'Action taken', 'Recorded by', 'Time · WAT'], state.events.map(event => [
    `${event.business_date} · ${branchName(event.branch_id)}`, `#${event.reconciliation_id}`, badge(event.resolution_state),
    event.responsible_name, node('span', event.explanation, 'table-note'), node('span', event.resolution_action || '—', 'table-note'), event.created_by_name, date(event.created_at)]));
  table('#adjustments-table', ['Product / branch', 'Type', 'Before', 'After', 'Change', 'Reason', 'Approved by', 'Time · WAT'], state.adjustments.map(record => [
    `${record.product_name} · ${record.branch_name}`, record.mode.replaceAll('_', ' '), `${record.quantity_before} ${record.base_unit}`,
    record.quantity_after, record.quantity_change, node('span', record.reason, 'table-note'), record.created_by_name, date(record.created_at)]));
}

async function openDiscrepancy(record) {
  const form = $('#discrepancy-form'); $('#discrepancy-panel').open = true;
  if (readPending(form)) { notice('Retry the saved decision before starting another.', true); return; }
  const assignees = await api(`/reconciliations/${record.id}/assignees`);
  form.reset(); form.hidden = false; form.elements.reconciliation_id.value = record.id;
  choices(form.elements.responsible_user_id, assignees.map(user => [user.id, `${user.username} · ${user.role}`]), 'Choose responsible staff');
  form.elements.responsible_user_id.value = record.responsible_user_id ||
    (assignees.some(user => user.id === record.submitted_by) ? record.submitted_by : state.user.id);
  const resolved = record.resolution_state === 'resolved';
  form.elements.namedItem('action').querySelector('[value=reopen]').disabled = !resolved;
  form.elements.namedItem('action').querySelector('[value=investigate]').disabled = resolved;
  form.elements.namedItem('action').querySelector('[value=resolve]').disabled = resolved || record.status !== 'reviewed';
  form.elements.namedItem('action').value = resolved ? 'reopen' : 'investigate';
  $('#discrepancy-label').textContent = `Count #${record.id} · ${branchName(record.branch_id)} · ${record.business_date} · Cash ${money(record.cash_difference)} · POS ${money(record.pos_difference)}`;
  updateDiscrepancyAction(); $('#discrepancy-panel').scrollIntoView({ behavior: 'smooth', block: 'start' });
}
function updateDiscrepancyAction() {
  const form = $('#discrepancy-form'); const resolving = field(form, 'action') === 'resolve';
  $('#resolution-action-label').hidden = !resolving;
  form.elements.resolution_action.disabled = !resolving; form.elements.resolution_action.required = resolving;
}
$('#discrepancy-action').addEventListener('change', updateDiscrepancyAction);
$('#discrepancy-form').addEventListener('submit', event => {
  event.preventDefault(); const form = event.currentTarget;
  const id = field(form, 'reconciliation_id');
  stockSubmit(form, `/reconciliations/${id}/discrepancy-events`, () => ({ action: field(form, 'action'),
    explanation: field(form, 'explanation').trim(), resolution_action: field(form, 'action') === 'resolve' ? field(form, 'resolution_action').trim() : null,
    responsible_user_id: Number(field(form, 'responsible_user_id')) }), result => {
      form.hidden = true; notice(`Decision #${result.id} saved · ${result.resolution_state} · ${result.responsible_name} · ${date(result.created_at)}.`);
    });
});

async function loadAdjustmentBalance() {
  const form = $('#adjustment-form'); if (readPending(form)) return;
  const branch = field(form, 'branch_id'), product = field(form, 'product_id');
  form.elements.expected_quantity.value = '';
  if (!branch || !product) return;
  const button = $('#load-adjustment-balance'); button.disabled = true;
  try {
    const rows = await api('/inventory?branch_id=' + branch);
    if (field(form, 'branch_id') !== branch || field(form, 'product_id') !== product) return;
    form.elements.expected_quantity.value = rows.find(row => row.product_id === Number(product))?.quantity ?? 0;
  } finally { button.disabled = false; }
}
function updateAdjustmentMode() {
  const form = $('#adjustment-form'), mode = field(form, 'mode');
  $('#adjustment-amount-label').textContent = mode === 'physical_count' ? 'Counted quantity' : mode === 'correction' ? 'Signed change (+ / −)' : 'Quantity removed';
  form.elements.amount.min = mode === 'correction' ? '-2147483647' : mode === 'physical_count' ? '0' : '1';
}
$('#adjustment-mode').addEventListener('change', updateAdjustmentMode);
$('#load-adjustment-balance').addEventListener('click', () => loadAdjustmentBalance().catch(error => notice(error.message, true)));
for (const name of ['branch_id', 'product_id']) $('#adjustment-form').elements.namedItem(name).addEventListener('change', () => loadAdjustmentBalance().catch(error => notice(error.message, true)));
$('#adjustment-form').addEventListener('submit', event => {
  event.preventDefault(); const form = event.currentTarget;
  if (!readPending(form) && field(form, 'expected_quantity') === '') { notice('Read the current balance before recording an adjustment.', true); return; }
  stockSubmit(form, '/stock-adjustments', () => {
    const mode = field(form, 'mode'), amount = Number(field(form, 'amount'));
    return { branch_id: Number(field(form, 'branch_id')), product_id: Number(field(form, 'product_id')), mode,
      expected_quantity: Number(field(form, 'expected_quantity')), reason: field(form, 'reason').trim(),
      counted_quantity: mode === 'physical_count' ? amount : null,
      quantity_change: mode === 'physical_count' ? null : ['damage','expiry'].includes(mode) ? -amount : amount };
  }, result => { updateAdjustmentMode(); notice(`Stock adjustment #${result.id} saved: ${result.quantity_before} → ${result.quantity_after} ${result.base_unit} · ${date(result.created_at)}.`); });
});

async function loadFinancialReport() {
  const form = $('#report-form'); if (!form.reportValidity()) return;
  const button = form.querySelector('[type=submit]'); button.disabled = true;
  const params = new URLSearchParams({ start_date: field(form, 'start_date'), end_date: field(form, 'end_date') });
  if (field(form, 'branch_id')) params.set('branch_id', field(form, 'branch_id'));
  try {
    const report = await api('/reports/financial?' + params);
    state.report = report; state.reportParams = params.toString();
    $('#report-gross').textContent = money(report.totals.gross_sales); $('#report-net').textContent = money(report.totals.net_sales);
    $('#report-unresolved').textContent = report.totals.unresolved_days;
    $('#report-missing').textContent = `${report.totals.unreconciled_days} missing/out-of-date count(s); ${report.totals.awaiting_review_days} awaiting review`;
    $('#report-generated').textContent = `Generated ${date(report.generated_at)} · ${report.rows.length} branch/day row(s) · Lagos dates`;
    table('#report-table', ['Date / branch', 'Gross cash', 'Gross POS', 'Credit sales', 'Debt reduced', 'Credit cash collected', 'Credit POS collected', 'Unknown method', 'Cash refunds', 'POS refunds', 'Expected cash collections', 'Net sales', 'Count status', 'Submitted cash difference', 'Submitted POS difference', 'Resolution', 'Responsible'], report.rows.map(row => [
      `${row.business_date} · ${row.branch_name}`, money(row.gross_cash), money(row.gross_pos), money(row.gross_credit), money(row.debt_reduced), money(row.repaid_cash), money(row.repaid_pos), money(row.unclassified_amount), money(row.refund_cash), money(row.refund_pos),
      money(row.expected_cash),
      money(row.net_sales), badge(row.reconciliation_status.replaceAll('_',' '), row.reconciliation_status === 'reviewed' ? '' : 'amber'),
      row.cash_difference == null ? '—' : money(row.cash_difference), row.pos_difference == null ? '—' : money(row.pos_difference),
      row.resolution_state.replaceAll('_',' '), row.responsible_name || '—']));
    $('#export-report').disabled = false;
  } finally { button.disabled = false; }
}
$('#report-form').addEventListener('submit', event => { event.preventDefault(); loadFinancialReport().catch(error => notice(error.message, true)); });
$('#report-form').addEventListener('input', () => {
  $('#export-report').disabled = true;
  if (state.report) $('#report-generated').textContent = 'Filters changed. Load the report to update these results.';
});
$('#export-report').addEventListener('click', async () => {
  if (!state.reportParams) return;
  const button = $('#export-report'); button.disabled = true;
  try {
    const response = await fetch('/reports/financial.csv?' + state.reportParams, { headers: { Authorization: `Bearer ${state.token}` } });
    if (!response.ok) { if (response.status === 401) showLogin(); throw new Error('Could not export report. Refresh or sign in again.'); }
    const url = URL.createObjectURL(await response.blob()); const link = node('a');
    link.href = url; link.download = `FAS-financial-${state.report.start_date}-${state.report.end_date}.csv`;
    document.body.append(link); link.click(); link.remove(); setTimeout(() => URL.revokeObjectURL(url), 1000);
    notice('Financial CSV downloaded. Amounts reflect the export time.');
  } catch (error) { notice(error.message, true); }
  finally { button.disabled = false; }
});
const reportToday = `${lagosParts.year}-${lagosParts.month}-${lagosParts.day}`;
$('#report-form').elements.end_date.defaultValue = reportToday;
$('#report-form').elements.start_date.defaultValue = new Date(Date.parse(reportToday + 'T12:00:00Z') - 6 * 86400000).toISOString().slice(0,10);
for (const name of ['start_date','end_date']) $('#report-form').elements.namedItem(name).max = reportToday;

// Add the same accessible visibility control to login and new-account passwords.
// Showing a password changes only its display; it never copies or stores the value.
$$('input[type=password]').forEach((input, index) => {
  const label = input.closest('label');
  const wrapper = node('div', null, 'password-field');
  const toggle = node('button', 'Show', 'password-toggle');
  input.id ||= `password-field-${index}`;
  toggle.type = 'button'; // Visibility must never submit the surrounding form.
  toggle.setAttribute('aria-controls', input.id);
  function setVisible(visible) {
    input.type = visible ? 'text' : 'password';
    toggle.textContent = visible ? 'Hide' : 'Show';
    toggle.setAttribute('aria-label', visible ? 'Hide password' : 'Show password');
    toggle.setAttribute('aria-pressed', String(visible));
  }
  label.replaceWith(wrapper); wrapper.append(label, toggle);
  setVisible(false);
  toggle.addEventListener('click', () => setVisible(input.type === 'password'));
  // Return to hidden mode after submission/reset, including logout and account switches.
  input.form.addEventListener('reset', () => setVisible(false));
  input.form.addEventListener('submit', () => setVisible(false));
});

// Version checks prevent a saved form from overwriting another staff member's edit.
function renderCustomers() {
  table('#customers-table', ['Customer', 'Branch', 'Phone', 'Status', 'Notes', 'Updated / WAT', 'Action'], state.customers.map(record => {
    let action = '';
    if (manager() || record.branch_id === state.user.branch_id) {
      action = node('button', 'Edit customer', 'secondary'); action.type = 'button';
      action.addEventListener('click', () => {
        const form = $('#customer-update-form');
        if (readPending(form)) { notice('Retry the saved customer update first.', true); return; }
        form.reset(); form.hidden = false;
        form.elements.customer_id.value = record.id;
        form.elements.expected_version.value = record.version;
        form.elements.name.value = record.name; form.elements.phone.value = record.phone || '';
        form.elements.notes.value = record.notes || ''; form.elements.is_active.value = String(record.is_active);
        $('#customer-edit-label').textContent = `Customer #${record.id} / ${branchName(record.branch_id)}`;
        form.scrollIntoView({ behavior:'smooth', block:'center' });
      });
    }
    if (manager() || record.branch_id === state.user.branch_id) {
      const group=node('div',null,'row-actions');group.append(action);const balance=node('button','View balance','secondary');balance.type='button';
      balance.addEventListener('click',async()=>{try{const result=await api(`/customers/${record.id}/balance`);notice(`${result.name}: outstanding ${money(result.outstanding)} as of ${date(result.generated_at)}.`)}catch(error){notice(error.message,true)}});group.append(balance);action=group;
    }
    return [`#${record.id} / ${record.name}`, branchName(record.branch_id), record.phone || '', badge(record.is_active ? 'Active' : 'Inactive', record.is_active ? '' : 'gray'), record.notes || '', date(record.updated_at), action];
  }));
}
function customerFields(form) {
  return { name:field(form,'name').trim(), phone:nullable(field(form,'phone')), notes:nullable(field(form,'notes')) };
}
$('#customer-form').addEventListener('submit', event => {
  event.preventDefault(); const form = event.currentTarget;
  stockSubmit(form, '/customers', () => ({ ...customerFields(form), branch_id:Number(field(form,'branch_id')) }),
    record => notice(`Customer #${record.id} added.`));
});
$('#customer-update-form').addEventListener('submit', event => {
  event.preventDefault(); const form = event.currentTarget;
  stockSubmit(form, `/customers/${field(form,'customer_id')}/update`, () => ({ ...customerFields(form),
    is_active:field(form,'is_active') === 'true', expected_version:Number(field(form,'expected_version')) }),
    record => { form.hidden = true; notice(`Customer #${record.id} updated.`); });
});

async function updateCreditCustomer() {
  const form = $('#sale-form');
  if (!state.user || readPending(form)) return;
  const credit = field(form,'payment_method') === 'credit';
  $('#credit-customer-label').hidden = !credit;
  form.elements.customer_id.disabled = !credit; form.elements.customer_id.required = credit;
  if (!credit || !field(form,'branch_id')) return;
  const branch = field(form,'branch_id'); const contacts = [];
  for (let offset=0; ; offset+=500) {
    const page = await api(`/customers?branch_id=${branch}&limit=500&offset=${offset}`); contacts.push(...page);
    if (page.length < 500) break;
  }
  if (branch !== field(form,'branch_id') || field(form,'payment_method') !== 'credit' || readPending(form)) return;
  choices(form.elements.customer_id, contacts.filter(customer=>customer.is_active).map(customer=>[customer.id,`#${customer.id} / ${customer.name}`]), 'Choose registered customer');
}
$('#sale-form').elements.payment_method.addEventListener('change',()=>updateCreditCustomer().catch(error=>notice(error.message,true)));
$('#sale-form').elements.branch_id.addEventListener('change',()=>updateCreditCustomer().catch(error=>notice(error.message,true)));
function renderCredit() {
  table('#credit-table', ['Invoice','Branch','Customer','Original credit sale','Net repayments','Debt reduced','Outstanding','Recorded / WAT','Action'], state.creditSales.map(record=>{
    const actions=node('div',null,'row-actions'); const print=node('button','Print invoice','secondary'); print.type='button';
    print.addEventListener('click',async()=>{try{receiptDetails(await api(`/checkouts/${record.id}`));printReceipt(state.receipt)}catch(error){notice(error.message,true)}}); actions.append(print);
    if((manager() || record.branch_id === state.user.branch_id) && kobo(record.outstanding)>0n){const pay=node('button','Repay','secondary');pay.type='button';pay.addEventListener('click',()=>{const form=$('#repayment-form');if(readPending(form)){notice('Retry the saved repayment first.',true);return;}form.elements.order_id.value=record.id;form.scrollIntoView({behavior:'smooth',block:'center'});});actions.append(pay);}
    return [record.receipt_number,branchName(record.branch_id),record.customer_name,money(record.total_amount),money(record.repaid),money(record.debt_reduced),money(record.outstanding),date(record.created_at),actions];
  }));
  if(!readPending($('#repayment-form'))) choices($('#repayment-order'),state.creditSales.filter(record=>kobo(record.outstanding)>0n).map(record=>[record.id,`${record.receipt_number} / ${record.customer_name} / owed ${money(record.outstanding)}`]),'Choose outstanding invoice');
  table('#repayments-table',['Receipt','Invoice','Branch','Amount','Method','Recorded by','Recorded / WAT','Notes','Action'],state.repayments.map(record=>{
    const actions=node('div',null,'row-actions');const print=node('button','Print repayment','secondary');print.type='button';
    print.addEventListener('click',()=>{receiptDetails({...record,receipt_type:'repayment',items:[],total_amount:record.amount,salesperson_name:record.recorded_by_name,notes:`Invoice FAS-${String(record.order_id).padStart(8,'0')} / ${record.notes || ''}`});printReceipt(state.receipt);});actions.append(print);
    if(manager() && kobo(record.amount)>0n){const reverse=node('button','Reverse entry','secondary');reverse.type='button';reverse.addEventListener('click',()=>{const form=$('#repayment-void-form');if(readPending(form)){notice('Retry the saved reversal first.',true);return;}form.reset();form.hidden=false;form.elements.repayment_id.value=record.id;$('#repayment-void-label').textContent=`Reverse ${record.receipt_number} / ${money(record.amount)}. Only correct mistaken entries; this does not move money through a bank.`;form.scrollIntoView({behavior:'smooth',block:'center'});});actions.append(reverse);}
    return [record.receipt_number,`FAS-${String(record.order_id).padStart(8,'0')}`,branchName(record.branch_id),money(record.amount),paymentName(record.payment_method),record.recorded_by_name,date(record.created_at),record.notes || '',actions];
  }));
}
$('#repayment-form').addEventListener('submit',event=>{event.preventDefault();const form=event.currentTarget;stockSubmit(form,'/credit-repayments',()=>({order_id:Number(field(form,'order_id')),amount:field(form,'amount'),payment_method:field(form,'payment_method'),notes:nullable(field(form,'notes'))}),record=>{notice(`Repayment ${record.receipt_number} recorded. Outstanding: ${money(record.outstanding)}.`);});});
$('#repayment-void-form').addEventListener('submit',event=>{event.preventDefault();const form=event.currentTarget;stockSubmit(form,`/credit-repayments/${field(form,'repayment_id')}/void`,()=>({reason:field(form,'reason').trim()}),record=>{form.hidden=true;notice(`Repayment reversed: ${record.receipt_number}.`);});});

// Keep historical category labels intact while presenting four shop departments.
const SHOP_CATEGORIES = [
  {id:'feed',label:'Feeds',value:'Feed',icon:'FE',aliases:['feed','feeds','poultry feed','poultry feeds']},
  {id:'vet',label:'Veterinary medication',value:'Medicine',icon:'RX',aliases:['medicine','medicines','medication','medications','vaccine','vaccines','veterinary medicine','veterinary medication']},
  {id:'equipment',label:'Poultry equipment',value:'Equipment',icon:'EQ',aliases:['equipment','equipments','poultry equipment','poultry equipments']},
  {id:'other',label:'Other products',value:'Other',icon:'OT',aliases:['other','others','other products']}
];
function categoryOf(product) {
  const raw=(product?.category || '').trim().toLowerCase().replace(/[_-]+/g,' ').replace(/\s+/g,' ');
  return SHOP_CATEGORIES.find(category=>category.aliases.includes(raw))?.id || 'other';
}
const categoryLabel = id => SHOP_CATEGORIES.find(category=>category.id===id)?.label || 'Other products';
const itemNumber = id => '#' + String(id).padStart(6,'0');
const productAlphabet = new Intl.Collator('en', {sensitivity:'base', numeric:true});
function compareProductNames(first, second) {
  // Inventory rows use "product"; catalogue rows use "name". Sort copies only.
  return productAlphabet.compare((first.name || first.product || '').trim(), (second.name || second.product || '').trim())
    || productAlphabet.compare(first.branch || '', second.branch || '')
    || (first.id || first.product_id || 0) - (second.id || second.product_id || 0);
}
function productCategoryChoices() {
  const values=SHOP_CATEGORIES.map(category=>[category.value,category.label]);
  for(const raw of [...new Set(state.products.map(product=>product.category))]) {
    if(!values.some(([value])=>value===raw)) values.push([raw,`${categoryLabel(categoryOf({category:raw}))} / ${raw}`]);
  }
  return values;
}
function matchesProduct(product, search) {
  const value=search.trim().toLowerCase();
  return !value || [product.name,product.category,categoryLabel(categoryOf(product)),product.barcode || '',itemNumber(product.id)].some(text=>text.toLowerCase().includes(value));
}
function renderCategoryButtons(selector,selected,products,choose) {
  const host=$(selector);host.replaceChildren();
  for(const category of [{id:'all',label:'All products'},...SHOP_CATEGORIES]) {
    const count=new Set(products.filter(product=>category.id==='all'||categoryOf(product)===category.id).map(product=>product.id)).size;
    const button=node('button',null,`category-button ${selected===category.id?'selected':''}`);button.type='button';button.dataset.category=category.id;
    button.setAttribute('aria-pressed',String(selected===category.id));button.append(node('span',category.label),node('span',String(count),'category-count'));
    button.addEventListener('click',()=>choose(category.id));host.append(button);
  }
}
function groupedTables(selector,rows,group,headings,values) {
  const host=$(selector);host.replaceChildren();
  if(!rows.length){host.append(node('p','No matching products in this category.','muted category-empty'));return;}
  for(const category of SHOP_CATEGORIES) {
    const items=rows.filter(row=>group(row)===category.id).sort(compareProductNames);if(!items.length)continue;
    const section=node('section',null,`category-section category-${category.id}`);const heading=node('div',null,'category-heading');
    heading.append(node('span',category.icon,'department-icon'),node('h3',category.label),node('span',`${items.length} record(s)`,'muted small'));
    const target=node('div',null,'table-wrap');target.id=selector.slice(1)+'-'+category.id;section.append(heading,target);host.append(section);
    table('#'+target.id,headings,items.map(values));
  }
}
function renderInventoryCategories() {
  const products=state.inventory.map(item=>state.products.find(product=>product.id===item.product_id)||{id:item.product_id,name:item.product,category:''});
  renderCategoryButtons('#inventory-categories',state.inventoryCategory,products,category=>{state.inventoryCategory=category;renderInventoryCategories();});
  const rows=state.inventory.filter(item=>{const product=state.products.find(p=>p.id===item.product_id)||{id:item.product_id,name:item.product,category:''};return matchesProduct(product,$('#inventory-search').value)&&(state.inventoryCategory==='all'||categoryOf(product)===state.inventoryCategory);});
  groupedTables('#inventory-table',rows,item=>categoryOf(state.products.find(p=>p.id===item.product_id)),['Product','Branch','Available','Unit','Barcode / item number',...(manager()?['Action']:[])],item=>[node('strong',item.product),item.branch,item.quantity,item.unit,state.products.find(p=>p.id===item.product_id)?.barcode||itemNumber(item.product_id),...(manager()?[editProductButton(item.product_id)]:[])]);
}
// Suggestions use the loaded catalogue, so each keystroke needs no network request.
let suggestionIndex = -1;
function matchingPosSuggestions() {
  return state.products.filter(product=>product.is_active && matchesProduct(product,$('#pos-search').value))
    .sort(compareProductNames).slice(0,12);
}
function hidePosSuggestions() {
  $('#pos-suggestions').hidden=true; $('#pos-search').setAttribute('aria-expanded','false');
  $('#pos-search').removeAttribute('aria-activedescendant'); suggestionIndex=-1;
}
function choosePosSuggestion(product) {
  hidePosSuggestions();
  const form=$('#sale-form');
  if(!field(form,'branch_id')) {
    form.elements.product_id.value=product.id;updateSalePolicy();$('#pos-search').value=product.name;
    notice('Choose the sale branch, then add this product to the basket.');form.elements.branch_id.focus();return;
  }
  addPosProduct(product); $('#pos-search').focus({preventScroll:true}); hidePosSuggestions();
}
function renderPosSuggestions() {
  const input=$('#pos-search'),host=$('#pos-suggestions');
  if(!state.user || document.activeElement!==input){hidePosSuggestions();return;}
  const products=matchingPosSuggestions(),branch=field($('#sale-form'),'branch_id');host.replaceChildren();
  if(suggestionIndex>=products.length)suggestionIndex=-1;
  if(!products.length)host.append(node('p','No matching products. Try another name or barcode.','small muted'));
  products.forEach((product,index)=>{
    const option=node('button',null,'pos-suggestion');option.type='button';option.id='pos-suggestion-'+product.id;
    option.dataset.suggestProduct=product.id;option.setAttribute('role','option');option.setAttribute('aria-selected',String(index===suggestionIndex));
    const stock=state.posBranch===branch?(state.posInventory.find(row=>row.product_id===product.id)?.quantity||0):null;
    option.append(node('strong',product.name),node('span',`${money(product.selling_price)} / ${product.base_unit} ? ${branch?(stock===null?'Loading stock':stock+' available'):'Choose a branch'}`,'small muted'));
    option.addEventListener('mousedown',event=>event.preventDefault());
    option.addEventListener('click',()=>choosePosSuggestion(product));host.append(option);
  });
  host.hidden=false;input.setAttribute('aria-expanded','true');
  if(suggestionIndex>=0){const option=host.children[suggestionIndex];input.setAttribute('aria-activedescendant',option.id);option.scrollIntoView({block:'nearest'});}
  else input.removeAttribute('aria-activedescendant');
}
function renderPosProducts() {
  if(!state.user) return;
  renderPosSuggestions();
  const form=$('#sale-form');const active=state.products.filter(product=>product.is_active).sort((first,second)=>
    SHOP_CATEGORIES.findIndex(category=>category.id===categoryOf(first))-SHOP_CATEGORIES.findIndex(category=>category.id===categoryOf(second)) || compareProductNames(first,second));
  renderCategoryButtons('#pos-categories',state.posCategory,active,category=>{state.posCategory=category;renderPosProducts();});
  const branch=field(form,'branch_id');const pending=readPending(form);const products=active.filter(product=>matchesProduct(product,$('#pos-search').value)&&(state.posCategory==='all'||categoryOf(product)===state.posCategory));
  $('#pos-stock-hint').textContent=branch ? `Available at ${branchName(Number(branch))}. Click a product to add one unit.` : 'Choose the sale branch to see available stock and add products.';
  $('#pos-basket-count').textContent=state.cart.reduce((sum,item)=>sum+Math.max(0,Number(item.quantity)||0),0)+' items in basket';
  const host=$('#pos-products');host.replaceChildren();
  if(!products.length){host.append(node('p','No matching products. Try another category or search.','muted'));return;}
  for(const product of products) {
    const category=SHOP_CATEGORIES.find(category=>category.id===categoryOf(product));const stock=state.posBranch===branch ? (state.posInventory.find(item=>item.product_id===product.id)?.quantity||0) : 0;
    const inCart=state.cart.find(item=>item.product_id===product.id)?.quantity||0;
    const card=node('article',null,`pos-product category-${category.id}`);card.dataset.productId=product.id;
    const header=node('div',null,'pos-product-head');header.append(node('span',category.icon,'department-icon'),node('span',category.label,'small muted'));
    card.append(header,node('h3',product.name),node('p',product.barcode||itemNumber(product.id),'small muted'),node('strong',product.selling_price==null?'Price needed':money(product.selling_price),'pos-price'),node('p',`per ${product.base_unit}`,'small muted'));
    if(branch)card.append(node('p',`${stock} ${product.base_unit} available${inCart ? ' / '+inCart+' in basket':''}`,'stock-label'));
    const add=node('button',branch && stock<=inCart?'Out of stock':'Add to basket','primary');add.type='button';add.dataset.addProduct=product.id;add.setAttribute('aria-label',`Add ${product.name} to basket`);
    add.disabled=!!pending||$('#refresh').disabled||!branch||product.selling_price==null||stock<=inCart;add.addEventListener('click',()=>addPosProduct(product));card.append(add);host.append(card);
  }
}
async function updatePosStock() {
  if(!state.user) return;
  const branch=field($('#sale-form'),'branch_id'), actor=state.user.id;
  state.posBranch='';state.posInventory=[];renderPosProducts();
  if(!branch)return;
  const rows=(!state.filter||state.filter===branch) ? state.inventory.filter(item=>item.branch_id===Number(branch)) : await api('/inventory?branch_id='+branch);
  if(state.user?.id!==actor || field($('#sale-form'),'branch_id')!==branch)return;
  state.posInventory=rows;state.posBranch=branch;renderPosProducts();
}
function addPosProduct(product) {
  const form=$('#sale-form');if(readPending(form)){notice('Retry the saved sale first.',true);return;}
  const branch=field(form,'branch_id');if(!branch){notice('Choose the sale branch first.',true);form.elements.branch_id.focus();return;}
  const stock=state.posBranch===branch ? state.posInventory.find(item=>item.product_id===product.id)?.quantity||0 : 0;
  const existing=state.cart.find(item=>item.product_id===product.id);
  if(!product.is_active||product.selling_price==null||stock<=(existing?.quantity||0)){notice('This product needs a price and available branch stock before selling.',true);return;}
  form.elements.product_id.value=product.id;updateSalePolicy();form.elements.quantity.value='1';form.elements.unit_price.value=existing?.unit_price||product.selling_price;
  if(addCartItem()){ $('#pos-search').value='';renderPosProducts(); }
}
$('#inventory-search').addEventListener('input',renderInventoryCategories);
$('#pos-search').addEventListener('input',()=>{
  suggestionIndex=-1;state.posCategory='all';
  if(/^(No exact barcode match|No matching products)/.test($('#notice').textContent))notice('');
  renderPosProducts();
});
$('#pos-search').addEventListener('focus',renderPosSuggestions);
$('.pos-search-box').addEventListener('focusout',event=>{if(!event.currentTarget.contains(event.relatedTarget))hidePosSuggestions();});
document.addEventListener('pointerdown',event=>{if(!$('.pos-search-box').contains(event.target))hidePosSuggestions();});
$('#sale-form').elements.branch_id.addEventListener('change',()=>updatePosStock().catch(error=>notice(error.message,true)));
$('#pos-search').addEventListener('keydown',event=>{
  if(event.key==='Escape'){event.preventDefault();hidePosSuggestions();return;}
  if(event.key==='ArrowDown'||event.key==='ArrowUp') {
    event.preventDefault();const matches=matchingPosSuggestions();
    if(matches.length){suggestionIndex=suggestionIndex<0?(event.key==='ArrowDown'?0:matches.length-1):(suggestionIndex+(event.key==='ArrowDown'?1:matches.length-1)+matches.length)%matches.length;renderPosSuggestions();}
    return;
  }
  if(event.key!=='Enter')return;event.preventDefault();
  const code=event.currentTarget.value.trim();if(!code && suggestionIndex<0)return;
  // Exact scanner codes still work; typed names use the suggestion selection instead.
  const exact=state.products.find(product=>product.is_active && product.barcode===code) || (/^#\d+$/.test(code)?state.products.find(product=>product.is_active && product.id===Number(code.slice(1))):null);
  const matches=matchingPosSuggestions();
  const selected=exact || (suggestionIndex>=0?matches[suggestionIndex]:matches.length===1?matches[0]:null);
  if(selected)choosePosSuggestion(selected);
  else if(matches.length){suggestionIndex=0;renderPosSuggestions();}
  else {renderPosSuggestions();notice('No matching products. Check the name or barcode.',true);}
});

// Attach every handler before restoring the session or enabling manual sign-in.
Offline.boot().then(token=>{if(token&&!savedSessionToken())saveSessionToken(token);return restoreSession();}).finally(() => { $('#login-form [type=submit]').disabled = false; });
