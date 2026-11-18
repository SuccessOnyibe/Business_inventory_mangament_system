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
  throw new Error('Timed out waiting for: ' + expression + '\nNotice: ' + await evaluate("JSON.stringify({notice:document.querySelector('#notice')?.textContent,login:document.querySelector('#login-error')?.textContent,offline:state.offline,valid:document.querySelector('#login-form')?.checkValidity(),user:state.user?.username,fields:[...document.querySelector('#login-form').elements].map(e=>[e.name,e.type,e.value.length,e.validationMessage]),hidden:document.querySelector('#workspace').hidden})")+' Exceptions: '+JSON.stringify(exceptions));
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
  await wait("!document.querySelector('#workspace').hidden && document.querySelector('#inventory-table').childElementCount>0 && !document.querySelector('#refresh').disabled");
}

// This suite deliberately disconnects Chrome. Node checks the separate disposable API.
await send('Network.enable');
const network=offline=>send('Network.emulateNetworkConditions',{offline,latency:0,downloadThroughput:-1,uploadThroughput:-1});
const records=()=>evaluate('OfflineDB.sales(state.user.id)');
async function apiTest(path,options={}) {
  const token=await evaluate('state.token');
  const response=await fetch(base+path,{...options,headers:{Authorization:'Bearer '+token,'Content-Type':'application/json','Idempotency-Key':crypto.randomUUID()},body:options.body?JSON.stringify(options.body):undefined});
  assert.ok(response.ok,'Test API '+path+' '+response.status);return response.status===204?null:response.json();
}
async function sale(quantity=1,payment='cash',extra={}) {
  await navigate('sales');
  await fill('sale-form',{branch_id:'1',product_id:'1',quantity:String(quantity),unit_price:'25000',payment_method:payment,...extra});
  await submit('sale-form');
}
async function reload() {
  await evaluate('window.testReload=true');await send('Page.reload');
  await wait("typeof Offline!=='undefined' && !window.testReload && state.user && !document.querySelector('#workspace').hidden && !document.querySelector('#refresh').disabled");
}
try {
  await send('Runtime.enable');await send('Page.enable');
  await send('Page.navigate',{url:base+'/app/'});await wait("document.querySelector('#login-form') !== null");await login('ui_admin');
  const customer=await apiTest('/customers',{method:'POST',body:{branch_id:1,name:'Offline customer',phone:'08012345678'}});
  await navigate('offline');await evaluate("document.querySelector('#offline-branch').value='1';document.querySelector('#prepare-offline').click()");
  await wait("document.querySelector('#notice').textContent.includes('Device prepared') && navigator.serviceWorker.controller");
  const keys=await evaluate("(await Promise.all((await caches.keys()).map(async key=>(await (await caches.open(key)).keys()).map(row=>new URL(row.url).pathname)))).flat()");
  assert.equal(keys.length,9);assert.ok(keys.every(path=>path.startsWith('/app/')),'No authenticated API responses in static cache');
  assert.equal((await (await fetch(base+'/app/manifest.webmanifest')).json()).display,'standalone');
  await evaluate("(async()=>{state.filter='2';await refresh()})()");
  assert.ok((await evaluate('state.inventory')).every(row=>row.branch_id===2),'Preparing a branch must preserve an online branch filter');
  await evaluate("(async()=>{state.filter='';await refresh()})()");
  await network(true);await wait('state.offline && state.inventory.length>0');
  await sale(2);await wait("state.cart.length===0 && document.querySelector('#connection-status').textContent.includes('1 sale(s)')");
  let savedRows=await records();assert.equal(savedRows[0].status,'pending');assert.ok(savedRows[0].body.notes.includes(savedRows[0].key));
  assert.ok(await evaluate("document.querySelector('#sale-receipt').textContent.includes('PROVISIONAL')"));
  assert.equal(await evaluate('state.posInventory.find(row=>row.product_id===1).quantity'),998);
  assert.equal((await apiTest('/inventory?branch_id=1'))[0].quantity,1000,'Offline save must not reach PostgreSQL');
  await reload();assert.equal(await evaluate('state.offline'),true);assert.equal((await records()).length,1);
  assert.equal(await evaluate('state.inventory.find(row=>row.product_id===1).quantity'),998);
  await sale(3,'pos');await wait("state.cart.length===0 && document.querySelector('#connection-status').textContent.includes('2 sale(s)')");
  // Credit uses a previously downloaded branch customer, without an online lookup.
  await navigate('sales');await fill('sale-form',{branch_id:'1',product_id:'1',quantity:'1',unit_price:'25000',payment_method:'credit'});
  await wait("!document.querySelector('#credit-customer').disabled");await fill('sale-form',{customer_id:String(customer.id)});await submit('sale-form');
  await wait("state.cart.length===0 && document.querySelector('#connection-status').textContent.includes('3 sale(s)')");
  // A storage failure must leave the basket available, with no extra queued sale.
  await evaluate("window.realEnqueue=OfflineDB.enqueue;OfflineDB.enqueue=async()=>{throw new Error('Simulated storage full')}");
  await sale(1);await wait("document.querySelector('#notice').textContent.includes('Simulated storage full')");
  assert.equal(await evaluate('state.cart.length'),1);assert.equal((await records()).length,3);
  await evaluate('OfflineDB.enqueue=window.realEnqueue;state.cart=[];renderCart()');
  // Offline actions other than sales are deliberately refused.
  assert.ok((await evaluate("api('/customers',{method:'POST',body:{}}).catch(error=>error.message)")).includes('internet'));
  await network(false);await wait("!state.offline && document.querySelector('#connection-status').textContent.includes('0 sale(s)') && !document.querySelector('#refresh').disabled");
  await evaluate('Offline.sync()');savedRows=await records();assert.ok(savedRows.every(row=>row.status==='synced'&&!row.reserved));
  assert.equal((await apiTest('/inventory?branch_id=1'))[0].quantity,994);
  assert.equal(new Set(savedRows.map(row=>row.response.id)).size,3);
  // Lose the successful HTTP response after PostgreSQL commits, then retry the same UUID.
  await evaluate("(()=>{window.realFetch=window.fetch;window.lost=false;window.fetch=async(...args)=>{const response=await window.realFetch(...args);if(args[0]==='/checkouts'&&!window.lost){window.lost=true;throw new TypeError('Lost response')};return response}})()");
  await sale(1);await wait("window.lost && state.cart.length===0 && state.offline");
  savedRows=await records();const uncertain=savedRows.find(row=>row.status==='pending');assert.ok(uncertain);
  assert.equal((await apiTest('/inventory?branch_id=1'))[0].quantity,993);
  await network(true);await reload();assert.equal((await records()).find(row=>row.key===uncertain.key).status,'pending');
  await network(false);await evaluate('Offline.sync()');await wait("!state.offline && document.querySelector('#connection-status').textContent.includes('0 sale(s)')");
  assert.equal((await apiTest('/inventory?branch_id=1'))[0].quantity,993,'Lost response retry cannot deduct stock twice');
  // A changed server price blocks a queued sale and never drops its reservation.
  await network(true);await wait('state.offline');await sale(1);await wait("state.cart.length===0 && document.querySelector('#connection-status').textContent.includes('1 sale(s)')");
  const conflict=(await records()).find(row=>row.status==='pending');
  await apiTest('/products/1',{method:'PATCH',body:{selling_price:'30000.00'}});
  await network(false);await evaluate('Offline.sync()');await wait("document.querySelector('#offline-sales').textContent.includes('Needs review')");
  assert.equal((await records()).find(row=>row.key===conflict.key).reserved,true);
  assert.equal((await apiTest('/inventory?branch_id=1'))[0].quantity,993);
  await apiTest('/products/1',{method:'PATCH',body:{selling_price:'25000.00'}});
  await evaluate("[...document.querySelectorAll('#offline-sales button')].find(button=>button.textContent==='Retry after review').click()");
  await wait("document.querySelector('#connection-status').textContent.includes('0 sale(s)')");await evaluate('Offline.sync()');
  assert.equal((await apiTest('/inventory?branch_id=1'))[0].quantity,992);
  assert.equal((await records()).find(row=>row.key===conflict.key).status,'synced');
  // Expiration stops offline access without erasing a queued sale.
  await network(true);await wait('state.offline');await sale(1);await wait("state.cart.length===0 && document.querySelector('#connection-status').textContent.includes('1 sale(s)')");
  const adminId=await evaluate('state.user.id');
  await evaluate("OfflineDB.meta('identity').then(value=>OfflineDB.put('identity',{...value,expiresAt:Date.now()-1}))");
  await send('Page.reload');await wait("document.querySelector('#login-form') && !document.querySelector('#login-form [type=submit]').disabled && document.querySelector('#workspace').hidden");
  assert.equal((await evaluate(`OfflineDB.sales(${adminId})`)).filter(row=>row.status!=='synced').length,1);
  await network(false);await login('ui_admin');await evaluate('Offline.sync()');await wait("document.querySelector('#connection-status').textContent.includes('0 sale(s)')");
  assert.equal((await apiTest('/inventory?branch_id=1'))[0].quantity,991);
  await evaluate("document.querySelector('#logout').click()");await wait("document.querySelector('#workspace').hidden");await login('ui_seller');
  assert.equal((await records()).length,0,'Another staff member cannot see the original owner queue');
  await navigate('offline');assert.equal(await evaluate("document.querySelector('#offline-branch').value"),'2');
  assert.equal(await evaluate("document.querySelector('#offline-branch').disabled"),true);
  // Concurrent tabs/clicks share a serialized stock reservation transaction.
  await evaluate("document.querySelector('#logout').click()");await wait("document.querySelector('#workspace').hidden");await login('ui_admin');await evaluate('Offline.sync()');
  await network(true);await wait('state.offline');
  const competing=await evaluate("await Promise.allSettled([1,2].map(()=>Offline.checkout(document.querySelector('#sale-form'),()=>({branch_id:1,items:[{product_id:1,quantity:600,unit_price:'25000.00'}],payment_method:'cash',customer_name:null,notes:null})))).then(results=>results.map(row=>row.status))");
  assert.equal(competing.filter(value=>value==='fulfilled').length,1);
  assert.equal(competing.filter(value=>value==='rejected').length,1,'Concurrent saves cannot reserve more stock than downloaded');
  assert.equal((await records()).filter(row=>row.status!=='synced').length,1);
  assert.equal((await apiTest('/inventory?branch_id=1'))[0].quantity,991);
  assert.deepEqual(exceptions,[],'No uncaught browser exceptions');
  console.log('PASS: PWA shell, real network loss, cash/POS/credit queue, offline reload, stock reservations, full storage, idempotent lost-response replay, conflict review, expired-session recovery and account isolation.');
} finally {try{await send('Browser.close')}catch{}socket.close();}
