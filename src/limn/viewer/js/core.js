
'use strict';
const $=s=>document.querySelector(s);
const $$=s=>Array.from(document.querySelectorAll(s));
// Lucide icons (vendor/lucide/README.md). Same shape as the server's icon_svg() - size is set by CSS (.ic).
const ICONS=__LUCIDE_JSON__;
function ic(n){const b=ICONS[n]; return b?'<svg class="ic ic-'+n+'" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true" focusable="false">'+b+'</svg>':'';}
const esc=t=>String(t==null?'':t).replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
const IS_MAC=/Mac|iPhone|iPad/i.test(navigator.platform||navigator.userAgent||'');
const SMOOTH=matchMedia('(prefers-reduced-motion: reduce)').matches?'auto':'smooth';
// Reduced motion (live, not only at load): the panel's slides are skipped, but thresholds and previews stay (§패널 폭과 시트 높이).
const MQ_REDUCED=matchMedia('(prefers-reduced-motion: reduce)');
const MQ=matchMedia('(prefers-color-scheme: light)');
let META=null,PINS=[],DONE=[],DROPPED=[],CUR=null,SAVING=false,ESAVING=false,EDIT=null,REPICK=null,PICKSEQ=0,PENDING=null,PICKING=false,PEND_SAVE=false;
let SNIP_OPEN=false,W=900,WRAP=true;
// Mobile: LAYOUT is 'wide'|'mid'|'narrow', SIDE_OPEN is whether the panel/sheet is expanded, SELMODE is touch selection mode,
// ZOOMED is whether the user changed the width via -/+ in compact (while true, it's never auto-fit to the screen width).
const MQ_COARSE=matchMedia('(pointer:coarse)');
// A device with no hover (phone/tablet): hover/focus tooltips are never shown at all - a tap sent a simulated mouseover and left the description stuck over the list (phone QA). Only long-press is used.
const MQ_NOHOVER=matchMedia('(hover:none)');
let OUTLINE_MID_OPEN=false,MID_OVERLAY=false;
let LAYOUT=null,SIDE_OPEN=true,SELMODE=false,ZOOMED=false,LAST_PTR='mouse',LAST_TOUCH_T=0;
const OPEN_CARDS=new Set();   // ids of pin cards expanded in compact
// Pin kind/thread (docs/handbook/viewer.md §스레드와 검토): KIND_NEW = the composer panel's kind (fix|question), REPLY = the open reply/reopen
// input field {id,mode,el} (holds onto the DOM like EDIT does, and re-inserts it in place when the list redraws), THREAD_OPEN = cards with the thread fully expanded,
// REPLY_DRAFT = a closed input field's draft text ('reply:12').
let KIND_NEW='fix',REPLY=null;
// @-tags (docs/handbook/viewer.md §@태그): PEOPLE = /api/people (tailnet people who opened this viewer + pin authors/actors), MENTION_ONLY = viewing only "pins that called me".
let PEOPLE=[],MENTION_ONLY=false;
const THREAD_OPEN=new Set(),REPLY_DRAFT=new Map();
// Multiple documents (§Multiple documents, docs/handbook/domain.md §여러 문서): DOCS = the /api/docs list, DOC = the current document key, DEFAULT_DOC = the first
// document that a legacy pin with no doc field belongs to. OPEN_ALL = open pins across all documents (PINS is the subset for the current document - marks/overlap/editing only look at PINS).
// META_BY = per-document meta cache (instant tab switching), VIEW_BY = per-document viewed position/zoom, BUILD_ERR_BY = per-document last build error,
// DOC_SEQ = another document's finished-build count (used to notice a build that finished in the background).
let DOCS=[],DOC=null,DEFAULT_DOC='main',OPEN_ALL=[],DONE_ALL=[],SHOW_ALL=false,SWITCHSEQ=0;
// Awaiting review (a pin closed by an agent, waiting for a person's [확인], state==='review'). Never put into DONE_ALL - drawn separately from the done archive.
let REVIEW_ALL=[];
const META_BY=new Map(),VIEW_BY=new Map(),BUILD_ERR_BY=new Map(),DOC_SEQ=new Map();
window.__pinViewerBoot=Date.now();   // a marker for checking reload status from outside

const T={
  stale:'핀을 찍은 첫 문장이 바뀌거나 지워져 위치를 되찾지 못했습니다. 이미 고쳐졌을 수 있으니 확인한 뒤 완료하거나 [수정] → 위치 다시 잡기를 하세요',
  n:"누르면 PDF에서 이 핀 자리로 갑니다. 에이전트에게는 '#2 처리해줘'처럼 번호로 부르세요. 번호는 다시 쓰이지 않습니다",
  loc:'핀이 가리키는 원문 줄. 클릭하면 복사',
  view:'PDF에서 이 핀 자리로 가서 깜빡입니다', edit:'메모와 범위를 고칩니다. 번호는 그대로입니다',
  close:"처리됨으로 표시해 목록과 pins.md에서 뺍니다. 아래 '닫힌 핀'에서 되돌릴 수 있습니다",
  drop:'핀을 휴지통으로 보냅니다. 알림의 [되돌리기]나 휴지통에서 같은 번호 그대로 되살릴 수 있습니다(30일 보관)',
  repick:'번호와 메모는 그대로 두고 PDF에서 새 위치를 드래그해 바꿉니다 (Esc 취소)',
  esave:'수정한 내용을 저장합니다 (⌘ Enter / Ctrl+Enter)', ecancel:'수정을 버립니다 (Esc)',
  restore:'삭제한 핀을 같은 번호로 되살려 열린 핀에 올립니다',
  purge:'휴지통에서 영구 삭제합니다(소유자만). 알림이 떠 있는 동안 [되돌리기]로 취소할 수 있고, 알림이 사라지면 지웁니다',
  synctex:'PDF 좌표(SyncTeX)로 줄을 찾았지만 드래그한 글자가 이 줄 범위에 다 있지는 않습니다(드문 낱말에 가중한 비율). 원문 칸에서 고칠 곳이 이 줄들에 들어 있는지 확인하세요.',
  text:'드래그한 글자를 원문에서 직접 찾아 위치를 정했습니다(표·기호표처럼 좌표 조회가 약한 곳). 원문 칸에서 고칠 곳이 이 줄들에 들어 있는지 확인하세요.',
  raw:'넓히기 전에 드래그 영역이 직접 가리킨 줄만 잡습니다',
  para:'드래그한 자리를 감싸는 문단 전체입니다(앞뒤 % 주석 줄은 뺍니다)',
  env:'감싸는 \\begin{…}…\\end{…} 블록 전체입니다. (바깥)은 한 단계 더 바깥 블록입니다',
  cur:'지금 핀이 가리키는 범위 그대로입니다',
  undo:'방금 한 저장·완료·삭제를 되돌립니다',
  question:'고칠 곳이 아니라 묻는 핀입니다. 답은 아래 스레드에 달리고, 원고는 질문이 수정을 뜻할 때만 고칩니다',
  review:'에이전트가 닫은 핀입니다. 사람이 결과를 보고 [확인]하면 완료로 가고, [답글]에 틀린 점을 쓰면 다시 열려 에이전트가 고칩니다',
  confirm:'결과를 확인했다고 기록하고 완료로 옮깁니다. 작성자에게 권하지만 누구나 누를 수 있고, 누른 사람이 기록됩니다',
  change:'변경사항 탭을 열어 이 핀을 고친 커밋(닫을 때 남긴 참조, 없으면 이 줄을 바꾼 최근 커밋)의 diff 에서 핀 자리를 강조합니다',
  reply:'이 핀에 답글을 답니다. 닫힌 핀이면 보내기 전에 칸 아래 한 줄이 결과(다시 열림·알림·그대로)를 알려 줍니다 (⌘ Enter / Ctrl+Enter 보내기)'
};

