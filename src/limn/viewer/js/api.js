// ------------------------------------------------ Server calls
// Calls the server (JSON in and out) and returns {status, data}; a network failure or an unexpected status >= 400 throws. Unless
// o.silent it is said first (apiFailed): o.what names the request ('핀 저장'), o.where the place (a NOTICE_HOST), o.retry the
// action a network failure offers, o.save that it was a pin's save. o.expect lists the statuses the caller handles itself;
// o.keepalive lets the request outlive the page. Its error is keyed by its source - o.source, else its method and URL (which
// name its pin and document): a repeat replaces it, and an answer from the same source clears it (sourceOk).
/** @returns {Promise<{status: number, data: any}>} */
async function api(url,o){o={...(o||{})}; o.source=o.source||(o.method||'GET')+' '+url;
  const init={method:o.method||'GET',headers:{}}; if(o.keepalive)init.keepalive=true;
  if(o.body!==undefined){init.body=JSON.stringify(o.body);init.headers['Content-Type']='application/json';}
  let r;
  try{r=await fetch(url,init);}catch(e){if(!o.silent)apiFailed(o,tr('서버에 닿지 않습니다'),true);throw e;}
  let d=null; try{d=await r.json();}catch(e){}
  if(r.status>=400&&!(o.expect||[]).includes(r.status)){
    if(!o.silent)apiFailed(o,errText(d)||('HTTP '+r.status),false);
    const err=/** @type {ApiError} */(new Error('HTTP '+r.status)); err.status=r.status; err.data=d; throw err;}
  sourceOk(o.source); return {status:r.status,data:d};
}
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

