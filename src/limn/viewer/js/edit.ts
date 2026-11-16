// ------------------------------------------------ Edit
// The active edit card and its save request share a lifetime; a dirty card may remain visible across document switches.
import { KIND_REQ, NOTICE_HOST, NOTICE_KIND, PINS, PIN_STATE, T, rendersInBrowser } from './core.ts';
import { html, ic, setHtml } from './markup.ts';
import { errText, tl, tr } from './i18n.ts';
import { api } from './api.ts';
import { bannerNote, quietNote } from './notices.ts';
import { dq, isRegion, pdoc } from './doc-tabs.ts';
import { findAnyPin } from './revisions.ts';
import { viaDoc } from './doc-switch.ts';
import { viewerBlocked } from './boot.ts';
import { pinState } from './polling.ts';
import { drawLadder, kindFor, lvOf, rangeCap, setCap, snipText, wireScope } from './levels.ts';
import { drawExcerpt } from './excerpt.ts';
import { pinPlace } from './figure.ts';
import { mdEditLevels } from './md-surface.ts';
import { editDocKind, renderEditSuggest, suggestForEdit, suggestOfPin, suggestOff, suggestRebase } from './suggest.ts';
import { qHint } from './composer.ts';
import { verdictOf } from './verdict.ts';
import { assigneeOf, isQuestion, peopleName } from './card-parts.ts';
import { drawPins, jumpPin, loadPins } from './list.ts';
import { mentionHints, mentionPreview, renderAssignEdit } from './mentions.ts';
import { segRove } from './events.ts';
const EDITOR = { current: null as EditCard | null, saving: false };
// A dirty edit card survives document switches, so only replacement or cancellation revokes its pending response.
function editorOwns(card) {
  return EDITOR.current === card;
}
/** Capture editable card values independently of its mutable range, mention hints, and controls - the suggested edit's
 * switch, text and base among them. */
function editFields(card) {
  return JSON.stringify({
    note: editNote(card).value,
    mentions: Array.from(editNote(card)._mentions || []),
    lo: card.lo,
    hi: card.hi,
    scope: card.scope,
    kind_req: card.kind_req,
    assignee: card.assignee,
    sg: { on: card.sg.on, text: card.sg.text, base: card.sg.base },
  });
}
/** Reflect the editor's shared request lifetime on whichever card is currently visible. */
function syncEditSaveButton() {
  const button = EDITOR.current && EDITOR.current.el.querySelector('.b-esave');
  if (button) (button as HTMLButtonElement).disabled = EDITOR.saving;
}
// The note field of an edit card (openEdit puts exactly one in every card).
function editNote(card: EditCard): HTMLTextAreaElement {
  return card.el.querySelector('.e-note') as HTMLTextAreaElement;
}
// Opens the edit card for pin `id` (the pin's document is switched to first) and focuses its note: builds the card
// markup, records the pin's current values as the editor's baseline (EDITOR.current, including a figure pin's element)
// and loads the snippet and range ladder. An edit already open on that pin is left as it is.
/**
 * Open an editable card with independent original mention hints, preserving the pin's identity and revision baseline.
 */
function openEdit(id) {
  if (viaDoc(id, openEdit)) return;
  const pin = PINS.find((listed) => listed.id === id);
  if (!pin) return;
  if (document.body.classList.contains('revision-open')) jumpPin(id);
  if (EDITOR.current && EDITOR.current.id === id) return;
  const cardElement = document.createElement('div');
  cardElement.className = 'edit';
  setHtml(
    cardElement,
    html`<div class="e-kind seg kind-seg" role="radiogroup" aria-label="핀 종류"><button data-act="e-kind" data-kind="fix" role="radio" data-tip="고쳐 달라는 요청">수정 요청</button>\
<button data-act="e-kind" data-kind="question" role="radio" data-tip="${T.question}">질문</button></div>\
<textarea class="e-note" rows="3" aria-label="메모 고치기" data-tip="메모를 고칩니다. ⌘ Enter / Ctrl+Enter 저장, Esc 취소"></textarea><div class="m-preview" aria-live="polite" hidden></div>\
<div class="e-qhint q-hint" role="status" hidden>${ic('circle-question-mark')}<span>질문처럼 보입니다 —</span><button data-act="e-kind" data-kind="question" data-tip="이 핀을 질문으로 바꿉니다">질문으로 보내기</button></div>\
<div class="e-assign assign-row" role="radiogroup" aria-label="담당" hidden></div>\
<div class="e-sg-row sg-row"><button class="btn-ghost sg-tg hit" role="switch" aria-checked="false" data-act="sg-toggle" \
data-tip="이 줄 범위를 바꿀 글을 직접 씁니다. 끄고 저장하면 이 핀의 제안 수정을 지웁니다"><span class="sg-sw" aria-hidden="true"></span><span class="lbl">제안 수정</span></button>\
<span class="sg-why tip-read" hidden></span></div>\
<div class="sg e-sg" hidden><textarea class="sg-text e-sg-text" rows="2" spellcheck="false" autocapitalize="off" autocomplete="off" aria-label="제안 문안" \
placeholder="이 줄들을 바꿀 글 (비우면 이 줄들을 지웁니다)" data-tip="이 줄 범위를 바꿀 글입니다. ⌘ Enter / Ctrl+Enter 저장, Esc 취소"></textarea>\
<div class="sg-note q-hint" aria-live="polite" hidden></div><div class="sg-cc q-hint" aria-live="polite" hidden></div><div class="sg-cur" hidden></div></div>\
<div class="e-sg-ro" hidden></div>\
<div class="rg-cap e-cap" aria-live="polite" aria-atomic="true"></div>\
<div class="e-levels seg lad" role="radiogroup" aria-label="범위" data-rungs="0" tabindex="-1"></div>\
<div class="xp e-xp" hidden></div>\
<pre class="e-snip wrap" translate="no">${tr('원문 읽는 중…')}</pre>\
<div class="e-acts"><button class="btn-sm b-repick" data-act="repick" data-tip="${T.repick}">위치 다시 잡기</button>\
<button class="btn-sm b-ecancel" data-act="ecancel" data-tip="${T.ecancel}">취소</button>\
<button class="btn-sm btn-default b-esave" data-act="esave" data-tip="${T.esave}">저장</button></div>`,
  );
  const noteField = cardElement.querySelector('.e-note') as HTMLTextAreaElement;
  noteField.value = pin.note || '';
  noteField._mentions = new Set(pin.mentions || []);
  autoGrow(noteField);
  mentionPreview(noteField);
  EDITOR.current = {
    id,
    el: cardElement,
    base_rev: pin.rev || 0,
    file: pin.file,
    name:
      pin.name ||
      String(pin.file || pin.pdf || '')
        .split('/')
        .pop() ||
      '',
    lo: pin.lo,
    hi: pin.hi,
    scope: pin.scope || null,
    kind: pin.kind,
    env: null,
    levels: [],
    n_lines: null,
    snippet: '',
    orig: {
      lo: pin.lo,
      hi: pin.hi,
      scope: pin.scope || null,
      note: pin.note || '',
      mentions: mentionHints(noteField),
      kind_req: isQuestion(pin) ? KIND_REQ.QUESTION : KIND_REQ.FIX,
      assignee: assigneeOf(pin),
    },
    assignee: assigneeOf(pin),
    doc: pdoc(pin),
    region: isRegion(pin),
    pinEl: pin.el || null,
    page: pinPlace(pin).page,
    quote: pin.quote || '',
    kind_req: isQuestion(pin) ? KIND_REQ.QUESTION : KIND_REQ.FIX,
    sg: suggestOfPin(pin),
  };
  if (EDITOR.current.region) cardElement.classList.add('region');
  // a verdict pin keeps its verdict and target (D3): only the note and the assignee are edited
  if (verdictOf(pin)) cardElement.classList.add('verdict');
  drawPins();
  renderEdit();
  noteField.focus();
  editSnip(true);
}
// Does the edit field have unsaved changes (whether it's safe to close the edit when switching documents)?
/**
 * Report unsaved note, mention hints, range, scope, kind, assignee or suggested-edit changes before a card may close or
 * change documents.
 */
function editDirty() {
  const card = EDITOR.current;
  if (!card) return false;
  const noteField = editNote(card);
  return (
    (noteField && noteField.value !== card.orig.note) ||
    JSON.stringify(mentionHints(noteField)) !== JSON.stringify(card.orig.mentions || []) ||
    card.lo !== card.orig.lo ||
    card.hi !== card.orig.hi ||
    (card.scope || null) !== (card.orig.scope || null) ||
    card.kind_req !== card.orig.kind_req ||
    card.assignee !== card.orig.assignee ||
    suggestForEdit(card.sg, suggestOff(card, editDocKind(card))) !== undefined
  );
}
function autoGrow(field) {
  field.style.height = 'auto';
  const lineHeight = 20;
  field.style.height = Math.min(12 * lineHeight, Math.max(3 * lineHeight, field.scrollHeight + 2)) + 'px';
}
document.addEventListener('input', (event) => {
  const target = event.target as HTMLElement;
  if (
    target.classList &&
    (target.classList.contains('e-note') || target.classList.contains('r-text') || target.id === 'note')
  )
    autoGrow(target);
});
async function editSnip(withLevels) {
  const card = EDITOR.current;
  if (!card) return;
  if (card.region) {
    card.snippet = card.quote ? tl('영역 글자: {text}', { text: card.quote }) : tr('(영역 글자 없음)');
    renderEdit();
    return;
  } // view-only: there is no source line
  try {
    const { status, data } = await api(
      dq(
        '/api/snippet?file=' +
          encodeURIComponent(String(card.file)) +
          '&lo=' +
          card.lo +
          '&hi=' +
          card.hi +
          (withLevels ? '&levels=1' : ''),
        card.doc,
      ),
      { what: '원문 읽기', expect: [400] },
    );
    if (EDITOR.current !== card) return;
    if (status === 400) {
      card.snippet = tr('원문을 읽지 못했습니다') + ' — ' + errText(data) + '\n' + tr('위치 다시 잡기로 고치세요.');
      renderEdit();
      return;
    }
    card.snippet = data.snippet;
    card.n_lines = data.n_lines;
    // a Markdown pin's rungs come from the drawn document
    const markdownRungs = withLevels && rendersInBrowser(editDocKind(card)) ? mdEditLevels(card) : null;
    if (markdownRungs) card.levels = markdownRungs;
    else if (withLevels && data.levels && !rendersInBrowser(editDocKind(card))) {
      card.levels = data.levels;
      if (!card.scope || !lvOf(card, card.scope)) {
        const matching = card.levels.find((rung) => rung.lo === card.lo && rung.hi === card.hi);
        if (matching && !card.scope) card.scope = null;
      }
    }
    renderEdit();
  } catch (error) {}
}
// Draws the open edit card from EDITOR.current: the kind, the range caption (a region's page and area instead), the
// ladder - shown only with two or more rungs - the range excerpt (a region's text in the plain source) and the assignee
// and question hints.
/**
 * Draw current editable fields and their save availability, including a card opened while an earlier edit is pending.
 */
function renderEdit() {
  const card = EDITOR.current;
  if (!card) return;
  const cardElement = card.el;
  syncEditSaveButton();
  (cardElement.querySelectorAll('.e-kind button') as NodeListOf<HTMLElement>).forEach((button) => {
    const on = button.dataset.kind === (card.kind_req || KIND_REQ.FIX);
    button.classList.toggle('on', on);
    button.setAttribute('aria-checked', String(on));
  });
  segRove(cardElement.querySelector('.e-kind')); // the group's one Tab stop is the kind now chosen (events.ts)
  setCap(
    cardElement.querySelector('.e-cap'),
    card.region
      ? html`<span class="e-range loc" tabindex="0" data-copy="${card.name + ' 쪽 ' + card.page}">${tl('쪽 {page} · 영역', { page: card.page })}</span>`
      : rangeCap(card, true),
  );
  drawLadder(cardElement.querySelector('.e-levels'), card, true);
  const pre = cardElement.querySelector('.e-snip') as HTMLElement;
  pre.className = 'e-snip wrap';
  pre.textContent = snipText(card.snippet, false);
  renderAssignEdit();
  drawExcerpt(card, cardElement.querySelector('.e-xp'), true);
  renderEditSuggest(card); // the [제안 수정] switch and its editor (suggest.ts); a closed pin's suggestion read-only
  qHint(cardElement.querySelector('.e-qhint'), editNote(card).value, card.kind_req);
  const pin = findAnyPin(card.id),
    closed = !!pin && pinState(pin) !== PIN_STATE.OPEN;
  (cardElement.querySelector('.b-repick') as HTMLElement).hidden = closed;
  if (closed) {
    (cardElement.querySelector('.e-levels') as HTMLElement).hidden = true;
    (cardElement.querySelector('.e-xp') as HTMLElement).hidden = true;
  }
}
function cancelEdit() {
  EDITOR.current = null;
  drawPins();
}
// Saves the open edit card (POST /api/pins/<id>/edit with `base_rev`): only what changed is sent - the note and its
// hints, the kind, the assignee, the suggested edit (suggestForEdit: set, replaced, or null to remove it) and, when the
// lines or the ladder rung moved, lo/hi with scope and kind. Nothing changed just closes the card. On 409
// suggest_base_changed nothing was saved: the card keeps its draft, shows the lines' current text against it and the
// banner offers [지금 원문으로 맞추기]. On 409 for a closed pin (error===done), the card retains its note against the
// latest stored range and a warning banner says only the note can still be changed; on any other 409 (a rival edit) the
// card adopts the stored pin's rev, range, scope, file and element, and a banner says so. A saved edit is silent (the
// card shows it; read out only). Always reloads the pins. A viewer role and a save already under way send nothing.
/**
 * Submit one edit revision, including hint-only changes; later input keeps the card open against the successful
 * response's baseline.
 */
async function saveEdit() {
  const card = EDITOR.current;
  if (!card || EDITOR.saving || viewerBlocked()) return;
  const note = editNote(card).value,
    body: {
      base_rev: number;
      note?: string;
      kind_req?: string;
      assignee?: string;
      mentions?: ReturnType<typeof mentionHints>;
      lo?: number;
      hi?: number;
      scope?: ReturnType<typeof wireScope>;
      kind?: ReturnType<typeof kindFor>;
      suggest?: ReturnType<typeof suggestForEdit>;
    } = { base_rev: card.base_rev };
  if (
    note !== card.orig.note ||
    JSON.stringify(mentionHints(editNote(card))) !== JSON.stringify(card.orig.mentions || [])
  )
    body.note = note;
  // A rival edit changed the note since the card opened (theirs, shown in the banner): the card's note is not saved
  // over it until the person chooses [내 메모로 덮어쓰기] - otherwise a second [저장] would write over an agent's
  // addition unseen.
  if (body.note !== undefined && card.theirs != null && !card.overwrite && card.theirs !== note) {
    editTheirs(card);
    return;
  }
  if (card.kind_req && card.kind_req !== card.orig.kind_req) body.kind_req = card.kind_req;
  if (card.assignee && card.assignee !== card.orig.assignee) body.assignee = card.assignee;
  if (body.note !== undefined) {
    const noteHints = mentionHints(editNote(card));
    if (noteHints.length) body.mentions = noteHints;
  }
  // A figure pin's ladder here is raw/lines only (no element rungs): a rung press alone would trade the element's kind
  // for 'lines', so only changed lines are sent; the pin keeps its el either way (a range edit is not a loc).
  if (
    card.lo !== card.orig.lo ||
    card.hi !== card.orig.hi ||
    (!card.pinEl && (card.scope || null) !== (card.orig.scope || null))
  ) {
    body.lo = card.lo;
    body.hi = card.hi;
    if (card.scope) {
      body.scope = wireScope(card.scope);
      body.kind = kindFor(card.scope, card.env);
    }
  }
  const suggestion = suggestForEdit(card.sg, suggestOff(card, editDocKind(card)));
  if (suggestion !== undefined) body.suggest = suggestion;
  if (Object.keys(body).length === 1) {
    cancelEdit();
    return;
  }
  const fields = editFields(card),
    hints = mentionHints(editNote(card));
  EDITOR.saving = true;
  syncEditSaveButton();
  try {
    const { status, data } = await api('/api/pins/' + card.id + '/edit', {
      method: 'POST',
      body,
      what: '핀 수정',
      where: NOTICE_HOST.LIST,
      expect: [409],
      intent: 'edit',
    });
    if (status === 409) {
      if (data && data.reason === 'suggest_base_changed') {
        editSuggestRefused(card, data);
        return;
      }
      if (data && data.error === PIN_STATE.DONE) {
        bannerNote(
          NOTICE_HOST.LIST,
          tl('핀 #{id} 은 이미 닫혀 범위를 바꿀 수 없습니다 — 메모만 고칠 수 있습니다', { id: card.id }),
          NOTICE_KIND.WARN,
        );
        if (editorOwns(card)) {
          const pin = data.pin;
          card.base_rev = pin.rev;
          card.lo = pin.lo;
          card.hi = pin.hi;
          card.scope = pin.scope || null;
          card.file = pin.file;
          card.pinEl = pin.el || null;
          card.orig = {
            lo: pin.lo,
            hi: pin.hi,
            scope: pin.scope || null,
            note: pin.note || '',
            mentions: (pin.mentions || []).filter((login) => (pin.note || '').includes('@' + peopleName(login))),
            kind_req: isQuestion(pin) ? KIND_REQ.QUESTION : KIND_REQ.FIX,
            assignee: assigneeOf(pin),
          };
          editSnip(true);
        }
        await loadPins();
        return;
      }
      const pin = data.pin,
        theirs = String(pin.note || ''),
        changed = theirs !== card.orig.note && body.note !== undefined;
      if (changed && editorOwns(card)) {
        card.theirs = theirs;
        card.overwrite = false;
      }
      if (changed) editTheirs(card);
      else
        bannerNote(
          NOTICE_HOST.LIST,
          '다른 쪽(에이전트나 자동 줄 맞춤)이 이 핀을 먼저 바꿨습니다 — 최신 위치를 불러왔습니다',
          NOTICE_KIND.WARN,
        );
      if (editorOwns(card)) {
        // a suggestion being changed is kept; else the stored one is taken
        const keep = suggestForEdit(card.sg, suggestOff(card, editDocKind(card))) !== undefined;
        card.base_rev = pin.rev;
        card.lo = pin.lo;
        card.hi = pin.hi;
        card.scope = pin.scope || null;
        card.file = pin.file;
        card.pinEl = pin.el || null;
        if (keep) card.sg.had = pin.suggest ? { base: pin.suggest.base, text: pin.suggest.text } : null;
        else card.sg = suggestOfPin(pin);
        card.orig = {
          lo: pin.lo,
          hi: pin.hi,
          scope: pin.scope || null,
          note: pin.note || '',
          mentions: (pin.mentions || []).filter((login) => (pin.note || '').includes('@' + peopleName(login))),
          kind_req: card.orig.kind_req,
          assignee: assigneeOf(pin),
        };
        editSnip(true);
      }
      await loadPins();
      return;
    }
    if (editorOwns(card)) {
      card.theirs = null;
      card.overwrite = false;
      if (editFields(card) === fields) EDITOR.current = null;
      else {
        const pin = data.pin;
        card.base_rev = pin.rev;
        card.orig = {
          lo: pin.lo,
          hi: pin.hi,
          scope: pin.scope || null,
          note: pin.note || '',
          mentions: hints.slice(),
          kind_req: isQuestion(pin) ? KIND_REQ.QUESTION : KIND_REQ.FIX,
          assignee: assigneeOf(pin),
        };
        card.sg.had = pin.suggest ? { base: pin.suggest.base, text: pin.suggest.text } : null;
      }
    }
    quietNote(tl('핀 #{id} 수정됨', { id: card.id }));
    await loadPins();
  } catch (error) {
  } finally {
    EDITOR.saving = false;
    syncEditSaveButton();
  }
}
// A rival edit wrote another note while the card was open (card.theirs): the banner shows that note whole and offers
// [내 메모로 덮어쓰기]; the card keeps the person's text, and [저장] alone does not write over theirs.
function editTheirs(card: EditCard) {
  const theirs = card.theirs == null ? '' : card.theirs;
  bannerNote(
    NOTICE_HOST.LIST,
    tl('핀 #{id} 메모를 저장하지 않았습니다 · 그사이 다른 곳에서 메모가 바뀌었습니다', { id: card.id }) +
      ' — ' +
      tl('지금 메모: {note}', { note: theirs || tr('(빈 메모)') }),
    NOTICE_KIND.WARN,
    {
      label: '내 메모로 덮어쓰기',
      tip: '지금 메모를 읽은 뒤, 카드의 메모로 바꿉니다',
      fn: () => {
        if (!editorOwns(card)) return;
        card.overwrite = true;
        saveEdit();
      },
    },
    { source: 'POST /api/pins/' + card.id + '/edit edit', literal: true },
  );
}
// An edit the server answered 409 suggest_base_changed: nothing was saved and the card keeps its draft. The editor
// shows the lines' current text against the draft and the list's banner offers [지금 원문으로 맞추기] (the draft keeps
// its text and takes that text as its base); then [저장] again.
function editSuggestRefused(card: EditCard, data: any) {
  if (editorOwns(card)) {
    card.sg.current = {
      text: String(data.current || ''),
      file: card.file || null,
      lo: card.lo as number,
      hi: card.hi as number,
    };
    renderEdit();
  }
  bannerNote(
    NOTICE_HOST.LIST,
    tl('핀 #{id} 수정 실패', { id: card.id }) + ' — ' + tr('그사이 그 줄들의 원문이 바뀌었습니다'),
    NOTICE_KIND.ERR,
    {
      label: '지금 원문으로 맞추기',
      tip: '쓰던 글은 그대로 두고, 이 제안이 바꿀 원문을 지금 그 줄들의 글로 바꿉니다. 그다음 다시 저장합니다',
      fn: () => {
        if (editorOwns(card))
          suggestRebase(
            card.sg,
            card,
            () => editorOwns(card),
            () => {
              if (editorOwns(card)) renderEditSuggest(card);
            },
          );
      },
    },
    { source: 'POST /api/pins/' + card.id + '/edit edit' },
  );
}
export { EDITOR, autoGrow, cancelEdit, editDirty, editNote, editSnip, openEdit, renderEdit, saveEdit };
