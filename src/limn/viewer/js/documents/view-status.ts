// ---------------------------------------- The status line (docs/handbook/viewer.md §모바일 레이아웃, 상태는 한 줄이다)
// One element, #status, shows one state at a time on every band, in the band's place (placeStatus): a 24px line on the
// phone and tablet sheet's top edge (#status-dock, outside the sheet so its action can reach 44px up over the PDF), a
// short text in the short band's top row and the middle of the mid action row (#status-slot), and on the desktop (wide)
// a line under the status chips (#status-wide). The line is the compact face of those chips: whenever one of them
// changes (a MutationObserver on #bar2) it is drawn again from the state they come from. It also carries the messages
// of platform/notices.ts (LINE): background events, first-visit hints and an undo whose place has left the screen - the
// only items the desktop's line shows besides a rebuild's 'no changes', a new Limn and the pins kept while cut off,
// since its chips say the rest (statusShown).
import { BAND, LAYOUT, META, buildsFromSource } from '../app/state.ts';
import { html, lucideIcon, setHtml } from '../platform/markup.ts';
import { translateTemplate, translate, TIP_TEXT } from '../platform/i18n.ts';
import { LINE, announce, holdLine, lineVisible, noticeButtons, noticeIcon } from '../platform/notices.ts';
import { hideTip, showTipText } from '../platform/tooltip.ts';
import { SYNC_REASON } from './flow-boot.ts';
import { POLL_FAILS } from './flow-polling.ts';
import { BUILD, pullSuffix } from './view-build-chip.ts';
import { versionOutdated } from './flow-updates.ts';
import { OFF } from '../offline/flow.ts';
import { NOTICE_KIND } from '../platform/tables.ts';
import { $ } from '../platform/dom.ts';
import { BUILD_STATE, LAYOUT_BAND, LAYOUT_MODE, STATUS_KIND, SYNC_STATE } from '../app/rules-tables.ts';
import { isViewer } from './state.ts';
let STATUS_SYNC = null as SyncStatus | null,
  STATUS_SIG = ''; // the last meta `sync`; the drawn item's kind, action and count
// the number of the message the line shows (0: none, or another item): lineNote reads out one it does not
let STATUS_TOP = 0;
// a passing answer (no changes) stays on the line as long as an undo's window (NOTICE_MS)
const STATUS_TRANSIENT_MS = 6000;

// A build's countable progress {done, total}: integers with total > 0 and 0 <= done <= total, else null - as if the
// field were missing (GET /api/build `progress`: the pages drawn of the PDF's while a render runs, null otherwise,
// absent from an older server; without it the bar does not know its end, docs/handbook/build-sync.md §진행 폴링). Pure.
function statusProgress(progress) {
  if (!progress || typeof progress !== 'object') return null;
  const { done, total } = progress;
  return Number.isInteger(done) && Number.isInteger(total) && total > 0 && done >= 0 && done <= total
    ? { done, total }
    : null;
}

// The items the status line shows for an input {notices, build, buildErr, offline, sync, stale, png, canRebuild,
// unchanged} (statusInput), highest priority first - errors before information (docs/handbook/viewer.md §알림 자리,
// rule 1): the line's error messages (alert, or kind ERR), newest first (notices, platform/notices.ts LINE; act
// 'notice'); the last build failed or had LaTeX errors; the connection is lost; the server runs another Limn than this
// page (outdated: its version, [새로 고침], documents/flow-updates.ts); the line's other messages, newest first; a
// build runs (rendering in the page render, else building); main sync is blocked; this tab's rebuild changed nothing
// (unchanged, for STATUS_TRANSIENT_MS); the PDF is older than its source - not while a build runs, which clears it, nor
// while the unchanged answer says the rebuild found nothing new (the line would contradict itself); main sync is under
// way; the PDF shows as PNG. Each item is {kind, act} plus what its text needs; act is the data-act of its one action,
// or null - [재빌드] and [그래도 빌드] (rebuild-force, a cold build) only where canRebuild (a LaTeX document and a
// person who may build). The phase whose work can be counted - the page render, whose progress field gives pages done
// of total - is looked up, not compared. Pure. One item of the status line (statusList), by its kind.
type StatusItem =
  | { kind: 'notice'; notice: Notice; act: string }
  | { kind: 'failed'; act: string }
  | { kind: 'errors'; n: number; act: string }
  | { kind: 'offline'; act: null }
  | { kind: 'queued'; n: number; held: number; act: string | null }
  | { kind: 'outdated'; version: string; act: string }
  | {
      kind: 'building' | 'rendering';
      phase: string;
      el: number;
      last: number;
      progress: ReturnType<typeof statusProgress>;
      act: null;
    }
  | { kind: 'sync-blocked'; reason: string; act: string }
  | { kind: 'unchanged'; pull: string; act: string | null }
  | { kind: 'stale'; act: string | null }
  | { kind: 'sync'; state: string; act: null }
  | { kind: 'png'; act: null };
function statusList(input) {
  const out: StatusItem[] = [],
    build = input.build,
    running = !!build && build.state === BUILD_STATE.RUNNING,
    buildError = input.buildErr,
    syncState = input.sync && input.sync.state;
  const notes = input.notices || [],
    alert = (notice: Notice) => !!notice.alert || notice.kind === NOTICE_KIND.ERR;
  notes.filter(alert).forEach((notice) => out.push({ kind: STATUS_KIND.NOTICE, notice: notice, act: 'notice' }));
  if (buildError && buildError.state === BUILD_STATE.FAIL)
    out.push({ kind: STATUS_KIND.FAILED, act: 'build-err-reopen' });
  else if (buildError && buildError.state === BUILD_STATE.OK_ERRORS)
    out.push({ kind: STATUS_KIND.ERRORS, n: (buildError.errors || []).length, act: 'build-err-reopen' });
  if (input.offline) out.push({ kind: STATUS_KIND.OFFLINE, act: null });
  if (input.queued)
    out.push({
      kind: STATUS_KIND.QUEUED,
      n: input.queued,
      held: input.held || 0,
      act: input.offline ? null : 'offline-flush',
    });
  if (input.outdated) out.push({ kind: STATUS_KIND.OUTDATED, version: input.outdated, act: 'reload' });
  notes
    .filter((notice) => !alert(notice))
    .forEach((notice) => out.push({ kind: STATUS_KIND.NOTICE, notice: notice, act: 'notice' }));
  if (running)
    out.push({
      kind: { render: STATUS_KIND.RENDERING }[build.phase] || STATUS_KIND.BUILDING,
      phase: build.phase || '',
      el: Math.round(build.elapsed_s || 0),
      last: build.last_s ? Math.round(build.last_s) : 0,
      progress: statusProgress(build.progress),
      act: null,
    });
  if (syncState === SYNC_STATE.BLOCKED || syncState === SYNC_STATE.ERROR)
    out.push({ kind: STATUS_KIND.SYNC_BLOCKED, reason: input.sync.reason || '', act: 'status-why' });
  if (input.unchanged && !running)
    out.push({
      kind: STATUS_KIND.UNCHANGED,
      pull: input.unchanged.pull || '',
      act: input.canRebuild ? 'rebuild-force' : null,
    });
  if (input.stale && !running && !input.unchanged)
    out.push({ kind: STATUS_KIND.STALE, act: input.canRebuild ? 'rebuild' : null });
  if (
    syncState === SYNC_STATE.CHECKING ||
    syncState === SYNC_STATE.DEFERRED ||
    syncState === SYNC_STATE.UPDATING ||
    syncState === SYNC_STATE.UPDATED
  )
    out.push({ kind: STATUS_KIND.SYNC, state: syncState, act: null });
  if (input.png) out.push({ kind: STATUS_KIND.PNG, act: null });
  return out;
}
// The items a band's line shows of statusList's: all of them on the compact bands; on the desktop (wide) only the
// messages, a rebuild's 'no changes', a new Limn and the pins kept while cut off - its status chips (#bar2) already
// show the build, the connection, sync, staleness and PNG, but no chip counts the kept pins, so the line is the one
// place the desktop says there are any. Pure.
function statusShown(list, wide) {
  return wide
    ? list.filter(
        (item) =>
          item.kind === STATUS_KIND.NOTICE ||
          item.kind === STATUS_KIND.UNCHANGED ||
          item.kind === STATUS_KIND.OUTDATED ||
          item.kind === STATUS_KIND.QUEUED,
      )
    : list;
}

// A filled template's text as [label, tail], cut at the template's first placeholder: the words before it (without the
// separator) are the label, the rest - the numbers - the tail. translateTemplate('쪽 {done}/{total}',{done:3,total:9})
// is ['쪽', ' 3/9'].
function statusSplit(key, values) {
  const template = translateTemplate(key, {}),
    brace = template.indexOf('{'),
    head = (brace < 0 ? template : template.slice(0, brace)).replace(/[\s·]+$/, ''),
    full = translateTemplate(key, values);
  return [head, full.slice(head.length)];
}

// The text of an item in its long form (fit 'long') or its short one ('short'), as [label, tail]: the label is what a
// screen reader hears when the item appears, the tail the seconds and pages that tick (drawn aria-hidden). Only
// translate/translateTemplate beyond itself.
function statusText(item, fit) {
  const long = fit !== 'short';
  switch (item.kind) {
    case STATUS_KIND.NOTICE: {
      const notice = item.notice;
      return [long && notice.desc ? notice.title + ' · ' + notice.desc : notice.title, ''];
    } // already in the UI language
    case STATUS_KIND.FAILED:
      return [long ? translate('빌드 실패 · 이전 PDF를 보는 중') : translate('빌드 실패'), ''];
    case STATUS_KIND.ERRORS:
      return [
        long
          ? translateTemplate('LaTeX 오류 {n}건 · 새 PDF', { n: item.n })
          : translateTemplate('LaTeX 오류 {n}', { n: item.n }),
        '',
      ];
    case STATUS_KIND.OFFLINE:
      return [long ? translate('연결 끊김 · 다시 잇는 중') : translate('연결 끊김'), ''];
    case STATUS_KIND.QUEUED:
      return [
        item.held
          ? translateTemplate('오프라인 핀 {n}개 · {h}개는 확인이 필요합니다', { n: item.n, h: item.held })
          : long
            ? translateTemplate('오프라인 핀 {n}개 · 연결되면 반영합니다', { n: item.n })
            : translateTemplate('오프라인 핀 {n}', { n: item.n }),
        '',
      ];
    case STATUS_KIND.OUTDATED:
      return [
        long
          ? translateTemplate('Limn {v}(으)로 바뀌었습니다 · 새로 고치면 새 화면을 씁니다', { v: item.version })
          : translate('Limn 업데이트됨'),
        '',
      ];
    case STATUS_KIND.RENDERING:
      if (item.progress) {
        const progress = item.progress;
        return long
          ? statusSplit('쪽 그리는 중 · {done}/{total}쪽', progress)
          : statusSplit('쪽 {done}/{total}', progress);
      }
    // falls through: no progress field - the seconds, as for any other phase
    case STATUS_KIND.BUILDING: {
      const name = translate(
        { pull: '원격 main 당겨오는 중', copy: '원고 복사 중', latex: 'LaTeX 컴파일 중', render: '쪽 그리는 중' }[
          item.phase
        ] || '재빌드 중',
      ).replace(/…$/, '');
      const seconds = translateTemplate('{s}초', { s: item.el });
      return [
        name,
        long
          ? ' · ' + seconds + (item.last ? ' ' + translateTemplate('(지난번 {s}초)', { s: item.last }) : '')
          : ' ' + seconds,
      ];
    }
    case STATUS_KIND.SYNC_BLOCKED:
      return [
        long
          ? translateTemplate('main 동기화 확인 필요 · {reason}', {
              reason: translate(SYNC_REASON[item.reason] || item.reason || ''),
            })
          : translate('main 동기화 막힘'),
        '',
      ];
    case STATUS_KIND.UNCHANGED:
      return [translate('변경 없음') + (long ? item.pull || '' : ''), ''];
    case STATUS_KIND.STALE:
      return [long ? translate('원고가 PDF보다 새롭습니다') : translate('원고 수정됨'), ''];
    case STATUS_KIND.SYNC:
      return [
        translate(
          item.state === SYNC_STATE.UPDATING
            ? '최신 main PDF 반영 중'
            : item.state === SYNC_STATE.UPDATED
              ? '최신 main 반영됨'
              : item.state === SYNC_STATE.DEFERRED
                ? '빌드 뒤 main 확인'
                : 'main 확인 중',
        ),
        '',
      ];
    case STATUS_KIND.PNG:
      return [long ? translate('PNG로 보는 중 · 확대하면 흐릴 수 있습니다') : translate('PNG로 보는 중'), ''];
  }
  return ['', ''];
}

// The leading mark of an item: a message's own (by its kind, platform/notices.ts noticeIcon), a warning triangle for a
// failure or blocked sync, the lost-connection icon, a spinner while work runs (a check once main sync is applied), an
// 8px warning dot for a stale PDF, the image icon for PNG.
function statusIcon(item) {
  const kinds = STATUS_KIND;
  if (item.kind === kinds.NOTICE)
    return html`<span class="st-ic nk-${item.notice.kind}">${noticeIcon(item.notice.kind)}</span>`;
  if (item.kind === kinds.FAILED || item.kind === kinds.ERRORS || item.kind === kinds.SYNC_BLOCKED)
    return html`<span class="st-ic warn">${lucideIcon('triangle-alert')}</span>`;
  if (item.kind === kinds.OFFLINE) return html`<span class="st-ic">${lucideIcon('wifi-off')}</span>`;
  if (item.kind === kinds.QUEUED)
    return html`<span class="st-ic${item.held ? ' warn' : ''}">${lucideIcon(item.held ? 'triangle-alert' : 'clock')}</span>`;
  if (item.kind === kinds.OUTDATED) return html`<span class="st-ic warn">${lucideIcon('refresh-cw')}</span>`;
  if (item.kind === kinds.STALE) return html`<span class="st-ic"><i class="st-stale"></i></span>`;
  if (item.kind === kinds.PNG) return html`<span class="st-ic">${lucideIcon('image')}</span>`;
  if (item.kind === kinds.UNCHANGED || (item.kind === kinds.SYNC && item.state === SYNC_STATE.UPDATED))
    return html`<span class="st-ic">${lucideIcon('check')}</span>`;
  return html`<span class="st-ic"><i class="spin"></i></span>`;
}

// An item's one action as a button (its data-act; [재빌드] is the line's one primary fill), or '' without one. [그래도
// 빌드] carries the tip on what a cold build is for (TIP_TEXT.buildanywaytip), [이유] the reason itself (statusWhy). A
// message brings its own action and [x] (noticeButtons). The label is a span (.lbl) so CSS can trim it to its cap
// height.
function statusAct(item) {
  if (!item.act) return html``;
  if (item.kind === STATUS_KIND.NOTICE) return noticeButtons(item.notice, true);
  const force = item.act === 'rebuild-force',
    why = item.act === 'status-why',
    reload = item.act === 'reload';
  const flush = item.act === 'offline-flush';
  const name =
    item.act === 'rebuild'
      ? translate('재빌드')
      : why
        ? translate('이유')
        : force
          ? translate(TIP_TEXT.buildanyway)
          : reload
            ? translate('새로 고침')
            : flush
              ? translate('지금 반영')
              : translate('보기');
  const tip = force
    ? html` data-tip="${TIP_TEXT.buildanywaytip}"`
    : why
      ? html` data-tip="${syncWhyText(STATUS_SYNC)}"`
      : reload
        ? html` data-tip="${TIP_TEXT.reloadtip}"`
        : '';
  return html`<button class="btn-sm st-act ${item.act === 'rebuild' || reload ? 'btn-default' : 'btn-secondary'}" data-act="${item.act}"${tip}><span class="lbl">${name}</span></button>`;
}

// What the status line is drawn from, gathered from the shell: its messages (LINE), the running build (BUILD.cur) and
// the last failed one, the light poll's failures, the last meta `sync`, and the chips that already say stale and PNG -
// plus whether this document and person may rebuild.
function statusInput() {
  return {
    notices: LINE,
    build: BUILD.cur,
    buildErr: BUILD.error,
    offline: POLL_FAILS >= 2,
    queued: OFF.n,
    held: OFF.held,
    outdated: versionOutdated(),
    sync: STATUS_SYNC,
    stale: !$('#meta-stale').hidden,
    png: !$('#vec-chip').hidden,
    canRebuild: !!META && buildsFromSource(META.kind) && !isViewer(),
    unchanged: BUILD.unchanged,
  };
}

// The answer to this tab's rebuild that kept the pages (ok, unchanged, the same seq), with [그래도 빌드] for a cold
// build: the status line says it on every band - the desktop's line under its chips too - for STATUS_TRANSIENT_MS, then
// shows what it showed before; a build that starts, a document switch or [그래도 빌드] ends it sooner.
function buildUnchanged(build) {
  const mark = { pull: pullSuffix(build) };
  BUILD.unchanged = mark;
  drawStatus();
  setTimeout(() => {
    if (BUILD.unchanged !== mark) return;
    BUILD.unchanged = null;
    drawStatus();
  }, STATUS_TRANSIENT_MS);
}

// Draws the status line from statusInput() - the items the band shows (statusShown): the first item with its icon, its
// text (the long form, the short one where the long does not fit and always in the short band's top row, then an
// ellipsis), '+N' for the rest and its action (a message's and its [x]), and a 2px progress bar while a build runs -
// counted when the build gives its progress, else one that does not know its end, all in .st-body, drawn again when the
// item, its action or the count changes. The spoken label is a separate live node (.st-sr) that stays: every draw puts
// the item's label there, and its text changes - and is read out - only when the label does, never for a redraw or the
// ticking numbers; an alert (an error message, a warning whose banner had no place on screen, a failed build, a lost
// connection) is left out there, as it was read out assertively when it came (lineNote, showBuildErr, pollLightOnce). A
// message whose button has the keyboard focus keeps the line while the focus is on it, and a redraw puts the focus back
// on that button (statusFocus): a new message never takes it from a [되돌리기] that is still there. Also the [⋯] row
// [PDF 재빌드]: off with '빌드 중' while a build runs. body.has-status says a line is up (the sheet joins it).
function drawStatus() {
  const box = $('#status'),
    spoken = box.querySelector('.st-sr'),
    body = box.querySelector('.st-body'),
    running = !!BUILD.cur;
  const focused = statusFocus();
  let list = statusShown(statusList(statusInput()), LAYOUT === LAYOUT_MODE.WIDE);
  const held =
    focused && focused.n ? list.findIndex((item) => !!item.notice && String(item.notice.n) === focused.n) : -1;
  if (held > 0) list = [list[held], ...list.slice(0, held), ...list.slice(held + 1)];
  const top = list[0];
  STATUS_TOP = top && top.notice ? top.notice.n : 0;
  const rebuildRow = $('#m-rebuild');
  if (rebuildRow) {
    rebuildRow.disabled = running;
    const tail = rebuildRow.querySelector('.m-tail');
    if (tail) tail.hidden = !running;
  }
  document.body.classList.toggle('has-status', !!top);
  box.hidden = !top;
  if ($('#status-list').open) {
    drawStatusList(list);
    placeStatusListSoon();
  } // its rows changed: placed again once the line is drawn
  if (!top) {
    if (STATUS_SIG) {
      body.replaceChildren();
      STATUS_SIG = '';
    }
    spoken.textContent = '';
    lineVisible(false);
    return;
  } // hidden: it holds nothing
  const sig =
    top.kind +
    '|' +
    (top.act || '') +
    '|' +
    list.length +
    '|' +
    (top.state || '') +
    '|' +
    // a message turned into a warning (noticeLate) takes its icon
    (top.notice ? top.notice.n + '|' + top.notice.kind : '');
  if (sig !== STATUS_SIG) {
    STATUS_SIG = sig;
    const more =
      list.length > 1
        ? html`<button class="btn-sm btn-ghost st-more" data-act="status-more" aria-haspopup="dialog" aria-label="${translateTemplate('상태 {n}건 더 보기', { n: list.length - 1 })}"><span class="lbl">${translateTemplate('+{n}', { n: list.length - 1 })}</span></button>`
        : '';
    const bar = running
      ? html`<span class="st-bar" role="progressbar" aria-label="${translate('빌드 진행')}"><i></i></span>`
      : '';
    setHtml(body, html`${statusIcon(top)}<span class="st-tx" aria-hidden="true"></span>${more}${statusAct(top)}${bar}`);
  }
  const textSpan = box.querySelector('.st-tx'),
    long = statusText(top, 'long'),
    short = statusText(top, 'short');
  // the short band's one row always takes the short text
  textSpan.textContent = BAND === LAYOUT_BAND.SHORT ? short[0] + short[1] : long[0] + long[1];
  if (textSpan.scrollWidth > textSpan.clientWidth) textSpan.textContent = short[0] + short[1];
  const said = top.notice
    ? top.notice.alert
    : // OUTDATED is read out politely here
      top.kind === STATUS_KIND.FAILED || top.kind === STATUS_KIND.ERRORS || top.kind === STATUS_KIND.OFFLINE;
  const say = said || (top.notice && top.notice.quiet) ? '' : long[0];
  if (spoken.textContent !== say) spoken.textContent = say; // a quiet one (a moved undo) was said when it came
  refocusStatus(focused);
  const bar = box.querySelector('.st-bar');
  if (!bar) return;
  const { done, total } = top.progress || {},
    percent = top.progress ? Math.round((done / total) * 100) : null;
  bar.classList.toggle('indet', percent === null);
  bar.querySelector('i').style.width = percent === null ? '' : percent + '%';
  if (percent === null) {
    bar.removeAttribute('aria-valuenow');
  } else {
    bar.setAttribute('aria-valuemin', '0');
    bar.setAttribute('aria-valuemax', '100');
    bar.setAttribute('aria-valuenow', String(percent));
  }
}

// The button of the line or its '+N' list that has the keyboard focus, as its data-act and data-n ('' for an item's own
// action), or null: the line's redraw gives the focus back to it (refocusStatus).
function statusFocus(): { act: string; n: string } | null {
  const active = document.activeElement as HTMLElement | null;
  return active && active.closest && active.closest('#status,#status-list') && active.dataset.act
    ? { act: active.dataset.act, n: active.dataset.n || '' }
    : null;
}
// Puts the focus back on the button `focused` names (statusFocus) when a redraw replaced it: in the open '+N' list,
// else on the line.
function refocusStatus(focused: { act: string; n: string } | null) {
  if (!focused) return;
  const active = document.activeElement;
  if (active && active !== document.body && document.contains(active)) return;
  const selector = '[data-act="' + focused.act + '"]' + (focused.n ? '[data-n="' + focused.n + '"]' : ''),
    listDialog = $('#status-list');
  const button = ((listDialog.open && listDialog.querySelector(selector)) ||
    $('#status').querySelector(selector)) as HTMLElement | null;
  if (button) button.focus({ preventScroll: true });
}
// The line follows the focus: when it leaves a message's button, the line shows again what comes first.
$('#status').addEventListener('focusout', () =>
  setTimeout(() => {
    if (!statusFocus()) drawStatus();
  }, 0),
);
// The '+N' list: every item as a 44px row with its long text and its action. A modal dialog over the line, so an
// outside tap, Esc and the back gesture fold it like the sheets; a row's action folds it too. While it is open the
// line's undo windows wait (platform/notices.ts lineHeld).
function drawStatusList(list) {
  setHtml(
    $('#status-list-rows'),
    html`${list.map((item) => {
      const text = statusText(item, 'long');
      return html`<div class="st-row">${statusIcon(item)}<span class="st-row-t" translate="no">${text[0] + text[1]}</span>${statusAct(item)}</div>`;
    })}`,
  );
}
// The sentence [이유] of blocked main sync explains: main sync is blocked, why (SYNC_REASON), and that the previous PDF
// may be showing. Only translate/translateTemplate beyond its argument.
function syncWhyText(sync: SyncStatus | null) {
  const reason = (sync && sync.reason) || '';
  return (
    translate('main 동기화 막힘') +
    ' — ' +
    translate(SYNC_REASON[reason] || reason) +
    ' · ' +
    translate('기존 PDF가 보일 수 있습니다')
  );
}
// [이유] of blocked main sync: its sentence (syncWhyText, also the button's description) shown right at the button -
// or, pressed in the '+N' list, which has just folded, at the line - and read out.
function statusWhy(button: HTMLElement) {
  const text = syncWhyText(STATUS_SYNC);
  showTipText(button.getClientRects().length ? button : $('#status'), text);
  announce(text);
}
// Opens the '+N' list beside the status line (placeStatusList), or folds it on a second press. It is placed before it
// is shown: drawn (open) but not yet modal, so it can be measured, then shown as a modal there. Shown first, the focus
// showModal gives its first row would come where the list stood before it was placed, and on a phone zoomed in on the
// line the view would move to that row and the line out of sight.
function toggleStatusList() {
  const dialog = $('#status-list');
  if (dialog.open) {
    dialog.close();
    return;
  }
  drawStatusList(statusShown(statusList(statusInput()), LAYOUT === LAYOUT_MODE.WIDE));
  hideTip();
  dialog.setAttribute('open', '');
  placeStatusList();
  dialog.removeAttribute('open');
  dialog.showModal();
  holdLine();
}
// The list folded (Esc, an outside press, the back gesture, a row's action) and the focus is still in it, or nowhere:
// the browser gives the focus back to the button that had it, '+N', but a message that came while the list was open has
// drawn the line again and that button with it - the focus would stay on the folded list's row and fall to the page as
// it went from view, and the next Tab would start from the top. So it goes to the line's '+N', else to the line's first
// control; a focus the row's action put elsewhere stays.
$('#status-list').addEventListener('close', () => {
  const active = document.activeElement,
    line = $('#status');
  if (active && active !== document.body && !$('#status-list').contains(active)) return;
  const button = (line.querySelector('[data-act="status-more"]') || line.querySelector('button')) as HTMLElement | null;
  if (button) button.focus({ preventScroll: true });
});
// Which side of the status line the '+N' list opens on, for a list `height` px tall with room px free above and below
// the line (to 8px off the edge of the window's visible part): its own side - over the line, or under it when the line
// is the short band's top row (under) - where the whole list fits there, else the other side where it fits, else the
// side with more room, where the list is cut to that room and scrolls. True for over the line. Pure.
function statusListUp(height: number, above: number, below: number, under: boolean) {
  if (height <= (under ? below : above)) return !under;
  if (height <= (under ? above : below)) return under;
  return above >= below;
}
// Puts the open '+N' list 4px off the status line on the side statusListUp picks, and lets it grow only to 8px off the
// visible part's edge on that side (--sl-room); its rows scroll inside that. Over the line is not always room enough:
// on a desktop the line sits under the status chips, about 114px from the top, and four rows over it would put the
// first two above the window (top -76px at 1400x850) with their [되돌리기] out of reach. The room is counted in the
// part of the window a person sees (visualViewport: a keyboard that does not resize the layout, a pinch zoom), not the
// whole window, under which the lower rows would stand behind such a keyboard. A line outside that part (a zoom panned
// away from it) has the list at the part's near edge instead of beside it, where its rows would be out of sight too,
// and at least a row tall - but never taller than the visible part, and never past it: where a row is taller than the
// room on its side, the list comes in from that edge over the line. On a phone zoomed in to 2x with its sheet open, a
// list one row (695-916px) tall over a line 280px from the top would run 418-639px above the window, and the focus
// showModal gives its first row would move the zoomed view to it. The list's full height is its content's
// (scrollHeight, with its border), read without undoing the cut, so a list scrolled down stays where it was. Placed
// again while it is open when its rows change (drawStatus: a new message, one that leaves - a list opened over the line
// with two rows that gets more keeps scrolling in that room), when the window or its visible part changes size or
// moves; a band change folds it (placeStatus).
function placeStatusList() {
  const dialog = $('#status-list');
  if (!dialog.open) return;
  const viewport = window.visualViewport,
    viewTop = viewport ? viewport.offsetTop : 0,
    viewBottom = viewport ? viewTop + viewport.height : innerHeight,
    lineRect = $('#status').getBoundingClientRect();
  // On the desktop the list's right edge follows the line's - its rows' [되돌리기] and [x] under the line's own - and
  // it reaches left from there: centred in the window it would stand about 350px left of the line, over the PDF.
  // Elsewhere the line spans the bar and the list is centred over it (responsive.css). Either box is then held 8px
  // inside the visible part, narrowed to it where it is narrower, so a phone zoomed in never has the list run past both
  // sides of what it shows.
  const viewLeft = viewport ? viewport.offsetLeft : 0,
    viewRight = viewport ? viewLeft + viewport.width : innerWidth;
  dialog.style.left = '';
  dialog.style.right = '';
  const style = getComputedStyle(dialog),
    max = parseFloat(style.maxWidth);
  let baseLeft, baseRight;
  if (LAYOUT === LAYOUT_MODE.WIDE) {
    baseRight = lineRect.right + parseFloat(style.paddingRight) + parseFloat(style.borderRightWidth);
    baseLeft = Math.max(8, baseRight - max);
  } else {
    const barLeft = parseFloat(style.left),
      barRight = innerWidth - parseFloat(style.right),
      barWidth = Math.min(max, barRight - barLeft);
    baseLeft = barLeft + (barRight - barLeft - barWidth) / 2;
    baseRight = baseLeft + barWidth;
  }
  const width = Math.min(baseRight - baseLeft, viewRight - viewLeft - 16),
    left = Math.min(Math.max(baseLeft, viewLeft + 8), viewRight - 8 - width);
  dialog.style.left = Math.round(left) + 'px';
  dialog.style.right = Math.round(innerWidth - left - width) + 'px';
  const lineTop = Math.min(Math.max(lineRect.top, viewTop), viewBottom),
    // the line's edges, held inside the visible part
    lineBottom = Math.min(Math.max(lineRect.bottom, viewTop), viewBottom);
  const above = lineTop - viewTop - 4 - 8,
    below = viewBottom - lineBottom - 4 - 8,
    height = dialog.scrollHeight + dialog.offsetHeight - dialog.clientHeight;
  const row = dialog.querySelector('.st-row') as HTMLElement | null,
    one = height - $('#status-list-rows').offsetHeight + (row ? row.offsetHeight : 0); // a row, its padding, border
  const up = statusListUp(height, above, below, BAND === LAYOUT_BAND.SHORT),
    room = Math.floor(Math.min(Math.max(up ? above : below, one), viewBottom - viewTop - 16));
  dialog.style.setProperty('--sl-room', room + 'px');
  dialog.style.top = up ? 'auto' : Math.round(Math.min(lineBottom + 4, viewBottom - 8 - room)) + 'px';
  dialog.style.bottom = up ? Math.round(innerHeight - Math.max(lineTop - 4, viewTop + 8 + room)) + 'px' : 'auto';
}
// placeStatusList at the next frame, once for all the changes before it: the line is drawn by then.
let STATUS_LIST_PLACE = 0;
function placeStatusListSoon() {
  if (!STATUS_LIST_PLACE)
    STATUS_LIST_PLACE = requestAnimationFrame(() => {
      STATUS_LIST_PLACE = 0;
      placeStatusList();
    });
}
addEventListener('resize', placeStatusListSoon);
{
  const viewport = window.visualViewport;
  if (viewport) {
    viewport.addEventListener('resize', placeStatusListSoon);
    viewport.addEventListener('scroll', placeStatusListSoon);
  }
}

// Moves #status to the band's place - the dock over the sheet (phone, tablet sheet), the short band's top row after the
// view switch, the mid action row's middle, the desktop's line under its status chips (#status-wide) - keeping a focus
// that was inside it, then draws it. An open '+N' list folds: it was placed for the old band.
function placeStatus() {
  const line = $('#status'),
    active = document.activeElement as HTMLElement,
    had = line.contains(active);
  if ($('#status-list').open) $('#status-list').close();
  lineVisible(false); // moved out from under the pointer: no hover is left holding its windows
  if (BAND === LAYOUT_BAND.SHORT) {
    if (line.previousElementSibling !== $('#view-switch')) $('#view-switch').after(line);
  } else if (LAYOUT === LAYOUT_MODE.MID) {
    if (line.parentNode !== $('#status-slot')) $('#status-slot').appendChild(line);
  } else if (LAYOUT === LAYOUT_MODE.WIDE) {
    if (line.parentNode !== $('#status-wide')) $('#status-wide').appendChild(line);
  } else if (line.parentNode !== $('#status-dock')) $('#status-dock').appendChild(line);
  if (had && active.focus) active.focus({ preventScroll: true });
  STATUS_SIG = '';
  drawStatus();
}
new MutationObserver(() => drawStatus()).observe($('#bar2'), {
  subtree: true,
  childList: true,
  characterData: true,
  attributes: true,
  attributeFilter: ['hidden'],
});
// The dock sits on the sheet's top edge: the sheet's height (with the keyboard's --kb under it) is its bottom.
if (window.ResizeObserver)
  new ResizeObserver(() => {
    document.documentElement.style.setProperty(
      '--sheet-h',
      Math.round($('#right').getBoundingClientRect().height) + 'px',
    );
  }).observe($('#right'), { box: 'border-box' });
// Sets STATUS_SIG, which this module declares, for another module that changes it (ADR-0042 D1); answers the value.
function setStatusSig<Value extends typeof STATUS_SIG>(value: Value): Value {
  STATUS_SIG = value;
  return value;
}
// Sets STATUS_SYNC, which this module declares, for another module that changes it (ADR-0042 D1); answers the value.
function setStatusSync<Value extends typeof STATUS_SYNC>(value: Value): Value {
  STATUS_SYNC = value;
  return value;
}
export {
  STATUS_TOP,
  buildUnchanged,
  drawStatus,
  placeStatus,
  setStatusSig,
  setStatusSync,
  statusWhy,
  toggleStatusList,
};
