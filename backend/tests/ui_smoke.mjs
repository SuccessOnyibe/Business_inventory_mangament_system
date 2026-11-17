// Browser smoke test using Chrome's DevTools protocol, with no third-party packages.
// Run only against prepare_ui_test.py's isolated database and test accounts.
import assert from 'node:assert/strict';
import { writeFile } from 'node:fs/promises';
import { dirname, join } from 'node:path';

const base = process.env.UI_TEST_URL;
assert.equal(base, 'http://127.0.0.1:58541', 'Only the dedicated UI-test server is allowed');
assert.ok(process.env.UI_TEST_PASSWORD);
const targets = await (await fetch('http://127.0.0.1:9223/json/list')).json();
const socket = new WebSocket(targets.find(target => target.type === 'page').webSocketDebuggerUrl);
await new Promise((resolve, reject) => { socket.onopen = resolve; socket.onerror = reject; });
let nextId = 0;
const waiting = new Map();
const exceptions = [];
socket.onclose = () => {
  for (const handler of waiting.values()) handler.reject(new Error('Test Chrome disconnected before responding'));
  waiting.clear();
};
socket.onmessage = event => {
  const message = JSON.parse(event.data);
  if (message.method === 'Runtime.exceptionThrown') exceptions.push(message.params.exceptionDetails.text);
  const handler = waiting.get(message.id);
  if (handler) { waiting.delete(message.id); message.error ? handler.reject(message.error) : handler.resolve(message.result); }
};
function send(method, params = {}) {
  return new Promise((resolve, reject) => { const id = ++nextId; waiting.set(id, { resolve, reject }); socket.send(JSON.stringify({ id, method, params })); });
}
async function evaluate(expression) {
  // CDP awaits returned promises, but top-level await needs an async wrapper.
  if (expression.includes('await ')) expression = `(async () => (${expression}))()`;
  const result = await send('Runtime.evaluate', { expression, awaitPromise: true, returnByValue: true });
  if (result.exceptionDetails) throw new Error(JSON.stringify(result.exceptionDetails));
  return result.result.value;
}
async function wait(expression) {
  const started = Date.now();
  while (Date.now() - started < 15000) {
    if (await evaluate(expression)) return;
    await new Promise(resolve => setTimeout(resolve, 100));
  }
  throw new Error('Timed out waiting for: ' + expression + '\nNotice: ' + await evaluate("document.querySelector('#notice')?.textContent"));
}
async function fill(formId, values) {
  await evaluate(`(() => { const form = document.getElementById(${JSON.stringify(formId)}); for (const [key,value] of Object.entries(${JSON.stringify(values)})) { const input = form.elements.namedItem(key); input.value = value; input.dispatchEvent(new Event('change', { bubbles:true })); input.dispatchEvent(new Event('input', { bubbles:true })); } })()`);
}
const submit = id => evaluate(`document.getElementById(${JSON.stringify(id)}).requestSubmit()`);
const navigate = view => evaluate(`document.querySelector('[data-view="${view}"]').click()`);
async function saved(message) { await wait(`document.querySelector('#notice').textContent.includes(${JSON.stringify(message)}) && !document.querySelector('#refresh').disabled && !document.querySelector('form [type=submit]:disabled')`); }
async function login(username) {
  await wait("document.readyState === 'complete' && !document.querySelector('#login-form [type=submit]').disabled");
  await fill('login-form', { username, password: process.env.UI_TEST_PASSWORD }); await submit('login-form');
  await wait("!document.querySelector('#workspace').hidden && document.querySelector('#inventory-table tbody tr') && !document.querySelector('#refresh').disabled");
}

try {
  assert.equal((await fetch(base + '/health/ready')).status, 200);
  await send('Runtime.enable'); await send('Page.enable');
  await send('Emulation.setDeviceMetricsOverride',{width:1440,height:1000,deviceScaleFactor:1,mobile:false});
  await send('Page.navigate', { url: base + '/app/' });
  await wait("document.querySelector('#login-form') !== null");
  await login('ui_admin');
  const originalSession = await evaluate('state.token');
  async function reloadSignedIn() {
    await evaluate('window.beforeSessionReload = true');
    await send('Page.reload');
    await wait("!window.beforeSessionReload && document.readyState === 'complete' && !document.querySelector('#login-form [type=submit]').disabled && !document.querySelector('#workspace').hidden && !document.querySelector('#refresh').disabled");
  }
  await reloadSignedIn();
  assert.equal(await evaluate('state.token'),originalSession,'Refresh must reuse the existing session');
  assert.equal(await evaluate("document.querySelector('#login-form').elements.password.value"),'');
  // A temporary connection failure must not destroy a still-valid saved session.
  await send('Network.enable');
  await send('Network.setBlockedURLs',{urls:['*/auth/me']});
  await evaluate('window.beforeSessionReload = true');await send('Page.reload');
  await wait("!window.beforeSessionReload && document.readyState === 'complete' && document.querySelector('#login-error').textContent.includes('Could not restore')");
  assert.equal(await evaluate('sessionStorage.getItem(SESSION_KEY)'),originalSession);
  await send('Network.setBlockedURLs',{urls:[]});
  await reloadSignedIn();
  assert.equal(await evaluate('state.token'),originalSession);
  // Revoke at the server while keeping browser storage to test restoration rejection.
  await evaluate("api('/auth/logout',{method:'POST'})");
  await evaluate('window.beforeSessionReload = true');await send('Page.reload');
  await wait("!window.beforeSessionReload && document.readyState === 'complete' && document.querySelector('#login-error').textContent.includes('session ended')");
  assert.equal(await evaluate('sessionStorage.getItem(SESSION_KEY)'),null);
  assert.equal(await evaluate('state.user'),null);
  await login('ui_admin');

  assert.equal(await evaluate("document.querySelector('[data-view=cash]')"),null);
  assert.equal(await evaluate("document.querySelectorAll('.sidebar [data-view]')[2].dataset.view"),'products');
  await evaluate("document.querySelector('[data-stock-action=open]').click()");
  assert.equal(await evaluate('state.view'),'receiving');
  await fill('receipt-form',{branch_id:'1',quantity:'10'});
  await evaluate("document.querySelector('#new-receiving-product').click()");
  assert.equal(await evaluate('state.view'),'products');
  assert.equal(await evaluate("document.activeElement === document.querySelector('#product-form').elements.name"),true);
  const productName = 'UI medicine <img src=x onerror=window.injected=1>';
  await fill('product-form', { name: productName, category: 'Medicine', barcode:'0012345678905', base_unit: 'piece', selling_price: '500.00', max_discount_percent: '10' });
  await submit('product-form'); await saved('Product added');
  assert.equal(await evaluate('window.injected'), undefined, 'Names must be rendered as text');
  const newProductId = await evaluate(`state.products.find(product => product.name === ${JSON.stringify(productName)}).id`);
  assert.equal(await evaluate('state.view'),'receiving');
  assert.equal(await evaluate("document.querySelector('#receipt-form').elements.branch_id.value"),'1');
  assert.equal(await evaluate("document.querySelector('#receipt-form').elements.product_id.value"),String(newProductId));
  assert.equal(await evaluate("document.querySelector('#receipt-form').elements.quantity.value"),'10');
  assert.equal(await evaluate(`(await api('/inventory')).some(row=>row.product_id===${newProductId})`),false);
  await navigate('products');
  await evaluate("document.querySelector('#product-categories [data-category=vet]').click()");
  assert.match(await evaluate("document.querySelector('#products-table').textContent"),/Veterinary medication/);
  assert.doesNotMatch(await evaluate("document.querySelector('#products-table').textContent"),/Chikun Starter Feed/);
  await evaluate("document.querySelector('#product-categories [data-category=all]').click()");

  await navigate('inventory');
  await evaluate("document.querySelector('#inventory-table button').click()");
  assert.equal(await evaluate('state.view'),'products');
  assert.equal(await evaluate("document.querySelector('#edit-product').value"),'1');
  assert.equal(await evaluate("document.querySelector('#price-form').elements.name.value"),'Chikun Starter Feed');
  await navigate('inventory');
  await evaluate("document.querySelector('[data-product-action=edit]').click()");
  assert.equal(await evaluate("document.activeElement.id"),'edit-product');
  await navigate('inventory');
  await evaluate("document.querySelector('[data-stock-action=open]').click(); document.querySelector('#receipt-form details').open = true");
  await fill('receipt-form', { branch_id: '1', product_id: String(newProductId), quantity: '10', batch_number:'UI-LOT-17', expires_on:'2099-12-31', notes: 'UI test receipt' });
  await submit('receipt-form'); await saved('Stock received');
  assert.match(await evaluate("document.querySelector('#receipt-result-text').textContent"),/Stock now: 10/);
  await fill('receipt-form',{branch_id:'2',product_id:String(newProductId),quantity:'7'});
  await submit('receipt-form'); await saved('Stock received');
  assert.equal(await evaluate(`(await api('/inventory?branch_id=1')).find(row=>row.product_id===${newProductId}).quantity`),10);
  assert.equal(await evaluate(`(await api('/inventory?branch_id=2')).find(row=>row.product_id===${newProductId}).quantity`),7);
  await evaluate("document.querySelector('#view-received-branch').click()");
  await wait("!document.querySelector('#refresh').disabled");
  assert.equal(await evaluate('state.view'),'inventory');
  assert.equal(await evaluate('state.filter'),'2');
  await evaluate("document.querySelector('#branch-filter').value='';document.querySelector('#branch-filter').dispatchEvent(new Event('change'))");
  await wait("!document.querySelector('#refresh').disabled");
  assert.match(await evaluate("document.querySelector('#receipts-table').textContent"), /UI-LOT-17/);
  assert.match(await evaluate("document.querySelector('#receipts-table').textContent"), /2099-12-31/);
  assert.equal(await evaluate("(await api('/stock-receipts'))[0].received_by_name"), 'ui_admin');
  assert.equal(await evaluate("document.querySelectorAll('#inventory-table .category-section').length"),2);
  await navigate('sales');await fill('sale-form',{branch_id:'1'});
  await wait("state.posBranch === '1'");
  await evaluate("document.querySelector('#pos-categories [data-category=feed]').click()");
  assert.equal(await evaluate(`document.querySelector('#pos-products [data-product-id="${newProductId}"]')`),null);
  await evaluate("document.querySelector('#pos-products [data-add-product=\"1\"]').click()");
  assert.equal(await evaluate('state.cart[0].quantity'),1);
  await evaluate("document.querySelector('#pos-products [data-add-product=\"1\"]').click()");
  assert.equal(await evaluate('state.cart[0].quantity'),2);
  await evaluate("document.querySelector('#cart-table button').click()");
  await evaluate("document.querySelector('#pos-categories [data-category=vet]').click()");
  await evaluate("(() => {const input=document.querySelector('#pos-search');input.value='0012345678905';input.dispatchEvent(new Event('input'));input.dispatchEvent(new KeyboardEvent('keydown',{key:'Enter',bubbles:true}));})()");
  assert.equal(await evaluate('state.cart[0].product_id'),newProductId);
  await evaluate("document.querySelector('#cart-table button').click()");
  await evaluate("document.querySelector('#pos-categories [data-category=all]').click()");

  await navigate('accounts');
  await fill('account-form', { username: 'ui_newseller', password: process.env.UI_TEST_PASSWORD, role: 'salesperson', branch_id: '2' });
  await submit('account-form'); await saved('Account created');

  await navigate('sales');
  await fill('sale-form', { branch_id: '1', product_id: '1', quantity: '2', unit_price: '24000.00', payment_method: 'pos', customer_name: 'UI customer' });
  await submit('sale-form'); await saved('Sale #');
  assert.match(await evaluate("document.querySelector('#sale-receipt').textContent"), /POS terminal/);
  assert.equal(await evaluate("(await api('/checkouts')).length"), 1);

  // Simulate losing a successful response after the server commits the sale.
  await evaluate(`(() => { const original = window.fetch; let once = true; window.fetch = async (...args) => { const response = await original(...args); if (once && args[0] === '/checkouts' && args[1]?.method === 'POST' && response.ok) { once = false; throw new TypeError('Simulated lost response'); } return response; }; })()`);
  await fill('sale-form', { branch_id: '1', product_id: '1', quantity: '1', unit_price: '25000.00', payment_method: 'cash' });
  await submit('sale-form'); await wait("document.querySelector('#sale-form [type=submit]').textContent === 'Retry saved request'");
  assert.equal(await evaluate("document.querySelector('#sale-price').disabled"), true);
  // The session and pending key survive together; retry still cannot duplicate a sale.
  await reloadSignedIn(); await navigate('sales');
  assert.equal(await evaluate("document.querySelector('#sale-form [type=submit]').textContent"), 'Retry saved request');
  await submit('sale-form'); await saved('Cash');
  assert.equal(await evaluate("(await api('/checkouts')).length"), 2, 'Retry must not create a third purchase');

  await fill('sale-form', { branch_id: '1', product_id: '1', quantity: '2', unit_price: '24000.00' });
  await evaluate("document.querySelector('#add-sale-item').click()");
  await fill('sale-form', { product_id: String(newProductId), quantity: '3', unit_price: '450.00', payment_method: 'pos' });
  await evaluate("document.querySelector('#add-sale-item').click()");
  assert.match(await evaluate("document.querySelector('#sale-total').textContent"), /49,350\.00/);
  await submit('sale-form'); await saved('Sale #');
  assert.equal(await evaluate('state.receipt.items.length'), 2);
  await evaluate("window.print = () => { window.printedReceipt = document.querySelector('#receipt-paper').innerText; }; document.querySelector('#print-latest').click()");
  assert.match(await evaluate('window.printedReceipt'), /FESTY AGRIC SERVICES/);
  // Hidden print content still contains all line items; print media makes only it visible.
  assert.match(await evaluate("document.querySelector('#receipt-paper').textContent"), /49,350\.00/);
  await send('Emulation.setEmulatedMedia', { media: 'print' });
  assert.equal(await evaluate("getComputedStyle(document.querySelector('#workspace')).display"), 'none');
  assert.equal(await evaluate("getComputedStyle(document.querySelector('#print-receipt')).display"), 'block');
  if (process.env.UI_SCREENSHOT_PATH) {
    const pdf = await send('Page.printToPDF', { printBackground: true, preferCSSPageSize: true });
    await writeFile(process.env.UI_SCREENSHOT_PATH.replace(/\.png$/, '-receipt.pdf'), Buffer.from(pdf.data, 'base64'));
  }
  await send('Emulation.setEmulatedMedia', { media: 'screen' });
  await evaluate("document.querySelector('#sales-table button').click()");
  await wait("document.querySelector('#sales-table button').disabled === false");

  await navigate('transfers');
  await evaluate("document.querySelector('#transfer-form').closest('details').open = true");
  await fill('transfer-form', { source_branch_id: '1', destination_branch_id: '2', product_id: '1', quantity: '5' });
  await submit('transfer-form'); await saved('dispatched');
  await evaluate("document.querySelector('#logout').click()");
  await wait("!document.querySelector('#login-screen').hidden");

  // The receiving Salesperson sees only Branch 2 and can confirm its incoming goods.
  await fill('login-form', { username: 'ui_seller', password: process.env.UI_TEST_PASSWORD }); await submit('login-form');
  await wait("!document.querySelector('#workspace').hidden && !document.querySelector('#refresh').disabled && state.user?.username === 'ui_seller'");
  assert.deepEqual(await evaluate('state.branches.map(branch => branch.id)'), [2]);
  assert.equal(await evaluate("getComputedStyle(document.querySelector('#product-form').closest('.manager-only')).display"), 'none');
  await navigate('transfers');
  await evaluate("window.confirm = () => true; document.querySelector('#transfers-table button').click()"); await saved('received on');
  await navigate('sales');
  await fill('sale-form', { product_id: '1', quantity: '1', unit_price: '25000.00', payment_method: 'pos' });
  await submit('sale-form'); await saved('POS terminal');
  assert.equal(await evaluate("(await api('/checkouts'))[0].branch_id"), 2);
  assert.equal(await evaluate("(await api('/inventory'))[0].quantity"), 4);

  await navigate('reconciliations');
  await wait("document.querySelector('#reconciliation-summary').textContent.includes('25,000.00')");
  await fill('reconciliation-form', { actual_cash: '0.00', actual_pos: '24900.00', notes: 'Terminal report short by 100' });
  await submit('reconciliation-form'); await saved('Daily count #');
  assert.match(await evaluate("document.querySelector('#reconciliations-table').textContent"), /-₦100\.00/);
  assert.equal(await evaluate("document.querySelector('#reconciliations-table button') === null"), true, 'Salesperson cannot review');
  await evaluate("document.querySelector('#logout').click()");
  await wait("!document.querySelector('#login-screen').hidden");
  await login('ui_admin'); await navigate('reconciliations');
  await evaluate("window.prompt = () => 'Checked terminal report; shortage recorded'; document.querySelector('#reconciliations-table button').click()");
  await saved('reviewed on');
  assert.equal(await evaluate("(await api('/reconciliations'))[0].status"), 'reviewed');
  assert.ok(await evaluate("(await api('/reconciliations'))[0].reviewed_at"));

  // Reconcile Branch 1, then prove a later return marks that snapshot out of date.
  await fill('reconciliation-form', { branch_id: '1', actual_cash: '25000.00', actual_pos: '97350.00' });
  await submit('reconciliation-form'); await saved('Daily count #');
  await navigate('sales');
  const multi = await evaluate("(await api('/checkouts')).find(receipt => receipt.item_count === 2)");
  const beforeReturn = await evaluate("(await api('/inventory?branch_id=1')).find(item => item.product_id === 1).quantity");
  await evaluate(`(() => {const row=[...document.querySelectorAll('#sales-table tbody tr')].find(row=>row.textContent.includes(${JSON.stringify(multi.receipt_number)})); row.querySelectorAll('button')[1].click();})()`);
  await wait("!document.querySelector('#correction-form').hidden");
  await evaluate("document.querySelector('.correction-quantity').value='1'; document.querySelector('.correction-quantity').dispatchEvent(new Event('input',{bubbles:true}))");
  await fill('correction-form', { reason: 'Returned bag damaged; keep out of available stock' });
  await submit('correction-form'); await saved('Correction FAS-C-');
  assert.equal(await evaluate("(await api('/inventory?branch_id=1')).find(item => item.product_id === 1).quantity"), beforeReturn);
  assert.equal(await evaluate(`(await api('/checkouts/${multi.id}')).status`), 'partially_returned');
  assert.equal(await evaluate("(await api('/sale-corrections'))[0].refund_total"), '24000.00');
  const day = await evaluate("document.querySelector('#reconciliation-date').value");
  assert.equal(await evaluate(`(await api('/reconciliations/summary?branch_id=1&business_date=${day}')).is_stale`), true);

  const cash = await evaluate("(await api('/checkouts')).find(receipt => receipt.payment_method === 'cash')");
  await evaluate(`(() => {const row=[...document.querySelectorAll('#sales-table tbody tr')].find(row=>row.textContent.includes(${JSON.stringify(cash.receipt_number)}));row.querySelectorAll('button')[1].click();})()`);
  await wait(`document.querySelector('#correction-form').elements.receipt_id.value === '${cash.id}' && !document.querySelector('#correction-form').hidden`);
  await fill('correction-form', { kind: 'void', reason: 'Cash sale entered incorrectly' });
  await submit('correction-form'); await saved('Correction FAS-C-');
  assert.equal(await evaluate(`(await api('/checkouts/${cash.id}')).status`), 'voided');
  assert.equal(await evaluate("(await api('/inventory?branch_id=1')).find(item => item.product_id === 1).quantity"), beforeReturn + 1);
  assert.equal(await evaluate("(await api('/checkouts')).length"), 4, 'Original purchases remain present');
  await evaluate("document.querySelector('#corrections-table button').click()");
  await wait("document.querySelector('#corrections-table button').disabled === false");
  assert.match(await evaluate("document.querySelector('#receipt-paper').textContent"), /Refund \/ reversal/);
  await evaluate(`(() => {const row=[...document.querySelectorAll('#sales-table tbody tr')].find(row=>row.textContent.includes(${JSON.stringify(multi.receipt_number)}));row.querySelector('button').click();})()`);
  await wait("document.querySelector('#receipt-paper').textContent.includes('partially returned')");

  await navigate('reconciliations');
  const openBranchTwoDecision = () => evaluate("[...document.querySelectorAll('#reconciliations-table tbody tr')].find(row=>row.textContent.includes('Branch 2')).querySelector('button').click()");
  await openBranchTwoDecision();
  await wait("!document.querySelector('#discrepancy-form').hidden");
  await fill('discrepancy-form', { responsible_user_id: '2', explanation: 'Investigating the terminal report difference' });
  await submit('discrepancy-form'); await saved('Decision #');
  assert.equal(await evaluate("(await api('/discrepancy-events'))[0].resolution_state"), 'investigating');
  await openBranchTwoDecision();
  await wait("!document.querySelector('#discrepancy-form').hidden");
  await fill('discrepancy-form', { action: 'resolve', responsible_user_id: '2', explanation: 'Receipts and terminal report checked', resolution_action: 'Documented shortage accepted; responsible staff follow-up completed' });
  await submit('discrepancy-form'); await saved('Decision #');
  assert.equal(await evaluate("(await api('/discrepancy-events'))[0].resolution_state"), 'resolved');
  assert.equal(await evaluate("(await api('/reconciliations')).find(row=>row.branch_id===2).pos_difference"), '-100.00');

  await navigate('reports');
  await wait("!document.querySelector('#report-form [type=submit]').disabled");
  await fill('report-form', { start_date: day, end_date: day, branch_id: '' });
  await submit('report-form');
  await wait(`state.report?.start_date === '${day}' && state.report?.end_date === '${day}' && !document.querySelector('#report-form [type=submit]').disabled`);
  assert.equal(await evaluate('state.report.totals.net_sales'), '98350.00');
  assert.equal(await evaluate('state.report.totals.unresolved_days'), 0);
  await evaluate(`(() => { const originalURL = URL.createObjectURL; URL.createObjectURL = blob => { blob.text().then(text=>{window.csvText=text});return originalURL(blob); }; const originalClick=HTMLAnchorElement.prototype.click;HTMLAnchorElement.prototype.click=function(){if(this.download){window.csvFilename=this.download;return;}return originalClick.call(this)};document.querySelector('#export-report').click(); })()`);
  await wait("typeof window.csvText === 'string' && !document.querySelector('#export-report').disabled");
  assert.match(await evaluate('window.csvText'), /branch_name/);
  assert.match(await evaluate('window.csvText'), /resolved/);
  assert.match(await evaluate('window.csvFilename'), /^FAS-financial-/);

  await navigate('adjustments');
  await evaluate("document.querySelector('#adjustment-panel').open=true");
  await fill('adjustment-form', { branch_id:'2', product_id:'1', mode:'physical_count', amount:'3', reason:'Physical shelf count confirmed by Manager' });
  await wait("document.querySelector('#adjustment-form').elements.expected_quantity.value==='4' && !document.querySelector('#load-adjustment-balance').disabled");
  await submit('adjustment-form'); await saved('Stock adjustment #');
  assert.equal(await evaluate("(await api('/inventory?branch_id=2'))[0].quantity"), 3);
  await fill('adjustment-form', { branch_id:'2', product_id:'1', mode:'expiry', amount:'1', reason:'One expired unit removed from available stock' });
  await wait("document.querySelector('#adjustment-form').elements.expected_quantity.value==='3' && !document.querySelector('#load-adjustment-balance').disabled");
  await submit('adjustment-form'); await saved('Stock adjustment #');
  assert.equal(await evaluate("(await api('/inventory?branch_id=2'))[0].quantity"), 2);
  assert.equal(await evaluate("(await api('/stock-adjustments')).length"), 2);
  assert.equal(await evaluate(`(await api('/reports/financial?start_date=${day}&end_date=${day}')).totals.net_sales`), '98350.00');

  // Cash ledger is removed for every role, including direct API access.
  assert.equal(await evaluate("document.querySelector('[data-view=cash]')"),null);
  assert.equal(await evaluate("document.querySelector('#cash-entry-form')"),null);
  assert.equal((await fetch(base+'/cash-movements',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({branch_id:2,kind:'expense',amount:'20',reason:'Retired'})})).status,404);

  await navigate('customers');
  await fill('customer-form', { branch_id:'1', name:'Private branch one customer', phone:'08010000001' });
  await submit('customer-form'); await saved('added.');
  const customerName = 'Branch two <img src=x onerror=window.customerInjected=1>';
  await fill('customer-form', { branch_id:'2', name:customerName, phone:'08010000002', notes:'Customer contact, no opening debt' });
  await submit('customer-form'); await saved('added.');
  assert.equal(await evaluate('window.customerInjected'), undefined);
  await evaluate("document.querySelector('#customers-table button').click()");
  await fill('customer-update-form', { name:'Branch two farm', is_active:'false', notes:'Inactive contact retained' });
  await submit('customer-update-form'); await saved('updated.');
  assert.equal(await evaluate("(await api('/customers'))[0].is_active"), false);
  await evaluate("document.querySelector('#logout').click()");
  await wait("!document.querySelector('#login-screen').hidden");
  assert.equal(await evaluate('sessionStorage.getItem(SESSION_KEY)'),null);
  await evaluate('window.beforeSessionReload = true');await send('Page.reload');
  await wait("!window.beforeSessionReload && document.readyState === 'complete' && !document.querySelector('#login-form [type=submit]').disabled");
  assert.equal(await evaluate("document.querySelector('#workspace').hidden"),true,'Logout must survive refresh');
  await login('ui_seller'); await navigate('customers');
  assert.equal(await evaluate('state.customers.length'), 1);
  assert.equal(await evaluate("document.querySelectorAll('#customers-table button').length"), 0);
  assert.doesNotMatch(await evaluate("document.querySelector('#customers-table').textContent"), /Private branch one/);
  await evaluate("document.querySelector('#logout').click()");
  await wait("!document.querySelector('#login-screen').hidden");
  await login('ui_admin');
  assert.equal(await evaluate(`(await api('/reports/financial?start_date=${day}&end_date=${day}')).totals.net_sales`), '98350.00');

  await navigate('sales');
  await fill('sale-form',{branch_id:'1',product_id:'1',quantity:'2',unit_price:'25000',payment_method:'credit'});
  await wait("document.querySelector('#credit-customer').options.length > 1");
  await fill('sale-form',{customer_id:'1'});await submit('sale-form');await saved('Credit / amount owed');
  const credit=await evaluate("(await api('/credit-sales'))[0]");
  assert.equal(credit.outstanding,'50000.00');
  assert.match(await evaluate("document.querySelector('#sale-receipt').textContent"),/Outstanding/);
  assert.equal(await evaluate(`(await api('/reports/financial?start_date=${day}&end_date=${day}')).totals.net_sales`),'148350.00');
  await navigate('credit');
  await fill('repayment-form',{order_id:String(credit.id),amount:'10000',payment_method:'cash',notes:'Verified customer payment'});
  await submit('repayment-form');await saved('Outstanding:');
  assert.equal(await evaluate("(await api('/credit-sales'))[0].outstanding"),'40000.00');
  await evaluate("document.querySelector('#repayments-table button').click()");
  await wait("document.querySelector('#receipt-paper').textContent.includes('Credit repayment')");
  await evaluate("document.querySelectorAll('#repayments-table button')[1].click()");
  await fill('repayment-void-form',{reason:'Mistaken payment method; re-enter correctly'});
  await submit('repayment-void-form');await saved('Repayment reversed:');
  assert.equal(await evaluate("(await api('/credit-sales'))[0].outstanding"),'50000.00');
  await fill('repayment-form',{order_id:String(credit.id),amount:'10000',payment_method:'pos'});
  await submit('repayment-form');await saved('Outstanding:');
  await navigate('sales');
  await evaluate(`(() => {const row=[...document.querySelectorAll('#sales-table tbody tr')].find(row=>row.textContent.includes(${JSON.stringify(credit.receipt_number)}));row.querySelectorAll('button')[1].click();})()`);
  await wait("!document.querySelector('#correction-form').hidden");
  await fill('correction-form',{kind:'void',reason:'Credit sale cancelled; refund collected POS portion',refund_method:'pos'});
  await submit('correction-form');await saved('Correction FAS-C-');
  assert.equal(await evaluate("(await api('/credit-sales'))[0].outstanding"),'0.00');
  assert.equal(await evaluate(`(await api('/reports/financial?start_date=${day}&end_date=${day}')).totals.net_sales`),'98350.00');

  if(process.env.UI_SCREENSHOT_PATH) {
    await navigate('sales');
    await fill('sale-form',{branch_id:'1'});
    await wait("state.posBranch === '1'");
    await evaluate('window.scrollTo(0,0)');
    const desktop=await send('Page.captureScreenshot',{format:'png',captureBeyondViewport:false});
    await writeFile(join(dirname(process.env.UI_SCREENSHOT_PATH),'till-desktop.png'),Buffer.from(desktop.data,'base64'));
  }
  await send('Emulation.setDeviceMetricsOverride', { width: 390, height: 844, deviceScaleFactor: 1, mobile: true });
  await navigate('sales');
  assert.equal(await evaluate('document.documentElement.scrollWidth <= window.innerWidth'),true,'Mobile till must not overflow');
  await navigate('inventory');
  assert.equal(await evaluate('document.documentElement.scrollWidth <= window.innerWidth'), true, 'Mobile page must not overflow');
  if (process.env.UI_SCREENSHOT_PATH) {
    const screenshot = await send('Page.captureScreenshot', { format: 'png', captureBeyondViewport: true });
    await writeFile(process.env.UI_SCREENSHOT_PATH, Buffer.from(screenshot.data, 'base64'));
  }
  assert.deepEqual(exceptions, [], 'Browser must not report uncaught JavaScript exceptions');
  console.log('PASS: credit sale, partial repayments, reversal, debt/refund split, revenue/collections, customer privacy, receipts, removed cash ledger, transfers, reports, adjustments, retries and mobile layout.');
} finally {
  try { await send('Browser.close'); } catch { /* The test browser may already be closed. */ }
  socket.close();
}
