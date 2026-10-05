// ------------------------------------------------ Messages in context (docs/handbook/viewer.md §알림 자리)
// The viewer has no toast (#167): every message has a home where it happened.
// - A success is silent unless it can be undone; a silent one is still read out (#sr-news, quietNote). An undo sits where the
//   action was (undoNote): a chip on the new pin's mark, a row in the card's place, a note in the card, a row in the Trash -
//   or the status line when that place is not on screen.
// - An error or a conflict is a banner at the top of the panel or section concerned (bannerNote), with its action - or, when
//   that place is not on screen now, the same on the status line, read out as an alert, with a dot on the chip that leads
//   there (rule 1: an error appears where the person can see it now; errors come first on the line).
// - Background events and first-visit hints go to the status line (lineNote); a background event also puts a red dot on the
//   chip that leads to it ([핀 N], [검토 M]) until the person looks there.
// - An undo lives its full NOTICE_MS window, or until the person dismisses or uses it; other presses never end it (rule 2).
// Every message is a Notice in NOTICES, numbered n; its buttons carry data-act="notice-act"/"notice-x" and data-n.
const NOTICE_MS=6000;   // the undo window: a deferred send goes when it ends (deferred()), and a save's chip stays as long
const LINE_MAX=5;       // the status line keeps the newest five messages; its '+N' lists the rest
const NOTICES=/** @type {Map<number,Notice>} */(new Map());
const LINE=/** @type {Notice[]} */([]);                         // the status line's messages, newest first
const BANNERS=/** @type {Map<string,Notice>} */(new Map());      // NOTICE_HOST -> its one banner
let NOTICE_SEQ=0;
// A message's lead icon by its kind (noticeIcon).
const NOTICE_IC=/** @type {Record<string,()=>Html>} */({[NOTICE_KIND.OK]:()=>ic('circle-check'),[NOTICE_KIND.WARN]:()=>ic('triangle-alert'),
  [NOTICE_KIND.ERR]:()=>ic('circle-x'),[NOTICE_KIND.INFO]:()=>ic('info')});
// The lead icon of a message of kind (NOTICE_KIND); an unknown kind draws the success one.
/** @param {string} kind @returns {Html} */
function noticeIcon(kind){return (NOTICE_IC[kind]||NOTICE_IC[NOTICE_KIND.OK])();}

// A message as [title, description]: everything before the first ' — ' (else the first ' · ') is the title, so the title of
// '핀 #10 · 본문 — 서준님이 불렀습니다: …' is '핀 #10 · 본문'. A message without either is all title. Pure.
/** @param {unknown} msg @returns {[string,string]} */
function msgSplit(msg){const s=String(msg==null?'':msg),m=/^(.+?) — (.+)$/.exec(s)||/^(.+?) · (.+)$/.exec(s); return m?[m[1],m[2]]:[s,''];}

// One event announced twice is shown once (QA: a focused tab showed both '핀 #37 · 본문 — 검토 대기: …' and '#37 이 검토 대기로
// 넘어왔습니다'). shown = the messages on the line; keys = the new message's event keys ('review_requested:37'), rank its path
// (the browser-notification path 2, the list comparison 1). Among shown messages younger than 8 seconds that share a key: a
// higher rank holding every key suppresses the new one ({skip:true}); a lower rank is replaced by it (drop). The same rank is
// the same path and so another event (a second review request after a reopen): never suppressed. No keys, no check. Pure.
/** @param {Notice[]} shown @param {string[]} keys @param {number} rank @param {number} now @returns {{skip:boolean,drop:Notice[]}} */
function noticeDupe(shown,keys,rank,now){const drop=/** @type {Notice[]} */([]); if(!keys||!keys.length)return {skip:false,drop};
  for(const x of shown){if(now-x.at>8000||!x.keys.length||!keys.some(k=>x.keys.includes(k)))continue;
    if(x.rank>rank&&keys.every(k=>x.keys.includes(k)))return {skip:true,drop:[]};
    if(rank>x.rank)drop.push(x);}
  return {skip:false,drop};}

// Where a banner goes (a NOTICE_HOST): the Trash while it is open as a modal - the page under it is inert, so a banner there
// could be neither read nor dismissed - else the host the call names, else the composer while one is open, else the top of
// the panel. Pure.
/** @param {string|undefined} want @param {{trashOpen:boolean,composerOpen:boolean}} v @returns {string} */
function bannerHost(want,v){if(v.trashOpen)return NOTICE_HOST.TRASH; if(want)return want; return v.composerOpen?NOTICE_HOST.COMPOSER:NOTICE_HOST.LIST;}
// Whether a banner host is on screen now (rule 1): the Trash while it is open; the composer while one is open in the shown
// panel (the phone's unfolded sheet); the list and the review section while the panel is shown. A banner whose host is not
// goes to the status line instead (bannerNote). Pure.
/** @param {string} host @param {{sideOpen:boolean,trashOpen:boolean,composerOpen:boolean}} v @returns {boolean} */
function bannerShown(host,v){if(host===NOTICE_HOST.TRASH)return v.trashOpen; if(host===NOTICE_HOST.COMPOSER)return v.sideOpen&&v.composerOpen; return v.sideOpen;}

// Whether an undo can be shown where its action happened; if not it goes to the status line. A row or a card note needs the
// panel open and its section expanded, a Trash row the Trash open; a chip waits for its mark (drawChips). Pure.
/** @param {string} place @param {{sideOpen:boolean,secOpen:boolean,trashOpen:boolean}} v @returns {boolean} */
function offerSeen(place,v){if(place===NOTICE_PLACE.TRASH)return v.trashOpen;
  if(place===NOTICE_PLACE.ROW||place===NOTICE_PLACE.CARD)return v.sideOpen&&v.secOpen; return true;}

// The dot a background message puts on a chip (a NOTICE_DOT, or '' for none): [검토 M]'s always; [핀 N]'s only while the
// panel is closed - an open panel already shows the list. Pure.
/** @param {string} want @param {boolean} sideOpen @returns {string} */
function noticeDot(want,sideOpen){return want===NOTICE_DOT.SIDE&&sideOpen?'':want||'';}

// Registers a new message from its fields; msg is split into its title and description (msgSplit).
/** @param {Partial<Notice>&{msg:string}} o @returns {Notice} */
function makeNotice(o){const [title,desc]=msgSplit(o.msg);
  const n=/** @type {Notice} */({n:++NOTICE_SEQ,place:o.place||NOTICE_PLACE.LINE,host:o.host||'',pin:o.pin==null?null:o.pin,sec:o.sec||'',
    prev:o.prev==null?null:o.prev,kind:o.kind||NOTICE_KIND.OK,title,desc,label:o.label||'',act:o.act||null,literal:!!o.literal,keys:o.keys||[],
    rank:o.rank||1,at:Date.now(),life:o.life||NOTICE_LIFE.STICKY,dot:o.dot||'',topic:o.topic||'',save:!!o.save,pending:!!o.pending,away:false,
    alert:!!o.alert,busy:false,timer:undefined,gone:o.gone||null,el:null});
  NOTICES.set(n.n,n); return n;}

// Reads text out politely (#sr-news: a silent success, an undo drawn where it happened, an info banner) or assertively
// (#sr-alert: an error on the status line). The same text twice in a row is read again: the region is emptied first.
/** @param {string} text @param {boolean} [assertive] */
function announce(text,assertive){const r=$(assertive?'#sr-alert':'#sr-news'); if(!r||!text)return;
  if(r.textContent===text){r.textContent=''; requestAnimationFrame(()=>{r.textContent=text;});} else r.textContent=text;}

// A success with nothing to undo: nothing is drawn - the change itself is on screen - but it is read out as before.
/** @param {string} msg */
function quietNote(msg){announce(trMsg(msg));}

// Puts a message on the status line, newest first, and returns it - or null when it repeats one already there (noticeDupe).
// o: literal (msg is already in the UI language and quotes what people wrote, so it is not translated), keys and rank, life
// (NOTICE_LIFE: STICKY until [x] or its action, CLICK until a press elsewhere, TIMER for NOTICE_MS), dot (the chip it marks,
// noticeDot), topic (a hint's, endTopic), gone (runs when it leaves other than by its action), alert (a warning read out as
// an alert: a banner whose place was not on screen). An error is always an alert: read out assertively (#sr-alert), first on
// the line (statusList), and past LINE_MAX the oldest other message leaves before it does. Any other message is read out by
// the line when it shows it, else - another one holds the line - politely (#sr-news).
/** @param {string} msg @param {string} kind @param {NoticeAct|null} [act] @param {Partial<Notice>} [o] @returns {Notice|null} */
function lineNote(msg,kind,act,o){o=o||{}; const keys=o.keys||[],rank=o.rank||1;
  const d=noticeDupe(LINE,keys,rank,Date.now()); if(d.skip)return null; d.drop.forEach(x=>endNotice(x,false));
  const n=makeNotice({...o,msg:o.literal?String(msg):trMsg(msg),kind,act:act||null,place:NOTICE_PLACE.LINE,pending:false,
    alert:kind===NOTICE_KIND.ERR||!!o.alert,dot:noticeDot(o.dot||'',SIDE_OPEN)});
  LINE.unshift(n); while(LINE.length>LINE_MAX)endNotice(LINE.slice(1).reverse().find(x=>!x.alert)||LINE[LINE.length-1],false);
  if(n.dot)document.body.classList.add('dot-'+n.dot);
  drawStatus(); armNotice(n);
  if(n.alert)announce(noticeText(n),true); else if(STATUS_TOP!==n.n)announce(noticeText(n));
  return n;}

// Puts a banner on top of its host's panel or section (bannerHost), replacing the one there, and scrolls it into view. ERR and
// WARN banners are alerts, read out when drawn; OK and INFO ones are read out politely. o.save marks a failed save: the
// composer's button then reads [다시 저장]. A host not on screen now (bannerShown) - the Trash closed, the panel collapsed,
// the phone's sheet folded - gets nothing: the message goes to the status line instead, ERR and WARN as alerts, with the dot
// on the chip that leads there ([검토 M] for the review section's, else [핀 N]). Returns the message drawn.
/** @param {string|undefined} host @param {string} msg @param {string} kind @param {NoticeAct|null} [act] @param {Partial<Notice>} [o] @returns {Notice|null} */
function bannerNote(host,msg,kind,act,o){o=o||{};
  const v={sideOpen:SIDE_OPEN,trashOpen:$('#trash').open,composerOpen:!$('#composer').hidden},h=bannerHost(host,v);
  if(!bannerShown(h,v))return lineNote(msg,kind,act,{...o,alert:kind===NOTICE_KIND.ERR||kind===NOTICE_KIND.WARN,
    dot:h===NOTICE_HOST.REVIEW?NOTICE_DOT.RV:NOTICE_DOT.SIDE});
  const old=BANNERS.get(h); if(old)endNotice(old,false);
  const n=makeNotice({...o,msg:o.literal?String(msg):trMsg(msg),kind,act:act||null,place:NOTICE_PLACE.BANNER,host:h});
  BANNERS.set(h,n); drawBanners();
  if(kind!==NOTICE_KIND.ERR&&kind!==NOTICE_KIND.WARN)announce(noticeText(n));
  if(n.el&&n.el.getClientRects().length)n.el.scrollIntoView({block:'nearest'});
  return n;}

// Offers an undo where the action happened (place CHIP, ROW, CARD or TRASH; offerSeen) or, when that place is not on screen,
// on the status line. o: pin, sec (its list section: 'open', 'review' or 'done') and prev (the pin drawn before it), label (a
// chip's short text; the whole message is what is read out), life (TIMER: NOTICE_MS, unless given - rule 2, no other press
// ends it), gone, pending (a chip whose mark comes only with the next list reload: settleChip). act.tip defaults to T.undo;
// act.wait = its action sends a request, and the undo stays until that is answered (noticeAct).
/** @param {string} place @param {string} msg @param {NoticeAct} act @param {Partial<Notice>} o @returns {Notice} */
function undoNote(place,msg,act,o){const a={tip:T.undo,...act},life=o.life||NOTICE_LIFE.TIMER;
  if(!offerSeen(place,{sideOpen:SIDE_OPEN,secOpen:!o.sec||!!SEC[o.sec],trashOpen:$('#trash').open}))
    return /** @type {Notice} */(lineNote(msg,NOTICE_KIND.OK,a,{...o,life}));   // no keys: never suppressed
  const n=makeNotice({...o,life,msg:trMsg(msg),kind:NOTICE_KIND.OK,act:a,place});
  armNotice(n); drawOffer(n); announce(noticeText(n)); return n;}

// Whether an undo row stands in list section sec ('open', 'review'): drawPins keeps that section shown while one does.
/** @param {string} sec @returns {boolean} */
function offersIn(sec){for(const n of NOTICES.values())if(n.place===NOTICE_PLACE.ROW&&n.sec===sec)return true; return false;}

// The id of the element drawn just before pin id's in box (both matching sel: '.pin.card', '.arc-row'), or null - where a
// row left in its place goes. Reads the page.
/** @param {HTMLElement} box @param {string} sel @param {number|null} id @returns {number|null} */
function drawnBefore(box,sel,id){const c=box.querySelector(sel+'[data-id="'+id+'"]'); let p=c&&c.previousElementSibling;
  while(p&&!p.matches(sel))p=p.previousElementSibling; return p?Number(/** @type {HTMLElement} */(p).dataset.id):null;}

// A message's text as one line: its title, then ' · ' and its description.
/** @param {Notice} n */
function noticeText(n){return n.title+(n.desc?' · '+n.desc:'');}

// Draws a new offer in its place now; its place's own redraw keeps it there (drawPins, marks, drawTrash).
/** @param {Notice} n */
function drawOffer(n){if(n.place===NOTICE_PLACE.CHIP)drawChips(); else if(n.place===NOTICE_PLACE.TRASH)drawTrashOffers(); else drawOffers();}

// Starts a message's life: a TIMER one ends after NOTICE_MS - paused while a mouse is on it, or for one on the status line while
// the line holds (lineHeld), and from the start again when that ends, as the toast did; not by the focus, which a reply sent
// with Ctrl+Enter puts on its [되돌리기], so the send would wait for the focus to move; nor while its action's request is out
// (busy). CLICK and STICKY ones wait for the press listener below, [x] or their action.
/** @param {Notice} n */
function armNotice(n){if(n.life!==NOTICE_LIFE.TIMER)return; clearTimeout(n.timer); n.timer=undefined;
  if(n.busy||n.place===NOTICE_PLACE.LINE&&lineHeld())return; n.timer=setTimeout(()=>endNotice(n,false),NOTICE_MS);}
// The status line holds its messages' windows while a mouse is on it (LINE_HOVER) or its '+N' list is open: what it shows
// there is being read. holdLine stops them; releaseLine starts each again once nothing holds.
let LINE_HOVER=false;
function lineHeld(){return LINE_HOVER||$('#status-list').open;}
function holdLine(){LINE.forEach(n=>{if(n.life===NOTICE_LIFE.TIMER){clearTimeout(n.timer); n.timer=undefined;}});}
function releaseLine(){if(lineHeld())return; LINE.forEach(n=>{if(n.life===NOTICE_LIFE.TIMER&&n.timer===undefined)armNotice(n);});}
$('#status').addEventListener('pointerenter',e=>{if(e.pointerType!=='mouse')return; LINE_HOVER=true; holdLine();});
$('#status').addEventListener('pointerleave',()=>{if(!LINE_HOVER)return; LINE_HOVER=false; releaseLine();});
$('#status-list').addEventListener('close',releaseLine);

// Takes a message away from its store and the screen. acted = its own action ended it: gone does not run (the action replaces
// it). acted or seen ([x]) = the person has read it: its dot goes unless another message on the line still holds it. Idempotent.
/** @param {Notice} n @param {boolean} acted @param {boolean} [seen] */
function endNotice(n,acted,seen){if(!NOTICES.has(n.n))return; NOTICES.delete(n.n); clearTimeout(n.timer);
  const li=LINE.indexOf(n); if(li>=0)LINE.splice(li,1);
  if(n.place===NOTICE_PLACE.BANNER&&BANNERS.get(n.host)===n)BANNERS.delete(n.host);
  if(n.el)n.el.remove();
  if((acted||seen)&&n.dot&&!LINE.some(x=>x.dot===n.dot))document.body.classList.remove('dot-'+n.dot);
  if(n.place===NOTICE_PLACE.LINE)drawStatus(); if(n.place===NOTICE_PLACE.BANNER)syncSaveBtn();
  if(!acted&&n.gone){const g=n.gone; n.gone=null; g();}}

// [되돌리기], [다시 시도], [보기]… on message num: the message goes and its action runs. An action that sends a request
// (act.wait: restoring, undoing a close, a delete, a save or an append) keeps its message, busy and with its window stopped,
// until the request is answered (rule 1: not cleared as if it had worked) - a failure then says itself where it can be seen.
/** @param {number} num */
function noticeAct(num){const n=NOTICES.get(num); if(!n||n.busy)return; const a=n.act;
  if(!a||!a.wait){endNotice(n,true); if(a)a.fn(); return;}
  n.busy=true; clearTimeout(n.timer); n.timer=undefined;
  document.querySelectorAll('[data-act="notice-act"][data-n="'+n.n+'"]').forEach(b=>b.setAttribute('aria-busy','true'));
  Promise.resolve(a.fn()).catch(()=>false).then(()=>endNotice(n,true));}
// [x] on message num: it goes as read (with its dot), and what it held runs (gone: a deferred send goes now).
/** @param {number} num */
function noticeClose(num){const n=NOTICES.get(num); if(n)endNotice(n,false,true);}
// A hint goes once the person does what it says (NOTICE_TOPIC.PICK: a selection was made; SIDE: the panel was opened).
/** @param {string} topic */
function endTopic(topic){NOTICES.forEach(n=>{if(n.topic===topic)endNotice(n,false,true);});}
// The person looks where a dot points (the panel opened, the review section gone to): that dot goes, with the panel open the
// hint on how to open it, and with the review section the messages about pins sent to review (seen).
/** @param {string} dot */
function noticeSeen(dot){if(dot===NOTICE_DOT.RV)LINE.slice().forEach(n=>{if(reviewPins(n.keys).length)endNotice(n,false,true);});
  document.body.classList.remove('dot-'+dot); if(dot===NOTICE_DOT.SIDE)endTopic(NOTICE_TOPIC.SIDE);}
// The pins a message's keys say were sent to review ('review_requested:<id>', noticeDupe's keys). Pure.
/** @param {string[]} keys @returns {number[]} */
function reviewPins(keys){const p=EVENT_TYPE.REVIEW_REQUESTED+':'; return keys.filter(k=>k.startsWith(p)).map(k=>Number(k.slice(p.length)));}
// Whether a message about pins sent to review is stale: it names some, and none of them awaits review any more (confirmed,
// reopened or deleted - here or elsewhere). inReview = the ids awaiting review. Pure.
/** @param {string[]} keys @param {number[]} inReview @returns {boolean} */
function reviewNewsStale(keys,inReview){const ids=reviewPins(keys); return ids.length>0&&!ids.some(i=>inReview.includes(i));}
// Each time the list is drawn (drawPins: after a reload, a confirm): the stale review arrivals go (reviewNewsStale), and
// [검토 M]'s dot - on the collapsed desktop's [핀 N] too - once no message on the line holds it.
function dropStaleReview(){const ids=REVIEW_ALL.map(p=>p.id); LINE.slice().forEach(n=>{if(reviewNewsStale(n.keys,ids))endNotice(n,false,true);});
  if(!LINE.some(n=>n.dot===NOTICE_DOT.RV))document.body.classList.remove('dot-'+NOTICE_DOT.RV);}

// A CLICK message - a passing notice that is not an undo (a restored draft's [버리기]) - lasts until the next press somewhere
// else: a click (a tap, Enter on a button) outside it ends it; a scroll does not. The press that made it has passed by the time
// it exists. An undo is never CLICK (rule 2).
document.addEventListener('click',e=>{const t=/** @type {HTMLElement} */(e.target);
  NOTICES.forEach(n=>{if(n.life!==NOTICE_LIFE.CLICK)return;
    const own=n.place===NOTICE_PLACE.LINE?!!(t.closest&&t.closest('#status,#status-list')):!!(n.el&&n.el.contains(t));
    if(!own)endNotice(n,false);});},true);

// One message's element, made once and kept on n.el (a redraw moves it, so a focus inside survives and an alert is not read
// out again): status icon, title and description (already in the UI language, so translate="no"), its action, and [x] -
// none on a chip, which goes by itself. ERR and WARN banners are alerts. A TIMER message holds while a mouse is on it (armNotice).
/** @param {Notice} n @param {string} cls @returns {HTMLElement} */
function noticeEl(n,cls){if(n.el)return n.el; const e=document.createElement('div'); e.className='nt '+cls+' nk-'+n.kind; e.dataset.n=String(n.n);
  if(n.place===NOTICE_PLACE.BANNER&&(n.kind===NOTICE_KIND.ERR||n.kind===NOTICE_KIND.WARN))e.setAttribute('role','alert');
  const chip=n.place===NOTICE_PLACE.CHIP,title=chip&&n.label?n.label:n.title,desc=chip?'':n.desc;
  setHtml(e,html`<span class="nt-ic">${noticeIcon(n.kind)}</span><span class="nt-t" translate="no"><span class="nt-ti">${title}</span>${desc?html`<span class="nt-d">${desc}</span>`:''}</span><span class="nt-acts">${noticeButtons(n,!chip)}</span>`);
  if(chip)for(const t of ['pointerdown','mousedown'])e.addEventListener(t,ev=>ev.stopPropagation());   // a press on the chip never starts a selection on the page under it
  if(n.life===NOTICE_LIFE.TIMER){e.addEventListener('pointerenter',ev=>{if(ev.pointerType==='mouse'){clearTimeout(n.timer); n.timer=undefined;}});
    e.addEventListener('pointerleave',ev=>{if(ev.pointerType==='mouse'&&NOTICES.has(n.n))armNotice(n);});}
  n.el=e; return e;}
// A message's buttons: its action (with its description, if any; aria-busy while its request is out) and, with close, [x]
// named '알림 닫기'.
/** @param {Notice} n @param {boolean} close @returns {Html} */
function noticeButtons(n,close){const a=n.act,tip=a&&a.tip?html` data-tip="${a.tip}"`:'',busy=n.busy?html` aria-busy="true"`:'';
  return html`${a?html`<button type="button" class="btn-sm btn-secondary nt-act" data-act="notice-act" data-n="${n.n}"${tip}${busy}><span class="lbl">${tr(a.label)}</span></button>`:''}\
${close?html`<button type="button" class="btn-icon btn-sm btn-ghost nt-x" data-act="notice-x" data-n="${n.n}" aria-label="알림 닫기">${ic('x')}</button>`:''}`;}

// The focused element inside a drawn message, if any: a redraw that detaches it gives the focus back (noticeRefocus).
/** @returns {HTMLElement|null} */
function noticeFocus(){const a=/** @type {HTMLElement|null} */(document.activeElement); return a&&a.closest&&a.closest('.nt')?a:null;}
/** @param {HTMLElement|null} a */
function noticeRefocus(a){if(a&&document.contains(a)&&document.activeElement!==a)a.focus({preventScroll:true});}

// Banners in their hosts: the composer's above its save row, the review section's under its head (at the top of the list while
// that section is hidden), the Trash's above its list, the list's at its top. One already in place is not moved.
function drawBanners(){BANNERS.forEach((n,host)=>{const e=noticeEl(n,'nt-banner'),rv=host===NOTICE_HOST.REVIEW&&!$('#sec-review').hidden;
  const p=host===NOTICE_HOST.COMPOSER?$('#c-actions'):host===NOTICE_HOST.TRASH?$('#trash'):rv?$('#sec-review'):$('#list');
  const before=host===NOTICE_HOST.TRASH?$('#trash-list'):rv?$('#review-pins'):p.firstElementChild;
  if(e.parentNode!==p||(before!==e&&e.nextElementSibling!==before))p.insertBefore(e,before===e?e.nextElementSibling:before);});
  syncSaveBtn();}
// The composer's [핀 저장] reads [다시 저장] while its banner is a failed save (saveBtnLabel), and goes back after.
function syncSaveBtn(){const b=$('#btn-save'); if(!b||b.dataset.pending)return; const n=BANNERS.get(NOTICE_HOST.COMPOSER),retry=!!(n&&n.save);
  if((b.dataset.retry==='1')!==retry){if(retry)b.dataset.retry='1'; else delete b.dataset.retry; setHtml(b,saveBtnLabel());}}
// A composer's banner belongs to its selection: when the composer closes (saved, cancelled), it goes with it.
new MutationObserver(()=>{if($('#composer').hidden){const n=BANNERS.get(NOTICE_HOST.COMPOSER); if(n)endNotice(n,false);}})
  .observe($('#composer'),{attributes:true,attributeFilter:['hidden']});

// Rows in a card's place and notes in a card, after drawPins drew the list. A row waits until its card has left the section
// (away), then goes after the card drawn before it (prev), or first; once its pin is back in that section, what it offers to
// undo is undone and it goes - unless it holds a deferred send, whose card stays out until the send. A note goes above its
// card's buttons (or a done pin's row's end); a note whose card is not drawn moves to the status line (offerToLine).
// focus = what noticeFocus() saw before the redraw.
/** @param {HTMLElement|null} [focus] */
function drawOffers(focus){NOTICES.forEach(n=>{
  if(n.place===NOTICE_PLACE.ROW){const box=n.sec==='review'?$('#review-pins'):$('#pins');
    if(box.querySelector('.pin.card[data-id="'+n.pin+'"]')){if(n.away&&!n.gone)endNotice(n,true); else if(n.el)n.el.remove(); return;}
    n.away=true; if(n.sec==='review')$('#sec-review').hidden=false;   // its last card may just have left (drawPins keeps it shown too)
    const e=noticeEl(n,'nt-row'),prev=n.prev!=null?box.querySelector('.pin.card[data-id="'+n.prev+'"]'):null;
    if(prev)prev.after(e); else box.prepend(e);}
  else if(n.place===NOTICE_PLACE.CARD){const c=document.querySelector('#list .pin.card[data-id="'+n.pin+'"],#list .arc-row[data-id="'+n.pin+'"]');
    if(!c){offerToLine(n); return;}
    const e=noticeEl(n,'nt-note'),acts=c.querySelector(':scope>.acts'); if(acts)acts.before(e); else c.appendChild(e);}});
  noticeRefocus(focus||null);}

// Chips on marks, after marks() drew them: on the pin's mark, kept on its page. A chip whose mark is not drawn (another
// document, a failed reload) moves to the status line - unless it waits for its first reload (pending) - and so does one
// that would sit under the select mode's bar (chipsClearOfBar).
function drawChips(){NOTICES.forEach(n=>{if(n.place!==NOTICE_PLACE.CHIP)return;
  const k=/** @type {HTMLElement|null} */(document.querySelector('.mark[data-pin="'+n.pin+'"]'));
  if(!k){if(!n.pending)offerToLine(n); return;}
  const f=noticeFocus(),e=noticeEl(n,'nt-chip'); if(e.parentNode!==k)k.appendChild(e); e.style.left='';
  const pg=k.closest('.pg'); if(pg){const pr=pg.getBoundingClientRect(),cr=e.getBoundingClientRect(),over=cr.right-(pr.right-4);   // stays on its page
    if(over>0)e.style.left=Math.round(-Math.min(over,cr.left-pr.left-4))+'px';}
  noticeRefocus(f);});
  chipsClearOfBar();}
// Whether two boxes (left, top, right, bottom) overlap by more than a touching edge. Pure.
/** @param {{left:number,top:number,right:number,bottom:number}} a @param {{left:number,top:number,right:number,bottom:number}} b */
function boxesMeet(a,b){return a.left<b.right&&b.left<a.right&&a.top<b.bottom&&b.top<a.bottom;}
// A chip never sits under the select mode's bar (#sel-bar, over the top of the PDF area while the mode is on): one whose box
// meets the bar's - the mode turned on, or the page scrolled the mark up under it - takes its undo to the status line.
function chipsClearOfBar(){const bar=$('#sel-bar'); if(!bar||!bar.getClientRects().length)return; const br=bar.getBoundingClientRect();
  NOTICES.forEach(n=>{if(n.place===NOTICE_PLACE.CHIP&&n.el&&n.el.getClientRects().length&&boxesMeet(n.el.getBoundingClientRect(),br))offerToLine(n);});}
$('#left').addEventListener('scroll',chipsClearOfBar,{passive:true});
new MutationObserver(chipsClearOfBar).observe(document.body,{attributes:true,attributeFilter:['class']});   // body.selmode comes and goes
// The list reload after a save or an append has run: a chip whose mark did not come goes to the status line (drawChips).
/** @param {Notice|null} n */
function settleChip(n){if(!n||!NOTICES.has(n.n)||n.place!==NOTICE_PLACE.CHIP)return; n.pending=false; drawChips();}
// Moves an undo whose place left the screen to the status line, with the same action, what it holds (gone) and life; a TIMER
// one gets a window of its own there.
/** @param {Notice} n */
function offerToLine(n){const act=n.act,gone=n.gone; n.gone=null; endNotice(n,true); if(!act)return;
  const m=lineNote(noticeText(n),NOTICE_KIND.OK,act,{life:n.life,gone,literal:true});
  DEFERRED.forEach(d=>{if(d.note===n)d.note=m;});}   // an early send takes the moved undo away

// Trash rows: an undo in the place of the row it took away (after the row drawn before it, or first). drawTrash calls this.
function drawTrashOffers(){const box=$('#trash-list'); NOTICES.forEach(n=>{if(n.place!==NOTICE_PLACE.TRASH)return;
  const e=noticeEl(n,'nt-row'),prev=n.prev!=null?box.querySelector('.arc-row[data-id="'+n.prev+'"]'):null;
  if(prev)prev.after(e); else box.prepend(e);});}
// Closing the Trash takes its rows' undos to the status line: inside a closed dialog they could no longer be pressed.
$('#trash').addEventListener('close',()=>{NOTICES.forEach(n=>{if(n.place===NOTICE_PLACE.TRASH)offerToLine(n);});});

// Deferred send with an undo (docs/handbook/viewer.md §알림 자리): commit runs when its undo leaves - after NOTICE_MS, on [x],
// or when the page is hidden - and [되돌리기] (cancel) runs undo instead, before anything reaches the server. So an agent never
// sees a reply or a permanent delete that was taken back. note = the undo drawn for it, which an early commit takes away.
const DEFERRED=/** @type {Set<Deferred>} */(new Set());
/** @param {()=>void} commit @param {()=>void} undo @returns {Deferred} */
function deferred(commit,undo){let done=false;
  const d=/** @type {Deferred} */({note:null,
    run:()=>{if(done)return; done=true; DEFERRED.delete(d); if(d.note)endNotice(d.note,true); commit();},
    cancel:()=>{if(done)return; done=true; DEFERRED.delete(d); undo();}});
  DEFERRED.add(d); return d;}
// Draws deferred send d's undo (undoNote, a TIMER life): its end sends, its [되돌리기] cancels. Returns it.
/** @param {Deferred} d @param {string} place @param {string} msg @param {Partial<Notice>} o @returns {Notice} */
function deferredNote(d,place,msg,o){
  const n=undoNote(place,msg,{label:'되돌리기',tip:'보내기 전에 취소합니다',fn:d.cancel},{...o,life:NOTICE_LIFE.TIMER,gone:d.run});
  d.note=n; return n;}
// The page is hidden or closed: what waits is sent now (fetch keepalive), and its undo goes - it could no longer cancel.
function flushDeferred(){Array.from(DEFERRED).forEach(d=>d.run());}
window.addEventListener('pagehide',flushDeferred);
document.addEventListener('visibilitychange',()=>{if(document.hidden)flushDeferred();});
