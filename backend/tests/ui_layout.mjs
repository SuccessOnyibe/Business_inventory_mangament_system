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


// Covers shell geometry after page scrolling, focus and zoom-equivalent resizing.
async function painted() { await evaluate('new Promise(resolve=>requestAnimationFrame(()=>requestAnimationFrame(resolve)))'); }
async function layoutReport() {
  return evaluate(`(() => {
    const rect=selector=>{const element=document.querySelector(selector),r=element.getBoundingClientRect();return {left:r.left,right:r.right,top:r.top,bottom:r.bottom,width:r.width,height:r.height}};
    const main=rect('.main'),sidebar=rect('.sidebar'), viewport=document.documentElement.clientWidth;
    const outside=[...document.querySelectorAll('.view:not([hidden]) .card,.view:not([hidden]) h2,.view:not([hidden]) h3,.view:not([hidden]) label,.view:not([hidden]) .pager')].filter(element=>{
      if(!element.getClientRects().length || element.closest('.table-wrap'))return false;
      const r=element.getBoundingClientRect();return r.width>0 && (r.left<main.left-1 || r.right>main.right+1);
    }).map(element=>({tag:element.tagName,id:element.id,text:element.textContent.trim().slice(0,50),left:element.getBoundingClientRect().left,right:element.getBoundingClientRect().right}));
    const cardOverflow=[...document.querySelectorAll('#pos-products .pos-product')].filter(e=>e.getClientRects().length&&e.scrollWidth>e.clientWidth+1).map(e=>e.dataset.productId);
    return {cardOverflow,insideMain:document.querySelector('.main').contains(document.querySelector('#view-'+state.view)),view:state.view,viewport,documentWidth:document.documentElement.scrollWidth,scrollX:window.scrollX,scrollY:window.scrollY,main,sidebar,outside};
  })()`);
}
function assertContained(report,context) {
  assert.equal(report.insideMain,true,`${context}: active screen escaped the main container`);
  assert.ok(report.documentWidth<=report.viewport+1,`${context}: page-wide horizontal overflow ${JSON.stringify(report)}`);
  assert.ok(report.scrollX<=1,`${context}: page was panned behind navigation ${JSON.stringify(report)}`);
  if(report.viewport>720)assert.ok(report.main.left>=report.sidebar.right-1,`${context}: sidebar covers main ${JSON.stringify(report)}`);
  assert.deepEqual(report.cardOverflow,[],`${context}: product text escaped its card`);
  assert.deepEqual(report.outside,[],`${context}: clipped controls/headings`);
}
try {
  await send('Runtime.enable');await send('Page.enable');
  await send('Emulation.setDeviceMetricsOverride',{width:1440,height:900,deviceScaleFactor:1,mobile:false});
  await send('Page.navigate',{url:base+'/app/'});await wait("document.querySelector('#login-form') !== null");await login('ui_admin');
  // All mutations below are fixture data on the guarded 58541/55439 test stack.
  await evaluate(`await api('/products',{method:'POST',body:{name:'Veterinary medicine with a deliberately long supplier and pack description for layout checks',category:'Medicine',base_unit:'vial',selling_price:'100.00',barcode:'0123456789012345678901234567890123456789012345678901234567890123'}})`);
  await evaluate(`await api('/products',{method:'POST',body:{name:'Poultry equipment layout fixture',category:'Equipment',base_unit:'piece',selling_price:'10.00'}})`);
  await evaluate('await refresh()');

  // Use unsorted browser-only fixture rows to check display order without creating stock transactions.
  await evaluate(`(() => {
    window.orderOriginal={products:state.products,inventory:state.inventory,posInventory:state.posInventory,posBranch:state.posBranch,branch:document.querySelector('#sale-form').elements.branch_id.value};
    const fixture=[];
    for(const [index,category] of SHOP_CATEGORIES.entries()) {
      for(const [offset,prefix] of ['Zebra','aardvark'].entries()) fixture.push({id:70000+index*10+offset,name:prefix+' order '+category.id,category:category.value,base_unit:'piece',is_active:true,selling_price:'10.00',max_discount_percent:'0.00',barcode:null});
    }
    state.products=[...state.products,...fixture];
    state.inventory=[...state.inventory,...fixture.map(product=>({product_id:product.id,product:product.name,branch_id:1,branch:'Main Branch',quantity:1,unit:'piece'}))];
    state.posInventory=state.inventory;state.posBranch='1';fillChoices();document.querySelector('#sale-form').elements.branch_id.value='1';render();
  })()`);
  try {
    for(const category of ['feed','vet','equipment','other']) {
      for(const root of ['inventory-table','products-table']) {
        const names=await evaluate(`[...document.querySelectorAll('#${root}-${category} tbody tr')].map(row=>row.cells[0].textContent.trim())`);
        assert.equal(names[0],'aardvark order '+category,`${root}/${category}: first item should be A`);
        assert.equal(names.at(-1),'Zebra order '+category,`${root}/${category}: last item should be Z`);
      }
      const names=await evaluate(`[...document.querySelectorAll('#pos-products .category-${category} h3')].map(element=>element.textContent)`);
      assert.equal(names[0],'aardvark order '+category,`till/${category}: first item should be A`);
      assert.equal(names.at(-1),'Zebra order '+category,`till/${category}: last item should be Z`);
    }
    console.log('PASS: alphabetical product order in all four categories across inventory, catalogue and till.');
  } finally {
    await evaluate(`(() => {const {branch,...original}=window.orderOriginal;Object.assign(state,original);document.querySelector('#sale-form').elements.branch_id.value=branch;delete window.orderOriginal;fillChoices();render();})()`);
  }
  const views=['offline','receiving','products','accounts','credit','transfers','reports','inventory','adjustments','reconciliations','customers','sales'];
  const cases=[
    {name:'desktop',width:1440,height:900,scale:1},
    {name:'zoom150',width:1280,height:552,scale:1.5},
    {name:'zoom200',width:960,height:414,scale:2},
    {name:'tablet',width:720,height:750,scale:1},
    {name:'mobile',width:390,height:844,scale:1}
  ];
  for(const size of cases) {
    await send('Emulation.setDeviceMetricsOverride',{width:size.width,height:size.height,deviceScaleFactor:size.scale,mobile:false});
    await painted();
    for(const view of views) {
      await evaluate('window.scrollTo(99999,document.documentElement.scrollHeight)');
      await navigate(view);
      if(view==='reports')await wait("!document.querySelector('#report-form [type=submit]').disabled");
      await painted();
      const top=await layoutReport();assertContained(top,`${size.name}/${view}/navigation`);
      assert.ok(top.scrollY<=1,`${size.name}/${view}: navigation retained the previous page's scroll position`);
      // Focus deep controls and attempt to pan the document; only table wrappers may scroll sideways.
      await evaluate(`(() => {const fields=[...document.querySelectorAll('.view:not([hidden]) input,.view:not([hidden]) select')].filter(e=>e.getClientRects().length&&!e.disabled);fields.at(-1)?.focus();window.scrollTo(99999,document.documentElement.scrollHeight);})()`);
      await painted();assertContained(await layoutReport(),`${size.name}/${view}/bottom-focus`);
      if(['zoom150','mobile'].includes(size.name)&&['accounts','credit','products','transfers'].includes(view)&&process.env.UI_SCREENSHOT_PATH) {
        const shot=await send('Page.captureScreenshot',{format:'png',captureBeyondViewport:false});
        await writeFile(join(dirname(process.env.UI_SCREENSHOT_PATH),`${size.name}-${view}.png`),Buffer.from(shot.data,'base64'));
      }
    }
  }
  assert.deepEqual(exceptions,[]);
  console.log(`PASS: ${cases.length*views.length} page/viewport combinations, including zoom-equivalent widths, focused controls, bottom scroll, sidebar separation and navigation scroll reset.`);
} finally {try{await send('Browser.close')}catch{}socket.close();}
