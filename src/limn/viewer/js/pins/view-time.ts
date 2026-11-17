// ------------------------------------------------ When, said on a card
// A card's times: how long ago ('3분 전') with the exact time as its tip, and a timestamp's own line, in the person's
// time zone.
import { translate, translateTemplate } from '../platform/i18n.ts';
import { html } from '../platform/markup.ts';
import { STAMP_FORM } from '../app/rules-tables.ts';
import type { Html } from '../platform/markup.ts';
// Relative time (docs/handbook/viewer.md §뜻과 모양): '방금'/'N분 전'/'N시간 전'/'N일 전', 'M-D' past a week. Absolute
// time is in the description (hover). The original string is kept in data-at and re-computed every 60 seconds
// (tickRel). The archive and the verdict line say this; a comment says stampText.
function relTime(stamp: string | null | undefined, now?: number) {
  stamp = String(stamp || '');
  const match = /^(\d{4})-(\d\d)-(\d\d)[ T](\d\d):(\d\d)/.exec(stamp);
  if (!match) return stamp;
  const then = new Date(+match[1], +match[2] - 1, +match[3], +match[4], +match[5]).getTime(),
    minutes = Math.max(0, ((now == null ? Date.now() : now) - then) / 60000);
  if (minutes < 1) return translate('방금');
  if (minutes < 60) return translateTemplate('{n}분 전', { n: Math.floor(minutes) });
  if (minutes < 24 * 60) return translateTemplate('{n}시간 전', { n: Math.floor(minutes / 60) });
  if (minutes < 7 * 24 * 60) return translateTemplate('{n}일 전', { n: Math.floor(minutes / 1440) });
  return +match[2] + '-' + +match[3];
}
function relSpan(stamp: string | undefined, className?: string, tip?: string) {
  return html`<span class="rt${className ? ' ' + className : ''}" data-at="${stamp || ''}" data-tip="${(tip ? tip + ' ' : '') + (stamp || '?')}">${relTime(stamp)}</span>`;
}
// A stored time as its wall-clock parts and the instant they name on this device ({y, mo, d, md:'MM-DD', hm:'HH:MM',
// t}), or null for a string that is no time. Pure but for the device's time zone.
function timeParts(stamp: string | null | undefined) {
  const match = /^(\d{4})-(\d\d)-(\d\d)[ T](\d\d):(\d\d)/.exec(String(stamp || ''));
  if (!match) return null;
  return {
    y: +match[1],
    mo: +match[2],
    d: +match[3],
    md: match[2] + '-' + match[3],
    hm: match[4] + ':' + match[5],
    t: new Date(+match[1], +match[2] - 1, +match[3], +match[4], +match[5]).getTime(),
  };
}
// The absolute part of a comment's time: 'MM-DD HH:MM', with the year ('2025-09-25 00:01') when it is not now's. A
// string that is no time comes back as it is. now is injected by tests.
function timeAbs(stamp: string | null | undefined, now?: number): string {
  const parts = timeParts(stamp);
  if (!parts) return String(stamp || '');
  return (
    (parts.y === new Date(now == null ? Date.now() : now).getFullYear() ? '' : parts.y + '-') +
    parts.md +
    ' ' +
    parts.hm
  );
}
// The relative part of a comment's time, relTime's words, for a time less than seven days old; else ''. now is injected
// by tests.
function timeAgo(stamp: string | null | undefined, now?: number): string {
  const parts = timeParts(stamp);
  return parts && (now == null ? Date.now() : now) - parts.t < 7 * 24 * 60 * 60000 ? relTime(stamp, now) : '';
}
// What a comment's time says (docs/handbook/viewer.md §뜻과 모양): BOTH '14시간 전 · 11-01 20:41', only the absolute
// part from seven days on; EDITED the same after '수정'; SHORT, a folded card's preview, the relative part if any, else
// the absolute.
/** @param form - a STAMP_FORM value */
function stampText(stamp: string | null | undefined, form: string, now?: number): string {
  const ago = timeAgo(stamp, now),
    abs = timeAbs(stamp, now);
  if (form === STAMP_FORM.SHORT) return ago || abs;
  const both = ago ? ago + ' · ' + abs : abs;
  return form === STAMP_FORM.EDITED ? translateTemplate('수정 {time}', { time: both }) : both;
}
// A comment's time as Html: stampText's words, kept current by tickRel, with the whole stored string as its
// description.
/** @param form - a STAMP_FORM value */
function stampSpan(stamp: string | null | undefined, form: string, className?: string): Html {
  return html`<span class="rt ts${className ? ' ' + className : ''}" data-at="${stamp || ''}" data-form="${form}" data-tip="${stamp || '?'}">${stampText(stamp, form)}</span>`;
}
export { relSpan, stampSpan, relTime, stampText, timeParts };
