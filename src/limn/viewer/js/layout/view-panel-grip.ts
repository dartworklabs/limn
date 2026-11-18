import { SIDE_OPEN } from '../app/state.ts';
import { $ } from '../platform/dom.ts';
import { translate } from '../platform/i18n.ts';
import type { PanelBounds } from './flow-panel-size.ts';

// The width last shown and its bounds - the handle's ARIA value while the panel is open (gripAria).
let SIDE_SHOWN: { w: number; min: number; max: number } | null = null;
// Shows a panel width without saving it: #right, --side-w, and the handle's ARIA while the panel is open.
function showSideWidth(width: number, bounds: PanelBounds) {
  $('#right').style.width = width + 'px';
  document.documentElement.style.setProperty('--side-w', width + 'px');
  SIDE_SHOWN = { w: width, min: bounds.min, max: bounds.max };
  if (SIDE_OPEN) gripAria();
}
// The open handle's hint (the markup's, translated by translate()); empty text if the markup gave none.
const GRIP_TIP = $('#grip').dataset.tip ?? '';
// The handle's ARIA as a window splitter: the panel width, or 0 (named '패널 폭 · 접힘') while collapsed - a collapsed
// wide panel's handle is the rail at the right edge, and its hint says how to bring the panel back.
function gripAria() {
  const grip = $('#grip'),
    shown = SIDE_SHOWN;
  if (!SIDE_OPEN) {
    grip.setAttribute('aria-valuenow', '0');
    grip.setAttribute('aria-valuemin', '0');
    grip.setAttribute('aria-label', translate('패널 폭') + ' · ' + translate('접힘'));
    grip.dataset.tip = translate(
      '끌어서 핀 패널을 폅니다. 두 번 클릭(터치는 탭)하거나 Enter 를 누르면 전에 쓰던 폭으로 폅니다',
    );
    return;
  }
  grip.setAttribute('aria-label', translate('패널 폭'));
  grip.dataset.tip = translate(GRIP_TIP);
  if (shown) {
    grip.setAttribute('aria-valuenow', String(shown.w));
    grip.setAttribute('aria-valuemin', String(shown.min));
    grip.setAttribute('aria-valuemax', String(shown.max));
  }
}
export { gripAria, showSideWidth };
