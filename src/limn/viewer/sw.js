'use strict';
self.addEventListener('install',()=>self.skipWaiting());
self.addEventListener('activate',e=>e.waitUntil(self.clients.claim()));
self.addEventListener('notificationclick',e=>{e.notification.close();const d=e.notification.data||{};
  const url=new URL(d.url||'/',self.location.origin).href;
  e.waitUntil((async()=>{const cs=await self.clients.matchAll({type:'window',includeUncontrolled:true});
    for(const c of cs){if(new URL(c.url).origin!==self.location.origin)continue;
      try{await c.focus();}catch(_){}
      c.postMessage({type:e.action==='restore'?'restore-pin':'open-pin',pin:d.pin,doc:d.doc});return;}
    if(self.clients.openWindow)await self.clients.openWindow(url+(e.action==='restore'?'&act=restore':''));})());});
