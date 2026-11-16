// ----------------------------------- Pin list: loading pins, list sections, marks on the PDF, jumping to a pin or card
// If the people list changes (a new person/name), the list is redrawn - the very first render can show a login instead
// of a name - and so is the composer's assignee row: a draft restored at boot is read before the list arrives, when
// none of its tags resolves yet.
import {
  DEFAULT_DOC,
  DOC,
  DOCS,
  DONE,
  DONE_ALL,
  DROPPED,
  LAYOUT,
  MENTION_ONLY,
  OPEN_ALL,
  OPEN_CARDS,
  PEOPLE,
  PEOPLE_KNOWN,
  PINS,
  REPLY,
  REVIEW_ALL,
  SHOW_ALL,
  SIDE_OPEN,
  SWITCHSEQ,
  scrollMotion,
  setDone,
  setDoneAll,
  setDropped,
  setMentionOnly,
  setOpenAll,
  setPeople,
  setPeopleKnown,
  setPins,
  setReviewAll,
  setShowAll,
  COMPOSE,
  EDITOR,
  setEditorCurrent,
} from '../app/state.ts';
import { html, lucideIcon, setHtml } from '../platform/markup.ts';
import { translateTemplate, translate } from '../platform/i18n.ts';
import {
  ORDER,
  SECTION_OPEN,
  SECTION_OPEN_DEFAULT,
  SECTION_SEEN,
  listOrderOf,
  savePrefs,
  countNewInSection,
  setOrder,
} from '../platform/prefs.ts';
import { api } from '../platform/api.ts';
import {
  NOTICES,
  drawBanners,
  drawChips,
  drawOffers,
  dropStaleReview,
  lineNote,
  noticeFocus,
  noticeSeen,
  offersIn,
} from '../platform/notices.ts';
import { TIP_AT, hideTip, keyInput, armedTipElement, MARK_HIDDEN } from '../platform/tooltip.ts';
import { drawDocTabs, multiDoc } from '../documents/view-tabs.ts';
import { REVISION_VIEW, findAnyPin, drawPinGuideActions, setViewMode } from '../revisions/flow.ts';
import { docTitle, switchDoc, viaDoc } from '../documents/flow-switch.ts';
import { noteNewPins } from '../documents/flow-updates.ts';
import { arrivePage, pageNoSides } from '../pdf/view-pages.ts';
import { applySide, setSide } from '../layout/flow.ts';
import { pendingBadgeSide } from '../pdf/input-selection.ts';
import { isElementLost, hasMark, isFrac, pinPlace } from '../pdf/view-figure.ts';
import { jumpToPinLines, drawPinMarks } from '../markdown/view.ts';
import { recomputeOverlap, renderOverlapBanner } from '../composer/flow-pick.ts';
import { drawPageVerdicts, jumpToPageLine, isShownOnLine } from '../verdict/flow-line.ts';
import { mentionsMe } from './view-card-parts.ts';
import { card, dayName, doneCard, drawTrash, openTrash, timeParts } from './view-cards.ts';
import { drawReviewPick } from './flow-review-pick.ts';
import { marksShow } from './input-hide-marks.ts';
import { CONFIRMING, CONFIRMING_PIN, PURGING } from './flow-actions.ts';
import { renderAssignNew } from '../composer/input-mentions.ts';
import { closeReply, renderReplyOutcome, replyNote } from './flow-reply.ts';
import { editDirty, renderEdit } from './flow-edit.ts';
import type { Html } from '../platform/markup.ts';
import { LIST_ORDER, NOTICE_DOT, NOTICE_HOST, NOTICE_KIND, NOTICE_PLACE } from '../platform/tables.ts';
import { $, $$ } from '../platform/dom.ts';
import { roveSegment } from '../platform/segments.ts';
import { LAYOUT_MODE, PIN_STATE, VIEW_MODE } from '../app/rules-tables.ts';
import { pinState } from '../app/rules-pins.ts';
import { who, isMe } from '../app/state-people.ts';
import { isMarkdownDoc, docInfo, pdoc } from '../documents/state.ts';
import { notePinChanges, noteReviewChanges } from './flow-changes.ts';
import { endJumpForScroll } from '../layout/flow-scroll.ts';
import { markBadgeRoom, markBadgeIn, markHitSides } from '../pdf/view-badges.ts';

async function loadPeople() {
  try {
    const answer = (await api('/api/people', { what: '사람 목록', silent: true })).data;
    if (Array.isArray(answer.people)) {
      const was = JSON.stringify(PEOPLE),
        first = !PEOPLE_KNOWN;
      setPeople(answer.people);
      setPeopleKnown(true);
      const changed = JSON.stringify(PEOPLE) !== was;
      if (changed) drawPins();
      if (changed || first) renderAssignNew();
    }
  } catch (error) {}
}
// A refresh that started earlier must not replace one already applied from a newer request. A failed request claims no
// snapshot.
let PINS_LOAD_SEQ = 0,
  PINS_APPLIED_SEQ = 0;
// Classifies one server snapshot without reading viewer state or changing the page. Legacy pins with no doc belong to
// defaultDoc. confirming (optional) holds the ids whose [확인] waits for its undo (CONFIRMING): they stay out of the
// review list.
function derivePinLists(rows: Pin[], doc, defaultDoc, confirming) {
  const openAll: Pin[] = [],
    reviewAll: Pin[] = [],
    doneAll: Pin[] = [],
    openHere: Pin[] = [],
    doneHere: Pin[] = [];
  for (const pin of rows) {
    const state = pinState(pin),
      here = !doc || (pin.doc || defaultDoc) === doc;
    if (state === PIN_STATE.OPEN) {
      openAll.push(pin);
      if (here) openHere.push(pin);
    } else if (state === PIN_STATE.REVIEW) {
      if (!(confirming && confirming.has(pin.id))) reviewAll.push(pin);
    } else if (state === PIN_STATE.DONE) {
      doneAll.push(pin);
      if (here) doneHere.push(pin);
    }
  }
  return { openAll, reviewAll, doneAll, openHere, doneHere };
}
// Applies an accepted snapshot: announces transitions on the status line, keeps active editors honest (an edit or reply
// whose pin left says so there too, with a dot on [핀 N]), then redraws the current document.
/**
 * Apply a fresh snapshot while retaining dirty or saving editors whose pin is still present, including a rival close.
 */
function applyPinLists(rows, dropped, lists) {
  const openBefore = OPEN_ALL,
    reviewBefore = REVIEW_ALL;
  notePinChanges(openBefore, rows, dropped);
  noteReviewChanges(reviewBefore, rows);
  noteNewPins(rows); // others' new pins (documents/flow-updates.ts)
  setOpenAll(lists.openAll);
  setReviewAll(lists.reviewAll);
  setDoneAll(lists.doneAll);
  setDropped(dropped);
  setPins(lists.openHere);
  setDone(lists.doneHere);
  // A pin whose [확인] waits for its undo stays in the verdict order (verdictOrder) as this snapshot has it - still
  // awaiting review - and leaves it once the snapshot does not have it so (deleted from another window, reopened,
  // confirmed elsewhere).
  CONFIRMING_PIN.forEach((_, id) => {
    const fresh = rows.find((row) => row.id === id);
    if (fresh && pinState(fresh) === PIN_STATE.REVIEW) CONFIRMING_PIN.set(id, fresh);
    else CONFIRMING_PIN.delete(id);
  });
  const card = EDITOR.current;
  if (card && !OPEN_ALL.some((pin) => pin.id === card.id)) {
    if (rows.some((pin) => pin.id === card.id) && (EDITOR.saving || editDirty())) SECTION_OPEN.open = true;
    else {
      lineNote(
        translateTemplate('편집 중이던 핀 #{id} 이 목록에서 빠졌습니다(다른 쪽에서 닫았거나 지움)', { id: card.id }),
        NOTICE_KIND.WARN,
        null,
        { dot: NOTICE_DOT.SIDE },
      );
      setEditorCurrent(null);
    }
  }
  const replyBox = REPLY;
  if (replyBox && !rows.some((pin) => pin.id === replyBox.id)) {
    closeReply(false);
    lineNote('답글을 쓰던 핀이 목록에서 빠졌습니다(지워짐) — 쓰던 글은 남겨 둡니다', NOTICE_KIND.WARN, null, {
      dot: NOTICE_DOT.SIDE,
    });
  }
  if (!SECTION_SEEN.open) {
    SECTION_SEEN.open = new Set(OPEN_ALL.map((pin) => pin.id));
    SECTION_SEEN.review = new Set(REVIEW_ALL.map((pin) => pin.id));
    SECTION_SEEN.done = new Set(DONE_ALL.map((pin) => pin.id));
  }
  drawPins();
  marks();
  drawDocTabs();
  if (COMPOSE.current) {
    recomputeOverlap();
    renderOverlapBanner();
  } // if the list changes (someone else's save/completion), overlap is recomputed too
  docTitle(true);
}
// Fetches one pin snapshot and its Trash. Returns whether it applied; only a newer applied snapshot supersedes it: a
// read another one started later overtook (a light poll's, an action's) returns false and draws nothing, and the list
// stays as the newer one drew it. A failed read is a banner on top of the panel with [다시 시도].
async function loadPins() {
  const seq = ++PINS_LOAD_SEQ;
  let rows;
  try {
    rows = (
      await api('/api/pins?all=1', {
        what: '핀 읽기',
        where: NOTICE_HOST.LIST,
        retry: () => {
          loadPins();
        },
      })
    ).data;
  } catch (error) {
    return false;
  }
  if (seq < PINS_APPLIED_SEQ) return false;
  let dropped = [];
  // Said, not silent: this read failing stops the whole snapshot from being applied, and a refresh that stops
  // without a word looks like a list that simply did not change (docs/handbook/viewer.md §알림 자리).
  try {
    dropped =
      (
        await api('/api/pins/dropped', {
          what: '삭제한 핀',
          where: NOTICE_HOST.LIST,
          retry: () => {
            loadPins();
          },
        })
      ).data.dropped || [];
  } catch (error) {
    return false;
  }
  if (seq < PINS_APPLIED_SEQ) return false;
  loadPeople();
  // All-document lists drive notices; only the current document's open and done pins drive its marks and rows.
  // before the redraw it makes: a page verdict line stops reading '판정 읽는 중…' with this list (pageLineHtml)
  PINS_APPLIED_SEQ = seq;
  applyPinLists(rows, dropped, derivePinLists(rows, DOC, DEFAULT_DOC, CONFIRMING));
  return true;
}
// Reads the list again for a caller that goes on to act on it as it stands (a pin link opening its card). Resolves true
// when the list now shows a snapshot asked for by this call or a later one - its own read applied, or a newer read that
// overtook it did - and false only when none since the call has applied (the read failed and said so). loadPins' own
// answer is false when overtaken, the light poll's cue to read that revision again (docs/handbook/build-sync.md §자동
// 동기화 (가벼운 meta 폴링)), so a caller that waits for the list itself reads it with this.
async function loadPinsNow(): Promise<boolean> {
  const since = PINS_LOAD_SEQ;
  await loadPins();
  return PINS_APPLIED_SEQ > since;
}
// The list drawn in the sidebar: the current document by default, everything if 'all documents'. A pin being edited is
// kept even from another document (so the draft text doesn't disappear).
function listOpen() {
  return SHOW_ALL && multiDoc()
    ? OPEN_ALL
    : OPEN_ALL.filter((pin) => pdoc(pin) === DOC || !DOC || (EDITOR.current && EDITOR.current.id === pin.id));
}
function listDone() {
  return SHOW_ALL && multiDoc() ? DONE_ALL : DONE;
}
function listReview() {
  return SHOW_ALL && multiDoc() ? REVIEW_ALL : REVIEW_ALL.filter((pin) => pdoc(pin) === DOC || !DOC);
}
// Awaiting-review count: counted across documents (the inbox of work for a person to confirm). The purple number next
// to [핀 N] (compact) / the tool bar chip (wide). [⬚ 선택] keeps the width of its pressed face [⬚ 선택 중] wherever it
// shows its label (docs/handbook/viewer.md §모바일 레이아웃 선택 모드), so pressing it moves neither it nor its
// neighbours - on the landscape phone's top row a wider face would move the button itself under the finger. Effect:
// --sel-w on the button, measured with the pressed face drawn for a moment (in the interface language), or removed
// where the label is hidden (the portrait phone's 36px icon, a stepped-down sheet bar).
function holdSelectWidth() {
  const button = $('#btn-select'),
    label = button.querySelector('.lbl') as HTMLElement;
  button.style.removeProperty('--sel-w');
  if (!button.getClientRects().length || getComputedStyle(label).display === 'none') return;
  const pressed = button.getAttribute('aria-pressed') || 'false',
    text = label.textContent;
  button.setAttribute('aria-pressed', 'true');
  label.textContent = translate('선택 중');
  const width = button.getBoundingClientRect().width;
  button.setAttribute('aria-pressed', pressed);
  label.textContent = text;
  button.style.setProperty('--sel-w', Math.ceil(width) + 'px');
}
// The phone and tablet sheet bar's left cell steps down until [핀 N | 검토 M] and [⬚] fit it (English, three-digit
// counts, a folded cover): first [⬚ 선택] drops its label for the 36px icon the phone has (#bar1.bar-sel-icon) - the
// chip never shrinks for it; then the chip's halves pad one 4px step less and the cell's gap is 4px (#bar1.bar-snug);
// then the words '핀' and '검토' give way to a dot each - green for the open pins, purple for those awaiting review
// (#bar1.bar-tight) - so a count never stands alone. Measured each time a count or the band changes, after [⬚ 선택] has
// its width (holdSelectWidth, every band); decoration only - nothing moves.
function fitBarWords() {
  const bar = $('#bar1'),
    leftCell = bar.querySelector('.bar-l');
  bar.classList.remove('bar-sel-icon', 'bar-snug', 'bar-tight');
  holdSelectWidth();
  if (LAYOUT !== LAYOUT_MODE.NARROW) return;
  const over = () => {
    // the last control's edge, not scrollWidth: the hits overflow too
    const shown = [...leftCell.children].filter((child) => child.getClientRects().length);
    return (
      shown.length > 0 &&
      shown[shown.length - 1].getBoundingClientRect().right > leftCell.getBoundingClientRect().right + 0.05
    );
  }; // past the cell, [⬚]'s hit reaches the grabber's column
  for (const step of ['bar-sel-icon', 'bar-snug', 'bar-tight']) {
    if (!over()) return;
    bar.classList.add(step);
    if (step === 'bar-sel-icon') holdSelectWidth();
  }
}
// The pill rides on both [핀 N] toggles (the tool bar's and the collapsed wide nav bar's); the phone and tablet sheet's
// bar shows the count as its own half [검토 M] (#btn-rv) instead; the chip is the open wide panel's. The pill is the
// eye icon and the count, so it never reads as part of the open count beside it ('11 1').
function updateReviewCount() {
  const count = REVIEW_ALL.length,
    chip = $('#rv-chip');
  for (const pill of $$('#btn-side .rv-n,#nav-side .rv-n')) {
    pill.hidden = !count;
    setHtml(pill, html`${lucideIcon('eye')}${count}`);
    pill.setAttribute('aria-label', translateTemplate('검토 대기 {n}', { n: count }));
  }
  const reviewButton = $('#btn-rv');
  reviewButton.hidden = !count;
  reviewButton.querySelector('.rv-c').textContent = count;
  // the sheet bar's [검토 M] half: its name starts with what it shows
  reviewButton.setAttribute('aria-label', translateTemplate('검토 {n} · 검토 대기 핀으로 가기', { n: count }));
  fitBarWords();
  const here = listReview().length;
  chip.hidden = !count || LAYOUT !== LAYOUT_MODE.WIDE || !SIDE_OPEN;
  chip.textContent =
    translateTemplate('검토 대기 {n}', { n: count }) +
    (multiDoc() && here !== count ? ' ' + translateTemplate('(이 문서 {n})', { n: here }) : '');
}
// [검토 M], the review chip and a review message's [보기]: the review section, opened and scrolled to; its dot goes
// (seen).
function gotoReview() {
  noticeSeen(NOTICE_DOT.RV);
  if (!listReview().length && REVIEW_ALL.length && multiDoc()) setShowAll(true);
  if (!SECTION_OPEN.review) {
    SECTION_OPEN.review = true;
    savePrefs({ sec: SECTION_OPEN });
  }
  drawPins();
  setSide(true);
  requestAnimationFrame(() => {
    const section = $('#sec-review');
    if (section && !section.hidden) section.scrollIntoView({ block: 'start', behavior: scrollMotion() });
  });
}
function reviewerLabel(pin: Pin) {
  if (!pin.author || !(pin.author.name || pin.author.login)) return translate('확인 필요');
  return isMe(pin.author)
    ? translate('내 확인 차례')
    : translateTemplate('{name}님 확인 필요', { name: who(pin.author) });
}
function listDropped() {
  return SHOW_ALL && multiDoc() ? DROPPED : DROPPED.filter((pin) => pdoc(pin) === DOC || !DOC);
}
// One section header (docs/handbook/viewer.md §목록 구획): chevron, name, count and - while collapsed - 'new N' (ids
// the section did not show when it was last expanded). The body it controls (aria-controls) is hidden while collapsed.
const SECTION_NAME_ID = { open: 'list-h', review: 'review-h', done: 'done-h' };
// ids = the pins this section lists now; all = the section's pins across every document. While expanded, everything is
// marked seen (all, so switching documents never reads as arrivals); SECTION_SEEN starts from the first load, so
// nothing is 'new' at boot.
function drawSectionHead(key, name, ids, all) {
  const toggle = document.getElementById(key + '-toggle');
  if (!toggle) return;
  const open = !!SECTION_OPEN[key],
    seen = SECTION_SEEN[key];
  if (open && seen) (all || ids).forEach((id) => seen.add(id));
  const newCount = open ? 0 : countNewInSection(seen, ids);
  const fresh = newCount ? html`<span class="sec-new">${translateTemplate('새 {n}', { n: newCount })}</span>` : '';
  setHtml(
    toggle,
    html`${lucideIcon(open ? 'chevron-down' : 'chevron-right')}<span class="sec-name" id="${SECTION_NAME_ID[key]}">${name} <span class="badge badge-secondary sec-n">${ids.length}</span></span>${fresh}`,
  );
  toggle.setAttribute('aria-expanded', String(open));
  const body = document.getElementById(toggle.getAttribute('aria-controls') || '');
  if (body) body.hidden = !open;
}
function toggleSection(key, force?) {
  if (!(key in SECTION_OPEN_DEFAULT)) return;
  SECTION_OPEN[key] = force === undefined ? !SECTION_OPEN[key] : !!force;
  savePrefs({ sec: SECTION_OPEN });
  drawPins();
}
// Redraws the pin panel from the lists (sections, counts, the Trash count, a reply in progress, the undo rows and notes
// and the banners of platform/notices.ts, keeping a focus that was in one) - and, while the changes view shows a pin,
// its guide line's buttons, whose [확인] follows that pin's state (drawPinGuideActions). The status line's review
// arrivals follow the review list it draws: those whose pins left it go, with [검토 M]'s dot (dropStaleReview).
/** Redraw active lists and retain the live editor, even when a rival close moved its pin out of the open list. */
function drawPins() {
  dropStaleReview();
  // the rows in the list's view: one of them is put back where it stood once the cards are drawn (lazyCards)
  const keep = listKeep();
  const openListed = listOpen(),
    doneListed = listDone(),
    droppedListed = listDropped();
  // a focus in an undo row or note, given back once they are drawn again (drawOffers)
  const keptNoticeFocus = noticeFocus();
  // The '나를 부른 핀' filter: only the open/awaiting-review pins across every document that @-tagged me (a
  // cross-document inbox).
  const mentioningMe = OPEN_ALL.concat(REVIEW_ALL).filter(mentionsMe),
    mentionFilter = $('#mention-filter');
  if (MENTION_ONLY && !mentioningMe.length) setMentionOnly(false);
  mentionFilter.hidden = !mentioningMe.length;
  mentionFilter.setAttribute('aria-pressed', String(MENTION_ONLY));
  setHtml(mentionFilter, html`${lucideIcon('at-sign')}${mentioningMe.length}`);
  mentionFilter.setAttribute('aria-label', translateTemplate('나를 부른 핀 {n}', { n: mentioningMe.length }));
  const openShown = MENTION_ONLY ? OPEN_ALL.filter(mentionsMe) : openListed;
  // If the cursor was in the reply input field or the edit card's note, it's restored to that position after redrawing
  // (so auto-sync redrawing the list, or a layout change redrawing the cards, never interrupts typing).
  const replyField = REPLY && replyNote(REPLY),
    replyFocus =
      replyField && document.activeElement === replyField ? [replyField.selectionStart, replyField.selectionEnd] : null;
  // The edit card's note or suggested-edit field keeps its focus and selection the same way.
  const editField =
    EDITOR.current &&
    document.activeElement &&
    EDITOR.current.el.contains(document.activeElement) &&
    document.activeElement.matches('.e-note,.e-sg-text')
      ? (document.activeElement as HTMLTextAreaElement)
      : null;
  const editArea = editField,
    editFocus = editArea ? [editArea.selectionStart, editArea.selectionEnd] : null,
    cardFocus = cardFocusKeep();
  drawSectionHead(
    'open',
    translate(MENTION_ONLY ? '나를 부른 열린 핀' : SHOW_ALL && multiDoc() ? '모든 문서의 열린 핀' : '열린 핀'),
    openShown.map((pin) => pin.id),
    OPEN_ALL.map((pin) => pin.id),
  );
  const allDocsButton = $('#all-docs');
  allDocsButton.setAttribute('aria-pressed', String(SHOW_ALL));
  setHtml(allDocsButton, html`${SHOW_ALL ? lucideIcon('check') : ''}${translate('모든 문서')}`);
  $('#side-n').textContent = PINS.length;
  applySide();
  // In compact, the Trash is a row in [⋯] with its count. On desktop the Trash is the link under the list.
  const trashCount = droppedListed.filter((pin) => !PURGING.has(pin.id)).length;
  $('#m-trash-n').textContent = trashCount;
  $('#trash-link').textContent = translateTemplate('휴지통 {n}', { n: trashCount });
  $('#trash-link').hidden = !trashCount;
  $('#empty').hidden = openShown.length > 0 || OPEN_ALL.length > 0 || REVIEW_ALL.length > 0 || !!EDITOR.current;
  // Empty list: the header's count already says it - a separate '아직 없습니다.' line is never added too. Only a note
  // that another document has pins is left.
  setHtml(
    $('#pins'),
    openShown.length
      ? cardRows(openShown, 'open')
      : html`${cardRows([], 'open')}${multiDoc() && !SHOW_ALL && OPEN_ALL.length ? html`<div class="dim list-empty">${translateTemplate('이 문서에는 없습니다 · 다른 문서에 {n}건', { n: OPEN_ALL.length })}</div>` : ''}`,
  ); // with no card, an undo row still gets its slot (cardRows)
  if (EDITOR.current) {
    const slot = $('#pins .edit-slot');
    if (slot) slot.replaceWith(EDITOR.current.el);
    else $('#pins').appendChild(EDITOR.current.el);
    renderEdit();
    if (editFocus && editArea && document.contains(editArea)) {
      editArea.focus();
      try {
        editArea.setSelectionRange(editFocus[0], editFocus[1]);
      } catch (error) {}
    }
  }
  // Awaiting-review section: between open pins and done. Hidden when empty - but not while a confirm's undo row stands
  // in it (offersIn). The card looks the same as an open pin (thread/replies); only the actions are [확인]/[답글].
  const reviewShown = MENTION_ONLY ? REVIEW_ALL.filter(mentionsMe) : listReview();
  $('#sec-review').hidden = !reviewShown.length && !offersIn('review');
  drawSectionHead(
    'review',
    translate('검토 대기'),
    reviewShown.map((pin) => pin.id),
    REVIEW_ALL.map((pin) => pin.id),
  );
  // result rows while the section picks (pins/flow-review-pick.ts)
  if (!drawReviewPick(reviewShown)) setHtml($('#review-pins'), cardRows(reviewShown, 'review'));
  drawOrderControl((SECTION_OPEN.open && openShown.length > 0) || (SECTION_OPEN.review && reviewShown.length > 0));
  updateReviewCount();
  // Done section: hidden header and all if empty. The header stays stuck to the top while scrolling.
  $('#sec-done').hidden = !doneListed.length;
  drawSectionHead(
    'done',
    translate('완료'),
    doneListed.map((pin) => pin.id),
    DONE_ALL.map((pin) => pin.id),
  );
  if (SECTION_OPEN.done)
    setHtml(
      $('#done-list'),
      doneListed.length ? html`${doneListed.slice().reverse().map(doneCard)}` : html`<div class="dim">없습니다.</div>`,
    );
  if ($('#trash').open) drawTrash();
  if (REPLY) {
    const slot = document.querySelector('#list .reply-slot');
    if (slot) slot.replaceWith(REPLY.el);
    renderReplyOutcome(); // the pin may have changed state meanwhile
    if (replyFocus && replyField && document.contains(replyField)) {
      replyField.focus();
      try {
        replyField.setSelectionRange(replyFocus[0], replyFocus[1]);
      } catch (error) {}
    }
  }
  drawOffers(keptNoticeFocus);
  drawBanners();
  lazyCards(keep);
  cardFocusBack(cardFocus);
  if (REVISION_VIEW.target) drawPinGuideActions();
}
// The pins of a list section in order (docs/handbook/viewer.md §목록 순서), list itself untouched. LIST_ORDER.NEW: the
// newest `at` first, the later pin first within a minute, a pin with no readable time last. LIST_ORDER.PAGE: by page,
// where the pin's mark is now, then line, then height on the page for a region, which has no line; pins of several
// documents stand document by document, since page numbers mean nothing across them. A pin with no page (a Markdown
// document's, ADR-0025 D2) is ordered by its lines alone - its page counts as 0. LIST_ORDER.ID: as the server lists
// them.
/** @param order - a LIST_ORDER value */
function orderPins(list: Pin[], order: string): Pin[] {
  if (order === LIST_ORDER.ID) return list;
  const key = (pin: Pin) => {
    if (order === LIST_ORDER.NEW) {
      const parts = timeParts(pin.at);
      return [parts ? -parts.t : Infinity, -pin.id];
    }
    const at = pinPlace(pin),
      docIndex = DOCS.findIndex((entry) => entry.key === pdoc(pin));
    return [
      docIndex < 0 ? DOCS.length : docIndex,
      typeof at.page === 'number' ? at.page : 0,
      pin.lo == null ? Infinity : pin.lo,
      at.frac ? at.frac[1] : Infinity,
      pin.id,
    ];
  };
  // Two missing values subtract to NaN, which falls through to the next key as a tie does.
  return list
    .map((pin) => ({ p: pin, k: key(pin) }))
    .sort((left, right) => {
      for (let i = 0; i < left.k.length; i++) {
        const difference = left.k[i] - right.k[i];
        if (difference) return difference;
      }
      return 0;
    })
    .map((entry) => entry.p);
}
// One list section's cards as Html, in the list's order; newest first, a day line stands over each day's first card.
// Its name is worked out here, so it is right from the next draw on when the date turns. An undo row of the section
// (sec: 'open', 'review') whose card has left gets an empty slot where its pin stands in that order, under its day's
// line, which stays while the row does if the pin was that day's only card (drawOffers puts the row in the slot). In
// the server's order the row follows the card drawn before it.
function cardRows(list: Pin[], section: string): Html {
  const now = Date.now(),
    slots = new Map();
  let day = '';
  if (ORDER !== LIST_ORDER.ID)
    for (const notice of NOTICES.values())
      if (
        notice.place === NOTICE_PLACE.ROW &&
        notice.sec === section &&
        notice.rec &&
        !list.some((pin) => pin.id === notice.pin)
      )
        slots.set(notice.rec, notice.n);
  return html`${orderPins(list.concat([...slots.keys()]), ORDER).map((pin) => {
    const dayText = ORDER === LIST_ORDER.NEW ? dayName(pin.at, now) : '',
      over = dayText && dayText !== day ? html`<div class="day-line"><span>${dayText}</span></div>` : '';
    if (dayText) day = dayText;
    const slot = slots.get(pin);
    return html`${over}${slot ? html`<div class="nt-slot" data-slot="${slot}"></div>` : card(pin)}`;
  })}`;
}
// Where a notice's undo row goes in a list section's box when the list drew no slot for it (the row came after that
// draw): where the list's next draw puts its slot (cardRows), so that draw moves nothing. Its place is by orderPins
// among what is drawn - the cards and the other rows that know their pins: after the one before it when that is of its
// day (newest first; in the page order always), else before the one after it when that is, else, its day having nothing
// else, under a line made for it between the two, which stays while the row does (dropBareDayLines). In the server's
// order, or for a row that does not know its pin, it follows the card drawn before it (the notice's prev), else it goes
// first.
function placeRow(box: HTMLElement, notice: Notice, row: HTMLElement) {
  const cardBefore = notice.prev != null ? box.querySelector('.pin.card[data-id="' + notice.prev + '"]') : null;
  if (!notice.rec || ORDER === LIST_ORDER.ID) {
    if (cardBefore) cardBefore.after(row);
    else box.prepend(row);
    return;
  }
  const drawn = new Map() as Map<Pin, Element>;
  for (const child of box.children) {
    const element = child as HTMLElement,
      drawnPin = element.matches('.pin.card')
        ? findAnyPin(Number(element.dataset.id))
        : element.matches('.nt-row')
          ? (NOTICES.get(Number(element.dataset.n)) || {}).rec || null
          : null;
    if (drawnPin && drawnPin !== notice.rec) drawn.set(drawnPin, child);
  }
  const order = orderPins([...drawn.keys(), notice.rec], ORDER),
    index = order.indexOf(notice.rec),
    before = order[index - 1],
    after = order[index + 1],
    now = Date.now();
  const day = (pin: Pin | undefined) => (pin && ORDER === LIST_ORDER.NEW ? dayName(pin.at, now) : ''),
    dayText = day(notice.rec);
  if (before && day(before) === dayText) {
    (drawn.get(before) as Element).after(row);
    return;
  }
  if (after && day(after) === dayText) {
    (drawn.get(after) as Element).before(row);
    return;
  }
  const dayLine = document.createElement('div');
  dayLine.className = 'day-line';
  dayLine.append(document.createElement('span'));
  (dayLine.firstChild as HTMLElement).textContent = dayText;
  if (before) (drawn.get(before) as Element).after(dayLine);
  else if (after) {
    const afterElement = drawn.get(after) as Element,
      over = afterElement.previousElementSibling;
    (over && over.matches('.day-line') ? over : afterElement).before(dayLine);
  } else box.prepend(dayLine);
  if (dayText) dayLine.after(row);
  else dayLine.replaceWith(row);
} // the page order has no day lines
// Takes out a day line with nothing of its day under it - its last undo row gone - in the open and review sections.
function dropBareDayLines() {
  for (const dayLine of $$('#pins>.day-line,#review-pins>.day-line')) {
    const next = dayLine.nextElementSibling;
    if (!next || next.matches('.day-line')) dayLine.remove();
  }
}
// [최신순 | 위치순 | 번호순]: shown while the open or review section shows a card, the list's order checked.
function drawOrderControl(any: boolean) {
  const control = $('#list-order');
  control.hidden = !any;
  for (const button of control.querySelectorAll('button')) {
    const on = (button as HTMLElement).dataset.order === ORDER;
    button.classList.toggle('on', on);
    button.setAttribute('aria-checked', String(on));
  }
  roveSegment(control);
} // the group's one Tab stop is the order now chosen (main.ts)
// A press on the order control: the list is drawn in that order, remembered for this browser, with the control where it
// stood under the pointer - a card kept in place (lazyCards) would scroll it away - and its button keeps the focus (it
// is not redrawn).
/** @param order - a LIST_ORDER value */
function setListOrder(order: string | undefined) {
  const next = listOrderOf(order);
  if (next === ORDER) return;
  setOrder(next);
  savePrefs({ order: next });
  const control = $('#list-order'),
    y = control.getBoundingClientRect().top;
  drawPins();
  listScroller().scrollTop += control.getBoundingClientRect().top - y;
}
// Cards far from the list's view are left for the browser to skip (.lazy: content-visibility:auto, list.css): it does
// not lay them out or paint them until they come near the view. Their markup stays whole and current all the while - a
// card coming back is drawn from what it holds then - and a focus, a find or a selection reaching into one draws it at
// once; a script's measure inside one lays it out for the answer, but the innerText of what is skipped is empty. What
// it saves: each page PDF.js draws for the first time adds its embedded fonts to document.fonts, and every font added
// makes the browser lay out all the text in the page again - every card in the open panel with it, so the first wheel
// scroll through a figure document of many pages stalls on those layouts. Only a card more than a view's height above
// or below the list's view is skipped (lazyWatch): skipping contains a card (paint containment), which draws its parts
// on whole pixels and clips what reaches past its edge (a focus ring, a 44px touch target's hit area), so a card in
// view, or scrolled to, is never held and draws as it is. A card being edited or holding the reply box is never
// skipped: containment would hold the fixed action row (compact) inside the card. A skipped card stands at the height
// it had when it went (--card-h, from the observer's own measure: no extra layout). With a guessed height instead the
// list would move under a person scrolled down it at every draw, by the guess's error over every card above, and a jump
// to a card (a mark's badge, [검토 M]) would aim by guesses. The height goes stale when the list's width or its font
// changes, so then every card is drawn again and sorted anew (lazyAgain), as at each draw - which makes new cards, all
// drawn once. A height that goes stale otherwise (a card changed in place while skipped) comes right as the card comes
// near: the browser's scroll anchoring keeps the view where it stands as it grows or shrinks. A draw makes new
// elements, which that anchoring cannot hold, so a row in the view before it (listKeep) is put back where it stood: its
// cards may stand at other heights than the ones they replace.
let LAZY_IO = null as IntersectionObserver | null,
  LAZY_ROOT = null as HTMLElement | null,
  LAZY_WIDTH = 0,
  LAZY_HEIGHT = -1;
// After a draw: the first row kept (listKeep) that is still drawn in the section it was in is put back where it stood -
// a row whose pin a poll moved to another section (검토 대기, 완료) or deleted gives way to the next, and with none
// left nothing is put back: followed into its new section, the view would jump past every card still open. Then every
// new card is sorted.
function lazyCards(keep: { sel: string; sec: string; top: number }[]) {
  const scroller = listScroller();
  for (const kept of keep) {
    const row = document.querySelector(kept.sel) as HTMLElement | null;
    if (!row || !row.getClientRects().length || listSection(row) !== kept.sec) continue;
    const moved = row.getBoundingClientRect().top - kept.top;
    if (Math.abs(moved) >= 0.5) scroller.scrollTop += moved;
    break;
  }
  const list = $('#list');
  LAZY_WIDTH = list.getClientRects().length ? list.clientWidth : 0;
  lazyWatch();
}
// Has every card sorted from its first report, by an observer whose margin is the scroller's height now, in px above
// and below its view (a percentage would be of the root's width): it is made again when that height or the scroller
// changes.
function lazyWatch() {
  if (!window.IntersectionObserver) return;
  const scroller = listScroller(),
    height = scroller.clientHeight;
  if (LAZY_IO) LAZY_IO.disconnect();
  if (!LAZY_IO || LAZY_ROOT !== scroller || LAZY_HEIGHT !== height) {
    LAZY_ROOT = scroller;
    LAZY_HEIGHT = height;
    LAZY_IO = new IntersectionObserver(lazySort, { root: scroller, rootMargin: height + 'px 0px' });
  }
  for (const card of $$('#list .pin.card')) LAZY_IO.observe(card);
}
// The observer's reports: a card that came within a view's height of the list's view is drawn as it is; one that went
// further is skipped at the height it has now - not a card that is not laid out (the panel folded: no height to stand
// at), being edited or holding the reply box.
function lazySort(entries: IntersectionObserverEntry[]) {
  for (const entry of entries) {
    const card = entry.target as HTMLElement;
    if (entry.isIntersecting) {
      card.classList.remove('lazy');
      continue;
    }
    if (
      card.classList.contains('lazy') ||
      !entry.boundingClientRect.height ||
      card.classList.contains('editing') ||
      card.querySelector('.reply-box')
    )
      continue;
    const style = getComputedStyle(card); // the content box: what contain-intrinsic-size sets
    card.style.setProperty(
      '--card-h',
      entry.boundingClientRect.height -
        parseFloat(style.paddingTop) -
        parseFloat(style.paddingBottom) -
        parseFloat(style.borderTopWidth) -
        parseFloat(style.borderBottomWidth) +
        'px',
    );
    card.classList.add('lazy');
  }
}
// Every card drawn once more and sorted anew, a row in the view kept in place: the skipped cards' heights are stale. So
// they are when the list's width changes or it is shown (a card not laid out was not skipped), and when a font the list
// is set in comes in (a slice of the bundled Pretendard for letters not drawn before): their heights were read in the
// fallback face. The fonts PDF.js adds are not the list's, and fire no loadingdone besides.
function lazyAgain() {
  const keep = listKeep();
  $$('#list .pin.card.lazy').forEach((card) => card.classList.remove('lazy'));
  lazyCards(keep);
}
// The scroller's height changed (a window, the sheet dragged): the observer's margin follows it.
if (window.ResizeObserver) {
  const listResize = new ResizeObserver(() => {
    const list = $('#list'),
      width = list.getClientRects().length ? list.clientWidth : 0;
    if (width && width !== LAZY_WIDTH) lazyAgain();
    else if (LAZY_IO && listScroller().clientHeight !== LAZY_HEIGHT) lazyWatch();
  });
  listResize.observe($('#list'));
  listResize.observe($('#right'));
}
document.fonts.addEventListener('loadingdone', (event) => {
  if (!$$('#list .pin.card.lazy').length) return;
  const listFonts = getComputedStyle($('#list')).fontFamily;
  if (
    (event as FontFaceSetLoadEvent).fontfaces.some((face) =>
      listFonts.includes(face.family.replace(/^["']|["']$/g, '')),
    )
  )
    lazyAgain();
});
// The box the list scrolls in: the list itself, or in compact the panel (#right), which holds the tool bar above it.
function listScroller() {
  return document.body.classList.contains('compact') ? $('#right') : $('#list');
}
// The cards and archive rows in the list's view, top first, each with its section and its top: the rows lazyCards may
// put back. None while the list is at its top (the browser does not anchor there either: what a draw adds above it
// shows) or is not laid out.
function listKeep(): { sel: string; sec: string; top: number }[] {
  const scroller = listScroller(),
    out: { sel: string; sec: string; top: number }[] = [];
  if (!scroller.scrollTop || !scroller.getClientRects().length) return out;
  const viewRect = scroller.getBoundingClientRect();
  for (const row of $$('#list .pin[data-id],#list .arc-row[data-id],#list .rv-row[data-id]') as HTMLElement[]) {
    if (!row.getClientRects().length) continue;
    const rect = row.getBoundingClientRect();
    if (rect.bottom <= viewRect.top) continue;
    if (rect.top >= viewRect.bottom) break;
    out.push({
      sel:
        '#list ' +
        (row.classList.contains('arc-row') ? '.arc-row' : row.classList.contains('rv-row') ? '.rv-row' : '.pin') +
        '[data-id="' +
        CSS.escape(row.dataset.id || '') +
        '"]',
      sec: listSection(row),
      top: rect.top,
    });
  }
  return out;
}
// The section a row is drawn in: open (#pins), awaiting review (#review-pins) or done (#done-list).
function listSection(row: Element) {
  const section = row.closest('#pins,#review-pins,#done-list');
  return section ? section.id : '';
}
// A focus on a card's control (its number, a button) goes back to the same control of the same card once the lists are
// drawn again (a poll, someone's change, the list read after a [지우기] whose focus went to the card beside): drawn
// anew, it would fall to the page and the next Tab start over. Text fields keep theirs above; a card gone leaves the
// focus where it fell, and a focus that is somewhere again (a notice's, drawOffers) stays there.
function cardFocusKeep(): { el: HTMLElement; id: string; act: string; i: number } | null {
  const focused = document.activeElement as HTMLElement | null,
    cardElement = focused && focused.closest ? (focused.closest('#list .pin[data-id]') as HTMLElement | null) : null;
  const act = focused && focused.dataset ? focused.dataset.act || '' : '';
  if (!focused || !cardElement || !act || focused.matches('textarea,input')) return null;
  return {
    el: focused,
    id: cardElement.dataset.id || '',
    act,
    i: [...cardElement.querySelectorAll('[data-act="' + CSS.escape(act) + '"]')].indexOf(focused),
  };
}
function cardFocusBack(kept: { el: HTMLElement; id: string; act: string; i: number } | null) {
  const focused = document.activeElement;
  if (!kept || (focused && focused !== document.body)) return;
  if (document.contains(kept.el)) {
    kept.el.focus({ preventScroll: true });
    return;
  } // the edit card or the reply, put back in its slot
  const cardElement = document.querySelector('#list .pin[data-id="' + CSS.escape(kept.id) + '"]'),
    same = cardElement ? cardElement.querySelectorAll('[data-act="' + CSS.escape(kept.act) + '"]') : null;
  const target = (same && (same[Math.max(0, kept.i)] || same[0])) as HTMLElement | null;
  if (target) target.focus({ preventScroll: true });
}
// Location estimation (.est, dashed) is judged by the server and carried as est in /api/pins (pin_est - comparing the
// manuscript fingerprint of the build the pin was placed on with the current build). The viewer does not judge it by
// wall clock - the browser's time zone, a note-only edited_at and a pin placed on a stale PDF would all mislead it -
// and renders the value it is given.
function isEstimated(pin: Pin) {
  return pin.est === true;
}
// Re-decides every page number's place (pageNoSides) and every drawn mark's badge side for its page's width and margin
// now (a zoom, a re-fit or a band change moves both), then how far each badge's press area reaches (markHitSides: the
// badges' distances follow the same width). A mark on a page that is not laid out keeps its side until the page shows
// again.
function markBadgeSides() {
  pageNoSides();
  const rooms = new Map();
  $$('.mark').forEach((mark) => {
    const page = mark.parentElement;
    if (!rooms.has(page)) rooms.set(page, markBadgeRoom(page));
    const room = rooms.get(page);
    if (room) mark.classList.toggle('in', markBadgeIn(+mark.dataset.fx, room.w, room.pad, room.reach));
  });
  $$('.sel.pending').forEach(pendingBadgeSide);
  markHitSides();
  markCoverSkip();
} // the pending boxes' '+' badges follow the same rule
// A badge no scroll can show is no stop for the keyboard (docs/handbook/viewer.md §모바일 레이아웃): otherwise Tab
// would put the ring on a mark the person cannot see, and its tooltip would float over the box that hides it. The
// covers are the boxes drawn over the pages, each where it is laid out (MARK_COVERS): the panel (#right: the sheet, the
// overlay panel, the closed sheet's bar) and the status line standing on the sheet's top edge (#status-dock, outside
// the panel so its action can reach up over the pages). The bars that also stand over the pages do so inside the
// panel's box: the tool bar is the sheet's head, and the phone's search row (#doc-nav at its foot) lies over the closed
// bar. A badge is a stop while the pages can scroll it, up or down within their ends, to where it stands whole in the
// pages' view (#left's box within the window) clear of every cover in its columns (markShift) - wherever it stands now,
// so Tab meets the badges under the sheet in turn and brings each out (markReveal). Were the badges a cover is over at
// that moment passed over, Tab from #3 would go past #4 and #5 to #6, whose scroll then shows the two it passed. No
// stop: a badge under the overlay panel (it runs the pages' height), one at the last page's foot the pages end before
// bringing above the sheet, every badge with the sheet pulled up to the document bar. A scroll moves a badge and the
// room it can go to alike, so it moves no stop. A badge whose centre a cover is over now (or one out of view with
// nowhere to show) is hidden (MARK_HIDDEN): a script's focus or the person's scroll can leave the focus on it, and its
// description does not show (platform/tooltip.ts showTip) - one standing over it goes. The boxes are compared, not
// hit-tested: a hit test per badge is too slow for a pass that a scroll pays every frame with many badges on screen;
// the comparison is cheap. Every box is read before any stop is written, and only a stop that changes is written.
const MARK_COVERS = ['#right', '#status-dock'],
  MARK_EDGE = 8; // MARK_EDGE: px a revealed badge keeps clear of a cover or the view's edge
/** The pages' view: #left's box within the window. */
function markView(): { left: number; top: number; right: number; bottom: number } {
  const rect = $('#left').getBoundingClientRect();
  return {
    left: Math.max(rect.left, 0),
    top: Math.max(rect.top, 0),
    right: Math.min(rect.right, innerWidth),
    bottom: Math.min(rect.bottom, innerHeight),
  };
}
/** The covers' boxes laid out over the view, each cut to it. */
function markCoverBoxes(view: { left: number; top: number; right: number; bottom: number }) {
  const out: { left: number; top: number; right: number; bottom: number }[] = [];
  for (const selector of MARK_COVERS) {
    const cover = $(selector);
    if (!cover || !cover.getClientRects().length) continue;
    const rect = cover.getBoundingClientRect();
    const x0 = Math.max(rect.left, view.left),
      y0 = Math.max(rect.top, view.top),
      x1 = Math.min(rect.right, view.right),
      y1 = Math.min(rect.bottom, view.bottom);
    if (x1 > x0 && y1 > y0) out.push({ left: x0, top: y0, right: x1, bottom: y1 });
  }
  return out;
}
// How far the pages scroll down (px, up negative) to bring the badge's box into a part of the view that none of the
// covers is over in the badge's columns, the scroll kept within [minScroll, maxScroll] (what the pages can still scroll
// up and down): the least such distance, null where no part can hold it. A badge wholly in such a part already is 0 -
// it is not moved, as the browser leaves a control in view - and one brought in stands MARK_EDGE px clear of that
// part's ends where the part has the room. Pure.
function markShift(
  badge: { left: number; top: number; right: number; bottom: number },
  view: { left: number; top: number; right: number; bottom: number },
  covers: { left: number; top: number; right: number; bottom: number }[],
  minScroll: number,
  maxScroll: number,
): number | null {
  let spans = [[view.top, view.bottom]];
  for (const cover of covers) {
    if (cover.right <= badge.left || cover.left >= badge.right) continue;
    spans = spans.flatMap(([top, bottom]) =>
      cover.bottom <= top || cover.top >= bottom
        ? [[top, bottom]]
        : [...(cover.top > top ? [[top, cover.top]] : []), ...(cover.bottom < bottom ? [[cover.bottom, bottom]] : [])],
    );
  }
  const height = badge.bottom - badge.top;
  let best = null as number | null;
  for (const [top, bottom] of spans) {
    if (bottom - top < height) continue;
    const margin = badge.top >= top && badge.bottom <= bottom ? 0 : Math.min(MARK_EDGE, (bottom - top - height) / 2);
    const shift = Math.min(
      maxScroll,
      Math.max(
        minScroll,
        badge.top < top + margin
          ? badge.top - top - margin
          : badge.bottom > bottom - margin
            ? badge.bottom - bottom + margin
            : 0,
      ),
    );
    // the pages end before the badge gets there
    if (badge.top - shift < top - 0.5 || badge.bottom - shift > bottom + 0.5) continue;
    if (best === null || Math.abs(shift) < Math.abs(best)) best = shift;
  }
  return best;
}
function markCoverSkip() {
  const pane = $('#left');
  if (!pane) return;
  const view = markView(),
    covers = markCoverBoxes(view),
    minScroll = -pane.scrollTop,
    maxScroll = pane.scrollHeight - pane.clientHeight - pane.scrollTop;
  const badges = $$('.mark button.mark-jump') as HTMLElement[];
  const at = badges.map((badge) => {
    const rect = badge.getBoundingClientRect();
    if (!rect.width) return { stop: 0, hid: false };
    const centerX = rect.left + rect.width / 2,
      centerY = rect.top + rect.height / 2;
    // a stop while the pages can bring it to where it shows, whether in view or not
    const stop = markShift(rect, view, covers, minScroll, maxScroll) === null ? -1 : 0;
    return {
      stop,
      hid:
        centerX >= view.left && centerX < view.right && centerY >= view.top && centerY < view.bottom
          ? covers.some(
              (cover) =>
                centerX >= cover.left && centerX < cover.right && centerY >= cover.top && centerY < cover.bottom,
            )
          : stop < 0,
    };
  });
  badges.forEach((badge, index) => {
    const state = at[index];
    if (badge.tabIndex !== state.stop) badge.tabIndex = state.stop;
    if (state.hid) MARK_HIDDEN.add(badge);
    else MARK_HIDDEN.delete(badge);
  });
  for (const tipTarget of [TIP_AT && TIP_AT.el, armedTipElement])
    if (tipTarget && MARK_HIDDEN.has(tipTarget)) {
      hideTip();
      break;
    }
}
// Scrolls the pages to bring a badge to where it shows (markShift), when they can. It shows something, so a jump on its
// way ends first (endJumpForScroll): its settling would glide the pages back.
function markReveal(badge: HTMLElement) {
  const pane = $('#left'),
    view = markView(),
    rect = badge.getBoundingClientRect();
  if (!rect.width) return;
  const shift = markShift(
    rect,
    view,
    markCoverBoxes(view),
    -pane.scrollTop,
    pane.scrollHeight - pane.clientHeight - pane.scrollTop,
  );
  if (!shift) return;
  endJumpForScroll();
  pane.scrollBy({ top: shift, behavior: 'instant' });
}
// Tab and Shift+Tab bring the badge they reach to where it shows. The browser scrolls a focused control into the pages'
// box only, and on the tablet's or the phone's sheet, under its status line or its closed bar, that can be out of
// sight: the focus would stay under the cover and its description over it. The key moves the focus as its default
// action, in its own task, so a focus that arrives while MARK_TAB is set is the walk's; a focus a script puts on a
// badge (focusPlace, without a scroll) is left where it is. The focus events come before the browser's own scroll for
// the focus, which then finds the badge in view.
let MARK_TAB = false;
function markTabKey(event: KeyboardEvent) {
  if (event.key !== 'Tab') return;
  MARK_TAB = true;
  setTimeout(() => {
    MARK_TAB = false;
  }, 0);
}
document.addEventListener('keydown', markTabKey, true);
$('#left').addEventListener('focusin', (event) => {
  const badge = event.target;
  if (!MARK_TAB || !(badge instanceof HTMLElement) || !badge.matches('.mark button.mark-jump')) return;
  markReveal(badge);
});
// What the covers cover changes without the marks being drawn again: the sheet opens, closes or is dragged to another
// height, the status line comes or goes, the overlay panel slides in, the window is resized, or the pages scroll under
// them. The covers' sizes are watched (the sheet's open and closed heights differ, a status line goes from none to its
// line); a scroll asks again at most once a frame. The keyboard's focus on a badge a cover has come over (the sheet a
// press of Enter on it opened, Ctrl+\ or a height chosen) is brought out again, as the keyboard's focus in a field is
// kept above the touch keyboard; a badge the person scrolls under a cover keeps the focus where it is, as a control
// scrolled out of the window does, and only its description goes - scrolling the pages back would undo the person's own
// scroll, and moving the focus would lose their place in the Tab order. The next Tab goes on from it.
function markCoversMoved() {
  markCoverSkip();
  const focused = document.activeElement;
  if (focused instanceof HTMLElement && MARK_HIDDEN.has(focused) && keyInput()) markReveal(focused);
}
if (window.ResizeObserver) {
  const coverResize = new ResizeObserver(markCoversMoved);
  for (const selector of MARK_COVERS) {
    const cover = $(selector);
    if (cover) coverResize.observe(cover, { box: 'border-box' });
  }
}
// The overlay panel slides in and out by its offset, its size unchanged (responsive.css mid-panel-in, side-panel.css
// side-in): the observer hears of the panel only while it is still off the pages, so the slide's end asks again.
$('#right').addEventListener('animationend', (event) => {
  if (event.target === event.currentTarget) markCoversMoved();
});
let MARK_COVER_TICK = 0;
$('#left').addEventListener(
  'scroll',
  () => {
    if (MARK_COVER_TICK) return;
    MARK_COVER_TICK = requestAnimationFrame(() => {
      MARK_COVER_TICK = 0;
      markCoverSkip();
    });
  },
  { passive: true },
);
// Draws one mark per open or awaiting-review pin of this document on its page: where the pin's element is now for a
// figure pin (pinPlace), else where it was pinned, then decides each badge's side (markBadgeSides) and puts a save's or
// an append's undo chip back on its mark (drawChips). A pin without a usable box or page draws nothing.
/** Draw native, named pin badge buttons at the current mark coordinates, preserving mark and undo-chip geometry. */
// A pin a page verdict line shows (isShownOnLine) draws no page-size box: the line under its page says it
// (drawPageVerdicts, first).
function marks() {
  if (isMarkdownDoc()) {
    drawPinMarks();
    drawChips();
    return;
  } // the Markdown surface marks its lines (markdown/view.ts)
  $$('.mark').forEach((mark) => mark.remove());
  drawPageVerdicts();
  // Awaiting-review pins are also drawn as purple marks - so the reviewer can see right there what was fixed (unrelated
  // to an open pin's overlap/editing). A figure pin is drawn where the server found its element in this build (see
  // pinPlace), and a found element is no estimate.
  PINS.concat(REVIEW_ALL.filter((pin) => pdoc(pin) === DOC)).forEach((pin) => {
    const at = pinPlace(pin),
      page = document.getElementById('p' + at.page);
    if (!page || !isFrac(at.frac)) return;
    if (isShownOnLine(pin)) return;
    const est = isEstimated(pin) && !hasMark(pin),
      lost = pin.stale || isElementLost(pin);
    const mark = document.createElement('div');
    mark.className =
      'mark' + (lost ? ' st' : '') + (est ? ' est' : '') + (pinState(pin) === PIN_STATE.REVIEW ? ' rv' : '');
    mark.dataset.pin = String(pin.id);
    mark.dataset.fx = String(at.frac[0]);
    Object.assign(mark.style, {
      left: at.frac[0] * 100 + '%',
      top: at.frac[1] * 100 + '%',
      width: at.frac[2] * 100 + '%',
      height: at.frac[3] * 100 + '%',
    });
    const note = String(pin.note || '')
      .replace(/\s+/g, ' ')
      .trim();
    const tip =
      '#' +
      pin.id +
      ' · ' +
      (note ? (note.length > 60 ? note.slice(0, 60) + '…' : note) : translate('(메모 없음)')) +
      (est ? ' ' + translate('(PDF가 새로 만들어져 위치는 추정입니다)') : '') +
      (isElementLost(pin) ? ' · ' + translate('요소 잃음') : '');
    setHtml(
      mark,
      html`<button type="button" class="mark-jump" translate="no" data-act="mark-jump" data-id="${pin.id}" aria-label="${translateTemplate('핀 #{id} 카드로 이동', { id: pin.id })}" data-tip="${tip}">${pin.id}</button>`,
    );
    page.appendChild(mark);
  }); // the tip carries the note
  markBadgeSides();
  drawChips();
}
// Clicking a badge scrolls to and flashes the card (never calls pick). The mark box itself has pointer-events:none, so
// a drag over it still becomes a new selection - only the badge button needs to block mousedown.
$('#doc').addEventListener(
  'mousedown',
  (event) => {
    if (event.target.closest('.mark [data-act=mark-jump]')) {
      event.stopPropagation();
      event.preventDefault();
    }
  },
  true,
);
// Clicking a badge -> scroll to the card + .cur highlight + a 1.2-second flash. The highlight is never left on - it
// releases, so it does not stay on the card until the next click. compact: clicking a badge expands the panel/sheet and
// that card, then scrolls via jumpToCard. Expands the section that holds pin id if it is collapsed (a mark click, a
// notification, [검토 대기 N]). Returns true if it changed.
function openSectionFor(id) {
  const pin = findAnyPin(id);
  if (!pin) return false;
  const state = pinState(pin),
    key = state === PIN_STATE.REVIEW ? 'review' : state === PIN_STATE.DONE ? 'done' : 'open';
  if (SECTION_OPEN[key]) return false;
  SECTION_OPEN[key] = true;
  savePrefs({ sec: SECTION_OPEN });
  return true;
}
// A mark badge's card: opens its section and the panel (a collapsed one too); compact also expands the card.
function revealCard(id) {
  if (openSectionFor(id)) drawPins();
  setSide(true);
  if (LAYOUT === LAYOUT_MODE.WIDE) return;
  if (!OPEN_CARDS.has(id) && (PINS.some((pin) => pin.id === id) || REVIEW_ALL.some((pin) => pin.id === id))) {
    OPEN_CARDS.add(id);
    drawPins();
  }
}
function jumpToCard(id) {
  if (openSectionFor(id)) drawPins();
  const cardElement = document.querySelector('.pin[data-id="' + id + '"],.rv-row[data-id="' + id + '"]') as HTMLElement;
  if (!cardElement) return; // a result row while the review section picks
  cardElement.scrollIntoView({ behavior: scrollMotion(), block: 'nearest' });
  $$('.pin.cur').forEach((other) => {
    if (other !== cardElement) other.classList.remove('cur');
  });
  clearTimeout(cardElement._curT);
  cardElement.classList.remove('flash');
  void cardElement.offsetWidth;
  cardElement.classList.add('cur', 'flash');
  cardElement._curT = setTimeout(() => cardElement.classList.remove('cur', 'flash'), 1200);
}
// A '#12' link in text: expands and scrolls to that pin's card/archive row, then flashes it. If it's on another
// document, '모든 문서' is turned on.
/** @param [focus] - by keyboard: the focus goes to the card (its number) */
function gotoPinRef(id: number, focus?: boolean) {
  const pin = findAnyPin(id);
  if (!pin) {
    if (DROPPED.some((dropped) => dropped.id === id)) openTrash(id);
    return;
  }
  const state = pinState(pin);
  if (multiDoc() && DOC && pdoc(pin) !== DOC) setShowAll(true);
  if (state === PIN_STATE.DONE) SECTION_OPEN.done = true;
  else {
    OPEN_CARDS.add(id);
    SECTION_OPEN[state === PIN_STATE.REVIEW ? 'review' : 'open'] = true;
  }
  savePrefs({ sec: SECTION_OPEN });
  setSide(true);
  drawPins();
  requestAnimationFrame(() => {
    const row = document.querySelector(
      '.pin[data-id="' + id + '"],.arc-row[data-id="' + id + '"],.rv-row[data-id="' + id + '"]',
    ) as HTMLElement;
    if (!row) return;
    row.scrollIntoView({ behavior: scrollMotion(), block: 'nearest' });
    row.classList.remove('flash');
    void row.offsetWidth;
    row.classList.add('flash');
    clearTimeout(row._flT);
    row._flT = setTimeout(() => row.classList.remove('flash'), 1200);
    if (focus) focusCard(id);
  });
}
// The pin id beside the card that holds the control - the next card in its section, else the one before - or null:
// where the focus goes when that card leaves by a keyboard press ([삭제], [지우기]).
function cardNeighbour(control: HTMLElement): number | null {
  const cardElement = control.closest('.pin.card');
  if (!cardElement) return null;
  let next = cardElement.nextElementSibling;
  while (next && !next.matches('.pin.card')) next = next.nextElementSibling;
  let previous = cardElement.previousElementSibling;
  while (previous && !previous.matches('.pin.card')) previous = previous.previousElementSibling;
  const neighbour = (next || previous) as HTMLElement | null;
  return neighbour ? Number(neighbour.dataset.id) : null;
}
// Puts the focus on pin id's card - its number (a button) - when it is drawn.
function focusCard(id: number) {
  const target = document.querySelector(
    '.pin[data-id="' +
      id +
      '"] .n.go,.arc-row[data-id="' +
      id +
      '"] .n,.rv-row[data-id="' +
      id +
      '"] input:not(:disabled),.rv-row[data-id="' +
      id +
      '"] .rv-act',
  ) as HTMLElement | null;
  if (target) target.focus({ preventScroll: true });
} // a result row (pins/flow-review-pick.ts): its box, or its first link when the box is off
// Scrolls the mark of pin id into view and flashes it (switching to the pin's document first); a pin whose mark is not
// drawn scrolls to the page the mark would be on.
function jumpPin(id) {
  if (viaDoc(id, jumpPin)) return;
  const pin = PINS.find((x) => x.id === id) || REVIEW_ALL.find((x) => x.id === id && pdoc(x) === DOC);
  if (!pin) {
    const reviewed = REVIEW_ALL.find((listed) => listed.id === id);
    if (reviewed && docInfo(pdoc(reviewed))) {
      const docKey = pdoc(reviewed),
        opening = switchDoc(docKey),
        visit = SWITCHSEQ;
      opening.then(() => {
        if (DOC === docKey && visit === SWITCHSEQ) jumpPin(id);
      });
    }
    return;
  }
  if (document.body.classList.contains('revision-open')) setViewMode(VIEW_MODE.MANUSCRIPT);
  if (jumpToPageLine(id)) return; // a pin its page verdict line shows: the line
  marksShow(); // the way to a mark shows the marks (pins/input-hide-marks.ts)
  // collapsed first so the sheet doesn't cover the page, then measured
  if (LAYOUT === LAYOUT_MODE.NARROW) setSide(false);
  if (isMarkdownDoc()) {
    jumpToPinLines(id);
    return;
  } // its first line on the Markdown surface
  const mark = document.querySelector('.mark[data-pin="' + id + '"]') as HTMLElement;
  if (mark) {
    const pane = $('#left'),
      paneRect = pane.getBoundingClientRect(),
      markRect = mark.getBoundingClientRect();
    endJumpForScroll();
    pane.scrollTop += markRect.top - (paneRect.top + paneRect.height * 0.3);
    mark.classList.remove('flash');
    void mark.offsetWidth;
    mark.classList.add('flash');
  } else {
    arrivePage(pinPlace(pin).page); // the page's top, or a figure page's figure
  }
}
// Hovering a card highlights its mark, along with any overlapping counterpart marks.
function markIdsFor(pin: Pin) {
  return [pin.id].concat((pin.rel || []).map((entry) => entry.id));
}
$('#pins').addEventListener('mouseover', (event) => {
  const cardElement = event.target.closest('.pin');
  if (!cardElement) return;
  const pin = PINS.find((listed) => listed.id === +cardElement.dataset.id);
  if (!pin) return;
  markIdsFor(pin).forEach((id) => {
    const mark = document.querySelector('.mark[data-pin="' + id + '"]');
    if (mark) mark.classList.add('hi');
  });
});
$('#pins').addEventListener('mouseout', (event) => {
  const cardElement = event.target.closest('.pin');
  if (!cardElement) return;
  const pin = PINS.find((listed) => listed.id === +cardElement.dataset.id);
  if (!pin) return;
  markIdsFor(pin).forEach((id) => {
    const mark = document.querySelector('.mark[data-pin="' + id + '"]');
    if (mark) mark.classList.remove('hi');
  });
});
export {
  PINS_APPLIED_SEQ,
  cardNeighbour,
  drawPins,
  dropBareDayLines,
  fitBarWords,
  focusCard,
  gotoPinRef,
  gotoReview,
  jumpPin,
  jumpToCard,
  listDropped,
  listReview,
  loadPins,
  loadPinsNow,
  markBadgeSides,
  marks,
  orderPins,
  placeRow,
  revealCard,
  reviewerLabel,
  setListOrder,
  toggleSection,
  updateReviewCount,
};
