// ------------------------------------------------ The claim badges' clock
// A claimed pin's badge says how long its claim has left or has run over; this keeps that text current.
import { $$ } from '../platform/dom.ts';
import { OPEN_ALL } from '../app/state.ts';
import { drawPins } from './flow-list.ts';
import { claimActive, claimInfo } from './view-card-parts.ts';
// The remaining/elapsed minutes change with time - only the badge text is updated every 30 seconds (the card isn't
// redrawn). The list is redrawn if any pin's lock has expired.
function tickClaims() {
  if (document.hidden) return;
  let gone = false;
  $$('.badge-claimed[data-claim]').forEach((badge) => {
    const pin = OPEN_ALL.find((listed) => listed.id === +badge.dataset.claim);
    if (!pin || !claimActive(pin)) {
      gone = true;
      return;
    }
    const claim = claimInfo(pin);
    badge.querySelector('.ct').textContent = claim.t;
    badge.dataset.tip = claim.tip;
    badge.classList.toggle('late', claim.late);
  });
  if (gone) drawPins();
}
setInterval(tickClaims, 30000);
