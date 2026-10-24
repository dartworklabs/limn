// ------------------------------------------------ Suggested edits (docs/handbook/viewer.md §제안 수정, ADR-0020)
// A LaTeX line pin may carry the exact text that replaces its lines lo..hi: `suggest` {base, text}, base being the lines the
// author saw (docs/handbook/api.md §제안 수정 (`suggest`)). The composer and an open edit card each write one draft
// (SuggestDraft): the [제안 수정] switch, the editor's text, the text it was filled from (base) and the lines that base is.
// Until the text is edited it follows the range - a new pick, a rung, the excerpt's + and − - and once edited a range change
// keeps it and one line offers to read the new range's lines. A card shows a suggestion as a line diff of base -> text in the
// changes view's source-diff look, folded past five rows as the excerpt's band is.

const SUGGEST_LINES=80;   // the most lines a suggestion may replace (limn.pins.editing.values.SUGGEST_LINES_MAX, the snippet's cap)
const SUGGEST_FOLD=5;     // a card's diff folds past this many rows to its first two and last two
// The short reason drawn where the switch would be when a selection can carry no suggested edit, and its tooltip.
const SUGGEST_WHY={pdf:['보기 전용 PDF에는 제안 수정 없음','보기 전용 PDF에는 LaTeX 원문 줄이 없어 바꿀 글을 둘 수 없습니다'],
  figure:['그림 문서에는 제안 수정 없음','그림 스크립트에는 공통 부품과 다시 그리기 규칙이 따로 있어, 그림 문서에는 바꿀 글을 둘 수 없습니다'],
  region:['영역에는 제안 수정 없음','영역에는 원문 줄이 없어 바꿀 글을 둘 수 없습니다'],
  long:['제안 수정은 80줄까지','제안 수정은 80줄까지의 범위만 바꿉니다. 범위를 줄이면 켤 수 있습니다']};

/** A draft with nothing in it: off, empty, never filled. @returns {SuggestDraft} */
function suggestDraft(){return {on:false,text:'',base:null,file:null,lo:0,hi:0,had:null,current:null,reading:'',fail:null};}
const SG=suggestDraft();   // the composer's draft; an open edit card keeps its own (EditCard.sg)
/** A copy of draft sg to keep (a discard's undo, the tab's stored draft): what it holds, without a read under way or its
 * failure. @param {SuggestDraft} sg @returns {SuggestDraft} */
function suggestCopy(sg){return {...sg,had:sg.had&&{...sg.had},current:sg.current&&{...sg.current},reading:'',fail:null};}
/** The draft an edit card of pin p opens with: on and filled with the pin's suggestion when it has one (had keeps it, to tell
 * what a save changes), else an empty draft. @param {Pin} p @returns {SuggestDraft} */
function suggestOfPin(p){const d=suggestDraft(),s=p.suggest; if(!s)return d;
  return {...d,on:true,text:s.text,base:s.base,file:p.file||null,lo:p.lo||0,hi:p.hi||0,had:{base:s.base,text:s.text}};}

// Why o - a pick or an edit card - can carry no suggested edit (SUGGEST_OFF), or null when it can: a view-only PDF, a figure
// document, an area (a region pick or pin, or no lines), or a range of more than SUGGEST_LINES lines. docKind is the document's
// kind; an unknown one is a LaTeX document. Pure.
/** @param {{kind?:string,file?:string,pdf?:string,region?:boolean,lo?:number,hi?:number}|null} o @param {string|undefined} docKind @returns {string|null} */
function suggestOff(o,docKind){if(docKind===DOC_KIND.PDF)return SUGGEST_OFF.PDF; if(isFigureKind(docKind))return SUGGEST_OFF.FIGURE;
  if(!o||o.region||isRegion(o)||o.lo==null||o.hi==null)return SUGGEST_OFF.REGION;
  return o.hi-o.lo+1>SUGGEST_LINES?SUGGEST_OFF.LONG:null;}
/** Whether draft sg holds a text other than the one it was filled from (a draft never filled is not edited). Pure.
 * @param {SuggestDraft} sg @returns {boolean} */
function suggestEdited(sg){return sg.base!=null&&sg.text!==sg.base;}
/** The lines o is, as a draft records them: 'file:lo-hi'. Pure. @param {{file?:string|null,lo?:number,hi?:number}} o @returns {string} */
function suggestKey(o){return String(o.file)+':'+o.lo+'-'+o.hi;}
/** Whether o's lines are not the ones draft sg's base was read from. Pure.
 * @param {SuggestDraft} sg @param {{file?:string|null,lo?:number,hi?:number}|null} o @returns {boolean} */
function suggestMoved(sg,o){return sg.base!=null&&!!o&&suggestKey(sg)!==suggestKey(o);}
// What a new pin's save sends as `suggest` for draft sg on a selection that is `off`: {base, text} when the editor is on, was
// filled and holds another text; null otherwise (nothing to suggest, or a selection that can carry none). A range over
// SUGGEST_LINES still sends it: the server's refusal (suggest_too_long) says why on the save row, and the draft stays. Pure.
/** @param {SuggestDraft} sg @param {string|null} off @returns {PinSuggest|null} */
function suggestForSave(sg,off){if(!sg.on||sg.base==null||(off&&off!==SUGGEST_OFF.LONG)||sg.text===sg.base)return null;
  return {base:sg.base,text:sg.text};}
// What an edit's save sends as `suggest` for card draft sg: undefined (the stored suggestion stays as it is), null (remove it)
// or {base, text}. Switched off, or left with the source's own text, removes the pin's suggestion and sends nothing when it
// had none; the pin's own base and text send nothing; a draft not filled yet sends nothing. Pure.
/** @param {SuggestDraft} sg @param {string|null} off @returns {PinSuggest|null|undefined} */
function suggestForEdit(sg,off){const had=sg.had;
  if(!sg.on)return had?null:undefined;
  if(sg.base==null||(off&&off!==SUGGEST_OFF.LONG))return undefined;
  if(sg.text===sg.base)return had?null:undefined;
  if(had&&had.base===sg.base&&had.text===sg.text)return undefined;
  return {base:sg.base,text:sg.text};}

// The lines of a suggestion's string: an empty text is no line (it deletes the range); a base always has its range's lines.
// Pure. @param {string} s @param {boolean} isText @returns {string[]}
function suggestLines(s,isText){return isText&&s===''?[]:String(s).split('\n');}
// A line diff of base -> text, top to bottom: rows {k:'ctx'|'del'|'add', t: the line, n: its number} - a base line numbered
// from lo as it is in the file, a text line from lo as it would be after the change; in a changed run the deleted lines come
// first. The longest common subsequence of whole lines. Pure.
/** @param {string} base @param {string} text @param {number} lo @returns {{k:string,t:string,n:number}[]} */
function suggestDiff(base,text,lo){const a=suggestLines(base,false),b=suggestLines(text,true),n=a.length,m=b.length;
  const L=Array.from({length:n+1},()=>new Int32Array(m+1));   // L[i][j]: the common lines of a[i..] and b[j..]
  for(let i=n-1;i>=0;i--)for(let j=m-1;j>=0;j--)L[i][j]=a[i]===b[j]?L[i+1][j+1]+1:Math.max(L[i+1][j],L[i][j+1]);
  const out=[]; let i=0,j=0;
  while(i<n||j<m){
    if(i<n&&j<m&&a[i]===b[j]){out.push({k:'ctx',t:b[j],n:lo+j}); i++; j++;}
    else if(i<n&&(j>=m||L[i+1][j]>=L[i][j+1])){out.push({k:'del',t:a[i],n:lo+i}); i++;}
    else{out.push({k:'add',t:b[j],n:lo+j}); j++;}}
  return out;}
// The rows a diff shows: all of them when open or no more than SUGGEST_FOLD, else the first two and the last two round
// {k:'fold', n} for the rows between - the excerpt's fold. Pure.
/** @param {{k:string,t:string,n:number}[]} rows @param {boolean} open @returns {{k:string,t:string,n:number}[]} */
function suggestFold(rows,open){if(open||rows.length<=SUGGEST_FOLD)return rows;
  return [rows[0],rows[1],{k:'fold',t:'',n:rows.length-4},rows[rows.length-2],rows[rows.length-1]];}
// Diff rows as Html in the changes view's source-diff look (revisions.css .rd-line): a number column and the line with its
// '+', '-' or ' ' mark, so a change never rests on colour alone. The lines are the manuscript's text (translate="no").
/** @param {{k:string,t:string,n:number}[]} rows @returns {Html} */
function suggestDiffHtml(rows){return html`<div class="sg-diff" translate="no">${rows.map(r=>r.k==='fold'
    ?html`<span class="rd-line rd-fold"><span class="rd-no" aria-hidden="true"></span><span class="rd-code">… ${tl('{n}줄',{n:r.n})}</span></span>`
    :html`<span class="rd-line rd-${r.k==='ctx'?'context':r.k}"><span class="rd-no" aria-hidden="true">${r.n}</span><span class="rd-code">${r.k==='add'?'+':r.k==='del'?'-':' '}${r.t}</span></span>`)}</div>`;}

// ---------------- A card's suggestion
const SG_OPEN=new Set();   // the cards whose suggestion diff is unfolded ('<doc>:<id>'), kept across redraws
// A card's suggested edit, after its note: the diff of base -> text, folded past SUGGEST_FOLD rows with [제안 펼치기 · N줄]
// under it to unfold. null when the pin has none.
/** @param {Pin} p @returns {Html|null} */
function suggestView(p){const s=p.suggest; if(!s)return null;
  const k=pdoc(p)+':'+p.id,open=SG_OPEN.has(k),rows=suggestDiff(s.base,s.text,p.lo||1);
  const foot=rows.length>SUGGEST_FOLD?html`<div class="sg-foot"><button class="btn-sm btn-ghost" data-act="sg-fold" data-key="${k}" aria-expanded="${String(open)}">\
${open?tr('제안 접기'):tr('제안 펼치기')+' · '+tl('{n}줄',{n:rows.length})}</button></div>`:null;
  return html`<div class="sg-view">${suggestDiffHtml(suggestFold(rows,open))}${foot}</div>`;}
// A card's [제안 수정] badge, with the reason not to apply it when its lines no longer read as its base ('원문 바뀜') or
// cannot be compared ('확인 불가'): a pin's `suggest_state`. A closed card shows the plain badge: a closed pin is not re-synced, and
// one whose suggestion was applied reads as changed. null without a suggestion.
/** @param {Pin} p @param {boolean} closed @returns {Html|null} */
function suggestBadge(p,closed){if(!p.suggest)return null; const st=closed?SUGGEST_STATE.READY:p.suggest_state;
  if(st===SUGGEST_STATE.CHANGED)return html`<span class="badge badge-warning sg-badge" data-tip="${tr('그사이 이 줄들이 바뀌어 제안의 원문과 다릅니다 — 에이전트는 넣지 않고 답글로 알립니다. [수정]에서 지금 원문으로 맞출 수 있습니다')}">${ic('triangle-alert')}${tr('제안 수정')} · ${tr('원문 바뀜')}</span>`;
  if(st===SUGGEST_STATE.UNKNOWN)return html`<span class="badge badge-warning sg-badge" data-tip="${tr('원문과 대조할 수 없습니다(위치를 잃었거나 파일을 읽지 못함) — 에이전트는 넣지 않고 알립니다')}">${ic('triangle-alert')}${tr('제안 수정')} · ${tr('확인 불가')}</span>`;
  return html`<span class="badge sg-badge" data-tip="${tr('작성자가 바꿀 글을 직접 썼습니다 — 에이전트가 이 줄 범위에 글자 그대로 넣습니다')}">${tr('제안 수정')}</span>`;}

// ---------------- The editor (composer and edit card)
// Reads the lines o.lo..o.hi of o.file exactly (GET /api/snippet?…&text=1) into draft sg as its base - and as its text too
// when `fill` - then redraws its owner. Only while owns() (the selection or the edit card is still on screen), o still has
// those lines and, for a fill, the text was not typed meanwhile: otherwise the next draw decides again. A failure keeps the
// draft and says why on its line (fail), with [원문 다시 읽기].
/** @param {SuggestDraft} sg @param {any} o @param {boolean} fill @param {()=>boolean} owns @param {()=>void} redraw */
async function suggestRead(sg,o,fill,owns,redraw){const key=suggestKey(o),was=sg.text; if(sg.reading===key)return;
  sg.reading=key; sg.fail=null; redraw();
  let text=/** @type {string|null} */(null),fail='';
  try{const {status,data}=await api(dq('/api/snippet?file='+encodeURIComponent(String(o.file))+'&lo='+o.lo+'&hi='+o.hi+'&text=1',o.doc),
      {what:'원문 읽기',expect:[400],silent:true});
    if(status===400)fail=errText(data); else if(data&&typeof data.text==='string')text=data.text; else fail=tr('80줄이 넘는 범위는 원문을 받지 못합니다');}
  catch(e){fail=tr('서버에 닿지 않습니다');}
  if(sg.reading!==key)return;   // a newer read took over
  sg.reading='';
  if(!owns())return;
  if(suggestKey(o)!==key||(fill&&sg.text!==was)){redraw(); return;}
  if(text==null){sg.fail={key,fill,why:fail}; redraw(); return;}
  sg.base=text; sg.file=o.file||null; sg.lo=o.lo; sg.hi=o.hi; sg.current=null; if(fill)sg.text=text;
  redraw();}
// Keeps draft sg on o's lines while its text is the source's own: an editor turned on and never filled, or not edited since
// and now on other lines, reads them as its text and base. Nothing while off, on a selection that can carry no suggestion,
// during a read, or after a read of these lines failed (its [원문 다시 읽기] tries again).
/** @param {SuggestDraft} sg @param {any} o @param {string|null} off @param {()=>boolean} owns @param {()=>void} redraw */
function suggestFollow(sg,o,off,owns,redraw){if(!sg.on||off||sg.reading)return;
  if(sg.fail&&sg.fail.key===suggestKey(o))return;
  if(sg.base==null||(suggestMoved(sg,o)&&!suggestEdited(sg)))suggestRead(sg,o,true,owns,redraw);}
// [지금 원문으로 맞추기]: draft sg keeps its text and takes the current lines of o as its base - the text a 409 answered with
// when it is o's lines, else read now.
/** @param {SuggestDraft} sg @param {any} o @param {()=>boolean} owns @param {()=>void} redraw */
function suggestRebase(sg,o,owns,redraw){const c=sg.current; sg.current=null;
  if(c&&o&&suggestKey(c)===suggestKey(o)){sg.base=c.text; sg.file=c.file; sg.lo=c.lo; sg.hi=c.hi; redraw(); return;}
  if(o)suggestRead(sg,o,false,owns,redraw); else redraw();}
// The one line under the editor of draft sg on o, or null: what is under way or wrong first, then what a save will do. Each is
// a Korean message (drawn through tr) and maybe the line's one action {act, label, tip}. isEdit: an edit card, whose pin's
// suggest_state is `state`.
/** @param {SuggestDraft} sg @param {any} o @param {string|null} off @param {boolean} isEdit @param {string|undefined} state
 * @returns {{msg:string,act:{act:string,label:string,tip:string}|null}|null} */
function suggestLine(sg,o,off,isEdit,state){
  const reload={act:'sg-reload',label:'원문 다시 불러오기',tip:'지금 범위의 원문 줄을 다시 읽어 이 칸을 채웁니다. 쓰던 글은 그 원문으로 바뀝니다'};
  const rebase={act:'sg-rebase',label:'지금 원문으로 맞추기',tip:'쓰던 글은 그대로 두고, 이 제안이 바꿀 원문을 지금 그 줄들의 글로 바꿉니다'};
  if(!sg.on)return isEdit&&sg.had?{msg:'저장하면 이 핀의 제안 수정을 지웁니다',act:null}:null;
  if(off===SUGGEST_OFF.LONG)return {msg:'범위가 80줄을 넘어 이대로는 저장되지 않습니다 — 범위를 줄이거나 제안 수정을 끄세요',act:null};
  if(sg.reading&&sg.base==null)return {msg:'원문 읽는 중…',act:null};
  const f=sg.fail; if(f)return {msg:tl('원문을 읽지 못했습니다 — {why}',{why:f.why}),act:{act:f.fill?'sg-reload':'sg-rebase',label:'원문 다시 읽기',tip:'이 줄들의 원문을 다시 읽습니다'}};
  if(sg.current&&o&&suggestKey(sg.current)===suggestKey(o))return {msg:'그사이 원문이 바뀌었습니다 — 아래는 지금 원문과 이 글의 차이입니다',act:rebase};
  if(suggestMoved(sg,o))return {msg:'범위가 바뀌었습니다',act:reload};
  if(isEdit&&sg.had&&state===SUGGEST_STATE.CHANGED&&sg.base===sg.had.base)return {msg:'그사이 원문이 바뀌었습니다',act:rebase};
  if(sg.base!=null&&sg.text===sg.base)return {msg:isEdit&&sg.had?'원문과 같아 저장하면 이 핀의 제안 수정을 지웁니다':'원문 그대로입니다 — 고친 글만 제안 수정으로 보냅니다',act:null};
  return null;}
// Grows a suggestion editor to its text, from two lines up to twelve (then it scrolls).
/** @param {HTMLTextAreaElement} ta */
function suggestGrow(ta){if(ta.hidden||!ta.getClientRects().length)return; const cs=getComputedStyle(ta),px=v=>parseFloat(v)||0;
  const lh=px(cs.lineHeight)||18,edge=px(cs.paddingTop)+px(cs.paddingBottom)+px(cs.borderTopWidth)+px(cs.borderBottomWidth);
  ta.style.height='auto'; const need=ta.scrollHeight+px(cs.borderTopWidth)+px(cs.borderBottomWidth);
  ta.style.height=Math.min(12*lh+edge,Math.max(2*lh+edge,need))+'px';}
// Draws draft sg on o into its elements (els): the switch - or, when o can carry no suggestion, the short reason in its place -
// the editor while on, the one line under it and, after a 409, the diff of the current source -> the text. A range over
// SUGGEST_LINES keeps the switch while it is on, so it can be switched off. The editor is read-only until its first fill. The
// line is a polite live region, so it is written only when what it says changes (typing redraws it on every key).
/** @param {SuggestDraft} sg @param {any} o @param {string|null} off
 * @param {{tg:HTMLElement,why:HTMLElement,box:HTMLElement,ta:HTMLTextAreaElement,line:HTMLElement,cur:HTMLElement}} els
 * @param {boolean} isEdit @param {string|undefined} state */
function drawSuggest(sg,o,off,els,isEdit,state){const shown=!off||(off===SUGGEST_OFF.LONG&&sg.on);
  els.tg.hidden=!shown; els.tg.setAttribute('aria-checked',String(sg.on));
  els.why.hidden=shown; if(!shown&&off){const w=SUGGEST_WHY[off]; els.why.textContent=tr(w[0]); els.why.dataset.tip=w[1];}
  const editing=sg.on&&shown; els.ta.hidden=!editing;
  if(els.ta.value!==sg.text)els.ta.value=sg.text; els.ta.readOnly=sg.base==null;
  const line=shown?suggestLine(sg,o,off,isEdit,state):null,said=line?line.msg+'\n'+(line.act?line.act.act:''):''; els.line.hidden=!line;
  if(els.line.dataset.said!==said){els.line.dataset.said=said; const a=line&&line.act;
    if(line)setHtml(els.line,html`<span>${tr(line.msg)}</span>${a?html`<button class="hit" data-act="${a.act}" data-tip="${a.tip}">${tr(a.label)}</button>`:''}`); else els.line.replaceChildren();}
  const c=editing&&sg.current&&o&&suggestKey(sg.current)===suggestKey(o)?sg.current:null; els.cur.hidden=!c;
  if(c)setHtml(els.cur,suggestDiffHtml(suggestDiff(c.text,sg.text,c.lo))); else els.cur.replaceChildren();
  els.box.hidden=els.ta.hidden&&els.line.hidden&&els.cur.hidden;
  if(editing)suggestGrow(els.ta);}

// ---------------- The composer's draft (SG)
/** The composer's suggestion elements. */
function composerSuggestEls(){return {tg:$('#c-sg-tg'),why:$('#c-sg-why'),box:$('#c-sg'),ta:/** @type {HTMLTextAreaElement} */($('#c-sg-text')),line:$('#c-sg-note'),cur:$('#c-sg-cur')};}
// Draws the composer's suggestion for selection d (renderComposer and renderRegionComposer call it on every draw) and keeps an
// unedited draft on d's lines. A read's answer redraws it, the overlap notice ([덧붙이기] waits on an edited suggestion) and the
// stored draft. The tablet sheet's height follows the editor as it opens, fills, grows and closes (applySheet, tabletLift).
/** @param {Selection} d */
function renderSuggest(d){const off=suggestOff(d,META?META.kind:undefined),owns=()=>COMPOSE.current===d;
  const redraw=()=>{if(!owns())return; renderSuggest(d); renderOverlapBanner(); saveDraftSoon();};
  drawSuggest(SG,d,off,composerSuggestEls(),false,undefined); suggestFollow(SG,d,off,owns,redraw);
  if(BAND===LAYOUT_BAND.TABLET_SHEET)applySheet();}
// Whether the composer's draft is a suggestion a save would send, so its note may not join an overlapped pin instead
// ([덧붙이기] appends a note; the suggestion belongs to this selection's lines).
function suggestPending(){return SG.on&&suggestEdited(SG);}
// Empties the composer's draft (a save, a discard without undo, another document) and its editor.
function suggestClear(){Object.assign(SG,suggestDraft()); const ta=/** @type {HTMLTextAreaElement} */($('#c-sg-text')); ta.value=''; ta.style.height='';}

// ---------------- An edit card's draft (EditCard.sg)
// The kind of edit card E's document (an unknown one is LaTeX).
/** @param {EditCard} E @returns {string|undefined} */
function editDocKind(E){const d=docInfo(E.doc); return d?d.kind:E.doc===DOC&&META?META.kind:undefined;}
/** Edit card E's suggestion elements. @param {EditCard} E */
function editSuggestEls(E){const q=s=>/** @type {HTMLElement} */(E.el.querySelector(s));
  return {tg:q('.e-sg-row .sg-tg'),why:q('.e-sg-row .sg-why'),box:q('.e-sg'),ta:/** @type {HTMLTextAreaElement} */(q('.e-sg-text')),line:q('.e-sg .sg-note'),cur:q('.e-sg .sg-cur')};}
// Draws edit card E's suggestion (renderEdit): the switch and the editor on an open pin; a closed pin's suggestion read-only
// (its diff, no switch), as it can only take memo edits.
/** @param {EditCard} E */
function renderEditSuggest(E){const pin=findAnyPin(E.id),closed=!!pin&&pinState(pin)!==PIN_STATE.OPEN,els=editSuggestEls(E);
  const row=/** @type {HTMLElement} */(E.el.querySelector('.e-sg-row')),ro=/** @type {HTMLElement} */(E.el.querySelector('.e-sg-ro'));
  row.hidden=closed; const view=closed&&pin?suggestView(pin):null; ro.hidden=!view; if(view)setHtml(ro,view); else ro.replaceChildren();
  if(closed){els.box.hidden=true; return;}
  const off=suggestOff(E,editDocKind(E)),owns=()=>EDITOR.current===E,redraw=()=>{if(owns())renderEditSuggest(E);};
  drawSuggest(E.sg,E,off,els,true,pin?pin.suggest_state:undefined); suggestFollow(E.sg,E,off,owns,redraw);}
// The draft and the selection or card an editor control belongs to: the open edit card's when el is inside it, else the composer's.
/** @param {HTMLElement} el @returns {{sg:SuggestDraft,o:any,owns:()=>boolean,redraw:()=>void}|null} */
function suggestOwner(el){if(el.closest('.edit')){const E=EDITOR.current; if(!E)return null;
    return {sg:E.sg,o:E,owns:()=>EDITOR.current===E,redraw:()=>{if(EDITOR.current===E)renderEditSuggest(E);}};}
  const d=COMPOSE.current; if(!d)return null;
  return {sg:SG,o:d,owns:()=>COMPOSE.current===d,redraw:()=>{if(COMPOSE.current!==d)return; renderSuggest(d); renderOverlapBanner(); saveDraftSoon();}};}
// The editor's controls: the switch, [원문 다시 불러오기] (fill from the range's lines) and [지금 원문으로 맞추기] (rebase), for the
// draft el belongs to.
/** @param {HTMLElement} el @param {string} act */
function suggestAct(el,act){const w=suggestOwner(el); if(!w)return;
  if(act==='sg-toggle'){w.sg.on=!w.sg.on; w.sg.current=null; w.redraw(); return;}
  if(act==='sg-reload'){w.sg.current=null; w.sg.fail=null; suggestRead(w.sg,w.o,true,w.owns,w.redraw); return;}
  if(act==='sg-rebase'){w.sg.fail=null; suggestRebase(w.sg,w.o,w.owns,w.redraw);}}
// Typing in an editor: its draft takes the text; the line under it and - in the composer - the overlap notice and the tab's
// draft follow.
document.addEventListener('input',e=>{const t=/** @type {HTMLTextAreaElement} */(e.target); if(!t.classList||!t.classList.contains('sg-text'))return;
  const w=suggestOwner(t); if(!w)return; w.sg.text=t.value; w.redraw();});
