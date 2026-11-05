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
const NOTICE_HOLD_MAX=30000;   // a hold (a mouse on it, the '+N' list open) stretches a window by at most this: a send always goes
const PV_CHIP_HOLD_MAX=4000;   // ...and a page verdict line's save chip by at most this: a mouse resting by the words kept it up for 30s
const LINE_MAX=5;       // the status line keeps five messages besides its undos (lineCap); its '+N' lists the rest
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
/** @template {{at:number,keys:string[],rank:number}} T @param {T[]} shown @param {string[]} keys @param {number} rank @param {number} now
 * @returns {{skip:boolean,drop:T[]}} */
function noticeDupe(shown,keys,rank,now){const drop=/** @type {T[]} */([]); if(!keys||!keys.length)return {skip:false,drop};
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
    prev:o.prev==null?null:o.prev,rec:o.rec||null,kind:o.kind||NOTICE_KIND.OK,title,desc,label:o.label||'',act:o.act||null,literal:!!o.literal,keys:o.keys||[],
    rank:o.rank||1,at:Date.now(),life:o.life||NOTICE_LIFE.STICKY,dot:o.dot||'',topic:o.topic||'',save:!!o.save,pending:!!o.pending,away:false,
    alert:!!o.alert,busy:false,source:o.source||'',undo:!!o.undo,quiet:!!o.quiet,hover:false,held:false,timer:undefined,gone:o.gone||null,el:null,
    group:o.group||'',keep:!!o.keep,back:!!o.back,dots:o.dots||[],onEnd:o.onEnd||null});
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
// an alert: a banner whose place was not on screen), source (an error's: one entry per source - sourceEntry), undo (it
// offers an undo: lineCap never evicts it). An error is
// always an alert: read out assertively (#sr-alert) and first on the line (statusList). An error from a source that already
// has one replaces it - and when its words are the same it is that one, kept and not said again. Past LINE_MAX the oldest
// information leaves, then the oldest error, never an undo (lineCap). Any other message is read out by the line when it
// shows it, else - another one holds the line - politely (#sr-news).
/** @param {string} msg @param {string} kind @param {NoticeAct|null} [act] @param {Partial<Notice>} [o] @returns {Notice|null} */
function lineNote(msg,kind,act,o){o=o||{}; const keys=o.keys||[],rank=o.rank||1,text=o.literal?String(msg):trMsg(msg);
  if(digestHold(msg,kind,act,o))return null;   // gathered while a person was away (digestBegin): said once, together
  if(o.source){const old=sourceEntry(o.source); if(old){if(old.place===NOTICE_PLACE.LINE&&sameWords(old,text,kind))return old; endNotice(old,true);}}
  if(newsDupe(keys,rank,null))return null;
  const n=makeNotice({...o,msg:o.literal?String(msg):trMsg(msg),kind,act:act||null,place:NOTICE_PLACE.LINE,pending:false,
    alert:kind===NOTICE_KIND.ERR||!!o.alert,dot:noticeDot(o.dot||'',SIDE_OPEN)});
  if(n.back)LINE.push(n); else if(n.group)LINE.splice(newsSlot(),0,n); else LINE.unshift(n);   // news: behind the undos (newsSlot); another document's behind all (updates.js)
  lineCap();
  if(n.dot)document.body.classList.add('dot-'+n.dot);
  drawStatus(); armNotice(n);
  if(n.alert)announce(noticeText(n),true); else if(STATUS_TOP!==n.n&&!n.quiet)announce(noticeText(n));
  return n;}
// The line's cap (rule 2): it keeps LINE_MAX messages besides its undos and what must stay (keep: a document's update, a
// gathered line). Past that the oldest piece of information leaves, then the oldest error - oldest by when it came (at), as
// news may stand behind older messages (newsSlot, back) - never the newest message, and never an undo, which leaves only by
// its window, its [되돌리기] or its [x] (an evicted deferred send would go early).
function lineCap(){for(;;){const kept=LINE.filter(n=>!isUndo(n)&&!n.keep); if(kept.length<=LINE_MAX)return;
  const rest=kept.filter(n=>n!==LINE[0]),oldest=(/** @type {Notice[]} */a)=>a.reduce((/** @type {Notice|null} */m,x)=>!m||x.at<=m.at?x:m,null);
  endNotice(/** @type {Notice} */(oldest(rest.filter(n=>!n.alert))||oldest(rest)),false);}}
// Whether message n offers an undo: made as one (undoNote, a discarded selection) or holding a deferred send (gone).
/** @param {Notice} n @returns {boolean} */
function isUndo(n){return n.undo||!!n.gone;}
// Whether message n already says text (its title and description, as msgSplit cuts it) as kind.
/** @param {Notice} n @param {string} text @param {string} kind @returns {boolean} */
function sameWords(n,text,kind){const [t,d]=msgSplit(text); return n.kind===kind&&n.title===t&&n.desc===d;}
// The message an error source has standing (one at most - a repeat replaces it), or null. A source is a request (its method
// and URL, which names its pin and document, with what it asks of that URL - api()'s intent) or a named one.
/** @param {string} source @returns {Notice|null} */
function sourceEntry(source){for(const n of NOTICES.values())if(n.source===source)return n; return null;}
// Source succeeded - its request was answered, or a build of its document came: its error is no longer true and goes.
/** @param {string} source */
function sourceOk(source){if(source)NOTICES.forEach(n=>{if(n.source===source)endNotice(n,true);});}

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
  const text=o.literal?String(msg):trMsg(msg);   // a source's repeat in the same words is the banner already there: not drawn or said again
  if(o.source){const same=sourceEntry(o.source); if(same){if(same.place===NOTICE_PLACE.BANNER&&same.host===h&&sameWords(same,text,kind))return same; endNotice(same,true);}}
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
    return /** @type {Notice} */(lineNote(msg,NOTICE_KIND.OK,a,{...o,life,undo:true}));   // no keys: never suppressed
  const n=makeNotice({...o,life,undo:true,msg:trMsg(msg),kind:NOTICE_KIND.OK,act:a,place});
  // One save chip on the pages at a time, the newest: an earlier one takes its undo to the status line (offerToLine), as a
  // chip whose mark went does - several pages each showing a chip read as several things to answer.
  if(place===NOTICE_PLACE.CHIP)[...NOTICES.values()].filter(x=>x!==n&&x.place===NOTICE_PLACE.CHIP).forEach(offerToLine);
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

// Starts (or restarts) a message's life: a TIMER one ends after NOTICE_MS. While it is held (noticeHeld: a mouse on it, or
// for one on the status line the line held) its window waits, and starts from the start again when the hold ends, as the
// toast did - but a hold never stretches it past NOTICE_HOLD_MAX beyond its first window, so no hold can keep it (and a
// send it holds) forever. Not held by the focus, which a reply sent with Ctrl+Enter puts on its [되돌리기], so the send would
// wait for the focus to move; stopped while its action's request is out (busy, noticeAct). CLICK and STICKY ones wait for
// the press listener below, [x] or their action.
/** @param {Notice} n */
function armNotice(n){if(n.life!==NOTICE_LIFE.TIMER)return; clearTimeout(n.timer); n.timer=undefined; n.held=false; if(n.busy)return;
  const line=n.place===NOTICE_PLACE.CHIP&&!!n.el&&!!n.el.parentElement&&n.el.parentElement.classList.contains('pv');
  const left=n.at+NOTICE_MS+(line?PV_CHIP_HOLD_MAX:NOTICE_HOLD_MAX)-Date.now(); n.held=noticeHeld(n);
  n.timer=setTimeout(()=>{const back=noticeFocusBack(n,true); endNotice(n,false); back();},Math.max(0,n.held?left:Math.min(NOTICE_MS,left)));}
// Whether message n's window is held now: one on the status line while the line is (lineHeld); one drawn in place while a
// mouse is on its element - still in the page and under the pointer, so no hold outlives what was hovered.
/** @param {Notice} n @returns {boolean} */
function noticeHeld(n){if(n.place===NOTICE_PLACE.LINE)return lineHeld(); return n.hover&&!!n.el&&n.el.isConnected&&n.el.matches(':hover');}
// The status line holds its messages' windows while a mouse is on it (LINE_HOVER) or its '+N' list is open: what it shows
// there is being read. The hover ends however the pointer leaves - out of the line, cancelled, out of the window - and when
// the line hides or loses a message (lineVisible, endNotice): a hold never outlives the thing hovered. holdLine stops the
// windows (bounded, armNotice); releaseLine starts each held one again once nothing holds.
let LINE_HOVER=false;
function lineHeld(){return LINE_HOVER||$('#status-list').open;}
function holdLine(){LINE.forEach(n=>{if(n.life===NOTICE_LIFE.TIMER&&!n.held)armNotice(n);});}
function releaseLine(){LINE.forEach(n=>{if(n.held)armNotice(n);});}
// A mouse moves over the line: the hover starts with a real movement (realMove), never with the line drawn under a resting
// pointer - that would hold every undo appearing there. A touch never holds: its pointer leaves as it lifts.
/** @param {{pointerType?:string,movementX?:number,movementY?:number,clientX?:number,clientY?:number}} e */
function lineHoverIn(e){if(LINE_HOVER||!e||!realMove(e))return; LINE_HOVER=true; holdLine();}
// The pointer's position at the last move the page saw (document pointermove, after the element's own listener has run).
let PT_LAST=/** @type {{x:number,y:number}|null} */(null);
// Whether pointer move e is a mouse really moving: a non-zero delta, by its own movement or against the last position seen.
// A move the browser makes up under a resting pointer when the page changes under it has neither, so a message drawn under
// a still pointer is not hovered until the mouse moves over it.
/** @param {{pointerType?:string,movementX?:number,movementY?:number,clientX?:number,clientY?:number}} e @returns {boolean} */
function realMove(e){if(e.pointerType!=='mouse')return false; if(e.movementX||e.movementY)return true;
  const p=PT_LAST; return !!p&&(p.x!==e.clientX||p.y!==e.clientY);}
document.addEventListener('pointermove',e=>{PT_LAST={x:e.clientX,y:e.clientY};},{passive:true});
// The pointer is off the line, for whatever reason: the hover ends and the windows run again.
function lineHoverOut(){if(!LINE_HOVER)return; LINE_HOVER=false; releaseLine();}
// The line shows (drawStatus) or hides: hidden - nothing to show, or moved to another band - it holds nothing.
/** @param {boolean} shown */
function lineVisible(shown){if(!shown)lineHoverOut();}
$('#status').addEventListener('pointermove',lineHoverIn,{passive:true});
for(const t of ['pointerleave','pointercancel'])$('#status').addEventListener(t,lineHoverOut);
document.addEventListener('pointerout',e=>{if(!e.relatedTarget)lineHoverOut();});   // out of the window
window.addEventListener('blur',lineHoverOut);
$('#status-list').addEventListener('close',releaseLine);

// Takes a message away from its store and the screen. acted = its own action ended it: gone does not run (the action replaces
// it). acted or seen ([x]) = the person has read it: its dot goes unless another message still holds it (dotHeld). One
// leaving the line ends the line's hover (lineHoverOut). Idempotent.
/** @param {Notice} n @param {boolean} acted @param {boolean} [seen] */
function endNotice(n,acted,seen){if(!NOTICES.has(n.n))return; NOTICES.delete(n.n); clearTimeout(n.timer); n.held=false;
  const li=LINE.indexOf(n); if(li>=0){LINE.splice(li,1); lineHoverOut();}
  if(n.place===NOTICE_PLACE.BANNER&&BANNERS.get(n.host)===n)BANNERS.delete(n.host);
  if(n.el)n.el.remove();
  if(n.place===NOTICE_PLACE.ROW)dropBareDayLines();   // a day line drawn for this row alone goes with it
  if(acted||seen)noticeDots(n).forEach(d=>{if(!dotHeld(d))document.body.classList.remove('dot-'+d);});
  const grp=n.group?GROUPS.get(n.group):undefined; if(grp&&grp.n===n)GROUPS.delete(n.group);
  if(n.place===NOTICE_PLACE.LINE)drawStatus(); if(n.place===NOTICE_PLACE.BANNER){syncSaveBtn(); tipFollow();}   // what was under it moved up
  if(n.onEnd){const f=n.onEnd; n.onEnd=null; f(acted,!!seen);}
  if(!acted&&n.gone){const g=n.gone; n.gone=null; g();}}
// The chips message n marks: its dot, or a gathered message's dots (digestEnd). Pure.
/** @param {Notice} n @returns {string[]} */
function noticeDots(n){return n.dots&&n.dots.length?n.dots:n.dot?[n.dot]:[];}
/** @param {Notice} n @param {string} d @returns {boolean} */
function holdsDot(n,d){return noticeDots(n).includes(d);}
// Whether a message still marks chip d: one on the line (a gathered line by what it holds), or one being gathered (DIGEST),
// whose dot went on as it was gathered (digestHold) and stays until it is said or seen.
/** @param {string} d @returns {boolean} */
function dotHeld(d){return LINE.some(x=>holdsDot(x,d))||!!DIGEST&&digestDots([...DIGEST.items.values()]).includes(d);}

// Read before message n goes. A button of it with the focus goes with it, and what is returned, called once it has gone, finds
// the focus a place: on a document with page lines the line of the page the button was on (a chip's) or the reading page's, else
// the pages - never nothing, so Tab goes on from there and not from the top of the page. Called where nothing took the focus
// meanwhile; a press with a reason being typed leaves it in its field (noticeAct). With a card's editor or reply open it is left
// out of the pages: there a digit is the pages' verdict key (verdictKey shuts them for a focus outside the pages), and a person
// in the middle of a reply did not ask for that. anyDoc: on a document without page lines too. An action's press goes without
// it, for the action may put the focus where it wants; the window's end and [x] have no action.
/** @param {Notice} n @param {boolean} [anyDoc] @returns {()=>void} */
function noticeFocusBack(n,anyDoc){const f=/** @type {HTMLElement|null} */(document.activeElement);
  const own=!!f&&!!f.closest&&!!f.closest('[data-act^="notice-"][data-n="'+n.n+'"]');
  const l=own&&f?/** @type {HTMLElement|null} */(f.closest('#doc .pv')):null,page=l?Number(l.dataset.page)||0:0;
  return ()=>{const g=document.activeElement; if(!own||(g&&g!==document.body)||EDITOR.current||REPLY)return; const lines=!!pageVerdictsOn();
    if(lines?!pvFocusLine(page||PV_READ):anyDoc)searchToPage();};}
// How long an action's request may go unanswered before its message says so (noticeLate) - the bound a page line's
// take-back has too (verdict.js PV_DROP_WAIT). A let: the tests shorten it.
let NOTICE_ACT_WAIT=8000;
// [되돌리기], [다시 시도], [보기]… on message num: the message goes and its action runs. An action that sends a request
// (act.wait: restoring, undoing a close, a delete, a save or an append) keeps its message, busy and with its window stopped,
// until the request is answered (rule 1: not cleared as if it had worked) - a failure then says itself where it can be seen.
// Past NOTICE_ACT_WAIT without an answer the message says the answer is late (noticeLate); the answer, whenever it comes,
// is still taken once. A late one leaves the focus the person has put somewhere since the press (a focusin anywhere but the
// message's own button: a redraw giving the focus back to that button, or the focus falling to nothing as the button goes -
// the action's own redraw may take it away before its answer resolves - is not a move): then back() does not run, and the
// action is told (run.away(), save.js) so that it takes no focus either.
/** @param {number} num */
function noticeAct(num){const n=NOTICES.get(num); if(!n||n.busy)return; const a=n.act;
  if(a&&a.stay){a.fn(); return;}   // an action that leaves the message standing (the next changed place, updates.js)
  const back=noticeFocusBack(n);
  if(!a||!a.wait){endNotice(n,true); if(a)a.fn(); back(); return;}
  n.busy=true; clearTimeout(n.timer); n.timer=undefined; n.held=false;
  document.querySelectorAll('[data-act="notice-act"][data-n="'+n.n+'"]').forEach(b=>b.setAttribute('aria-busy','true'));
  let late=false,moved=false; const wait=setTimeout(()=>{late=true; noticeLate(n,a);},NOTICE_ACT_WAIT);
  const seen=(/** @type {FocusEvent} */e)=>{const t=/** @type {HTMLElement|null} */(e.target); if(!t||!t.closest||!t.closest('[data-act="notice-act"][data-n="'+n.n+'"]'))moved=true;};
  document.addEventListener('focusin',seen,true);
  /** @type {NoticeRun} */ const run={away:()=>late&&moved};
  Promise.resolve(a.fn(run)).catch(()=>false).then(()=>{clearTimeout(wait); document.removeEventListener('focusin',seen,true);
    endNotice(n,true); sourceOk(NOTICE_LATE_SRC+n.n); if(!run.away())back();});}
// noticeAct's question for an action run without its watch - a failure's [다시 시도], which is no waiting action, running an
// undo again (save.js): away() = its answer is late (NOTICE_ACT_WAIT) and the person has put the focus somewhere since. The
// watch starts once the press's own work is done (its message going, back()), so the focus that work moves is not counted.
/** @returns {NoticeRun&{stop:()=>void}} */
function focusRun(){const at=Date.now(); let moved=false,on=true; const seen=()=>{moved=true;};
  queueMicrotask(()=>{if(on)document.addEventListener('focusin',seen,true);});
  return {away:()=>moved&&Date.now()-at>=NOTICE_ACT_WAIT,stop:()=>{on=false; document.removeEventListener('focusin',seen,true);}};}
// The source of the status line's message that says message n's answer is late, when n is not on the line (noticeLate).
const NOTICE_LATE_SRC='notice-late:';
// Message n's action a has sent a request that is not answered after NOTICE_ACT_WAIT: '되돌리기의 답이 늦습니다' (a 되살리기's
// says so) goes before all the message said ('되돌리기의 답이 늦습니다 · #12 채택 판정 저장됨 · …'). It is one title with no
// description: a line too narrow for a long text shows a message's title alone (drawStatus), which as the late words alone
// lost what was being undone and drew the line narrower; whole, the target follows the late words and only the end is
// cut. On the status line the message itself says it, first on the line again (newest) and as a warning: a message whose
// busy button has the focus keeps the line (drawStatus), so a message of its own would wait behind '+N'. Elsewhere - a
// chip, a row, the Trash, or the message gone by its [x] - the status line says it in one message of its own
// (NOTICE_LATE_SRC), which goes with the answer as the message does (noticeAct). Either way one message per action:
// nothing is said twice. The line is not locked meanwhile, so there is nothing to give back.
/** @param {Notice} n @param {NoticeAct} a */
function noticeLate(n,a){const what=tr(a.label==='되살리기'?'되살리기의 답이 늦습니다':'되돌리기의 답이 늦습니다')+' · '+noticeText(n);   // every action that waits is one of the two
  const i=n.place===NOTICE_PLACE.LINE&&NOTICES.has(n.n)?LINE.indexOf(n):-1;
  if(i<0){const m=lineNote(what,NOTICE_KIND.WARN,null,{literal:true,source:NOTICE_LATE_SRC+n.n}); if(m){m.title=what; m.desc=''; drawStatus();} return;}   // lineNote cuts at ' · '
  n.title=what; n.desc=''; n.kind=NOTICE_KIND.WARN; n.quiet=false; LINE.splice(i,1); LINE.unshift(n);
  drawStatus(); if(n.alert)announce(noticeText(n),true); else if(STATUS_TOP!==n.n)announce(noticeText(n));}   // as lineNote reads one out
// A press on a message's action does not take the focus from the reason field being typed in: its button goes with the message, and
// the keys typed next would be verdict keys.
document.addEventListener('mousedown',e=>{const t=/** @type {HTMLElement|null} */(e.target); if(!!t&&!!t.closest&&!!t.closest('[data-act="notice-act"]')&&pvIsReasonField(document.activeElement))e.preventDefault();},true);
// [x] on message num: it goes as read (with its dot), and what it held runs (gone: a deferred send goes now).
/** @param {number} num */
function noticeClose(num){const n=NOTICES.get(num); if(!n)return; const back=noticeFocusBack(n,true); endNotice(n,false,true); back();}
// A hint goes once the person does what it says (NOTICE_TOPIC.PICK: a selection was made; SIDE: the panel was opened).
/** @param {string} topic */
function endTopic(topic){NOTICES.forEach(n=>{if(n.topic===topic)endNotice(n,false,true);});}
// The person looks where a dot points (the panel opened, the review section gone to): that dot goes, with the panel open the
// hint on how to open it, and with the review section the messages about pins sent to review (seen) - on the line and
// folded in a gathered line (foldedGone), which [펼치기] would otherwise put back with the dot.
/** @param {string} dot */
function noticeSeen(dot){if(dot===NOTICE_DOT.RV){LINE.slice().forEach(n=>{if(reviewPins(n.keys).length)endNotice(n,false,true);});
    foldedNews().forEach(f=>{if(reviewPins(f.keys).length)foldedGone(f,true);}); gatheredGone(o=>reviewPins(o.keys||[]).length>0);}
  document.body.classList.remove('dot-'+dot); if(dot===NOTICE_DOT.SIDE)endTopic(NOTICE_TOPIC.SIDE);}
// The gathering under way (DIGEST) loses the messages test picks (by their options), as seen: never said - their groups
// go with them when no message of theirs stands, and what each held for its end runs, as for a message seen on the line.
/** @param {(o:any)=>boolean} test */
function gatheredGone(test){if(!DIGEST)return; for(const [g,a] of [...DIGEST.items]){const o=a[3]||{}; if(!test(o))continue;
  DIGEST.items.delete(g); const h=GROUPS.get(g); if(h&&!(h.n&&NOTICES.has(h.n.n)))GROUPS.delete(g); if(o.onEnd)o.onEnd(false,true);}}
// The pins a message's keys say were sent to review ('review_requested:<id>', noticeDupe's keys). Pure.
/** @param {string[]} keys @returns {number[]} */
function reviewPins(keys){const p=EVENT_TYPE.REVIEW_REQUESTED+':'; return keys.filter(k=>k.startsWith(p)).map(k=>Number(k.slice(p.length)));}
// Whether a message about pins sent to review is stale: it names some, and none of them awaits review any more (confirmed,
// reopened or deleted - here or elsewhere). inReview = the ids awaiting review. Pure.
/** @param {string[]} keys @param {number[]} inReview @returns {boolean} */
function reviewNewsStale(keys,inReview){const ids=reviewPins(keys); return ids.length>0&&!ids.some(i=>inReview.includes(i));}
// Each time the list is drawn (drawPins: after a reload, a confirm): the stale review arrivals go (reviewNewsStale) - on the
// line, folded in a gathered line (foldedGone: the line then says, and marks, what is left) and in a gathering still under
// way (DIGEST) - and [검토 M]'s dot - on the collapsed desktop's [핀 N] too - once no message on the line or gathered holds
// it (dotHeld).
function dropStaleReview(){const ids=REVIEW_ALL.map(p=>p.id); LINE.slice().forEach(n=>{if(reviewNewsStale(n.keys,ids))endNotice(n,false,true);});
  foldedNews().forEach(f=>{if(reviewNewsStale(f.keys,ids))foldedGone(f,true);});
  gatheredGone(o=>reviewNewsStale(o.keys||[],ids));   // still being gathered (the return's poll said it before the list came)
  if(!dotHeld(NOTICE_DOT.RV))document.body.classList.remove('dot-'+NOTICE_DOT.RV);}

// ---------------- Messages that gather (docs/handbook/viewer.md §새 소식)
// One status-line message per group ('new:<doc>', 'done', 'upd:<doc>'…): a new event of a group whose message still stands
// merges into it - merge(old data, new data) gives the whole - and the message says the whole again in place, as the newest
// on the line, its window (a passing one's) starting again. view(data) gives what it says: {msg, kind, act, o}. A group held
// by a gathering (digestHold) or by a gathered message not yet unfolded (digestTake) merges the same way, so twelve pins
// closed one by one are one message, never twelve.
// The same event on two paths is said once per event, not per message (noticeDupe's keys): less(data, keys) - given by a
// group whose message carries keys - is its data without the events of those keys, or null when none is left. Events a
// message of a higher rank already says are left out of what a group says (keysHeld); and when such a message comes later,
// it takes its events out of the group's message, which says the rest in place (noticeLess) - the others stay. Such a
// message coming by growing its own group's message does the same, and a group's message folded in a gathered line not yet
// unfolded, or still being gathered, gives way as one on the line does (newsDupe, foldedLess, gatheredLess).
/** @typedef {(d:any)=>{msg:string,kind:string,act:NoticeAct|null,o:Partial<Notice>}} GroupView */
/** @typedef {(d:any,keys:string[])=>any} GroupLess */
const GROUPS=/** @type {Map<string,{data:any,n:Notice|null,view:GroupView,less:GroupLess|null}>} */(new Map());
/** @param {string} group @param {any} data @param {GroupView} view @param {((a:any,b:any)=>any)|null} [merge]
 * @param {GroupLess|null} [less] @returns {Notice|null} */
function groupNote(group,data,view,merge,less){const g=GROUPS.get(group);
  if(less){const o=view(data).o||{},held=keysHeld(o.keys||[],o.rank||1); if(held.length){data=less(data,held); if(data==null)return g&&g.n&&NOTICES.has(g.n.n)?g.n:null;}}
  const alive=!!g&&(!!g.n&&NOTICES.has(g.n.n)&&!g.n.busy||!!DIGEST&&DIGEST.items.has(group)||digestTake(group));
  const d=alive&&g&&merge?merge(g.data,data):data,v=view(d);
  if(alive&&g&&g.n&&NOTICES.has(g.n.n)){const o=view(data).o||{}; newsDupe(o.keys||[],o.rank||1,g.n);   // what this event says, said elsewhere
    g.data=d; g.view=view; g.less=less||null; regroup(g.n,v); return g.n;}
  GROUPS.set(group,{data:d,n:null,view,less:less||null});
  const n=lineNote(v.msg,v.kind,v.act,{...v.o,group}); const h=GROUPS.get(group); if(h&&n)h.n=n; return n;}
// The keys among keys that a message of a higher rank than rank already says: one on the line or folded in a gathered line
// (foldedNews), younger than noticeDupe's window, or one gathered (DIGEST).
/** @param {string[]} keys @param {number} rank @returns {string[]} */
function keysHeld(keys,rank){const now=Date.now(),gathered=DIGEST?[...DIGEST.items.values()].map(a=>a[3]||{}).filter(o=>(o.rank||1)>rank):[],folded=foldedNews();
  return keys.filter(k=>noticeDupe(LINE,[k],rank,now).skip||noticeDupe(folded,[k],rank,now).skip||gathered.some(o=>(o.keys||[]).includes(k)));}
// A message of rank that says the events of keys comes (lineNote), or a group's message grows by them (groupNote; except:
// that message): whether one of a higher rank says them all already - on the line, folded in a gathered line not yet
// unfolded (foldedNews) or in the gathering under way (gatheredDupe) - so it is not said again (noticeDupe's skip); else
// each of a lower rank that says some of them gives way (its drop): it says the rest in place (noticeLess, foldedLess,
// gatheredLess) or goes.
/** @param {string[]} keys @param {number} rank @param {Notice|null} except @returns {boolean} */
function newsDupe(keys,rank,except){const now=Date.now(),line=noticeDupe(LINE.filter(x=>x!==except),keys,rank,now),fold=noticeDupe(foldedNews(),keys,rank,now),
    dig=gatheredDupe(keys,rank,except?except.group:'');
  if(line.skip||fold.skip||dig.skip)return true;
  line.drop.forEach(x=>noticeLess(x,keys)); fold.drop.forEach(f=>foldedLess(f,keys)); dig.drop.forEach(g=>gatheredLess(g,keys)); return false;}
// The gathering under way (DIGEST) as noticeDupe compares the line - a gathering is shorter than its window: skip when a
// gathered message of a higher rank says every one of keys; else drop names each gathered group of a lower rank that says
// some of them. except: the group of the message that says keys. Pure but for DIGEST.
/** @param {string[]} keys @param {number} rank @param {string} except @returns {{skip:boolean,drop:string[]}} */
function gatheredDupe(keys,rank,except){const drop=/** @type {string[]} */([]); if(!DIGEST||!keys.length)return {skip:false,drop};
  for(const [g,a] of DIGEST.items){const x=a[3]||{},xk=x.keys||[],xr=x.rank||1; if(g===except||!keys.some(k=>xk.includes(k)))continue;
    if(xr>rank&&keys.every(k=>xk.includes(k)))return {skip:true,drop:[]};
    if(rank>xr)drop.push(g);}
  return {skip:false,drop};}
// Gathered group g gives way to a message of a higher rank that says the events of keys, as noticeLess on the line: a group
// that can leave them out (less) stays gathered with the rest; with nothing left, or a group that cannot, it leaves the
// gathering, never said - its group with it, and what it held for its end runs, as for a folded message (foldedGone).
/** @param {string} g @param {string[]} keys */
function gatheredLess(g,keys){const d=DIGEST,a=d?d.items.get(g):undefined; if(!d||!a)return;
  const gr=GROUPS.get(g),rest=gr&&gr.less?gr.less(gr.data,keys):null;
  if(!gr||rest==null){const o=a[3]||{}; d.items.delete(g); if(gr&&!(gr.n&&NOTICES.has(gr.n.n)))GROUPS.delete(g); if(o.onEnd)o.onEnd(false,false); return;}
  gr.data=rest; const v=gr.view(rest); d.items.set(g,[v.msg,v.kind,v.act,{...v.o,group:g}]);}
// Group's message says its data again wherever it stands - on the line (regroup), gathered (DIGEST) or folded in a gathered
// line not yet unfolded (which then says what it holds, digestRetitle) - for what its view reads besides its data (a
// document's moved pins and changed lines, updates.js). Whether it stands anywhere.
/** @param {string} group @returns {boolean} */
function groupRedraw(group){const g=GROUPS.get(group); if(!g)return false;
  if(g.n&&NOTICES.has(g.n.n)){regroup(g.n,g.view(g.data)); return true;}
  const v=g.view(g.data),item=[v.msg,v.kind,v.act,{...v.o,group}];
  if(DIGEST&&DIGEST.items.has(group)){DIGEST.items.set(group,item); return true;}
  const f=foldedNews().find(x=>(x.item[3]||{}).group===group),items=f?f.line.items||[]:[],i=f?items.indexOf(f.item):-1;
  if(!f||i<0)return false;
  items[i]=item; digestRetitle(f.line); return true;}
// The messages gathered lines not yet unfolded hold (digestNote's items), as noticeDupe compares them: each with its keys
// and rank, as old as its gathered line (at), and where it is held (line, item).
/** @returns {{at:number,keys:string[],rank:number,line:Notice,item:any[]}[]} */
function foldedNews(){return LINE.flatMap(n=>(n.items||[]).map(a=>{const o=a[3]||{}; return {at:n.at,keys:o.keys||[],rank:o.rank||1,line:n,item:a};}));}
// Folded message f gives way to a message of a higher rank that says the events of keys, as noticeLess on the line: its
// group that can leave them out (less) says the rest in the gathered line; with nothing left, or a group that cannot, it
// leaves the gathered line, not seen (foldedGone). The line says what is left (digestRetitle).
/** @param {{line:Notice,item:any[]}} f @param {string[]} keys */
function foldedLess(f,keys){const items=f.line.items||[],i=items.indexOf(f.item),o=f.item[3]||{},g=o.group?GROUPS.get(o.group):undefined; if(i<0)return;
  const rest=g&&g.less?g.less(g.data,keys):null;
  if(!g||rest==null){foldedGone(f,false); return;}
  g.data=rest; const v=g.view(rest); items[i]=[v.msg,v.kind,v.act,{...v.o,group:o.group}]; digestRetitle(f.line);}
// Folded message f leaves its gathered line, as a message leaving the line does: its group ends with it, what it held for
// its end runs (seen: as read - a review request whose pins left review, or the review section seen), and the line says
// and marks what is left (digestRetitle).
/** @param {{line:Notice,item:any[]}} f @param {boolean} seen */
function foldedGone(f,seen){const items=f.line.items||[],i=items.indexOf(f.item),o=f.item[3]||{},g=o.group?GROUPS.get(o.group):undefined; if(i<0)return;
  items.splice(i,1); if(g&&!(g.n&&NOTICES.has(g.n.n)))GROUPS.delete(o.group); if(o.onEnd)o.onEnd(false,seen);
  digestRetitle(f.line);}
// Message x gives way to a message of a higher rank that says the events of keys (noticeDupe's drop): a group's message
// that can leave them out (less) says the rest in place - not as news again: neither moved, nor read out, nor its window
// started again - and one with nothing left, or that cannot, goes.
/** @param {Notice} x @param {string[]} keys */
function noticeLess(x,keys){const g=x.group?GROUPS.get(x.group):undefined,rest=g&&g.n===x&&g.less?g.less(g.data,keys):null;
  if(!g||rest==null){endNotice(x,false); return;}
  g.data=rest; regroup(x,g.view(rest),true);}
// Where news (a message of a group) stands on the line: right behind the last undo still standing - an undo lives its window
// where it can be pressed (rule 2), and news arriving meanwhile must not hide it behind '+N' - else first.
/** @returns {number} */
function newsSlot(){let i=0; LINE.forEach((x,j)=>{if(isUndo(x))i=j+1;}); return i;}
// Message n says view v now (groupNote): its words, kind, action, keys and dot, as the newest on the line, read out again
// (politely, unless quiet) when its words changed - by the line's own live region (.st-sr, drawStatus) when the line shows
// it, else by #sr-news, never by both, as lineNote reads a first message - and a passing one's window starts again.
// still: it says less than before (noticeLess) and stays where it is, its window running on, not read out.
/** @param {Notice} n @param {{msg:string,kind:string,act:NoticeAct|null,o:Partial<Notice>}} v @param {boolean} [still] */
function regroup(n,v,still){const o=v.o||{},[t,d]=msgSplit(o.literal?String(v.msg):trMsg(v.msg));
  const same=n.title===t&&n.desc===d&&n.kind===v.kind; n.title=t; n.desc=d; n.kind=v.kind; n.act=v.act||null; if(!still)n.at=Date.now();
  if(o.keys)n.keys=o.keys; if(o.onEnd)n.onEnd=o.onEnd; if(o.life)n.life=o.life; n.back=!!o.back;
  const dot=noticeDot(o.dot||'',SIDE_OPEN); if(dot){n.dot=dot; document.body.classList.add('dot-'+dot);}
  const i=LINE.indexOf(n); if(i>=0&&!n.back&&!still){LINE.splice(i,1); LINE.splice(newsSlot(),0,n);}
  STATUS_SIG=''; drawStatus(); if(still)return; armNotice(n);
  if(!same&&!o.quiet&&STATUS_TOP!==n.n)announce(noticeText(n));}

// ---------------- Gathering while a person was away (docs/handbook/viewer.md §새 소식)
// Back after a while (the tab hidden or the device asleep, polling.js) or opening the viewer again (boot), what the first
// polls say is gathered for a moment (digestBegin … digestEnd) and said as one message: '자리를 비운 사이 (38분) — 본문이
// 바뀌었습니다 · 나를 부름 2 · 검토 대기 3', with [펼치기], which puts each on the line as it would have come. One gathered
// thing alone is said as itself. Only news is gathered - a message of a group (groupNote: a document's update, new pins, an
// event addressed to me, the list comparison) - and its dots are put on at once. The screen's own messages (a restored draft,
// a hint), an error, an undo, a message with an error source or one that asks not to (digest:false) are said as they come -
// an error where it can be seen now (rule 1).
let DIGEST=/** @type {{title:string,items:Map<string,any[]>,timer:ReturnType<typeof setTimeout>|undefined}|null} */(null);
const DIGEST_MAX_MS=8000;   // a gathering never lasts longer than this, whatever it waits for
/** @param {string} title */
function digestBegin(title){if(DIGEST)return; DIGEST={title,items:new Map(),timer:setTimeout(digestEnd,DIGEST_MAX_MS)};}
// Ends the gathering ms from now (at once without ms): what the first poll set going has come by then.
/** @param {number} [ms] */
function digestSoon(ms){const d=DIGEST; if(!d)return; clearTimeout(d.timer); d.timer=setTimeout(digestEnd,ms||0);}
/** @param {string} msg @param {string} kind @param {NoticeAct|null|undefined} act @param {Partial<Notice>} o @returns {boolean} */
function digestHold(msg,kind,act,o){const d=DIGEST; if(!d||!o.group||o.digest===false||o.undo||o.gone||o.source||o.alert||kind===NOTICE_KIND.ERR)return false;
  // one event on two paths is gathered once, as the line shows it once (noticeDupe): the event path wins over the list's
  // - per event: a gathered group that can leave the events out (less) keeps the rest (gatheredLess)
  const keys=o.keys||[],dup=gatheredDupe(keys,o.rank||1,o.group); if(dup.skip)return true; dup.drop.forEach(g=>gatheredLess(g,keys));
  d.items.set(o.group,[msg,kind,act,o]); const dot=noticeDot(o.dot||'',SIDE_OPEN); if(dot)document.body.classList.add('dot-'+dot); return true;}
// The gathering ends: nothing, the one thing as itself, or one message for all of them (digestNote) - behind what the line
// says already (back): what came meanwhile never takes the line from an undo or a hint the screen itself put there.
function digestEnd(){const d=DIGEST; if(!d)return; DIGEST=null; clearTimeout(d.timer); const items=[...d.items.values()];
  if(items.length===1)digestReplay(items[0],true); else if(items.length)digestNote(d.title,items);}
// The words a gathered message is named by in the gathered line: its brief (o.brief), else its title. Pure.
/** @param {any[]} a @returns {string} */
function digestBrief(a){const o=a[3]||{}; return o.brief||msgSplit(o.literal?String(a[0]):trMsg(a[0]))[0];}
// The gathered line's description: each brief once, in the order they came, with how many - a brief that ends in a count
// ('새 핀 1', one per document) adds its count up ('새 핀 2'), any other counts how many said it ('나를 부름 2'). Pure.
/** @param {string[]} briefs @returns {string} */
function digestLine(briefs){const seen=new Map();
  briefs.forEach(b=>{const m=/^(.*\S) (\d+)$/.exec(b),k=m?m[1]:b,n=m?+m[2]:1,was=seen.get(k); seen.set(k,{n:(was?was.n:0)+n,counted:!!m||(was?was.counted:false)});});
  return [...seen].map(([b,v])=>v.n>1||v.counted?b+' '+v.n:b).join(' · ');}
/** @param {string} title @param {any[][]} items */
function digestNote(title,items){items=[...items.filter(a=>!(a[3]||{}).back),...items.filter(a=>!!(a[3]||{}).back)];   // this document's news first
  const dots=digestDots(items);
  const n=lineNote(title+' — '+digestLine(items.map(digestBrief)),NOTICE_KIND.INFO,
    {label:'펼치기',tip:'모은 소식을 하나씩 상태 줄에 놓습니다',fn:()=>{const all=n?n.items||[]:[]; all.forEach(a=>digestReplay(a,false)); if(all.length>1&&!$('#status-list').open)toggleStatusList();}},
    {literal:true,keep:true,back:true,dots,digest:false,onEnd:(acted,seen)=>{if(!acted&&n)digestClosed(n.items||[],seen);}});
  if(n){n.items=items; n.digestTitle=title;}}
// A gathered line went other than by [펼치기] (its [x]: seen): the groups it held end with it - each of their messages has
// gone, so what a group's end checks (no other new-pins message, updates.js) sees them gone - and then what each held for
// its end runs, as seen.
/** @param {any[][]} items @param {boolean} seen */
function digestClosed(items,seen){items.forEach(a=>{const g=(a[3]||{}).group,h=g?GROUPS.get(g):undefined; if(h&&!(h.n&&NOTICES.has(h.n.n)))GROUPS.delete(g);});
  items.forEach(a=>{const f=(a[3]||{}).onEnd; if(f)f(false,seen);});}
// Puts gathered message a on the line as it would have come - behind what the line says (back), or, unfolded by [펼치기], in
// front; a group's message is that group's again.
/** @param {any[]} a @param {boolean} back */
function digestReplay(a,back){const o=a[3]||{},n=lineNote(a[0],a[1],a[2],{...o,digest:false,back:back||!!o.back}); const g=o.group&&GROUPS.get(o.group); if(g&&n)g.n=n;}
// Takes group's gathered message out of a gathered line not yet unfolded, so the group's new event merges into it and is
// said on its own (groupNote); the line says what is left. Whether there was one.
/** @param {string} group @returns {boolean} */
function digestTake(group){for(const n of NOTICES.values()){const items=n.items; if(!items)continue; const i=items.findIndex(a=>(a[3]||{}).group===group); if(i<0)continue;
    items.splice(i,1); digestRetitle(n); return true;}
  return false;}
// The chips the gathered messages items mark (digestNote's dots): each one's dot once. Pure but for SIDE_OPEN.
/** @param {any[][]} items @returns {string[]} */
function digestDots(items){return [...new Set(items.map(a=>noticeDot((a[3]||{}).dot||'',SIDE_OPEN)).filter(Boolean))];}
// Gathered line n says what it holds now (digestTake, foldedLess, foldedGone): each brief once with how many, and the dots
// of those alone - one left stays a gathered line naming it - or, holding nothing more, it goes (nothing it held runs for
// its end: what took them out did).
/** @param {Notice} n */
function digestRetitle(n){const items=n.items||[]; if(!items.length){n.onEnd=null; endNotice(n,true); return;}
  n.dots=digestDots(items); const [t,d]=msgSplit((n.digestTitle||n.title)+' — '+digestLine(items.map(digestBrief))); n.title=t; n.desc=d; STATUS_SIG=''; drawStatus();}

// A CLICK message - a passing notice that is not an undo (a restored draft's [버리기]) - lasts until the next press somewhere
// else: a click (a tap, Enter on a button) outside it ends it; a scroll does not. The press that made it has passed by the time
// it exists. An undo is never CLICK (rule 2).
document.addEventListener('click',e=>{const t=/** @type {HTMLElement} */(e.target);
  NOTICES.forEach(n=>{if(n.life!==NOTICE_LIFE.CLICK)return;
    const own=n.place===NOTICE_PLACE.LINE?!!(t.closest&&t.closest('#status,#status-list')):!!(n.el&&n.el.contains(t));
    if(!own)endNotice(n,false);});},true);

// One message's element, made once and kept on n.el (a redraw moves it, so a focus inside survives and an alert is not read
// out again): status icon, title and description (already in the UI language, so translate="no"), its action, and [x] -
// none on a chip, which goes by itself. ERR and WARN banners are alerts. A TIMER message holds while a mouse is on it - from
// a real movement over it (realMove), not from being drawn under a resting pointer - until the pointer leaves (armNotice).
/** @param {Notice} n @param {string} cls @returns {HTMLElement} */
function noticeEl(n,cls){if(n.el)return n.el; const e=document.createElement('div'); e.className='nt '+cls+' nk-'+n.kind; e.dataset.n=String(n.n);
  if(n.place===NOTICE_PLACE.BANNER&&(n.kind===NOTICE_KIND.ERR||n.kind===NOTICE_KIND.WARN))e.setAttribute('role','alert');
  const chip=n.place===NOTICE_PLACE.CHIP,title=chip&&n.label?n.label:n.title,desc=chip?'':n.desc;
  setHtml(e,html`<span class="nt-ic">${noticeIcon(n.kind)}</span><span class="nt-t" translate="no"><span class="nt-ti">${title}</span>${desc?html`<span class="nt-d">${desc}</span>`:''}</span><span class="nt-acts">${noticeButtons(n,!chip)}</span>`);
  if(chip)for(const t of ['pointerdown','mousedown'])e.addEventListener(t,ev=>ev.stopPropagation());   // a press on the chip never starts a selection on the page under it
  if(n.life===NOTICE_LIFE.TIMER){e.addEventListener('pointermove',ev=>{if(!n.hover&&realMove(ev)&&NOTICES.has(n.n)){n.hover=true; armNotice(n);}},{passive:true});
    for(const t of ['pointerleave','pointercancel'])e.addEventListener(t,()=>{if(n.hover&&NOTICES.has(n.n)){n.hover=false; armNotice(n);}});}
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
  syncSaveBtn(); tipFollow();}   // what is under a banner moved down
// The composer's [핀 저장] reads [다시 저장] while its banner is a failed save (saveBtnLabel), and goes back after.
function syncSaveBtn(){const b=$('#btn-save'); if(!b||b.dataset.pending)return; const n=BANNERS.get(NOTICE_HOST.COMPOSER),retry=!!(n&&n.save);
  if((b.dataset.retry==='1')!==retry){if(retry)b.dataset.retry='1'; else delete b.dataset.retry; setHtml(b,saveBtnLabel());}}
// A composer's banner belongs to its selection: when the composer closes (saved, cancelled), it goes with it.
new MutationObserver(()=>{if($('#composer').hidden){const n=BANNERS.get(NOTICE_HOST.COMPOSER); if(n)endNotice(n,false);}})
  .observe($('#composer'),{attributes:true,attributeFilter:['hidden']});

// Rows in a card's place and notes in a card, after drawPins drew the list. A row waits until its card has left the section
// (away), then goes into the slot the list drew where its pin would stand in the list's order (cardRows: under its day line), or
// for a row made after that draw where placeRow puts it; once its pin is back in that section, what it offers to
// undo is undone and it goes - unless it holds a deferred send, whose card stays out until the send. A note goes above its
// card's buttons (or a done pin's row's end); a note whose card is not drawn moves to the status line (offerToLine).
// focus = what noticeFocus() saw before the redraw.
/** @param {HTMLElement|null} [focus] */
function drawOffers(focus){NOTICES.forEach(n=>{
  if(n.place===NOTICE_PLACE.ROW){const box=n.sec==='review'?$('#review-pins'):$('#pins');
    if(box.querySelector('.pin.card[data-id="'+n.pin+'"]')){if(n.away&&!n.gone)endNotice(n,true); else if(n.el)n.el.remove(); return;}
    n.away=true; if(n.sec==='review')$('#sec-review').hidden=false;   // its last card may just have left (drawPins keeps it shown too)
    const e=noticeEl(n,'nt-row'),slot=box.querySelector('.nt-slot[data-slot="'+n.n+'"]');
    if(slot)slot.replaceWith(e); else if(e.parentElement!==box)placeRow(box,n,e);}   // one standing since the last draw has its place
  else if(n.place===NOTICE_PLACE.CARD){const c=document.querySelector('#list .pin.card[data-id="'+n.pin+'"],#list .arc-row[data-id="'+n.pin+'"]');
    if(!c){offerToLine(n); return;}
    const e=noticeEl(n,'nt-note'),acts=c.querySelector(':scope>.acts'); if(acts)acts.before(e); else c.appendChild(e);}});
  noticeRefocus(focus||null);}

// Chips on marks, after marks() drew them: on the pin's mark, kept on its page. A chip whose mark is not drawn (another
// document, a failed reload) moves to the status line - unless it waits for its first reload (pending) - and so does one
// that would sit under the select mode's bar (chipsClearOfBar).
function drawChips(){NOTICES.forEach(n=>{if(n.place!==NOTICE_PLACE.CHIP)return;
  const k=/** @type {HTMLElement|null} */(document.querySelector('.mark[data-pin="'+n.pin+'"]')||document.querySelector('#doc .pv[data-pin="'+n.pin+'"]'));   // a page verdict line shows its pin instead of a mark
  if(!k){if(!n.pending)offerToLine(n); return;}
  const f=noticeFocus(),e=noticeEl(n,'nt-chip'); if(e.parentNode!==k)k.appendChild(e); e.style.left=''; e.style.right=''; e.style.maxWidth='';
  chipInRoom(e,k); noticeRefocus(f);});
  chipsClearOfBar();}
// Keeps a chip where it can be pressed: inside its page, inside what the PDF area shows, and clear of a panel laid over the
// PDF area (the unfolded foldable's overlay panel while composing). Where the room is narrower than the chip its words give
// way (ellipsis, .nt-t) - never its [되돌리기] - then it moves left until it fits. A page verdict line's chip stands in the
// line's row (notices.css), which already keeps out of all of that (sizePv): nothing to move.
/** @param {HTMLElement} e @param {HTMLElement} k */
function chipInRoom(e,k){if(k.classList.contains('pv'))return;
  const L=$('#left'),R=$('#right'),box=(k.closest('.pg')||k).getBoundingClientRect(),lr=L.getBoundingClientRect();
  let right=Math.min(box.right,lr.left+L.clientWidth)-4; const left=Math.max(box.left,lr.left)+4,cr0=e.getBoundingClientRect();
  // A panel beside or over the PDF area - a column down its right side, not a bottom sheet (which starts at its left) -
  // bounds the chip at every height: the chip may be scrolled up beside it after it is drawn.
  if(R&&R.getClientRects().length){const rr=R.getBoundingClientRect(); if(rr.left>lr.left+40)right=Math.min(right,rr.left-4);}
  // ...and so does the panel's handle (#grip), whose touch area (::after, 44px on touch) reaches into the PDF area at the
  // panel's middle: a chip scrolled there had its [되돌리기] under the handle.
  const G=$('#grip'); if(G&&G.getClientRects().length){const gr=G.getBoundingClientRect(),reach=Math.max(gr.width,parseFloat(getComputedStyle(G,'::after').width)||0);
    if(gr.left>lr.left+40)right=Math.min(right,gr.right-reach-4);}
  if(right-left<=0)return;
  if(cr0.width>right-left)e.style.maxWidth=Math.floor(right-left)+'px';
  const cr=e.getBoundingClientRect(),over=cr.right-right,under=left-cr.left;
  if(over>0)e.style.left=Math.round(e.offsetLeft-Math.min(over,cr.left-left))+'px';
  else if(under>0)e.style.left=Math.round(e.offsetLeft+under)+'px';}
// Whether two boxes (left, top, right, bottom) overlap by more than a touching edge. Pure.
/** @param {{left:number,top:number,right:number,bottom:number}} a @param {{left:number,top:number,right:number,bottom:number}} b */
function boxesMeet(a,b){return a.left<b.right&&b.left<a.right&&a.top<b.bottom&&b.top<a.bottom;}
// A chip never sits under the select mode's bar (#sel-bar, over the top of the PDF area while the mode is on): one whose box
// meets the bar's - the mode turned on, or the page scrolled the mark up under it - takes its undo to the status line.
// Nothing is read while no chip is up, and while the area scrolls only once a frame (with placeChips): read on every scroll
// event it forced a layout each time - seconds of long tasks over a first scroll through a list of a hundred pins.
function chipsClearOfBar(){let any=false; NOTICES.forEach(n=>{if(n.place===NOTICE_PLACE.CHIP&&n.el)any=true;}); if(!any)return;
  const bar=$('#sel-bar'); if(!bar||!bar.getClientRects().length)return; const br=bar.getBoundingClientRect();
  NOTICES.forEach(n=>{if(n.place===NOTICE_PLACE.CHIP&&n.el&&n.el.getClientRects().length&&boxesMeet(n.el.getBoundingClientRect(),br))offerToLine(n);});}
// A page verdict line's chip with no room to stand in (verdict.js pvChipPlace) takes its undo to the status line.
/** @param {HTMLElement} e */
function chipAway(e){NOTICES.forEach(n=>{if(n.el===e&&n.place===NOTICE_PLACE.CHIP)offerToLine(n);});}
// Places every save chip on screen again by chipInRoom's rules, from its mark's or line's place now: after a zoom (setW) and,
// once a frame, while the PDF area scrolls either way - its place was set in px, so a zoomed page or a sideways scroll could
// leave [되돌리기] off the PDF area or under the panel or its handle.
function placeChips(){NOTICES.forEach(n=>{const e=n.el,k=e&&e.parentElement; if(n.place!==NOTICE_PLACE.CHIP||!e||!k||!e.isConnected||k.classList.contains('pv'))return;
  e.style.left=''; e.style.right=''; e.style.maxWidth=''; chipInRoom(e,k);});}
let CHIP_FRAME=0;
$('#left').addEventListener('scroll',()=>{if(!CHIP_FRAME)CHIP_FRAME=requestAnimationFrame(()=>{CHIP_FRAME=0; placeChips(); chipsClearOfBar();});},{passive:true});
new MutationObserver(chipsClearOfBar).observe(document.body,{attributes:true,attributeFilter:['class']});   // body.selmode comes and goes
// The list reload after a save or an append has run: a chip whose mark did not come goes to the status line (drawChips).
/** @param {Notice|null} n */
function settleChip(n){if(!n||!NOTICES.has(n.n)||n.place!==NOTICE_PLACE.CHIP)return; n.pending=false; drawChips();}
// Moves an undo whose place left the screen to the status line, with the same action, what it holds (gone) and life; a TIMER
// one gets a window of its own there. A pressed one (busy: its request is out) does not move - it is offered nowhere else,
// and goes when the request is answered (noticeAct); the place it left was its own doing (a save's chip and its mark).
/** @param {Notice} n */
function offerToLine(n){if(n.busy)return; const act=n.act,gone=n.gone; n.gone=null; endNotice(n,true); if(!act)return;
  // Its title and description stay as they were split: joined back with ' · ' a title that holds one ('#6 채택 판정 저장됨 · PL16')
  // was cut at it on the line.
  const m=lineNote(n.desc?n.title+' — '+n.desc:n.title,NOTICE_KIND.OK,act,{life:n.life,gone,literal:true,undo:true,quiet:true});   // said when it came: not again as it moves
  DEFERRED.forEach(d=>{if(d.note===n)d.note=m;});}   // an early send takes the moved undo away

// Trash rows: an undo in the place of the row it took away (after the row drawn before it, or first). drawTrash calls this.
function drawTrashOffers(){const box=$('#trash-list'); NOTICES.forEach(n=>{if(n.place!==NOTICE_PLACE.TRASH)return;
  const e=noticeEl(n,'nt-row'),prev=n.prev!=null?box.querySelector('.arc-row[data-id="'+n.prev+'"]'):null;
  if(prev)prev.after(e); else box.prepend(e);});}
// Closing the Trash takes its rows' undos to the status line: inside a closed dialog they could no longer be pressed.
$('#trash').addEventListener('close',()=>{NOTICES.forEach(n=>{if(n.place===NOTICE_PLACE.TRASH)offerToLine(n);});});

// Deferred send with an undo (docs/handbook/viewer.md §알림 자리): commit runs when its undo leaves - after NOTICE_MS, on [x],
// or when the page is hidden - and [되돌리기] (cancel) runs undo instead, before anything reaches the server. So an agent never
// sees a reply or a permanent delete that was taken back. note = the undo drawn for it, which an early commit takes away. Its
// own bound is the guard: whatever holds or moves its undo, it is sent NOTICE_MS + NOTICE_HOLD_MAX after it was made at the
// latest. Runs once, cancels once, never both.
const DEFERRED=/** @type {Set<Deferred>} */(new Set());
/** @param {()=>void} commit @param {()=>void} undo @returns {Deferred} */
function deferred(commit,undo){let done=false; const bound=setTimeout(()=>d.run(),NOTICE_MS+NOTICE_HOLD_MAX);
  const d=/** @type {Deferred} */({note:null,
    run:()=>{if(done)return; done=true; clearTimeout(bound); DEFERRED.delete(d); if(d.note)endNotice(d.note,true); commit();},
    cancel:()=>{if(done)return; done=true; clearTimeout(bound); DEFERRED.delete(d); undo();}});
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
