// Draw, discard and restore the current composer selection.
import {
  DOC,
  KIND_NEW,
  LAYOUT,
  META,
  PICKSEQ,
  REPICK,
  SNIP_OPEN,
  captureVisit,
  currentVisit,
  isFigureKind,
  setKindNew,
  setPickseq,
  setSnipOpen,
  COMPOSE,
  EDITOR,
  setComposeBox,
  setComposeCurrent,
  setComposeDismissedOverlap,
  setComposeIntent,
  setComposePicking,
} from '../app/state.ts';
import { renderOverlapBanner, recomputeOverlap } from './view-overlap.ts';
import { html, lucideIcon, setHtml } from '../platform/markup.ts';
import { markHiddenHtml, markHiddenPlain } from '../platform/hidden-chars.ts';
import { translateTemplate, translate, warnText } from '../platform/i18n.ts';
import { lineNote } from '../platform/notices.ts';
import { hideTip, LAST_POINTER } from '../platform/tooltip.ts';
import { applySheet } from '../layout/flow-panel-size.ts';
import { applySide, setSelectMode, setSide } from '../layout/flow.ts';
import { revealBox } from '../pdf/input-selection.ts';
import { drawLadder, onLines, rangeCap, scopeLabel, setCap, snipText, viaTag } from './view-levels.ts';
import { drawExcerpt } from './view-excerpt.ts';
import { figureRegionBadge, renderElement } from '../pdf/view-figure.ts';
import { lineLeaves, markChosenLines, shownChoice } from '../markdown/view.ts';
import { renderSuggest } from './flow-suggest.ts';
import { suggestEdited, SUGGEST_DRAFT, suggestClear, suggestCopy, suggestDraft } from './state-suggest.ts';
import { holdDraftUntil, saveDraftSoon, syncDraft } from './flow-draft.ts';
import { clearPendingSave, syncComposeSaveButtons } from './view-save.ts';
import { closeSelectionPopover, drawSelectionPopover } from './view-selection-popover.ts';
import { ASSIGN_NEW, setAssignNewTouched } from './state-assignee.ts';
import { renderAssignNew } from './input-mentions.ts';
import type { Html } from '../platform/markup.ts';
import { NOTICE_KIND, NOTICE_LIFE } from '../platform/tables.ts';
import { $, focusFell, focusHold, findAll, findMaybe } from '../platform/dom.ts';
import { roveSegment } from '../platform/segments.ts';
import { REQUEST_KIND, LAYOUT_MODE } from '../app/rules-tables.ts';
import { lineRange } from '../app/rules-pins.ts';
import { isMarkdownDoc, isRegion } from '../documents/state.ts';
import { imeOpen } from '../platform/composition.ts';
import { QUOTE_OPEN, autoGrow } from './view-text.ts';
import { composerVerdict } from './state-seams.ts';
import type { Visit } from '../app/state.ts';
import { syncQuestionHint } from './view-note-hints.ts';
import { cancelRepick } from './flow-repick-banner.ts';

/** Capture editable composer fields by value - the suggested edit's switch, text and base among them; derived overlap
 * and snippet updates do not count as new input. */
function composeFields() {
  const selection = COMPOSE.current,
    noteField = $('#note');
  return JSON.stringify({
    note: noteField.value,
    mentions: Array.from(noteField._mentions || []),
    kind: KIND_NEW,
    assign: { ...ASSIGN_NEW },
    range: selection && {
      lo: selection.lo,
      hi: selection.hi,
      scope: selection.scope,
      kind: selection.kind,
      env: selection.env,
      elSel: selection.elSel,
    },
    sg: { on: SUGGEST_DRAFT.on, text: SUGGEST_DRAFT.text, base: SUGGEST_DRAFT.base },
  });
}
/**
 * A successful request may clear its original selection only when every submitted editable field is still unchanged.
 */
function composeOwns(selection: ComposerSelection | null, box: HTMLElement | null, visit: Visit, fields: string) {
  return currentVisit(visit) && COMPOSE.current === selection && COMPOSE.box === box && composeFields() === fields;
}
function setBusy(on: boolean) {
  $('#c-spin').hidden = !on;
  $('#c-body').classList.toggle('busy', on);
}
// Location is one line: 'file L159' + page + match badge + [copy]. Range kind/line count are never repeated: the range
// caption (rangeCap) under it says them, and the ladder's pressed segment. The dragged line goes into the description.
// Selection on a view-only PDF: the location is '쪽 N - 영역', and the region's text (pdftotext) is shown in the source
// field. The range ladder and excerpt are hidden.
function renderRegionComposer(selection: ComposerSelection) {
  $('#composer').classList.add('region');
  // A selection made while cut off (offline/flow.ts offlinePick) has this shape and no file yet: its lines are found
  // when it is sent.
  $('#c-loc').textContent =
    (selection.name ? selection.name + ' · ' : '') + translateTemplate('쪽 {page} 영역', { page: selection.page });
  $('#c-loc').dataset.copy = (selection.name ? selection.name + ' ' : '') + '쪽 ' + selection.page;
  // A figure region: '코드 없는 요소' (element without code lines, its box snapped) or '영역' (map unreadable).
  const pageTag = $('#c-page'),
    regionBadge = figureRegionBadge(selection.el, isFigureKind(META ? META.kind : undefined));
  pageTag.hidden = false;
  pageTag.textContent = selection.offline
    ? translate('오프라인')
    : regionBadge
      ? regionBadge.t
      : translate('보기 전용');
  pageTag.dataset.tip = selection.offline
    ? '연결이 끊긴 채 고른 자리입니다 — 저장하면 쌓아 두었다가, 연결되면 이 PDF로 줄을 찾아 핀으로 씁니다'
    : regionBadge
      ? regionBadge.tip
      : 'LaTeX 소스가 없는 PDF입니다 — 줄 번호 없이 쪽·영역과 영역 글자로 핀을 남깁니다';
  $('#c-tag').hidden = true;
  $('#c-warn').hidden = !selection.warn;
  $('#c-warn').textContent = warnText(selection.warn);
  $('#c-overlap').hidden = true;
  $('#c-levels').replaceChildren();
  setCap($('#c-cap'), html``);
  drawExcerpt(null, $('#c-xp'), false, renderComposer);
  const pre = $('#c-snip');
  pre.className = 'wrap open';
  pre.textContent = selection.quote
    ? translateTemplate('영역 글자: {text}', { text: selection.quote })
    : translate('(이 영역에는 글자가 없습니다)');
  $('#c-expand').hidden = true;
  drawComposerQuote(selection);
  renderElement(selection, COMPOSE.box);
  renderSuggest(selection);
  drawSelectionPopover();
}
// Draws the composer from COMPOSE.current (location, ladder, range excerpt, overlap) and schedules the draft write -
// every change of the selection (a pick, a level, a line set in the excerpt, a restore) passes through here. Its markup
// is in the order the screen shows on every layout (docs/handbook/viewer.md §패널 정리), so Tab follows it.
/**
 * Render and persist the chosen location without enabling a new submission while another create or append is pending.
 */
function renderComposer() {
  const selection = COMPOSE.current;
  if (!selection) return;
  saveDraftSoon();
  syncComposeSaveButtons();
  if (isRegion(selection)) {
    renderRegionComposer(selection);
    return;
  }
  $('#composer').classList.remove('region');
  const copy = selection.name + ' L' + selection.lo + '-L' + selection.hi;
  $('#c-loc').textContent = selection.name + ' ' + lineRange(selection.lo, selection.hi);
  $('#c-loc').dataset.copy = copy;
  renderElement(selection, COMPOSE.box);
  const pageTag = $('#c-page'),
    pageText = typeof selection.page === 'number' ? translateTemplate('{page}쪽', { page: selection.page }) : '',
    scope = scopeLabel(selection);
  pageTag.textContent = pageText;
  pageTag.hidden = !pageText; // a Markdown document's lines have no page: the file and lines say it
  pageTag.dataset.tip =
    pageText +
    (scope ? ' · ' + scope : '') +
    ' · ' +
    translateTemplate('{n}줄', { n: onLines(selection) ? selection.hi - selection.lo + 1 : NaN }) +
    ' · ' +
    translateTemplate('드래그한 줄 {range}', { range: lineRange(selection.raw_lo, selection.raw_hi) });
  const locationTag = viaTag(selection),
    tagElement = $('#c-tag');
  tagElement.hidden = !locationTag;
  if (locationTag) {
    tagElement.textContent = locationTag.t;
    tagElement.dataset.tip = locationTag.tip;
    tagElement.classList.toggle('badge-warning', !!locationTag.low);
  }
  $('#c-warn').hidden = !selection.warn;
  $('#c-warn').textContent = warnText(selection.warn);
  renderOverlapBanner();
  setCap($('#c-cap'), rangeCap(selection, false));
  drawLadder($('#c-levels'), selection, false);
  const pre = $('#c-snip');
  pre.className = 'wrap' + (SNIP_OPEN ? ' open' : '');
  pre.textContent = snipText(selection.snippet, SNIP_OPEN);
  // A collapsed source is cut to 4 lines by CSS. Whether it was cut is measured after rendering (a manuscript where one
  // long line wraps into several is common).
  const over = SNIP_OPEN || pre.scrollHeight > pre.clientHeight + 2,
    lineCount = String(selection.snippet || '').split('\n').length;
  pre.classList.toggle('clip', !SNIP_OPEN && over);
  $('#c-expand').hidden = !over;
  $('#c-expand').textContent = SNIP_OPEN
    ? translate('원문 접기')
    : translate('원문 펼치기') + (lineCount > 1 ? ' · ' + translateTemplate('{n}줄', { n: lineCount }) : '');
  drawExcerpt(selection, $('#c-xp'), false, renderComposer); // the range excerpt (composer/view-excerpt.ts)
  drawComposerQuote(selection);
  renderSuggest(selection); // the [제안 수정] switch and its editor follow the range (composer/flow-suggest.ts)
  drawSelectionPopover(); // the popover by the box shows the same location
  markChosenLines(shownChoice()); // the chosen lines on the Markdown surface (a re-place's candidate while it has one)
}
// ---------------- The PDF text a drag chose (docs/handbook/viewer.md §패널 정리 '드래그한 글자')
// The selection whose quote line is open, or null: a new pick is a new object, so it starts folded, while a range
// change (the same object) keeps it open.
let QUOTE_OPEN_SELECTION: ComposerSelection | null = null;
// What a pick or a pin shows of its quote (the dragged PDF text, whitespace-normalized by the server): the text
// trimmed, or '' for none - no text (a tap or a long press), a region (a view-only PDF or a figure region shows its
// text as the source already) or a line of a figure document (its quote is the element's name, which the location line
// names). A document of an unknown kind is a LaTeX one. Pure.
function shownQuote(
  pickOrPin: { kind?: string; file?: string; pdf?: string; quote?: string } | null,
  docKind: string | undefined,
): string {
  if (!pickOrPin || isRegion(pickOrPin) || isFigureKind(docKind)) return '';
  return String(pickOrPin.quote || '').trim();
}
// The quote line's inside: the icon, a name for screen readers and the text. The line is the manuscript's text and is
// drawn translate="no", so the name is put in the screen's language here (translate); it says where the text was chosen
// - in the PDF, or in a document drawn in the browser (drawnInBrowser: Markdown or text), which has none. A character
// in the text that would hide or reorder it is in its box (markHiddenHtml), and its tooltip names it (markHiddenPlain).
// CSS cuts the text to one line until it is opened.
function quoteInner(quote: string, drawnInBrowser: boolean): Html {
  return html`<span class="q-ic" aria-hidden="true">${lucideIcon('text-quote')}</span><span class="sr-only">${translate(drawnInBrowser ? '문서에서 고른 글자' : 'PDF에서 고른 글자')}: </span><span class="q-t">${markHiddenHtml(quote)}</span>`;
}
// Opens or folds a quote line (the composer's #c-quote or a card's .quote) where it is, without redrawing, so the focus
// stays on it. Open, the whole text is on screen and the tooltip that repeated it goes; folded, it comes back. The
// state is kept for the next draw: the composer's per selection (QUOTE_OPEN_SELECTION), a card's per pin (QUOTE_OPEN).
function toggleQuote(line: HTMLElement) {
  const open = line.getAttribute('aria-expanded') !== 'true',
    text = line.querySelector('.q-t');
  line.classList.toggle('open', open);
  line.setAttribute('aria-expanded', String(open));
  hideTip();
  if (open) delete line.dataset.tip;
  else line.dataset.tip = text ? markHiddenPlain(text.textContent || '') : '';
  if (line.id === 'c-quote') QUOTE_OPEN_SELECTION = open ? COMPOSE.current : null;
  else {
    const key = line.dataset.key || '';
    if (open) QUOTE_OPEN.add(key);
    else QUOTE_OPEN.delete(key);
  }
}
// The composer's quote line, right under the location line: shown for a LaTeX line pick with text, open if it was
// opened for this selection. Nothing, and no gap, otherwise.
function drawComposerQuote(selection: ComposerSelection | null) {
  const line = $('#c-quote'),
    quote = shownQuote(selection, META ? META.kind : undefined);
  line.hidden = !quote;
  if (!quote) {
    line.replaceChildren();
    delete line.dataset.tip;
    return;
  }
  const open = !!selection && QUOTE_OPEN_SELECTION === selection;
  setHtml(line, quoteInner(quote, isMarkdownDoc()));
  line.classList.toggle('open', open);
  line.setAttribute('aria-expanded', String(open));
  if (open) delete line.dataset.tip;
  else line.dataset.tip = markHiddenPlain(quote);
}
// When a selection ends via save/cancel/append, selection mode is turned off (scrolling resumes) and the narrow sheet
// collapses (the body comes forward again). The composer panel's pin kind (fix request / question). Reverts to fix
// request on save or discard (the default for the next pin). The kind says what the note is, not who handles it: the
// assignee does not follow it (composer/input-mentions.ts).
function setKind(kind: string | undefined) {
  const was = KIND_NEW;
  setKindNew(kind === REQUEST_KIND.QUESTION ? REQUEST_KIND.QUESTION : REQUEST_KIND.FIX);
  saveDraftSoon();
  if (KIND_NEW !== was) setComposeIntent(COMPOSE.intent + 1); // a failed verdict save's retry is for the intent it was pressed with
  findAll(document, '#c-kind button', HTMLElement).forEach((button) => {
    const on = button.dataset.kind === KIND_NEW;
    button.classList.toggle('on', on);
    button.setAttribute('aria-checked', String(on));
  });
  roveSegment($('#c-kind')); // the group's one Tab stop is the kind now chosen (platform/segments.ts)
  $('#note').placeholder =
    KIND_NEW === REQUEST_KIND.QUESTION ? '무엇이 궁금한지 적어 주세요' : '메모: 여기를 어떻게 고칠지 (비워도 됩니다)';
  syncQuestionHint($('#c-qhint'), $('#note').value, KIND_NEW);
  composerVerdict().drawRow();
} // a question takes no verdict
// Drops the current selection and its box (clearNote also empties the note, kind and assignee). No undo here -
// discardSelection() is the user's Esc/[취소], which offers one. A sheet's height is drawn again (applySheet): the
// tablet sheet's composing lift ends with the composer, also when an open edit card keeps the sheet open.
function cancelSelection(clearNote: boolean) {
  if (REPICK) cancelRepick();
  closeSelectionPopover();
  markChosenLines(null);
  setComposeCurrent(null);
  setComposeIntent(COMPOSE.intent + 1);
  setPickseq(PICKSEQ + 1);
  setComposePicking(false);
  clearPendingSave();
  if (COMPOSE.box) {
    COMPOSE.box.remove();
    setComposeBox(null);
  }
  saveDraftSoon();
  setComposeDismissedOverlap(null);
  setBusy(false);
  $('#composer').hidden = true;
  if (clearNote) {
    $('#note').value = '';
    $('#note')._mentions = null;
    setAssignNewTouched(false);
    renderAssignNew();
    setKind(REQUEST_KIND.FIX);
    suggestClear();
  }
  if (!REPICK) setSelectMode(false);
  if (LAYOUT === LAYOUT_MODE.NARROW && !EDITOR.current) setSide(false);
  applySide();
  if (LAYOUT === LAYOUT_MODE.NARROW) applySheet();
}
// What a discarded or saved selection needs to come back (restoreSelection): the pick (COMPOSE.current), its box on the
// page, the note with its
// @-tag hints, the kind, the assignee choice and the suggested edit's draft, and the document/build the box belongs to.
// null when there is no selection.
function selectionSnapshot() {
  if (!COMPOSE.current && !COMPOSE.picking && $('#composer').hidden) return null;
  const noteField = $('#note');
  return {
    cur: COMPOSE.current,
    box: COMPOSE.box,
    page: COMPOSE.box && COMPOSE.box.parentNode,
    note: noteField.value,
    mentions: noteField._mentions || null,
    kind: KIND_NEW,
    assign: { v: ASSIGN_NEW.v, touched: ASSIGN_NEW.touched },
    sg: suggestCopy(SUGGEST_DRAFT),
    doc: DOC,
    build: META && META.pages_build,
  };
}
// Brings a snapshot back - the undo of a discard or of a save: the note, kind, assignee and suggested edit always; the
// selection, its box and the composer when they still belong to the pages on screen (same document and build; the box
// if its page is still there). Never over a newer selection - that one wins. When only the note can come back (the PDF
// changed), the status line says so. Returns whether anything came back. focus false: the note field does not take the
// focus (a late undo's answer, composer/flow-save.ts).
function restoreSelection(snapshot: ReturnType<typeof selectionSnapshot>, focus?: boolean) {
  if (!snapshot || COMPOSE.current || COMPOSE.picking || REPICK || !$('#composer').hidden) return false;
  const noteField = $('#note');
  if (noteField.value) return false; // a note-only draft also belongs to the current document
  noteField.value = snapshot.note;
  noteField._mentions = snapshot.mentions;
  setKind(snapshot.kind);
  Object.assign(ASSIGN_NEW, snapshot.assign);
  Object.assign(SUGGEST_DRAFT, suggestCopy(snapshot.sg || suggestDraft()));
  renderAssignNew();
  autoGrow(noteField);
  if (!(snapshot.cur && snapshot.doc === DOC && META && snapshot.build === META.pages_build)) {
    lineNote('메모만 되살렸습니다 — PDF가 바뀌어 자리를 다시 골라야 합니다', NOTICE_KIND.WARN);
    return true;
  }
  if (COMPOSE.box) COMPOSE.box.remove();
  setComposeBox(null);
  if (snapshot.box && snapshot.page && document.contains(snapshot.page)) {
    setComposeBox(snapshot.box);
    snapshot.page.appendChild(snapshot.box);
  }
  setComposeCurrent(snapshot.cur);
  setComposeIntent(COMPOSE.intent + 1);
  recomputeOverlap();
  setSnipOpen(false);
  $('#c-err').hidden = true;
  $('#c-body').hidden = false;
  $('#composer').hidden = false;
  renderComposer();
  setSide(true);
  applySide();
  if (LAYOUT !== LAYOUT_MODE.WIDE) revealBox(COMPOSE.box);
  if (LAST_POINTER === 'mouse' && focus !== false) noteField.focus({ preventScroll: true });
  return true;
}
// Whether the focus has nowhere left to stay: on <body>, or inside the composer or the popover by the box, which have
// just closed (a field hidden under the focus may still report itself focused until the next layout). What a late
// focusPlace checks against: this visit and the composer's intent, read just after the composer closed.
function focusClosed() {
  return { visit: captureVisit(), intent: COMPOSE.intent };
}
// Puts a focus that fell (focusFell) when the composer closed - Esc, [취소], a save, an append - where its work was, so
// the next Tab goes on from there, not from the page's start (<body>, then the sidebar's first control): the pin saved
// or appended to (id) - its badge on the Markdown surface, its mark on a PDF page, where the save chip's [되돌리기] is
// the next Tab - else the place the selection was made at: the line dragged or pressed first on the Markdown surface
// (raw_lo; the pick may have widened to its block), its page on a PDF; else the document area. A place that is no
// control holds the focus while it has it (focusHold). A focus the person has put elsewhere meanwhile stays, and so
// does one in a composer opened since (a save's answer and the pins it reloads come later): with closed - the visit and
// the composer's intent just after the close (focusClosed) - nothing moves unless both are still those, no composer or
// pick is open and no input method's composition is (imeOpen).
function focusPlace(
  selection: ComposerSelection | null | undefined,
  id: number | null,
  closed?: { visit: { doc: string | null; seq: number }; intent: number },
) {
  if (closed && !(currentVisit(closed.visit) && COMPOSE.intent === closed.intent)) return;
  if (COMPOSE.current || COMPOSE.picking || !$('#composer').hidden || imeOpen() || !focusFell()) return;
  const mark = id ? findMaybe(document, '#doc [data-act="mark-jump"][data-id="' + id + '"]', HTMLElement) : null;
  if (mark && mark.getClientRects().length) {
    mark.focus({ preventScroll: true });
    return;
  }
  let at: HTMLElement | null = null;
  if (selection && (selection.doc || DOC) === DOC) {
    if (isMarkdownDoc()) {
      const line = typeof selection.raw_lo === 'number' ? selection.raw_lo : selection.lo;
      if (!isRegion(selection) && typeof line === 'number') at = lineLeaves(line, line)[0] || null;
    } else if (typeof selection.page === 'number') at = document.getElementById('p' + selection.page);
  }
  focusHold(at && at.getClientRects().length ? at : $('#left'));
}
// Esc and [취소] on a selection (docs/handbook/viewer.md §패널 정리): it goes at once, and when its note had text or
// its suggested edit an edited text the status line offers [되돌리기] for NOTICE_MS, which no other press ends (its
// place, the composer, is gone), bringing back the selection, the note, the suggested edit and the box - an undo
// instead of a confirmation. The stored draft stays for that window (a page left meanwhile still restores it) and is
// removed when the offer goes. A focus the closing composer took with it goes to the place the selection stood
// (focusPlace).
function discardSelection() {
  syncDraft();
  const snapshot = selectionSnapshot();
  cancelSelection(true);
  focusPlace(snapshot && snapshot.cur, null);
  if (!(snapshot && snapshot.cur && (snapshot.note.trim() || (snapshot.sg.on && suggestEdited(snapshot.sg))))) {
    syncDraft();
    return;
  }
  const note = lineNote(
    '선택 취소됨',
    NOTICE_KIND.OK,
    { label: '되돌리기', tip: '선택과 메모를 되살립니다', fn: () => restoreSelection(snapshot) },
    { life: NOTICE_LIFE.TIMER, undo: true },
  );
  if (note) holdDraftUntil(note);
} // the kept draft goes when the window does

export {
  composeFields,
  composeOwns,
  setBusy,
  renderComposer,
  quoteInner,
  toggleQuote,
  shownQuote,
  setKind,
  cancelSelection,
  selectionSnapshot,
  restoreSelection,
  focusClosed,
  focusPlace,
  discardSelection,
};
