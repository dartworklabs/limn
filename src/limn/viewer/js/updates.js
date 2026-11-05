// ------------------------------------------------ What came while you were viewing (docs/handbook/viewer.md §새 소식)
// Said from reads the viewer already makes - no new field, no event type, nothing written on a GET (ADR-0027):
// - a document changed (a merge the instance pulled, a push, a file edited where the instance serves it, a figure or PDF
//   that came again): one message per document, '본문이 바뀌었습니다 — PR #12 서론 다듬기 · Bob Park · 핀 2개 줄 이동',
//   with [변경 보기] (the changes view on exactly the new commits) or, on a Markdown or text document, [바뀐 곳] (the changed
//   lines, tinted while the message stands). It stands until [x] or its action - only then is the change seen - and each
//   later change of that document merges into it. What a person has seen is kept per device (localStorage limnSeen), so a
//   reload, another document or a visit days later still says what changed since;
// - others' new pins (a co-author's, an agent's), one message per document, [보기];
// - this page is older than the Limn the server runs now (GET /api/version): a status item with [새로 고침] (status.js);
// - back after a while, what came meanwhile is said as one message (notices.js digestBegin, polling.js).
const UPD={moved:/** @type {Map<string,{moved:Set<number>,lost:Set<number>}>} */(new Map()),
  lines:/** @type {Map<string,{base:string[],ranges:{lo:number,hi:number}[],at:number}>} */(new Map()),expect:0,expectAt:0,
  seenAt:/** @type {Map<string,number>} */(new Map()),top:/** @type {number|null} */(null),
  checking:/** @type {Map<string,{ver:string,again:boolean}>} */(new Map())};   // document -> the check reading its history: its version, and whether a call left it to that check
const UPD_EXPECT_MS=120000;   // after a source change is seen, how long its pins' moves wait for the document's update message
const DIGEST_TAIL_MS=2500;   // how long a gathering waits after its poll for the build and the update it set going
const LINE_DIFF_MAX=500;   // edit steps the line comparison tries before calling the whole middle one changed place

// ---------------- What a person has seen (localStorage limnSeen: {v, pin, docs:{<key>:{ver, rev}}})
// ver names what a document showed (its build on screen, or a drawn document's source mtime), rev its newest commit then (''
// without history); pin the highest pin number whose arrival was said. Another browser or device keeps its own. A browser
// whose storage refuses (a SecurityError, a full quota) keeps it in memory for this visit (SEEN_MEM) from the first refusal.
let SEEN_MEM=/** @type {string|null} */(null);
/** @returns {{v?:number,pin?:number,docs?:Record<string,{ver:string,rev:string}>}} */
function seenStore(){let raw=SEEN_MEM; if(raw===null)try{raw=localStorage.getItem('limnSeen');}catch(e){raw=SEEN_MEM='{}';}
  try{const v=JSON.parse(raw||'{}'); return v&&typeof v==='object'?v:{};}catch(e){return {};}}
/** @param {{v?:number,pin?:number,docs?:Record<string,{ver:string,rev:string}>}} all */
function seenSave(all){all.v=1; const raw=JSON.stringify(all); if(SEEN_MEM!==null){SEEN_MEM=raw; return;}
  try{localStorage.setItem('limnSeen',raw);}catch(e){SEEN_MEM=raw;}}
/** @param {string} k @returns {{ver:string,rev:string}|null} */
function seenDoc(k){const d=(seenStore().docs||{})[k]; return d&&typeof d.ver==='string'?{ver:d.ver,rev:String(d.rev||'')}:null;}
// Records rec as what document k showed when seen - unless the record kept already names a later version (verAfter): another
// tab of this browser saw a newer one meanwhile, and an old tab dismissing its older message never takes that back.
/** @param {string} k @param {{ver:string,rev:string}} rec */
function setSeenDoc(k,rec){const all=seenStore(),was=(all.docs||{})[k]; if(was&&typeof was.ver==='string'&&verAfter(was.ver,rec.ver))return;
  all.docs={...(all.docs||{}),[k]:rec}; seenSave(all);}
// Whether version a (limnSeen's ver) is later than b: a drawn document's source mtime ('src:<seconds>') by its number, a
// built one's build id ('build:pages-<YYYYMMDDHHMMSS>[-<n>]', the server's names) by its time and then its count. Versions
// of different kinds are not ordered (false). Pure.
/** @param {string} a @param {string} b @returns {boolean} */
function verAfter(a,b){const src=/^src:(.+)$/,bld=/^build:pages(?:-(\d{14})(?:-(\d+))?)?$/,sa=src.exec(a),sb=src.exec(b);
  if(sa&&sb)return Number(sa[1])>Number(sb[1]);
  const ba=bld.exec(a),bb=bld.exec(b); if(!ba||!bb)return false;
  const ta=ba[1]||'',tb=bb[1]||''; return ta!==tb?ta>tb:Number(ba[2]||0)>Number(bb[2]||0);}
// Whether this device was here before: it has a seen record or an event cursor (notify.js).
function visitedBefore(){return !!seenStore().v||notifyCursor()!==null;}
/** @returns {number|null} */
function seenPin(){const n=seenStore().pin; return typeof n==='number'?n:null;}
/** @param {number} n */
function setSeenPin(n){const all=seenStore(); if(typeof all.pin==='number'&&all.pin>=n)return; all.pin=n; seenSave(all);}

// ---------------- Pure rules
// The PR number a commit subject names: a merge commit's 'Merge pull request #12 …', a squash merge's '… (#12)'; 0 for none.
/** @param {unknown} subject @returns {number} */
function prOf(subject){const s=String(subject||''),m=/^Merge pull request #(\d+)/.exec(s)||/\(#(\d+)\)\s*$/.exec(s); return m?+m[1]:0;}
// The commits above the last seen one (seen: its id or a prefix) in rows (newest first, /api/revisions): how many (all of
// them when seen is not among them: more), their PRs and authors, the newest one's subject without its '(#12)' - a merge
// commit's own subject is passed over for the commit under it - and time, and the newest id (top). Nothing when there are
// no rows (no history). unknown: which of them are new cannot be told - the rows are not known (null: what the shown build
// carries is not known, shownRows) or no commit was known as seen ('') - so none is named, and top is the newest of the rows
// known ('' for none). Pure.
/** @param {{id:string,subject:string,author?:string,time?:string}[]|null} rows @param {string} seen */
function describeCommits(rows,seen){const top=rows&&rows.length?rows[0].id:'',none={n:0,more:false,prs:/** @type {number[]} */([]),authors:/** @type {string[]} */([]),subject:'',time:'',top,unknown:false};
  if(!rows||rows.length&&!seen)return {...none,unknown:true};
  if(!rows.length)return none;
  const at=rows.findIndex(r=>r.id===seen||r.id.startsWith(seen)),fresh=at<0?rows:rows.slice(0,at);
  const plain=fresh.find(r=>!/^Merge (pull request|branch)\b/.test(r.subject))||fresh[0];
  return {n:fresh.length,more:at<0,prs:[...new Set(fresh.map(r=>prOf(r.subject)).filter(Boolean))],authors:[...new Set(fresh.map(r=>String(r.author||'')).filter(Boolean))],
    subject:plain?String(plain.subject).replace(/\s*\(#\d+\)\s*$/,''):'',time:fresh.length?String(fresh[0].time||''):'',top,unknown:false};}
// Where the lines now (b) differ from the lines before (a): the changed lines of b as ranges {lo, hi} (1-based, in order); a
// place where lines only went away is the line after it (the last line at the end). Common heads and tails are set aside, the
// middle is compared line by line (Myers) up to max edit steps, past that the whole middle is one place. Pure.
/** @param {string[]} a @param {string[]} b @param {number} max @returns {{lo:number,hi:number}[]} */
function lineChanges(a,b,max){let p=0; while(p<a.length&&p<b.length&&a[p]===b[p])p++;
  let s=0; while(s<a.length-p&&s<b.length-p&&a[a.length-1-s]===b[b.length-1-s])s++;
  const A=a.slice(p,a.length-s),B=b.slice(p,b.length-s),N=A.length,M=B.length; if(!N&&!M)return [];
  const at=(/** @type {number} */i)=>Math.max(1,Math.min(b.length,i));
  if(!M)return [{lo:at(p+1),hi:at(p+1)}];
  if(!N)return [{lo:p+1,hi:p+M}];
  const lim=Math.min(N+M,max),O=lim+1,V=new Int32Array(2*lim+3),trace=[]; let end=-1;
  for(let d=0;d<=lim&&end<0;d++){trace.push(V.slice());
    for(let k=-d;k<=d;k+=2){let x=k===-d||(k!==d&&V[O+k-1]<V[O+k+1])?V[O+k+1]:V[O+k-1]+1,y=x-k;
      while(x<N&&y<M&&A[x]===B[y]){x++; y++;} V[O+k]=x; if(x>=N&&y>=M){end=d; break;}}}
  if(end<0)return [{lo:p+1,hi:p+M}];
  const mark=new Uint8Array(M+1); let x=N,y=M;
  for(let d=end;d>0;d--){const v=trace[d],k=x-y,pk=k===-d||(k!==d&&v[O+k-1]<v[O+k+1])?k+1:k-1,px=v[O+pk],py=px-pk;
    while(x>px&&y>py){x--; y--;}
    if(x===px)mark[py]=1; else if(!mark[py])mark[py]=2;   // 1: B[py] came in; 2: lines of A went away before B[py]
    x=px; y=py;}
  const out=[]; let lo=-1;
  for(let i=0;i<=M;i++){const add=i<M&&mark[i]===1,del=mark[i]===2;
    if(add){if(lo<0)lo=i; continue;}
    if(lo>=0){out.push({lo:p+lo+1,hi:p+i}); lo=-1;}
    if(del){const n=at(p+i+1); const last=out[out.length-1]; if(!last||last.hi<n-1)out.push({lo:n,hi:n});}}
  return out;}
// The pins in rows numbered above top, not made by me (my login): the new ones others made. Pure.
/** @param {Pin[]} rows @param {number} top @param {string} me @returns {Pin[]} */
function freshPins(rows,top,me){return (rows||[]).filter(p=>p.id>top&&!(p.author&&me&&p.author.login===me)).sort((a,b)=>a.id-b.id);}
// How long a person was away, as the gathered message's title says it: minutes, hours, then days. Pure but for tl().
/** @param {number} ms @param {boolean} lost the connection was what was gone @returns {string} */
function awayTitle(ms,lost){const m=Math.max(1,Math.round(ms/60000)),t=m<60?tl('{n}분',{n:m}):m<1440?tl('{n}시간',{n:Math.round(m/60)}):tl('{n}일',{n:Math.round(m/1440)});
  return tl(lost?'연결이 끊긴 사이 ({t})':'자리를 비운 사이 ({t})',{t});}

// ---------------- A document changed
// The document k as it shows now - its name, kind and ver (what limnSeen keeps) - from its meta on screen or its entry in the
// document list; null before it is known.
/** @param {string} k @returns {{ver:string,name:string,kind:string}|null} */
function updDocState(k){const m=k===DOC?META:META_BY.get(k),d=docInfo(k),kind=(d&&d.kind)||(m&&m.kind)||'',src=/** @type {any} */(m||d); if(!src)return null;
  // a drawn document on screen: its source as last read (MD.mtime), not the meta it was opened with; off screen: the
  // document list's (noteOtherDocs keeps it fresh) - MD still holds the lines of one drawn before, as they were when left
  const mt=k===DOC&&MD.doc===k&&typeof MD.mtime==='number'?MD.mtime:k!==DOC&&d&&typeof d.src_mtime==='number'?d.src_mtime:src.src_mtime;
  const ver=rendersInBrowser(kind)?(typeof mt==='number'?'src:'+mt:''):(src.pages_build?'build:'+src.pages_build:'');
  return ver?{ver,name:(d&&d.name)||(m&&m.doc_name)||k,kind}:null;}
// Document k's commits, newest first ([] without history), or null when they could not be read.
/** @param {string} k @returns {Promise<RevisionRow[]|null>} */
async function docRows(k){try{const r=(await api(dq('/api/revisions?limit='+REVISION_PAGE,k),{what:'변경사항 읽기',silent:true})).data;
  return r.available?/** @type {RevisionRow[]} */(r.revisions||[]):[];}catch(e){return null;}}
// What document k's shown build was made from, for a built one: the commit its pages came from (the meta's head, '' outside
// git or unknown) and whether the checkout has moved past it (stale_build: its sources changed since); a drawn document shows
// the checkout's source ({head:'', behind:false}). From the meta on screen or kept, else the document's light meta; null when
// that shows another build than now's (a newer one came meanwhile) or cannot be read.
/** @param {string} k @param {{ver:string,kind:string}} now @returns {Promise<{head:string,behind:boolean}|null>} */
async function docBuild(k,now){if(rendersInBrowser(now.kind))return {head:'',behind:false};
  let m=/** @type {any} */(k===DOC?META:META_BY.get(k));
  if(!m||'build:'+m.pages_build!==now.ver){try{m=(await api(dq('/api/meta?light=1',k),{what:'상태 확인',silent:true})).data;}catch(e){return null;}}
  if(!m||'build:'+m.pages_build!==now.ver)return null;
  const h=String(m.head||''); return {head:/^[0-9a-f]{4,40}$/i.test(h)?h:'',behind:!!m.stale_build};}
// The commits of a document that its shown build carries, of rows (its history from the checkout, newest first): from the
// build's commit (head, a prefix will do) down when that is one of them; when it is not - the build's commit touched none of
// the document's files - all of them, unless the build is behind the checkout (behind): then which of them it carries is not
// known (null) - the reads say neither where the build's commit stands among them nor which of them it lacks, and a guess
// would name a commit it had already as new. A drawn document: all. Pure.
/** @param {RevisionRow[]} rows @param {string} head @param {boolean} behind @returns {RevisionRow[]|null} */
function shownRows(rows,head,behind){const i=head?rows.findIndex(r=>r.id.startsWith(head)):-1; return i>=0?rows.slice(i):behind&&rows.length?null:rows;}
// Whether document k changed since this device last saw it, and if so says so (docUpdateNote). The first visit of a document
// on a device, and this tab's own rebuild that brought nothing new (ctx.mine), record what shows as seen - unless a change
// not yet seen stands, which the rebuild then joins. What shows is the shown build's (docBuild): its commit, not the
// checkout's newest - a checkout pulled ahead of the pages still has those commits to say when their build comes. When which
// commits it carries is not known (shownRows), no commit is recorded (''): the next change then names none (describeCommits).
// What shows being older than what this device has seen (verAfter) is no change: this tab has not caught up yet - a drawn
// document come back to shows the lines it was left with until it draws its source again, whose change was said while it
// was off screen - and the read that catches up has nothing new to say either. What this device has seen is read again once
// the history has answered: another tab (limnSeen is shared) may have seen this version or a later one meanwhile - then
// nothing is said, and what this tab kept for the change (its tinted lines, its counted moves) goes as if its message had
// been seen (updForget) - or a version between the one read first and this one: the commits are counted from its commit.
// Whether this is a first visit is decided again then: a record another tab made meanwhile of this version or a later one
// stays - this answer may name an older commit - and one of an earlier version makes it a change to say. A history (or a
// build) that could not be read is not known, never an empty one: the check gives up, records nothing and asks again for
// the calls it stood for.
/** @param {string} k @param {{mine?:boolean}} ctx */
async function checkDocUpdate(k,ctx){if(!k)return; const now=updDocState(k); if(!now)return; const seen=seenDoc(k),open=GROUPS.has('upd:'+k);
  if(seen&&(seen.ver===now.ver&&!open||verAfter(seen.ver,now.ver)))return;
  const first=!seen||(!!ctx.mine&&!open); if(seen&&!first&&seen.ver===now.ver)return;
  // A check of this version is reading the history: it says it - and if it gives up (its reads failed, or another version
  // came), it asks again for the calls it stood for (again), so no version is left unchecked by one that did not finish.
  const out=UPD.checking.get(k); if(!ctx.mine&&out&&out.ver===now.ver){out.again=true; return;}
  const mark={ver:now.ver,again:false}; UPD.checking.set(k,mark);
  let rows,build; try{[rows,build]=await Promise.all([docRows(k),docBuild(k,now)]);}
  finally{if(UPD.checking.get(k)===mark)UPD.checking.delete(k);}
  const cur=updDocState(k);
  // gave up - a newer change's own check says it (the redraw asks); a history or a build that could not be read is not
  // known, never an empty one: nothing is said or recorded on it
  if(!cur||cur.ver!==now.ver||!build||!rows){if(mark.again)checkDocUpdate(k,{}); return;}
  // what this device has seen, read again, decides: another tab may have recorded this version or a later one meanwhile -
  // a first visit's late answer never overwrites that (its commit may be older) - or a message of this document come
  const kept=seenDoc(k),last=kept||seen,other=!!kept&&(!seen||kept.ver!==seen.ver||kept.rev!==seen.rev);
  const fresh=!last||(!!ctx.mine&&!GROUPS.has('upd:'+k));
  if(last&&(!fresh||other)&&(last.ver===now.ver||verAfter(last.ver,now.ver))){if(!GROUPS.has('upd:'+k))updForget(k); return;}
  const shown=shownRows(rows,build.head,build.behind);
  if(fresh||!last){setSeenDoc(k,{ver:now.ver,rev:!shown?'':shown.length?shown[0].id:last?last.rev:''}); return;}
  const commits=describeCommits(shown,last.rev);
  groupNote('upd:'+k,{key:k,name:now.name,kind:now.kind,ver:now.ver,seenRev:last.rev,top:commits.unknown?commits.top:commits.top||last.rev,commits,history:rows.length>0},docUpdateView,null);}
// Every document, the one on screen first: what changed since this device last saw it (boot).
function checkDocsSeen(){[DOC,...DOCS.map(d=>d.key).filter(k=>k!==DOC)].forEach(k=>{if(k)checkDocUpdate(k,{});});}
// What document k's update message says (groupNote's view): '<name>이(가) 바뀌었습니다' and then the commits (one: its PR and
// subject and author; several: how many, their PRs and authors; none named when which are new is not known), the places a
// drawn document changed, the pins it moved or lost. Its action: [바뀐 곳] on a drawn document of this visit with places,
// else [변경 보기] when there are commits (the changes view on just them, or as it opens when which are new is not known),
// [열기] for another document - whose message stands behind this one's (back) - none otherwise. It is seen - limnSeen takes
// it - once it goes by [x] or its action; a message pushed off the line is not seen and comes again on the next visit.
/** @param {any} d */
function docUpdateView(d){const k=d.key,c=d.commits,here=k===DOC,parts=[],mv=UPD.moved.get(k),lines=here?UPD.lines.get(k):null;
  if(c.unknown){/* the change is said without its commits */}
  else if(c.n===1){parts.push((c.prs[0]?'PR #'+c.prs[0]+' ':'')+c.subject); if(c.authors[0])parts.push(c.authors[0]);}
  else if(c.n>1){parts.push(tl(c.more?'커밋 {n}개 넘게':'커밋 {n}개',{n:c.n})); if(c.prs.length)parts.push(c.prs.slice(0,3).map(/** @param {number} n */n=>'PR #'+n).join(', ')+(c.prs.length>3?' …':''));
    if(c.authors.length)parts.push(c.authors.slice(0,2).join(', ')+(c.authors.length>2?' '+tl('외 {n}명',{n:c.authors.length-2}):''));}
  else parts.push(tr(isFigureKind(d.kind)?'그림을 새로 가져왔습니다':isViewOnlyKind(d.kind)?'PDF를 새로 그렸습니다':'커밋 없이 파일이 바뀌었습니다'));
  if(lines&&lines.ranges.length)parts.push(tl('바뀐 곳 {n}',{n:lines.ranges.length}));
  if(mv&&mv.moved.size)parts.push(tl('핀 {n}개 줄 이동',{n:mv.moved.size}));
  if(mv&&mv.lost.size)parts.push(tl('핀 {n}개 위치 잃음',{n:mv.lost.size}));
  const act=!here?{label:'열기',tip:'그 문서로 바꿉니다',fn:()=>switchDoc(k)}
    :lines&&lines.ranges.length?{label:'바뀐 곳',tip:'바뀐 줄로 갑니다. 다시 누르면 다음 곳으로 갑니다',stay:true,fn:()=>updGoNext(k)}
    :c.unknown&&d.history?{label:'변경 보기',tip:'변경 보기를 엽니다',fn:()=>openUpdateRange(k,'')}
    :c.n>0&&d.history?{label:'변경 보기',tip:'새로 들어온 커밋만 변경 보기에서 엽니다',fn:()=>openUpdateRange(k,d.seenRev,d.top)}:null;
  const title=tl('{name}{p} 바뀌었습니다',{name:d.name,p:josaName(d.name,'이','가')});
  return {msg:parts.length?title+' — '+parts.join(' · '):title,kind:NOTICE_KIND.INFO,act,
    o:{literal:true,keep:true,back:!here,brief:title,onEnd:(/** @type {boolean} */acted,/** @type {boolean} */seen)=>{if(acted||seen)docUpdateSeen(k,d);}}};}
// Document k's update message has been seen: limnSeen takes what it said, and its moved pins and changed lines go
// (updForget). A record of the message's own version is another tab's - the message is said only while the record names
// an earlier one (checkDocUpdate) - and stays: that tab read the history too, perhaps after a commit this message missed.
/** @param {string} k @param {any} d */
function docUpdateSeen(k,d){const was=seenDoc(k); if(!was||was.ver!==d.ver)setSeenDoc(k,{ver:d.ver,rev:d.top}); updForget(k);}
// What this tab kept for a change of document k that is seen - its moved pins and its tinted lines - goes. Moves that come
// after this belong to no message that is due (updPinMoved).
/** @param {string} k */
function updForget(k){UPD.moved.delete(k); UPD.seenAt.set(k,Date.now()); if(UPD.lines.delete(k))updMarks();}
// A source or a build is changing (polling.js): for UPD_EXPECT_MS its pins' moves wait for its document's update message.
// fresh: a source changed now - the wait starts now, so a message seen before it does not end it (updPinMoved).
/** @param {boolean} [fresh] */
function updExpect(fresh){const t=Date.now(); if(fresh||UPD.expect<t)UPD.expectAt=t; UPD.expect=t+UPD_EXPECT_MS;}
// Pin p moved its lines (lost: lost its place) - counted for its document's update message while that stands or is due, and
// said there. Due: a change is awaited (updExpect) that this document's message has not been seen for since - after [x] on
// that message a late move (a maintenance save of the moved place, ADR-0028) is said on its own, not taken into a message
// that has gone. Returns whether a moved pin is said there (its own message is then left out); a lost pin is always said on
// its own as well, for it asks for a new place.
/** @param {Pin} p @param {boolean} lost @returns {boolean} */
function updPinMoved(p,lost){const k=pdoc(p),g=GROUPS.get('upd:'+k),t=Date.now();
  if(!g&&!(UPD.expect>=t&&(UPD.seenAt.get(k)||0)<UPD.expectAt))return false;
  let m=UPD.moved.get(k); if(!m){m={moved:new Set(),lost:new Set()}; UPD.moved.set(k,m);} (lost?m.lost:m.moved).add(p.id);
  if(g&&g.n&&NOTICES.has(g.n.n))regroup(g.n,docUpdateView(g.data)); return !lost;}
// The changes view on the commits the message named, on document k: its source diff of base (the last seen commit) → top
// (the newest it named - the shown build's, not the checkout's newest: a checkout ahead of the pages, or a commit come
// since the message, is not in it), the list painting just them (revisions.js REV.want); without base, the view as it
// opens. Another document is switched to first.
/** @param {string} k @param {string} base @param {string} [top] */
function openUpdateRange(k,base,top){const go=()=>{REV.want={base,top:top||''}; REV.target=null;   // the view opened for a pin shows the message's range now, not that pin's commit
  if(document.body.classList.contains('revision-open'))loadRevisions(); else setViewMode(VIEW_MODE.REVISIONS);};
  if(k===DOC){go(); return;} const opening=switchDoc(k),visit=SWITCHSEQ; opening.then(()=>{if(DOC===k&&visit===SWITCHSEQ)go();});}

// ---------------- A drawn document's changed lines
// The source of drawn document k was drawn (md-surface.js mdBuild); before: the lines it replaced on screen (null on the
// visit's first draw). The lines that differ from the base - the lines before the change not yet seen began, kept while
// its message stands - are tinted (md-upd) while that message stands, and the message says how many places and goes to
// them. A later change before it is seen is compared with that base again, not with the lines just drawn, so a place changed
// first stays tinted and counted beside the new one; a return to the document compares what it draws now. A change this
// device has seen already - its message dismissed while the document was off screen, or in another tab - is no base: the
// lines it drew are not compared, so no tint stands that no message would take away.
/** @param {string} k @param {string[]|null} before @param {string[]} now */
function updSourceRedrawn(k,before,now){const u=UPD.lines.get(k),seen=seenDoc(k),cur=updDocState(k);
  const base=u?u.base:before&&seen&&cur&&verAfter(cur.ver,seen.ver)?before:null;
  // the first draw of a visit asks too: a change that came between the page's meta and this draw made the boot's check
  // give up (its version no longer the one on screen), and nothing else would ask until the next change
  if(!base){checkDocUpdate(k,{}); return;}
  const ranges=lineChanges(base,now,LINE_DIFF_MAX); if(!u&&!ranges.length)return;
  const same=!!u&&JSON.stringify(u.ranges)===JSON.stringify(ranges);
  UPD.lines.set(k,{base,ranges,at:u&&same?u.at:-1}); updMarks();
  if(before){checkDocUpdate(k,{}); return;}
  const g=GROUPS.get('upd:'+k); if(!same&&g&&g.n&&NOTICES.has(g.n.n))regroup(g.n,docUpdateView(g.data));}
// Tints the changed lines of the document on screen (after every draw of it, md-surface.js mdShow), and only those.
function updMarks(){$$('#md .md-upd').forEach(e=>e.classList.remove('md-upd')); const u=UPD.lines.get(DOC||''); if(!u||!isMdDoc())return;
  u.ranges.forEach(r=>mdLeaves(r.lo,r.hi).forEach(e=>e.classList.add('md-upd')));}
// [바뀐 곳]: the next changed place (the first after the last), scrolled to the reading depth and flashed like a pin's lines.
/** @param {string} k */
function updGoNext(k){if(k!==DOC){switchDoc(k); return;} const u=UPD.lines.get(k); if(!u||!u.ranges.length)return;
  u.at=(u.at+1)%u.ranges.length; const r=u.ranges[u.at],els=mdLeaves(r.lo,r.hi); if(!els.length)return;
  pvShow(); const L=$('#left'),lr=L.getBoundingClientRect(),er=els[0].getBoundingClientRect(); L.scrollTop+=er.top-(lr.top+lr.height*0.30);
  els.forEach(e=>{e.classList.remove('md-flash'); void e.offsetWidth; e.classList.add('md-flash');}); setTimeout(()=>els.forEach(e=>e.classList.remove('md-flash')),1200);}

// ---------------- Others' new pins
// Each pin snapshot (list.js applyPinLists): pins others made since the highest number this tab - or, on the first snapshot,
// this device (limnSeen.pin) - had seen, one message per document. The first visit of a device says nothing.
/** @param {Pin[]} rows */
function updNewPins(rows){const me=(META&&META.me&&META.me.login)||'',max=(rows||[]).reduce((m,p)=>Math.max(m,p.id),0);
  // the highest this device has seen stands even when the pins above the list's highest were deleted since: one restored
  // later keeps its number, and it is no new pin
  if(UPD.top===null){const seen=seenPin(); UPD.top=Math.max(max,seen===null?0:seen); if(seen===null||seen>=max){setSeenPin(max); return;} announceNewPins(freshPins(rows,seen,me)); return;}
  const fresh=freshPins(rows,UPD.top,me); UPD.top=Math.max(UPD.top,max);
  if(fresh.length)announceNewPins(fresh); else if(![...GROUPS.keys()].some(g=>g.startsWith('new:')))setSeenPin(UPD.top);}
/** @param {Pin[]} pins */
function announceNewPins(pins){const by=new Map(); pins.forEach(p=>{const k=pdoc(p); if(!by.has(k))by.set(k,[]); by.get(k).push(p);});
  if(!pins.length){setSeenPin(UPD.top||0); return;}
  by.forEach((list,k)=>groupNote('new:'+k,{doc:k,pins:list.map(p=>({id:p.id,who:who(p.author)||tr('누군가'),verdict:p.verdict||'',
      place:p.page?tl('{n}쪽',{n:p.page}):typeof p.lo==='number'?'L'+p.lo:'',note:String(p.note||'').split('\n')[0].slice(0,40)}))},newPinsView,
    (a,b)=>({doc:a.doc,pins:[...a.pins,...b.pins.filter(/** @param {any} x */x=>!a.pins.some(/** @param {any} y */y=>y.id===x.id))]})));}
// What a document's new-pins message says: one pin by its number, who made it, where and the start of its memo ('새 핀 #14 —
// Bob Park · 3쪽 · 서론 첫 문장…', a verdict pin '새 판정 #15 — … · 채택'); more as a count with their numbers and makers.
// Another document's names it ('부록에 새 핀 2개'). [보기] opens the first; on this document it marks [핀 N].
/** @param {any} d */
function newPinsView(d){const here=d.doc===DOC,ps=d.pins,one=ps.length===1,p=ps[0],info=docInfo(d.doc),name=info?info.name:d.doc;
  const head=one?tl(p.verdict?'새 판정 #{id}':'새 핀 #{id}',{id:p.id}):tl('새 핀 {n}개',{n:ps.length});
  const desc=one?[p.who,p.place,p.verdict||p.note].filter(Boolean).join(' · ')
    :ps.slice(0,3).map(/** @param {any} x */x=>'#'+x.id).join(', ')+(ps.length>3?' '+tl('외 {n}개',{n:ps.length-3}):'')+' · '+[...new Set(ps.map(/** @param {any} x */x=>x.who))].slice(0,2).join(', ');
  return {msg:(here?head:tl('{doc}에 {what}',{doc:name,what:head}))+' — '+desc,kind:NOTICE_KIND.INFO,
    act:{label:here?'보기':'열기',tip:'그 핀으로 갑니다',fn:()=>openPinFromLink(d.doc,p.id)},
    o:{literal:true,back:!here,dot:here?NOTICE_DOT.SIDE:'',keys:ps.map(/** @param {any} x */x=>'new:'+x.id),brief:tl('새 핀 {n}',{n:ps.length}),
      onEnd:(/** @type {boolean} */acted,/** @type {boolean} */seen)=>{if((acted||seen)&&![...GROUPS.keys()].some(g=>g.startsWith('new:')))setSeenPin(UPD.top||0);}}};}

// ---------------- Limn itself was updated
// The page's version (the [더보기] foot's 'v0.4.51', filled in when the server made the page) and the server's (GET
// /api/version, asked by polling.js after a lost connection comes back, on return and every VERSION_EVERY_MS): when they
// differ, this tab runs the old viewer against a new server, and the status line says so with [새로 고침] until it reloads.
const VERSION={page:'',server:'',at:0,busy:false};
const VERSION_EVERY_MS=60000;
function versionDue(){return Date.now()-VERSION.at>=VERSION_EVERY_MS;}
function versionOutdated(){if(!VERSION.page){const e=document.querySelector('#more-foot .m-ver'); VERSION.page=e?String(e.textContent||'').trim().replace(/^v/,''):'';}
  return VERSION.server&&VERSION.page&&VERSION.server!==VERSION.page?VERSION.server:'';}
async function checkVersion(){if(VERSION.busy)return; VERSION.busy=true; VERSION.at=Date.now();
  try{const r=(await api('/api/version',{what:'버전 확인',silent:true})).data,v=String((r&&r.version)||'');
    if(v&&v!==VERSION.server){const was=versionOutdated(); VERSION.server=v; if(versionOutdated()!==was)drawStatus();}}
  catch(e){} finally{VERSION.busy=false;}}
// [새로 고침]: reloads this tab - the composer's draft and the reading spot are kept (sessionStorage), what waits behind an undo
// is sent first - unless a reply or an edit is being written, which a reload would lose: that is said instead.
function reloadForUpdate(){const r=REPLY&&replyNote(REPLY),typing=!!(r&&r.value.trim())||REPLY_DRAFT.size>0||editDirty();
  if(typing){lineNote('쓰던 답글이나 수정이 있습니다 — 보내거나 저장한 뒤 새로 고치세요',NOTICE_KIND.WARN,null,{source:'reload-typing',digest:false}); return;}
  flushDeferred(); location.reload();}
