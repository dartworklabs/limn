// ------------------------------------------------ Viewer startup and page-wide input
import {
  DOCS,
  LAYOUT,
  MENTION_ONLY,
  MID_OVERLAY,
  OPEN_CARDS,
  OUTLINE_MID_OPEN,
  REPICK,
  REPLY,
  setReplyFlip,
  SELMODE,
  SHOW_ALL,
  SIDE_OPEN,
  SNIP_OPEN,
  THREAD_OPEN,
  imeKey,
  setMentionOnly,
  setShowAll,
  setSnipOpen,
  REVIEW_ALL,
  setDoc,
  setMeta,
  knownMeta,
  META_BY,
  DOC,
  VIEW_BY,
  COARSE_POINTER_QUERY,
  DOC_SEQ,
  COMPOSE,
  EDITOR,
  setComposeDismissedOverlap,
  setComposeIntent,
  setEditAssignee,
  setEditRequestKind,
} from './app/state.ts';
import { switchLang, i18nStart, translate } from './platform/i18n.ts';
import { setTheme, applyTheme, savePrefs, prefs } from './platform/prefs.ts';
import { copyText, setRequestFallback, api } from './platform/api.ts';
import {
  bannerNote,
  noticeAct,
  noticeClose,
  setNoticeComposer,
  setNoticeFocus,
  setNoticePanel,
  setNoticeStatusLine,
  digestBegin,
  DIGEST,
  digestSoon,
} from './platform/notices.ts';
import { watchTooltips, TIP, focusGivenBack, hideTip } from './platform/tooltip.ts';
import {
  closeDocMenu,
  multiDoc,
  toggleDocMenu,
  loadDocs,
  initialDoc,
  setHash,
  drawDocTabs,
} from './documents/view-tabs.ts';
import { REVISION_VIEW } from './revisions/state.ts';
import { drawPinGuideActions } from './revisions/view-pin-guide.ts';
import {
  moreRevisions,
  pressRevisionRow,
  renderRevisionFile,
  returnToManuscript,
  setRevisionFormat,
  setRevisionRange,
  setRevisionSide,
  setRevisionWhole,
  setViewMode,
  showChange,
  loadRevisions,
  showRevision,
  toggleRevisionOther,
  renderCommitList,
  COMPARISON_SCOPE,
} from './revisions/flow.ts';
import {
  cycleDoc,
  openNavigationSheet,
  switchDoc,
  loadViews,
  applyViewWidth,
  restoreView,
  saveView,
} from './documents/flow-switch.ts';
import {
  notifyToggle,
  takeLinkHash,
  drawNotify,
  notifySupported,
  notifyPerm,
  notifyRegister,
  openPinFromLink,
  notifyOn,
  notifyQuery,
  notifyHandle,
  notifyCursor,
} from './pins/flow-notification.ts';
import { setBuildLastSeq, startBuildPolling, rebuild } from './documents/flow-build.ts';
import { setBuildUnchanged, SHOWN_BUILD } from './documents/state-build.ts';
import { reloadForUpdate, visitedBefore, checkDocsSeen, DIGEST_TAIL_MS } from './documents/flow-updates.ts';
import {
  watchStatusPlacement,
  drawStatus,
  statusWhy,
  toggleStatusList,
  STATUS_TOP,
  setStatusSig,
  placeStatus,
} from './documents/view-status.ts';
import { applySideWidth, outlineOverlay } from './layout/flow-panel-size.ts';
import { arrivalLetGo } from './layout/flow-scroll.ts';
import { sizePreset } from './layout/flow-panel-actions.ts';
import {
  actualSize,
  fitToWidth,
  goSheetPage,
  zoom,
  buildDoc,
  autoFitWidth,
  pageSrc,
  reapplyScale,
  startScale,
  widestPagePoints,
  drawZoom,
} from './pdf/view-pages.ts';
import {
  dropOutlinePick,
  pickOutline,
  updateSectionStrip,
  OUTLINE_ACTIVE_PAGE,
  markOutline,
} from './pdf/view-outline.ts';
import {
  watchPageListPlacement,
  closePageList,
  goListedPage,
  togglePageList,
  drawSheetPages,
  revealPageRow,
  tipCutTitles,
} from './pdf/view-page-list.ts';
import { watchSearchDismissal, searchClose, searchGo, searchOpen, searchFit, searchLeave, SEARCH } from './pdf/flow.ts';
import { revisionPdfActive, revisionZoom } from './revisions/input.ts';
import { zoomKey } from './pdf/input-zoom.ts';
import {
  watchFrameSize,
  toggleOutline,
  applyOutlineState,
  focusSideToggle,
  headInk,
  openMore,
  setSelectMode,
  setSide,
  showSheet,
  toggleSide,
  applyLayout,
  coach,
  onRelayout,
  setFrameHost,
} from './layout/flow.ts';
import { applyRange, dropLine, widenTo } from './composer/view-excerpt.ts';
import { showElementBox } from './pdf/view-figure.ts';
import { watchReadingScroll } from './markdown/input-navigation.ts';
import { goToAnchor, goToDocLink } from './markdown/flow-links.ts';
import { toggleHtmlRun } from './markdown/view-html.ts';
import { MARKDOWN_VIEW } from './markdown/state.ts';
import { buildMarkdownDoc } from './markdown/view.ts';
import { checkTreeImages } from './markdown/flow-image-refresh.ts';
import { lineLeaves, readingAnchor, keepReadingSpot, goToHeading } from './markdown/view-reading.ts';
import { markdownPositionLabel, showMarkdownHint, updateMarkdownStrip } from './markdown/view-outline.ts';
import { showLines } from './markdown/view-marks.ts';
import { stepChangeGroup } from './revisions/view-rendered-compare.ts';
import { SUGGEST_OPEN, suggestAct } from './composer/flow-suggest.ts';
import {
  discardSelection,
  renderComposer,
  setKind,
  toggleQuote,
  cancelSelection,
  setBusy,
} from './composer/flow-selection.ts';
import { recomputeOverlap, renderOverlapBanner } from './composer/view-overlap.ts';
import { pick } from './composer/flow-pick.ts';
import { syncDraft, saveDraftSoon, parkDraft } from './composer/flow-draft.ts';
import { restoreDraft, openDraftDoc } from './composer/flow-restore-draft.ts';
import { appendToPin, savePin } from './composer/flow-save.ts';
import { saveButtonLabel } from './composer/view-save.ts';
import {
  offlineFlush,
  offlinePrepare,
  offReadKey,
  offStaleSaid,
  offStash,
  offStashed,
  offlineBack,
  offlineMayServe,
  offlineAskDown,
  offlineBoot,
  OFF,
  offlinePick,
  offlineQueueSave,
  offlineKey,
} from './offline/flow.ts';
// Install the queued pin controls.
import './offline/input.ts';
import { READING_LINE_PAGE } from './verdict/state-lines.ts';
import { stickSoon, setVerdictLineRenderer } from './verdict/state-line-renderer.ts';
import { watchVerdictFold } from './verdict/input-typing-fold.ts';
import { cancelLineVerdict, undoFromLine, verdictUndo } from './verdict/flow-cancel.ts';
import { verdictPress } from './verdict/flow-save.ts';
import { watchVerdictFonts } from './verdict/view-line-fit.ts';
import { sizePageLines } from './verdict/view-line-fit.ts';
import { renderVerdictRow, figureVerdictBody, figureVerdictRoot, verdictDropped } from './verdict/flow-words.ts';
import {
  drawPageVerdicts,
  isShownOnLine,
  jumpToPageLine,
  fillPageLine,
  stickReadingLine,
  watchLineChips,
} from './verdict/flow-line.ts';
import { watchVerdictLayout } from './verdict/input-lines.ts';
import { goToSummaryPage } from './verdict/input-lines.ts';
import { isReasonField, isComposingNow } from './verdict/view-reason-field.ts';
import { watchReasonInput } from './verdict/input-reason.ts';
import { actOnReason, afterComposition } from './verdict/input-reason.ts';
import { focusLine, holdReasonFocus, restoreReasonFocus } from './verdict/view-reason.ts';
import { watchPanelNavigation, setBuildReadingPage, pageUnderReadingLine } from './verdict/view-panel.ts';
import {
  handPopoverToComposer,
  openSelectionPopover,
  isSelectionPopoverOpen,
  SELECTION_POPOVER,
  SELECTION_POPOVER_BOX,
  placeSelectionPopover,
} from './composer/view-selection-popover.ts';
import { MESSAGE_OPEN } from './pins/view-card-parts.ts';
// Refresh claim ages while the page is open.
import './pins/flow-claims.ts';
import { tickRel, ARC_OPEN, openTrash } from './pins/view-cards.ts';
import { REVIEW_PICK } from './pins/view-review-pick.ts';
import { confirmTicked, setReviewPicking, goToReviewCard } from './pins/flow-review-pick.ts';
import {
  watchPinPlacement,
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
  toggleSection,
  marks,
} from './pins/flow-list.ts';
import { marksKeyDown, MARKS, marksSet } from './pins/input-hide-marks.ts';
import { closePin, confirmPin, dropPin, purgePin, trashRestore, unclaimPin } from './pins/flow-actions.ts';
import { setAssignNewValue, setAssignNewTouched } from './composer/state-assignee.ts';
import { watchMentions, mentionApply, renderAssignEdit, renderAssignNew } from './composer/input-mentions.ts';
import { renderReplyOutcome, replyNote } from './pins/view-reply.ts';
import { closeReply, openReply, sendReply } from './pins/flow-reply.ts';
import { growEditedField, cancelEdit, openEdit, saveEdit, editSnip } from './pins/flow-edit.ts';
import { setComposerPins, setComposerQueue, setComposerVerdict, setPinFields } from './composer/state-seams.ts';
import { setPinVerdicts } from './pins/state-seams.ts';
import { applyRepick, badgeMovePin, repickFromBadge, restartRepick, startRepick } from './composer/flow-repick.ts';
import { downloadPdf, hideBuildErr, showBuildErr, syncBuildErrChip } from './documents/flow-rebuild.ts';
import { NOTICE_HOST, NOTICE_KIND } from './platform/tables.ts';
import { $, $$, eventElement, findClosest, focusedElement } from './platform/dom.ts';
import { offeredWords, shownWords, roveSegment } from './platform/segments.ts';
import { REQUEST_KIND, LAYOUT_MODE } from './app/rules-tables.ts';
import { isMarkdownDoc, viewerBlocked, withDocQuery, isTextDoc, pageVerdictsOn } from './documents/state.ts';
import { useLevel } from './documents/rules.ts';
import { setHtml } from './platform/markup.ts';
import { bootVector, openVectorDocument } from './pdf/flow-open.ts';
import { watchVectorViewport, releaseAllVectorPages } from './pdf/view-draw.ts';
import {
  setChangesView,
  setDocumentNavigation,
  setDocumentPins,
  setDocumentWork,
  setMarkdownSurface,
  setOfflineQueue,
  setPageNavigation,
  setPageSurface,
  setPinNotifications,
  setVerdictHold,
} from './documents/state-seams.ts';
import { setLineMarks, setLinePick, setTextSurface } from './markdown/state-seams.ts';
import { buildTextView, textLevels } from './text/view.ts';
import { setPageChanges, setPageMarkdown, setPageMarks, setPageSelection, setPageVerdicts } from './pdf/state-seams.ts';
import { setLastPinsRevision, setLastSrcMtime, startLightPolling, pollLight } from './documents/flow-polling.ts';
import { drawMeta } from './documents/view-meta.ts';
import { renderEdit, editDirty } from './pins/view-edit.ts';
import { cancelRepick, bannerCompare } from './composer/flow-repick-banner.ts';
import {
  pageVerdictPins,
  verdictBadge,
  verdictTarget,
  verdictOldMarker,
  dropPageLineOverlaps,
  figureShort,
} from './verdict/view-pins.ts';
import { fitBarWords, updateReviewCount } from './pins/view-bar.ts';
import { dropBareDayLines, placeRow } from './pins/view-list-sections.ts';
import { markBadgeSides } from './pins/view-mark-covers.ts';

// The seams platform calls the features through (docs/handbook/viewer.md §모듈 경계), each registered here once. This
// runs before boot() and before any listener can fire (no code that runs while the script loads calls one), so no
// platform call meets an unregistered seam; each member is the function the platform code called directly before.
setRequestFallback({
  readKey: offReadKey,
  mayServe: offlineMayServe,
  stashed: offStashed,
  staleSaid: offStaleSaid,
  back: offlineBack,
  stash: offStash,
});
setNoticeStatusLine({
  top: () => STATUS_TOP,
  draw: drawStatus,
  setSignature: setStatusSig,
  toggleList: toggleStatusList,
});
setNoticePanel({ sideOpen: () => SIDE_OPEN, reviewPins: () => REVIEW_ALL, placeRow, dropBareDayLines });
setNoticeFocus({
  fieldOpen: () => !!EDITOR.current || !!REPLY,
  pageLinesOn: () => !!pageVerdictsOn(),
  readingLinePage: () => READING_LINE_PAGE,
  focusLine,
  isReasonField,
});
setNoticeComposer({ saveButtonLabel });
// The seams documents calls the features above it through (documents/state-seams.ts), registered the same way.
setPageSurface({
  build: buildDoc,
  fitWidth: autoFitWidth,
  widestPoints: widestPagePoints,
  startScale,
  reapplyScale,
  pageSource: pageSrc,
  openVector: openVectorDocument,
  releaseVector: releaseAllVectorPages,
});
setPageNavigation({
  leaveSearch: searchLeave,
  fitSearch: searchFit,
  closePageList,
  outlinePage: () => OUTLINE_ACTIVE_PAGE,
  markOutline,
  drawSheetPages,
  revealPageRow,
  tipCutTitles,
});
setMarkdownSurface({
  reading: () => MARKDOWN_VIEW,
  build: buildMarkdownDoc,
  checkTreeImages,
  readingAnchor,
  positionLabel: markdownPositionLabel,
  showHint: showMarkdownHint,
  lineLeaves,
  showLines,
});
setChangesView({ wanted: () => REVISION_VIEW, setMode: setViewMode, load: loadRevisions });
setDocumentWork({
  parkDraft,
  restoreDraft,
  openDraft: openDraftDoc,
  cancelRepick,
  cancelSelection,
  editDirty,
  cancelEdit,
  replyNote,
});
setDocumentPins({ load: loadPins, draw: drawPins, marks });
setPinNotifications({
  on: notifyOn,
  query: notifyQuery,
  handle: notifyHandle,
  cursor: notifyCursor,
  openFromLink: openPinFromLink,
});
setVerdictHold({
  readingPage: pageUnderReadingLine,
  holdReadingPage: setBuildReadingPage,
  composing: isComposingNow,
  afterComposition,
});
setDocumentNavigation({ open: switchDoc });
setOfflineQueue({ queued: () => OFF.n, held: () => OFF.held, flush: offlineFlush });
// The frame's seams: the features that act on the steps of a relayout, in the order those steps' calls ran (the pin
// list first, then the pages, the Markdown surface, the composer), and the parts of the frame features draw.
onRelayout({ layoutChanged: drawPins, fieldKeptInView: fitBarWords });
onRelayout({ widthsApplied: autoFitWidth, barStuck: updateSectionStrip });
onRelayout({ anchorRestored: keepReadingSpot });
onRelayout({ selectionHeld: renderComposer });
setFrameHost({
  placeStatus,
  drawChangesView: () => {
    if (REVISION_VIEW.target) drawPinGuideActions();
    if (REVISION_VIEW.rows.length) renderCommitList();
  },
  updateReviewCount,
  syncBuildErrorChip: syncBuildErrChip,
  stickSoon,
  drawZoom,
  fitBarWords,
  searchOpen: () => SEARCH.open,
  setHash,
});
// The seams the page surface calls the features above it through (pdf/state-seams.ts).
setPageMarks({ draw: marks, placeBadges: markBadgeSides });
setPageVerdicts({ holdReasonFocus, restoreReasonFocus, sizeLines: sizePageLines, pagePins: pageVerdictPins });
setPageSelection({
  pick,
  badgeMove: badgeMovePin,
  repickFromBadge,
  restartRepick,
  cancelRepick,
  discard: discardSelection,
  openPopover: openSelectionPopover,
  popoverOpen: isSelectionPopoverOpen,
  popover: () => SELECTION_POPOVER,
  popoverBox: () => SELECTION_POPOVER_BOX,
  placePopover: placeSelectionPopover,
});
setPageMarkdown({
  drawn: () => MARKDOWN_VIEW,
  build: buildMarkdownDoc,
  goToHeading,
  updateStrip: updateMarkdownStrip,
});
setPageChanges({ setMode: setViewMode });
// The seams the Markdown surface calls the features above it through (markdown/state-seams.ts).
setTextSurface({ build: buildTextView, levels: textLevels });
setLinePick({ compare: bannerCompare, setBusy, renderComposer, renderVerdictRow });
setLineMarks({ draw: marks });
// The composer's seams (composer/state-seams.ts) and the pin list's (pins/state-seams.ts): the verdict row and the
// verdict a save carries, the pin list a save changes, the queue a save goes into while cut off, the edit card and the
// reply that share the composer's text tools, and what a verdict adds to the pin list.
setComposerVerdict({
  drawRow: renderVerdictRow,
  figureBody: figureVerdictBody,
  figureRoot: figureVerdictRoot,
  figureShort,
  undo: verdictUndo,
  dropped: verdictDropped,
});
setComposerPins({ load: loadPins, drop: dropPin });
setComposerQueue({ pick: offlinePick, save: offlineQueueSave, keyed: () => OFF.idem, key: offlineKey });
setPinFields({ snipEdit: editSnip, drawReplyOutcome: renderReplyOutcome });
setPinVerdicts({
  badge: verdictBadge,
  target: verdictTarget,
  oldMarker: verdictOldMarker,
  dropOverlaps: dropPageLineOverlaps,
  drawLines: drawPageVerdicts,
  shownOnLine: isShownOnLine,
  jumpToLine: jumpToPageLine,
});
setVerdictLineRenderer({ watchLineChips, drawPageVerdicts, fillPageLine, stickReadingLine });

// A captured click dismisses notices before a tooltip can swallow it or the page list can close.
watchTooltips();
watchSearchDismissal();

// Cancel stale page arrivals and outline jumps before fitting the frame. Place overlays after measuring the pages.
watchStatusPlacement();
window.addEventListener('resize', arrivalLetGo);
window.addEventListener('resize', dropOutlinePick);
watchPageListPlacement();
watchVectorViewport();
watchFrameSize();
watchReadingScroll();
watchVerdictFold();
watchVerdictFonts();
watchVerdictLayout();
$('#left').addEventListener('scroll', placeSelectionPopover, { passive: true });
window.addEventListener('resize', placeSelectionPopover);
watchPinPlacement();

// Verdict line controls handle a key or end a glide before the panel, mark shortcuts and mention picker respond.
watchReasonInput();
watchPanelNavigation();
window.addEventListener('keydown', marksKeyDown);
watchMentions();
document.addEventListener('input', growEditedField);

// An expired claim can redraw the cards. Refresh their relative timestamps after the claim clock.
setInterval(tickRel, 60000);

// The revisions listener first restores the manuscript, whose reading position belongs in session storage.
window.addEventListener('pagehide', saveView);
window.addEventListener('pagehide', syncDraft);

let HELP_BACK: HTMLElement | null = null;
// Opens help with its head on one ink line (headInk); closing it gives the focus back to what had it.
function openHelp() {
  const dialog = $('#help');
  if (dialog.open) return;
  HELP_BACK = focusedElement();
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
function zoomVisiblePdf(action: 'in' | 'out' | 'fit' | 'actual') {
  if (document.body.classList.contains('revision-open')) {
    if (action !== 'actual') revisionZoom(action);
  } else if (action === 'fit') fitToWidth();
  else if (action === 'actual') actualSize();
  else zoom(action === 'in' ? 1 : -1);
}
// compact: a click on a collapsed card that hit nothing of its own opens the card, as its preview line and chevron do
// (the card's 44px links and chips keep their own action). wide cards are always open.
function openTappedCard(target: Element) {
  const card = target.closest('.pin.card:not(.open):not(.editing)');
  if (
    !(card instanceof HTMLElement) ||
    LAYOUT === LAYOUT_MODE.WIDE ||
    target.closest('[data-copy],button,input,textarea')
  )
    return;
  OPEN_CARDS.add(Number(card.dataset.id));
  drawPins();
}
document.addEventListener('click', (event) => {
  const target = eventElement(event);
  if (!target) return;
  const copier = findClosest(target, '[data-copy]', HTMLElement);
  if (copier) {
    copyText(copier.dataset.copy || '', copier);
    return;
  }
  const control = findClosest(target, '[data-act]', HTMLElement);
  if (!control) {
    openTappedCard(target);
    return;
  }
  const host = findClosest(control, '[data-id]', HTMLElement),
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
      setSelectMode(!SELMODE);
      if (SELMODE && LAYOUT === LAYOUT_MODE.NARROW && !COMPOSE.current && !EDITOR.current) setSide(false);
      break;
    case 'selmode-end':
      setSelectMode(false);
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
      setBuildUnchanged(null);
      drawStatus();
      rebuild(true);
      break; // the status line's [그래도 빌드]: a cold build
    case 'offline-prepare':
      void offlinePrepare();
      break; // [더보기]'s [오프라인으로 받기] (offline/flow.ts)
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
      break; // [더보기]'s [핀 표시] switch (pins/input-hide-marks.ts)
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
      break; // a verdict word's button: the composer's row or a page verdict line (verdict/flow-save.ts)
    case 'pv-earlier':
      gotoPinRef(Number(control.dataset.ref), event.detail === 0);
      break;
    case 'pv-cancel':
      cancelLineVerdict(control);
      break; // a page line's [판정 취소] on the person's own open verdict (verdict/flow-cancel.ts)
    // a page line's reason and its popover (verdict/input-reason.ts)
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
      break; // a page's summary beside the verdict panel brings that page to it (verdict/view-panel.ts)
    case 'pv-undo':
      undoFromLine(control);
      break; // a take-back's [되돌리기] on its line (verdict/flow-cancel.ts)
    case 'pop-more':
      handPopoverToComposer();
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
      setComposeDismissedOverlap(control.dataset.key || null);
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
      break; // a suggested edit's switch and line (composer/flow-suggest.ts)
    case 'sg-fold': {
      const key = control.dataset.key;
      if (!key) break;
      if (SUGGEST_OPEN.has(key)) SUGGEST_OPEN.delete(key);
      else SUGGEST_OPEN.add(key);
      drawPins();
      break;
    } // a card's suggestion diff
    case 'level': {
      const draft = inEdit ? EDITOR.current : COMPOSE.current;
      if (!draft) break;
      useLevel(draft, control.dataset.level);
      if (!inEdit) {
        setComposeIntent(COMPOSE.intent + 1);
        recomputeOverlap();
      }
      inEdit ? renderEdit() : renderComposer();
      break;
    }
    case 'xp-to': {
      const draft = inEdit ? EDITOR.current : COMPOSE.current,
        line = Number(control.dataset.line);
      if (draft && draft.lo != null && draft.hi != null)
        applyRange(
          draft,
          widenTo(draft.lo, draft.hi, line),
          line < draft.lo ? draft.hi : draft.lo,
          inEdit ? renderEdit : renderComposer,
        );
      break;
    } // the excerpt: widen to a dimmed line
    case 'xp-drop': {
      const draft = inEdit ? EDITOR.current : COMPOSE.current,
        line = Number(control.dataset.line);
      if (draft && draft.lo != null && draft.hi != null)
        applyRange(
          draft,
          dropLine(draft.lo, draft.hi, line),
          line === draft.lo ? draft.hi : draft.lo,
          inEdit ? renderEdit : renderComposer,
        );
      break;
    } // ...or drop an end line
    case 'view':
      if (id !== null) jumpPin(id);
      break;
    case 'edit':
      if (id !== null) openEdit(id);
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
      break; // the composer's element path: show the chosen element's box on the page (pdf/view-figure.ts)
    case 'doc-more':
      toggleDocMenu();
      break; // [+N]: the documents popover (documents/view-tabs.ts)
    case 'nav-sheet':
      openNavigationSheet();
      break;
    case 'nav-sheet-close':
      $('#nav-sheet').close();
      break;
    case 'ns-go':
      goSheetPage();
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
      returnToManuscript();
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
      stepChangeGroup(Number(control.dataset.step) || 0);
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
      setReviewPicking(!REVIEW_PICK);
      break;
    case 'rv-go':
      confirmTicked();
      break;
    case 'rv-card':
      if (id != null) goToReviewCard(id);
      break; // confirming from result rows (pins/flow-review-pick.ts)
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
      setAssignNewValue(control.dataset.v || 'agent');
      setAssignNewTouched(true);
      renderAssignNew();
      saveDraftSoon();
      break;
    case 'assign-edit':
      if (EDITOR.current) {
        setEditAssignee(EDITOR.current, control.dataset.v || 'agent');
        renderAssignEdit();
      }
      break;
    case 'msg-more': {
      const key = control.dataset.key;
      if (!key) break;
      if (MESSAGE_OPEN.has(key)) MESSAGE_OPEN.delete(key);
      else MESSAGE_OPEN.add(key);
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
      setRevisionWhole(!COMPARISON_SCOPE.whole);
      break;
    case 'mark-jump':
      revealCard(id);
      jumpToCard(id);
      break;
    case 'close':
      if (id !== null) closePin(id);
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
      // [질문으로 보내기] hides itself (syncQuestionHint), which would drop focus to <body> and make Ctrl+Enter do
      // nothing - back to the memo.
      if (fromHint) {
        const note = $('#note');
        note.focus({ preventScroll: true });
        note.setSelectionRange(note.value.length, note.value.length);
      }
      break;
    }
    case 'e-kind':
      if (EDITOR.current) {
        setEditRequestKind(
          EDITOR.current,
          control.dataset.kind === REQUEST_KIND.QUESTION ? REQUEST_KIND.QUESTION : REQUEST_KIND.FIX,
        );
        renderEdit();
      }
      break;
    case 'reply-open':
      if (id != null) openReply(id);
      break;
    case 'reply-flip':
      if (REPLY) {
        setReplyFlip(REPLY, !REPLY.flip);
        renderReplyOutcome();
      }
      break;
    case 'confirm': {
      if (id == null) break;
      const inGuide = !!control.closest('#revision-pin,#revision-acts'); // before confirmPin redraws the guide line
      confirmPin(id);
      if (inGuide) returnToManuscript();
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
      goToAnchor(control);
      break; // an in-document #heading link of the Markdown surface
    case 'md-doc':
      goToDocLink(control);
      break; // a link to another registered document (markdown/view.ts, ADR-0030)
    case 'md-html-run':
      toggleHtmlRun(control);
      break; // a run of raw HTML blocks opens or closes (markdown/view.ts)
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
      toggleSection(control.dataset.sec);
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
      if (SHOWN_BUILD.error) {
        setSide(true);
        showBuildErr(SHOWN_BUILD.error);
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
    case 'reload-viewer':
      reloadForUpdate();
      break;
    case undefined: // control matched [data-act], so the attribute is there; nothing to do without it
      break;
  }
});
$('#doc-select').addEventListener('change', (event: Event) => {
  if (event.target instanceof HTMLSelectElement) switchDoc(event.target.value);
});
$('#revision-file').addEventListener('change', renderRevisionFile);
// A segmented control is a radio group (docs/handbook/viewer.md §디자인 토큰과 컴포넌트): the whole group is one Tab
// stop, the arrows move inside it and Home/End go to its ends. The one stop is a roving tabindex - the chosen word is
// the one Tab reaches - set wherever a group is drawn or its choice changes (roveSegment), and the key that moves
// presses the word it moves to, so the arrows and a click take the same path. A key that lands on the word already
// chosen (Home on the first when it is the one, an arrow round a group of one) only moves the focus: pressing a chosen
// word is no new choice. A group whose choice changes the context (data-seg-manual in the markup: [더보기]'s language
// reopens the page, the phone's navigation sheet [원고 | 변경사항] changes the view and closes the sheet) is walked
// without choosing, as tabs with manual activation are (WCAG 3.2.2): the keys only move the focus, and Enter or Space -
// the word's own press - chooses. While the focus walks such a group the stop goes with it, so Tab leaves from where
// the focus is in one step; when the focus leaves, the stop goes back to the chosen word (leaveManualSegment).
const SEGMENT_STEP: Partial<Record<string, number>> = { ArrowLeft: -1, ArrowUp: -1, ArrowRight: 1, ArrowDown: 1 };
// the groups in the page's markup; a drawn one calls roveSegment itself
for (const group of $$('[role=radiogroup]')) roveSegment(group);
document.addEventListener('keydown', (event) => {
  const target = event.target;
  if (imeKey(event) || event.ctrlKey || event.metaKey || event.altKey) return;
  if (!(target instanceof HTMLButtonElement) || target.getAttribute('role') !== 'radio') return;
  const group = target.closest('[role=radiogroup]');
  if (!group) return;
  const words = shownWords(group),
    index = words.indexOf(target);
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
  // a group the press draws again keeps the focus (keepSegmentFocus)
  if (word.getAttribute('aria-checked') !== 'true') word.click();
  roveSegment(group);
});
// The focus has left a group walked without choosing: its stop is the chosen word again, where Tab and Shift+Tab come
// back to.
function leaveManualSegment(event: FocusEvent) {
  const target = eventElement(event),
    group = target ? target.closest('[role=radiogroup][data-seg-manual]') : null;
  const to = event.relatedTarget instanceof Node ? event.relatedTarget : null;
  if (group && !(to && group.contains(to))) roveSegment(group);
}
document.addEventListener('focusout', leaveManualSegment);
// A ladder's scroll box (.seg.lad) is no Tab stop (tabindex="-1": Firefox makes a box that overflows one of its own),
// but a press on it - the gap between two words, its edge - still gives it the focus, and from a focused box with
// tabindex -1 Firefox's next Tab would begin again at the page's start. So the focus such a press gives the box goes on
// to the group's one stop (roveSegment's word) as no new focus (focusGivenBack: no description), and Tab leaves from
// there, as from a word.
function passLadderBoxFocus(event: FocusEvent) {
  const box = eventElement(event);
  if (!box || !box.matches('.seg.lad[tabindex="-1"]')) return;
  const group = box.matches('[role=radiogroup]') ? box : box.querySelector('[role=radiogroup]') || box,
    words = offeredWords(group),
    word = words.find((offered) => offered.tabIndex === 0) || words[0];
  if (word) focusGivenBack(word);
}
document.addEventListener('focusin', passLadderBoxFocus);

document.addEventListener('keydown', (event) => {
  if (imeKey(event)) return; // an input method's key, the Enter or Esc that ended its composition too (app/state.ts)
  const target = event.target instanceof HTMLElement ? event.target : null,
    inField =
      target &&
      (target.tagName === 'TEXTAREA' ||
        target.tagName === 'INPUT' ||
        target.tagName === 'SELECT' ||
        target.isContentEditable);
  // Ctrl(Cmd) + = / - / 0 zooms/fits just the PDF page instead of the browser zoom. Left to the browser inside an input
  // field.
  if ((event.ctrlKey || event.metaKey) && !event.altKey && !inField && !isMarkdownDoc()) {
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
      setSelectMode(false);
      return;
    } // a keyboard ends the select mode as [끝내기] does
    if (REVIEW_PICK && target && target.closest && target.closest('#sec-review')) {
      event.preventDefault();
      setReviewPicking(false);
      return;
    } // the review section's pick, from inside it (pins/flow-review-pick.ts)
    // The 701-900px overlay panel covers the document: Esc collapses it (a selection above is cancelled first).
    if (LAYOUT === LAYOUT_MODE.MID && MID_OVERLAY && SIDE_OPEN) {
      event.preventDefault();
      setSide(false, true, true);
      focusSideToggle();
      return;
    }
    if (document.body.classList.contains('revision-open')) {
      event.preventDefault();
      returnToManuscript();
      return;
    } // Esc in [변경 보기] = [원고로]
    return;
  }
  if (event.key === '?' && !inField && !event.metaKey && !event.ctrlKey && !event.altKey) {
    event.preventDefault();
    openHelp();
  }
});
// Starts the viewer: language, theme and layout, the document list and meta, pages, pins, this tab's kept draft, the
// first-visit hint (touch or mouse), polling and notifications, then a pin link from the hash (#doc=&pin=) if there was
// one.
async function boot() {
  i18nStart();
  // A link /#doc=<key>&pin=<n>[&act=restore] (a notification clicked with no tab open) is read first: the boot below
  // rewrites the hash to #doc=<key> on an instance with several documents, which would lose pin=.
  const link = takeLinkHash();
  applyTheme();
  applyLayout();
  // There's no keyboard shortcut on a touch device - "핀 저장 Ctrl+Enter" would just get clipped at phone width.
  setHtml($('#btn-save'), saveButtonLabel());
  await offlineAskDown(); // a page the worker answered from its copy starts from the stored reads (offline/flow.ts)
  await loadDocs();
  setDoc(initialDoc());
  try {
    setMeta(
      (await api('GET /api/meta', { query: withDocQuery(''), what: '화면 정보 읽기', where: NOTICE_HOST.LINE })).data,
    );
  } catch (error) {
    return;
  }
  const first = knownMeta();
  if (first.doc) setDoc(first.doc);
  META_BY.set(DOC, first);
  loadViews();
  const view = VIEW_BY.get(DOC);
  if (multiDoc()) {
    setHash(DOC);
    savePrefs({ lastDoc: DOC });
  }
  // A device that was here before hears what came since, gathered into one message (docs/handbook/viewer.md §새 소식).
  if (visitedBefore()) digestBegin(translate('지난 방문 뒤'));
  drawMeta();
  applySideWidth();
  applyOutlineState();
  const hadWidth = applyViewWidth(view);
  buildDoc();
  if (!hadWidth) autoFitWidth();
  bootVector();
  const pinsLoaded = await loadPins();
  restoreView(view);
  drawDocTabs();
  updateSectionStrip();
  restoreDraft(); // the page count is there before the first scroll (mid shows it in the nav bar)
  if (isMarkdownDoc())
    coach(
      COARSE_POINTER_QUERY.matches ? 'touch' : 'mouse',
      isTextDoc()
        ? COARSE_POINTER_QUERY.matches
          ? '줄을 누르면 그 줄을, 길게 눌러 글을 고르면 그 줄들을 고릅니다'
          : '누르면 그 줄을, 끌면 그 줄들을 고릅니다' // a text document: a press picks its line
        : COARSE_POINTER_QUERY.matches
          ? '블록을 누르면 그 블록을, 길게 눌러 글을 고르면 그 줄을 고릅니다'
          : '끌면 그 줄을, 누르면 그 블록을 고릅니다',
    );
  else if (COARSE_POINTER_QUERY.matches)
    coach('touch', 'PDF를 길게 누르면 그 문단을 고릅니다 · [선택]을 켜면 끌어서 고릅니다');
  // a mouse user's first hint how to pin (the PDF also shows a crosshair)
  else coach('mouse', 'PDF를 끌어서 고칠 곳을 고르세요');
  // The open document's meta now: a switch while the pins loaded may have replaced the first one.
  const meta = knownMeta();
  // A failed first read has no pin baseline; the light poll must retry even when meta has not changed.
  if (pinsLoaded) {
    setLastPinsRevision(meta.pins_rev);
    setLastSrcMtime(meta.src_sig || meta.src_mtime);
  }
  // the build count this tab has already "seen"
  setBuildLastSeq(typeof meta.build_seq === 'number' ? meta.build_seq : 0);
  (meta.docs || []).forEach((entry) => DOC_SEQ.set(entry.key, entry.build_seq));
  startLightPolling();
  startBuildPolling();
  offlineBoot();
  checkDocsSeen(); // what changed since this device last saw each document (documents/flow-updates.ts)
  if (DIGEST) pollLight().finally(() => digestSoon(DIGEST_TAIL_MS)); // the events addressed to me since the last visit
  drawNotify();
  if (prefs().notify && notifySupported() && notifyPerm() === 'granted') notifyRegister();
  if (link.pin) openPinFromLink(link.doc || DOC, link.pin, link.restore);
}
boot();
