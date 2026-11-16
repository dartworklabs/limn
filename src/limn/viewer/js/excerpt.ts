// ------------------------------------------------ Range excerpt (docs/handbook/viewer.md §패널 정리 범위 발췌)
// On every layout the source under the range ladder is the range control itself: the selected lines in a tinted band
// with one dimmed line above and below. A tap or click on a dimmed line widens the range to it; the '−' on the band's
// first or last line drops that line; with a keyboard, Enter or Space on the row or the '−' does the same. The composer
// and the edit card draw the same excerpt.
import { $, SNIP_OPEN } from './core.ts';
import { html, ic, setHtml } from './markup.ts';
import { ccHtml } from './hidden-chars.ts';
import { tl, tr } from './i18n.ts';
import { api } from './api.ts';
import { dq, isRegion } from './doc-tabs.ts';
import { refetchSnip } from './levels.ts';
import { COMPOSE, recomputeOverlap, renderComposer } from './composer.ts';
import { EDITOR, renderEdit } from './edit.ts';

// The range first..last widened to line: [min(first, line), max(last, line)]. Pure.
function widenTo(first, last, line) {
  return [Math.min(first, line), Math.max(last, line)];
}
// The range first..last less its end line `line`: [first+1, last] or [first, last-1]; null when that line is neither
// end of a range of two or more lines. Pure.
function dropLine(first, last, line) {
  if (first >= last) return null;
  return line === first ? [first + 1, last] : line === last ? [first, last - 1] : null;
}
// The rows the excerpt draws round first..last in a file of lineCount lines, top to bottom: a dimmed line above (none
// above line 1), the band - folded to its first two and last two lines round {kind:'fold', n} (n: the lines folded)
// when longer than five and not opened - and a dimmed line below (none past the file's last line). Each row is {k,
// kind:'ctx'|'on', edge} (k: its line; edge: an end of a band of two or more). Pure. One row of the excerpt
// (excerptRows).
type ExcerptRow = { k: number; kind: 'ctx' | 'on'; edge: boolean } | { kind: 'fold'; n: number };
function excerptRows(first, last, lineCount, open) {
  const out: ExcerptRow[] = [],
    bandSize = last - first + 1,
    on = (line): ExcerptRow => ({ k: line, kind: 'on', edge: bandSize > 1 && (line === first || line === last) });
  if (first > 1) out.push({ k: first - 1, kind: 'ctx', edge: false });
  if (bandSize <= 5 || open) for (let k = first; k <= last; k++) out.push(on(k));
  else out.push(on(first), on(first + 1), { kind: 'fold', n: bandSize - 4 }, on(last - 1), on(last));
  if (last < lineCount) out.push({ k: last + 1, kind: 'ctx', edge: false });
  return out;
}
// Each selection's or edit card's source lines (line -> text, null when the server gave none) and the ones being
// fetched. Kept beside the object, not on it: the composer's selection is written to the tab's draft (draft.ts) as
// JSON.
const EXCERPT_LINES = new WeakMap(),
  EXCERPT_FETCHING = new WeakSet();
// The line cache of owner - a selection or an edit card - in EXCERPT_LINES, made on first use.
function excerptLines(owner) {
  let lines = EXCERPT_LINES.get(owner);
  if (!lines) {
    lines = new Map();
    EXCERPT_LINES.set(owner, lines);
  }
  return lines;
}
// Reads a numbered snippet ('   40  text' lines, limn.pins.location.mapping.snippet) into the owner's line cache.
function excerptTake(owner, snip) {
  const lines = excerptLines(owner);
  String(snip || '')
    .split('\n')
    .forEach((snippetLine) => {
      const match = /^\s*(\d+)(?: {2}(.*))?$/.exec(snippetLine);
      if (match) lines.set(+match[1], match[2] || '');
    });
}
// Fetches the lines the excerpt shows that the owner's cache lacks - its ends and their neighbours - in at most two
// windows of /api/snippet, then redraws the owner's panel. A line the server did not give is cached as null ('…'), so a
// failure never loops.
async function excerptFetch(owner) {
  const lineCount = owner.n_lines || owner.hi,
    want = new Set<number>();
  for (const k of [owner.lo - 1, owner.lo, owner.lo + 1, owner.hi - 1, owner.hi, owner.hi + 1])
    if (k >= 1 && k <= lineCount) want.add(k);
  const lines = excerptLines(owner),
    miss = [...want].filter((line) => !lines.has(line)).sort((left, right) => left - right);
  if (!miss.length || EXCERPT_FETCHING.has(owner)) return;
  EXCERPT_FETCHING.add(owner);
  const fetchWindows: number[][] = [];
  miss.forEach((line) => {
    const lastWindow = fetchWindows[fetchWindows.length - 1];
    if (lastWindow && line <= lastWindow[1] + 4) lastWindow[1] = line;
    else fetchWindows.push([line, line]);
  });
  try {
    for (const [from, to] of fetchWindows) {
      const { data } = await api(
        dq('/api/snippet?file=' + encodeURIComponent(owner.file) + '&lo=' + from + '&hi=' + to, owner.doc),
        { what: '원문 읽기' },
      );
      excerptTake(owner, data.snippet);
      if (data.n_lines) owner.n_lines = data.n_lines;
    }
  } catch (error) {}
  miss.forEach((line) => {
    if (!lines.has(line)) lines.set(line, null);
  });
  EXCERPT_FETCHING.delete(owner);
  excerptRedraw(owner);
}
// Redraws the panel the owner belongs to (the composer's selection or the open edit card); a stale owner draws nothing.
function excerptRedraw(owner) {
  if (owner === COMPOSE.current) renderComposer();
  else if (owner === EDITOR.current) renderEdit();
}
// The owner's excerpt box: the composer's #c-xp or the open edit card's .e-xp, else null.
function excerptBox(owner) {
  const editing = EDITOR.current;
  return owner === COMPOSE.current
    ? $('#c-xp')
    : editing && owner === editing
      ? editing.el.querySelector('.e-xp')
      : null;
}
// The control to focus after a redraw that took the focused one (a keyboard's Enter or Space on '+' or '−'): the same
// action on the same line; else the same action on the side the change happened - the next dimmed line above or below,
// or the band's new end line's '−' - so another press repeats it; else the control nearest that line. was: {act, line};
// the owner has the new range. Pure over the rows' buttons ([{act, line, el}]).
function excerptFocusTarget(buttons, was, owner) {
  const at = (act, line) => buttons.find((button) => button.act === act && button.line === line);
  const up = was.line <= owner.lo,
    same =
      at(was.act, was.line) ||
      (was.act === 'xp-to' ? at('xp-to', up ? owner.lo - 1 : owner.hi + 1) : at('xp-drop', up ? owner.lo : owner.hi));
  if (same) return same;
  return buttons.reduce(
    (nearest, button) =>
      !nearest || Math.abs(button.line - was.line) < Math.abs(nearest.line - was.line) ? button : nearest,
    null,
  );
}
// Draws the owner's excerpt into box, or clears and hides it (a region, no selection). isEdit: an edit card (the
// composer's [원문 펼치기] unfolds a long band; an edit card's band stays folded). A redraw that takes the focused '+'
// or '−' puts the focus on its successor (excerptFocusTarget), so a keyboard keeps its place.
function drawExcerpt(owner, box, isEdit) {
  const on = !!owner && !owner.region && !isRegion(owner);
  const focused = document.activeElement as HTMLElement,
    had =
      box.contains(focused) && focused.dataset.act
        ? { act: focused.dataset.act, line: Number(focused.dataset.line) }
        : null;
  box.hidden = !on;
  if (!on) {
    box.replaceChildren();
    return;
  }
  excerptTake(owner, owner.snippet);
  excerptFetch(owner);
  const lines = excerptLines(owner),
    text = (line) => {
      const lineText = lines.get(line);
      return lineText == null ? '…' : ccHtml(lineText);
    }; // a character that would hide or reorder the line in its box (hidden-chars.ts)
  const rows = excerptRows(owner.lo, owner.hi, owner.n_lines || owner.hi, !isEdit && SNIP_OPEN).map((row) =>
    row.kind === 'fold'
      ? html`<div class="xp-fold">… ${tl('{n}줄', { n: row.n })}</div>`
      : row.kind === 'ctx'
        ? html`<button class="xp-row ctx" data-act="xp-to" data-line="${row.k}" aria-label="${tl('L{n}까지 넓히기', { n: row.k })}"><span class="ln">${row.k}</span>\
<span class="tx">${text(row.k)}</span><span class="xp-chip add" aria-hidden="true">${ic('plus')}</span></button>`
        : html`<div class="xp-row on" data-line="${row.k}"><span class="ln">${row.k}</span><span class="tx">${text(row.k)}</span>\
${row.edge ? html`<button class="xp-chip xp-drop" data-act="xp-drop" data-line="${row.k}" aria-label="${tl('이 줄 빼기 (L{n})', { n: row.k })}">${ic('minus')}</button>` : html`<span></span>`}</div>`,
  );
  const hint =
    owner.hi > owner.lo
      ? tr('흐린 줄을 누르면 그 줄까지 넓어지고, −를 누르면 그 줄이 빠집니다')
      : tr('흐린 줄을 누르면 그 줄까지 넓어집니다');
  setHtml(box, html`<div class="xp-hint">${hint}</div><div class="xp-list" translate="no">${rows}</div>`);
  if (had) {
    const target = excerptFocusTarget(
      [...box.querySelectorAll('[data-act]')].map((control) => ({
        act: control.dataset.act,
        line: +control.dataset.line,
        el: control,
      })),
      had,
      owner,
    );
    if (target) target.el.focus({ preventScroll: true });
  }
  if (!isEdit) {
    const bandSize = owner.hi - owner.lo + 1;
    $('#c-expand').hidden = bandSize <= 5;
    $('#c-expand').textContent = SNIP_OPEN ? tr('원문 접기') : tr('원문 펼치기') + ' · ' + tl('{n}줄', { n: bandSize });
  }
}
// Sets the owner's lines by hand: first..last, the scope 'lines' and no environment; a figure pick keeps its element
// (elSel) - lines set in the source are a range edit, not a new place.
function setLines(owner, first, last) {
  owner.lo = first;
  owner.hi = last;
  owner.scope = 'lines';
  owner.env = null;
}
// Applies range ([first, last], kept inside the file) to the owner as lines set by hand (setLines), then the overlap
// (composer), the panel and the source text. The sheet scrolls by whatever the redraw moved line anchor's row - the end
// that stayed - so a row that came or went above never shifts the band under the finger. Nothing changed: nothing done.
function applyRange(owner, range, anchor) {
  if (!owner || !range) return;
  const lineCount = owner.n_lines || Math.max(range[1], owner.hi),
    first = Math.max(1, Math.min(range[0], lineCount)),
    last = Math.max(first, Math.min(range[1], lineCount));
  if (first === owner.lo && last === owner.hi) return;
  const row = () => {
      const box = excerptBox(owner);
      return box && box.querySelector('.xp-row[data-line="' + anchor + '"]');
    },
    rowBefore = row(),
    topBefore = rowBefore && rowBefore.getBoundingClientRect().top;
  setLines(owner, first, last);
  if (owner === COMPOSE.current) {
    COMPOSE.intent++;
    recomputeOverlap();
  }
  excerptRedraw(owner);
  const rowAfter = row();
  if (rowBefore && rowAfter) $('#right').scrollTop += rowAfter.getBoundingClientRect().top - topBefore;
  refetchSnip(owner, () => excerptRedraw(owner));
}
export { applyRange, drawExcerpt, dropLine, widenTo };
