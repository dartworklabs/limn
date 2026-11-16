// ------------------------------------------------ Range levels
import { T, UI_LANG, VIA, captureVisit, currentVisit } from './core.ts';
import { html, setHtml } from './markup.ts';
import { LANG, tl, tr } from './i18n.ts';
import { api } from './api.ts';
import { dq } from './doc-tabs.ts';
import { elName, rungTip } from './figure.ts';
import { isMdDoc } from './md-surface.ts';
import { COMPOSE } from './composer.ts';
import { EDITOR } from './edit.ts';
import { segFocusAt, segKeep, segRove } from './events.ts';
function lvOf(owner, key) {
  return (owner.levels || []).find((rung) => rung.level === key || (rung.merged || []).includes(key));
}
// A Markdown document's rungs (md-surface.ts markdownLevels, ADR-0025 D3): a block is md:<its kind> (the rung's env), a
// section md:section, and several blocks whole (level blocks) are lines - a pin's scope is one of the server's
// (wireScope), and blocks is none of them.
function wireScope(scope) {
  return scope === 'blocks' ? 'lines' : scope;
}
function kindFor(scope, env) {
  if (!scope) return null;
  if (scope.startsWith('env')) return 'env:' + (env || '?');
  if (scope === 'block') return 'md:' + (env || 'paragraph');
  if (scope === 'section') return 'md:section';
  if (scope === 'indent') return 'indent'; // a text document's indented block (ADR-0029 D3)
  return scope === 'para' ? 'paragraph' : 'lines';
}
// The name of the owner's range kind for a description: its rung's, else its kind's; '' for lines set one by one (scope
// 'lines'), whose lines alone say what they are.
function scopeLabel(owner) {
  const rung = owner.scope && lvOf(owner, owner.scope);
  if (rung) return levelLabel(rung.label);
  if (owner.scope === 'lines') return '';
  return tr(
    { float: '그림/표', block: '환경 블록', paragraph: '문단', none: '생성 파일', lines: '줄' }[owner.kind] ||
      owner.kind ||
      '',
  );
}
// Range-level labels come from the server in Korean ('드래그한 줄', '문단', '환경 table', '환경 table (바깥)').
function levelLabel(label) {
  label = String(label || '');
  if (LANG !== UI_LANG.EN) return label;
  const match = /^환경 (.+?)( \(바깥( 2)?\))?$/.exec(label);
  return match
    ? tl(match[3] ? '환경 {env} (바깥 2)' : match[2] ? '환경 {env} (바깥)' : '환경 {env}', { env: match[1] })
    : tr(label);
}
// The rung matching the owner's range, shown as pressed: with a scope, that scope's rung (when the range matches it
// too); otherwise the first rung whose lo/hi match (shown as '지금 범위' on an edit card).
function currentRung(owner) {
  const rungs = owner.levels || [];
  const scopeRung = owner.scope && lvOf(owner, owner.scope);
  if (scopeRung && scopeRung.lo === owner.lo && scopeRung.hi === owner.hi) return scopeRung;
  return rungs.find((rung) => rung.lo === owner.lo && rung.hi === owner.hi) || null;
}
// Line-range notation: 'L159' for a single line, 'L155-L173' for multiple (the copy/pins.md format 'L159-L159' is left
// as-is).
function rng(first, last) {
  return 'L' + first + (last !== first ? '-L' + last : '');
}
// Segment-control labels are kept short - '환경 abstract' -> 'abstract'. When the same environment name appears more
// than once, '(바깥)' is kept to distinguish them. The line range is left out of the label, going instead into the
// description (data-tip)/aria-label and the location line. A figure rung is named by its element as the server labelled
// it (a person's words, not run through levelLabel).
function levelName(rung, all) {
  if (rung.el) return String(rung.label || elName(rung.el));
  if (!rung.env || rung.level === 'block') return levelLabel(rung.label);
  const dup = (all || []).filter((other) => other.env === rung.env).length > 1;
  return dup ? levelLabel(rung.label).replace(/^(환경|Environment) /, '') : rung.env;
}
// The range ladder's segments (composer and edit card) as Html, one radio button per rung, the rung matching the range
// checked. A figure rung (it carries an element) gets the element's tooltip; its line count comes from lo-hi when the
// rung has no n. A Markdown document's rungs have descriptions of their own (T.mdraw: no drag area there, a tap chose
// the line too).
function rungButtons(owner, isEdit) {
  const current = currentRung(owner),
    rungs = owner.levels || [];
  return rungs.map((rung) => {
    const on = rung === current,
      lineCount = rungLines(rung);
    const tip = rung.el
      ? rungTip(rung)
      : isEdit && rung.level === 'raw'
        ? T.cur
        : rung.level.startsWith('env')
          ? T.env
          : rung.level === 'raw' && isMdDoc()
            ? T.mdraw
            : // a rung may name its own description (a text document's paragraphs, txLevels)
              T[rung.tip || rung.level] || '';
    const label = isEdit && rung.level === 'raw' ? tr('지금 범위') : levelName(rung, rungs),
      linesText = tl('{n}줄', { n: lineCount });
    return html`<button class="${on ? 'on' : ''}" data-act="level" data-level="${rung.level}" role="radio" aria-checked="${on}" aria-label="${label + ' ' + rng(rung.lo, rung.hi) + ' · ' + linesText}" \
data-tip="${rng(rung.lo, rung.hi) + (tip ? ' · ' + tr(tip) : '')}">${label} <span class="k${lineCount > 50 ? ' wn' : ''}">· ${linesText}</span></button>`;
  });
}
// A rung's line count: the server's n, else its lo-hi span (a figure rung may come without n).
function rungLines(rung) {
  return typeof rung.n === 'number' ? rung.n : rung.hi - rung.lo + 1;
}
// Draws the owner's range ladder into box (#c-levels or an edit card's .e-levels): its segments, shown only when there
// are two or more rungs - one segment is no choice, and '문단 · 1줄' alone reads as noise; the caption then names that
// rung (rangeCap). data-rungs keeps the count for the CSS and the tests. The box is a scroll box and carries
// tabindex="-1" in its markup: Firefox makes a box that overflows a Tab stop of its own, so an overflowing ladder would
// take two stops - the box, then the chosen rung. The chosen rung shows itself as the focus or the range moves
// (segReveal).
function drawLadder(box, owner, isEdit) {
  const rungCount = (owner.levels || []).length,
    at = segFocusAt(box);
  box.dataset.rungs = String(rungCount);
  box.hidden = rungCount < 2;
  setHtml(box, rungCount < 2 ? html`` : html`<div class="lad-t">${rungButtons(owner, isEdit)}</div>`);
  if (rungCount >= 2) segReveal(box); // .lad-t: the drawn track inside the scroll box
  segRove(box);
  segKeep(box, at);
} // one Tab stop, the rung matching the range (else the first), and the focus kept (events.ts)
// The range caption over the ladder (composer and edit card): '범위 L5-L6 · 2줄' - the lines a save will hand over and
// their count, whatever set them (a rung or the excerpt). When the ladder is hidden (one rung) and the range is that
// rung, its name follows ('범위 L5 · 1줄 · 문단'); with a ladder, its checked segment names it. An edit card's own
// lines (its 'raw' rung) get no name. A range matching no rung has none either: the lines say what it is. In an edit
// card the range copies as 'file Llo-Lhi' (the composer's location line has its copy). Writes the caption markup (Html)
// into its element only when its text changed: the caption is a polite live region (a screen reader hears the new range
// after a rung or an excerpt press, not every redraw), and its copyable range keeps its focus.
function setCap(caption, markup) {
  if (caption._cap !== markup.text) {
    caption._cap = markup.text;
    setHtml(caption, markup);
  }
}
function rangeCap(owner, isEdit) {
  const rungs = owner.levels || [],
    current = currentRung(owner),
    range = rng(owner.lo, owner.hi);
  const named =
    rungs.length < 2 && current && !(isEdit && current.level === 'raw') ? ' · ' + levelName(current, rungs) : '';
  const rangeHtml = isEdit
    ? html`<span class="e-range loc" tabindex="0" data-copy="${owner.name + ' L' + owner.lo + '-L' + owner.hi}" data-tip="${tr('저장하면 핀이 가리킬 원문 줄. 누르면 복사')}">${range}</span>`
    : html`<span class="rg-v">${range}</span>`;
  return html`<b class="rg-l">${tr('범위')}</b> ${rangeHtml} · ${tl('{n}줄', { n: owner.hi - owner.lo + 1 })}${named}`;
}
const SEGMENT_FADE = 32; // how wide a scrolling segment control's edge fade is at most (composer.css)
// Scrolls a horizontally overflowing segment control so the selected segment is visible (vertical scroll is left
// untouched). A control that asks for the whole segment (data-reveal="whole": the assignee row, whose segments are
// names nearly as long as the row) brings it clear of the edge fades too - a fade's width in from an edge that has more
// to scroll to, or centred when it is too long for that; fadeSegmentEdges then keeps each fade off it.
function segReveal(control) {
  const on = control && control.querySelector('.on');
  if (!on) {
    fadeSegmentEdges(control);
    return;
  }
  const left = on.offsetLeft,
    right = left + on.offsetWidth,
    width = control.clientWidth;
  if (control.dataset.reveal === 'whole')
    control.scrollLeft = wholeSegmentAt(left, right, width, control.scrollWidth, control.scrollLeft);
  else if (left < control.scrollLeft) control.scrollLeft = Math.max(0, left - 4);
  else if (right > control.scrollLeft + width) control.scrollLeft = right - width + 4;
  fadeSegmentEdges(control);
}
// Where a scroll box `width` wide over content `full` wide, now at `at`, stands to show the segment from `left` to
// `right` whole and clear of the edge fades: the nearest place that leaves SEGMENT_FADE on each side of it, or the
// segment centred when the box has no room for both; never past either end. Pure.
function wholeSegmentAt(left: number, right: number, width: number, full: number, at: number): number {
  const end = Math.max(0, full - width),
    fits = right - left + 2 * SEGMENT_FADE <= width;
  return Math.max(
    0,
    Math.min(
      end,
      fits
        ? Math.max(right - width + SEGMENT_FADE, Math.min(left - SEGMENT_FADE, at))
        : left - (width - (right - left)) / 2,
    ),
  );
}
// If the range ladder is longer than the panel, the overflowing edge is faded - since the scrollbar is hidden, a
// segment cut off at the edge would give no sign that there is more. A control that shows its selected segment whole
// (data-reveal="whole") narrows each fade to the room between that segment and the edge (--fade-l, --fade-r), so the
// fade lies on what there is more of and never on the selected segment.
function fadeSegmentEdges(control) {
  if (!control) return;
  const over = control.scrollWidth - control.clientWidth;
  control.classList.toggle('fade-l', over > 1 && control.scrollLeft > 1);
  control.classList.toggle('fade-r', over > 1 && over - control.scrollLeft > 1);
  const on = control.dataset.reveal === 'whole' ? (control.querySelector('.on') as HTMLElement | null) : null;
  if (!on) return;
  const controlRect = control.getBoundingClientRect(),
    segmentRect = on.getBoundingClientRect(),
    room = (px) => Math.max(0, Math.min(SEGMENT_FADE, Math.floor(px))) + 'px';
  control.style.setProperty('--fade-l', room(segmentRect.left - controlRect.left));
  control.style.setProperty('--fade-r', room(controlRect.right - segmentRect.right));
}
document.addEventListener(
  'scroll',
  (event) => {
    const target = event.target as HTMLElement;
    if (target && target.classList && target.classList.contains('seg')) fadeSegmentEdges(target);
  },
  true,
);
// Applies rung `key` to the owner (the composer's selection or an edit card): its lines, scope and source; a figure
// rung also selects its element (elSel), which lines later set in the excerpt keep (setLines).
function useLevel(owner, key) {
  const rung = lvOf(owner, key);
  if (!rung) return;
  if ('score' in rung) owner.score = rung.score;
  owner.lo = rung.lo;
  owner.hi = rung.hi;
  owner.scope = rung.level;
  owner.env = rung.env || null;
  owner.snippet = rung.snippet;
  if (rung.el) owner.elSel = rung.el;
}
let SNIPPET_TIMER = undefined as ReturnType<typeof setTimeout> | undefined;
// Refreshes the text of a range set in the excerpt only while its selection still owns the visit or its edit card
// survives.
function refetchSnip(owner, after) {
  const visit = captureVisit();
  clearTimeout(SNIPPET_TIMER);
  SNIPPET_TIMER = setTimeout(async () => {
    try {
      const { data } = await api(
        dq('/api/snippet?file=' + encodeURIComponent(owner.file) + '&lo=' + owner.lo + '&hi=' + owner.hi, owner.doc),
        { what: '원문 읽기' },
      );
      if (
        (owner === EDITOR.current || (owner === COMPOSE.current && currentVisit(visit))) &&
        data.lo === owner.lo &&
        data.hi === owner.hi
      ) {
        owner.snippet = data.snippet;
        after();
      }
    } catch (error) {}
  }, 250);
}
function snipText(text, open) {
  const rungs = String(text || '').split('\n');
  return open || rungs.length <= 8
    ? rungs.join('\n')
    : rungs.slice(0, 8).join('\n') + '\n      … ' + tl('{n}줄 접힘', { n: rungs.length - 8 });
}
// Location match-rate badge: hidden at 90% or above (a number on a location you can trust is just noise). Below that,
// '위치 불확실'; below 30%, the warning color. The description is whole sentences in this order: how the place was
// found (coordinates, text, the figure map, or a method this page does not know, named as it came), how much of the
// drag it matches (the line paths: the dragged words in these lines, rarer words weighing more; the map: the dragged
// area inside the chosen element), that it may be far off (only below 30%), and what to check. Shared by the composer
// panel and cards. No score is no measure, so no badge: there was nothing to weigh (a picture, or words too common to
// name a place). A SyncTeX pin with a score of 0 and no quote is read as one with no score. A map pick also hides -
// below 90% - when the pick answer says nothing is in doubt (mapSure): the element's share of the drag is at least
// VIA_SURE_SCORE, the drag covers at least VIA_SURE_FILL of the element (`fill`, the element side: a drag with a margin
// all round a small element, which never reaches 90% of the drag), and no other element competes for the drag (`rival`
// false: not an ancestor or descendant, a candidate within 0.1 of the score or one the drag holds nearly whole -
// docs/handbook/domain.md §그림 문서의 요소 pick). A pick is not taken for sure on its share alone: a drag round a
// small element can leave it out of the candidates and choose the big box behind it with a large share of the drag,
// while the drag covers little of that box. The two limits are the lowest that hide no wrong pick over a figure set's
// real map and held-out drags. A pin without fill and rival keeps 90%.
const VIA_HIDE = 90,
  VIA_WARN = 30,
  VIA_SURE_SCORE = 75,
  VIA_SURE_FILL = 95;
/** Whether a map pick that is under VIA_HIDE is surely the element the drag meant (see above). */
function mapSure(pick: any, percent: number) {
  return (
    pick.via === VIA.MAP &&
    pick.rival === false &&
    typeof pick.fill === 'number' &&
    percent >= VIA_SURE_SCORE &&
    Math.round(pick.fill * 100) >= VIA_SURE_FILL
  );
}
function viaTag(pick) {
  if (!pick.via || pick.score == null || (pick.via === VIA.SYNCTEX && !pick.score && !pick.quote)) return null;
  const percent = Math.round((+pick.score || 0) * 100);
  if (percent >= VIA_HIDE || mapSure(pick, percent)) return null;
  const low = percent < VIA_WARN;
  const lines = pick.via === VIA.SYNCTEX || pick.via === VIA.TEXT,
    map = pick.via === VIA.MAP;
  const how =
    pick.via === VIA.SYNCTEX
      ? tr(T.synctex)
      : pick.via === VIA.TEXT
        ? tr(T.text)
        : map
          ? tr(T.map)
          : tl('이 화면이 모르는 방법({via})으로 찾은 위치입니다.', { via: pick.via });
  const match = lines
    ? tl('드래그한 글자 중 {pct}%가 이 줄들에 있습니다(드문 낱말일수록 크게 셉니다).', { pct: percent })
    : map
      ? tl('드래그한 영역 중 {pct}%가 이 요소 안에 있습니다.', { pct: percent })
      : tl('드래그와 맞는 정도는 {pct}%입니다.', { pct: percent });
  const check = lines
    ? tr('원문 칸에서 고칠 곳이 이 줄들에 들어 있는지 확인하세요.')
    : map
      ? tr('고른 상자가 고칠 곳을 덮는지 확인하세요.')
      : tr('고칠 곳이 이 범위에 들어 있는지 확인하세요.');
  return {
    t: tr('위치 불확실'),
    tip: [how, match, ...(low ? [tr('위치가 많이 어긋났을 수 있습니다.')] : []), check].join(' '),
    low,
  };
}
export {
  drawLadder,
  kindFor,
  levelLabel,
  lvOf,
  rangeCap,
  refetchSnip,
  rng,
  scopeLabel,
  segReveal,
  setCap,
  snipText,
  useLevel,
  viaTag,
  wireScope,
};
