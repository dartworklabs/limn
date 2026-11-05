// ------------------------------------------------ Characters that hide or reorder text (ADR-0029 D5, docs/superpowers/specs/2026-11-05-text-documents.md §결정 5)
// A bidirectional control can make a line read in another order than its source, and a zero-width, filler or control
// character can make two texts look the same (Trojan Source, CVE-2021-42574). Every place that shows a source's or a
// suggestion's text as it is - the text surface's lines, the excerpt under the ladder, a suggestion's diff, a rung's label -
// marks them, for every document kind, with this one repertoire, in one of two forms:
// - ccBox, ccHtml: the character stays in the text (a copy keeps it) inside an isolating span (.cc) that shows its name.
// - ccPlain: its name in angle brackets ('⟨U+202E⟩'), where only plain text can go (a label, a tooltip, a fallback view).
// The repertoire (CC_RANGES), by code point: Unicode's Default_Ignorable_Code_Point (the soft hyphen, the combining
// grapheme joiner, the Hangul fillers, the Khmer inherent vowels, the Mongolian variation selectors and vowel separator, the
// zero-width characters and bidirectional marks, the bidirectional embeddings, overrides and isolates, the word joiner and
// invisible operators, the deprecated format characters, the variation selectors, the byte-order mark, the shorthand and
// musical format controls, the tags), every C0 and C1 control but the tab and the line feed, the line and paragraph
// separators and the interlinear annotation characters. limn.pins.listing.hidden holds the same table for pins.md; a test
// ties the two and checks this one against the engine's own Unicode properties.
// A character a legitimate sequence needs is left as it is (ccKept). Nothing else is: a tag sequence (a subdivision flag)
// shows its tags by name.
/** @type {ReadonlyArray<readonly [number,number]>} */
const CC_RANGES=Object.freeze([[0x00,0x08],[0x0b,0x1f],[0x7f,0x9f],[0xad,0xad],[0x34f,0x34f],[0x61c,0x61c],[0x115f,0x1160],
  [0x17b4,0x17b5],[0x180b,0x180f],[0x200b,0x200f],[0x2028,0x202e],[0x2060,0x206f],[0x3164,0x3164],[0xfe00,0xfe0f],[0xfeff,0xfeff],
  [0xffa0,0xffa0],[0xfff0,0xfffb],[0x1bca0,0x1bca3],[0x1d173,0x1d17a],[0xe0000,0xe0fff]].map(r=>Object.freeze(/** @type {[number,number]} */(r))));
// The repertoire as one regular expression over code points (a supplementary character is one match, never two halves).
const CC_RE=new RegExp('['+CC_RANGES.map(([a,b])=>'\\u{'+a.toString(16)+'}'+(b>a?'-\\u{'+b.toString(16)+'}':'')).join('')+']','gu');
const CC_ANY=new RegExp(CC_RE.source,'u');   // the same, for a test that keeps no state
// The scripts whose ordinary text puts a zero-width joiner or non-joiner between two of its letters (Persian, Indic
// conjuncts and half forms, Syriac, Mongolian), an emoji's pictograph, a Han ideograph and a Mongolian letter.
const CC_JOINING=/[\p{sc=Arabic}\p{sc=Syriac}\p{sc=Mongolian}\p{sc=Devanagari}\p{sc=Bengali}\p{sc=Gurmukhi}\p{sc=Gujarati}\p{sc=Oriya}\p{sc=Tamil}\p{sc=Telugu}\p{sc=Kannada}\p{sc=Malayalam}\p{sc=Sinhala}]/u;
const CC_PICTO=/\p{Extended_Pictographic}/u,CC_HAN=/\p{sc=Han}/u,CC_MONGOLIAN=/\p{sc=Mongolian}/u;
// The name a marked character shows: a C0 control's picture (the U+2400 block), DEL's, else its code point (U+202E,
// U+E0041). Pure.
/** @param {number} c */
function ccName(c){if(c<0x20)return String.fromCodePoint(0x2400+c); if(c===0x7f)return '␡';
  return 'U+'+c.toString(16).toUpperCase().padStart(4,'0');}
// The code point just before index i of s (a surrogate pair whole), or -1 at its start; and the one at index i, or -1 past it.
/** @param {string} s @param {number} i */
function ccBefore(s,i){if(i<=0)return -1; const lo=s.charCodeAt(i-1); if(i>=2&&lo>=0xdc00&&lo<=0xdfff){const hi=s.charCodeAt(i-2); if(hi>=0xd800&&hi<=0xdbff)return s.codePointAt(i-2)??-1;} return lo;}
/** @param {string} s @param {number} i */
function ccAt(s,i){return i<s.length?(s.codePointAt(i)??-1):-1;}
/** @param {number} c @param {RegExp} re */
function ccIn(c,re){return c>=0&&re.test(String.fromCodePoint(c));}
// Whether the marked character c at index i of s is one a legitimate sequence needs, and so is left as it is - the
// exceptions, each tested:
// - a byte-order mark at the very start of a file (first: s is its line 1): the encoding's mark, not text;
// - a zero-width non-joiner or joiner between two letters or marks of a script that joins with them (CC_JOINING);
// - a zero-width joiner inside an emoji sequence: after a pictograph, a skin-tone modifier or VS16, before a pictograph;
// - VS15 or VS16 after a pictograph, and VS16 in a keycap ([#*0-9] U+FE0F U+20E3);
// - a variation selector after a Han ideograph (an ideographic variation sequence, as in a Japanese name);
// - a Mongolian free variation selector after a Mongolian letter;
// - the Hangul choseong filler before a real jungseong, the jungseong filler after a real choseong (old Hangul written in
//   conjoining jamo). The two fillers together, U+3164 and U+FFA0 are always marked: they draw nothing at all.
// Pure. @param {string} s @param {number} i @param {number} c @param {boolean} first
function ccKept(s,i,c,first){const p=ccBefore(s,i),n=ccAt(s,i+(c>0xffff?2:1));
  if(c===0xfeff)return first&&i===0;
  if(c===0x200c||c===0x200d){if(ccIn(p,CC_JOINING)&&ccIn(n,CC_JOINING))return true;
    return c===0x200d&&(ccIn(p,CC_PICTO)||(p>=0x1f3fb&&p<=0x1f3ff)||p===0xfe0f)&&ccIn(n,CC_PICTO);}
  if(c===0xfe0e||c===0xfe0f){if(ccIn(p,CC_PICTO))return true; if(c===0xfe0f&&n===0x20e3&&(p===0x23||p===0x2a||(p>=0x30&&p<=0x39)))return true;}
  if((c>=0xfe00&&c<=0xfe0f)||(c>=0xe0100&&c<=0xe01ef))return ccIn(p,CC_HAN);
  if((c>=0x180b&&c<=0x180d)||c===0x180f)return ccIn(p,CC_MONGOLIAN);
  if(c===0x115f)return (n>0x1160&&n<=0x11a7)||(n>=0xd7b0&&n<=0xd7c6);
  if(c===0x1160)return (p>=0x1100&&p<0x115f)||(p>=0xa960&&p<=0xa97c);
  return false;}
// Every character of s in the repertoire, in order: {at, ch} for one that is marked, null for one that is kept (ccKept) -
// so a caller can count the work either costs and pause within a long line. first: s is line 1 of a file. A generator.
/** @param {string} s @param {boolean} [first] @returns {Generator<{at:number,ch:string}|null>} */
function* ccScan(s,first){const str=String(s); if(!CC_ANY.test(str))return;   // most lines hold none: one native test
  const re=new RegExp(CC_RE.source,'gu'); let m;
  while((m=re.exec(str))){const c=m[0].codePointAt(0)||0; yield ccKept(str,m.index,c,!!first)?null:{at:m.index,ch:m[0]};}}
// The marked characters of s, in order: [{at, ch}]. Pure. @param {string} s @param {boolean} [first]
function ccFind(s,first){const out=[]; for(const c of ccScan(s,first))if(c)out.push(c); return out;}
// s with each marked character as its name in angle brackets: plain text that never reads in another order than s. Pure.
/** @param {string} s @param {boolean} [first] */
function ccPlain(s,first){const str=String(s); let out='',at=0;
  for(const c of ccFind(str,first)){out+=str.slice(at,c.at)+'⟨'+ccName(c.ch.codePointAt(0)||0)+'⟩'; at=c.at+c.ch.length;}
  return out+str.slice(at);}
// s as plain text cut to at most max characters of what it shows, a marked character's name counted whole and never cut, with
// '…' when it was cut. Reads no more of s than max + 2 characters (one past the cut keeps a joiner's context). Pure.
/** @param {string} s @param {number} max */
function ccClip(s,max){let head='',k=0; for(const ch of String(s)){if(++k>max+2)break; head+=ch;}
  const pieces=/** @type {string[]} */([]); let at=0;
  for(const c of ccFind(head)){pieces.push(...head.slice(at,c.at),'\u27e8'+ccName(c.ch.codePointAt(0)||0)+'\u27e9'); at=c.at+c.ch.length;}
  pieces.push(...head.slice(at)); let out='',n=0;
  for(const p of pieces){const w=[...p].length; if(n+w>max)return out+'…'; out+=p; n+=w;}
  return out;}
// How many marked characters of each name text holds more than base: [[name, count]] by first appearance in text, [] when it
// adds none - what a suggestion's draft puts in that its lines do not have. Each line is read on its own, as a diff shows it. Pure.
/** @param {string} text @param {string} base @returns {[string,number][]} */
function ccAdded(text,base){const count=(/** @type {string} */t)=>{const m=new Map(); for(const ln of String(t).split('\n'))for(const c of ccFind(ln)){const k=ccName(c.ch.codePointAt(0)||0); m.set(k,(m.get(k)||0)+1);} return m;};
  const a=count(text),b=count(base),out=/** @type {[string,number][]} */([]);
  for(const [k,n] of a){const d=n-(b.get(k)||0); if(d>0)out.push([k,d]);} return out;}
// A marked character ch as its box: an isolating span showing its name, the character itself in a .sr-only child - it takes no
// room, and a copy of the text keeps it.
/** @param {string} ch @returns {HTMLElement} */
function ccBox(ch){const e=document.createElement('span'); e.className='cc'; e.dataset.cc=ccName(ch.codePointAt(0)||0);
  const k=document.createElement('span'); k.className='sr-only'; k.textContent=ch; e.append(k); return e;}
// s as Html: its text, each marked character as its box (ccBox's markup). Pure.
/** @param {string} s @returns {Html} */
function ccHtml(s){const str=String(s),out=[]; let at=0;
  for(const c of ccFind(str)){out.push(str.slice(at,c.at),html`<span class="cc" data-cc="${ccName(c.ch.codePointAt(0)||0)}"><span class="sr-only">${c.ch}</span></span>`); at=c.at+c.ch.length;}
  out.push(str.slice(at)); return html`${out}`;}
