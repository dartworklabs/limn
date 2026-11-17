// ----------------------------------- Mark badges on the pages: inside or beside a mark, and how far a press reaches
import { $, findAll } from '../platform/dom.ts';
import { COARSE_POINTER_QUERY } from '../app/state.ts';
// Whether a mark's number badge goes inside the mark (docs/handbook/viewer.md §모바일 레이아웃): markLeft is the mark's
// left as a fraction of the page, pageWidth the page width, pad the room left of the page in the PDF scroller (its
// margin) and reach how far the badge hangs left of the mark (28px on touch, 24px with a mouse). Only when the margin
// and the offset together are short of the reach would the badge be clipped, and only then does it sit in the mark's
// top-left corner - inside, it covers the text the mark points at. Pure.
function markBadgeIn(markLeft: number, pageWidth: number, pad: number, reach: number) {
  return markLeft * pageWidth + pad < reach;
}
// A page's room: the room left of it in the PDF scroller, in scroll coordinates (a horizontal scroll does not count),
// its width, and the badge's reach for the primary pointer: {pad, w, reach}. Pages have their own widths and a narrower
// page is centred, so each page has its own margin. null for a page that is not laid out (the changes view hides the
// pages).
function markBadgeRoom(page: Element | null) {
  const pane = $('#left');
  if (!pane || !page || !page.getClientRects().length) return null;
  const rect = page.getBoundingClientRect();
  return {
    pad: rect.left - pane.getBoundingClientRect().left - pane.clientLeft + pane.scrollLeft,
    w: rect.width,
    reach: COARSE_POINTER_QUERY.matches ? 28 : 24,
  };
}
// A badge's room on each side (markHitRooms): the px a neighbour leaves it, null where none limits it.
type HitRoom = { t: number | null; r: number | null; b: number | null; l: number | null };
// How far each mark badge's press area may reach on each side (docs/handbook/viewer.md §모바일 레이아웃): boxes are the
// badges' drawn boxes {x,y,w,h} in one coordinate space and reach the press area's full size. Two badges whose press
// areas would overlap split the gap between their drawn boxes in half, along the axis on which their centres are
// further apart - so a press goes to the nearer badge, and a badge with no close neighbour keeps its whole area.
// Returns one {t,r,b,l} per box: the room in px on that side, or null where no neighbour limits it; 0 where the drawn
// boxes touch or overlap. Pure.
function markHitRooms(boxes: { x: number; y: number; w: number; h: number }[], reach: number) {
  const rooms = boxes.map(() => ({ t: null, r: null, b: null, l: null }));
  const cut = (room: HitRoom, side: keyof HitRoom, value: number) => {
    room[side] = room[side] === null ? value : Math.min(room[side], value);
  };
  boxes.forEach((box, index) => {
    for (let j = index + 1; j < boxes.length; j++) {
      const other = boxes[j];
      const apartX = other.x + other.w / 2 - (box.x + box.w / 2),
        apartY = other.y + other.h / 2 - (box.y + box.h / 2);
      if (Math.abs(apartX) >= reach || Math.abs(apartY) >= reach) continue;
      if (Math.abs(apartY) >= Math.abs(apartX)) {
        const room = Math.max(0, (Math.abs(apartY) - (box.h + other.h) / 2) / 2);
        cut(rooms[index], apartY >= 0 ? 'b' : 't', room);
        cut(rooms[j], apartY >= 0 ? 't' : 'b', room);
      } else {
        const room = Math.max(0, (Math.abs(apartX) - (box.w + other.w) / 2) / 2);
        cut(rooms[index], apartX >= 0 ? 'r' : 'l', room);
        cut(rooms[j], apartX >= 0 ? 'l' : 'r', room);
      }
    }
  });
  return rooms;
}
// Gives every drawn badge its sides' room (markHitRooms) as --room-t/-r/-b/-l, which the badge's ::after caps its reach
// by (components.css); a side no neighbour limits has no property and reaches the whole way. The boxes are read in the
// viewport, so badges on two pages are neighbours too; the press area is the touch one, 44px (a mouse's 24px lies
// inside it). Badges that are not laid out (the changes view hides the pages) have no boxes to read: nothing is set,
// and setViewMode measures when the pages show again.
function markHitSides() {
  const badges = findAll(document, '.mark button.mark-jump', HTMLElement);
  if (badges.some((badge) => !badge.getClientRects().length)) return;
  const rooms = markHitRooms(
    badges.map((badge) => {
      const rect = badge.getBoundingClientRect();
      return { x: rect.left, y: rect.top, w: rect.width, h: rect.height };
    }),
    44,
  );
  badges.forEach((badge, index) => {
    const room = rooms[index],
      px = (value: number | null) => (value === null ? '' : value + 'px'); // '' takes the property off
    badge.style.setProperty('--room-t', px(room.t));
    badge.style.setProperty('--room-r', px(room.r));
    badge.style.setProperty('--room-b', px(room.b));
    badge.style.setProperty('--room-l', px(room.l));
  });
}
export { markBadgeRoom, markBadgeIn, markHitSides };
