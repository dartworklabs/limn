// ------------------------------------------------ Preferences (merged save): per-device pinPrefs, list-section state, theme
function prefs(){try{const p=JSON.parse(localStorage.getItem('pinPrefs')||'{}');return p&&typeof p==='object'?p:{};}catch(e){return {};}}
function savePrefs(patch){try{localStorage.setItem('pinPrefs',JSON.stringify(Object.assign(prefs(),patch)));}catch(e){}}
(function(){const p=prefs(); if(p.side)$('#right').style.width=p.side+'px'; if(p.w)W=p.w; if(p.wrap!==undefined)WRAP=!!p.wrap;})();
// List sections (docs/handbook/viewer.md §목록 구획): expanded/collapsed per section, remembered in pinPrefs.sec. Defaults: open pins and
// awaiting review expanded, done collapsed. SEC_SEEN holds, per section, the ids known at the first load plus everything the section
// held while expanded - while collapsed, a listed id not in it is counted as 'new N' on the header.
const SEC_DEFAULT={open:true,review:true,done:false};
function secState(saved){const o=Object.assign({},SEC_DEFAULT); if(saved&&typeof saved==='object')for(const k in SEC_DEFAULT)if(typeof saved[k]==='boolean')o[k]=saved[k]; return o;}
function secNewCount(seen,ids){if(!seen)return 0; return ids.filter(id=>!seen.has(id)).length;}
let SEC=secState(prefs().sec);
const SEC_SEEN={open:null,review:null,done:null};

const THEMES=['system','light','dark'],THEME_ICON={system:'sun-moon',light:'sun',dark:'moon'},THEME_NAME={system:'시스템',light:'밝게',dark:'어둡게'};
function applyTheme(){let t=prefs().theme||'light'; if(!THEME_ICON[t])t='light';
  const eff=t==='system'?(MQ.matches?'light':'dark'):(t==='light'?'light':'dark');
  document.documentElement.setAttribute('data-theme',eff); const b=$('#btn-theme'); b.innerHTML=ic(THEME_ICON[t]);
  const nm=tr(THEME_NAME[t]); b.setAttribute('aria-label',tl('화면 테마: {name}',{name:nm}));
  b.dataset.tip=tl('화면 테마: 지금 {name}. 누르면 시스템 따름 → 밝게 → 어둡게 순으로 바뀝니다. PDF 종이 색은 그대로입니다',{name:nm});
  const m=$('#m-theme'); if(m)m.textContent=tl('테마: {name}',{name:nm});}
MQ.addEventListener('change',applyTheme);
function cycleTheme(){const t=prefs().theme||'light';savePrefs({theme:THEMES[(THEMES.indexOf(t)+1)%3]});applyTheme();}

