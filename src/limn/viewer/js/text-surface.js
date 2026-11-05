// ------------------------------------------------ The text surface (ADR-0029, docs/superpowers/specs/2026-11-05-text-documents.md)
// A text document (showsSourceLines: kind "text" - plain text or source code) is drawn in the browser as the Markdown surface's
// documents are (md-surface.js: GET /api/source, the reading spot, marks, badges, picks, the composer), but it is never parsed:
// every server line is one line span (data-line), numbered in the gutter by CSS, in a monospace column that wraps.
// - The DOM is built with createElement and textContent only, a yield to the browser after every MD_LIMITS.chunk lines. Over
//   MD_LIMITS.lines lines there is no view, but the notice the Markdown surface gives (mdNotice).
// - Nothing in the text is a link, an image or markup: it is only ever text.
// - A character that would hide or reorder text - a bidirectional control, a zero-width one, a control character - stays in
//   the text (so a copy keeps it) inside an isolating span that shows its name (txChars); a line of the view never reads in
//   another order than its source. A notice above the lines counts them.
// - A wrapped line's continuation hangs under its indentation, rounded down to a tab stop (txHang), so a tab still lands on the
//   same stop as in an editor whose tabs are TX_TAB columns wide.
// - The ladder is: the chosen lines -> the paragraph between blank lines (para, or the paragraphs the lines meet: blocks, saved
//   as lines) -> the indented block the lines head or stand in (indent). txLevels reads the server's lines alone.
const TX_TAB=4;           // the columns a tab spans (CSS tab-size of the view, and txCols)
const TX_HANG_MAX=16;     // the most columns a wrapped line's continuation hangs: a phone keeps room for the text
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
// A line that closes the block above it at the header's own depth: a closing bracket, or a shell's or Ruby's, Lua's, Julia's
// or MATLAB's end word. It belongs to the block.
const TX_CLOSER=/^([\]\)}]|end\b|fi\b|done\b|esac\b)/;
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
  const b=txIndentBlock(lines,r.lo,r.hi); if(b)add('indent',tr('블록')+' · '+(b.title.length>12?b.title.slice(0,12)+'…':b.title),Math.min(b.lo,r.lo),Math.max(b.hi,r.hi),null);
  const [raw,...wider]=ls; wider.sort((a,b)=>a.n-b.n); return [raw,...wider];}   // widening: the smaller of the paragraph and the block first
// ---------------- Characters that would hide or reorder text
// The name the view shows for such a character (TX_HIDDEN): a C0 control's picture (U+2400 block), DEL's, else its code point.
/** @param {number} c */
function txCharName(c){if(c<0x20)return String.fromCodePoint(0x2400+c); if(c===0x7f)return '\u2421';
  return 'U+'+c.toString(16).toUpperCase().padStart(4,'0');}
// The characters marked: bidirectional controls (embeddings, overrides, isolates, the marks LRM, RLM and ALM), the zero-width
// space, word joiner and invisible operators, a byte-order mark, and C0 and C1 controls but the tab (the server's line ends
// never reach a line). The zero-width joiner and non-joiner are left as they are: an emoji sequence and Persian or Indic text
// need them, and they reorder nothing.
const TX_HIDDEN=/[\u0000-\u0008\u000e-\u001f\u007f-\u009f\u061c\u200b\u200e\u200f\u202a-\u202e\u2060-\u2064\u2066-\u2069\ufeff]/g;
// The characters of line that the view marks (TX_HIDDEN), with where they stand: [{at, ch}]. A byte-order mark at the very start
// of the file (first: line 1) is the file's encoding mark, not text, and is left alone. Pure.
/** @param {string} line @param {boolean} [first] */
function txChars(line,first){const out=[]; TX_HIDDEN.lastIndex=0; let m;
  while((m=TX_HIDDEN.exec(line))){if(first&&m.index===0&&m[0]==='\ufeff')continue; out.push({at:m.index,ch:m[0]});} return out;}
// The snippet's form of a line (the composer's source lines): each marked character as its name in angle brackets, so a line
// of the snippet never reads in another order than its source either.
/** @param {string} line */
function txPlain(line){return String(line).replace(TX_HIDDEN,ch=>'\u27e8'+txCharName(ch.codePointAt(0)||0)+'\u27e9');}
// ---------------- Drawing
// One line span: the line's text, each marked character in its own isolating span that shows its name; the continuation's hang
// (txHang) through CSSOM. The text ends in "\n" so that a selection's text keeps its line ends.
/** @param {string} ln @param {number} n */
function txLine(ln,n){const s=document.createElement('span'); s.className='ln'; s.dataset.line=String(n);
  const h=txHang(ln); if(h)s.style.setProperty('--hang',String(h));
  const cs=txChars(ln,n===1); let at=0;
  for(const c of cs){if(c.at>at)s.append(ln.slice(at,c.at)); const e=document.createElement('span'); e.className='tx-cc'; e.dataset.cc=txCharName(c.ch.codePointAt(0)||0);
    const k=document.createElement('span'); k.className='sr-only'; k.textContent=c.ch; e.append(k); s.append(e); at=c.at+c.ch.length;}
  s.append(ln.slice(at)+'\n'); return {el:s,marked:cs.length};}
// Builds article#md for the text document on screen from MD.lines, in chunks with a check for a newer draw (stale) between
// them; null when one came. A notice above the lines counts the marked characters, when there are any.
/** @param {()=>boolean} stale @returns {Promise<HTMLElement|null>} */
async function txView(stale){const root=document.createElement('article'); root.className='md tx'; root.id='md'; root.setAttribute('translate','no');
  root.style.setProperty('--gut',String(String(MD.lines.length).length+1));
  const body=document.createElement('div'); body.className='tx-src'; let marked=0;
  for(let i=0;i<MD.lines.length;i++){const r=txLine(MD.lines[i],i+1); body.appendChild(r.el); marked+=r.marked;
    if((i+1)%MD_LIMITS.chunk===0){await mdYield(); if(stale())return null;}}
  if(marked){const n=document.createElement('div'); n.className='md-limit tx-hidden'; n.setAttribute('role','status');
    n.textContent=tl('보이지 않거나 글 순서를 바꾸는 문자 {n}개를 이름으로 표시했습니다',{n:mdCount(marked)}); root.appendChild(n);}
  root.appendChild(body); return root;}
// The empty list's help (#empty) for a text document: a line is picked by a press, lines by a drag.
function txHint(){const e=$('#empty'); if(!e)return;
  setHtml(e,html`<span class="t-mouse"><b>${tr('줄을 누르면')}</b> ${tr('그 줄을,')} ${tr('글을')} <b>${tr('끌어')}</b> ${tr('고르면 그 줄들을 고르고')}</span><span class="t-touch"><b>${tr('줄을 누르면')}</b> ${tr('그 줄을,')} <b>${tr('길게 눌러')}</b> ${tr('글을 고르면 그 줄들을 고르고')}</span> ${tr('그 자리의')} <b>${tr('원문 줄 번호')}</b>${tr('가 핀의 위치가 됩니다.')}<br>
    ${tr('메모를 달아 핀으로 저장하면, 에이전트가 pins.md 한 장만 읽고 작업합니다.')}<br><span class="t-mouse"><kbd>?</kbd> ${tr('를 누르면 도움말.')}</span><span class="t-touch">${tr('도움말은 [더보기]에 있습니다.')}</span>`);}
