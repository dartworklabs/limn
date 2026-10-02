// ------------------------------------------------ Preferences (merged save): per-device pinPrefs, list-section state, theme
function prefs(){try{const p=JSON.parse(localStorage.getItem('pinPrefs')||'{}');return p&&typeof p==='object'?p:{};}catch(e){return {};}}
function savePrefs(patch){try{localStorage.setItem('pinPrefs',JSON.stringify(Object.assign(prefs(),patch)));}catch(e){}}
// The saved width and page width, and the keys of the [줄바꿈] toggles an older release stored (wrap, diffWrap) dropped: the
// source and the diff always wrap now.
(function(){const p=prefs(); if(p.side)$('#right').style.width=p.side+'px'; if(p.w)W=p.w;
  if('wrap' in p||'diffWrap' in p){delete p.wrap; delete p.diffWrap; try{localStorage.setItem('pinPrefs',JSON.stringify(p));}catch(e){}}})();
// List sections (docs/handbook/viewer.md §목록 구획): expanded/collapsed per section, remembered in pinPrefs.sec. Defaults: open pins and
// awaiting review expanded, done collapsed. SEC_SEEN holds, per section, the ids known at the first load plus everything the section
// held while expanded - while collapsed, a listed id not in it is counted as 'new N' on the header.
const SEC_DEFAULT={open:true,review:true,done:false};
function secState(saved){const o=Object.assign({},SEC_DEFAULT); if(saved&&typeof saved==='object')for(const k in SEC_DEFAULT)if(typeof saved[k]==='boolean')o[k]=saved[k]; return o;}
function secNewCount(seen,ids){if(!seen)return 0; return ids.filter(id=>!seen.has(id)).length;}
let SEC=secState(prefs().sec);
const SEC_SEEN={open:null,review:null,done:null};

const THEMES=['system','light','dark'],THEME_NAME={system:'시스템',light:'밝게',dark:'어둡게'};
// Applies the saved theme (system, light or dark; light by default): the page's data-theme and [더보기]'s theme segments - the
// saved one checked, and under 시스템 what the system gives now ('지금 밝게'). The segments are the one theme control on every
// layout: the desktop's cycle button went with its [⋯] (3b of the cross-resolution pass).
function applyTheme(){let t=prefs().theme||'light'; if(!THEMES.includes(t))t='light';
  const eff=t==='system'?(MQ.matches?'light':'dark'):(t==='light'?'light':'dark');
  document.documentElement.setAttribute('data-theme',eff);
  for(const r of $$('#m-theme [role=radio]')){const on=r.dataset.theme===t; r.setAttribute('aria-checked',String(on)); r.classList.toggle('on',on);}
  const now=$('#m-theme-now'); if(now){now.hidden=t!=='system'; now.textContent=tl('지금 {name}',{name:tr(THEME_NAME[eff])});}}
MQ.addEventListener('change',applyTheme);
// [더보기]'s theme segment: saves theme t (one of THEMES) and applies it at once - the change is its own preview, another
// segment its undo.
function setTheme(t){if(!THEMES.includes(t))return; savePrefs({theme:t}); applyTheme();}

