/* Cache public app files only: authenticated APIs and receipts never enter Cache Storage. */
'use strict';
// Bump this version whenever a cached app file changes in a later release.
const VERSION='festy-shell-1';
const ASSETS=['./','./index.html','./style.css','./offline-store.js','./offline.js','./app.js','./manifest.webmanifest','./icon-192.png','./icon-512.png'];
const URLS=ASSETS.map(path=>new URL(path,self.registration.scope).href);
self.addEventListener('install',event=>event.waitUntil(caches.open(VERSION).then(cache=>cache.addAll(URLS.map(url=>new Request(url,{cache:'reload'}))))));
self.addEventListener('activate',event=>event.waitUntil((async()=>{for(const name of await caches.keys())if(name.startsWith('festy-shell-')&&name!==VERSION)await caches.delete(name);await self.clients.claim();})()));
self.addEventListener('message',event=>{if(event.data==='ACTIVATE_UPDATE')self.skipWaiting();});
self.addEventListener('fetch',event=>{
  if(event.request.method!=='GET'||!URLS.includes(event.request.url))return;
  event.respondWith(caches.open(VERSION).then(async cache=>(await cache.match(event.request))||fetch(event.request)));
});
