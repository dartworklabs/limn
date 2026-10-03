// ------------------------------------------------ UI language (Korean source, English table)
// UI language (window.LIMN_LANG from the head script). Korean strings in this file are the source; in English
// mode tr()/trMsg() look them up in I18N_EN (src/limn/viewer/ui_en.json) and a MutationObserver translates text
// nodes and UI attributes as they are rendered. Strings missing from the table stay Korean.
const LANG=window.LIMN_LANG===UI_LANG.EN?UI_LANG.EN:UI_LANG.KO, I18N_EN=__UI_EN_JSON__, I18N_ATTRS=['data-tip','aria-label','title','placeholder'];
function tr(s){if(LANG!==UI_LANG.EN||typeof s!=='string')return s; const t=s.trim();
  if(!t||!Object.prototype.hasOwnProperty.call(I18N_EN,t)||typeof I18N_EN[t]!=='string')return s; return s.replace(t,I18N_EN[t]);}
// Composed UI strings: tl('{n}쪽',{n:3}). The Korean key is the template and the Korean output; in English the
// table value is the template - a string, or plural forms {"one":...,"other":...} picked by p.n. {x} placeholders
// are filled from p (values are inserted as given - escape them first if the result goes into HTML).
function tl(k,p){let s=k; if(LANG===UI_LANG.EN&&Object.prototype.hasOwnProperty.call(I18N_EN,k)){const v=I18N_EN[k];
    s=typeof v==='string'?v:(v&&(Number(p&&p.n)===1&&v.one?v.one:v.other))||k;}
  return s.replace(/\{(\w+)\}/g,(m,x)=>p&&p[x]!=null?String(p[x]):m);}
function trMsg(s){if(LANG!==UI_LANG.EN||typeof s!=='string')return s; const e=tr(s); if(e!==s)return e;
  for(const sep of [' — ',' · ']){if(s.indexOf(sep)>0)return s.split(sep).map(tr).join(sep);} return s;}
// An API error body {error, reason} as the UI shows it (docs/handbook/viewer.md §뷰어 규칙을 바꿀 때). Korean shows the
// server's `error` text as is - it is the agent contract (api.md §오류 응답). English looks up the stable reason code
// ('reason:<code>' in the table) and falls back to the server text through the table. '' when there is no body.
function errText(d){if(!d)return ''; const s=d.error==null?'':String(d.error);
  if(LANG===UI_LANG.EN&&typeof d.reason==='string'){const v=I18N_EN['reason:'+d.reason]; if(typeof v==='string')return v;}
  return trMsg(s);}
// The pick's `warn` (a Korean UI hint, not an error body) is up to three sentences the server joins with a space, some
// with numbers. Each Korean template here matches one server sentence ({x} = the number); English fills the table's
// template through tl(). Korean shows the server text as is; a sentence no template matches stays as it is.
const PICK_WARNS=['이 영역은 원문 대조가 약합니다({pct}%). 줄 범위를 눈으로 확인하세요.','두 경로가 다른 곳을 가리킵니다(L{a} / L{b}). 확인이 필요합니다.',
  '화면의 PDF 가 지금 원고보다 낡았습니다 — [PDF 재빌드] 뒤에 다시 고르세요.','빌드 중이라 결과가 흔들릴 수 있습니다.',
  '이 영역에는 글자가 없습니다(그림·스캔본). 메모에 무엇을 가리키는지 적어 주세요.','PDF 가 바뀌어 쪽을 다시 그리는 중입니다 — 끝나면 다시 고르세요.',
  '이 그림의 요소 지도를 읽지 못해 영역으로 찍습니다 — 그림 저장소가 지도를 다시 쓰면 다시 고르세요.',
  '이 요소를 그린 코드 줄을 찾지 못해 영역으로 찍습니다 — 스크립트를 고친 뒤라면 그림을 다시 렌더하고 다시 고르세요.'];
function warnText(s){s=s==null?'':String(s); if(LANG!==UI_LANG.EN||!s)return s;
  for(const k of PICK_WARNS){const names=[],lit=k.split(/\{(\w+)\}/).filter((p,i)=>i%2===0||!names.push(p));
    const re=new RegExp(lit.map(p=>p.replace(/[.*+?^$()|[\]\\{}]/g,'\\$&')).join('(\\d+)'),'g');
    s=s.replace(re,(...m)=>tl(k,Object.fromEntries(names.map((n,i)=>[n,m[i+1]]))));}
  return s;}
// What people wrote is never translated (docs/handbook/viewer.md §뷰어 규칙을 바꿀 때): document names, notes, authors and thread
// posts are drawn under translate="no", and the translator leaves that subtree - its text and its UI attributes - alone, so a
// document named '그림' or a note that reads '완료' stays as written. The UI words drawn inside it are tr()'d by the code that
// draws them. el is an element (an SVG one has no translate and counts as translatable).
function i18nUser(el){return !!el&&el.translate===false;}
// Translates el's UI attributes in place, unless el is user text.
function i18nEl(el){if(i18nUser(el))return; for(const a of I18N_ATTRS){const v=el.getAttribute(a); if(v){const e=trMsg(v); if(e!==v)el.setAttribute(a,e);}}}
// Translates text node n in place, unless it sits in a text field, a script or style, or user text.
function i18nText(n){const p=n.parentNode; if(!p||/^(TEXTAREA|SCRIPT|STYLE)$/.test(p.nodeName)||i18nUser(p))return;
  const e=trMsg(n.nodeValue); if(e!==n.nodeValue)n.nodeValue=e;}
// Translates root and everything under it in English mode, skipping whole user-text subtrees.
function i18nTree(root){if(LANG!==UI_LANG.EN||!root)return;
  if(root.nodeType===3)return i18nText(root);
  if(root.nodeType!==1||i18nUser(root))return; i18nEl(root);
  const w=document.createTreeWalker(root,NodeFilter.SHOW_ELEMENT|NodeFilter.SHOW_TEXT,
    {acceptNode:n=>n.nodeType===1&&i18nUser(n)?NodeFilter.FILTER_REJECT:NodeFilter.FILTER_ACCEPT}); let n;
  while((n=w.nextNode())){if(n.nodeType===3)i18nText(n); else i18nEl(n);}}
// Checks the current language in [더보기]'s language segment, then in English translates the page once and everything drawn or
// changed after it (text nodes and UI attributes), leaving user text alone (i18nUser).
function i18nStart(){for(const r of /** @type {NodeListOf<HTMLElement>} */(document.querySelectorAll('#m-lang [role=radio]'))){const on=r.dataset.lang===LANG; r.setAttribute('aria-checked',String(on)); r.classList.toggle('on',on);}
  if(LANG!==UI_LANG.EN)return; i18nTree(document.body);
  new MutationObserver(ms=>{for(const m of ms){
    if(m.type==='childList')m.addedNodes.forEach(i18nTree);
    else if(m.type==='characterData')i18nText(m.target);
    else if(m.type==='attributes'&&m.target.nodeType===1&&!i18nUser(m.target)){const el=/** @type {Element} */(m.target),name=m.attributeName||'',v=el.getAttribute(name);
      if(v){const e=trMsg(v); if(e!==v)el.setAttribute(name,e);}}}})
    .observe(document.body,{childList:true,subtree:true,characterData:true,attributes:true,attributeFilter:I18N_ATTRS});}
// [더보기]'s language segment: saves lang (ko or en) as this device's choice and reloads in it - the tab's draft is kept
// (sessionStorage). The language on screen does nothing; nothing asks first.
function switchLang(lang){if(lang!==UI_LANG.KO&&lang!==UI_LANG.EN||lang===LANG)return;
  try{localStorage.setItem('limnLang',lang);}catch(e){}
  const u=new URL(location.href); u.searchParams.delete('lang'); location.replace(u.toString());}
