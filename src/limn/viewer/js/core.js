
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
// Closed sets (docs/handbook/viewer.md §닫힌 값 표): every value the viewer compares a state, status or mode against is a
// member of one frozen table here, never a string literal at the comparison. The first group comes from the server and
// must equal its strings exactly (tests/viewer/test_viewer_source.py compares each table with the server's Literal or producer);
// the second is the viewer's own. Free text (messages, reasons, DOM and key names) is not tabled.
const PIN_STATE=Object.freeze({OPEN:'open',REVIEW:'review',DONE:'done'});   // a pin's `state` (pins.model.StateName); read it with pinState()
const BUILD_STATE=Object.freeze({IDLE:'idle',RUNNING:'running',OK:'ok',OK_ERRORS:'ok_errors',FAIL:'fail'});   // GET /api/build `state`, meta `last_state`
const PULL_STATE=Object.freeze({OK:'ok',UP_TO_DATE:'up_to_date',SKIPPED:'skipped',ERROR:'error'});   // a build's `pull.state` (pull.pull_record)
const SYNC_STATE=Object.freeze({DISABLED:'disabled',CHECKING:'checking',DEFERRED:'deferred',UPDATING:'updating',UPDATED:'updated',CURRENT:'current',BLOCKED:'blocked',ERROR:'error'});   // meta `sync.state`
const REVISION_STATE=Object.freeze({IDLE:'idle',RUNNING:'running',READY:'ready',ERROR:'error'});   // a comparison PDF's status `state`
const SCOPE_MODE=Object.freeze({PIN:'pin',COMMIT:'commit'});   // a pin's change scope `mode` / a comparison's `scope` (scope.ScopeMode)
const SCOPE_SOURCE=Object.freeze({CHANGES:'changes',INFERRED:'inferred',NONE:'none'});   // where a pin's change scope came from (scope.ScopeSource)
const THREAD_EV=Object.freeze({CLOSE:'close',REOPEN:'reopen',CONFIRM:'confirm',ASSIGN:'assign'});   // a thread record's `ev` (pins.model.ThreadEv)
const RANGE_REL=Object.freeze({EQUAL:'equal',INSIDE:'inside',CONTAINS:'contains',PARTIAL:'partial'});   // how two line ranges overlap (pins.position.selection_rel)
const KIND_REQ=Object.freeze({FIX:'fix',QUESTION:'question'});   // a pin's `kind_req` (pins.model.KindReq)
const ROLE=Object.freeze({OWNER:'owner',EDITOR:'editor',VIEWER:'viewer',AGENT:'agent'});   // a person's `role` (access.ROLES)
const EVENT_TYPE=Object.freeze({MENTION:'mention',REVIEW_REQUESTED:'review_requested',REPLIED:'replied',REOPENED:'reopened',ASSIGNED:'assigned',DROPPED:'dropped'});   // an event's `type` (events.EventType)
const VIA=Object.freeze({SYNCTEX:'synctex',TEXT:'text',MAP:'map'});   // how a pick traced its range: a pick's and a pin's `via` (limn.pins.location.mapping.Via)
const DOC_KIND=Object.freeze({TEX:'tex',PDF:'pdf',FIGURE:'figure'});   // a document's `kind` in /api/docs and /api/meta (limn.runtime.documents.DocKind)
const EL_SYNC=Object.freeze({OK:'ok',MOVED:'moved',LOST:'lost'});   // where a figure pin's element is in the current build: a pin's `el_sync` (limn.builds.figure_map.ElSync)
const LOCAL_LOGIN='local',ASSIGNEE_AGENT='agent';   // the identity-less local login (access.LOCAL_LOGIN); the assignee meaning "the agent" (pins.edit.ASSIGNEE_AGENT)
const LAYOUT_MODE=Object.freeze({WIDE:'wide',MID:'mid',NARROW:'narrow'});   // LAYOUT, the band's mode (BAND_MODE)
const LAYOUT_BAND=Object.freeze({PHONE:'phone',TABLET_SHEET:'tablet-sheet',SHORT:'short',MID_OVERLAY:'mid-overlay',MID_SIDE:'mid-side',WIDE:'wide'});   // BAND, by window width, height and primary pointer (layoutFor)
const BAND_STEP=Object.freeze({KEEP:'keep',WAIT:'wait',SETTLE:'settle'});   // what a new window observation does to the band (settleBand)
const CARD_DOT=Object.freeze({OPEN:'open',CLAIMED:'claimed',REVIEW:'review',LOST:'lost'});   // a card's status dot (stDot); also its CSS class
const DIFF_FORMAT=Object.freeze({PDF:'pdf',SOURCE:'source'});   // the changes view's tab (REVISION_FORMAT); index.html data-format
const VIEW_MODE=Object.freeze({MANUSCRIPT:'manuscript',REVISIONS:'revisions'});   // the manuscript or the changes view; index.html data-mode
const UI_LANG=Object.freeze({KO:'ko',EN:'en'});   // LANG
const NOTIFY_STATE=Object.freeze({ON:'on',OFF:'off',BLOCKED:'blocked',UNSUPPORTED:'unsupported',LOCAL:'local'});   // browser notifications on this device (notifyState)
const STATUS_KIND=Object.freeze({FAILED:'failed',ERRORS:'errors',OFFLINE:'offline',BUILDING:'building',RENDERING:'rendering',SYNC_BLOCKED:'sync-blocked',UNCHANGED:'unchanged',STALE:'stale',SYNC:'sync',PNG:'png'});   // an item of the status line (statusList)
// Each band's layout mode (docs/handbook/viewer.md §모바일 레이아웃): the sheet (narrow), the panel between the nav bar and the
// action row (mid) or the desktop (wide). Code that only asks which of the three reads LAYOUT; code that differs per band reads BAND.
const BAND_MODE=Object.freeze({[LAYOUT_BAND.PHONE]:LAYOUT_MODE.NARROW,[LAYOUT_BAND.TABLET_SHEET]:LAYOUT_MODE.NARROW,[LAYOUT_BAND.SHORT]:LAYOUT_MODE.MID,[LAYOUT_BAND.MID_OVERLAY]:LAYOUT_MODE.MID,[LAYOUT_BAND.MID_SIDE]:LAYOUT_MODE.MID,[LAYOUT_BAND.WIDE]:LAYOUT_MODE.WIDE});
// Whether a document `kind` is a figure document (a figure set drawn by code, with its element map): the one place this is asked.
function isFigureKind(kind){return kind===DOC_KIND.FIGURE;}
// Whether a document of this `kind` is rebuilt from its source: only a LaTeX one. A view-only PDF and a figure redraw when their
// files change, so they have no rebuild and word a finished build as a redraw.
function buildsFromSource(kind){return kind===DOC_KIND.TEX;}
let META=null,PINS=[],DONE=[],DROPPED=[],REPICK=null,PICKSEQ=0;
let SNIP_OPEN=false,W=900;
// Mobile: BAND is a LAYOUT_BAND (layoutFor of BAND_IN, the settled {w,h,coarse} - settleBand) and LAYOUT its LAYOUT_MODE (wide|mid|narrow, BAND_MODE), SIDE_OPEN is whether the panel/sheet is expanded, SELMODE is touch selection mode,
// ZOOMED is whether the user changed the width via -/+ in compact (while true, it's never auto-fit to the screen width).
const MQ_COARSE=matchMedia('(pointer:coarse)');
// A device with no hover (phone/tablet): hover/focus tooltips are never shown at all - a tap sent a simulated mouseover and left the description stuck over the list (phone QA). Only long-press is used.
const MQ_NOHOVER=matchMedia('(hover:none)');
let OUTLINE_MID_OPEN=false,MID_OVERLAY=false;
let LAYOUT=null,BAND=null,BAND_IN=null,SIDE_OPEN=true,SELMODE=false,ZOOMED=false,LAST_PTR='mouse',LAST_TOUCH_T=0;
const OPEN_CARDS=new Set();   // ids of pin cards expanded in compact
// Pin kind/thread (docs/handbook/viewer.md §스레드와 검토): KIND_NEW = the composer panel's kind (fix|question), REPLY = the open reply/reopen
// input field {id,mode,el} (holds onto the DOM like EDITOR.current does, and re-inserts it in place when the list redraws), THREAD_OPEN = cards with the thread fully expanded,
// REPLY_DRAFT = a closed input field's draft text ('reply:12').
let KIND_NEW=KIND_REQ.FIX,REPLY=null;
// @-tags (docs/handbook/viewer.md §@태그): PEOPLE = /api/people (tailnet people who opened this viewer + pin authors/actors), MENTION_ONLY = viewing only "pins that called me".
let PEOPLE=[],MENTION_ONLY=false;
const THREAD_OPEN=new Set(),REPLY_DRAFT=new Map();
// Multiple documents (§Multiple documents, docs/handbook/domain.md §여러 문서): DOCS = the /api/docs list, DOC = the current document key, DEFAULT_DOC = the first
// document that a legacy pin with no doc field belongs to. OPEN_ALL = open pins across all documents (PINS is the subset for the current document - marks/overlap/editing only look at PINS).
// META_BY = per-document meta cache (instant tab switching), VIEW_BY = per-document viewed position/zoom, BUILD_ERR_BY = per-document last build error,
// DOC_SEQ = another document's finished-build count (used to notice a build that finished in the background).
let DOCS=[],DOC=null,DEFAULT_DOC='main',OPEN_ALL=[],DONE_ALL=[],SHOW_ALL=false,SWITCHSEQ=0;
// A continuation may paint visit-local UI only while both the document and its visit number still match.
function captureVisit(){return {doc:DOC,seq:SWITCHSEQ};}
// Match a captured visit after an await, including leave-and-return to the same document.
function currentVisit(visit){return DOC===visit.doc&&SWITCHSEQ===visit.seq;}
// Awaiting review (a pin closed by an agent, waiting for a person's [확인], pinState(p)===PIN_STATE.REVIEW). Never put into DONE_ALL - drawn separately from the done archive.
let REVIEW_ALL=[];
const META_BY=new Map(),VIEW_BY=new Map(),BUILD_ERR_BY=new Map(),DOC_SEQ=new Map();
window.__pinViewerBoot=Date.now();   // a marker for checking reload status from outside

const T={
  stale:'핀을 찍은 첫 문장이 바뀌거나 지워져 위치를 되찾지 못했습니다. 이미 고쳐졌을 수 있으니 확인한 뒤 완료하거나 [수정] → 위치 다시 잡기를 하세요',
  ellost:'그림을 다시 그린 뒤 지도에서 이 요소를 찾지 못했습니다(요소 id가 바뀌었거나 지워짐). 표시는 핀을 찍은 때 자리에 그립니다. 이미 고쳐졌을 수 있으니 확인한 뒤 완료하거나 [수정] → 위치 다시 잡기를 하세요',
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
  viaother:'이 화면이 알지 못하는 방법으로 위치를 정했고, 드래그와 다 맞지는 않습니다. 고칠 곳이 이 범위에 들어 있는지 확인하세요.',
  map:'그림 지도에서 드래그와 가장 많이 겹치는 요소를 골랐습니다. 고른 상자가 고칠 곳을 덮는지 확인하세요.',
  raw:'넓히기 전에 드래그 영역이 직접 가리킨 줄만 잡습니다',
  para:'드래그한 자리를 감싸는 문단 전체입니다(앞뒤 % 주석 줄은 뺍니다)',
  env:'감싸는 \\begin{…}…\\end{…} 블록 전체입니다. (바깥)은 한 단계 더 바깥 블록입니다',
  el:'이 요소를 그린 코드 줄입니다. 대기 상자가 그림의 이 요소에 맞춰집니다',
  fig:'그림 전체를 그린 코드 줄입니다',
  elregion:'이 요소를 그린 코드 줄을 찾지 못했습니다 — 쪽·영역과 요소로 핀을 남깁니다',
  figregion:'그림 지도를 읽지 못해 쪽·영역과 영역 글자로 핀을 남깁니다',
  shape:'이 자리는 지금 핀과 모양(줄/영역)이 달라 옮길 수 없습니다 — 다른 자리를 고르거나 새 핀을 남기세요',
  cur:'지금 핀이 가리키는 범위 그대로입니다',
  undo:'방금 한 저장·완료·삭제를 되돌립니다',
  question:'고칠 곳이 아니라 묻는 핀입니다. 답은 아래 스레드에 달리고, 원고는 질문이 수정을 뜻할 때만 고칩니다',
  review:'에이전트가 닫은 핀입니다. 사람이 결과를 보고 [확인]하면 완료로 가고, [답글]에 틀린 점을 쓰면 다시 열려 에이전트가 고칩니다',
  confirm:'결과를 확인했다고 기록하고 완료로 옮깁니다. 작성자에게 권하지만 누구나 누를 수 있고, 누른 사람이 기록됩니다',
  change:'변경사항 탭을 열어 이 핀을 고친 커밋(닫을 때 남긴 참조, 없으면 이 줄을 바꾼 최근 커밋)의 diff 에서 핀 자리를 강조합니다',
  reply:'이 핀에 답글을 답니다. 닫힌 핀이면 보내기 전에 칸 아래 한 줄이 결과(다시 열림·알림·그대로)를 알려 줍니다 (⌘ Enter / Ctrl+Enter 보내기)',
  nochange:'변경 없음', buildanyway:'그래도 빌드',
  buildanywaytip:'남겨 둔 LaTeX 부산물을 지우고 처음부터 다시 빌드합니다. 빌드가 비교하지 않는 것(셸 탈출로 도는 프로그램이 읽는 파일 등)을 바꿨을 때 씁니다'
};
