import { pinState, lineRange } from '../app/rules-pins.ts';
import { VERDICT_PLACE, PIN_STATE, REQUEST_KIND } from '../app/rules-tables.ts';
import { COMPOSE, DOC, META, imeKey, isFigureKind, KIND_NEW, setComposeRetryVerdict } from '../app/state.ts';
import { SUGGEST_DRAFT } from '../composer/state-suggest.ts';
import { isRegion, docKindOf, docVerdicts } from '../documents/state.ts';
import { figureFields } from '../pdf/view-figure.ts';
import { CONFIRMING } from '../pins/state.ts';
import { $, eventClosest, findMaybe, focusedElement } from '../platform/dom.ts';
import { translateTemplate, translate } from '../platform/i18n.ts';
import { html, lucideIcon, setHtml } from '../platform/markup.ts';
import { announce, BANNERS, bannerNote } from '../platform/notices.ts';
import { NOTICE_HOST, NOTICE_KIND } from '../platform/tables.ts';
import { hideTip, SWALLOW_CLICK } from '../platform/tooltip.ts';
import { verdictLineRenderer } from './state-line-renderer.ts';
import { fitWrappedWords } from './view-line.ts';
import {
  VERDICT_ARM_MS,
  canCancelVerdict,
  WHOLE_PAGE,
  canVerdict,
  pageTakesVerdict,
  figureShort,
} from './view-pins.ts';

// ---------------- Two presses for a confirm word (D9)
// The armed first press: the word, where (VERDICT_PLACE) and - on a page line - the page, with the document, build and
// (in the composer) selection it is bound to; null when nothing is armed.
let ARMED_VERDICT: {
  key: string;
  label: string;
  where: string;
  page: number;
  doc: string | null;
  build: string;
  sel: string;
  kbd: boolean;
  timer: ReturnType<typeof setTimeout>;
} | null = null;

// What the composer's selection is, for the binding: its page, lines, rung, box and element.
function selectionBindingKey() {
  const selection = COMPOSE.current;
  return selection
    ? JSON.stringify([
        selection.page,
        selection.lo,
        selection.hi,
        selection.scope,
        selection.frac,
        selection.elSel && selection.elSel.id,
      ])
    : '';
}

// Whether the armed press is this word's button.
function isArmedHere(key: string, where: string, page: number) {
  const armed = ARMED_VERDICT;
  return (
    !!armed && armed.key === key && armed.where === where && (where === VERDICT_PLACE.COMPOSER || armed.page === page)
  );
}

// Whether an armed press still holds: the same document, build and (in the composer) selection.
function armStillHolds(armed: NonNullable<typeof ARMED_VERDICT>) {
  return (
    armed.doc === DOC &&
    !!META &&
    armed.build === META.pages_build &&
    (armed.where !== VERDICT_PLACE.COMPOSER || armed.sel === selectionBindingKey())
  );
}

// What an armed word says while it waits, with how long it waits: '삭제 — 4초 안에 한 번 더 누르면 저장합니다'.
function armedWaitText(label: string) {
  return translateTemplate('{word} — {sec}초 안에 한 번 더 누르면 저장합니다', {
    word: label,
    sec: VERDICT_ARM_MS / 1000,
  });
}

// Arms word key's button: it reads '<낱말> 확정' for VERDICT_ARM_MS, a screen reader hears that the next press saves
// and within how long (armedWaitText), and a page line says so beside it (pageLineHtml .pv-arm). kbd: armed by a key
// (verdictKey), which also lets it go when the reading page changes (stickReadingLine).
function armVerdict(key: string, where: string, page: number, label: string, kbd?: boolean) {
  disarmVerdict(false);
  ARMED_VERDICT = {
    key,
    label,
    where,
    page,
    doc: DOC,
    build: META ? META.pages_build : '',
    sel: where === VERDICT_PLACE.COMPOSER ? selectionBindingKey() : '',
    kbd: !!kbd,
    timer: setTimeout(() => disarmVerdict(true, true), VERDICT_ARM_MS),
  };
  redrawVerdictButtons(where);
  announce(armedWaitText(label));
}

// Lets an armed press go (Esc, another press, a press elsewhere, a new selection, document or build, the time running
// out). Nothing keeps saying it waits: when it goes by itself, by Esc or by a press elsewhere (say) a screen reader
// hears so - '삭제 확정을 풀었습니다' replaces '… 한 번 더 누르면 저장합니다' -, and otherwise (its second press saves,
// a new document or build) that sentence is taken out of the live region; a description box still up for it closes.
function disarmVerdict(redraw: boolean, say?: boolean) {
  const armed = ARMED_VERDICT;
  if (!armed) return;
  clearTimeout(armed.timer);
  ARMED_VERDICT = null;
  if (redraw) redrawVerdictButtons(armed.where);
  hideTip();
  if (say) announce(translateTemplate('{word} 확정을 풀었습니다', { word: armed.label }));
  else {
    const liveRegion = $('#sr-news');
    if (liveRegion && liveRegion.textContent === armedWaitText(armed.label)) liveRegion.textContent = '';
  }
}

function redrawVerdictButtons(where: string) {
  if (where === VERDICT_PLACE.COMPOSER) renderVerdictRow();
  else verdictLineRenderer().drawPageVerdicts();
}

// A press anywhere but on the armed button lets it go; Esc does too, and does nothing else. The click a long press's
// release ends with is no press (platform/tooltip.ts swallows it after this, on the document): it lets nothing go, nor
// closes the description the long press showed.
window.addEventListener(
  'click',
  (event) => {
    if (!ARMED_VERDICT || Date.now() < SWALLOW_CLICK) return;
    const button = eventClosest(event, '[data-act="verdict-save"],[data-act="pv-save"]', HTMLElement);
    if (!(button && isArmedHere(button.dataset.key || '', whereOfButton(button), Number(button.dataset.page) || 0)))
      disarmVerdict(true, true);
  },
  true,
);

window.addEventListener(
  'keydown',
  (event) => {
    if (event.key !== 'Escape' || !ARMED_VERDICT || imeKey(event)) return;
    event.preventDefault();
    event.stopImmediatePropagation();
    disarmVerdict(true, true);
  },
  true,
);

function whereOfButton(button: HTMLElement) {
  return button.dataset.act === 'verdict-save' ? VERDICT_PLACE.COMPOSER : VERDICT_PLACE.PAGE;
}

// One word's button: outline, a confirm word's text in the danger colour, '<낱말> 확정' while armed. The word is the
// manuscript's, so the button is translate="no" and its name is put in the screen's language here. In the composer it
// saves (its name says what about: '채택 판정으로 저장 — 3쪽'; its description, that the selection and note become that
// verdict's pin at once). On a page line it is a toggle: `pressed` says its state (PRESSED_AS) - the line's current
// verdict, or the word a save on the line is for, is pressed (aria-pressed, a filled look; a confirm word the
// destructive fill) - and its name stays '채택 판정 — 3쪽' whichever it is. Its description says what a press does: an
// unpressed word saves that verdict (the current one is replaced), the pressed one takes the person's own open verdict
// back (as [판정 취소]), and a pressed one that is not theirs or is handled says why it is not taken back here. The
// word a save is for (SAVING) keeps its box's words but gives a screen reader none (an empty aria-description, which
// platform/tooltip.ts leaves as the drawing code's): the line's status (.pv-busy, role=status) says the save, once. A
// click presses the word and focuses it at the same moment, and a screen reader reads a description that changes then
// twice, with the focus and as a change, before the status. Off: a composer's button is disabled; a page line's waits
// (aria-disabled, verdictPress ignores it) before the first list, and right after its word was taken back
// (TAKEN_BACK_HOLD) - it keeps the focus a keyboard press left on it, which a disabled button would drop to the page.
// keyNumber: on the line of the page the keys act on (KEYED_PAGE), the word's key 1-5 - drawn after the word as a key
// hint (data-kn, generated text on a mouse screen only, so the button's text stays the word) and, on that screen only
// (KEY_MARK_SCREEN), said in its description and as aria-keyshortcuts; 0 elsewhere. quiet: drawn without its
// description (data-tip) - a page line whose save chip stands (pageLineHtml) - so no description box comes over the
// chip; the name and the keys are still said. A page line's armed word ('삭제 확정') has no description either: its box
// would cover the line's figure name while the word waits for its second press, the button already reads what the box
// would say, and the line says how long it waits beside it (.pv-arm). Either keeps it for a long press (data-tip-press,
// platform/tooltip.ts): hover and focus raise no box, but a long press shows it and its release presses nothing, as on
// a word at rest - so a long press never takes the pressed word's verdict back while a chip or the reason popover is
// up, nor saves the armed word. The screen that draws the key marks (components.css .vd-b[data-kn]::after): a mouse's.
// Only there does a word's description end in '단축키 1' and its button carry aria-keyshortcuts, so a phone's long
// press never names a key it has none of. The lines are drawn again when that changes (a tablet's keyboard cover with
// its touchpad taken off), so the description follows the marks.
const KEY_MARK_SCREEN = matchMedia('(hover:hover) and (pointer:fine)');

KEY_MARK_SCREEN.addEventListener('change', () => {
  if (META) verdictLineRenderer().drawPageVerdicts();
});

function verdictButton(
  choice: VerdictChoice,
  where: string,
  page: number,
  target: string,
  off: boolean,
  keyNumber?: number,
  quiet?: boolean,
  pressed?: number,
) {
  const armed = isArmedHere(choice.key, where, page),
    line = where !== VERDICT_PLACE.COMPOSER,
    on = line && !!pressed && !armed;
  const said = !!keyNumber && KEY_MARK_SCREEN.matches; // the key said as well as drawn
  const name = armed
    ? translateTemplate('{word} 확정 — {sec}초 안에 한 번 더 누르면 저장합니다', {
        word: choice.label,
        sec: VERDICT_ARM_MS / 1000,
      })
    : line
      ? translateTemplate('{word} 판정 — {target}', { word: choice.label, target })
      : translateTemplate('{word} 판정으로 저장 — {target}', { word: choice.label, target });
  const forFigure = where === VERDICT_PLACE.COMPOSER && !!figureVerdictRoot(COMPOSE.current);
  let tip = armed
    ? name
    : forFigure
      ? translateTemplate('누르면 메모와 함께 이 그림 전체({target})의 {word} 판정 핀으로 바로 저장합니다', {
          word: choice.label,
          target,
        })
      : where === VERDICT_PLACE.COMPOSER
        ? translateTemplate('누르면 지금 선택과 메모를 {word} 판정 핀으로 바로 저장합니다', { word: choice.label })
        : pressed === PRESSED_AS.MINE
          ? translate('지금 판정입니다 · 다시 누르면 이 판정을 거둡니다(판정 취소)')
          : pressed === PRESSED_AS.OTHER
            ? translate('지금 판정입니다 · 다른 사람의 판정이라 여기서 거두지 않습니다')
            : pressed === PRESSED_AS.HANDLED
              ? translate('지금 판정입니다 · 처리된 판정이라 카드의 [지우기]로 거둡니다')
              : pressed === PRESSED_AS.SAVING
                ? translate('이 판정을 저장하는 중입니다')
                : translate('누르면 이 쪽의 판정으로 저장합니다 · 다시 누르면 거둡니다');
  if (said)
    tip += ' · ' + translateTemplate(choice.confirm ? '단축키 {key} (두 번)' : '단축키 {key}', { key: keyNumber });
  return html`<button type="button" class="vd-b hit${choice.confirm ? ' vd-confirm' : ''}${armed ? ' armed' : ''}" translate="no" data-act="${where === VERDICT_PLACE.COMPOSER ? 'verdict-save' : 'pv-save'}" \
data-key="${choice.key}" data-page="${page}" aria-label="${name}"${line ? html` aria-pressed="${on ? 'true' : 'false'}"` : ''}${on && pressed !== PRESSED_AS.SAVING ? html` aria-describedby="pv-on-${page}"` : ''}${on && pressed === PRESSED_AS.SAVING ? html` aria-description=""` : ''}\
${quiet || (armed && line) ? html` data-tip-press="${tip}"` : html` data-tip="${tip}"`}${keyNumber ? html` data-kn="${keyNumber}"` : ''}${said ? html` aria-keyshortcuts="${keyNumber}"` : ''}${off ? (line ? html` aria-disabled="true"` : html` disabled`) : ''}>\
${on ? lucideIcon('check') : ''}<span class="lbl">${armed ? translateTemplate('{word} 확정', { word: choice.label }) : choice.label}</span></button>`;
}

// A page line's word state (verdictButton's `pressed`): not pressed, or pressed as the person's own open verdict (a
// press takes it back), someone else's, a handled one (neither is taken back from the line), or the word a save on the
// line is for (SAVING). A pressed word carries a check before its word and is described by the line's state line
// (pressedWordHint, aria-describedby).
const PRESSED_AS = Object.freeze({ NONE: 0, MINE: 1, OTHER: 2, HANDLED: 3, SAVING: 4 });

// Gives the focus back to the button it was on after a redraw (an armed press redraws its buttons).
function refocusVerdictButton(focused: HTMLElement | null) {
  if (!focused || document.contains(focused) || !focused.dataset || !focused.dataset.act) return;
  const selector = focused.dataset.ref
    ? // a line's '#N' link or its earlier link
      '#doc .pv [data-act="' + focused.dataset.act + '"][data-ref="' + CSS.escape(focused.dataset.ref) + '"]'
    : '[data-act="' +
      focused.dataset.act +
      '"][data-key="' +
      CSS.escape(focused.dataset.key || '') +
      '"][data-page="' +
      (focused.dataset.page || '0') +
      '"]';
  const button = findMaybe(document, selector, HTMLElement);
  if (button) button.focus({ preventScroll: true });
}

// What a line's current verdict is to this person, as a pressed word (PRESSED_AS): their own open one, someone else's,
// or a handled one (검토 대기, 처리됨, or one whose [확인] waits for its undo).
function pressedAsOf(pin: Pin) {
  return canCancelVerdict(pin)
    ? PRESSED_AS.MINE
    : pinState(pin) !== PIN_STATE.OPEN || CONFIRMING.has(pin.id)
      ? PRESSED_AS.HANDLED
      : PRESSED_AS.OTHER;
}

// ---------------- The composer's verdict row
// What the selection is, for a button's name: on a figure document the figure it is saved for (figureName), else its
// page's region, else its file and lines.
function selectionTargetName(selection: ComposerSelection) {
  const figureRoot = figureVerdictRoot(selection);
  if (figureRoot && selection.page !== undefined) return figureName(selection.page, figureRoot);
  return isRegion(selection)
    ? translateTemplate('{page}쪽 영역', { page: selection.page })
    : selection.name + ' ' + lineRange(selection.lo, selection.hi);
}

// A figure's name for a person: its title in the map (meta pages[].title, '[후보] PL26 · …'), else '그림 <id>', with
// its page: '5쪽 · [후보] PL26 · …'. The title is only taken while that page still shows the figure.
function figureName(page: number, root: string) {
  const facts = META && Array.isArray(META.pages) ? META.pages[page - 1] : null,
    title = facts && facts.figure === root && facts.title ? facts.title : '';
  return translateTemplate('{page}쪽', { page }) + ' · ' + (title || translateTemplate('그림 {id}', { id: root }));
}

// The figure a figure document's selection is about - the root of its element's path - or null: not a figure document,
// or a pick without an element (a map it could not read).
function figureVerdictRoot(selection: ComposerSelection | null): string | null {
  if (!selection || !isFigureKind(docKindOf(selection.doc || DOC || ''))) return null;
  const element = selection.elSel || selection.el;
  const root = element && Array.isArray(element.path) ? element.path[0] : null;
  return typeof root === 'string' && root ? root : null;
}

// The pin body of a verdict saved from the composer on a figure document (ADR-0022 D2): a verdict is about the figure,
// so whatever element the selection names, it is saved as the verdict of the figure - the root of the element's path,
// the page's whole target, as a page line's press saves it. The root's rung of the pick's ladder when it has one (its
// lines, element and kind), else a region over the whole page naming the root (an element drawn without code, whose
// answer has no ladder). null when the selection is not about a figure (figureVerdictRoot): it is saved as it is.
function figureVerdictBody(selection: ComposerSelection): Record<string, unknown> | null {
  const root = figureVerdictRoot(selection);
  if (!root) return null;
  const rung = isRegion(selection)
    ? null
    : (selection.levels || []).find(
        (candidate) =>
          !!candidate.el &&
          Array.isArray(candidate.el.path) &&
          candidate.el.path.length === 1 &&
          candidate.el.path[0] === root &&
          candidate.el.id === root,
      );
  if (rung)
    return figureFields(
      {
        file: selection.file,
        name: selection.name,
        page: selection.page,
        lo: rung.lo,
        hi: rung.hi,
        raw_lo: selection.raw_lo,
        raw_hi: selection.raw_hi,
        via: selection.via,
        score: selection.score,
        frac: selection.frac,
        quote: selection.quote,
        pdf_build: selection.pdf_build || undefined,
        scope: rung.level,
      },
      rung.el,
      rung,
    );
  return figureFields(
    { page: selection.page, frac: WHOLE_PAGE.slice(), quote: '', pdf_build: selection.pdf_build || undefined },
    { id: root, path: [root], frac: WHOLE_PAGE.slice() },
    null,
  );
}

// The composer's verdict row (#c-verdict-row, after the note and its lines, before the kind row): '판정 바로 저장' and
// one button per word in file order. Shown for a document with words to a person who may make a verdict pin; its
// buttons are off, with the reason under them, while the kind is a question or [제안 수정] is on (a verdict pin is a
// fix request with no suggestion) and while the selection is still being found - really disabled, with the reason, also
// during a second pick over a selection (pick redraws the row when it starts).
function renderVerdictRow() {
  const row = $('#c-verdict-row'),
    verdicts = docVerdicts(),
    selection = COMPOSE.current;
  dropStaleRetry();
  // A figure page that takes no verdict (its map says verdict: false - a list or a question page) offers no word
  // either.
  const show =
    !!verdicts &&
    canVerdict() &&
    !$('#composer').hidden &&
    !(
      selection &&
      isFigureKind(docKindOf(selection.doc || DOC || '')) &&
      selection.page !== undefined &&
      !pageTakesVerdict(selection.page)
    );
  row.hidden = !show;
  if (ARMED_VERDICT && ARMED_VERDICT.where === VERDICT_PLACE.COMPOSER && (!show || !armStillHolds(ARMED_VERDICT)))
    disarmVerdict(false);
  if (!verdicts || !show) return;
  const why =
    COMPOSE.picking && !selection
      ? translate('위치를 찾는 중입니다')
      : KIND_NEW === REQUEST_KIND.QUESTION
        ? translate('질문에는 판정을 붙이지 않습니다 — 아래에서 [수정 요청]을 고릅니다')
        : SUGGEST_DRAFT.on
          ? translate('판정을 저장하려면 [제안 수정]을 끕니다')
          : '';
  const focused = focusedElement(),
    inRow = !!focused && row.contains(focused);
  // On a figure document the lead says whose verdict it is - the selected element's figure, by name ('· PL35 … 전체') -
  // whatever element is selected: a panel that shows another figure is still this page's figure's verdict.
  const figureRoot = selection ? figureVerdictRoot(selection) : null,
    mark = '\u0001',
    parts = translateTemplate('{name} 전체', { name: mark }).split(mark);
  const scope =
    figureRoot && selection && selection.page !== undefined
      ? html`<span class="vd-scope"> · ${parts[0]}<span class="vd-fig" translate="no">${figureShort(selection.page, figureRoot)}</span>${parts[1] || ''}</span>`
      : isFigureKind(docKindOf((selection && selection.doc) || DOC || '')) && !selection
        ? html`<span class="vd-scope"> · ${translate('그림 전체')}</span>`
        : '';
  setHtml(
    row,
    html`<span id="c-verdict-l" class="vd-l">${translate('판정 바로 저장')}${scope}</span><span class="vd-btns">${verdicts.choices.map((choice) => verdictButton(choice, VERDICT_PLACE.COMPOSER, 0, selection ? selectionTargetName(selection) : '', !!why || !selection || COMPOSE.saving))}</span>\
${why ? html`<span class="vd-why" id="c-verdict-why">${why}</span>` : ''}`,
  );
  if (why) row.setAttribute('aria-describedby', 'c-verdict-why');
  else row.removeAttribute('aria-describedby');
  fitWrappedWords(row.querySelector('.vd-btns'));
  if (inRow) refocusVerdictButton(focused);
}

if (typeof ResizeObserver !== 'undefined') {
  const row = document.getElementById('c-verdict-row');
  if (row) new ResizeObserver(() => fitWrappedWords(row.querySelector('.vd-btns'))).observe(row);
}

// A failed verdict save's retry that the composer stopped asking for (COMPOSE.intent moved since its press): it goes,
// and the failure's banner says so (verdictDropped). Run on every redraw of the verdict row, which every such change
// makes.
function dropStaleRetry() {
  const retry = COMPOSE.retryVerdict;
  if (!retry || retry.gen === COMPOSE.intent) return;
  setComposeRetryVerdict(null);
  verdictDropped();
}

// The composer's failed-save banner when the verdict it was for is not asked for any more - dropped after the failure,
// or the intent changed while the request was out (savePin): '핀 저장 실패 — 선택했던 판정은 해제됐습니다 — ...'. [다시
// 저장] saves the selection as the composer has it, without the verdict; pressing the word again saves the verdict.
function verdictDropped() {
  const banner = BANNERS.get(NOTICE_HOST.COMPOSER);
  if (!banner || !banner.save || $('#composer').hidden) return;
  bannerNote(
    NOTICE_HOST.COMPOSER,
    translateTemplate('{what} 실패', { what: translate('핀 저장') }) +
      ' — ' +
      translate('선택했던 판정은 해제됐습니다 — 판정으로 저장하려면 판정 버튼을 다시 누릅니다'),
    NOTICE_KIND.ERR,
    null,
    { save: true, source: banner.source },
  );
}

export {
  ARMED_VERDICT,
  PRESSED_AS,
  armStillHolds,
  armVerdict,
  disarmVerdict,
  figureVerdictBody,
  figureVerdictRoot,
  isArmedHere,
  pressedAsOf,
  refocusVerdictButton,
  renderVerdictRow,
  verdictButton,
  verdictDropped,
  whereOfButton,
};
