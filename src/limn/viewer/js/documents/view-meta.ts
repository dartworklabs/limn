// ------------------------------------------------ Document
// The header: the document's meta, its stale and sync badges, the viewer's own name and role.
import { META, buildsFromSource, isFigureKind } from '../app/state.ts';
import { html, setHtml } from '../platform/markup.ts';
import { translateTemplate, translate } from '../platform/i18n.ts';
import { setStatusSync } from './view-status.ts';
import { showMarkdownHint } from '../markdown/view.ts';
import { $ } from '../platform/dom.ts';
import { LOCAL_LOGIN, ROLE, SYNC_STATE } from '../app/rules-tables.ts';
import { isAgent, who, isHuman } from '../app/state-people.ts';
import { avatar } from '../app/view-people.ts';
import { isMarkdownDoc, isTextDoc, isViewer } from './state.ts';
function builtAtEpoch(builtAt) {
  const parsed = Date.parse(String(builtAt || '').replace(' ', 'T'));
  return isNaN(parsed) ? null : parsed / 1000;
}
// The "manuscript modified" badge - judged only from numbers the server provides (stale_build, src_age_s), independent
// of the browser's clock/timezone. Only a legacy response with no stale_build falls back to comparing
// src_mtime/build_src_mtime (both server epochs).
function updateStaleBadge(meta) {
  const badge = $('#meta-stale'),
    rebuildButton = $('#btn-rebuild');
  let stale;
  if (typeof meta.stale_build === 'boolean') stale = meta.stale_build;
  else {
    const ref = typeof meta.build_src_mtime === 'number' ? meta.build_src_mtime : builtAtEpoch(META && META.built_at);
    stale = ref != null && typeof meta.src_mtime === 'number' && meta.src_mtime > ref + 2;
  }
  if (!stale) {
    badge.hidden = true;
    rebuildButton.classList.remove('btn-default');
    return;
  }
  const age = typeof meta.src_age_s === 'number' ? meta.src_age_s : Date.now() / 1000 - meta.src_mtime;
  const minutes = Math.max(0, Math.round(age / 60));
  badge.hidden = false;
  badge.textContent = translateTemplate('원고 수정됨 · {n}분 전', { n: minutes });
  rebuildButton.classList.add('btn-default');
}
const SYNC_REASON = {
  not_git: 'Git 저장소가 아닙니다',
  no_upstream: 'main 업스트림이 없습니다',
  not_main: '현재 체크아웃이 main이 아닙니다',
  dirty: '로컬에 커밋되지 않은 수정이 있습니다',
  diverged: '로컬 main과 원격 main이 갈라졌습니다',
  fetch_failed: '원격을 확인하지 못했습니다',
  fetch_timeout: '원격 확인 시간이 초과됐습니다',
  status_failed: '로컬 수정 상태를 읽지 못했습니다',
  unexpected: '동기화 중 오류가 났습니다',
  building: '다른 PDF 빌드가 진행 중입니다',
  build_failed: '새 원고의 PDF 빌드가 실패했습니다',
};
// The main sync badge (--git-pull) from a meta's `sync` {state, reason}: hidden when off or current, a warning when
// blocked or failed. It also keeps the sync for the status line (STATUS_SYNC), which words the same state on compact
// bands.
function updateSyncBadge(sync) {
  setStatusSync(sync || null);
  const badge = $('#meta-sync');
  if (!badge) return;
  if (!sync || sync.state === SYNC_STATE.DISABLED || sync.state === SYNC_STATE.CURRENT) {
    badge.hidden = true;
    return;
  }
  badge.hidden = false;
  badge.classList.toggle('badge-warning', sync.state === SYNC_STATE.BLOCKED || sync.state === SYNC_STATE.ERROR);
  const reason = translate(SYNC_REASON[sync.reason] || sync.reason || '');
  badge.textContent = translate(
    sync.state === SYNC_STATE.UPDATING
      ? '최신 main PDF 반영 중'
      : sync.state === SYNC_STATE.UPDATED
        ? '최신 main 반영됨'
        : sync.state === SYNC_STATE.DEFERRED
          ? '빌드 뒤 main 확인'
          : sync.state === SYNC_STATE.CHECKING
            ? 'main 확인 중'
            : 'main 동기화 확인 필요',
  );
  badge.dataset.tip = reason
    ? badge.textContent + ' · ' + reason + ' · ' + translate('기존 PDF가 보일 수 있습니다')
    : badge.textContent;
}
// An agent identity (role agent): it neither deletes nor restores a verdict pin (D16, 403 verdict_human), so it is
// offered neither.
function isAgentRole() {
  return !!(typeof META !== 'undefined' && META && META.me && META.me.role === ROLE.AGENT);
}
/** Whether this server-provided identity is a person with write access; server authorization remains authoritative. */
function canConfirmReview() {
  return isHuman() && !isViewer();
}
/** Explain why this screen cannot confirm a reviewed result, without offering a request the server will refuse. */
function confirmAccessText() {
  return translate(
    isViewer()
      ? '보기 권한만 있습니다 — 편집 권한이 있는 사람이 확인합니다'
      : '에이전트 권한으로 접속 중입니다 — 사람 신원으로 접속해 확인하세요',
  );
}
// Paints the header and the info line from META (the document on screen): names, page count, commit, build time, who is
// signed in, the stale and sync badges and the pins.md help text; the rebuild button is hidden unless the document
// builds from source. Reads META only and sends nothing.
function drawMeta() {
  // only a LaTeX document builds from source; a view-only PDF and a figure redraw when their files change
  document.body.classList.toggle('no-rebuild', !buildsFromSource(META.kind));
  // a figure document's marks are a frame with no tint (components.css)
  document.body.classList.toggle('fig-doc', isFigureKind(META.kind));
  document.body.classList.toggle('md-surface', isMarkdownDoc());
  showMarkdownHint(); // a Markdown document: no pages, so the page-only controls hide (md-surface.css)
  // the document area's name says what it holds
  $('#left').setAttribute(
    'aria-label',
    translate(isMarkdownDoc() ? (isTextDoc() ? '텍스트 문서' : 'Markdown 문서') : 'PDF 쪽'),
  );
  document.body.classList.toggle('role-viewer', isViewer());
  $('#m-download').disabled = !META.pages_build || isMarkdownDoc(); // no build on screen, no PDF to save
  // A Markdown document has no PDF: its file is the tab's source, 'Markdown' its form, and no build time (nor its ' ·
  // ').
  $('#meta-main').textContent = META.main;
  $('#meta-main').dataset.tip = translate(isMarkdownDoc() ? '이 탭의 원문 파일' : 'PDF를 만든 최상위 원고 파일');
  const isText = isMarkdownDoc() && isTextDoc(); // a text document's form is 텍스트 (text/view.ts)
  $('#meta-pages').textContent = isText
    ? translate('텍스트')
    : isMarkdownDoc()
      ? 'Markdown'
      : translateTemplate('{n}쪽', { n: META.pages.length });
  $('#meta-pages').dataset.tip = translate(
    isText
      ? '브라우저가 원문 줄을 그대로 보이는 문서 형식'
      : isMarkdownDoc()
        ? '브라우저가 원문에서 그리는 문서 형식'
        : '지금 화면에 있는 PDF의 쪽 수',
  );
  const head = commitShown(META.head);
  $('#meta-head').textContent = head;
  $('#meta-head-w').hidden = !head;
  const built = isMarkdownDoc()
    ? ''
    : String(META.built_at || '')
        .slice(0, 16)
        .replace('T', ' ');
  $('#meta-built').textContent = built;
  $('#meta-built-w').hidden = !built; // a Markdown document is never built
  const me = META.me || ({} as Me);
  setHtml($('#me'), html`${avatar(me)}<span class="au-n" translate="no">${who(me)}</span>`);
  $('#me').dataset.tip = translateTemplate(
    '지금 이 화면을 쓰는 사람: {name}. 핀을 저장·수정·완료하면 이 이름으로 기록됩니다',
    {
      name:
        (isAgent(me) ? who(me) : me.name || '') + (me.login && me.login !== LOCAL_LOGIN ? ' (' + me.login + ')' : ''),
    },
  );
  updateStaleBadge(META);
  updateSyncBadge(META.sync);
  $('#help-pins-md').textContent = META.pins_md || '';
  setHtml($('#more-info'), moreInfo(META, me));
}
// [더보기]'s meta (compact, where #bar2's line is hidden) as two lines: the file · pages · commit, then the build time
// · me. Each piece keeps its words together and the lines break only between pieces; a piece longer than the line (a
// long file name) breaks after / . _ - (<wbr>), never cut at '…' with its rest only in a long-press tip. The words are
// the viewer's (translate/translateTemplate), the names the user's: #more-info is translate="no".
function moreInfo(meta, me) {
  const built = String(meta.built_at || '')
    .slice(5, 16)
    .replace('T', ' ');
  const piece = (text) =>
    html`<span class="mc">${String(text)
      .split(/([/._-])/)
      .map((part, index) => (index % 2 ? html`${part}<wbr>` : part))}</span>`;
  const line = (texts) => texts.filter(Boolean).map((text, index) => (index ? html` · ${piece(text)}` : piece(text)));
  return html`${line([meta.main, translateTemplate('{n}쪽', { n: meta.pages.length }), commitShown(meta.head)])}<br>${line([built && built !== '?' ? built + ' ' + translate('빌드') : '', translateTemplate('나: {name}', { name: who(me) })])}`;
}
// The commit a meta names, or '' when it names none: the server sends '-' for a manuscript outside Git and nothing
// before the first build. The meta lines leave that piece out with its separator - they read 'main.tex · 2쪽 · -'.
// Pure.
function commitShown(head) {
  const text = String(head == null ? '' : head).trim();
  return text === '-' || text === '?' ? '' : text;
}
export { SYNC_REASON, canConfirmReview, confirmAccessText, drawMeta, isAgentRole, updateStaleBadge, updateSyncBadge };
