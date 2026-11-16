// ------------------------------------------------ Help
import {
  $,
  $$,
  DOCS,
  KIND_REQ,
  LAYOUT,
  LAYOUT_MODE,
  MENTION_ONLY,
  MID_OVERLAY,
  NOTICE_HOST,
  NOTICE_KIND,
  OPEN_CARDS,
  OUTLINE_MID_OPEN,
  REPICK,
  REPLY,
  SELMODE,
  SHOW_ALL,
  SIDE_OPEN,
  SNIP_OPEN,
  THREAD_OPEN,
  imeKey,
  setMentionOnly,
  setShowAll,
  setSnipOpen,
} from './core.ts';
import { switchLang } from './i18n.ts';
import { setTheme } from './prefs.ts';
import { copyText } from './api.ts';
import { bannerNote, noticeAct, noticeClose } from './notices.ts';
import { TIP, focusGivenBack, hideTip } from './tooltip.ts';
import { closeDocMenu, multiDoc, toggleDocMenu } from './doc-tabs.ts';
import {
  REV_SCOPE,
  moreRevisions,
  pressRevisionRow,
  renderRevisionFile,
  revBack,
  setRevisionFormat,
  setRevisionRange,
  setRevisionSide,
  setRevisionWhole,
  setViewMode,
  showChange,
  showRevision,
  toggleRevisionOther,
} from './revisions.ts';
import { cycleDoc, openNavSheet, switchDoc } from './doc-switch.ts';
import { boot, viewerBlocked } from './boot.ts';
import { notifyToggle } from './notify.ts';
import { BUILD } from './build-chip.ts';
import { reloadForUpdate } from './updates.ts';
import { drawStatus, statusWhy, toggleStatusList } from './status.ts';
import { sizePreset, toggleOutline } from './panel-size.ts';
import { actualSize, fitW, navGo, zoom } from './pages.ts';
import { pickOutline } from './outline.ts';
import { closePageList, goListedPage, togglePageList } from './page-list.ts';
import { searchClose, searchGo, searchOpen } from './search.ts';
import { revisionPdfActive, revisionZoom } from './revision-zoom.ts';
import { zoomKey } from './zoom.ts';
import {
  focusSideToggle,
  headInk,
  openMore,
  outlineOverlay,
  setSelMode,
  setSide,
  showSheet,
  toggleSide,
} from './layout.ts';
import { useLevel } from './levels.ts';
import { applyRange, dropLine, widenTo } from './excerpt.ts';
import { showElementBox } from './figure.ts';
import { isMdDoc, mdGoAnchor, mdGoDoc, mdHtmlRun } from './md-surface.ts';
import { mdcStep } from './md-compare.ts';
import { SG_OPEN, suggestAct } from './suggest.ts';
import {
  COMPOSE,
  discardSelection,
  recomputeOverlap,
  renderComposer,
  renderOverlapBanner,
  setKind,
  toggleQuote,
} from './composer.ts';
import { saveDraftSoon } from './draft.ts';
import { appendToPin, savePin } from './save.ts';
import { offlineFlush, offlinePrepare } from './offline.ts';
import { cancelLineVerdict, undoFromLine, verdictPress } from './verdict.ts';
import { actOnReason } from './verdict-reason.ts';
import { goToSummaryPage } from './verdict-panel.ts';
import { selPopMore } from './sel-popover.ts';
import { MSG_OPEN } from './card-parts.ts';
import { ARC_OPEN, openTrash } from './cards.ts';
import { RV_PICK, rvConfirm, rvPick, rvToCard } from './review-pick.ts';
import {
  cardNeighbour,
  drawPins,
  focusCard,
  gotoPinRef,
  gotoReview,
  jumpPin,
  jumpToCard,
  loadPins,
  revealCard,
  setListOrder,
  toggleSec,
} from './list.ts';
import { MARKS, marksSet } from './marks-hide.ts';
import { closePin, confirmPin, dropPin, purgePin, trashRestore, unclaimPin } from './actions.ts';
import { ASSIGN_NEW, mentionApply, renderAssignEdit, renderAssignNew } from './mentions.ts';
import { closeReply, openReply, renderReplyOutcome, sendReply } from './reply.ts';
import { EDITOR, cancelEdit, openEdit, renderEdit, saveEdit } from './edit.ts';
import { applyRepick, cancelRepick, startRepick } from './repick.ts';
import { downloadPdf, hideBuildErr, rebuild, showBuildErr } from './rebuild.ts';
let HELP_BACK = null as HTMLElement | null;
// Opens help with its head on one ink line (headInk); closing it gives the focus back to what had it.
function openHelp() {
  const dialog = $('#help');
  if (dialog.open) return;
  HELP_BACK = document.activeElement as HTMLElement | null;
  hideTip();
  showSheet(dialog);
  headInk();
}
$('#help').addEventListener('close', () => {
  if (HELP_BACK && HELP_BACK.focus) HELP_BACK.focus();
  HELP_BACK = null;
});

// ------------------------------------------------ Event delegation (no inline handlers)
/** Route shared zoom controls to the visible PDF, leaving source views unchanged. */
// [100%] is the manuscript's print size: the comparison PDF's zoom is against its fitted width, so the changes view
// hides the control (responsive.css) and leaves it nothing to do.
function zoomVisiblePdf(action) {
  if (document.body.classList.contains('revision-open')) {
    if (action !== 'actual') revisionZoom(action);
  } else if (action === 'fit') fitW();
  else if (action === 'actual') actualSize();
  else zoom(action === 'in' ? 1 : -1);
}
// compact: a click on a collapsed card that hit nothing of its own opens the card, as its preview line and chevron do
// (the card's 44px links and chips keep their own action). wide cards are always open.
function openTappedCard(target) {
  const card = target && target.closest && target.closest('.pin.card:not(.open):not(.editing)');
  if (!card || LAYOUT === LAYOUT_MODE.WIDE || target.closest('[data-copy],button,input,textarea')) return;
  OPEN_CARDS.add(+card.dataset.id);
  drawPins();
}
document.addEventListener('click', (event) => {
  const target = event.target as HTMLElement;
  const copier = target.closest('[data-copy]') as HTMLElement;
  if (copier) {
    copyText(copier.dataset.copy || '', copier);
    return;
  }
  const control = target.closest('[data-act]') as HTMLElement;
  if (!control) {
    openTappedCard(target);
    return;
  }
  const host = control.closest('[data-id]') as HTMLElement,
    id = host ? Number(host.dataset.id) : null,
    inEdit = !!control.closest('.edit');
  const fromMore = !!control.closest('#more');
  if (fromMore && (control.dataset.close || control.dataset.act === 'help')) $('#more').close();
  if (control.closest('#status-list')) $('#status-list').close(); // a row's action folds the status list
  // a destination in the navigation sheet: go there, the sheet closes
  if (control.dataset.close && control.closest('#nav-sheet')) $('#nav-sheet').close();
  switch (control.dataset.act) {
    case 'side':
      toggleSide();
      break;
    case 'selmode':
      setSelMode(!SELMODE);
      if (SELMODE && LAYOUT === LAYOUT_MODE.NARROW && !COMPOSE.current && !EDITOR.current) setSide(false);
      break;
    case 'selmode-end':
      setSelMode(false);
      break; // the mode bar's [끝내기]: one press, no confirmation
    case 'more':
      openMore();
      break;
    case 'more-close':
      $('#more').close();
      break;
    case 'size-preset':
      sizePreset(Number(control.dataset.i));
      break;
    case 'card-toggle':
      if (id == null) break;
      if (OPEN_CARDS.has(id)) OPEN_CARDS.delete(id);
      else OPEN_CARDS.add(id);
      drawPins();
      break;
    case 'rebuild':
      rebuild();
      break;
    case 'reload':
      loadPins();
      break;
    case 'pdf-download':
      downloadPdf();
      break;
    case 'rebuild-force':
      BUILD.unchanged = null;
      drawStatus();
      rebuild(true);
      break; // the status line's [그래도 빌드]: a cold build
    case 'offline-prepare':
      void offlinePrepare();
      break; // [더보기]'s [오프라인으로 받기] (offline.ts)
    case 'offline-flush':
      void offlineFlush();
      break; // the status line's [지금 반영]: send the kept pins now
    case 'zoom-in':
      zoomVisiblePdf('in');
      break;
    case 'zoom-out':
      zoomVisiblePdf('out');
      break;
    case 'fit':
      zoomVisiblePdf('fit');
      break;
    case 'actual':
      zoomVisiblePdf('actual');
      break;
    case 'marks-toggle':
      marksSet(!MARKS.off);
      break; // [더보기]'s [핀 표시] switch (marks-hide.ts)
    case 'theme':
      setTheme(control.dataset.theme);
      break;
    case 'lang':
      switchLang(control.dataset.lang);
      break;
    case 'notify-toggle':
      notifyToggle();
      break;
    case 'help':
      openHelp();
      break;
    case 'help-close':
      $('#help').close();
      break;
    case 'save':
    case 'pop-save':
      if (!viewerBlocked()) savePin();
      break;
    case 'cancel':
      discardSelection();
      break;
    case 'verdict-save':
    case 'pv-save':
      verdictPress(control, event.detail === 0 ? 'kb' : undefined);
      break; // a verdict word's button: the composer's row or a page verdict line (verdict.ts)
    case 'pv-earlier':
      gotoPinRef(Number(control.dataset.ref), event.detail === 0);
      break;
    case 'pv-cancel':
      cancelLineVerdict(control);
      break; // a page line's [판정 취소] on the person's own open verdict (verdict.ts)
    // a page line's reason and its popover (verdict-reason.ts)
    case 'pv-reason-open':
    case 'pv-reason-save':
    case 'pv-reason-clear':
    case 'pv-reason-close':
    case 'pv-reason-fold':
    case 'pv-reason-reapply':
    case 'pv-reason-see':
      actOnReason(control);
      break;
    case 'pv-sum':
      goToSummaryPage(control);
      break; // a page's summary beside the verdict panel brings that page to it (verdict-panel.ts)
    case 'pv-undo':
      undoFromLine(control);
      break; // a take-back's [되돌리기] on its line (verdict.ts)
    case 'pop-more':
      selPopMore();
      break; // the note popover by the box hands over to the composer in the panel
    case 'overlap-append': {
      const text = $('#note').value.trim();
      if (!text) {
        bannerNote(NOTICE_HOST.COMPOSER, '메모를 먼저 써야 덧붙일 수 있습니다', NOTICE_KIND.WARN);
        break;
      }
      appendToPin(Number(control.dataset.oid), text);
      break;
    }
    case 'overlap-separate':
      COMPOSE.dismissedOverlap = control.dataset.key || null;
      renderOverlapBanner();
      break;
    case 'copy-cur':
      if (COMPOSE.current)
        copyText(COMPOSE.current.name + ' L' + COMPOSE.current.lo + '-L' + COMPOSE.current.hi, control);
      break;
    case 'expand':
      setSnipOpen(!SNIP_OPEN);
      renderComposer();
      break;
    case 'quote':
      toggleQuote(control);
      break; // the dragged PDF text's line: open in full, or fold back to one line
    case 'sg-toggle':
    case 'sg-reload':
    case 'sg-rebase':
      suggestAct(control, String(control.dataset.act));
      break; // a suggested edit's switch and line (suggest.ts)
    case 'sg-fold': {
      const key = control.dataset.key;
      if (!key) break;
      if (SG_OPEN.has(key)) SG_OPEN.delete(key);
      else SG_OPEN.add(key);
      drawPins();
      break;
    } // a card's suggestion diff
    case 'level': {
      const draft = inEdit ? EDITOR.current : COMPOSE.current;
      if (!draft) break;
      useLevel(draft, control.dataset.level);
      if (!inEdit) {
        COMPOSE.intent++;
        recomputeOverlap();
      }
      inEdit ? renderEdit() : renderComposer();
      break;
    }
    case 'xp-to': {
      const draft = inEdit ? EDITOR.current : COMPOSE.current,
        line = Number(control.dataset.line);
      if (draft && draft.lo != null && draft.hi != null)
        applyRange(draft, widenTo(draft.lo, draft.hi, line), line < draft.lo ? draft.hi : draft.lo);
      break;
    } // the excerpt: widen to a dimmed line
    case 'xp-drop': {
      const draft = inEdit ? EDITOR.current : COMPOSE.current,
        line = Number(control.dataset.line);
      if (draft && draft.lo != null && draft.hi != null)
        applyRange(draft, dropLine(draft.lo, draft.hi, line), line === draft.lo ? draft.hi : draft.lo);
      break;
    } // ...or drop an end line
    case 'view':
      jumpPin(id);
      break;
    case 'edit':
      openEdit(id);
      break;
    case 'doc': {
      // inMenu is read before switchDoc(): for a cached document switchDoc finishes synchronously through drawDocTabs,
      // which redraws the open #nav-sheet (drawDocsMenu) and detaches the control from the DOM. control.closest() after
      // switchDoc would return null, leaving the sheet open and blocking the next tap on a tab.
      const inMenu = !!control.closest('#nav-sheet');
      if (control.closest('#doc-pop')) closeDocMenu(true);
      switchDoc(control.dataset.doc);
      if (inMenu) $('#nav-sheet').close();
      break;
    }
    case 'el-show':
      showElementBox();
      break; // the composer's element path: show the chosen element's box on the page (figure.ts)
    case 'doc-more':
      toggleDocMenu();
      break; // [+N]: the documents popover (doc-tabs.ts)
    case 'nav-sheet':
      openNavSheet();
      break;
    case 'nav-sheet-close':
      $('#nav-sheet').close();
      break;
    case 'ns-go':
      navGo();
      break;
    case 'page-list':
      togglePageList(control);
      break;
    case 'page-go':
      goListedPage(Number(control.dataset.page));
      break;
    case 'view-mode':
      setViewMode(control.dataset.mode);
      break;
    case 'search-open':
      searchOpen();
      break;
    case 'search-close':
      searchClose(true);
      break; // the magnifier (and the phone's navigation-sheet row), [검색 닫기]
    case 'search-prev':
      searchGo(-1);
      break;
    case 'search-next':
      searchGo(1);
      break;
    case 'rev-back':
      revBack();
      break;
    case 'outline':
      toggleOutline();
      break;
    case 'outline-page':
      if (outlineOverlay() && OUTLINE_MID_OPEN) toggleOutline();
      pickOutline(Number(control.dataset.index));
      break;
    case 'revision':
      showRevision(control.dataset.commit || '');
      break;
    case 'revision-format':
      setRevisionFormat(control.dataset.format);
      break;
    case 'revision-side':
      setRevisionSide(control.dataset.side);
      break;
    case 'mdc-step':
      mdcStep(Number(control.dataset.step) || 0);
      break;
    case 'revision-row':
      pressRevisionRow(control.dataset.commit);
      break;
    case 'revision-range':
      setRevisionRange(control.dataset.range);
      break;
    case 'revision-more':
      moreRevisions();
      break;
    case 'all-docs':
      setShowAll(!SHOW_ALL);
      drawPins();
      break;
    case 'mention-filter':
      setMentionOnly(!MENTION_ONLY);
      drawPins();
      break;
    case 'review-pick':
      rvPick(!RV_PICK);
      break;
    case 'rv-go':
      rvConfirm();
      break;
    case 'rv-card':
      if (id != null) rvToCard(id);
      break; // confirming from result rows (review-pick.ts)
    case 'list-order':
      setListOrder(control.dataset.order);
      break;
    case 'mention-pick':
      mentionApply(Number(control.dataset.i));
      break;
    case 'pin-ref':
      gotoPinRef(Number(control.dataset.ref), event.detail === 0);
      break; // by keyboard the focus goes to the card
    case 'assign-new':
      ASSIGN_NEW.v = control.dataset.v || 'agent';
      ASSIGN_NEW.touched = true;
      renderAssignNew();
      saveDraftSoon();
      break;
    case 'assign-edit':
      if (EDITOR.current) {
        EDITOR.current.assignee = control.dataset.v || 'agent';
        renderAssignEdit();
      }
      break;
    case 'msg-more': {
      const key = control.dataset.key;
      if (!key) break;
      if (MSG_OPEN.has(key)) MSG_OPEN.delete(key);
      else MSG_OPEN.add(key);
      drawPins();
      break;
    }
    case 'revision-other':
      toggleRevisionOther();
      break;
    case 'revision-zoom':
      revisionZoom(control.dataset.zoom);
      break;
    case 'revision-whole':
      setRevisionWhole(!REV_SCOPE.whole);
      break;
    case 'mark-jump':
      revealCard(id);
      jumpToCard(id);
      break;
    case 'close':
      closePin(id);
      break;
    case 'drop': {
      const neighbour = event.detail === 0 ? cardNeighbour(control) : null;
      dropPin(id, false);
      if (neighbour !== null) focusCard(neighbour);
      break;
    } // by keyboard the focus goes to the card beside
    case 'restore':
      trashRestore(id);
      break;
    case 'purge':
      if (id != null) purgePin(id);
      break;
    case 'unclaim':
      unclaimPin(id);
      break;
    case 'kind': {
      const fromHint = !!control.closest('#c-qhint');
      setKind(control.dataset.kind);
      // [질문으로 보내기] hides itself (qHint), which would drop focus to <body> and make Ctrl+Enter do nothing - back
      // to the memo.
      if (fromHint) {
        const note = $('#note');
        note.focus({ preventScroll: true });
        note.setSelectionRange(note.value.length, note.value.length);
      }
      break;
    }
    case 'e-kind':
      if (EDITOR.current) {
        EDITOR.current.kind_req = control.dataset.kind === KIND_REQ.QUESTION ? KIND_REQ.QUESTION : KIND_REQ.FIX;
        renderEdit();
      }
      break;
    case 'reply-open':
      if (id != null) openReply(id);
      break;
    case 'reply-flip':
      if (REPLY) {
        REPLY.flip = !REPLY.flip;
        renderReplyOutcome();
      }
      break;
    case 'confirm': {
      if (id == null) break;
      const inGuide = !!control.closest('#revision-pin,#revision-acts'); // before confirmPin redraws the guide line
      confirmPin(id);
      if (inGuide) revBack();
      break;
    } // the review ends where it is read: back to the manuscript
    case 'change':
      if (id != null) showChange(id);
      break;
    case 'goto-review':
      gotoReview();
      break;
    case 'reply-cancel':
      closeReply();
      break;
    case 'reply-send':
      sendReply();
      break;
    case 'thread-more':
      if (id == null) break;
      if (THREAD_OPEN.has(id)) THREAD_OPEN.delete(id);
      else THREAD_OPEN.add(id);
      drawPins();
      break;
    case 'arc-toggle': {
      const key = control.dataset.key;
      if (!key) break;
      if (ARC_OPEN.has(key)) ARC_OPEN.delete(key);
      else ARC_OPEN.add(key);
      drawPins();
      break;
    }
    case 'esave':
      saveEdit();
      break;
    case 'ecancel':
      cancelEdit();
      break;
    case 'md-anchor':
      mdGoAnchor(control);
      break; // an in-document #heading link of the Markdown surface
    case 'md-doc':
      mdGoDoc(control);
      break; // a link to another registered document (md-surface.ts, ADR-0030)
    case 'md-html-run':
      mdHtmlRun(control);
      break; // a run of raw HTML blocks opens or closes (md-surface.ts)
    case 'repick':
      startRepick();
      break;
    case 'rp-cancel':
      cancelRepick();
      break;
    case 'rp-apply':
      applyRepick();
      break;
    case 'sec-toggle':
      toggleSec(control.dataset.sec);
      break;
    case 'trash-open':
      openTrash();
      break;
    case 'trash-close':
      $('#trash').close();
      break;
    case 'err-close':
      hideBuildErr();
      break;
    case 'build-err-reopen':
      if (BUILD.error) {
        setSide(true);
        showBuildErr(BUILD.error);
      }
      break; // the chip floats on a collapsed panel; the log is inside it
    case 'status-more':
      toggleStatusList();
      break;
    case 'status-why':
      statusWhy(control);
      break;
    case 'notice-act':
      noticeAct(Number(control.dataset.n));
      break;
    case 'notice-x':
      noticeClose(Number(control.dataset.n));
      break;
    case 'reload':
      reloadForUpdate();
      break;
  }
});
$('#doc-select').addEventListener('change', (event) => switchDoc(event.target.value));
$('#revision-file').addEventListener('change', renderRevisionFile);
// A segmented control is a radio group (docs/handbook/viewer.md §디자인 토큰과 컴포넌트): the whole group is one Tab
// stop, the arrows move inside it and Home/End go to its ends. The one stop is a roving tabindex - the chosen word is
// the one Tab reaches - set wherever a group is drawn or its choice changes (segRove), and the key that moves presses
// the word it moves to, so the arrows and a click take the same path. A key that lands on the word already chosen (Home
// on the first when it is the one, an arrow round a group of one) only moves the focus: pressing a chosen word is no
// new choice. A group whose choice changes the context (data-seg-manual in the markup: [더보기]'s language reopens the
// page, the phone's navigation sheet [원고 | 변경사항] changes the view and closes the sheet) is walked without
// choosing, as tabs with manual activation are (WCAG 3.2.2): the keys only move the focus, and Enter or Space - the
// word's own press - chooses. While the focus walks such a group the stop goes with it, so Tab leaves from where the
// focus is in one step; when the focus leaves, the stop goes back to the chosen word (leaveManualSegment).
const SEGMENT_STEP = { ArrowLeft: -1, ArrowUp: -1, ArrowRight: 1, ArrowDown: 1 };
/** The words of a radio group that can take the focus: neither disabled nor hidden. */
function offeredWords(group: Element) {
  return ([...group.querySelectorAll('[role=radio]')] as HTMLButtonElement[]).filter(
    (word) => !word.disabled && !word.hidden,
  );
}
/** The words of a group on offer that are laid out - the ones a key walks. */
function shownWords(group: Element) {
  return offeredWords(group).filter((word) => word.getClientRects().length);
}
/** Where the focus is among the words a group shows (shownWords), -1 when it is not on one of them. */
function segFocusAt(group: Element) {
  return shownWords(group).indexOf(document.activeElement as HTMLButtonElement);
}
// Three groups draw their words again: the assignee row on every pick and every change of the note (mentions.ts
// assigneeRowHtml), the range ladder with every range (levels.ts drawLadder - a pick that leaves the excerpt short of
// lines draws it again once more when they come back, excerpt.ts excerptFetch) and [더보기]'s size on every pick and
// relayout (panel-size.ts renderSizeSeg). The word with the focus goes with the old words, and the focus would land on
// the body: an arrow's walk would end there, as would Enter or Space on the chosen word, and the next Tab would begin
// again from the page's start. So each draw notes where the focus was (segFocusAt) and gives it back to the word now at
// `index` - the last when there are fewer - as no new focus: a description shows only after a key (tooltip.ts
// focusGivenBack). A group drawn away (no people left to assign) has none, and the focus stays.
function segKeep(group: Element, index: number) {
  if (index < 0) return;
  const words = shownWords(group),
    word = words[Math.min(index, words.length - 1)];
  if (word) focusGivenBack(word);
}
/** Keep one Tab stop in a radio group: the chosen word, else the first one on offer. It reads the markup only, not the
 * layout, so a group drawn while its panel is closed holds its one stop before it shows. */
function segRove(group: Element | null) {
  if (!group) return;
  const words = offeredWords(group),
    on = words.find((word) => word.getAttribute('aria-checked') === 'true') || words[0];
  for (const word of words) word.tabIndex = word === on ? 0 : -1;
}
// the groups in the page's markup; a drawn one calls segRove itself
for (const group of $$('[role=radiogroup]')) segRove(group);
document.addEventListener('keydown', (event) => {
  const target = event.target as HTMLElement;
  if (imeKey(event) || event.ctrlKey || event.metaKey || event.altKey) return;
  if (!target || !target.closest || target.getAttribute('role') !== 'radio') return;
  const group = target.closest('[role=radiogroup]');
  if (!group) return;
  const words = shownWords(group),
    index = words.indexOf(target as HTMLButtonElement);
  if (index < 0) return;
  const step = SEGMENT_STEP[event.key];
  const to =
    step !== undefined
      ? (index + step + words.length) % words.length
      : event.key === 'Home'
        ? 0
        : event.key === 'End'
          ? words.length - 1
          : -1;
  if (to < 0) return;
  event.preventDefault();
  const word = words[to];
  if (group.hasAttribute('data-seg-manual')) {
    for (const offered of offeredWords(group)) offered.tabIndex = offered === word ? 0 : -1;
    word.focus();
    return;
  } // the focus only
  word.tabIndex = 0;
  word.focus();
  // a group the press draws again keeps the focus (segKeep)
  if (word.getAttribute('aria-checked') !== 'true') word.click();
  segRove(group);
});
// The focus has left a group walked without choosing: its stop is the chosen word again, where Tab and Shift+Tab come
// back to.
function leaveManualSegment(event: FocusEvent) {
  const target = event.target as HTMLElement,
    group = target && target.closest ? target.closest('[role=radiogroup][data-seg-manual]') : null;
  const to = event.relatedTarget as Node | null;
  if (group && !(to && group.contains(to))) segRove(group);
}
document.addEventListener('focusout', leaveManualSegment);
// A ladder's scroll box (.seg.lad) is no Tab stop (tabindex="-1": Firefox makes a box that overflows one of its own),
// but a press on it - the gap between two words, its edge - still gives it the focus, and from a focused box with
// tabindex -1 Firefox's next Tab would begin again at the page's start. So the focus such a press gives the box goes on
// to the group's one stop (segRove's word) as no new focus (focusGivenBack: no description), and Tab leaves from there,
// as from a word.
function passLadderBoxFocus(event: FocusEvent) {
  const box = event.target as HTMLElement;
  if (!box || !box.matches || !box.matches('.seg.lad[tabindex="-1"]')) return;
  const group = box.matches('[role=radiogroup]') ? box : box.querySelector('[role=radiogroup]') || box,
    words = offeredWords(group),
    word = words.find((offered) => offered.tabIndex === 0) || words[0];
  if (word) focusGivenBack(word);
}
document.addEventListener('focusin', passLadderBoxFocus);

document.addEventListener('keydown', (event) => {
  if (imeKey(event)) return; // an input method's key, the Enter or Esc that ended its composition too (core.ts)
  const target = event.target as HTMLElement,
    inField =
      target &&
      (target.tagName === 'TEXTAREA' ||
        target.tagName === 'INPUT' ||
        target.tagName === 'SELECT' ||
        target.isContentEditable);
  // Ctrl(Cmd) + = / - / 0 zooms/fits just the PDF page instead of the browser zoom. Left to the browser inside an input
  // field.
  if ((event.ctrlKey || event.metaKey) && !event.altKey && !inField && !isMdDoc()) {
    const zoomAction = zoomKey(event); // a Markdown document's text zooms with the browser
    if (zoomAction) {
      if (document.body.classList.contains('revision-open')) {
        if (!revisionPdfActive()) return;
      }
      event.preventDefault();
      zoomVisiblePdf(zoomAction);
      return;
    }
  }
  // Document switching (multiple documents): Ctrl+PgUp/PgDn is previous/next, Alt+1...9 is that index (event.code -
  // Option+digit on Mac produces a different character). The selector uses default keyboard handling. Global shortcuts
  // are never used inside an input field.
  if (multiDoc() && !inField) {
    if (event.ctrlKey && !event.altKey && !event.metaKey && (event.key === 'PageUp' || event.key === 'PageDown')) {
      event.preventDefault();
      closePageList(false);
      closeDocMenu($('#doc-pop').contains(target));
      cycleDoc(event.key === 'PageDown' ? 1 : -1);
      return;
    }
    if (event.altKey && !event.ctrlKey && !event.metaKey && /^Digit[1-9]$/.test(event.code || '')) {
      const entry = DOCS[+event.code.slice(5) - 1];
      if (entry) {
        event.preventDefault();
        closePageList(false);
        closeDocMenu($('#doc-pop').contains(target));
        switchDoc(entry.key);
      }
      return;
    }
  }
  // Ctrl(Cmd)+\ opens and collapses the pin panel at every width (docs/handbook/viewer.md §패널 폭과 시트 높이) - not
  // inside a text field.
  if (
    (event.ctrlKey || event.metaKey) &&
    !event.altKey &&
    !inField &&
    (event.code === 'Backslash' || event.key === '\\')
  ) {
    event.preventDefault();
    toggleSide();
    return;
  }
  if (event.key === 'Enter' && (event.metaKey || event.ctrlKey)) {
    if (
      target &&
      (target.id === 'note' ||
        target.id === 'c-sg-text' ||
        (target.closest && target.closest('#sel-pop')) ||
        (target.closest && target.closest('#composer') && !$('#composer').hidden && !inField))
    ) {
      event.preventDefault();
      if (!viewerBlocked()) savePin();
    } else if (
      target &&
      target.classList &&
      (target.classList.contains('e-note') || target.classList.contains('e-sg-text'))
    ) {
      event.preventDefault();
      saveEdit();
    } else if (target && target.classList && target.classList.contains('r-text')) {
      event.preventDefault();
      sendReply();
    }
    return;
  }
  if (event.key === 'Enter' && target && target.dataset && target.dataset.copy !== undefined && !inField) {
    copyText(target.dataset.copy, target);
    return;
  }
  // A span with role=button (a card's #number) is also activated by Enter/Space - sent through the same data-act path
  // as a click.
  if (
    (event.key === 'Enter' || event.key === ' ') &&
    target &&
    target.getAttribute &&
    /^(button|link)$/.test(target.getAttribute('role') || '') &&
    target.dataset &&
    target.dataset.act &&
    !inField
  ) {
    event.preventDefault();
    target.click();
    return;
  }
  if (event.key === 'Escape') {
    if ($('#help').open || $('#more').open || $('#nav-sheet').open || $('#trash').open || $('#status-list').open)
      return;
    if (!$('#page-pop').hidden) {
      event.preventDefault();
      closePageList(true);
      return;
    } // the page list first: it floats over everything below
    if (!$('#doc-pop').hidden) {
      event.preventDefault();
      closeDocMenu(true);
      return;
    } // so does the documents popover
    if (!TIP.hidden) {
      hideTip();
      if (!inField) {
        event.preventDefault();
        return;
      }
    }
    // Each Esc closes the top thing only; a handled Esc is not also a close request (the back-gesture layer's
    // CloseWatcher).
    if (outlineOverlay() && OUTLINE_MID_OPEN) {
      event.preventDefault();
      toggleOutline();
      return;
    }
    if (REPICK) {
      event.preventDefault();
      cancelRepick();
      return;
    }
    if (REPLY) {
      event.preventDefault();
      closeReply();
      return;
    }
    if (EDITOR.current) {
      event.preventDefault();
      cancelEdit();
      return;
    }
    if (COMPOSE.current || !$('#composer').hidden) {
      event.preventDefault();
      discardSelection();
      return;
    }
    if (SELMODE) {
      event.preventDefault();
      setSelMode(false);
      return;
    } // a keyboard ends the select mode as [끝내기] does
    if (RV_PICK && target && target.closest && target.closest('#sec-review')) {
      event.preventDefault();
      rvPick(false);
      return;
    } // the review section's pick, from inside it (review-pick.ts)
    // The 701-900px overlay panel covers the document: Esc collapses it (a selection above is cancelled first).
    if (LAYOUT === LAYOUT_MODE.MID && MID_OVERLAY && SIDE_OPEN) {
      event.preventDefault();
      setSide(false, true, true);
      focusSideToggle();
      return;
    }
    if (document.body.classList.contains('revision-open')) {
      event.preventDefault();
      revBack();
      return;
    } // Esc in [변경 보기] = [원고로]
    return;
  }
  if (event.key === '?' && !inField && !event.metaKey && !event.ctrlKey && !event.altKey) {
    event.preventDefault();
    openHelp();
  }
});
boot();
export { segFocusAt, segKeep, segRove };
