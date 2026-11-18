/* Durable browser storage. Only completed transactions may clear the sale form. */
'use strict';
window.OfflineDB = (() => {
  let opened;
  const request = value => new Promise((resolve,reject) => {value.onsuccess=()=>resolve(value.result);value.onerror=()=>reject(value.error);});
  function open() {
    if(!opened) opened=new Promise((resolve,reject)=>{
      const value=indexedDB.open('festy-offline',1);
      value.onupgradeneeded=()=>{value.result.createObjectStore('meta');value.result.createObjectStore('sales',{keyPath:'key'});};
      value.onsuccess=()=>{value.result.onversionchange=()=>{value.result.close();opened=null;};resolve(value.result);};
      value.onerror=()=>{opened=null;reject(value.error);};
      value.onblocked=()=>reject(new Error('Close other app tabs to enable offline storage.'));
    });
    return opened;
  }
  async function transaction(stores,mode,work) {
    const db=await open();const tx=db.transaction(stores,mode,{durability:'strict'});
    const finished=new Promise((resolve,reject)=>{tx.oncomplete=resolve;tx.onabort=()=>reject(tx.error||new Error('Device storage write was not completed.'));tx.onerror=()=>{};});
    try {const result=await work(tx);await finished;return result;}
    catch(error){try{tx.abort();}catch{}await finished.catch(()=>{});throw error;}
  }
  const meta=key=>transaction(['meta'],'readonly',tx=>request(tx.objectStore('meta').get(key)));
  const put=(key,value)=>transaction(['meta'],'readwrite',tx=>request(tx.objectStore('meta').put(value,key)));
  const remove=key=>transaction(['meta'],'readwrite',tx=>request(tx.objectStore('meta').delete(key)));
  const sales=owner=>transaction(['sales'],'readonly',async tx=>(await request(tx.objectStore('sales').getAll())).filter(row=>row.owner===owner).sort((a,b)=>a.recordedAt.localeCompare(b.recordedAt)||a.key.localeCompare(b.key)));
  async function change(key,patch) {
    return transaction(['sales'],'readwrite',async tx=>{const store=tx.objectStore('sales');const row=await request(store.get(key));if(!row)throw new Error('Saved sale was not found.');if(row.status==='synced')return row;Object.assign(row,patch);await request(store.put(row));return row;});
  }
  async function enqueue(row,validate) {
    return transaction(['meta','sales'],'readwrite',async tx=>{
      const meta=tx.objectStore('meta'),store=tx.objectStore('sales');
      const identity=await request(meta.get('identity')),snapshot=await request(meta.get('snapshot:'+row.owner));
      const existing=await request(store.get(row.key));if(existing){if(existing.owner!==row.owner)throw new Error('Saved sale belongs to another account.');return existing;}
      if(!identity || identity.user.id!==row.owner || identity.expiresAt<=Date.now())throw new Error('Connect and sign in again before recording offline sales.');
      if(!snapshot || snapshot.branchId!==row.body.branch_id)throw new Error('Prepare this device for this branch while online first.');
      const all=await request(store.getAll());
      if(all.some(sale=>sale.owner!==row.owner&&sale.status!=='synced'))throw new Error('Another account has unsynced sales on this device. Sync that account first.');
      const reserved=all.filter(sale=>sale.reserved);
      validate(snapshot,reserved);
      await request(store.add(row));return row;
    });
  }
  async function snapshot(owner,value,included) {
    return transaction(['meta','sales'],'readwrite',async tx=>{
      const store=tx.objectStore('sales');
      await request(tx.objectStore('meta').put(value,'snapshot:'+owner));
      const all=(await request(store.getAll())).filter(row=>row.owner===owner);
      for(const row of all)if(included.includes(row.key)&&row.status==='synced'){row.reserved=false;await request(store.put(row));}
      // Confirmed receipts also live on the server. Never evict unsynced sales.
      const archived=all.filter(row=>row.status==='synced'&&!row.reserved).sort((a,b)=>b.recordedAt.localeCompare(a.recordedAt));
      for(const row of archived.slice(200))await request(store.delete(row.key));
    });
  }
  const otherPending=owner=>transaction(['sales'],'readonly',async tx=>(await request(tx.objectStore('sales').getAll())).some(row=>row.owner!==owner&&row.status!=='synced'));
  return {meta,put,remove,sales,change,enqueue,snapshot,otherPending};
})();
