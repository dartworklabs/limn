// ------------------------------------------------ Server calls
// Calls the server (JSON in and out) and returns {status, data}; a network failure or an unexpected status >= 400 throws. Unless
// o.silent it is said first (apiFailed): o.what names the request ('핀 저장'), o.where the place (a NOTICE_HOST), o.retry the
// action a network failure offers, o.save that it was a pin's save. o.quietUnreached leaves a failure to reach the server
// to the caller to say (a refusal is still said). o.expect lists the statuses the caller handles itself;
// o.keepalive lets the request outlive the page; o.signal (an AbortSignal) ends it unanswered, as a network failure - also
// while its body is read. o.wait (ms) is the longest it waits for an answer, body included; past it the request is
// ended and is a network failure like any other (API_WAIT). Its error is keyed by its source - o.source, else its
// method and URL (which
// name its pin and document) with o.intent, what it asks of a URL several actions share (a pin's edit: 'edit', 'loc',
// 'append', 'append-undo'): a repeat replaces it, and an answer from the same source - the same intent - clears it (sourceOk).
// How long a request waits for an answer (ms). A server that cannot be reached does not always refuse: on a tailnet
// with no internet behind it the name still resolves and the request goes into the tunnel, and nothing comes back for
// as long as the system lets a connection wait - a minute and more. Everything that tells "cut off" from "connected"
// hangs on a request failing, so a request that only waits left the viewer connected and busy: the light poll never
// counted a failure, a drag's composer never opened, a save never ended and nothing reached the queue. A request that
// carries a wait is ended at it and fails as an unreached server does.
//   POLL  the light poll, and the question a send of the queue starts with
//   READ  a document read that has a stored answer to fall back on (offline.js OFF_READS)
//   PICK  finding a selection's lines        SAVE  writing a new pin        SEND  a request of the queue's send
// Requests without one (a rebuild, a revision's diff or build) may take as long as the server needs.
// API_OUT says the last request that ended got no answer (or the worker answered this page from its copy because the
// network did not, offlineAskDown). While it stands and a stored answer may serve (offlineMayServe), a document read
// with a stored answer is answered from it without asking: a visit's first reads are made one after another, and each
// waiting out its own request drew the page a read's wait later, every time. The light poll always asks, and its
// answer - any answer - takes API_OUT down.
const API_WAIT={POLL:8000,READ:8000,PICK:8000,SAVE:10000,SEND:30000};
let API_OUT=false;
/** @returns {Promise<{status: number, data: any}>} */
async function api(url,o){o={...(o||{})}; o.source=o.source||(o.method||'GET')+' '+url+(o.intent?' '+o.intent:'');
  const init=/** @type {RequestInit&{headers:Record<string,string>}} */({method:o.method||'GET',headers:{}}); if(o.keepalive)init.keepalive=true; if(o.signal)init.signal=o.signal;
  if(o.body!==undefined){init.body=JSON.stringify(o.body);init.headers['Content-Type']='application/json';}
  const read=!!offReadKey(url,o);
  if(read&&API_OUT&&offlineMayServe()){const kept=await offStashed(url,o);
    if(kept){offStaleSaid(kept.at); sourceOk(o.source); return {status:kept.status,data:kept.data};}}
  const wait=o.wait||(read?API_WAIT.READ:0);
  let timer=/** @type {ReturnType<typeof setTimeout>|undefined} */(undefined); const ctl=wait?new AbortController():null;
  if(ctl){const end=()=>ctl.abort(); timer=setTimeout(end,wait); init.signal=ctl.signal;
    if(o.signal){if(o.signal.aborted)end(); else o.signal.addEventListener('abort',end,{once:true});}}   // the caller's signal still ends it
  let r;
  try{r=await fetch(url,init);}catch(e){clearTimeout(timer); return apiUnanswered(url,o,e);}
  let d=null; try{d=await r.json();}catch(e){
    if(o.signal&&o.signal.aborted){clearTimeout(timer); throw e;}   // a body the caller's signal cut off is no answer, not an empty one
    if(ctl&&ctl.signal.aborted)return apiUnanswered(url,o,e);}      // nor is one the wait ran out on
  clearTimeout(timer); API_OUT=false;
  if(r.status>=400&&!(o.expect||[]).includes(r.status)){
    if(!o.silent)apiFailed(o,errText(d)||('HTTP '+r.status),false);
    const err=/** @type {ApiError} */(new Error('HTTP '+r.status)); err.status=r.status; err.data=d; throw err;}
  sourceOk(o.source); offlineBack(); offStash(url,d,r.status,o);   // a document read the server answered is kept for a later visit with no network
  return {status:r.status,data:d};
}
// A request that got no answer - refused by the network, or ended at its wait.
// A document read is answered from the last answer stored for it, where there is one and only where that is meant
// (offlineMayServe: this visit's first reads, or a connection known to be gone): a tab opened again with no network is
// drawn from it instead of staying empty. Writes, every other read, and a read that fails while the viewer is
// connected fail as before.
/** @param {string} url @param {any} o @param {unknown} e @returns {Promise<{status: number, data: any}>} */
async function apiUnanswered(url,o,e){if(!(o.signal&&o.signal.aborted))API_OUT=true;   // ended by its caller is not unanswered
  const kept=offlineMayServe()?await offStashed(url,o):null;
  if(kept){offStaleSaid(kept.at); sourceOk(o.source); return {status:kept.status,data:kept.data};}
  if(!o.silent&&!o.quietUnreached)apiFailed(o,tr('서버에 닿지 않습니다'),true); throw e;}
// Says that request o failed ('{what} 실패 — {why}'): on the status line when o.where is NOTICE_HOST.LINE, else in a banner at
// that host (bannerNote), keyed by its source. [다시 시도] (o.retry) only when the server could not be reached - a refusal
// would refuse again.
/** @param {{what?:string,where?:string,retry?:()=>void,save?:boolean,source?:string}} o @param {string} why @param {boolean} unreachable */
function apiFailed(o,why,unreachable){const msg=tl('{what} 실패',{what:tr(o.what||'요청').replace(/…$/,'')})+' — '+why;
  const act=unreachable&&o.retry?{label:'다시 시도',fn:o.retry}:null,source=o.source||'';
  if(o.where===NOTICE_HOST.LINE)lineNote(msg,NOTICE_KIND.ERR,act,{source}); else bannerNote(o.where,msg,NOTICE_KIND.ERR,act,{save:!!o.save,source});}
// Copies s to the clipboard (a textarea and execCommand where the Clipboard API is refused). Said where it happened: the
// control that copied (el) reads '복사됨' with a check for a moment (copiedMark), and it is read out politely.
/** @param {string} s @param {HTMLElement|null} [el] */
async function copyText(s,el){
  try{await navigator.clipboard.writeText(s);}catch(e){
    const ta=document.createElement('textarea');ta.value=s;document.body.appendChild(ta);ta.select();
    try{document.execCommand('copy');}catch(e2){} ta.remove();}
  quietNote(tl('복사함: {text}',{text:s})); if(el)copiedMark(el);
}
const COPIED_MS=1500;   // how long a copy control says it copied
// Control el says it copied: a check and '복사됨' in place of what it shows, never narrower than it was, for COPIED_MS; then
// what it showed comes back. A second copy meanwhile starts the moment again. Its name (aria-label) stays: the copy is read
// out by copyText.
/** @param {HTMLElement} el */
function copiedMark(el){if(el._copiedT)clearTimeout(el._copiedT);
  else{el._copied=[...el.childNodes]; el.style.minWidth=Math.ceil(el.getBoundingClientRect().width)+'px';}
  el.classList.add('copied'); setHtml(el,html`${ic('check')}<span class="lbl">${tr('복사됨')}</span>`);
  el._copiedT=setTimeout(()=>{el.classList.remove('copied'); el.replaceChildren(...(el._copied||[])); el._copied=undefined; el._copiedT=undefined; el.style.minWidth='';},COPIED_MS);}

