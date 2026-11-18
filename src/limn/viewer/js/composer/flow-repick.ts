// ------------------------------------------------ Re-place location
// Shows the re-place banner with markup (Html) as its content.
import {
  DOC,
  LAYOUT,
  COARSE_POINTER_QUERY,
  REPICK,
  SWITCHSEQ,
  captureVisit,
  currentVisit,
  setRepick,
  COMPOSE,
  EDITOR,
} from '../app/state.ts';
import { translateTemplate } from '../platform/i18n.ts';
import { api, isRefusal } from '../platform/api.ts';
import { bannerNote, quietNote } from '../platform/notices.ts';
import { switchDoc } from '../documents/flow-switch.ts';
import { setSelectMode, setSide } from '../layout/flow.ts';
import { kindFor } from './view-levels.ts';
import { figureFields, pinPlace, repickElement } from '../pdf/view-figure.ts';
import { cancelSelection } from './flow-selection.ts';
import { NOTICE_HOST, NOTICE_KIND } from '../platform/tables.ts';
import { $ } from '../platform/dom.ts';
import { LAYOUT_MODE, PIN_STATE } from '../app/rules-tables.ts';
import { lineRange } from '../app/rules-pins.ts';
import { isRegion } from '../documents/state.ts';
import { levelOf } from '../documents/rules.ts';
import { composerPins, pinFields } from './state-seams.ts';
import { bannerRepick, cancelRepick } from './flow-repick-banner.ts';
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
  const base = EDITOR.current && EDITOR.current.id === repick.id ? EDITOR.current.base_rev : 0;
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
export { applyRepick, startRepick };
