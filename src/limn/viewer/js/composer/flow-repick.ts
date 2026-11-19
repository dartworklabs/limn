// ------------------------------------------------ Re-place location
// Shows the re-place banner with markup (Html) as its content.
import {
  DOC,
  LAYOUT,
  COARSE_POINTER_QUERY,
  META,
  PICKSEQ,
  REPICK,
  SWITCHSEQ,
  captureVisit,
  currentVisit,
  findAnyPin,
  isFigureKind,
  setPickseq,
  setRepick,
  setRepickBox,
  setRepickCandidate,
  COMPOSE,
  EDITOR,
} from '../app/state.ts';
import { translateTemplate } from '../platform/i18n.ts';
import { api, isRefusal } from '../platform/api.ts';
import { bannerNote, quietNote } from '../platform/notices.ts';
import { switchDoc } from '../documents/flow-switch.ts';
import { setSelectMode, setSide } from '../layout/flow.ts';
import { kindFor } from './view-levels.ts';
import { figureFields, isFrac, pinPlace, repickElement } from '../pdf/view-figure.ts';
import { cancelSelection } from './flow-selection.ts';
import { NOTICE_HOST, NOTICE_KIND } from '../platform/tables.ts';
import { $ } from '../platform/dom.ts';
import { LAYOUT_MODE, PIN_STATE } from '../app/rules-tables.ts';
import { lineRange, markMovable } from '../app/rules-pins.ts';
import { isRegion } from '../documents/state.ts';
import { levelOf } from '../documents/rules.ts';
import { composerPins, pinFields } from './state-seams.ts';
import { clearSelectionParts } from '../pdf/input-selection.ts';
import { bannerRepick, cancelRepick } from './flow-repick-banner.ts';
// Where pin `id` stands now and whether it is a region pin, for a press on its number badge - what the pages ask
// through the seam before they let that press become a drag (pdf/input-selection.ts badgeMove,
// docs/adr/0050-pin-badge-drag-reposition.md D1). null when that press places nothing: a figure document (a figure
// pin's place comes from its element map, which this does not touch), a pin this tab does not have, a pin whose place
// is fixed (markMovable - a verdict, a closed or an awaiting-review pin, the same judgement that hides [위치 다시
// 잡기]), a region pin whose box has no size to move, or a finger outside the re-place mode for that very pin.
//
// A line pin needs no box of its own: what its drag sends is the probe at the pointer (D3), and the box the person
// sees it leave is its range's, which the pin list answers. A pin saved without a `frac` - an agent's, or one an
// older client wrote - is dragged like any other.
function badgeMovePin(id: number, mouse: boolean) {
  if (isFigureKind(META ? META.kind : undefined)) return null;
  const pin = findAnyPin(id);
  if (!pin || !markMovable(pin)) return null;
  if (!mouse && !(REPICK && REPICK.id === pin.id)) return null;
  const at = pinPlace(pin),
    region = isRegion(pin),
    frac = isFrac(at.frac) ? at.frac.slice() : [];
  if (region && !(frac.length === 4 && frac[2] > 0 && frac[3] > 0)) return null;
  return { frac, region };
}
// A second drag on the badge of a pin whose re-place is already open: the place that banner is offering is not the
// one the hand is choosing now, so it goes and the banner goes back to asking. Without this the confirm stands
// through the whole drag and saves the place before it (docs/adr/0050-pin-badge-drag-reposition.md D6: nothing is
// saved that the person has not been shown).
//
// **The drag before it may still be asking.** Its answer would arrive mid-drag and put that confirm up, so the
// question goes with the answer: raising PICKSEQ is what tells that continuation it is no longer the one being
// waited for (flow-pick.ts pick). This runs whether or not a place is on show, because an answer on its way is
// exactly the case where there is none yet.
//
// The mode itself is left exactly as it is. On touch it was turned on by [위치 다시 잡기], and taking it down and up
// again mid-drag would put the sheet back over the page and lose the revision the edit card holds.
// The box goes with the place. It is what the page showed as '새 위치', and a drag that is cancelled - a second
// finger, a cancelled pointer - takes only its own box away, so a box left here would stand on the pages as the
// place of a question nobody is asking any more, under a banner asking for another one.
function restartRepick(id: number) {
  if (!REPICK || REPICK.id !== id) return;
  setPickseq(PICKSEQ + 1);
  clearSelectionParts('repick');
  if (REPICK.box) REPICK.box.remove();
  setRepickBox(REPICK, null);
  setRepickCandidate(REPICK, null);
  bannerRepick();
}
// Turns the re-place mode on for pin `id` from a drag on its number badge that is already moving its box
// (pdf/input-selection.ts badgeDragBegin). It clears an unfinished selection first, as startRepick does, but asks for
// no drag of its own: the drag under way is the new place. Touch selection mode and the sheet are left as they are -
// the person is holding the badge, not about to start a drag - and the pin's own revision is the base the drop saves
// against, there being no edit card to read it from (docs/adr/0050-pin-badge-drag-reposition.md D6). Does nothing for
// a pin this tab does not have.
function repickFromBadge(id: number) {
  const pin = findAnyPin(id);
  if (!pin) return;
  if (COMPOSE.picking || (!COMPOSE.current && !$('#composer').hidden)) cancelSelection(false);
  if (REPICK) cancelRepick();
  setRepick({
    id: pin.id,
    from: { lo: pin.lo, hi: pin.hi, page: pinPlace(pin).page, region: isRegion(pin) },
    box: null,
    cand: null,
    base_rev: pin.rev || 0,
  });
  bannerRepick();
}
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
    base_rev: EDITOR.current.base_rev || 0,
  });
  bannerRepick();
  if (COARSE_POINTER_QUERY.matches) setSelectMode(true);
  if (LAYOUT === LAYOUT_MODE.NARROW) setSide(false);
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
    rung = levelOf(candidate, candidate.default_level),
    level = rung || candidate;
  const visit = captureVisit(),
    editing = EDITOR.current;
  let loc: Record<string, unknown> = {
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
    scope: (rung && rung.level) || null,
    kind: rung && rung.level ? kindFor(rung.level, rung.env) : candidate.kind,
  };
  if (!loc.scope) delete loc.scope;
  if (isRegion(candidate))
    loc = {
      page: candidate.page,
      frac: candidate.frac,
      quote: candidate.quote,
      pdf_build: candidate.pdf_build || undefined,
    }; // view-only: only the region is re-placed
  // a new loc names its element or none: a loc without el drops the pin's el
  figureFields(loc, repickElement(candidate), isRegion(candidate) || !level.el ? null : level);
  // The revision this save is against: an open edit card for that pin keeps the current one, and a re-place a badge
  // drag began has none, so it carries the pin's own (docs/adr/0050-pin-badge-drag-reposition.md D6).
  const base = EDITOR.current && EDITOR.current.id === repick.id ? EDITOR.current.base_rev : repick.base_rev;
  try {
    const { status, data } = await api('POST /api/pins/{id}/edit', {
      id: repick.id,
      body: { loc, base_rev: base },
      what: '위치 바꾸기',
      where: NOTICE_HOST.LIST,
      expect: [409],
      intent: 'loc',
    });
    if (status === 409) {
      bannerNote(
        NOTICE_HOST.LIST,
        isRefusal(data) && data.error === PIN_STATE.DONE
          ? '닫힌 핀은 위치를 바꿀 수 없습니다'
          : '다른 쪽이 이 핀을 먼저 바꿨습니다 — 최신 값을 불러왔습니다',
        NOTICE_KIND.WARN,
      );
      if (EDITOR.current === editing && editing && data.pin) editing.base_rev = data.pin.rev;
      if (currentVisit(visit) && REPICK === repick) cancelRepick();
      await composerPins().load();
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
      pinFields().snipEdit(true);
    }
    quietNote(
      translateTemplate('핀 #{id} 위치를 {where} 로 바꿨습니다', {
        id: pin.id,
        where: isRegion(pin)
          ? translateTemplate('쪽 {page} 영역', { page: pinPlace(pin).page })
          : lineRange(pin.lo, pin.hi),
      }),
    );
    await composerPins().load();
  } catch (error) {}
}
export { applyRepick, badgeMovePin, repickFromBadge, restartRepick, startRepick };
