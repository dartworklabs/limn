// ------------------------------------------------ Seeing and pinning while cut off (docs/handbook/viewer.md §끊긴 채 보기와 핀 쌓기)
// Before leaving the network, [오프라인으로 받기] keeps this build's page (the shell), its PDF and its page images in the
// service worker's cache and asks the server to hold that build's reverse-mapping material (POST /api/hold). While cut off,
// a drag keeps its box: pick cannot run, so the selection carries only its page, box, and the words PDF.js reads inside it,
// and [핀 저장] puts the pin in a queue (IndexedDB limnOffline) instead of on the server. The queue survives a reload, the
// tab closing and the browser restarting - only this browser sees it. Back on the network the queue is replayed in the
// order it was written: each record's own coordinates go to POST /api/pick with the build they were drawn on, and its
// answer to POST /api/pin. A record whose place cannot be found again is kept and counted, never dropped.
const OFF_DB='limnOffline',OFF_STORE='pins',OFF_STATE='state',OFF_MAX=200;
const OFF_WROTE='wrote';   // the state key holding the pin numbers this queue wrote while a record still waits
// The document reads a reopened tab needs before it can draw anything, and whose last answer is therefore stored. It is
// every read the boot path makes: the document's meta and the document list, the pin list AND the dropped one (loadPins
// applies neither snapshot unless both answered - without the second the stored list was fetched and then thrown away),
// the people, the outline labels, and the source a Markdown or text document is drawn from. A light poll (light=1) is
// not among them - that one has to fail, so the status line says the connection is gone. Nothing else is ever stored,
// and no answer to a write ever is.
const OFF_READS=['/api/meta','/api/docs','/api/pins','/api/pins/dropped','/api/people','/api/outline-labels','/api/source'];
// idem: the server said it knows a write by its key (meta's pin_idem, offStash). boot: this visit's first reads are still under way (cleared by offlineBoot, which boot() calls last). staleNote: the
// status line's message that the screen was drawn from stored reads, while it stands.
const OFF={n:0,held:0,flushing:false,prep:false,saidStale:false,boot:true,idem:false,staleNote:/** @type {Notice|null|undefined} */(null),
  db:/** @type {IDBDatabase|null} */(null)};
// This browser's queue, opened once per page. A browser that refuses IndexedDB (a private window) answers null, and every
// caller below falls back to saying the pin could not be kept rather than losing it quietly.
/** @returns {Promise<IDBDatabase|null>} */
function offDb(){if(OFF.db)return Promise.resolve(OFF.db);
  return new Promise(res=>{let rq; try{rq=indexedDB.open(OFF_DB,2);}catch(e){res(null);return;}
    rq.onupgradeneeded=()=>{const db=rq.result;
      if(!db.objectStoreNames.contains(OFF_STORE))db.createObjectStore(OFF_STORE,{keyPath:'id',autoIncrement:true});
      if(!db.objectStoreNames.contains(OFF_STATE))db.createObjectStore(OFF_STATE,{keyPath:'key'});};
    // A tab left open on an older Limn holds the previous version and would block this one's upgrade, which stops the
    // queue in both. Each tab lets go when another needs the newer version, and opens again on its next call.
    rq.onsuccess=()=>{const db=rq.result; db.onversionchange=()=>{try{db.close();}catch(e){} if(OFF.db===db)OFF.db=null;};
      OFF.db=db; res(db);}; rq.onerror=()=>res(null); rq.onblocked=()=>res(null);});}
/** One operation on a store as a promise; `fn` gets the store and returns its request. @returns {Promise<any>} */
function offIn(store,mode,fn){return offDb().then(db=>new Promise(res=>{if(!db){res(null);return;}
  let rq; try{rq=fn(db.transaction(store,mode).objectStore(store));}catch(e){res(null);return;}
  rq.onsuccess=()=>res(rq.result); rq.onerror=()=>res(null);}));}
/** One operation on the queue. @returns {Promise<any>} */
function offTx(mode,fn){return offIn(OFF_STORE,mode,fn);}
/** Every queued record, oldest first - the order they were written is the order they are sent. @returns {Promise<any[]>} */
function offAll(){return offTx('readonly',s=>s.getAll()).then(v=>Array.isArray(v)?v:[]);}
function offAdd(rec){return offTx('readwrite',s=>s.add(rec));}
// The pins this browser's queue has written, kept in the state store (OFF_WROTE, newest last, OFF_WROTE_MAX of them).
// A record whose answer never came is looked for in the pin list, and a pin that is in here was written by a different
// record of this queue - it is not this one's, however alike the two are. Without that, a record that lost its answer
// while a twin of it was written (the same place, the same note) matched the twin's pin and was deleted unwritten.
/** @returns {Promise<number[]>} */
function offWrote(){return offIn(OFF_STATE,'readonly',s=>s.get(OFF_WROTE)).then(v=>Array.isArray(v&&v.ids)?v.ids:[]);}
/** @param {number} id */
async function offWroteAdd(id){if(typeof id!=='number')return;
  const ids=await offWrote(); if(ids.includes(id))return;
  ids.push(id); await offIn(OFF_STATE,'readwrite',s=>s.put({key:OFF_WROTE,ids}));}
// Keeps only what some waiting record can still be confused by. A record is matched only against pins newer than the
// one it was attempted after (its `top`), so every number at or below the smallest of those tops is past being
// needed; an empty queue needs none of them. Capping the list by its length instead would drop the very number a
// record that waited through many writes still needs.
/** @param {any[]} rest */
async function offWroteKeep(rest){const ids=await offWrote(); if(!ids.length)return;
  const tops=rest.map(r=>typeof r.top==='number'?r.top:0);
  const floor=tops.length?Math.min(...tops):Infinity;
  const kept=rest.length?ids.filter(id=>id>floor):[];
  if(kept.length!==ids.length)await offIn(OFF_STATE,'readwrite',s=>s.put({key:OFF_WROTE,ids:kept}));}
/** Whether this record is still queued - another tab of this browser may have written and dropped it. @returns {Promise<boolean>} */
function offHas(id){return offTx('readonly',s=>s.getKey(id)).then(v=>v!==null&&v!==undefined);}
function offPut(rec){return offTx('readwrite',s=>s.put(rec));}
function offDel(id){return offTx('readwrite',s=>s.delete(id));}
// Reads the queue and lets the status line say how many wait and how many of those lost their place.
async function offlineSync(){const all=await offAll();
  OFF.n=all.length; OFF.held=all.filter(r=>r&&r.held).length; drawStatus();
  offlineUiSync(all);}   // the queued pins on the page and in the panel (offline-ui.js)
// Whether this tab should keep a pin instead of sending it: the light poll has lost the server (POLL_FAILS, the same
// judgment the status line's '연결 끊김' uses) or the browser says there is no network at all.
function offlineNow(){return POLL_FAILS>=2||navigator.onLine===false;}

// ---------------- The last answer to a document read
// A tab the phone discarded during a flight is opened again with no network. The worker answers with the page, but the
// document reads are API calls, which are never cached: without them there is no page list, no PDF build and no pin
// list, so nothing is drawn and nothing can be dragged. So the last answer to each read of OFF_READS is stored, and a
// read the network refuses is answered from that store instead of failing - said once on the status line, with when it
// was read, so a stored list is never taken for the current one.
/** The store key of a read: its path and query without the cache-busting bits. @returns {string|null} */
function offReadKey(url,o){if(o&&o.method&&o.method!=='GET')return null;
  const u=String(url); if(u.indexOf('light=1')>=0)return null;
  const path=u.split('?')[0]; if(!OFF_READS.includes(path))return null;
  return u;}
// Stores the answer to a document read, so a later visit with no network can be drawn from it. Only an answer the
// server gave as a success, with a body of its own: a read may hand its caller an error it expects to handle (a
// Markdown document past the drawing limit answers 413 with its reason, md-surface.js), and that answer is not the
// document. Stored, it would come back on the next visit as a document that opened and was empty.
/** @param {string} url @param {any} data @param {number} status @param {{method?:string}|null} [o] */
function offStash(url,data,status,o){
  // Every answer the network gives passes here, so this is also where the server says what it can do: a meta answer,
  // the light poll's included, carries pin_idem when a write is known by its key (api.md POST /api/pin).
  if(status===200&&data&&String(url).split('?')[0]==='/api/meta')OFF.idem=data.pin_idem===true;
  const key=offReadKey(url,o||null); if(!key)return;
  if(!(status>=200&&status<300)||data===null||data===undefined)return;
  void offIn(OFF_STATE,'readwrite',s=>s.put({key,data,status,at:Date.now()}));}
/** The stored answer to a read, or null - never one the server refused. @returns {Promise<{data:any,status:number,at:number}|null>} */
function offStashed(url,o){const key=offReadKey(url,o); if(!key)return Promise.resolve(null);
  return offIn(OFF_STATE,'readonly',s=>s.get(key)).then(v=>{
    if(!v||!('data' in v))return null;
    // The record has to say for itself that the server answered it with a success. A record that does not say so is
    // not trusted and is dropped: an earlier build of this viewer stored refusals too, and read as a success they
    // open a document that is simply empty. A read that finds nothing asks the network, which is the right answer.
    if(typeof v.status!=='number'||v.status<200||v.status>=300){
      void offIn(OFF_STATE,'readwrite',s=>s.delete(key)); return null;}
    return {data:v.data,status:v.status,at:v.at};});}
// When a read the network refused may be answered from the store: while this visit is still making its first reads
// (a tab opened again with no network has nothing else to draw from), or while the connection is known to be gone
// (offlineNow - switching documents during a flight). Never for a read that fails while the viewer is connected: that
// failure is said and asked again as it always was (a failed pin read's '핀 읽기 실패 [다시 시도]', a Markdown source's
// note and its re-ask on the next poll). Answered from the store there, it read as a success - the list stayed stale
// and nothing asked again.
function offlineMayServe(){return OFF.boot||offlineNow();}
// Says once per visit that what is on screen was read before the connection went, and when. The pins and the pages are
// that moment's, not this one's: the status line already says the connection is gone, and this says how old the screen is.
function offStaleSaid(at){if(OFF.saidStale)return; OFF.saidStale=true;
  const d=new Date(at),two=(/** @type {number} */n)=>String(n).padStart(2,'0');
  OFF.staleNote=lineNote(tl('연결이 없어 {time}에 읽어 둔 화면입니다 — 핀을 찍으면 쌓였다가 연결되면 반영됩니다',
    {time:two(d.getHours())+':'+two(d.getMinutes())}),NOTICE_KIND.WARN,null,{literal:true});}
// The server answered again after a screen drawn from stored reads: its message goes, and the pin list is read again
// whatever revision it was last read at - the stored list is that old moment's, and the light poll compares revisions,
// so a stored list whose revision happens to equal the server's would otherwise stand unread. Called for every answer
// the network gives (api); nothing happens unless a stored screen was said.
function offlineBack(){if(!OFF.saidStale)return; OFF.saidStale=false;
  if(OFF.staleNote){endNotice(OFF.staleNote,false); OFF.staleNote=null;}
  LAST_PINS_REV=null;}

// ---------------- The service worker
// The worker is registered for every visit, not only where notifications are allowed (notify.js asks it for those): it is
// what answers when the network does not. A browser without one still works online, and says so when asked to prepare.
/** @returns {Promise<ServiceWorkerRegistration|null>} */
async function offlineWorker(){if(!('serviceWorker' in navigator))return null;
  try{return SW_REG||(SW_REG=await navigator.serviceWorker.register('/sw.js',{scope:'/'}));}catch(e){return null;}}
// One question to the worker, answered on its own port so a replaced worker never leaves this waiting. The wait fits the
// question: a count comes back at once (3s), files have to be fetched first - over a tailnet from a phone that is not 3s,
// and a wait that short called a keep that was still going a failure.
/** @param {{type:string,urls?:string[]}} msg @param {number} [ms] @returns {Promise<any>} */
async function offlineAsk(msg,ms){const reg=await offlineWorker(); if(!reg)return null;
  let sw=navigator.serviceWorker.controller; if(!sw){try{await navigator.serviceWorker.ready;}catch(e){} sw=navigator.serviceWorker.controller;}
  if(!sw)return null;
  return new Promise(res=>{const ch=new MessageChannel(),t=setTimeout(()=>res(null),ms||3000);
    ch.port1.onmessage=e=>{clearTimeout(t); res(e.data);}; try{sw.postMessage(msg,[ch.port2]);}catch(e){clearTimeout(t); res(null);}});}
// What the page needs to open with no network: the page itself and everything it has already loaded from this origin
// (the inlined shell leaves only the vendored PDF.js, fonts, KaTeX and the Markdown worker). Nothing is hardcoded, so a
// change to the vendored files follows along.
/** @returns {string[]} */
function offlineUrls(){const out=new Set([location.pathname+location.search]);
  try{performance.getEntriesByType('resource').forEach(e=>{const u=new URL(e.name,location.href);
    if(u.origin===location.origin&&!u.pathname.startsWith('/api/')&&u.pathname!=='/sw.js')out.add(u.href);});}catch(e){}
  return Array.from(out);}
// The PDF and the page images of document k as its meta m names them - the very addresses the viewer asks for when that
// document is on screen (pdf-open.js vecOpen, pages.js pageSrc), since a copy is found again by its address. Pure.
/** @param {string|null} k @param {any} m @returns {string[]} */
function offlineDocFiles(k,m){const b=(m&&m.pages_build)||'',out=/** @type {string[]} */([]); if(!b)return out;
  out.push(dq('/pdf?build='+encodeURIComponent(b)+'&v='+encodeURIComponent(m.built_at||''),k));
  (m.pages||[]).forEach((/** @type {any} */pg)=>out.push(dq('/pages/'+encodeURIComponent(b)+'/'+encodeURIComponent(pg.name),k)));
  return out;}
const OFF_KEEP_CHUNK=12,OFF_KEEP_MS=180000;   // files asked of the worker at a time, and how long one such ask may take
// [오프라인으로 받기]: keeps every document of this instance for reading with no network - a person on a flight moves
// between them - and asks the server to hold each build its pins will point at. Each document's reads go through api(),
// which stores their answers (offStash): its meta, its outline labels, and for a Markdown or text document the source it
// is drawn from. The files go to the worker a few at a time, so the line can say how far it is. The hold is what lets the
// queue land on exact lines later; a server without that route (an older Limn) is not a failure - the pins are kept all
// the same, and said to need their place chosen again if the build is gone by then.
async function offlinePrepare(){
  if(OFF.prep)return; OFF.prep=true;
  const note=lineNote('오프라인용으로 받는 중…',NOTICE_KIND.INFO,null,{life:NOTICE_LIFE.CLICK});
  const say=(/** @type {string} */t)=>{if(note&&NOTICES.has(note.n)){note.title=t; note.desc=''; drawStatus();}};
  try{
    const reg=await offlineWorker();
    if(!reg){if(note)endNotice(note,false); lineNote('이 브라우저는 오프라인 보기를 지원하지 않습니다',NOTICE_KIND.WARN,null,{}); return;}
    const urls=new Set(offlineUrls()),keys=DOCS.length?DOCS.map(d=>d.key):[DOC];
    let docs=0,held=0,lost=0;
    for(const k of keys){let m=/** @type {any} */(null);
      try{m=(await api(dq('/api/meta',k),{what:'화면 정보 읽기',silent:true})).data;}catch(e){lost++; continue;}
      docs++;
      const info=k?docInfo(k):null,kind=(m&&m.kind)||(info&&info.kind);
      if(rendersInBrowser(kind)){
        try{await api(dq('/api/source',k),{what:'원문 읽기',silent:true,expect:[413]});}catch(e){lost++;}
        continue;}
      offlineDocFiles(k,m).forEach(u=>urls.add(u));
      try{await api(dq('/api/outline-labels',k),{what:'목차 번호 읽기',silent:true});}catch(e){}
      if(m&&m.pages_build){
        // Held only when the server says until when. A 404 is handed back, not thrown (expect), and it is not a hold:
        // an older Limn has no such route, and a build that left while this ran answers pdf_build_gone.
        try{const r=await api(dq('/api/hold',k),{method:'POST',body:{build:m.pages_build,days:7},what:'빌드 보류',silent:true,expect:[404]});
          if(r.status===200&&r.data&&r.data.until)held++;}catch(e){}}}
    // The lists every document shares, as they stand now.
    for(const u of ['/api/docs','/api/pins?all=1','/api/pins/dropped','/api/people']){
      try{await api(u,{what:'핀 읽기',silent:true});}catch(e){lost++;}}
    const all=Array.from(urls); let kept=0,failed=0;
    for(let i=0;i<all.length;i+=OFF_KEEP_CHUNK){
      say(tl('오프라인용으로 받는 중… {n}/{m}',{n:i,m:all.length}));
      const r=await offlineAsk({type:'keep',urls:all.slice(i,i+OFF_KEEP_CHUNK)},OFF_KEEP_MS);
      if(!r){if(note)endNotice(note,false);
        lineNote('오프라인용 받기를 마치지 못했습니다 — 다시 시도하세요',NOTICE_KIND.ERR,{label:'다시 시도',fn:()=>{OFF.prep=false; offlinePrepare();}},{}); return;}
      kept+=r.kept||0; failed+=(r.failed||[]).length;}
    if(note)endNotice(note,false);
    const bad=failed+lost;
    lineNote(bad?tl('오프라인용 {n}개 중 {m}개를 받지 못했습니다 — 연결을 확인하고 다시 받으세요',{n:all.length+lost,m:bad})
      :held?tl('오프라인 준비됨 · 문서 {d}개 · 파일 {n}개 · PDF의 자리를 7일간 지킵니다',{d:docs,n:kept})
      :tl('오프라인 준비됨 · 문서 {d}개 · 파일 {n}개',{d:docs,n:kept}),
      bad?NOTICE_KIND.WARN:NOTICE_KIND.OK,null,{life:bad?NOTICE_LIFE.CLICK:NOTICE_LIFE.TIMER});
  }finally{OFF.prep=false;}}

// ---------------- Pinning while cut off
// The words inside the dragged box, read from the PDF this tab already has open (PDF.js, the same text the search reads).
// The server's own quote comes from pdftotext at pick time; this one only has to say what was pinned while the answer is
// still hours away, and the pick's quote replaces it when the pin is written.
/** @param {number} page @param {{x0:number,y0:number,x1:number,y1:number}} rect @returns {Promise<string>} */
async function offlineQuote(page,rect){if(!VEC.doc)return '';
  try{const {items,vp}=await pageText(VEC.doc,page);   // the one reader of a page's text (search.js)
    return quoteIn(items,vp.height,rect);}catch(e){return '';}}
// The words of a page's text items that a box lies on. The box is in PDF points measured from the page's top, as a
// drag's is; PDF.js gives each item where its baseline starts, measured from the bottom, and how wide and tall it is.
// An item counts when its run crosses the box and the middle of its line is inside it. Judged by where the item
// starts alone, a line that begins at the margin and runs through the box was left out - which is most lines, so
// the quote came back empty. Cut at 160 characters the way the server cuts its own (159 and an ellipsis). Pure.
/** @param {any[]} items @param {number} pageH @param {{x0:number,y0:number,x1:number,y1:number}} rect @returns {string} */
function quoteIn(items,pageH,rect){const out=/** @type {string[]} */([]);
  (items||[]).forEach(it=>{const t=it&&it.transform; if(!t||typeof it.str!=='string'||!it.str.trim())return;
    const x=t[4],w=Number(it.width)||0,h=Number(it.height)||Math.hypot(t[2],t[3])||0,mid=pageH-t[5]-h/2;
    if(x+w>=rect.x0&&x<=rect.x1&&mid>=rect.y0&&mid<=rect.y1)out.push(it.str);});
  const q=out.join(' ').replace(/\s+/g,' ').trim();
  return q.length>160?q.slice(0,159)+'…':q;}
// A drag whose pick could not be sent: the box stays and the composer opens on a selection with no lines - the same shape a
// view-only PDF's region selection has (isRegion), so the range ladder, the source snippet, a suggested edit and a verdict
// are all off, and [핀 저장] has only the page, the box and the words to keep. Its lines are found when the queue is sent.
/** @param {{page:number,x0:number,y0:number,x1:number,y1:number,frac:number[],pdf_build?:string,doc?:string}} r */
async function offlinePick(r){
  const seq=PICKSEQ,rect={x0:r.x0,y0:r.y0,x1:r.x1,y1:r.y1},quote=await offlineQuote(r.page,rect);
  if(seq!==PICKSEQ)return;   // a newer drag or a cancel owns the composer now
  const sel=/** @type {any} */({kind:'region',page:r.page,frac:r.frac,quote,file:null,name:null,lo:null,hi:null,
    pdf:META?META.pages_build:null,pdf_build:r.pdf_build,doc:r.doc||DOC,offline:true,rect,levels:[],overlaps:[],
    scope:null,env:null,elSel:null,el:null,via:null,score:null,warn:'',snippet:'',n_lines:0,default_level:null});
  COMPOSE.current=/** @type {Selection} */(sel); COMPOSE.intent++; COMPOSE.picking=false; COMPOSE.dismissedOverlap=null;
  SNIP_OPEN=false; $('#c-err').hidden=true; $('#c-body').hidden=false; $('#composer').hidden=false;
  renderComposer(); $('#composer').scrollTop=0;
  lineNote('연결이 끊겨 줄은 뒤에 찾습니다 — 메모를 쓰고 저장하면 쌓아 둡니다',NOTICE_KIND.INFO,null,{life:NOTICE_LIFE.CLICK,topic:NOTICE_TOPIC.OFFLINE});
  if(LAST_PTR==='mouse')(selPopOpen()?SEL_POP_FIELD:$('#note')).focus({preventScroll:true});}
// [핀 저장] with no server: the pin goes to the queue with everything needed to write it later - where it was drawn, on which
// build, its words, and what the composer asked (the note, its kind, its assignee and the @-tags). Answers whether it was
// kept; a browser that refuses the queue answers false and the caller says the save failed, so no pin is lost silently.
/** @param {Selection} d @param {string} note @param {{kind:string|null,assignee:string|null}} out @param {string[]} mentions @returns {Promise<boolean>} */
async function offlineQueueSave(d,note,out,mentions){
  if(OFF.n>=OFF_MAX){bannerNote(NOTICE_HOST.COMPOSER,tl('쌓아 둘 수 있는 핀은 {n}개까지입니다 — 연결되면 먼저 반영하세요',{n:OFF_MAX}),NOTICE_KIND.ERR,null,{save:true,source:'offline-queue'}); return false;}
  // What the send needs is the drag itself, never the lines a pick once answered: hours pass, the manuscript is edited
  // while the person is away, and those line numbers would be written against text that has moved - a pin that reads
  // as placed and points elsewhere. So the record carries the box as page fractions (frac, which every drag has) and
  // the page's size in points on the build it was drawn on, which together rebuild that pick request exactly. The
  // lines a pick already found are kept only to tell the person what the pin used to point at if its place is lost.
  const pg=META&&META.pages&&META.pages[d.page-1];
  const found=!d.offline&&!isRegion(d)&&!!d.file&&typeof d.lo==='number'&&typeof d.hi==='number';
  // A Markdown or text document has no page: its lines are the place, and the browser drew them from the source it
  // holds. The record keeps those lines' own text, so the send can tell whether they still read the same - and find
  // them again when lines were only added or removed above them.
  const lined=found&&typeof d.page!=='number'&&MD.doc===(d.doc||DOC);
  const lo=/** @type {number} */(d.lo),hi=/** @type {number} */(d.hi);
  const rec={v:1,label:META?META.label:'',doc:d.doc||DOC,build:d.pdf_build||(META?META.pages_build:'')||'',
    page:d.page,rect:d.rect||null,frac:d.frac,pt:pg?{w:pg.pt_w,h:pg.pt_h}:null,
    quote:d.quote||'',note,kind_req:out.kind,assignee:out.assignee,
    mentions:mentions.slice(),at:new Date().toISOString(),held:false,why:'',sent:false,
    place:found?{file:d.file,name:d.name,lo:d.lo,hi:d.hi}:null,
    lines:lined?{file:d.file,name:d.name,lo,hi,text:MD.lines.slice(lo-1,hi).join('\n'),
      kind:d.scope?kindFor(d.scope,d.env):d.kind,scope:d.scope?wireScope(d.scope):null}:null,
    idem:offlineKey()};
  if(found&&typeof d.page!=='number'&&!lined){   // a line selection whose source this tab no longer holds: nothing to check it against later
    bannerNote(NOTICE_HOST.COMPOSER,tr('핀 저장 실패 — 이 문서의 원문을 다시 읽은 뒤 저장하세요'),NOTICE_KIND.ERR,null,{save:true,source:'offline-queue'}); return false;}
  const id=await offAdd(rec);
  if(id===null){bannerNote(NOTICE_HOST.COMPOSER,tr('핀 저장 실패 — 이 브라우저가 오프라인 보관을 막고 있습니다'),NOTICE_KIND.ERR,null,{save:true,source:'offline-queue'}); return false;}
  await offlineSync();
  undoNote(NOTICE_PLACE.LINE,tl('쌓아 둠 · 오프라인 핀 {n}개 — 연결되면 반영합니다',{n:OFF.n}),
    {label:'되돌리기',wait:true,fn:async()=>{await offDel(id); await offlineSync(); return true;}},{literal:true});
  // A selection picked while cut off is kept even once the connection is back (it still has no lines). Then there is
  // nothing to wait for: it goes out now, rather than sitting in the queue until the next reconnect or reload.
  if(!offlineNow())void offlineFlush();
  return true;}

// ---------------- Sending the queue
// A key for one write, made when the pin is kept and sent with every attempt at it: the server answers a second attempt
// with the pin the first one made (api.md POST /api/pin, idem). 16 to 64 characters of [A-Za-z0-9_-]; a UUID where the
// browser gives one, else time and random digits (a page that is not a secure context has no randomUUID).
function offlineKey(){try{if(crypto&&typeof crypto.randomUUID==='function')return crypto.randomUUID();}catch(e){}
  const r=()=>Math.floor(Math.random()*0x100000000).toString(16).padStart(8,'0');
  return 'k'+Date.now().toString(16)+'-'+r()+r()+r();}
// Where the kept lines of a Markdown or text document stand in its source now, or null when they no longer do. The
// same lines at the same numbers are that place. Else the one place in the source where those very lines stand
// together - text was added or removed above them, the common change - is. Lines that changed, or that stand in two
// places, have no place this can vouch for. Pure.
/** @param {string[]} lines the source now @param {{lo:number,text:string}} want the kept lines @returns {{lo:number,hi:number}|null} */
function linesWhere(lines,want){const text=String(want.text).split('\n'),n=text.length;
  const same=(/** @type {number} */lo)=>{for(let i=0;i<n;i++)if(lines[lo-1+i]!==text[i])return false; return true;};
  if(want.lo>=1&&want.lo-1+n<=lines.length&&same(want.lo))return {lo:want.lo,hi:want.lo+n-1};
  let hit=0,count=0;
  for(let lo=1;lo+n-1<=lines.length;lo++)if(same(lo)){count++; hit=lo; if(count>1)return null;}
  return count===1?{lo:hit,hi:hit+n-1}:null;}
// The place a kept Markdown or text record is written at: its lines as the source reads now (linesWhere), in the shape
// offlineBody takes. 'net' when the source could not be asked for (the record waits), null when the lines are gone.
/** @param {any} rec @returns {Promise<any>} */
async function offlinePlaceLines(rec){let r;
  try{r=await api(dq('/api/source',rec.doc),{what:'원문 읽기',silent:true,expect:[413]});}
  catch(e){const x=/** @type {ApiError} */(e),st=x&&x.status||0; return st>=400&&st<500?null:'net';}
  const lines=r.status===200&&r.data&&Array.isArray(r.data.lines)?r.data.lines.map(String):null;
  const at=lines?linesWhere(lines,rec.lines):null; if(!at)return null;
  return {file:rec.lines.file,name:rec.lines.name,lo:at.lo,hi:at.hi,raw_lo:at.lo,raw_hi:at.hi,kind:rec.lines.kind,
    scope:rec.lines.scope||undefined,quote:rec.quote};}
// The drag a record holds, in the PDF points pick reads: the box kept with it, or the one its page fractions and that
// page's size on the build make - the same product selection.js sends when the drag happens. Null when the record has
// neither, which is the one case nothing can be placed from (a box of zeros would resolve to the page's corner). Pure.
/** @param {any} rec @returns {{x0:number,y0:number,x1:number,y1:number}|null} */
function offlineBox(rec){if(rec.rect)return rec.rect;
  const f=rec.frac,pt=rec.pt;
  if(!Array.isArray(f)||f.length<4||!pt||!(pt.w>0)||!(pt.h>0))return null;
  return {x0:f[0]*pt.w,y0:f[1]*pt.h,x1:(f[0]+f[2])*pt.w,y1:(f[1]+f[3])*pt.h};}
// The pin body a found place and a kept record make, the same whitelist POST /api/pin takes (api.md §핀 추가). A pick
// that answered with no file is a region answer - a view-only PDF, or a figure element with no code behind it - and
// that pin is its page and box, as savePin sends one.
/** @param {any} rec @param {any} d @returns {Record<string, unknown>} */
function offlineBody(rec,d){
  if(!d.file){const region=/** @type {Record<string, unknown>} */({page:d.page,frac:d.frac||rec.frac,note:rec.note,
    quote:d.quote||rec.quote||'',pdf_build:d.pdf_build||rec.build||undefined,doc:rec.doc||undefined,
    kind_req:rec.kind_req,assignee:rec.assignee});
    if((rec.mentions||[]).length)region.mentions=rec.mentions;
    if(rec.idem)region.idem=rec.idem;
    return region;}
  const body=/** @type {Record<string, unknown>} */({file:d.file,name:d.name,page:d.page,lo:d.lo,hi:d.hi,
  raw_lo:d.raw_lo,raw_hi:d.raw_hi,kind:d.kind,via:d.via,score:d.score,fill:d.fill,rival:d.rival,frac:d.frac,
  note:rec.note,quote:d.quote||rec.quote||'',pdf_build:d.pdf_build||rec.build||undefined,doc:rec.doc||undefined,
  kind_req:rec.kind_req,assignee:rec.assignee});
  if(d.scope)body.scope=d.scope;
  if((rec.mentions||[]).length)body.mentions=rec.mentions;
  if(rec.idem)body.idem=rec.idem;
  return body;}
// Two boxes are the same box: every number within a millionth of the page, the tolerance a whole-page verdict target
// is read with (domain.md §판정 대상). Pure.
/** @param {unknown} a @param {unknown} b */
function fracSame(a,b){if(!Array.isArray(a)||!Array.isArray(b)||a.length<4||b.length<4)return false;
  for(let i=0;i<4;i++)if(!(Math.abs(a[i]-b[i])<=1e-6))return false; return true;}
// The pin this record already is on the server, or 0: mine, on its document, at the same place, with the same note.
// A send whose answer was lost is found here instead of written twice - the judgment savePin makes for its own lost
// answer. A line answer stands on its lines; a region answer stands on its page AND its box, because two region pins
// on one page are told apart by nothing else, and a page-only judgment deleted a second pin that was never written.
// A pin this queue has already written - in this send or any earlier one (offWrote) - is not offered again: two
// deliberate pins may be alike in every field this reads, and only one of them is that pin. Nor is a pin that was
// already there when this record was attempted (rec.top, as pvLanded reads its own lost answer): whatever that pin
// is, it is not the write this record made afterwards.
/** @param {any} rec @param {any} d @param {Set<number>} claimed @returns {number} */
function offlineLanded(rec,d,claimed){const f=d.frac||rec.frac;
  const top=typeof rec.top==='number'?rec.top:0;
  const hit=OPEN_ALL.find(p=>p.id>top&&!claimed.has(p.id)&&isMe(p.author)&&pdoc(p)===(rec.doc||DEFAULT_DOC)&&String(p.note||'')===String(rec.note||'')&&
    (d.file?(p.file===d.file&&p.lo===d.lo&&p.hi===d.hi):(!p.file&&p.page===d.page&&fracSame(p.frac,f))));
  return hit?hit.id:0;}
// Sends the queue, oldest first: each record's own coordinates and build go to pick, its answer to the pin. A record is
// dropped only once its pin is on the server. One whose place cannot be found again (the build is gone, or the drag no
// longer reads as text) is kept and marked, so the count never hides it and the next send tries again.
async function offlineFlush(){
  // The flag is taken before anything is awaited. Reconnecting fires several triggers within the same tick (the
  // 'online' event, the light poll's recovery, boot, the status line's [지금 반영]); a flag set after the first await
  // let two of them read the same records and write every pin twice, since each had read the list before the other wrote.
  if(OFF.flushing||offlineNow()||viewerBlocked())return;
  OFF.flushing=true;
  const all=await offAll(); if(!all.length){OFF.flushing=false; await offlineSync(); return;}
  // The server is asked what it can do before a way of sending is chosen. What it could do when it was last heard
  // from is not that: a tab drawn from stored reads has heard nothing this visit and starts sending on the 'online'
  // event, and a server may have been rolled back to a Limn that drops the key it does not know. The answer sets
  // OFF.idem on its way through api() (offStash). No answer means the connection is not there after all.
  try{await api(dq('/api/meta?light=1'),{what:'상태 확인',silent:true});}
  catch(e){OFF.flushing=false; return;}
  const saved=/** @type {number[]} */([]),claimed=new Set(await offWrote()); let held=0,failed=0;
  try{
    await loadPins();   // what is already there - a lost answer from an earlier send is found, not written twice
    for(const rec of all){
      if(offlineNow())break;
      // A record whose write was already attempted on a server that knows a write by its key is asked about by the
      // key alone, before anything is placed. The earlier attempt may have made the pin and lost only its answer -
      // and by now its place may be gone (the held build expired; the lines were edited, perhaps by the agent that
      // handled that very pin). Placed first, such a record was held and its key never tried: the pin stood on the
      // server while the record stayed in the queue, a [다시 찍기] away from being made twice. The question writes
      // nothing whichever way it is answered (api.md POST /api/pin, replay_only).
      const keyed=OFF.idem&&!!rec.idem;
      if(keyed&&rec.sent){
        try{const r=await api('/api/pin',{method:'POST',body:{idem:rec.idem,replay_only:true,doc:rec.doc||undefined},what:'핀 저장',silent:true,expect:[409]});
          if(r.status===200&&r.data&&typeof r.data.id==='number'){claimed.add(r.data.id); await offWroteAdd(r.data.id);
            saved.push(r.data.id); await offDel(rec.id); continue;}}
        catch(e){failed++; continue;}}   // no answer to the question either: the record waits, unplaced and unheld
      // Every record is placed afresh. A drag is asked of pick, on the build it was drawn on; the lines of a Markdown
      // or text document are looked for in its source as it reads now. The lines a pick once answered are never
      // written: the manuscript moves while a person is away, and writing them would anchor the pin to whatever
      // stands at those numbers now.
      let d=/** @type {any} */(null);
      if(rec.lines){d=await offlinePlaceLines(rec);
        if(d==='net'){failed++; continue;}
        if(!d){rec.held=true; rec.why=tr('그사이 그 줄들의 글이 바뀌었습니다'); await offPut(rec); held++; continue;}}
      else{const box=offlineBox(rec);
        if(!box){rec.held=true; rec.why=tr('위치를 찾지 못했습니다'); await offPut(rec); held++; continue;}
        const req={page:rec.page,x0:box.x0,y0:box.y0,x1:box.x1,y1:box.y1,
          frac:rec.frac,pdf_build:rec.build||undefined,doc:rec.doc||undefined};
        try{d=(await api('/api/pick',{method:'POST',body:req,what:'위치 찾기',silent:true})).data;}
        catch(e){failed++; continue;}                     // no answer or a refusal: the record stays for the next send
        if(!d||d.error){rec.held=true; rec.why=errText(d)||tr('위치를 찾지 못했습니다'); await offPut(rec); held++; continue;}}
      // A server that knows a write by its key needs none of the looking below: the same key is the same pin, so the
      // record is sent with it until an answer comes, and an answer to a second attempt names the pin the first made.
      // The attempt is recorded before it is made (a tab closed mid-request never reaches the lines after it), which
      // is what sends the next visit to the question above. A refusal of the request itself (4xx) says nothing was
      // written: the mark comes off and the record is kept with what the server said.
      // Both ways of sending keep what the other needs. This one notes the pins that existed before the attempt
      // (top) and records the pin it writes (offWroteAdd), although it reads neither: a server rolled back to a Limn
      // without the key sends the next visit to the looking below, and an attempt marked here with no boundary let
      // any older look-alike answer for it, as a pin written here but not recorded let a twin's pin do.
      if(keyed){
        if(!(await offHas(rec.id)))continue;
        rec.sent=true; rec.top=pvTopId(); await offPut(rec);
        try{const {data}=await api('/api/pin',{method:'POST',body:offlineBody(rec,d),what:'핀 저장',silent:true});
          if(data&&typeof data.id==='number'){claimed.add(data.id); await offWroteAdd(data.id);}
          saved.push(data&&data.id); await offDel(rec.id);}
        catch(e){const x=/** @type {ApiError} */(e),st=x&&x.status||0;
          if(st>=400&&st<500){rec.sent=false; rec.held=true; rec.why=errText(x.data)||('HTTP '+st); await offPut(rec); held++;}
          else failed++;}
        continue;}
      // Only a record whose write was already attempted can be a pin on the server. A record that has never been
      // sent is written, whatever is there: two pins alike in document, place and note are told apart by nothing this
      // can read, and matching a fresh record against one of them deleted a pin that was never written.
      if(rec.sent){const was=offlineLanded(rec,d,claimed);
        if(was){claimed.add(was); await offWroteAdd(was); saved.push(was); await offDel(rec.id); continue;}}   // its pin number, not the record's
      // Another tab of this browser shares the queue and may have written this one while the pick was out: a record
      // that is no longer there has been dealt with, and writing it again would make the pin twice.
      if(!(await offHas(rec.id)))continue;
      // The attempt is recorded before it is made: a tab closed mid-request never reaches the lines below, and the
      // record has to stay matchable or its pin is written twice. The mark comes off again only for an answer that
      // says the request was turned away before anything was written - a refusal of the request itself (4xx: a field
      // the server would not take, a role that may not write, a conflict). Everything else may be on the server: no
      // answer at all, a 5xx the server returned after its write went through, a gateway's 502 or 504 over a request
      // that did reach it. Those keep the mark and are looked for in the list instead.
      rec.sent=true; rec.top=pvTopId(); await offPut(rec);   // the pins that existed before this write, as savePin notes for its own
      try{const {data}=await api('/api/pin',{method:'POST',body:offlineBody(rec,d),what:'핀 저장',silent:true});
        if(data&&typeof data.id==='number'){claimed.add(data.id); await offWroteAdd(data.id);}
        saved.push(data&&data.id); await offDel(rec.id);}
      catch(e){const x=/** @type {ApiError} */(e);
        const st=x&&x.status||0;
        if(st>=400&&st<500){rec.sent=false; rec.held=true; rec.why=errText(x.data)||('HTTP '+st); await offPut(rec); held++; continue;}   // turned away: nothing is on the server
        await loadPins(); const late=offlineLanded(rec,d,claimed);
        if(late){claimed.add(late); await offWroteAdd(late); saved.push(late); await offDel(rec.id); continue;}
        failed++;}}
  }finally{OFF.flushing=false; try{await offWroteKeep(await offAll());}catch(e){} await offlineSync(); await loadPins();}
  const ids=saved.filter(n=>typeof n==='number');
  if(ids.length)lineNote(ids.length<=3?tl('오프라인 핀 저장됨 · #{ids}',{ids:ids.join(', #')}):tl('오프라인 핀 {n}개 저장됨',{n:ids.length}),
    NOTICE_KIND.OK,null,{life:NOTICE_LIFE.TIMER,literal:true});
  if(held)lineNote(tl('오프라인 핀 {n}개는 반영하지 못했습니다 — 쌓인 핀 목록에서 까닭을 보고 다시 찍거나 버리세요',{n:held}),NOTICE_KIND.WARN,null,{literal:true});
  if(failed)lineNote(tl('오프라인 핀 {n}개를 아직 보내지 못했습니다 — 연결되면 다시 보냅니다',{n:failed}),NOTICE_KIND.WARN,
    {label:'지금 반영',fn:()=>{void offlineFlush();}},{literal:true});}

// Boot: the worker is registered, the queue is counted, and a queue waiting on a live connection is sent right away. The
// light poll calls offlineFlush() again whenever the connection comes back (polling.js).
function offlineBoot(){OFF.boot=false;   // the first reads are done: from here a read that fails while connected is a failure again
  void offlineWorker();
  void offlineSync().then(()=>{if(OFF.n&&!offlineNow())void offlineFlush();});}
addEventListener('online',()=>{void offlineFlush();});
