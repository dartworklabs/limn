// ------------------------------------------------ The text surface (ADR-0029, docs/superpowers/specs/2026-11-05-text-documents.md)
// A text document (showsSourceLines: kind "text" - plain text or source code) is drawn in the browser as the Markdown surface's
// documents are (md-surface.js: GET /api/source, the reading spot, marks, badges, picks, the composer), but it is never parsed:
// every server line is one line span (data-line), numbered in the gutter by CSS, in a monospace column that wraps.
// - The DOM is built with createElement and textContent only, within the Markdown surface's limits (MD_LIMITS): over
//   MD_LIMITS.lines lines there is no view but its notice; the elements drawn - one per line, two per marked character -
//   stay under MD_LIMITS.elements, and past it the view is the names view (each marked character's name as plain text, one
//   element per line); a yield to the browser after every MD_LIMITS.chunk units of work (a line, a character of the
//   repertoire), within a long line too, and a newer draw (stale) drops the build at each yield.
// - Nothing in the text is a link, an image or markup: it is only ever text.
// - A character that would hide or reorder text (the repertoire of hidden-chars.js) stays in the text, so a copy keeps it,
//   inside an isolating span that shows its name (ccBox); a line of the view never reads in another order than its source. A
//   notice above the lines counts them. Another notice names the line ends the server split on that are not LF or CRLF
//   (/api/source line_ends): Limn numbers lines past them as str.splitlines() does, an editor that counts LF alone does not.
// - A wrapped line's continuation hangs under its indentation, rounded down to a tab stop (txHang), so a tab still lands on the
//   same stop as in an editor whose tabs are TX_TAB columns wide.
// - The ladder is: the chosen lines -> the paragraph between blank lines (para, or the paragraphs the lines meet: blocks, saved
//   as lines) -> the indented block the lines head or stand in (indent). txLevels reads the server's lines alone.
const TX_TAB=4;           // the columns a tab spans (CSS tab-size of the view, and txCols)
const TX_HANG_MAX=16;     // the most columns a wrapped line's continuation hangs: a phone keeps room for the text
const TX_LABEL=12;        // the most characters of a block's header its rung's label shows
// Whether the document on screen is a text document (shown line for line, never parsed).
function isTextDoc(){return !!META&&showsSourceLines(META.kind);}
// ---------------- Lines, columns and blocks: pure but for tl/tr
// The columns a line's leading whitespace spans, tabs to the next multiple of tab, or -1 for a blank line (only whitespace).
/** @param {string} line @param {number} [tab] */
function txCols(line,tab){const t=tab||TX_TAB; let c=0; for(const ch of String(line)){if(ch===' ')c++; else if(ch==='\t')c+=t-c%t; else return c;} return -1;}
// How far a wrapped line's continuation hangs, in columns, at most TX_HANG_MAX: its indentation, rounded down to a tab stop when
// the line holds a tab - the first line then starts on a stop, so each tab lands where it does in an editor.
/** @param {string} line */
function txHang(line){const c=txCols(line); if(c<=0)return 0; return Math.min(TX_HANG_MAX,String(line).includes('\t')?c-c%TX_TAB:c);}
// The paragraph of lines lo..hi (1-based, inclusive): the lines widened to the blank lines around them, and how many
// paragraphs - runs of non-blank lines - they meet. null when lo..hi holds only blank lines.
/** @param {string[]} lines @param {number} lo @param {number} hi */
function txParagraph(lines,lo,hi){const blank=(/** @type {number} */n)=>!String(lines[n-1]||'').trim();
  let a=lo,b=hi; while(a<=b&&blank(a))a++; while(b>=a&&blank(b))b--; if(a>b)return null;
  while(a>1&&!blank(a-1))a--; while(b<lines.length&&!blank(b+1))b++;
  let n=0,inside=false; for(let k=a;k<=b;k++){const nb=!blank(k); if(nb&&!inside)n++; inside=nb;}
  return {lo:a,hi:b,n};}
// A line that closes the block above it at the header's own depth, and so belongs to it: one that starts with a closing
// bracket ('}', ')', ']', as '} else {' or '});'), or whose statement is a closing word alone - a shell's fi, done or esac,
// Ruby's, Lua's, Julia's or MATLAB's end - followed by nothing, ';', ',', ')', a shell redirection or pipe ('done < list'), or
// a comment. A call or an assignment of a name spelt so ('done()', 'end = 3', 'done.append(x)') is no closer.
const TX_CLOSER=/^(?:[\]\)}]|(?:end|fi|done|esac)\s*(?:$|[;,)<>|&]|#|--|%|\/\/))/;
// The indented block of lines lo..hi: the block they head when the next non-blank line below is deeper than they are, else the
// block they stand in, under the nearest line above that is shallower than they are. It runs from its header to the last line
// before the next non-blank line no deeper than the header, taking that line too when it closes the block (TX_CLOSER), less
// trailing blank lines. {lo,hi,title} - title is the header's text - or null when no such header is found (an unindented
// paragraph of prose, a file's top level).
/** @param {string[]} lines @param {number} lo @param {number} hi */
function txIndentBlock(lines,lo,hi){const col=(/** @type {number} */n)=>txCols(String(lines[n-1]||''));
  let m=Infinity; for(let k=lo;k<=hi;k++){const c=col(k); if(c>=0&&c<m)m=c;} if(m===Infinity)return null;
  let next=hi+1; while(next<=lines.length&&col(next)<0)next++;
  let h=-1;
  if(next<=lines.length&&col(next)>m&&col(lo)===m)h=lo;                  // the lines head a deeper body
  else for(let k=lo-1;k>=1;k--){const c=col(k); if(c>=0&&c<m){h=k; break;}}   // the lines stand in the block of a shallower line above
  if(h<0)return null; const d=col(h);
  let end=lines.length; for(let k=Math.max(hi,h)+1;k<=lines.length;k++){const c=col(k); if(c>=0&&c<=d){end=c===d&&TX_CLOSER.test(String(lines[k-1]).trim())?k:k-1; break;}}
  while(end>h&&col(end)<0)end--; if(end<hi)end=hi;
  return {lo:h,hi:end,title:String(lines[h-1]||'').trim()};}
// The ladder for lines r of the text on screen: the chosen lines, then their paragraph (or the paragraphs they meet, saved as
// lines) and their indented block, the shorter first; a rung with the range of one before it merges into that one (as mdLevels
// does). Array.prototype.sort is stable, so rungs of one length keep that order.
/** @param {{lo:number,hi:number}} r */
function txLevels(r){const ls=/** @type {any[]} */([]),lines=MD.lines;
  const add=(/** @type {string} */level,/** @type {string} */label,/** @type {number} */lo,/** @type {number} */hi,/** @type {string|null} */tip)=>{const same=ls.find(l=>l.lo===lo&&l.hi===hi);
    if(same){(same.merged=same.merged||[]).push(level); return;} ls.push({level,label,lo,hi,n:hi-lo+1,snippet:mdSnippet(lo,hi),env:null,tip});};
  add('raw','고른 줄',r.lo,r.hi,null);
  const p=txParagraph(lines,r.lo,r.hi);
  if(p&&p.n>1)add('blocks',tl('문단 {n}개',{n:p.n}),p.lo,p.hi,'txparas'); else if(p)add('para','문단',p.lo,p.hi,'txpara');   // T.txpara: no % comment rule here
  const b=txIndentBlock(lines,r.lo,r.hi); if(b)add('indent',tr('블록')+' · '+ccClip(b.title,TX_LABEL),Math.min(b.lo,r.lo),Math.max(b.hi,r.hi),null);   // the header's hidden characters by name (ccClip)
  const [raw,...wider]=ls; wider.sort((a,b)=>a.n-b.n); return [raw,...wider];}   // widening: the smaller of the paragraph and the block first
// ---------------- Drawing
// Line n's span (ln its text): the hang of its continuation (txHang) through CSSOM, no text yet.
/** @param {string} ln @param {number} n */
function txSpan(ln,n){const s=document.createElement('span'); s.className='ln'; s.dataset.line=String(n);
  const h=txHang(ln); if(h)s.style.setProperty('--hang',String(h)); return s;}
// Builds article#md for the text document on screen from MD.lines (srcLines): each line's text, each marked character in its
// box (ccBox), the text ending in "\n" so that a selection's text keeps its line ends. Within MD_LIMITS (the header above):
// past MD_LIMITS.elements it gives the names view instead; null when a newer draw came (stale) at a yield.
// ends: /api/source's line_ends.
/** @param {()=>boolean} stale @param {Record<string,number>|undefined} ends @returns {Promise<HTMLElement|null>} */
async function txView(stale,ends){const r=await srcLines(txSpan,'tx-src',stale); if(!r)return null;
  if(r.names)return txRoot(r.body,ends,txNamesText(r.marked),MD_LIMIT.ELEMENTS);
  return txRoot(r.body,ends,r.marked?txMarksText(r.marked):'',null);}
// The source lines on screen (MD.lines) as line spans in a new div of class cls - span(ln, n) makes line n's span, empty - for
// the text surface (txView) and the Markdown surface's line view (mdLineView). Each marked character (hidden-chars.js) is its
// box (ccBox) while the elements drawn stay within MD_LIMITS.elements: one a line, two a box, counted on every line, not only
// on a box (plain lines after a line of boxes). Past it, the names form: each line one span whose text has every marked
// character as its name in angle brackets ('⟨U+200B⟩', ccPlain's form) - one element a line, never a raw character that
// reorders the line; a copy of it gives the names, not the characters (txNamesText says so). A yield to the browser after
// every MD_LIMITS.chunk units of work (a line, a character of the repertoire), within a long line too. -> {body, marked (how
// many characters it marked), names (the names form)}, or null when a newer draw came (stale) at a yield.
/** @param {(ln:string,n:number)=>HTMLElement} span @param {string} cls @param {()=>boolean} stale
    @returns {Promise<{body:HTMLElement,marked:number,names:boolean}|null>} */
async function srcLines(span,cls,stale){const lines=MD.lines,w={n:0};
  for(const names of [false,true]){const body=document.createElement('div'); body.className=cls; let els=0,marked=0,over=false;
    for(let i=0;i<lines.length&&!over;i++){const ln=lines[i],s=span(ln,i+1); let at=0,out='';
      if(!names&&++els>MD_LIMITS.elements){over=true; break;}
      for(const c of ccScan(ln,i===0)){if(mdDue(w)){await mdYield(); if(stale())return null;}
        if(!c)continue;
        if(names)out+=ln.slice(at,c.at)+'\u27e8'+ccName(c.ch.codePointAt(0)||0)+'\u27e9';
        else{if((els+=2)>MD_LIMITS.elements){over=true; break;} if(c.at>at)s.append(ln.slice(at,c.at)); s.append(ccBox(c.ch));}
        at=c.at+c.ch.length; marked++;}
      if(over)break;
      if(names)s.textContent=out+ln.slice(at)+'\n'; else s.append(ln.slice(at)+'\n');
      body.appendChild(s);
      if(mdDue(w)){await mdYield(); if(stale())return null;}}
    if(!over)return {body,marked,names};}
  return null;}   // never reached: the names form has no limit to pass
// What the notice above the lines says of the characters marked: n boxes, or the names form for n of them.
/** @param {number} n */
function txMarksText(n){return tl('보이지 않거나 글 순서를 바꾸는 문자 {n}개를 이름으로 표시했습니다',{n:mdCount(n)});}
/** @param {number} n */
function txNamesText(n){return tl('보이지 않거나 글 순서를 바꾸는 문자가 {n}개라 이름을 글자로 보입니다(그릴 요소 한도 {max}개). 이 보기에서 복사하면 그 문자 대신 이름이 복사됩니다',
  {n:mdCount(n),max:mdCount(MD_LIMITS.elements)});}
// A notice above a document's text (kind: its data-note - 'marks', 'ends'): out of the text, never selected or copied with it, in
// the viewer's words and so in the screen's language. A Markdown document's notice is the same element (mdRenderAll, mdLineView).
/** @param {string} kind @param {string} text */
function txNote(kind,text){const n=document.createElement('div'); n.className='md-limit tx-note';
  n.dataset.note=kind; n.setAttribute('role','status'); n.textContent=text; n.lang=document.documentElement.lang; return n;}
// article#md round the lines (body): the notices above them - what was marked (marks, '' for none) and the line ends that are
// not LF or CRLF (txEndsText) - and the limit the view hit (limit, its data-limit; null for none).
/** @param {HTMLElement} body @param {Record<string,number>|undefined} ends @param {string} marks @param {string|null} limit */
function txRoot(body,ends,marks,limit){const root=document.createElement('article'); root.className='md tx'; root.id='md'; root.setAttribute('translate','no'); root.lang='';   // as mdRenderAll's: the text's language is not known
  if(limit)root.dataset.limit=limit;
  root.style.setProperty('--gut',String(String(MD.lines.length).length+1));
  for(const [kind,text] of [['marks',marks],['ends',txEndsText(ends)]])if(text)root.appendChild(txNote(kind,text));
  root.appendChild(body); return root;}
// The notice for the line ends of the source that are not LF or CRLF (ends: {name: count}, /api/source line_ends - 'U+000C',
// 'U+2028', a lone CR as 'U+000D'), or '' when there are none. Limn numbers lines past them; an editor or git that counts LF
// alone does not, and a copy joins the lines with LF.
/** @param {Record<string,number>|undefined} ends */
function txEndsText(ends){const e=Object.entries(ends||{}).filter(([k,n])=>/^U\+[0-9A-F]{4,6}$/.test(k)&&Number(n)>0); if(!e.length)return '';
  const n=e.reduce((a,[,c])=>a+Number(c),0);
  return tl('줄 끝 {n}곳이 LF가 아닙니다({kinds}). Limn은 거기서 줄을 나누므로, 줄 번호가 LF만 세는 편집기·git과 다를 수 있고 복사하면 LF로 바뀝니다',
    {n:mdCount(n),kinds:e.map(([k,c])=>k+' '+mdCount(c)).join(', ')});}
// The empty list's help (#empty) for a text document: a line is picked by a press, lines by a drag.
function txHint(){const e=$('#empty'); if(!e)return;
  setHtml(e,html`<span class="t-mouse"><b>${tr('줄을 누르면')}</b> ${tr('그 줄을,')} ${tr('글을')} <b>${tr('끌어')}</b> ${tr('고르면 그 줄들을 고르고')}</span><span class="t-touch"><b>${tr('줄을 누르면')}</b> ${tr('그 줄을,')} <b>${tr('길게 눌러')}</b> ${tr('글을 고르면 그 줄들을 고르고')}</span> ${tr('그 자리의')} <b>${tr('원문 줄 번호')}</b>${tr('가 핀의 위치가 됩니다.')}<br>
    ${tr('메모를 달아 핀으로 저장하면, 에이전트가 pins.md 한 장만 읽고 작업합니다.')}<br><span class="t-mouse"><kbd>?</kbd> ${tr('를 누르면 도움말.')}</span><span class="t-touch">${tr('도움말은 [더보기]에 있습니다.')}</span>`);}
