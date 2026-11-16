// --------------------------------------- Pins changed elsewhere: what the status line says between two list refreshes
import { pinState } from '../app/rules-pins.ts';
import { PIN_STATE, ELEMENT_SYNC } from '../app/rules-tables.ts';
import { translateTemplate, translate, josa, josaName } from '../platform/i18n.ts';
import { groupNote } from '../platform/notices.ts';
import { NOTICE_KIND, NOTICE_LIFE, NOTICE_DOT, EVENT_TYPE } from '../platform/tables.ts';
import { gotoReview } from './flow-list.ts';
import { who } from '../app/state-people.ts';
import { restorePin } from './flow-actions.ts';
import { openTrash } from './view-cards.ts';
import { countPinMove } from '../documents/flow-updates.ts';
// A list comparison's group without the pins whose events a message of a higher rank says (groupNote's less): the pins
// named '<type>:<id>' leave group[field] - numbers or pins - and each of `also` beside them, or null when none is left.
// Pure.
function newsWithout(type: string, field: string, ...also: string[]): (group: any, keys: string[]) => any {
  return (group, keys) => {
    const keep = group[field].map((x: any) => !keys.includes(type + ':' + (typeof x === 'number' ? x : x.id)));
    if (!keep.some(Boolean)) return null;
    const out = { ...group };
    [field, ...also].forEach((key) => {
      out[key] = group[key].filter((_: any, index: number) => keep[index]);
    });
    return out;
  };
}
// This tab's own close/drop/reopen/restore already said so where it happened, so the next loadPins()'s notePinChanges
// never announces the same transition again: only the first notePinChanges judgment right after markMine(id) is
// swallowed (consumeMine removes it as soon as it's confirmed), and if that judgment hasn't arrived after 10 seconds (a
// lost response), it's given up on and later values are announced normally. An action from another tab isn't in this
// map, so it's shown as usual.
const MY_ACTIONS = new Map();
function markMine(id) {
  MY_ACTIONS.set(id, Date.now() + 10000);
}
function consumeMine(id) {
  const until = MY_ACTIONS.get(id);
  if (until === undefined) return false;
  MY_ACTIONS.delete(id);
  return Date.now() <= until;
}
// Says on the status line what changed between two list refreshes (docs/handbook/viewer.md §알림 자리): pins sent to
// review ([보기], a dot on [검토 M]), dropped ([되살리기]) or closed by someone else, and an open pin whose location or
// figure element was lost or whose lines moved. What needs a look stays until [x] or its action and dots [핀 N];
// passing news (closed elsewhere, lines moved) goes after NOTICE_MS. An action this tab performed is swallowed
// (markMine).
function notePinChanges(previous, listed, dropped) {
  // previous is only the "open pins" this tab saw last time (PINS never holds done ones); listed is every open+closed
  // pin (all=1) from this GET. An id of previous that is in listed with done=true was completed; one not in listed at
  // all (neither open nor closed) was dropped. The two are told apart, so a pin a co-author deleted is never announced
  // to its author as "#N 이 완료되었습니다".
  if (!previous || !previous.length) return;
  const byId = new Map<number, Pin>(previous.map((pin) => [pin.id, pin]));
  const known = new Map<number, Pin>((listed || []).map((pin) => [pin.id, pin]));
  const dropById = new Map<number, Pin>((dropped || []).map((pin) => [pin.id, pin]));
  const closed: number[] = [],
    droppedIds: number[] = [],
    reviewed: number[] = [];
  byId.forEach((_, id) => {
    const current = known.get(id),
      state = current && pinState(current);
    if (current && state !== PIN_STATE.OPEN) {
      if (!consumeMine(id)) (state === PIN_STATE.REVIEW ? reviewed : closed).push(id);
    } else if (!current) {
      if (!consumeMine(id)) droppedIds.push(id);
    }
  });
  // Each kind of change is one message however many pins and polls it spans (groupNote): up to three pins by number,
  // more as a count with the first numbers after it ('핀 12개가 완료되었습니다 — #3, #5, #8 외 9개').
  const ids = (numbers: number[]) =>
    numbers
      .slice(0, 3)
      .map((id) => '#' + id)
      .join(', ') + (numbers.length > 3 ? ' ' + translateTemplate('외 {n}개', { n: numbers.length - 3 }) : '');
  const some = (numbers: number[], one, many) =>
    numbers.length <= 3
      ? translateTemplate(one, { ids: numbers.join(', #'), n: numbers.length })
      : translateTemplate(many, { n: numbers.length }) + ' — ' + ids(numbers);
  const merge = (older: any, newer: any) => ({ ...newer, ids: [...new Set([...older.ids, ...newer.ids])] });
  if (closed.length)
    groupNote(
      'done',
      { ids: closed },
      (group) => ({
        msg: some(group.ids, '#{ids} 이 완료되었습니다', '핀 {n}개가 완료되었습니다'),
        kind: NOTICE_KIND.OK,
        act: null,
        o: {
          life: NOTICE_LIFE.TIMER,
          dot: NOTICE_DOT.SIDE,
          literal: true,
          brief: translateTemplate('완료 {n}', { n: group.ids.length }),
        },
      }),
      merge,
    );
  if (reviewed.length)
    groupNote(
      'review',
      { ids: reviewed },
      (group) => ({
        msg:
          group.ids.length <= 3
            ? translateTemplate('#{ids} 이 검토 대기로 넘어왔습니다 — 결과를 보고 [확인]하세요', {
                ids: group.ids.join(', #'),
                n: group.ids.length,
              })
            : translateTemplate('핀 {n}개가 검토 대기로 넘어왔습니다', { n: group.ids.length }) +
              ' — ' +
              ids(group.ids),
        kind: NOTICE_KIND.OK,
        act: { label: '보기', tip: '검토 대기 핀으로 갑니다', fn: gotoReview },
        o: {
          keys: group.ids.map((id) => EVENT_TYPE.REVIEW_REQUESTED + ':' + id),
          dot: NOTICE_DOT.RV,
          literal: true,
          brief: translateTemplate('검토 대기 {n}', { n: group.ids.length }),
        },
      }),
      merge,
      newsWithout(EVENT_TYPE.REVIEW_REQUESTED, 'ids'),
    );
  // One dropped pin offers [되살리기]; several, the Trash they are in.
  if (droppedIds.length)
    groupNote(
      'drop',
      {
        ids: droppedIds,
        names: droppedIds.map((id) => {
          const rec = dropById.get(id);
          return (rec && who(rec.dropped_by)) || translate('다른 세션');
        }),
      },
      (group) => {
        const name = [...new Set(group.names)].join(', '),
          one = group.ids.length === 1,
          id = group.ids[0];
        return {
          msg: one
            ? translateTemplate('#{id}{o} {name}{p} 삭제함', {
                id,
                o: josa(id, '을', '를'),
                name,
                p: josaName(name, '이', '가'),
              })
            : translateTemplate('핀 {n}개를 {name}{p} 삭제함', {
                n: group.ids.length,
                name,
                p: josaName(name, '이', '가'),
              }) +
              ' — ' +
              ids(group.ids),
          kind: NOTICE_KIND.WARN,
          act: one
            ? { label: '되살리기', wait: true, fn: () => restorePin(id) }
            : { label: '휴지통', tip: '지운 핀을 휴지통에서 봅니다', fn: () => openTrash(id) },
          o: {
            keys: group.ids.map((id) => EVENT_TYPE.DROPPED + ':' + id),
            dot: NOTICE_DOT.SIDE,
            literal: true,
            brief: translateTemplate('삭제됨 {n}', { n: group.ids.length }),
          },
        };
      }, // translateTemplate() spoke the UI language; the name is as written
      (older, newer) => {
        // names stay beside their ids
        const add = newer.ids.map((id, index) => index).filter((index) => !older.ids.includes(newer.ids[index]));
        return {
          ids: [...older.ids, ...add.map((index) => newer.ids[index])],
          names: [...older.names, ...add.map((index) => newer.names[index])],
        };
      },
      newsWithout(EVENT_TYPE.DROPPED, 'ids', 'names'),
    );
  const lost: Pin[] = [],
    gone: Pin[] = [],
    moved: { id: number; delta: string; p: Pin }[] = [];
  (listed || [])
    .filter((pin) => pinState(pin) === PIN_STATE.OPEN)
    .forEach((pin) => {
      const was = byId.get(pin.id);
      if (!was) return;
      if (!was.stale && pin.stale) {
        lost.push(pin);
        return;
      }
      if (was.el_sync !== ELEMENT_SYNC.LOST && pin.el_sync === ELEMENT_SYNC.LOST) {
        gone.push(pin);
        return;
      } // a re-render lost a figure pin's element
      const move = /^moved ([+-]\d+)$/.exec(pin.sync || ''),
        earlierMove = /^moved ([+-]\d+)$/.exec(was.sync || '');
      if (move && pin.el_sync !== ELEMENT_SYNC.OK && (!earlierMove || earlierMove[1] !== move[1]))
        moved.push({ id: pin.id, delta: move[1], p: pin });
    });
  // A pin that lost its place asks for a new one: said on its own, and counted in its document's update message.
  lost.forEach((pin) => countPinMove(pin, true));
  gone.forEach((pin) => countPinMove(pin, true));
  const each = (numbers: number[], one, many) =>
    numbers.length === 1
      ? translateTemplate(one, { id: numbers[0] })
      : translateTemplate(many, { n: numbers.length }) + ' — ' + ids(numbers);
  if (lost.length)
    groupNote(
      'lost',
      { ids: lost.map((pin) => pin.id) },
      (group) => ({
        msg: each(group.ids, '#{id} 위치를 잃었습니다', '핀 {n}개가 위치를 잃었습니다'),
        kind: NOTICE_KIND.WARN,
        act: null,
        o: { dot: NOTICE_DOT.SIDE, literal: true, brief: translateTemplate('위치 잃음 {n}', { n: group.ids.length }) },
      }),
      merge,
    );
  if (gone.length)
    groupNote(
      'el-lost',
      { ids: gone.map((pin) => pin.id) },
      (group) => ({
        msg: each(group.ids, '#{id} 요소를 잃었습니다', '핀 {n}개가 요소를 잃었습니다'),
        kind: NOTICE_KIND.WARN,
        act: null,
        o: { dot: NOTICE_DOT.SIDE, literal: true, brief: translateTemplate('요소 잃음 {n}', { n: group.ids.length }) },
      }),
      merge,
    );
  // Lines that moved with a document's update are said in its update message; others pass by as one message.
  const said = moved.filter((x) => !countPinMove(x.p, false));
  if (said.length)
    groupNote(
      'moved',
      { moves: said.map((x) => ({ id: x.id, delta: x.delta })) },
      (group) => {
        const ms = group.moves.slice(-12);
        return {
          msg:
            ms.length === 1
              ? translateTemplate('#{id} 줄 {delta} 이동', { id: ms[0].id, delta: ms[0].delta })
              : translateTemplate('핀 {n}개 줄 이동', { n: group.moves.length }) +
                ' — ' +
                ms.map((x: any) => '#' + x.id + ' ' + x.delta).join(', '),
          kind: NOTICE_KIND.OK,
          act: null,
          o: { life: NOTICE_LIFE.TIMER, literal: true },
        };
      },
      (older, newer) => ({
        moves: [...older.moves.filter((x: any) => !newer.moves.some((y: any) => y.id === x.id)), ...newer.moves],
      }),
    );
}
// Says on the status line when a pin that was awaiting review gets confirmed (done; passing news) or reopened (until
// [x], with a dot on [핀 N]) elsewhere. An action this tab performed (markMine) is swallowed.
function noteReviewChanges(previous, listed) {
  if (!previous || !previous.length) return;
  const known = new Map<number, Pin>((listed || []).map((pin) => [pin.id, pin]));
  const ok: { id: number; by: string }[] = [],
    back: { id: number; by: string }[] = [];
  previous.forEach((pin) => {
    const current = known.get(pin.id);
    if (!current) return;
    const state = pinState(current);
    if (state === PIN_STATE.REVIEW) return;
    if (consumeMine(pin.id)) return;
    (state === PIN_STATE.DONE ? ok : back).push({
      id: pin.id,
      by: who(state === PIN_STATE.DONE ? current.confirmed_by : current.reopened_by),
    });
  });
  // Each is one message however many pins (groupNote): one pin with who did it, more as a count.
  const text = (entries: { id: number; by: string }[], one, many) =>
    entries.length === 1
      ? translateTemplate(one, { id: entries[0].id }) + (entries[0].by ? ' · ' + entries[0].by : '')
      : translateTemplate(many, { n: entries.length }) +
        ' — ' +
        entries
          .slice(0, 3)
          .map((x) => '#' + x.id)
          .join(', ') +
        (entries.length > 3 ? ' ' + translateTemplate('외 {n}개', { n: entries.length - 3 }) : '');
  const merge = (older: any, newer: any) => ({
    pins: [...older.pins, ...newer.pins.filter((x) => !older.pins.some((y) => y.id === x.id))],
  });
  if (ok.length)
    groupNote(
      'confirmed',
      { pins: ok },
      (group) => ({
        msg: text(group.pins, '#{id} 확인됨', '핀 {n}개 확인됨'),
        kind: NOTICE_KIND.OK,
        act: null,
        o: {
          life: NOTICE_LIFE.TIMER,
          dot: NOTICE_DOT.SIDE,
          literal: true,
          brief: translateTemplate('확인됨 {n}', { n: group.pins.length }),
        },
      }),
      merge,
    );
  if (back.length)
    groupNote(
      'reopened',
      { pins: back },
      (group) => ({
        msg: text(group.pins, '#{id} 다시 열림', '핀 {n}개 다시 열림'),
        kind: NOTICE_KIND.WARN,
        act: null,
        o: {
          keys: group.pins.map((x) => EVENT_TYPE.REOPENED + ':' + x.id),
          dot: NOTICE_DOT.SIDE,
          literal: true,
          brief: translateTemplate('다시 열림 {n}', { n: group.pins.length }),
        },
      }),
      merge,
      newsWithout(EVENT_TYPE.REOPENED, 'pins'),
    );
}
export { markMine, notePinChanges, noteReviewChanges };
