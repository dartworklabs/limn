// ------------------------------------------------ Re-place location
// Shows the re-place banner with markup (Html) as its content.
import {
  $,
  DOC,
  LAYOUT,
  LAYOUT_MODE,
  MQ_COARSE,
  NOTICE_HOST,
  NOTICE_KIND,
  PICKSEQ,
  PIN_STATE,
  REPICK,
  SWITCHSEQ,
  T,
  captureVisit,
  currentVisit,
  setPickseq,
  setRepick,
} from './core.ts';
import { html, setHtml } from './markup.ts';
import { tl, tr } from './i18n.ts';
import { api } from './api.ts';
import { bannerNote, quietNote } from './notices.ts';
import { isRegion } from './doc-tabs.ts';
import { switchDoc } from './doc-switch.ts';
import { setSelMode, setSide } from './layout.ts';
import { kindFor, levelLabel, lvOf, rng, scopeLabel } from './levels.ts';
import { figureFields, pinPlace, repickEl, snapBox } from './figure.ts';
import { isMdDoc, mdSelMark, mdSelShown } from './md-surface.ts';
import { COMPOSE, cancelSelection } from './composer.ts';
import { loadPins } from './list.ts';
import { EDITOR, editSnip } from './edit.ts';
function banner(markup) {
  const bannerBox = $('#banner');
  setHtml(bannerBox, markup);
  bannerBox.hidden = false;
}
function bannerRepick(err?) {
  if (!REPICK) return;
  const line = err ? html`<span class="errline flush">${err}</span>` : '';
  banner(
    html`<span>${isMdDoc() ? tl('핀 #{id} 의 새 위치를 문서에서 고르세요 · Esc 취소', { id: REPICK.id }) : tl('핀 #{id} 의 새 위치를 PDF에서 드래그하세요 · Esc 취소', { id: REPICK.id })}</span>${line}<span class="sp"></span><button class="btn-sm" data-act="rp-cancel" data-tip="위치 다시 잡기를 그만둡니다 (Esc)">취소</button>`,
  );
}
// The re-place banner compares the current and the new place (lines as the composer writes them, rng: L9, L3-L5); on a
// figure the '새 위치' box snaps to the new element, and on the Markdown surface the candidate's lines are marked
// (mdSelShown). A candidate of the other shape (a region for a line pin, lines for a region pin) is dropped and the
// banner asks for another drag: /edit never changes a pin's shape, so no request it would refuse is offered.
function bannerCompare() {
  const repick = REPICK,
    candidate = repick && repick.cand;
  if (!repick || !candidate) return;
  const level = lvOf(candidate, candidate.default_level) || candidate,
    isRegionPick = isRegion(candidate);
  if (isRegionPick !== !!repick.from.region) {
    repick.cand = null;
    bannerRepick(tr(T.shape));
    return;
  }
  const where = isRegionPick
    ? tl('지금 쪽 {from} · 새 쪽 {to} 영역', { from: repick.from.page, to: candidate.page })
    : tl('지금 {from} · 새 {to}', { from: rng(repick.from.lo, repick.from.hi), to: rng(level.lo, level.hi) });
  const what = isRegionPick
    ? candidate.quote
      ? String(candidate.quote).slice(0, 40)
      : tr('글자 없는 영역')
    : level.label
      ? levelLabel(level.label)
      : scopeLabel(candidate);
  const acts = html`<button class="btn-sm btn-default" data-act="rp-apply" data-tip="번호와 메모는 그대로 두고 위치만 바꿉니다">이 위치로 바꾸기</button><button class="btn-sm" data-act="rp-cancel" data-tip="위치 다시 잡기를 그만둡니다 (Esc)">취소</button>`;
  banner(
    html`<span class="loc" data-tip="지금 위치 → 새 위치" tabindex="0">${where}</span><span class="dim">(${what})</span><span class="sp"></span>${acts}`,
  );
  snapBox(repick.box, repickEl(candidate));
  mdSelMark(mdSelShown());
} // the Markdown surface marks the candidate's lines as its box
// On touch, selection mode is turned on during a re-place, and narrow collapses the sheet to reveal the page (the
// banner stays visible even on the collapsed sheet).
async function startRepick() {
  if (!EDITOR.current) return;
  if (EDITOR.current.doc && EDITOR.current.doc !== DOC) {
    const editing = EDITOR.current,
      opening = switchDoc(editing.doc),
      visit = SWITCHSEQ;
    await opening;
    if (DOC !== editing.doc || EDITOR.current !== editing || visit !== SWITCHSEQ) return;
  } // selection happens on that pin's document
  // Repick clears an unfinished drag or error panel; a completed selection remains available if repick is cancelled.
  if (COMPOSE.picking || (!COMPOSE.current && !$('#composer').hidden)) cancelSelection(false);
  if (REPICK) cancelRepick();
  setRepick({
    id: EDITOR.current.id,
    from: { lo: EDITOR.current.lo, hi: EDITOR.current.hi, page: EDITOR.current.page, region: !!EDITOR.current.region },
    box: null,
    cand: null,
  });
  bannerRepick();
  if (MQ_COARSE.matches) setSelMode(true);
  if (LAYOUT === LAYOUT_MODE.NARROW) setSide(false);
}
// Cancelling also invalidates an in-flight /api/pick; its continuation must not render a banner for the cleared
// re-place. The Markdown surface's mark goes back to the composer's selection, if any.
function cancelRepick() {
  const was = !!REPICK;
  if (was) setPickseq(PICKSEQ + 1);
  if (REPICK && REPICK.box) REPICK.box.remove();
  setRepick(null);
  $('#banner').hidden = true;
  if (was) mdSelMark(mdSelShown());
  if (was) {
    if (!COMPOSE.current) setSelMode(false);
    if (EDITOR.current && LAYOUT !== LAYOUT_MODE.WIDE) setSide(true);
  }
}
// Sends the re-place candidate as the pin's new location (POST /api/pins/<id>/edit with `loc` and the `base_rev` the
// editor holds). The loc carries the candidate's range, its element and that element's box on a figure, or only the
// region on a view-only page; one without an element drops the pin's el. On 409 a warning banner on top of the panel
// says why, and it keeps the editor's rev current and reloads the pins; on success (silent: the mark moves; read out
// only) it syncs the open editor with the stored pin. Does nothing without a candidate.
async function applyRepick() {
  const repick = REPICK;
  if (!repick || !repick.cand) return;
  const candidate = repick.cand,
    level = lvOf(candidate, candidate.default_level) || candidate;
  const visit = captureVisit(),
    editing = EDITOR.current;
  let loc = {
    file: candidate.file,
    page: candidate.page,
    lo: level.lo,
    hi: level.hi,
    raw_lo: candidate.raw_lo,
    raw_hi: candidate.raw_hi,
    via: candidate.via,
    score: candidate.score,
    fill: candidate.fill,
    rival: candidate.rival,
    frac: candidate.frac,
    pdf_build: candidate.pdf_build || undefined,
    quote: candidate.quote,
    scope: level.level || null,
    kind: level.level ? kindFor(level.level, level.env) : candidate.kind,
  } as Record<string, unknown>;
  if (!loc.scope) delete loc.scope;
  if (isRegion(candidate))
    loc = {
      page: candidate.page,
      frac: candidate.frac,
      quote: candidate.quote,
      pdf_build: candidate.pdf_build || undefined,
    }; // view-only: only the region is re-placed
  // a new loc names its element or none: a loc without el drops the pin's el
  figureFields(loc, repickEl(candidate), isRegion(candidate) || !level.el ? null : level);
  const base = EDITOR.current && EDITOR.current.id === repick.id ? EDITOR.current.base_rev : 0;
  try {
    const { status, data } = await api('/api/pins/' + repick.id + '/edit', {
      method: 'POST',
      body: { loc, base_rev: base },
      what: '위치 바꾸기',
      where: NOTICE_HOST.LIST,
      expect: [409],
      intent: 'loc',
    });
    if (status === 409) {
      bannerNote(
        NOTICE_HOST.LIST,
        data && data.error === PIN_STATE.DONE
          ? '닫힌 핀은 위치를 바꿀 수 없습니다'
          : '다른 쪽이 이 핀을 먼저 바꿨습니다 — 최신 값을 불러왔습니다',
        NOTICE_KIND.WARN,
      );
      if (EDITOR.current === editing && editing && data.pin) editing.base_rev = data.pin.rev;
      if (currentVisit(visit) && REPICK === repick) cancelRepick();
      await loadPins();
      return;
    }
    const pin = data.pin;
    if (currentVisit(visit) && REPICK === repick) cancelRepick();
    if (EDITOR.current === editing && editing && editing.id === pin.id) {
      Object.assign(editing, {
        base_rev: pin.rev,
        lo: pin.lo,
        hi: pin.hi,
        file: pin.file,
        name: pin.name,
        scope: pin.scope || null,
        page: pinPlace(pin).page,
        quote: pin.quote || '',
        pinEl: pin.el || null,
      });
      editing.orig.lo = pin.lo;
      editing.orig.hi = pin.hi;
      editing.orig.scope = pin.scope || null;
      editSnip(true);
    }
    quietNote(
      tl('핀 #{id} 위치를 {where} 로 바꿨습니다', {
        id: pin.id,
        where: isRegion(pin)
          ? tl('쪽 {page} 영역', { page: pinPlace(pin).page })
          : rng(pin.lo as number, pin.hi as number),
      }),
    );
    await loadPins();
  } catch (error) {}
}
export { applyRepick, banner, bannerCompare, bannerRepick, cancelRepick, startRepick };
