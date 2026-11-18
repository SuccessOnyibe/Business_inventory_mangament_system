/* Offline sales remain provisional until the existing transactional checkout confirms them. */
'use strict';
window.Offline = (() => {
  let snapshot=null,identity=null,rows=[],registration=null,busy=false,lastSale=null,installPrompt=null,reloadRequested=false,running=null;
  const supported=()=>isSecureContext && !!window.indexedDB && !!navigator.locks && 'serviceWorker' in navigator;
  const owner=()=>state.user?.id;
  const leaseValid=value=>value && value.expiresAt>Date.now();
  const activeSnapshot=()=>snapshot && snapshot.owner===owner() && (state.user.role!=='salesperson'||state.user.branch_id===snapshot.branchId);
  const pending=()=>rows.filter(row=>row.status!=='synced');
  const locked=work=>navigator.locks.request('festy-offline-sync',{ifAvailable:true},lock=>lock?work():null);
  const fail=message=>{throw new Error(message);};
  const cents=value=>{if(!/^\d+(?:\.\d{1,2})?$/.test(String(value)))fail('Enter a valid price with at most two decimal places.');return kobo(value);};
  function available(cache,records) {
    return cache.inventory.map(row=>({...row,quantity:Math.max(0,row.quantity-records.filter(sale=>sale.reserved && sale.body.branch_id===row.branch_id).reduce((sum,sale)=>sum+sale.body.items.filter(item=>item.product_id===row.product_id).reduce((count,item)=>count+item.quantity,0),0))}));
  }
  function projectStock() {
    const projected=available(snapshot,rows);
    // Managers may be viewing all branches online; replace only this branch's rows.
    if(state.offline||!state.filter||Number(state.filter)===snapshot.branchId)
      state.inventory=state.offline?projected:[...state.inventory.filter(row=>row.branch_id!==snapshot.branchId),...projected];
    if(Number(state.posBranch)===snapshot.branchId)state.posInventory=projected;
  }
  async function reload() {
    if(!owner())return;
    snapshot=await OfflineDB.meta('snapshot:'+owner());rows=await OfflineDB.sales(owner());render();
  }
  async function remember(user,token,expiresAt) {
    if(!supported())return;
    const old=await OfflineDB.meta('identity');
    if(!expiresAt && old?.token===token)expiresAt=old.expiresAt;
    identity={user:{...user},token,expiresAt:Number(expiresAt)||0};
    // Persist a sign-in only after this account opts into a prepared device.
    if(await OfflineDB.meta('snapshot:'+user.id))await OfflineDB.put('identity',identity);
    await reload();
  }
  async function restore(token) {
    if(!supported())return null;
    const saved=await OfflineDB.meta('identity');
    if(!leaseValid(saved)||(token&&saved.token!==token))return null;
    const cache=await OfflineDB.meta('snapshot:'+saved.user.id);
    if(!cache || (saved.user.role==='salesperson'&&saved.user.branch_id!==cache.branchId))return null;
    identity=saved;snapshot=cache;return saved;
  }
  async function signOut() {
    identity=null;snapshot=null;rows=[];lastSale=null;
    if(supported())await OfflineDB.remove('identity');
  }
  async function enter() {
    const saved=await restore(state.token);if(!saved)fail('Connect and sign in to prepare this device before using it offline.');
    state.user=saved.user;state.token=saved.token;state.offline=true;await applyCache();
  }
  async function applyCache() {
    await reload();if(!activeSnapshot())fail('This device has no offline data for your current branch.');
    state.filter=String(snapshot.branchId);state.branches=[snapshot.branch];state.products=snapshot.products;
    state.inventory=available(snapshot,rows);state.customers=snapshot.customers;state.users=[];
    for(const key of ['sales','transfers','reconciliations','corrections','events','adjustments','receipts','creditSales','repayments'])state[key]=[];
    fillChoices();window.render();
    $('#sale-form').elements.branch_id.value=String(snapshot.branchId);
    state.posBranch=String(snapshot.branchId);state.posInventory=state.inventory;
    renderPosProducts();await updateCreditCustomer();render();
  }
  async function cachedRead(path,method='GET') {
    if(!state.offline)return undefined;
    if(method!=='GET')fail('This action needs an internet connection.');
    if(!leaseValid(identity))fail('Offline sign-in expired. Connect and sign in again; queued sales are retained.');
    const url=new URL(path,location.origin),branch=url.searchParams.get('branch_id');
    if(branch&&Number(branch)!==snapshot.branchId)fail('Only the prepared branch is available offline.');
    if(url.pathname==='/customers'){const offset=Number(url.searchParams.get('offset')||0),limit=Number(url.searchParams.get('limit')||500);return snapshot.customers.slice(offset,offset+limit);}
    if(url.pathname==='/inventory')return available(snapshot,rows);
    fail('This action needs an internet connection. Offline sales are in Device & sync.');
  }
  async function cacheBranch(branchId) {
    const actor=owner(),confirmed=(await OfflineDB.sales(actor)).filter(row=>row.status==='synced').map(row=>row.key);
    // Capture confirmed IDs BEFORE reading stock, then release those reservations atomically.
    const [inventory,products,branches]=await Promise.all([api('/inventory?branch_id='+branchId,{forceOnline:true}),api('/products',{forceOnline:true}),api('/branches',{forceOnline:true})]);
    const customers=[];
    for(let offset=0;;offset+=500){const page=await api(`/customers?branch_id=${branchId}&limit=500&offset=${offset}`,{forceOnline:true});customers.push(...page);if(page.length<500)break;}
    if(owner()!==actor)fail('Account changed while preparing the device.');
    const branch=branches.find(row=>row.id===branchId);if(!branch)fail('Branch is no longer accessible.');
    const value={owner:actor,branchId,branch,products,inventory,customers,preparedAt:new Date().toISOString()};
    await OfflineDB.snapshot(actor,value,confirmed);await reload();projectStock();window.render();
  }
  async function prepare() {
    if(!supported())fail('Use a current Chrome, Edge or Safari browser over HTTPS for offline storage.');
    if(state.offline||!navigator.onLine)fail('Reconnect and use Sync now before preparing fresh branch data.');
    if(!leaseValid(identity))fail('Sign out and sign in again to enable an eight-hour offline session.');
    const branchId=Number($('#offline-branch').value);if(!branchId)fail('Choose the branch this device will serve offline.');
    if(state.user.role==='salesperson'&&branchId!==state.user.branch_id)fail('Choose your assigned branch.');
    if(pending().some(row=>row.body.branch_id!==branchId))fail('Resolve existing unsynced sales before changing the prepared branch.');
    if(await OfflineDB.otherPending(owner()))fail('Another staff account has unsynced sales on this device. Sign in as that account and sync first.');
    await new Promise((resolve,reject)=>{
      const timer=setTimeout(()=>reject(new Error('App files could not finish downloading. Reconnect, reload and prepare again.')),30000);
      navigator.serviceWorker.ready.then(value=>{clearTimeout(timer);resolve(value);},error=>{clearTimeout(timer);reject(error);});
    });
    const saved=await locked(async()=>{await cacheBranch(branchId);await OfflineDB.put('identity',identity);return true;});
    if(!saved)fail('Another app tab is syncing. Try again after it finishes.');
    if(navigator.storage?.persist)await navigator.storage.persist();
    notice('Device prepared. Use only this device for offline sales at this branch.');
  }
  function validate(cache,reserved,body) {
    const stock=available(cache,reserved);
    if(!['cash','pos','credit'].includes(body.payment_method))fail('Choose the payment method.');
    if(!body.items.length||body.items.length>100||new Set(body.items.map(row=>row.product_id)).size!==body.items.length)fail('Check the basket quantities.');
    if(body.notes?.length>2000||body.customer_name?.length>150)fail('Shorten the customer name or notes before saving.');
    if(body.payment_method==='credit'&&!cache.customers.some(row=>row.id===body.customer_id&&row.is_active&&row.branch_id===body.branch_id))fail('Choose an active customer downloaded for this branch.');
    for(const item of body.items){
      const product=cache.products.find(row=>row.id===item.product_id);
      if(!Number.isInteger(item.quantity)||item.quantity<1||item.quantity>2147483647)fail('Enter a positive whole quantity.');
      if(!product?.is_active||product.selling_price==null)fail('The product needs an active cached price.');
      const price=cents(item.unit_price),list=cents(product.selling_price),minimum=(list*(10000n-kobo(product.max_discount_percent))+9999n)/10000n;
      if(price<minimum||price>list)fail('The price exceeds the downloaded discount limits.');
      if(item.quantity>(stock.find(row=>row.product_id===item.product_id)?.quantity||0))fail('Not enough downloaded stock remains after queued sales.');
    }
  }
  async function checkout(form,buildBody) {
    if(!supported())return false;
    await reload();
    if(!activeSnapshot()){
      if(state.offline||!navigator.onLine)fail('Prepare this device online before recording offline sales.');
      return false;
    }
    const legacy=readPending(form);
    // An earlier online request may already be committed. Resolve it with its original retry path.
    if(legacy){if(state.offline)fail('Reconnect to finish the earlier saved request before recording offline sales.');return false;}
    const body=buildBody();
    if(body.branch_id!==snapshot.branchId){if(state.offline)fail('This device is prepared for a different branch.');return false;}
    if(!leaseValid(identity))fail('Sign in again before recording device sales. The basket has not been cleared.');
    const recordedAt=new Date().toISOString(),key=crypto.randomUUID();
    body.notes=`[Device sale ${key}; recorded ${recordedAt}; server posting occurs on sync]${body.notes?' '+body.notes:''}`;
    const total=body.items.reduce((sum,item)=>sum+cents(item.unit_price)*BigInt(item.quantity),0n);
    const customer=body.customer_id?snapshot.customers.find(row=>row.id===body.customer_id)?.name:body.customer_name;
    const record={key,owner:owner(),recordedAt,body,status:'pending',reserved:true,error:'',
      receipt:{receipt_number:'OFF-'+key,receipt_type:'offline',status:'awaiting_sync',branch_name:snapshot.branch.name,
        salesperson_name:state.user.username,created_at:recordedAt,customer_name:customer,payment_method:body.payment_method,total_amount:decimal(total),
        outstanding:body.payment_method==='credit'?decimal(total):'0.00',items:body.items.map(item=>{const product=snapshot.products.find(row=>row.id===item.product_id);return {...item,product_name:product?.name||'Product',base_unit:product?.base_unit||'',total_amount:decimal(cents(item.unit_price)*BigInt(item.quantity))};}),
        notes:'PROVISIONAL - saved on this device, not yet confirmed by the server. '+(body.notes||'')}};
    await OfflineDB.enqueue(record,(cache,reserved)=>validate(cache,reserved,body));
    // Never clear a paid sale until its complete request and receipt are durable.
    try {
      lastSale=key;state.cart=[];form.reset();form.elements.branch_id.value=String(body.branch_id);renderCart();receiptDetails(record.receipt);
      await reload();projectStock();window.render();
      notice("Sale saved on this device - Awaiting sync. Keep this browser's saved data.");
      await sync();
    } catch {notice('Sale is safely saved. Open Device & sync to check its upload; do not enter it again.',true);}
    return true;
  }
  function sync() {
    // All callers await the same upload pass, instead of racing another tab/event.
    if(running)return running;
    if(!state.user||!navigator.onLine||!supported()||(!activeSnapshot()&&!pending().length&&!state.offline))return Promise.resolve();
    running=performSync().finally(()=>{running=null;});return running;
  }
  async function performSync() {
    busy=true;render();
    const wasOffline=state.offline;let uploaded=false;
    try {
      await locked(async()=>{
        const actor=owner();const current=await api('/auth/me',{forceOnline:true});
        if(owner()!==actor||current.id!==actor||!navigator.onLine)return;
        state.user=current;document.body.dataset.role=current.role;state.offline=false;
        if(identity){identity={...identity,user:current};if(activeSnapshot())await OfflineDB.put('identity',identity);}
        $('#profile').textContent=current.username+' / '+current.role;
        await reload();
        for(const row of rows.filter(row=>row.status!=='synced')){
          if(owner()!==actor||row.status==='blocked')break;
          try {
            const result=await api('/checkouts',{method:'POST',body:row.body,headers:{'Idempotency-Key':row.key},forceOnline:true});
            uploaded=true;await OfflineDB.change(row.key,{status:'synced',response:result,error:'',syncedAt:new Date().toISOString()});
            if(lastSale===row.key&&owner()===actor){receiptDetails(result);notice('Sale confirmed by the server. Receipt '+result.receipt_number+'.');}
          } catch(error) {
            if(error.status===401)break;
            await OfflineDB.change(row.key,{status:error.status>=400&&error.status<500&&error.status!==429?'blocked':'pending',error:error.message});
            if(!error.status||error.status>=500)state.offline=true;
            break;
          }
        }
        if(owner()===actor&&activeSnapshot()){
          if(!state.offline)await cacheBranch(snapshot.branchId);
          await reload();
          if(state.offline)await applyCache();
        }
      });
      // Refill normal screens after reconnecting, outside the cross-tab upload lock.
      if(state.user&&!state.offline&&(wasOffline||uploaded))await refresh();
    } catch(error) {
      if(state.user){
        if(!error.status||error.status>=500){state.offline=true;if(await restore(state.token))await applyCache();}
        $('#offline-status').textContent=error.status===401?'Sign in as the original staff member to sync.':'Waiting for a connection. Saved sales remain on this device.';
      }
    } finally {busy=false;render();}
  }
  async function afterRefresh() {
    if(!supported()||!state.user)return;
    await remember(state.user,state.token,Number(sessionStorage.getItem('festy-session-expires')));
    if(activeSnapshot()&&!busy)await locked(()=>cacheBranch(snapshot.branchId));
    if(activeSnapshot()){
      projectStock();window.render();
    }
  }
  function render() {
    const online=!state.offline&&navigator.onLine;
    document.body.dataset.offline=String(!online);
    if(!document.querySelector('#offline-status')||!state.user)return;
    const count=pending().length;
    $('#connection-status').textContent=(online?'Online':'Offline')+` | ${count} sale(s) awaiting sync`;
    $('#offline-status').textContent=busy?'Checking connection / uploading saved sales...':activeSnapshot()?`Prepared for ${snapshot.branch.name}. Last stock download: ${date(snapshot.preparedAt)}. ${count} awaiting sync.`:'Prepare this device online before offline selling.';
    const select=$('#offline-branch');const selected=select.value;
    choices(select,state.branches.map(row=>[row.id,row.name]),'Choose offline branch');select.value=selected||String(snapshot?.branchId||state.user.branch_id||'');
    select.disabled=!online||state.user.role==='salesperson';$('#prepare-offline').disabled=!online||busy||!supported();
    $('#sync-offline').disabled=busy||!navigator.onLine;
    const host=$('#offline-sales');host.replaceChildren();
    for(const record of [...rows].reverse()){
      const card=node('article',null,'offline-sale');card.append(node('strong',record.response?.receipt_number||'OFF-'+record.key),node('p',`${record.status==='synced'?'Synced':record.status==='blocked'?'Needs review':'Awaiting sync'} | ${money(record.receipt.total_amount)} | ${date(record.recordedAt)}`));
      if(record.error)card.append(node('p',record.error,'error'));
      const print=node('button','View / print receipt','secondary');print.type='button';print.addEventListener('click',()=>{receiptDetails(record.response||record.receipt);printReceipt(state.receipt);});card.append(print);
      if(record.status==='blocked'){const retry=node('button','Retry after review','secondary');retry.type='button';retry.addEventListener('click',async()=>{try{await OfflineDB.change(record.key,{status:'pending',error:''});await reload();await sync();}catch(error){notice(error.message,true);}});card.append(retry);}
      host.append(card);
    }
    if(!rows.length)host.append(node('p','No device sales saved for this account.','muted'));
  }
  async function boot() {
    bindEvents();
    if(!supported())return null;
    try {
      registration=await navigator.serviceWorker.register('./sw.js');
      const update=()=>{if(registration.waiting&&navigator.serviceWorker.controller)$('#update-pwa').hidden=false;};
      registration.addEventListener('updatefound',()=>registration.installing?.addEventListener('statechange',update));update();
      const saved=await restore();return saved?.token||null;
    } catch {return null;}
  }
  function bindEvents() {
  window.addEventListener('online',()=>sync());
  window.addEventListener('offline',()=>{if(!state.user)return;if(!activeSnapshot()){render();notice('Connection lost. This account has not prepared a branch for offline use.',true);return;}state.offline=true;enter().catch(error=>notice(error.message,true));});
  window.addEventListener('beforeinstallprompt',event=>{event.preventDefault();installPrompt=event;$('#install-pwa').hidden=false;});
  $('#install-pwa').addEventListener('click',async()=>{if(installPrompt){await installPrompt.prompt();installPrompt=null;$('#install-pwa').hidden=true;}});
  $('#update-pwa').addEventListener('click',()=>{if(state.cart.length){notice('Finish the current basket before reloading the app.',true);return;}reloadRequested=true;registration?.waiting?.postMessage('ACTIVATE_UPDATE');});
  navigator.serviceWorker?.addEventListener('controllerchange',()=>{if(reloadRequested)location.reload();});
  $('#prepare-offline').addEventListener('click',()=>prepare().catch(error=>notice(error.message,true)));
  $('#sync-offline').addEventListener('click',()=>sync());
  $('#export-offline').addEventListener('click',async()=>{
    try{const saved=await OfflineDB.sales(owner());const blob=new Blob([JSON.stringify(saved,null,2)],{type:'application/json'}),url=URL.createObjectURL(blob),link=document.createElement('a');link.href=url;link.download='festy-device-sales.json';link.click();setTimeout(()=>URL.revokeObjectURL(url),1000);}catch(error){notice(error.message,true);}
  });
  setInterval(()=>{
    if(state.offline&&state.user&&!leaseValid(identity)){showLogin();$('#login-error').textContent='Offline sign-in expired. Connect and sign in again; saved sales are retained.';return;}
    if(state.user&&navigator.onLine&&(pending().length||state.offline))sync();
  },30000);
  document.addEventListener('visibilitychange',()=>{if(!document.hidden&&state.user)sync();});
  document.addEventListener('submit',event=>{
    if(state.offline&&!['sale-form','login-form'].includes(event.target.id)){event.preventDefault();event.stopImmediatePropagation();notice('This action is online-only. Saved sales are in Device & sync.',true);}
    if(event.target.id==='reconciliation-form'&&pending().length){event.preventDefault();event.stopImmediatePropagation();notice('Sync or resolve all device sales before submitting the daily count.',true);}
  },true);
  }
  return {boot,remember,restore,signOut,enter,applyCache,cachedRead,prepare,checkout,sync,afterRefresh,render,
    hasPending:()=>pending().length>0,isPrepared:()=>!!activeSnapshot()};
})();

