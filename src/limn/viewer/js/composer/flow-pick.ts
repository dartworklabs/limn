// ------------------------------------------------ composer
// The active selection owns its PDF box, in-flight pick/save, and overlap choice for one composer visit. intent: a
// counter every change to what the composer asks bumps (COMPOSE.intent++) - a new, cleared or restored selection (pick,
// cancelSelection, restoreSelection, restoreDraft), its rung or lines (the 'level' press, applyRange), the kind
// (setKind) and the [제안 수정] switch (suggestAct). retryVerdict: the verdict a failed save carried, the selection it
// was bound to and the intent it was pressed with; the failure's [다시 저장] saves it again only while that intent is
// unchanged (savePin).
import {
  DOC,
  KIND_NEW,
  LAYOUT,
  META,
  MID_OVERLAY,
  PICKSEQ,
  PINS,
  REPICK,
  SNIP_OPEN,
  captureVisit,
  currentVisit,
  isFigureKind,
  setKindNew,
  setPickseq,
  setSnipOpen,
} from '../app/state.ts';
import { html, lucideIcon, setHtml } from '../platform/markup.ts';
import { markHiddenHtml, markHiddenPlain } from '../platform/hidden-chars.ts';
import { errText, translateTemplate, translate, warnText, josa } from '../platform/i18n.ts';
import { API_OUT, API_WAIT, api } from '../platform/api.ts';
import { endTopic, lineNote } from '../platform/notices.ts';
import { hideTip, LAST_POINTER } from '../platform/tooltip.ts';
import { applySheet } from '../layout/flow-panel-size.ts';
import { applySide, relayout, setSelectMode, setSide } from '../layout/flow.ts';
import { revealBox } from '../pdf/input-selection.ts';
import { drawLadder, rangeCap, scopeLabel, setCap, snipText, viaTag } from './view-levels.ts';
import { drawExcerpt } from './view-excerpt.ts';
import { figureRegionBadge, renderElement } from '../pdf/view-figure.ts';
import { lineLeaves, markChosenLines, shownChoice } from '../markdown/view.ts';
import {
  SUGGEST_DRAFT,
  renderSuggest,
  suggestClear,
  suggestCopy,
  suggestDraft,
  suggestEdited,
  suggestPending,
} from './flow-suggest.ts';
import { holdDraftUntil, saveDraftSoon, syncDraft } from './flow-draft.ts';
import { clearPendingSave, savePin, syncComposeSaveButtons } from './flow-save.ts';
import { offlinePick } from '../offline/flow.ts';
import { renderVerdictRow } from '../verdict/flow-line.ts';
import {
  SELECTION_POPOVER_FIELD,
  closeSelectionPopover,
  drawSelectionPopover,
  isSelectionPopoverOpen,
} from './view-selection-popover.ts';
import { QUOTE_OPEN } from '../pins/view-card-parts.ts';
import { loadPins } from '../pins/flow-list.ts';
import { ASSIGN_NEW, renderAssignNew } from '../pins/input-mentions.ts';
import { autoGrow, EDITOR } from '../pins/flow-edit.ts';
import { banner, bannerCompare, bannerRepick, cancelRepick } from './flow-repick.ts';
import { refreshDoc } from '../documents/flow-rebuild.ts';
import type { Html } from '../platform/markup.ts';
import { NOTICE_KIND, NOTICE_LIFE, NOTICE_TOPIC } from '../platform/tables.ts';
import { $, $$, focusFell, focusHold } from '../platform/dom.ts';
import { roveSegment } from '../platform/segments.ts';
import { REQUEST_KIND, LAYOUT_MODE, RANGE_REL } from '../app/rules-tables.ts';
import { lineRange, overlapsFor } from '../app/rules-pins.ts';
import { isMarkdownDoc, isRegion } from '../documents/state.ts';
import { offlineNow } from '../documents/flow-polling.ts';
import { useLevel } from '../documents/rules.ts';
import { imeOpen } from '../platform/composition.ts';
const COMPOSE = {
  current: null as Selection | null,
  box: null as HTMLElement | null,
  picking: false,
  pendingSave: false,
  saving: false,
  dismissedOverlap: null as string | null,
  intent: 0,
  retryVerdict: null as { key: string; sel: Selection; gen: number } | null,
};

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
function composeOwns(selection, box, visit, fields) {
  return currentVisit(visit) && COMPOSE.current === selection && COMPOSE.box === box && composeFields() === fields;
}
function setBusy(on) {
  $('#c-spin').hidden = !on;
  $('#c-body').classList.toggle('busy', on);
}
// Turns a dragged PDF region into source lines (/api/pick) and fills the composer - or, while relocating, the banner. A
// new selection opens a collapsed panel; stale responses (PICKSEQ) are dropped; a save queued meanwhile runs after it.
// The first-visit hint on how to pick goes (endTopic): it has been done.
async function pick(region) {
  const seq = setPickseq(PICKSEQ + 1),
    repick = REPICK;
  endTopic(NOTICE_TOPIC.PICK); // the first-visit hint on how to pick has been done
  // When a new selection (not a re-place) starts, the previous COMPOSE.current is cleared at once, so a [핀 저장] while
  // the pick runs never saves the stale COMPOSE.current - the old place - and instead goes through the
  // COMPOSE.pendingSave queue (docs/handbook/viewer.md §패널 정리) to save the place just chosen.
  if (repick) {
    banner(html`<span>되짚는 중…</span>`);
  } else {
    COMPOSE.current = null;
    COMPOSE.intent++;
    $('#composer').hidden = false;
    setBusy(true);
    COMPOSE.picking = true;
    $('#c-err').hidden = true;
    $('#c-body').hidden = false;
    // a second pick over a selection: its verdict buttons go off, with the reason, until the place is found
    renderVerdictRow();
    setSide(true);
    applySide(); // a collapsed panel opens for a new selection in every layout (wide included)
    // composing in the overlay pads the PDF by the panel width (CSS): re-fit now, then reveal the box
    if (MID_OVERLAY) relayout();
    if (LAYOUT !== LAYOUT_MODE.WIDE) {
      $('#right').scrollTop = 0;
      revealBox(COMPOSE.box);
    }
  }
  let answer;
  // A new selection the server cannot be reached for is not a failure: offlinePick opens the composer on it and says
  // what happens next, so the call does not say '위치 찾기 실패' over that. A re-place and a Markdown or text
  // document have no such way on, and say it.
  // While the connection is known to be gone, or the last request to end got no answer (API_OUT - the poll has not
  // counted its two failures yet), the server is not asked at all: each drag would wait out a request that cannot be
  // answered before its composer opened. And a request that is asked waits no longer than API_WAIT.PICK.
  try {
    if (!repick && !isMarkdownDoc() && (offlineNow() || API_OUT)) throw new Error('cut off');
    answer = (
      await api('/api/pick', {
        method: 'POST',
        body: region,
        what: '위치 찾기',
        quietUnreached: !repick && !isMarkdownDoc(),
        wait: API_WAIT.PICK,
      })
    ).data;
  } catch (error) {
    if (seq !== PICKSEQ) return;
    setBusy(false);
    if (!repick) {
      COMPOSE.picking = false;
      clearPendingSave();
    }
    // The server could not be reached (a refusal carries a status): the drag is not lost. Its box stays and the
    // composer opens on a selection with no lines, which [핀 저장] keeps in the queue until the connection is back
    // (offline/flow.ts).
    const failure = error as ApiError;
    if (!repick && !(failure && failure.status) && !isMarkdownDoc()) {
      void offlinePick(region);
      return;
    }
    if (repick) {
      bannerRepick();
    } else {
      if (COMPOSE.box) {
        COMPOSE.box.remove();
        COMPOSE.box = null;
      }
      if (!COMPOSE.current) {
        $('#composer').hidden = true;
        applySide();
      }
      drawSelectionPopover();
    }
    return;
  }
  if (seq !== PICKSEQ) return;
  setBusy(false);
  if (!repick) COMPOSE.picking = false;
  if (answer.error) {
    if (answer.pdf_build_gone) {
      try {
        await refreshDoc();
      } catch (error) {}
      if (seq !== PICKSEQ) return;
      if (repick && repick.box) {
        repick.box.remove();
        repick.box = null;
      } else if (!repick && COMPOSE.box) {
        COMPOSE.box.remove();
        COMPOSE.box = null;
      }
    }
    if (repick) {
      bannerRepick(errText(answer));
      return;
    }
    // A failed pick never carries out a pending save - only the error panel is shown, so a save never fails silently.
    COMPOSE.current = null;
    COMPOSE.intent++;
    clearPendingSave();
    $('#c-err').textContent = errText(answer);
    $('#c-err').hidden = false;
    $('#c-body').hidden = true;
    drawSelectionPopover();
    return;
  }
  if (repick) {
    repick.cand = answer;
    bannerCompare();
    return;
  }
  const selection = answer as Selection;
  COMPOSE.current = selection;
  COMPOSE.intent++;
  selection.scope = null;
  selection.elSel = answer.el || null;
  if (!isRegion(answer)) {
    useLevel(selection, answer.default_level);
    if (!selection.scope) {
      selection.lo = answer.lo;
      selection.hi = answer.hi;
    }
  }
  // a freshly chosen selection - re-notified even if [별도 핀으로 저장] was pressed for a previous selection
  COMPOSE.dismissedOverlap = null;
  selection.overlaps = overlapsFor(selection, PINS);
  // If a pin the server saw as overlapping isn't in this tab's PINS (someone else just saved it), the list is
  // re-fetched - loadPins recomputes overlap too.
  if ((answer.overlaps || []).some((overlap) => !PINS.some((pin) => pin.id === overlap.id))) loadPins();
  setSnipOpen(false);
  $('#c-err').hidden = true;
  $('#c-body').hidden = false;
  renderComposer();
  // so a second drag's new location/ladder never hides above the scroll (the note stays as-is)
  $('#composer').scrollTop = 0;
  if (LAYOUT !== LAYOUT_MODE.WIDE) $('#right').scrollTop = 0;
  // Drag -> straight into the note field - the popover's by the box while it is open
  // (composer/view-selection-popover.ts), else the composer's. Never focused on touch - the virtual keyboard would pop
  // up immediately and cover the range ladder and page.
  if (LAST_POINTER === 'mouse')
    (isSelectionPopoverOpen() ? SELECTION_POPOVER_FIELD : $('#note')).focus({ preventScroll: true });
  // If [핀 저장] was pressed while the pick was still running, the queued save runs here (COMPOSE.current has just been
  // filled in).
  if (COMPOSE.pendingSave) {
    clearPendingSave();
    savePin();
  }
}
// One representative: same range > inside (the narrowest enclosing pin) > contains (the widest inner pin) > overlap
// (the smallest id).
function pickOverlap(overlaps) {
  if (!overlaps || !overlaps.length) return null;
  const equal = overlaps.filter((overlap) => overlap.rel === RANGE_REL.EQUAL);
  if (equal.length) return equal.reduce((best, candidate) => (candidate.id < best.id ? candidate : best));
  const insides = overlaps.filter((overlap) => overlap.rel === RANGE_REL.INSIDE);
  if (insides.length)
    return insides.reduce((best, candidate) => (candidate.hi - candidate.lo < best.hi - best.lo ? candidate : best));
  const contains = overlaps.filter((overlap) => overlap.rel === RANGE_REL.CONTAINS);
  if (contains.length)
    return contains.reduce((best, candidate) => (candidate.hi - candidate.lo > best.hi - best.lo ? candidate : best));
  const partials = overlaps.filter((overlap) => overlap.rel === RANGE_REL.PARTIAL);
  if (partials.length) return partials.reduce((best, candidate) => (candidate.id < best.id ? candidate : best));
  return null;
}
// Overlap-banner wording: what relationship the selection has to that pin - '#4와 같은 범위' - '#4 범위 안' - '#4를
// 감쌈' - '#4와 일부 겹침'. The whole banner sentence in the UI language: '열린 핀 #4와 같은 범위입니다' / 'Same range
// as open pin #4'.
function overlapText(rel, id) {
  const template =
    {
      equal: '열린 핀 #{id}{p} 같은 범위입니다',
      inside: '열린 핀 #{id} 범위 안입니다',
      contains: '열린 핀 #{id}{p} 감쌉니다',
      partial: '열린 핀 #{id}{p} 일부 겹칩니다',
    }[rel] || '열린 핀 #{id}{p} 겹칩니다';
  return translateTemplate(template, {
    id,
    p: rel === RANGE_REL.CONTAINS ? josa(id, '을', '를') : josa(id, '과', '와'),
  });
}
// [별도 핀으로 저장] turns off "that relationship with that pin" (id:rel). Re-announced if changing the range changes
// the relationship, and reset on a fresh drag (pick), so one press never silences it for every later selection.

function recomputeOverlap() {
  if (COMPOSE.current) COMPOSE.current.overlaps = overlapsFor(COMPOSE.current, PINS);
}
// The open pin the composer's note may join instead of becoming a pin: the overlap its notice offers [덧붙이기] for -
// or null without one, and once the author chose [따로 저장] for it.
function appendTarget(): { id: number; lo: number; hi: number; rel: string } | null {
  const selection = COMPOSE.current,
    overlap = selection ? pickOverlap(selection.overlaps) : null;
  return overlap && COMPOSE.dismissedOverlap !== overlap.id + ':' + overlap.rel ? overlap : null;
}
// Draws the overlap notice for the current selection, or hides it. On the phone sheet it is one line (three lines would
// take too much room above the note): the short relation ('#4와 같은 범위', the full sentence and the lines in its
// tooltip) and the two actions with short names; elsewhere the sentence with the lines and the two full-named buttons.
/** Render the current overlap choice; its append control shares the composer's in-flight submission lock. The assignee
 *  row and the preview line follow it (renderAssignNew): while an append is on offer they say what it does. */
function renderOverlapBanner() {
  const box = $('#c-overlap'),
    overlap = appendTarget();
  if (!overlap) {
    box.hidden = true;
    renderAssignNew();
    return;
  }
  box.hidden = false;
  box.dataset.rel = overlap.rel;
  const one = LAYOUT === LAYOUT_MODE.NARROW,
    full = overlapText(overlap.rel, overlap.id) + ' (L' + overlap.lo + '-L' + overlap.hi + ')';
  box.classList.toggle('one', one);
  const text = one
    ? html`<span class="ov-t" data-tip="${full}">${overlapShort(overlap.rel, overlap.id)}</span>`
    : html`<span>${overlapText(overlap.rel, overlap.id)} <span class="dim">(L${overlap.lo}-L${overlap.hi})</span></span>`;
  // A suggested edit belongs to this selection's lines and is saved with a new pin only: while one is written,
  // [덧붙이기] waits.
  const isSuggesting = suggestPending(),
    appendTip = isSuggesting
      ? translate('제안 수정은 새 핀으로만 저장합니다 — 덧붙이려면 제안 수정을 끄세요')
      : translateTemplate('이 선택의 메모를 #{id} 에 덧붙이고, 지금 선택은 새 핀으로 만들지 않습니다', {
          id: overlap.id,
        });
  setHtml(
    box,
    html`${text}\
<button class="btn-sm btn-secondary hit" data-act="overlap-append" data-oid="${overlap.id}" data-tip="${appendTip}"${COMPOSE.saving || isSuggesting ? html` disabled` : ''}>${one ? translate('덧붙이기') : translateTemplate('#{id} 메모에 덧붙이기', { id: overlap.id })}</button>\
<button class="btn-sm btn-secondary hit" data-act="overlap-separate" data-key="${overlap.id + ':' + overlap.rel}" data-tip="겹쳐도 별도 핀으로 저장합니다">${one ? translate('따로 저장') : '별도 핀으로 저장'}</button>`,
  );
  renderAssignNew();
}
// The overlap in a few words for the one-line notice: '#4와 같은 범위' - '#4 범위 안' - '#4를 감쌈' - '#4와 일부 겹침'
// (the card badges' wording).
function overlapShort(rel, id) {
  const template =
    { equal: '#{id}{p} 같은 범위', inside: '#{id} 범위 안', contains: '#{id}{p} 감쌈', partial: '#{id}{p} 일부 겹침' }[
      rel
    ] || '#{id}{p} 일부 겹침';
  return translateTemplate(template, {
    id,
    p: rel === RANGE_REL.CONTAINS ? josa(id, '을', '를') : josa(id, '과', '와'),
  });
}
// Location is one line: 'file L159' + page + match badge + [copy]. Range kind/line count are never repeated: the range
// caption (rangeCap) under it says them, and the ladder's pressed segment. The dragged line goes into the description.
// Selection on a view-only PDF: the location is '쪽 N - 영역', and the region's text (pdftotext) is shown in the source
// field. The range ladder and excerpt are hidden.
function renderRegionComposer(selection) {
  $('#composer').classList.add('region');
  // A selection made while cut off (offline/flow.ts offlinePick) has this shape and no file yet: its lines are found
  // when it is sent.
  $('#c-loc').textContent =
    (selection.name ? selection.name + ' · ' : '') + translateTemplate('쪽 {page} 영역', { page: selection.page });
  $('#c-loc').dataset.copy = (selection.name ? selection.name + ' ' : '') + '쪽 ' + selection.page;
  // A figure region: '코드 없는 요소' (element without code lines, its box snapped) or '영역' (map unreadable).
  const pageTag = $('#c-page'),
    regionBadge = figureRegionBadge(selection.el, isFigureKind(META && META.kind));
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
  drawExcerpt(null, $('#c-xp'), false);
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
    translateTemplate('{n}줄', { n: (selection.hi as number) - (selection.lo as number) + 1 }) +
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
  drawExcerpt(selection, $('#c-xp'), false); // the range excerpt (composer/view-excerpt.ts)
  drawComposerQuote(selection);
  renderSuggest(selection); // the [제안 수정] switch and its editor follow the range (composer/flow-suggest.ts)
  drawSelectionPopover(); // the popover by the box shows the same location
  markChosenLines(shownChoice()); // the chosen lines on the Markdown surface (a re-place's candidate while it has one)
}
// ---------------- The PDF text a drag chose (docs/handbook/viewer.md §패널 정리 '드래그한 글자')
// The selection whose quote line is open, or null: a new pick is a new object, so it starts folded, while a range
// change (the same object) keeps it open.
let QUOTE_OPEN_SELECTION = null as Selection | null;
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
function drawComposerQuote(selection: Selection | null) {
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
// assignee does not follow it (pins/input-mentions.ts).
function setKind(kind) {
  const was = KIND_NEW;
  setKindNew(kind === REQUEST_KIND.QUESTION ? REQUEST_KIND.QUESTION : REQUEST_KIND.FIX);
  saveDraftSoon();
  if (KIND_NEW !== was) COMPOSE.intent++; // a failed verdict save's retry is for the intent it was pressed with
  $$('#c-kind button').forEach((button) => {
    const on = button.dataset.kind === KIND_NEW;
    button.classList.toggle('on', on);
    button.setAttribute('aria-checked', String(on));
  });
  roveSegment($('#c-kind')); // the group's one Tab stop is the kind now chosen (platform/segments.ts)
  $('#note').placeholder =
    KIND_NEW === REQUEST_KIND.QUESTION ? '무엇이 궁금한지 적어 주세요' : '메모: 여기를 어떻게 고칠지 (비워도 됩니다)';
  syncQuestionHint($('#c-qhint'), $('#note').value, KIND_NEW);
  renderVerdictRow();
} // a question takes no verdict
// A note that reads like a question (docs/handbook/viewer.md §스레드와 검토 - suggesting the kind). True if it ends in
// ?/? or a Korean interrogative ending (는가/나요/까요/인가/건가/니/냐/까). A trailing period/ellipsis/closing
// bracket/quote and a trailing @-tag (e.g. '맞나요? @Bob Park') are ignored. Only judges - never changes the kind
// itself.
function looksQuestion(text) {
  let trimmed = String(text || '').trim();
  for (let i = 0; i < 3; i++)
    trimmed = trimmed
      .replace(/[\s.…~!。)\]"'”’]+$/, '')
      .replace(/(?:\s*@[^\s@?？]+(?:\s+[A-Za-z][A-Za-z.'-]*)?)+$/, '');
  return /[?？]$/.test(trimmed) || /(는가|나요|까요|인가|건가|니|냐|까)$/.test(trimmed);
}
// If it's a fix request but the note reads like a question, a one-line suggestion appears next to the kind control. It
// never changes the kind itself - only a click does. It goes once the kind is a question or the text does not read like
// one.
function syncQuestionHint(box, text, kind) {
  if (box) box.hidden = kind === REQUEST_KIND.QUESTION || !looksQuestion(text);
}
// Drops the current selection and its box (clearNote also empties the note, kind and assignee). No undo here -
// discardSelection() is the user's Esc/[취소], which offers one. A sheet's height is drawn again (applySheet): the
// tablet sheet's composing lift ends with the composer, also when an open edit card keeps the sheet open.
function cancelSelection(clearNote) {
  if (REPICK) cancelRepick();
  closeSelectionPopover();
  markChosenLines(null);
  COMPOSE.current = null;
  COMPOSE.intent++;
  setPickseq(PICKSEQ + 1);
  COMPOSE.picking = false;
  clearPendingSave();
  if (COMPOSE.box) {
    COMPOSE.box.remove();
    COMPOSE.box = null;
  }
  saveDraftSoon();
  COMPOSE.dismissedOverlap = null;
  setBusy(false);
  $('#composer').hidden = true;
  if (clearNote) {
    $('#note').value = '';
    $('#note')._mentions = null;
    ASSIGN_NEW.touched = false;
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
function restoreSelection(snapshot, focus?: boolean) {
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
  COMPOSE.box = null;
  if (snapshot.box && snapshot.page && document.contains(snapshot.page)) {
    COMPOSE.box = snapshot.box;
    snapshot.page.appendChild(snapshot.box);
  }
  COMPOSE.current = snapshot.cur;
  COMPOSE.intent++;
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
  selection: Selection | null | undefined,
  id: number | null,
  closed?: { visit: { doc: string | null; seq: number }; intent: number },
) {
  if (closed && !(currentVisit(closed.visit) && COMPOSE.intent === closed.intent)) return;
  if (COMPOSE.current || COMPOSE.picking || !$('#composer').hidden || imeOpen() || !focusFell()) return;
  const mark = (
    id ? document.querySelector('#doc [data-act="mark-jump"][data-id="' + id + '"]') : null
  ) as HTMLElement | null;
  if (mark && mark.getClientRects().length) {
    mark.focus({ preventScroll: true });
    return;
  }
  let at = null as HTMLElement | null;
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
  appendTarget,
  cancelSelection,
  composeFields,
  composeOwns,
  discardSelection,
  focusClosed,
  focusPlace,
  pick,
  syncQuestionHint,
  quoteInner,
  recomputeOverlap,
  renderComposer,
  renderOverlapBanner,
  restoreSelection,
  selectionSnapshot,
  setBusy,
  setKind,
  shownQuote,
  toggleQuote,
  COMPOSE,
};
