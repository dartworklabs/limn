import { verdictOf } from '../app/rules-pins.ts';
import { DOC } from '../app/state.ts';
import { docInfo, verdictLabel, pageVerdictsOn } from '../documents/state.ts';
import { endJumpForScroll } from '../layout/flow-scroll.ts';
import { focusedElement, findMaybe, $, searchToPage } from '../platform/dom.ts';
import { translateTemplate, translate } from '../platform/i18n.ts';
import { html, lucideIcon } from '../platform/markup.ts';
import { getDraft } from './state-drafts.ts';
import { verdictLineRenderer } from './state-line-renderer.ts';
import { KEYED_PAGE, READING_LINE_PAGE } from './state-lines.ts';
import { replacesWholeNote } from './state-reason-edit.ts';
import type { ReasonSession } from './state-reason.ts';
import {
  REASON_SESSION,
  setKeyGuard,
  setReasonSession,
  isReasonOpenOn,
  findReasonPin,
  hasUnsavedReason,
  LAST_KEY_SAVE,
  LAST_LINE_SAVE,
} from './state-reason.ts';
import { IS_BESIDE_PAGES, bringPage } from './view-panel.ts';
import { pageTargetShort, canVerdict, canCancelVerdict, pageVerdictPins } from './view-pins.ts';
import { isReasonField, findReasonField, COMPOSING_FIELD } from './view-reason-field.ts';

// A rebuild of the pages (buildDoc) takes the open popover away with them, and a focus in it would fall to nothing:
// what is typed on would be lost and a digit would save a verdict. Before it, holdReasonFocus notes the focus in the
// session's popover - its field with the selection, or one of its controls; null when the focus is anywhere else, which
// the rebuild leaves alone. After it, restoreReasonFocus gives the focus back to the same place in the popover drawn
// again, beside the pages or under one - while it is still on nothing. An input method's composition ends with the old
// field (the session's text holds what it had composed). A popover not drawn again leaves the keys typed on no verdict
// keys (KEY_GUARD).
type ReasonFocus = { sid: number; sel: [number, number, 'forward' | 'backward' | 'none'] | null; act: string };

function holdReasonFocus(): ReasonFocus | null {
  const session = REASON_SESSION,
    active = focusedElement(),
    pop = active ? active.closest('#doc .pv-pop') : null;
  if (!session || !active || !pop || pop.getAttribute('data-id') !== 's' + session.sid) return null;
  if (isReasonField(active))
    return {
      sid: session.sid,
      sel: [active.selectionStart, active.selectionEnd, active.selectionDirection || 'none'],
      act: '',
    };
  return { sid: session.sid, sel: null, act: active.dataset.act || '' };
}

function restoreReasonFocus(held: ReasonFocus | null) {
  const active = document.activeElement;
  if (!held || (active && active !== document.body)) return;
  const session = REASON_SESSION,
    pop =
      session && session.sid === held.sid ? document.querySelector('#doc .pv-pop[data-id="s' + held.sid + '"]') : null;
  const control = !pop
    ? null
    : held.sel
      ? findMaybe(pop, '.pv-reason', HTMLElement)
      : held.act
        ? findMaybe(pop, '[data-act="' + held.act + '"]', HTMLElement)
        : null;
  if (!control) {
    setKeyGuard(true);
    return;
  }
  control.focus({ preventScroll: true });
  if (held.sel && isReasonField(control)) control.setSelectionRange(held.sel[0], held.sel[1], held.sel[2]);
}

// Brings page `page`'s line into view and puts the focus on its draft's mark ('초안 있음') - before the saved reason,
// which comes first on the line and opens the popover too - else its reason control (focusLine).
function showDraftLine(page: number) {
  if (IS_BESIDE_PAGES) {
    bringPage(page);
    verdictLineRenderer().stickReadingLine();
  } // beside the pages the panel is the line, once the page is read (verdict/view-panel.ts)
  const line = document.querySelector('#doc .pv[data-page="' + page + '"]');
  if (!line) return;
  if (!IS_BESIDE_PAGES) {
    const block = line.parentElement || line;
    endJumpForScroll();
    block.scrollIntoView({ block: block.getBoundingClientRect().height <= $('#left').clientHeight ? 'center' : 'end' });
  }
  requestAnimationFrame(() => {
    if (isReasonField(document.activeElement)) return; // the mark was already pressed: its field keeps the focus
    const mark = findMaybe(document, '#doc .pv[data-page="' + page + '"] .pv-draft', HTMLElement);
    if (mark) mark.focus({ preventScroll: true });
    else if (!focusLine(page)) searchToPage();
  });
}

// Closes the popover. Closed on purpose (back: Esc, Enter after its save, [닫기], [지우기], [접기]) the focus stays on
// its own page: on the line's reason control ([이유 추가], the saved reason, '초안 있음' - whichever the line shows
// now), else the pressed word, else the line's first word - never the PDF area, from which the next Tab would go to the
// first page's line and scroll the document there. Closed by moving on with the focus inside, the focus goes to the PDF
// area.
function closeReasonPopover(back: boolean) {
  const session = REASON_SESSION,
    pop = document.querySelector('#doc .pv-pop'),
    had = !!pop && pop.contains(document.activeElement);
  setReasonSession(null);
  verdictLineRenderer().drawPageVerdicts();
  if (!back) {
    if (had) searchToPage();
    return;
  }
  if (!session || !focusLine(session.page)) searchToPage();
}

// Puts the focus on page `page`'s line: its reason control, else its pressed word, else its first word. Returns whether
// it did.
function focusLine(page: number) {
  const line = document.querySelector('#doc .pv[data-page="' + page + '"]');
  if (!line) return false;
  const control =
    findMaybe(line, '[data-act="pv-reason-open"]', HTMLElement) ||
    findMaybe(line, '.vd-b[aria-pressed="true"]', HTMLElement) ||
    findMaybe(line, '.vd-b', HTMLElement);
  if (!control) return false;
  control.focus({ preventScroll: true });
  return true;
}

// Puts the focus in the open field, its caret at the end.
function focusReasonField() {
  const field = findReasonField();
  if (!field || field.disabled) return;
  field.focus({ preventScroll: true });
  const end = field.value.length;
  field.setSelectionRange(end, end);
}

// What a reason session's verdict is about, by a short name for the status line: its page's target while its document
// is on screen ('PL16'), else its document's name.
function reasonTargetName(session: ReasonSession) {
  return targetNameOn(session.doc, session.page, session.id);
}

// The same for verdict pin id (0 while it has none) about page `page` of document doc.
function targetNameOn(doc: string | null, page: number, id: number) {
  if (doc === DOC) return pageTargetShort(page);
  const entry = doc ? docInfo(doc) : null;
  return (entry && entry.name) || (id ? '#' + id : translateTemplate('{page}쪽', { page }));
}

// ---------------- The popover and the line's reason
// What the popover says of its draft: '저장 중…' while it writes, '저장됨' with a check when its text is the saved
// reason, '저장 안 됨' when it is not written yet, nothing when empty.
function popoverState(session: ReasonSession): { text: string; cls: string } {
  if (session.writing || session.saveWhenBound) return { text: translate('저장 중…'), cls: 'busy' };
  const text = session.text.trim();
  if (!text) return { text: '', cls: '' };
  return text === session.saved || text === session.base.trim()
    ? { text: translate('저장됨'), cls: 'ok' }
    : { text: translate('저장 안 됨'), cls: 'warn' };
}

// What the keys do now, under the field: with a fine pointer and the focus in it, Enter saves (and with nothing typed
// Esc closes); after a first Esc, what the second does. With touch only the second press of [닫기] is said. The digits
// are not mentioned: in the field they are text.
function popoverHint(session: ReasonSession, focused: boolean) {
  const fine = matchMedia('(pointer:fine)').matches;
  if (session.escArm === 'btn') return translate('[닫기]를 한 번 더 누르면 이 이유를 버립니다');
  if (!fine) return '';
  if (session.escArm) return translate('Esc 한 번 더 누르면 이 이유를 버립니다');
  if (!focused) return '';
  return session.text.trim() ? translate('Enter 저장') : translate('Enter 저장') + ' · ' + translate('Esc 닫기');
}

// The popover on page `page`'s line while its session is open there (a person who may make a verdict): a labelled,
// non-modal group - the field, then one row: whose reason it is ('판정 #16 보류 이유', '판정 #16 보류 · 저장된 이유
// 수정' when it changes a saved one, '#15 채택에서 옮김' after a move), the draft's state, the keys, and [지우기] (a
// saved reason), [접기] (a draft, not while it is being written: the popover folds to the line's '초안 있음'), [닫기],
// [저장]. When a write found the note changed elsewhere, a row above the field shows that note whole (scrolling when
// long) with [메모 보기] and [그 위에 쓰기]. The keys' line is always there (aria-describedby never points at nothing),
// empty when there is nothing to say. The field is drawn empty; its text is put in after drawing (fillReasonField),
// never as markup a redraw could put back under the caret or an input method.
function reasonPopoverHtml(page: number) {
  const session = isReasonOpenOn(page) && canVerdict() ? REASON_SESSION : null;
  if (!session) return '';
  const active = document.activeElement,
    focused = isReasonField(active) && active.dataset.id === 's' + session.sid,
    state = popoverState(session),
    hint = popoverHint(session, focused);
  const word = verdictLabel(session.key),
    who = !session.id
      ? translateTemplate('{word} 판정 이유 · 판정 저장 중', { word })
      : replacesWholeNote(session) && session.base.trim()
        ? translateTemplate('판정 #{id} {word} · 저장된 이유 수정', { id: session.id, word })
        : translateTemplate('판정 #{id} {word} 이유', { id: session.id, word });
  const from = session.from ? findReasonPin(session.from) : null,
    moved = session.from
      ? translateTemplate('#{id} {word}에서 옮김', {
          id: session.from,
          word: verdictLabel((from && verdictOf(from)) || ''),
        })
      : '';
  const conflictRow = session.conflict
    ? html`<div class="pv-pop-cf" role="alert"><span class="pv-pop-cf-t">${translate('그사이 다른 곳에서 메모가 바뀌었습니다 — 지금 메모')}</span>\
<div class="pv-pop-cf-note" translate="no" tabindex="0">${session.conflict.note || translate('(빈 메모)')}</div><span class="pv-pop-acts">\
<button type="button" class="btn-ghost btn-sm hit" data-act="pv-reason-see">${translate('메모 보기')}</button>\
<button type="button" class="btn-sm hit" data-act="pv-reason-reapply" data-tip="${translate('바뀐 메모를 이 글로 바꿉니다')}">${translate('그 위에 쓰기')}</button></span></div>`
    : '';
  // never pointing at a line that says nothing (while it writes)
  const describedBy = hint && !session.writing ? html` aria-describedby="pv-pop-h-${session.sid}"` : '';
  return html`<div class="pv-pop" role="group" data-id="s${session.sid}" aria-labelledby="pv-pop-to-${session.sid}"${describedBy}>${conflictRow}\
<textarea class="pv-reason" rows="1" maxlength="4000" autocomplete="off" enterkeyhint="done" data-id="s${session.sid}" data-pin="${session.id}"${session.writing ? html` readonly aria-busy="true"` : ''} \
placeholder="${translate('이유 (선택)')}" aria-label="${translateTemplate('{who} (선택)', { who })}"${describedBy}></textarea>\
<div class="pv-pop-f"><span class="pv-pop-to" id="pv-pop-to-${session.sid}" translate="no">${who}${moved ? html`<span class="pv-pop-from"> · ${moved}</span>` : ''}</span>\
<span class="pv-pop-st${state.cls ? ' ' + state.cls : ''}" aria-live="polite">${state.cls === 'ok' ? lucideIcon('check') : ''}${state.text}</span><span class="pv-pop-h" id="pv-pop-h-${session.sid}">${hint}</span>\
<span class="pv-pop-acts">${
    replacesWholeNote(session) && session.base.trim()
      ? html`<button type="button" class="btn-ghost btn-sm pv-pop-clear hit" data-act="pv-reason-clear" \
data-tip="${translate('저장한 이유를 지웁니다. 상태 줄의 [되돌리기]가 되살립니다')}">${translate('지우기')}</button>`
      : ''
  }\
${hasUnsavedReason(session) && !session.writing && session.id ? html`<button type="button" class="btn-ghost btn-sm hit" data-act="pv-reason-fold" data-tip="${translate('초안을 둔 채 접습니다. 줄의 [초안 있음]이 다시 엽니다')}">${translate('접기')}</button>` : ''}\
<button type="button" class="btn-ghost btn-sm hit" data-act="pv-reason-close" data-tip="${translate('닫습니다. 쓰던 이유가 있으면 한 번 더 눌러야 버립니다')}">${translate('닫기')}</button>\
<button type="button" class="btn-sm pv-pop-save hit" data-act="pv-reason-save"${session.writing || session.conflict ? html` aria-disabled="true"` : ''}>${translate('저장')}</button></span></div></div>`;
}

// The reason on page `page`'s line, after its state: the saved reason of its current verdict (a check and its first
// line, .pv-rn) - a button that opens the popover to change it on the person's own open verdict, with a pencil and the
// name '저장된 이유 수정' -, then (.pv-ra) a kept draft not written yet ('초안 있음', which opens it: a folded popover,
// a failed write, a reload's other drafts, a page's draft whose verdict went) on any line, or the way to write one for
// the person's own open verdict without a reason - on the reading line and on the line of the last save
// (LAST_LINE_SAVE): after a key save, while the keys act on the line (a mouse screen), 'Enter 이유 쓰기' (Enter opens
// it, openReasonOnEnter); else [이유 추가] - a click save's. Every other line with such a verdict holds that [이유
// 추가] hidden (the identifier's way, hidden: never shown, focused or heard), which fitPageLines lays out unseen
// (#doc.pv-measure, components.css): every line is fitted as the reading line it may become, so becoming it or leaving
// it never stacks or unstacks a line. Every name holds the words the button shows. Nothing for the reason the open
// popover holds.
function inlineReason(page: number, cur: Pin | undefined) {
  const open = isReasonOpenOn(page) && !!REASON_SESSION && (!cur || REASON_SESSION.id === cur.id || !REASON_SESSION.id),
    pageDraft = open ? null : getDraft(DOC, 'p' + page);
  const sep = html`<span class="pv-sep" aria-hidden="true">·</span>`;
  const mark = html`<span class="pv-ra">${sep}<button type="button" class="btn-ghost btn-sm pv-draft hit" data-act="pv-reason-open" \
aria-label="${translate('초안 있음 — 저장 안 된 이유 초안, 누르면 이어 씁니다')}" data-tip="${translate('저장 안 된 이유 초안이 있습니다 — 누르면 이어 씁니다')}">${translate('초안 있음')}</button></span>`;
  if (!cur) return pageDraft ? mark : '';
  const mine = canCancelVerdict(cur),
    note = String(cur.note || ''),
    first = note.split('\n')[0];
  const verdictDraft = open ? null : getDraft(DOC, cur.id),
    draft = !!verdictDraft && verdictDraft.text.trim() !== note.trim();
  const ok = html`<span class="pv-ok" aria-hidden="true">${lucideIcon('check')}</span>`;
  const saved = !note
    ? ''
    : mine && !open
      ? html`<span class="pv-rn">${sep}<button type="button" class="btn-ghost btn-sm pv-note hit" data-act="pv-reason-open" translate="no" \
aria-label="${translateTemplate('{note} — 저장된 이유 수정, 판정 #{id}', { id: cur.id, note: first })}" data-tip="${translate('저장된 이유 수정')}">${ok}<span class="pv-note-t">${first}</span>${lucideIcon('pencil')}</button></span>`
      : // open: no box over the popover
        html`<span class="pv-rn">${sep}<span class="pv-note" translate="no"${open ? '' : html` data-tip="${note}"`}>${ok}${first}</span></span>`;
  // a key save: its line says the key
  const keys = KEYED_PAGE === page && LAST_KEY_SAVE === cur.id && matchMedia('(pointer:fine)').matches;
  const act =
    (draft || (pageDraft && !verdictDraft)) && mine && !open
      ? mark
      : pageDraft && !mine
        ? mark
        : !mine || open || note
          ? ''
          : READING_LINE_PAGE === page || LAST_LINE_SAVE === cur.id
            ? keys
              ? html`<span class="pv-ra">${sep}<button type="button" class="btn-ghost btn-sm pv-add hit" data-act="pv-reason-open" aria-keyshortcuts="Enter" \
data-tip="${translate('이 판정의 이유를 씁니다. 메모로 붙습니다')}"><kbd class="pv-kbd">Enter</kbd> ${translate('이유 쓰기')}</button></span>`
              : html`<span class="pv-ra">${sep}<button type="button" class="btn-ghost btn-sm pv-add hit" data-act="pv-reason-open" \
data-tip="${translate('이 판정의 이유를 씁니다. 메모로 붙습니다')}">${translate('이유 추가')}</button></span>`
            : // no data-act: no focus or press finds it
              html`<span class="pv-ra" hidden>${sep}<button type="button" class="btn-ghost btn-sm pv-add hit" tabindex="-1">${translate('이유 추가')}</button></span>`;
  return html`${saved}${act}`;
}

// After a line is drawn (fillPageLine): the open field holds the session's text - put in only when it differs and no
// input method is composing - and its height follows its lines.
function fillReasonField(line: HTMLElement) {
  const session = REASON_SESSION,
    field = findMaybe(line, '.pv-pop .pv-reason', HTMLTextAreaElement);
  if (!session || !field) return;
  if (field.value !== session.text && COMPOSING_FIELD !== field) {
    const had = document.activeElement === field;
    field.value = session.text;
    if (had) {
      const end = field.value.length;
      field.setSelectionRange(end, end);
    }
  }
  growReasonField(field);
}

// The field's height: its lines, up to its max-height (CSS), from one line.
function growReasonField(field: HTMLTextAreaElement) {
  field.style.height = 'auto';
  field.style.height = Math.ceil(field.scrollHeight + (field.offsetHeight - field.clientHeight)) + 'px';
}

// Page `page`'s line drawn again now: what its popover says follows the field's text and focus.
function refillLine(page: number) {
  const verdicts = pageVerdictsOn(),
    line = findMaybe(document, '#doc .pv[data-page="' + page + '"]', HTMLElement);
  if (verdicts && line) verdictLineRenderer().fillPageLine(line, page, pageVerdictPins().get(page), verdicts);
}

export {
  closeReasonPopover,
  fillReasonField,
  focusLine,
  focusReasonField,
  growReasonField,
  holdReasonFocus,
  inlineReason,
  reasonPopoverHtml,
  reasonTargetName,
  refillLine,
  restoreReasonFocus,
  showDraftLine,
  targetNameOn,
};
