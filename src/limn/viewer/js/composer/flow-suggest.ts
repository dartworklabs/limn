// ------------------------------------------------ Suggested edits (docs/handbook/viewer.md §제안 수정, ADR-0020)
// A LaTeX line pin may carry the exact text that replaces its lines lo..hi: `suggest` {base, text}, base being the
// lines the author saw (docs/handbook/api.md §제안 수정 (`suggest`)). The composer and an open edit card each write one
// draft (SuggestDraft): the [제안 수정] switch, the editor's text, the text it was filled from (base) and the lines
// that base is. Until the text is edited it follows the range - a new pick, a rung, the excerpt's + and − - and once
// edited a range change keeps it and one line offers to read the new range's lines. A card shows a suggestion as a line
// diff of base -> text in the changes view's source-diff look, folded past five rows as the excerpt's band is.
import { BAND, DOC, META, isFigureKind, COMPOSE, EDITOR, setComposeIntent } from '../app/state.ts';
import { html, lucideIcon, setHtml } from '../platform/markup.ts';
import { countAddedHidden, findHidden, markHiddenHtml } from '../platform/hidden-chars.ts';
import { errText, translateTemplate, translate } from '../platform/i18n.ts';
import { api } from '../platform/api.ts';
import { findAnyPin } from '../revisions/flow.ts';
import { applySheet } from '../layout/flow-panel-size.ts';
import { renderOverlapBanner } from './flow-pick.ts';
import { saveDraftSoon } from './flow-draft.ts';
import type { Html } from '../platform/markup.ts';
import { $ } from '../platform/dom.ts';
import { DOC_KIND, LAYOUT_BAND, PIN_STATE, SUGGEST_OFF, SUGGEST_STATE } from '../app/rules-tables.ts';
import { pinState } from '../app/rules-pins.ts';
import { docInfo, withDocQuery, isRegion, pdoc, isViewer } from '../documents/state.ts';
import { composerVerdict } from './state-seams.ts';
import { SUGGEST_DRAFT, suggestDraft } from './state-suggest.ts';

// the most lines a suggestion may replace (limn.pins.editing.values.SUGGEST_LINES_MAX, the snippet's cap)
const SUGGEST_LINES = 80;
const SUGGEST_FOLD = 5; // a card's diff folds past this many rows to its first two and last two
// The short reason drawn where the switch would be when a selection can carry no suggested edit, and its tooltip.
const SUGGEST_WHY: Record<string, string[]> = {
  pdf: ['보기 전용 PDF에는 제안 수정 없음', '보기 전용 PDF에는 LaTeX 원문 줄이 없어 바꿀 글을 둘 수 없습니다'],
  figure: [
    '그림 문서에는 제안 수정 없음',
    '그림 스크립트에는 공통 부품과 다시 그리기 규칙이 따로 있어, 그림 문서에는 바꿀 글을 둘 수 없습니다',
  ],
  region: ['영역에는 제안 수정 없음', '영역에는 원문 줄이 없어 바꿀 글을 둘 수 없습니다'],
  long: ['제안 수정은 80줄까지', '제안 수정은 80줄까지의 범위만 바꿉니다. 범위를 줄이면 켤 수 있습니다'],
};

/** The draft an edit card of a pin opens with: on and filled with the pin's suggestion when it has one (had keeps it,
 * to tell what a save changes), else an empty draft. */
function suggestOfPin(pin: Pin): SuggestDraft {
  const empty = suggestDraft(),
    suggestion = pin.suggest;
  if (!suggestion) return empty;
  return {
    ...empty,
    on: true,
    text: suggestion.text,
    base: suggestion.base,
    file: pin.file || null,
    lo: pin.lo || 0,
    hi: pin.hi || 0,
    had: { base: suggestion.base, text: suggestion.text },
  };
}

// Why the owner - a pick or an edit card - can carry no suggested edit (SUGGEST_OFF), or null when it can: a view-only
// PDF, a figure document, an area (a region pick or pin, or no lines), or a range of more than SUGGEST_LINES lines.
// docKind is the document's kind; an unknown one is a LaTeX document. Pure.
function suggestOff(
  owner: { kind?: string; file?: string; pdf?: string; region?: boolean; lo?: number; hi?: number } | null,
  docKind: string | undefined,
): string | null {
  if (docKind === DOC_KIND.PDF) return SUGGEST_OFF.PDF;
  if (isFigureKind(docKind)) return SUGGEST_OFF.FIGURE;
  if (!owner || owner.region || isRegion(owner) || owner.lo == null || owner.hi == null) return SUGGEST_OFF.REGION;
  return owner.hi - owner.lo + 1 > SUGGEST_LINES ? SUGGEST_OFF.LONG : null;
}
/** Whether a draft holds a text other than the one it was filled from (a draft never filled is not edited). Pure. */
function suggestEdited(draft: SuggestDraft): boolean {
  return draft.base != null && draft.text !== draft.base;
}
/** The lines an owner is, as a draft records them: 'file:lo-hi'. Pure. */
function suggestKey(owner: { file?: string | null; lo?: number; hi?: number }): string {
  return String(owner.file) + ':' + owner.lo + '-' + owner.hi;
}
/** Whether the owner's lines are not the ones the draft's base was read from. Pure. */
function suggestMoved(draft: SuggestDraft, owner: { file?: string | null; lo?: number; hi?: number } | null): boolean {
  return draft.base != null && !!owner && suggestKey(draft) !== suggestKey(owner);
}
// What a new pin's save sends as `suggest` for a draft on a selection that is `off`: {base, text} when the editor is
// on, was filled and holds another text; null otherwise (nothing to suggest, or a selection that can carry none). A
// range over SUGGEST_LINES still sends it: the server's refusal (suggest_too_long) says why on the save row, and the
// draft stays. Pure.
function suggestForSave(draft: SuggestDraft, off: string | null): PinSuggest | null {
  if (!draft.on || draft.base == null || (off && off !== SUGGEST_OFF.LONG) || draft.text === draft.base) return null;
  return { base: draft.base, text: draft.text };
}
// What an edit's save sends as `suggest` for an edit card's draft: undefined (the stored suggestion stays as it is),
// null (remove it) or {base, text}. Switched off, or left with the source's own text, removes the pin's suggestion and
// sends nothing when it had none; the pin's own base and text send nothing; a draft not filled yet sends nothing. Pure.
function suggestForEdit(draft: SuggestDraft, off: string | null): PinSuggest | null | undefined {
  const had = draft.had;
  if (!draft.on) return had ? null : undefined;
  if (draft.base == null || (off && off !== SUGGEST_OFF.LONG)) return undefined;
  if (draft.text === draft.base) return had ? null : undefined;
  if (had && had.base === draft.base && had.text === draft.text) return undefined;
  return { base: draft.base, text: draft.text };
}

// The lines of a suggestion's string: an empty text is no line (it deletes the range); a base always has its range's
// lines. Pure.
function suggestLines(value: string, isText: boolean): string[] {
  return isText && value === '' ? [] : String(value).split('\n');
}
// A line diff of base -> text, top to bottom: rows {k:'ctx'|'del'|'add', t: the line, n: its number} - a base line
// numbered from first as it is in the file, a text line from first as it would be after the change; in a changed run
// the deleted lines come first. The longest common subsequence of whole lines. Pure.
function suggestDiff(base: string, text: string, first: number): { k: string; t: string; n: number }[] {
  const baseLines = suggestLines(base, false),
    textLines = suggestLines(text, true),
    baseCount = baseLines.length,
    textCount = textLines.length;
  // common[i][j]: the common lines of baseLines[i..] and textLines[j..]
  const common = Array.from({ length: baseCount + 1 }, () => new Int32Array(textCount + 1));
  for (let i = baseCount - 1; i >= 0; i--)
    for (let j = textCount - 1; j >= 0; j--)
      common[i][j] =
        baseLines[i] === textLines[j] ? common[i + 1][j + 1] + 1 : Math.max(common[i + 1][j], common[i][j + 1]);
  const out: { k: string; t: string; n: number }[] = [];
  let baseIndex = 0,
    textIndex = 0;
  while (baseIndex < baseCount || textIndex < textCount) {
    if (baseIndex < baseCount && textIndex < textCount && baseLines[baseIndex] === textLines[textIndex]) {
      out.push({ k: 'ctx', t: textLines[textIndex], n: first + textIndex });
      baseIndex++;
      textIndex++;
    } else if (
      baseIndex < baseCount &&
      (textIndex >= textCount || common[baseIndex + 1][textIndex] >= common[baseIndex][textIndex + 1])
    ) {
      out.push({ k: 'del', t: baseLines[baseIndex], n: first + baseIndex });
      baseIndex++;
    } else {
      out.push({ k: 'add', t: textLines[textIndex], n: first + textIndex });
      textIndex++;
    }
  }
  return out;
}
// The rows a diff shows: all of them when open or no more than SUGGEST_FOLD, else the first two and the last two round
// {k:'fold', n} for the rows between - the excerpt's fold. Pure.
function suggestFold(
  rows: { k: string; t: string; n: number }[],
  open: boolean,
): { k: string; t: string; n: number }[] {
  if (open || rows.length <= SUGGEST_FOLD) return rows;
  return [rows[0], rows[1], { k: 'fold', t: '', n: rows.length - 4 }, rows[rows.length - 2], rows[rows.length - 1]];
}
// Diff rows as Html in the changes view's source-diff look (revisions.css .rd-line): a number column and the line with
// its '+', '-' or ' ' mark, so a change never rests on colour alone. The lines are the manuscript's text
// (translate="no"), each character that would hide or reorder it in its box (markHiddenHtml), whatever the document's
// kind: a suggestion that puts one in never reads as another text than the one an agent will apply.
function suggestDiffHtml(rows: { k: string; t: string; n: number }[]): Html {
  return html`<div class="sg-diff" translate="no">${rows.map((row) =>
    row.k === 'fold'
      ? html`<span class="rd-line rd-fold"><span class="rd-no" aria-hidden="true"></span><span class="rd-code">… ${translateTemplate('{n}줄', { n: row.n })}</span></span>`
      : html`<span class="rd-line rd-${row.k === 'ctx' ? 'context' : row.k}"><span class="rd-no" aria-hidden="true">${row.n}</span><span class="rd-code">${row.k === 'add' ? '+' : row.k === 'del' ? '-' : ' '}${markHiddenHtml(row.t)}</span></span>`,
  )}</div>`;
}
// What a draft's text holds of the characters that would hide or reorder text (platform/hidden-chars.ts), which the
// editor (a textarea) shows as the browser does - unseen, or the text reordered: the ones it adds to its base ([[name,
// count]], countAddedHidden) and how many it has in all; null when it has none. Pure.
function suggestHidden(draft: SuggestDraft): { added: [string, number][]; n: number } | null {
  if (draft.base == null) return null;
  let count = 0;
  for (const line of draft.text.split('\n')) count += findHidden(line).length;
  return count ? { added: countAddedHidden(draft.text, draft.base), n: count } : null;
}
// The line under the editor for hidden, what suggestHidden found in the draft on lines from first, as Html: the
// characters the draft adds, with the draft's added lines that hold them in the diff look - each character in its box -
// so the person sees where they are; or, when it only keeps its base's, how many. pins.md flags an added one for the
// agent too.
function suggestHiddenHtml(draft: SuggestDraft, hidden: { added: [string, number][]; n: number }, first: number): Html {
  if (!hidden.added.length)
    return html`<span>${translateTemplate('원문에 있던, 보이지 않거나 글 순서를 바꾸는 문자 {n}개가 제안 문안에 그대로 있습니다. 이 칸에서는 보이지 않습니다', { n: hidden.n })}</span>`;
  const rows = suggestDiff(draft.base || '', draft.text, first)
    .filter((row) => row.k === 'add' && findHidden(row.t).length)
    .slice(0, SUGGEST_FOLD);
  return html`<span>${translateTemplate(
    '제안 문안이 원문에 없는, 보이지 않거나 글 순서를 바꾸는 문자를 넣습니다: {list}. 이 칸에서는 보이지 않거나 글 순서가 바뀌어 보입니다',
    { list: hidden.added.map(([name, count]) => name + ' ' + translateTemplate('{n}개', { n: count })).join(', ') },
  )}</span>${suggestDiffHtml(rows)}`;
}

// ---------------- A card's suggestion
const SUGGEST_OPEN = new Set(); // the cards whose suggestion diff is unfolded ('<doc>:<id>'), kept across redraws
// A card's suggested edit, after its note: the diff of base -> text, folded past SUGGEST_FOLD rows with [제안 펼치기 ·
// N줄] under it to unfold. null when the pin has none.
function suggestView(pin: Pin): Html | null {
  const suggestion = pin.suggest;
  if (!suggestion) return null;
  const key = pdoc(pin) + ':' + pin.id,
    open = SUGGEST_OPEN.has(key),
    rows = suggestDiff(suggestion.base, suggestion.text, pin.lo || 1);
  const foot =
    rows.length > SUGGEST_FOLD
      ? html`<div class="sg-foot"><button class="btn-sm btn-ghost" data-act="sg-fold" data-key="${key}" aria-expanded="${String(open)}">\
${open ? translate('제안 접기') : translate('제안 펼치기') + ' · ' + translateTemplate('{n}줄', { n: rows.length })}</button></div>`
      : null;
  return html`<div class="sg-view">${suggestWarnLine(pin)}${suggestDiffHtml(suggestFold(rows, open))}${foot}</div>`;
}
// The line over the diff of an open pin whose suggestion the agent will not apply (docs/handbook/viewer.md §제안 수정):
// that the agent will not apply it ('에이전트는 넣지 않음'), then why or what to do. 'unknown': why, '원문과 대조 불가'
// (`reason`). 'changed': what to do - rebase it in the edit card - as the line's one action (`edit`), a link-style
// button that opens that card's editor, as the card's [수정] does (an icon alone on touch). A viewer cannot edit, so
// has no action and reads the first part alone. The warning badge's explanation, said on screen for everyone, short
// enough for one line in the desktop panel and at 320px. null for a ready suggestion or a pin that is not open (a
// closed pin is not re-synced). Pure.
function suggestWarn(
  suggestState: string | undefined,
  stateOfPin: string,
  viewer: boolean,
): { reason: string | null; edit: boolean } | null {
  if (stateOfPin !== PIN_STATE.OPEN) return null;
  if (suggestState === SUGGEST_STATE.CHANGED) return { reason: null, edit: !viewer };
  if (suggestState === SUGGEST_STATE.UNKNOWN) return { reason: '원문과 대조 불가', edit: false };
  return null;
}
/** suggestWarn's line for a pin, in the screen's language; null when it has none. */
function suggestWarnLine(pin: Pin): Html | null {
  const warning = suggestWarn(pin.suggest_state, pinState(pin), isViewer());
  if (!warning) return null;
  const go = warning.edit
    ? html` · <button class="sg-warn-go hit" data-act="edit" data-tip="${translate('이 핀의 수정 칸을 엽니다 — 거기서 [지금 원문으로 맞추기]가 제안의 원문을 지금 그 줄들로 바꿉니다')}">\
${translate('수정해서 원문에 맞추기')}</button>`
    : null;
  return html`<p class="sg-warn">${translate('에이전트는 넣지 않음')}${warning.reason ? ' · ' + translate(warning.reason) : null}${go}</p>`;
}
// A card's [제안 수정] badge, with the reason not to apply it when its lines' text differs from its base ('원문 바뀜')
// or cannot be compared ('확인 불가'): a pin's `suggest_state`. A closed card shows the plain badge: a closed pin is
// not re-synced, and one whose suggestion was applied reads as changed. null without a suggestion. The two warning
// badges are .tip-shown: the card's line over the diff (suggestWarnLine) says what their explanation says, so they
// carry no words for a screen reader (platform/tooltip.ts); their explanation box stays.
function suggestBadge(pin: Pin, closed: boolean): Html | null {
  if (!pin.suggest) return null;
  const state = closed ? SUGGEST_STATE.READY : pin.suggest_state;
  if (state === SUGGEST_STATE.CHANGED)
    return html`<span class="badge badge-warning sg-badge tip-shown" data-tip="${translate('그사이 이 줄들이 바뀌어 제안의 원문과 다릅니다 — 에이전트는 넣지 않고 답글로 알립니다. [수정]에서 지금 원문으로 맞출 수 있습니다')}">${lucideIcon('triangle-alert')}${translate('제안 수정')} · ${translate('원문 바뀜')}</span>`;
  if (state === SUGGEST_STATE.UNKNOWN)
    return html`<span class="badge badge-warning sg-badge tip-shown" data-tip="${translate('원문과 대조할 수 없습니다(위치를 잃었거나 파일을 읽지 못함) — 에이전트는 넣지 않고 알립니다')}">${lucideIcon('triangle-alert')}${translate('제안 수정')} · ${translate('확인 불가')}</span>`;
  return html`<span class="badge sg-badge" data-tip="${translate('작성자가 바꿀 글을 직접 썼습니다 — 에이전트가 이 줄 범위에 넣고, 명백한 오타·문장 오류만 고쳐 알립니다. 뜻이 걸린 문제는 넣기 전에 묻습니다')}">${translate('제안 수정')}</span>`;
}

// ---------------- The editor (composer and edit card)
// Reads the lines owner.lo..owner.hi of owner.file exactly (GET /api/snippet?…&text=1) into the draft as its base - and
// as its text too when `fill` - then redraws its owner. Only while owns() (the selection or the edit card is still on
// screen), the owner still has those lines and, for a fill, the text was not typed meanwhile: otherwise the next draw
// decides again. A failure keeps the draft and says why on its line (fail), with [원문 다시 읽기].
async function suggestRead(draft: SuggestDraft, owner: any, fill: boolean, owns: () => boolean, redraw: () => void) {
  const key = suggestKey(owner),
    was = draft.text;
  if (draft.reading === key) return;
  draft.reading = key;
  draft.fail = null;
  redraw();
  let text = null as string | null,
    fail = '';
  try {
    const { status, data } = await api(
      withDocQuery(
        '/api/snippet?file=' +
          encodeURIComponent(String(owner.file)) +
          '&lo=' +
          owner.lo +
          '&hi=' +
          owner.hi +
          '&text=1',
        owner.doc,
      ),
      { what: '원문 읽기', expect: [400], silent: true },
    );
    if (status === 400) fail = errText(data);
    else if (data && typeof data.text === 'string') text = data.text;
    else fail = translate('80줄이 넘는 범위는 원문을 받지 못합니다');
  } catch (error) {
    fail = translate('서버에 닿지 않습니다');
  }
  if (draft.reading !== key) return; // a newer read took over
  draft.reading = '';
  if (!owns()) return;
  if (suggestKey(owner) !== key || (fill && draft.text !== was)) {
    redraw();
    return;
  }
  if (text == null) {
    draft.fail = { key, fill, why: fail };
    redraw();
    return;
  }
  draft.base = text;
  draft.file = owner.file || null;
  draft.lo = owner.lo;
  draft.hi = owner.hi;
  draft.current = null;
  if (fill) draft.text = text;
  redraw();
}
// Keeps the draft on the owner's lines while its text is the source's own: an editor turned on and never filled, or not
// edited since and now on other lines, reads them as its text and base. Nothing while off, on a selection that can
// carry no suggestion, during a read, or after a read of these lines failed (its [원문 다시 읽기] tries again).
function suggestFollow(draft: SuggestDraft, owner: any, off: string | null, owns: () => boolean, redraw: () => void) {
  if (!draft.on || off || draft.reading) return;
  if (draft.fail && draft.fail.key === suggestKey(owner)) return;
  if (draft.base == null || (suggestMoved(draft, owner) && !suggestEdited(draft)))
    suggestRead(draft, owner, true, owns, redraw);
}
// [지금 원문으로 맞추기]: the draft keeps its text and takes the owner's current lines as its base - the text a 409
// answered with when it is those lines, else read now.
function suggestRebase(draft: SuggestDraft, owner: any, owns: () => boolean, redraw: () => void) {
  const current = draft.current;
  draft.current = null;
  if (current && owner && suggestKey(current) === suggestKey(owner)) {
    draft.base = current.text;
    draft.file = current.file;
    draft.lo = current.lo;
    draft.hi = current.hi;
    redraw();
    return;
  }
  if (owner) suggestRead(draft, owner, false, owns, redraw);
  else redraw();
}
// The one line under the editor of the draft on the owner, or null: what is under way or wrong first, then what a save
// will do. Each is a Korean message (drawn through translate) and maybe the line's one action {act, label, tip}.
// isEdit: an edit card, whose pin's suggest_state is `state`. While its draft keeps the pin's own base, an edit card of
// a pin the agent will not apply says so first ('에이전트는 넣지 않음', `warn`: drawn in the warning colour, as on the
// card): 'changed' with the rebase that ends it, 'unknown' with why. A rebase or a new range's source is a new base,
// and the line goes, as the card's will once it is saved.
function suggestLine(
  draft: SuggestDraft,
  owner: any,
  off: string | null,
  isEdit: boolean,
  state: string | undefined,
): { msg: string; act: { act: string; label: string; tip: string } | null; warn?: boolean } | null {
  const reload = {
    act: 'sg-reload',
    label: '원문 다시 불러오기',
    tip: '지금 범위의 원문 줄을 다시 읽어 이 칸을 채웁니다. 쓰던 글은 그 원문으로 바뀝니다',
  };
  const rebase = {
    act: 'sg-rebase',
    label: '지금 원문으로 맞추기',
    tip: '쓰던 글은 그대로 두고, 이 제안이 바꿀 원문을 지금 그 줄들의 글로 바꿉니다',
  };
  if (!draft.on) return isEdit && draft.had ? { msg: '저장하면 이 핀의 제안 수정을 지웁니다', act: null } : null;
  if (off === SUGGEST_OFF.LONG)
    return { msg: '범위가 80줄을 넘어 이대로는 저장되지 않습니다 — 범위를 줄이거나 제안 수정을 끄세요', act: null };
  if (draft.reading && draft.base == null) return { msg: '원문 읽는 중…', act: null };
  const failure = draft.fail;
  if (failure)
    return {
      msg: translateTemplate('원문을 읽지 못했습니다 — {why}', { why: failure.why }),
      act: {
        act: failure.fill ? 'sg-reload' : 'sg-rebase',
        label: '원문 다시 읽기',
        tip: '이 줄들의 원문을 다시 읽습니다',
      },
    };
  if (draft.current && owner && suggestKey(draft.current) === suggestKey(owner))
    return { msg: '그사이 원문이 바뀌었습니다 — 아래는 지금 원문과 이 글의 차이입니다', act: rebase };
  if (suggestMoved(draft, owner)) return { msg: '범위가 바뀌었습니다', act: reload };
  const own = isEdit && !!draft.had && draft.base === draft.had.base;
  if (own && state === SUGGEST_STATE.CHANGED)
    return { msg: '에이전트는 넣지 않음 · 그사이 원문이 바뀌었습니다', act: rebase, warn: true };
  if (own && state === SUGGEST_STATE.UNKNOWN)
    return { msg: '에이전트는 넣지 않음 · 원문과 대조 불가', act: null, warn: true };
  if (draft.base != null && draft.text === draft.base)
    return {
      msg:
        isEdit && draft.had
          ? '원문과 같아 저장하면 이 핀의 제안 수정을 지웁니다'
          : '원문 그대로입니다 — 고친 글만 제안 수정으로 보냅니다',
      act: null,
    };
  return null;
}
// Grows a suggestion editor to its text, from two lines up to twelve (then it scrolls).
function suggestGrow(editor: HTMLTextAreaElement) {
  if (editor.hidden || !editor.getClientRects().length) return;
  const style = getComputedStyle(editor),
    px = (value: string) => parseFloat(value) || 0;
  const lineHeight = px(style.lineHeight) || 18,
    edge = px(style.paddingTop) + px(style.paddingBottom) + px(style.borderTopWidth) + px(style.borderBottomWidth);
  editor.style.height = 'auto';
  const need = editor.scrollHeight + px(style.borderTopWidth) + px(style.borderBottomWidth);
  editor.style.height = Math.min(12 * lineHeight + edge, Math.max(2 * lineHeight + edge, need)) + 'px';
}
// Draws the draft on the owner into its elements: the switch - or, when the owner can carry no suggestion, the short
// reason in its place - the editor while on, the one line under it, the characters the editor cannot show
// (suggestHiddenHtml) and, after a 409, the diff of the current source -> the text. A range over SUGGEST_LINES keeps
// the switch while it is on, so it can be switched off. The editor is read-only until its first fill. The line is a
// polite live region, so it is written only when what it says changes (typing redraws it on every key).
function drawSuggest(
  draft: SuggestDraft,
  owner: any,
  off: string | null,
  elements: {
    tg: HTMLElement;
    why: HTMLElement;
    box: HTMLElement;
    ta: HTMLTextAreaElement;
    line: HTMLElement;
    cc: HTMLElement;
    cur: HTMLElement;
  },
  isEdit: boolean,
  state: string | undefined,
) {
  const shown = !off || (off === SUGGEST_OFF.LONG && draft.on);
  elements.tg.hidden = !shown;
  elements.tg.setAttribute('aria-checked', String(draft.on));
  elements.why.hidden = shown;
  if (!shown && off) {
    const why = SUGGEST_WHY[off];
    elements.why.textContent = translate(why[0]);
    elements.why.dataset.tip = why[1];
  }
  const editing = draft.on && shown;
  elements.ta.hidden = !editing;
  if (elements.ta.value !== draft.text) elements.ta.value = draft.text;
  elements.ta.readOnly = draft.base == null;
  const line = shown ? suggestLine(draft, owner, off, isEdit, state) : null,
    said = line ? line.msg + '\n' + (line.act ? line.act.act : '') : '';
  elements.line.hidden = !line;
  elements.line.classList.toggle('sg-note-warn', !!(line && line.warn));
  if (elements.line.dataset.said !== said) {
    elements.line.dataset.said = said;
    const action = line && line.act;
    if (line)
      setHtml(
        elements.line,
        html`<span>${translate(line.msg)}</span>${action ? html`<button class="hit" data-act="${action.act}" data-tip="${action.tip}">${translate(action.label)}</button>` : ''}`,
      );
    else elements.line.replaceChildren();
  }
  const hiddenChars = editing ? suggestHidden(draft) : null,
    hiddenHtml = hiddenChars ? suggestHiddenHtml(draft, hiddenChars, draft.lo || (owner && owner.lo) || 1) : null,
    hiddenSaid = hiddenHtml ? hiddenHtml.text : '';
  elements.cc.hidden = !hiddenHtml;
  // in the warning colour when it adds some
  elements.cc.classList.toggle('sg-cc-warn', !!hiddenChars && hiddenChars.added.length > 0);
  if (elements.cc.dataset.said !== hiddenSaid) {
    elements.cc.dataset.said = hiddenSaid;
    if (hiddenHtml) setHtml(elements.cc, hiddenHtml);
    else elements.cc.replaceChildren();
  } // a live region: written when it changes
  const current =
    editing && draft.current && owner && suggestKey(draft.current) === suggestKey(owner) ? draft.current : null;
  elements.cur.hidden = !current;
  if (current) setHtml(elements.cur, suggestDiffHtml(suggestDiff(current.text, draft.text, current.lo)));
  else elements.cur.replaceChildren();
  elements.box.hidden = elements.ta.hidden && elements.line.hidden && elements.cc.hidden && elements.cur.hidden;
  if (editing) suggestGrow(elements.ta);
}

// ---------------- The composer's draft (SUGGEST_DRAFT)
/** The composer's suggestion elements. */
function composerSuggestElements() {
  return {
    tg: $('#c-sg-tg'),
    why: $('#c-sg-why'),
    box: $('#c-sg'),
    ta: $('#c-sg-text'),
    line: $('#c-sg-note'),
    cc: $('#c-sg-cc'),
    cur: $('#c-sg-cur'),
  };
}
// Draws the composer's suggestion for the selection (renderComposer and renderRegionComposer call it on every draw) and
// keeps an unedited draft on its lines. A read's answer redraws it, the overlap notice ([덧붙이기] waits on an edited
// suggestion) and the stored draft. The tablet sheet's height follows the editor as it opens, fills, grows and closes
// (applySheet, tabletLift).
function renderSuggest(selection: Selection) {
  const off = suggestOff(selection, META ? META.kind : undefined),
    owns = () => COMPOSE.current === selection;
  const redraw = () => {
    if (!owns()) return;
    renderSuggest(selection);
    renderOverlapBanner();
    saveDraftSoon();
  };
  drawSuggest(SUGGEST_DRAFT, selection, off, composerSuggestElements(), false, undefined);
  suggestFollow(SUGGEST_DRAFT, selection, off, owns, redraw);
  composerVerdict().drawRow(); // [제안 수정] on turns the verdict buttons off
  if (BAND === LAYOUT_BAND.TABLET_SHEET) applySheet();
}
// Whether the composer's draft is a suggestion a save would send, so its note may not join an overlapped pin instead
// ([덧붙이기] appends a note; the suggestion belongs to this selection's lines).
function suggestPending() {
  return SUGGEST_DRAFT.on && suggestEdited(SUGGEST_DRAFT);
}

// ---------------- An edit card's draft (EditCard.sg)
// The kind of an edit card's document (an unknown one is LaTeX).
function editDocKind(card: EditCard): string | undefined {
  const entry = docInfo(card.doc);
  return entry ? entry.kind : card.doc === DOC && META ? META.kind : undefined;
}
/** An edit card's suggestion elements. */
function editSuggestElements(card: EditCard) {
  const find = (selector: string) => card.el.querySelector(selector) as HTMLElement;
  return {
    tg: find('.e-sg-row .sg-tg'),
    why: find('.e-sg-row .sg-why'),
    box: find('.e-sg'),
    ta: find('.e-sg-text') as HTMLTextAreaElement,
    line: find('.e-sg .sg-note'),
    cc: find('.e-sg .sg-cc'),
    cur: find('.e-sg .sg-cur'),
  };
}
// Draws an edit card's suggestion (renderEdit): the switch and the editor on an open pin; a closed pin's suggestion
// read-only (its diff, no switch), as it can only take memo edits.
function renderEditSuggest(card: EditCard) {
  const pin = findAnyPin(card.id),
    closed = !!pin && pinState(pin) !== PIN_STATE.OPEN,
    elements = editSuggestElements(card);
  const row = card.el.querySelector('.e-sg-row') as HTMLElement,
    readOnly = card.el.querySelector('.e-sg-ro') as HTMLElement;
  row.hidden = closed;
  const view = closed && pin ? suggestView(pin) : null;
  readOnly.hidden = !view;
  if (view) setHtml(readOnly, view);
  else readOnly.replaceChildren();
  if (closed) {
    elements.box.hidden = true;
    return;
  }
  const off = suggestOff(card, editDocKind(card)),
    owns = () => EDITOR.current === card,
    redraw = () => {
      if (owns()) renderEditSuggest(card);
    };
  drawSuggest(card.sg, card, off, elements, true, pin ? pin.suggest_state : undefined);
  suggestFollow(card.sg, card, off, owns, redraw);
}
// The draft and the selection or card an editor control belongs to: the open edit card's when the control is inside it,
// else the composer's.
function suggestOwner(
  control: HTMLElement,
): { sg: SuggestDraft; o: any; owns: () => boolean; redraw: () => void } | null {
  if (control.closest('.edit')) {
    const card = EDITOR.current;
    if (!card) return null;
    return {
      sg: card.sg,
      o: card,
      owns: () => EDITOR.current === card,
      redraw: () => {
        if (EDITOR.current === card) renderEditSuggest(card);
      },
    };
  }
  const selection = COMPOSE.current;
  if (!selection) return null;
  return {
    sg: SUGGEST_DRAFT,
    o: selection,
    owns: () => COMPOSE.current === selection,
    redraw: () => {
      if (COMPOSE.current !== selection) return;
      renderSuggest(selection);
      renderOverlapBanner();
      saveDraftSoon();
    },
  };
}
// The editor's controls: the switch, [원문 다시 불러오기] (fill from the range's lines) and [지금 원문으로 맞추기]
// (rebase), for the draft the control belongs to.
function suggestAct(control: HTMLElement, act: string) {
  const owner = suggestOwner(control);
  if (!owner) return;
  if (act === 'sg-toggle') {
    owner.sg.on = !owner.sg.on;
    owner.sg.current = null;
    if (owner.sg === SUGGEST_DRAFT) setComposeIntent(COMPOSE.intent + 1);
    owner.redraw();
    return;
  } // the composer's switch ends a failed verdict save's retry
  if (act === 'sg-reload') {
    owner.sg.current = null;
    owner.sg.fail = null;
    suggestRead(owner.sg, owner.o, true, owner.owns, owner.redraw);
    return;
  }
  if (act === 'sg-rebase') {
    owner.sg.fail = null;
    suggestRebase(owner.sg, owner.o, owner.owns, owner.redraw);
  }
}
// Typing in an editor: its draft takes the text; the line under it and - in the composer - the overlap notice and the
// tab's draft follow.
document.addEventListener('input', (event) => {
  const editor = event.target as HTMLTextAreaElement;
  if (!editor.classList || !editor.classList.contains('sg-text')) return;
  const owner = suggestOwner(editor);
  if (!owner) return;
  owner.sg.text = editor.value;
  owner.redraw();
});
export {
  SUGGEST_OPEN,
  editDocKind,
  renderEditSuggest,
  renderSuggest,
  suggestAct,
  suggestBadge,
  suggestEdited,
  suggestForEdit,
  suggestForSave,
  suggestOfPin,
  suggestOff,
  suggestPending,
  suggestRebase,
  suggestView,
};
