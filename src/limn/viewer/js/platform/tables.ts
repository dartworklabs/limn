// ------------------------------------------------ Closed value tables platform code compares
// The closed sets (docs/handbook/viewer.md §닫힌 값 표) that the platform modules read: a notice's kind, place, host,
// life, dot and topic, the UI language, the list order and an event's type. The app's other tables are in
// app/rules-tables.ts. Each is a frozen table compared by member, never by a string literal.
const EVENT_TYPE = Object.freeze({
  MENTION: 'mention',
  REVIEW_REQUESTED: 'review_requested',
  REPLIED: 'replied',
  REOPENED: 'reopened',
  ASSIGNED: 'assigned',
  DROPPED: 'dropped',
}); // an event's `type` (events.EventType)
const UI_LANG = Object.freeze({ KO: 'ko', EN: 'en' }); // LANG
// what a message reports (platform/notices.ts): its icon, colour and how it is read out
const NOTICE_KIND = Object.freeze({ OK: 'ok', WARN: 'warn', ERR: 'err', INFO: 'info' });
const NOTICE_PLACE = Object.freeze({
  LINE: 'line',
  BANNER: 'banner',
  CHIP: 'chip',
  ROW: 'row',
  CARD: 'card',
  TRASH: 'trash',
}); // where a message is drawn (platform/notices.ts)
const NOTICE_HOST = Object.freeze({
  COMPOSER: 'composer',
  LIST: 'list',
  REVIEW: 'review',
  TRASH: 'trash',
  LINE: 'line',
}); // a banner's panel or section; LINE puts an api() error on the status line
// how long a message stays (armNotice)
const NOTICE_LIFE = Object.freeze({ STICKY: 'sticky', CLICK: 'click', TIMER: 'timer' });
// the chip a background message marks, [핀 N] or [검토 M]; also the body class dot-<value>
const NOTICE_DOT = Object.freeze({ SIDE: 'side', RV: 'rv' });
// what a first-visit hint asks for (endTopic): a selection, the panel opened, a pin kept while cut off
const NOTICE_TOPIC = Object.freeze({ PICK: 'pick', SIDE: 'side', OFFLINE: 'offline' });
// the pin list's order (orderPins); index.html data-order
const LIST_ORDER = Object.freeze({ NEW: 'new', PAGE: 'page', ID: 'id' });
// The entry for key in a table keyed by a field the server may leave out or send as null; none without a key, as for a
// key the table does not name, so the caller's fallback stands for both.
function tableEntry<Value>(table: Readonly<Record<string, Value>>, key: string | null | undefined): Value | undefined {
  return key == null ? undefined : table[key];
}
// Whether a value read from outside the code (parsed JSON, a stored copy, a message, an error's body) is an object
// whose fields can be read - each field still unknown. Arrays are objects too. Pure.
function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === 'object' && value !== null;
}
export {
  isRecord,
  tableEntry,
  EVENT_TYPE,
  UI_LANG,
  NOTICE_KIND,
  NOTICE_PLACE,
  NOTICE_HOST,
  NOTICE_LIFE,
  NOTICE_DOT,
  NOTICE_TOPIC,
  LIST_ORDER,
};
