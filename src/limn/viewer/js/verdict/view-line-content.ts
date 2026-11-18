import { pinState, verdictOf } from '../app/rules-pins.ts';
import { PIN_STATE, VERDICT_PLACE } from '../app/rules-tables.ts';
import { isMe, who } from '../app/state-people.ts';
import { isFigureKind, META, DOC } from '../app/state.ts';
import { verdictLabel } from '../documents/state.ts';
import { PINS_APPLIED_SEQ } from '../pins/flow-list.ts';
import { claimActive } from '../pins/view-card-parts.ts';
import { relSpan } from '../pins/view-time.ts';
import { translateTemplate, translate } from '../platform/i18n.ts';
import { html } from '../platform/markup.ts';
import { NOTICES } from '../platform/notices.ts';
import { ARMED_VERDICT, PRESSED_AS, pressedAsOf, verdictButton } from './flow-words.ts';
import {
  pageLineSlot,
  NEXT_PRESS,
  SAVING_LINES,
  CANCEL_HOLD,
  READING_LINE_PAGE,
  KEYED_PAGE,
  TAKEN_BACK_HOLD,
  LINE_SAVE_ERROR,
  LINE_UNDO_OFFERS,
} from './state-lines.ts';
import { verdictStateWord, VERDICT_ARM_MS, canCancelVerdict, pageLineName, canVerdict } from './view-pins.ts';
import { isReasonField } from './view-reason-field.ts';
import { inlineReason, reasonPopoverHtml } from './view-reason.ts';

// One page's line: its state - '판정 없음', or the newest verdict pin about its target with its state, its number and
// word, and who made it and when if that was someone else - its reason (inlineReason: a check and its first line, a
// kept draft, [이유 추가]), [판정 취소] on the person's own while it is open (canCancelVerdict), the earlier open
// verdicts as a link ('이전 판정 N건 · 새 판정으로 대체됨'), and, for a person who may make one, a button per word. The
// current verdict's word is pressed (a toggle, pressPageVerdict); while a save on the line is out, the word it saves -
// or the last one pressed meanwhile (NEXT_PRESS) - is pressed instead and the state says '보류 저장 중…'. The reason
// popover (reasonPopoverHtml) is the line's last child, laid above it.
/**
 * @param [chip] - the line holds a save chip or its reason popover: it draws no descriptions @param [panel] - the panel
 * beside the pages (verdict/view-panel.ts)
 */
function pageLineHtml(page: number, list: Pin[] | undefined, verdicts: DocVerdicts, chip?: boolean, panel?: boolean) {
  const cur = list && list[0],
    earlier = list ? list.slice(1).filter((pin) => pinState(pin) === PIN_STATE.OPEN) : [];
  // Before the first pin list is applied (PINS_APPLIED_SEQ) the line knows no verdict yet: '판정 읽는 중…', buttons
  // waiting.
  const loading = !PINS_APPLIED_SEQ;
  const key = cur && verdictOf(cur),
    other = !!cur && !!cur.author && !isMe(cur.author);
  // One order for every state: '판정 #4 채택 · 처리 대기', then who made it and when if someone else did. The number is
  // a link to the card (the viewer's link style), the word is bold. A claimed one names who has it: '처리 중(Agent B)'
  // - the name after it is the pin's author.
  const mark = '\u0001',
    by = cur && pinState(cur) === PIN_STATE.OPEN && claimActive(cur) && cur.claimed_by ? who(cur.claimed_by) : '',
    state = cur ? verdictStateWord(cur) : '',
    parts = by ? translateTemplate('처리 중({name})', { name: mark }).split(mark) : [state];
  const text =
    cur && key
      ? html`<span class="pv-s">${translate('판정')} <span class="pin-ref pv-ref hit" role="link" tabindex="0" data-act="pin-ref" data-ref="${cur.id}" \
aria-label="${translateTemplate('지금 판정 #{id} 카드로 갑니다', { id: cur.id })}" data-tip="${translateTemplate('핀 #{id} 로 갑니다', { id: cur.id })}">#${cur.id}</span> <b class="vd-w" translate="no">${verdictLabel(key)}</b></span>\
<span class="pv-sep" aria-hidden="true">·</span><span class="pv-st">${parts[0]}${by ? html`<span class="pv-by" translate="no">${by}</span>${parts[1] || ''}` : ''}</span>\
${other ? html`<span class="pv-sep" aria-hidden="true">·</span><span class="pv-au" translate="no">${who(cur.author)}</span> ${relSpan(cur.at, 'pv-at', '')}` : ''}\
${inlineReason(page, cur)}`
      : html`<span class="pv-s pv-none">${translate(loading ? '판정 읽는 중…' : '판정 없음')}</span>${loading ? '' : inlineReason(page, undefined)}`;
  // A save on the line that is out: what it saves - or the last word pressed meanwhile, which comes after it.
  const slot = pageLineSlot(page),
    next = NEXT_PRESS.get(slot),
    savingKey = SAVING_LINES.get(slot),
    want = next ? next.key : savingKey !== undefined ? savingKey : key || null;
  const saving =
    savingKey !== undefined
      ? html`<span class="pv-busy" role="status"><span class="pv-sep" aria-hidden="true">·</span> ${translateTemplate('{word} 저장 중…', { word: verdictLabel(want || savingKey) })}</span>`
      : '';
  // A confirm word armed on this line says how long it waits, beside it.
  const armed =
    !!ARMED_VERDICT && ARMED_VERDICT.where === VERDICT_PLACE.PAGE && ARMED_VERDICT.page === page ? ARMED_VERDICT : null;
  const armSay = armed
    ? html`<span class="pv-arm"><span class="pv-sep" aria-hidden="true">·</span> ${translateTemplate('{sec}초 안에 한 번 더 누르면 저장', { sec: VERDICT_ARM_MS / 1000 })}</span>`
    : '';
  // [판정 취소]: a text action in the row (the viewer's link look, as the earlier link), after the state. It is its
  // verdict's own element (data-id): once that verdict goes the next one's is a new one, which a keyboard focus does
  // not carry over. It waits (aria-disabled) while the page's save is out, the first list is not in, or a cancel on
  // this page just ran.
  const canCancel = !!cur && canCancelVerdict(cur),
    cancelWaits = SAVING_LINES.has(slot) || loading || (CANCEL_HOLD.get(slot) || 0) > Date.now();
  const cancel =
    canCancel && cur
      ? html`<span class="pv-sep pv-cn" aria-hidden="true">·</span><button type="button" class="btn-ghost btn-sm pv-cancel pv-cn hit" data-act="pv-cancel" \
data-ref="${cur.id}" data-id="${cur.id}" aria-label="${translateTemplate('판정 취소 — 내 판정 #{id}', { id: cur.id })}" \
${lineTipAttribute(!!chip, translate('이 판정을 거둡니다. 핀은 휴지통으로 가고, 같은 대상에 앞선 판정이 있으면 그 판정이 다시 지금 판정이 됩니다. 상태 줄의 [되돌리기]가 되살립니다'))}${cancelWaits ? html` aria-disabled="true"` : ''}>${translate('판정 취소')}</button>`
      : '';
  // The earlier link is short - '이전 2건' ('+2 earlier') - and never cut: where its line is tight (.pv-tight,
  // fitPageLines) it is its count alone, '+2' (data-n, components.css). Its name says it whole ('이전 판정 2건 · 새
  // 판정으로 대체됨'), and so does its tooltip before what it is; the whole words would stand in the row and be cut to
  // fit. A dot sets it off from what comes before it, as the state's other parts are (.pv-ea, gone whenever the link
  // is): right after [✓ 채택 1]'s key digit on a stacked line, or after [판정 취소], a bare '+2' would read as a count
  // of that button's.
  const earlierCount = earlier.length,
    earlierName = translateTemplate('이전 판정 {n}건 · 새 판정으로 대체됨', { n: earlierCount });
  const early = earlierCount
    ? html`<span class="pv-sep pv-ea" aria-hidden="true">·</span><button type="button" class="btn-ghost btn-sm pv-early hit" data-act="pv-earlier" data-ref="${earlier[0].id}" data-n="${earlierCount}" aria-label="${earlierName}" \
${lineTipAttribute(!!chip, earlierName + ' — ' + translate('이 쪽의 더 새 판정으로 대체되어 실행하지 않는 열린 판정 핀입니다. 누르면 그 카드로 갑니다'))}><span class="pv-early-w">${translateTemplate('이전 {n}건', { n: earlierCount })}</span></button>`
    : '';
  // The reading page's line - the one that floats - names what it decides: '7쪽 · [후보] PL18 · …' (figureName), cut to
  // fit. Its two spans are on every line, hidden but on the reading one: the line's children keep their places when the
  // reading page moves, so the morph (morphNode) never takes a focused button out of the page. A hidden one holds the
  // identifier, so every line is fitted as the reading line it may become (fitPageLines). The panel beside the pages
  // (verdict/view-panel.ts) names its page and figure whole: the title on rows of its own under the identifier, kept
  // even when empty, so the words below stand at one height for every page. A view-only PDF has no titles.
  const isReadingLine = READING_LINE_PAGE === page || !!panel,
    lineName = isReadingLine ? pageLineName(page) : { id: pageLineName(page).id, rest: '' };
  const name = panel
    ? html`<span class="pv-fig" translate="no"><span class="pv-fig-id">${lineName.id}</span>${isFigureKind(META ? META.kind : undefined) ? html`<span class="pv-fig-t">${lineName.rest}</span>` : ''}</span><span class="pv-sep pv-fig-sep" aria-hidden="true">·</span>`
    : html`<span class="pv-fig" translate="no"${isReadingLine ? '' : html` hidden`}><span class="pv-fig-id">${lineName.id}</span>${lineName.rest ? html`<span class="pv-fig-t">${' · ' + lineName.rest}</span>` : ''}</span><span class="pv-sep pv-fig-sep" aria-hidden="true"${isReadingLine ? '' : html` hidden`}>·</span>`;
  const keys = KEYED_PAGE === page,
    target = translateTemplate('{page}쪽', { page }),
    held = TAKEN_BACK_HOLD.get(slot),
    hold = held && held.until > Date.now() ? held.key : null;
  const pressedFor = (key: string) =>
    key !== want
      ? PRESSED_AS.NONE
      : next || savingKey !== undefined
        ? PRESSED_AS.SAVING
        : cur
          ? pressedAsOf(cur)
          : PRESSED_AS.NONE;
  // In the panel the pressed word's description is its context under the panel (pressedWordHint): a hover box over it
  // as well would cover the page's name above the words and say the same again. Only a long press shows it
  // (verdictButton's quiet).
  const said = (key: string) => !!panel && pressedFor(key) !== PRESSED_AS.NONE && pressedFor(key) !== PRESSED_AS.SAVING;
  const buttons = canVerdict()
    ? html`<span class="vd-btns">${verdicts.choices.map((choice, index) => verdictButton(choice, VERDICT_PLACE.PAGE, page, target, loading || choice.key === hold, keys ? index + 1 : 0, !!chip || said(choice.key), pressedFor(choice.key)))}</span>`
    : '';
  // The line's last failed save, said where it was pressed (LINE_SAVE_ERROR) - for the document and build on screen
  // only.
  const failure = LINE_SAVE_ERROR.get(page),
    failureShown = !!failure && failure.doc === DOC && !!META && failure.build === (META.pages_build || '');
  // always there, so the reason field after it keeps its place
  const err = html`<span class="pv-err"${failureShown ? '' : html` hidden`}>${failureShown && failure ? failure.text : ''}</span>`;
  // A take-back of this line's, while its status-line [되돌리기] lasts: the line offers it too (LINE_UNDO_OFFERS).
  const lineUndo = LINE_UNDO_OFFERS.get(slot),
    undo =
      lineUndo && NOTICES.has(lineUndo.n) && canVerdict()
        ? html`<span class="pv-sep pv-un" aria-hidden="true">·</span><button type="button" class="btn-ghost btn-sm pv-undo pv-un hit" \
data-act="pv-undo" data-id="u${lineUndo.id}" aria-label="${translateTemplate('되돌리기 — 거둔 판정 #{id}', { id: lineUndo.id })}">${translate('되돌리기')}</button>`
        : '';
  if (lineUndo && !undo) LINE_UNDO_OFFERS.delete(slot);
  const hint = pressedWordHint(
    page,
    verdicts,
    want,
    next || savingKey !== undefined ? PRESSED_AS.SAVING : cur ? pressedAsOf(cur) : PRESSED_AS.NONE,
  );
  // In the panel the words come right under the name - one place on the screen for every page, whatever the state under
  // them says - and the Tab order follows the rows: the words, then the state's links and actions.
  if (panel)
    return html`${name}${buttons}<span class="pv-t">${text}${saving}${armSay}${cancel}${undo}${early}</span>${err}${hint}${reasonPopoverHtml(page)}`;
  return html`${name}<span class="pv-t">${text}${saving}${armSay}${cancel}${undo}${early}</span>${buttons}${err}${hint}${reasonPopoverHtml(page)}`;
}

// A line control's description: data-tip, or - on a line that holds a save chip or its reason popover (pageLineHtml
// chip) - data-tip-press, which only a long press shows (platform/tooltip.ts): no box over either, and a long press
// still presses nothing.
function lineTipAttribute(quiet: boolean, tip: string) {
  return quiet ? html`data-tip-press="${tip}"` : html`data-tip="${tip}"`;
}

// The pressed word's context (taking a verdict back by pressing its word again must be found without a hover - a line
// holding a save chip or a popover draws no descriptions, and touch has none): one short sentence, the pressed word's
// description for assistive technology (aria-describedby="pv-on-<page>") and shown over the word group - never in the
// line's flow, so the line keeps its height - while the pressed word is hovered or has the keyboard's focus, and for a
// few seconds after a press made it the line's verdict (.pv-onshow, showPressedHint). '지금 삭제 판정 · 다시 누르면
// 판정 취소' on the person's own open verdict; someone else's or a handled one says it stays.
function pressedWordHint(page: number, verdicts: DocVerdicts, key: string | null, pressed: number) {
  const choice = key ? verdicts.choices.find((x) => x.key === key) : null;
  if (!choice || !pressed || pressed === PRESSED_AS.SAVING || !canVerdict()) return '';
  const say =
    pressed === PRESSED_AS.MINE
      ? translateTemplate('지금 {word} 판정 · 다시 누르면 판정 취소', { word: choice.label })
      : pressed === PRESSED_AS.OTHER
        ? translateTemplate('지금 {word} 판정 · 다른 사람의 판정이라 그대로 둡니다', { word: choice.label })
        : translateTemplate('지금 {word} 판정 · 처리된 판정이라 그대로 둡니다', { word: choice.label });
  return html`<span class="pv-onhint" id="pv-on-${page}" translate="no">${say}</span>`;
}

// Makes the target's children the source's, keeping every node that is the same kind in the same place (morphNode). The
// child that is or holds the reason field stays where it is when the source has the same one anywhere: the nodes before
// and after it are made the source's on either side of it. By place alone a node new before it (the pressed word's
// context, once the save the popover waited for lands) would take its place and the field would be drawn again, which
// ends an input method's composition in it and loses the typed reason.
function morphChildren(target: Node, source: Node) {
  const targetChildren = [...target.childNodes],
    sourceChildren = [...source.childNodes],
    fieldAt = targetChildren.findIndex(holdsReasonField),
    sourceFieldAt = fieldAt < 0 ? -1 : sourceChildren.findIndex((node) => canMorph(targetChildren[fieldAt], node));
  if (sourceFieldAt < 0) {
    morphChildRun(target, targetChildren, sourceChildren, null);
    return;
  }
  morphChildRun(
    target,
    targetChildren.slice(0, fieldAt),
    sourceChildren.slice(0, sourceFieldAt),
    targetChildren[fieldAt],
  );
  morphNode(targetChildren[fieldAt], sourceChildren[sourceFieldAt]);
  morphChildRun(target, targetChildren.slice(fieldAt + 1), sourceChildren.slice(sourceFieldAt + 1), null);
}

// Makes a run of the parent's children (targetRun) read as sourceRun, by place: the new nodes past its end go in before
// `at` (null: at the end), and the old ones past the source run's end go.
function morphChildRun(parent: Node, targetRun: ChildNode[], sourceRun: ChildNode[], at: Node | null) {
  sourceRun.forEach((node, index) => {
    if (index < targetRun.length) morphNode(targetRun[index], node);
    else parent.insertBefore(node, at);
  });
  targetRun.slice(sourceRun.length).forEach((node) => node.remove());
}

// Whether a node is the reason field or holds it.
function holdsReasonField(node: Node) {
  return node instanceof Element && (isReasonField(node) || !!node.querySelector('.pv-reason'));
}

// Whether morphNode keeps a target node to read as the source node: the same kind of node - for an element the same
// tag, data-act and data-id (a reason field of another pin is another field, never one keeping the first pin's typed
// text).
function canMorph(target: Node, source: Node) {
  return (
    target.nodeType === source.nodeType &&
    target.nodeName === source.nodeName &&
    !(
      target instanceof Element &&
      source instanceof Element &&
      (target.getAttribute('data-act') !== source.getAttribute('data-act') ||
        target.getAttribute('data-id') !== source.getAttribute('data-id'))
    )
  );
}

// Makes a target node read as the source node: the same text, or the same element (canMorph) with the source's
// attributes and children; another kind of node takes the target's place.
function morphNode(target: Node, source: Node) {
  if (!canMorph(target, source)) {
    if (target instanceof Element || target instanceof CharacterData) target.replaceWith(source);
    return;
  }
  if (!(target instanceof Element && source instanceof Element)) {
    if (target.nodeValue !== source.nodeValue) target.nodeValue = source.nodeValue;
    return;
  }
  [...target.attributes].forEach((x) => {
    if (!source.hasAttribute(x.name)) target.removeAttribute(x.name);
  });
  [...source.attributes].forEach((x) => {
    if (target.getAttribute(x.name) !== x.value) target.setAttribute(x.name, x.value);
  });
  morphChildren(target, source);
}

export { morphChildren, pageLineHtml };
