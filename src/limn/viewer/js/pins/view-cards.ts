import { DROPPED, LAYOUT, META, COARSE_POINTER_QUERY, OPEN_CARDS, REPLY, isFigureKind, EDITOR } from '../app/state.ts';
import { html, lucideIcon, setHtml } from '../platform/markup.ts';
import { LANG, translateTemplate, translate, translateMessage, TIP_TEXT, josa } from '../platform/i18n.ts';
import { NOTICES, drawTrashOffers } from '../platform/notices.ts';
import { hideTip, tipFollow } from '../platform/tooltip.ts';
import { canConfirmReview, confirmAccessText, isAgentRole } from '../documents/view-meta.ts';
import { showSheet } from '../layout/flow.ts';
import { viaTag } from '../composer/view-levels.ts';
import { isElementLost, lostElementTag, figureRegionBadge, pinPlace } from '../pdf/view-figure.ts';
import { isMarkdownPin } from '../markdown/view.ts';
import { suggestBadge, suggestView } from '../composer/flow-suggest.ts';
import { dropPageLineOverlaps, verdictBadge, verdictOldMarker, verdictTarget } from '../verdict/flow-line.ts';
import {
  addressedTag,
  authorTip,
  cardMetadata,
  cardQuote,
  claimActive,
  claimTag,
  docChip,
  fmtText,
  fyiTag,
  hasRef,
  isQuestion,
  locCopy,
  locText,
  messageHtml,
  nodeAvatar,
  noteHead,
  relBadge,
  reopenedTurn,
  replyCount,
  stateDot,
  threadHtml,
  threadOf,
} from './view-card-parts.ts';
import { listDropped, reviewerLabel } from './flow-list.ts';
import { PURGING } from './flow-actions.ts';
import type { Html } from '../platform/markup.ts';
import { NOTICE_PLACE, UI_LANG } from '../platform/tables.ts';
import { $, $$, TABBABLE, isTabStop } from '../platform/dom.ts';
import { CARD_DOT, ELEMENT_SYNC, LAYOUT_MODE, PIN_STATE, RANGE_REL, ROLE, STAMP_FORM } from '../app/rules-tables.ts';
import { pinState, verdictOf, lineRange } from '../app/rules-pins.ts';
import { who, isMe } from '../app/state-people.ts';
import { avatar } from '../app/view-people.ts';
import { docInfo, isRegion, pdoc, isViewer } from '../documents/state.ts';

/** Native active/review cards and archive rows preserve their state-specific actions.
 * Notes and participant names use escaping Html templates and disable browser translation;
 * UI words inside those regions are translated before rendering. */
/** Render a pin's request, status and available actions; confirmation is offered only to a person with write access. */
function card(pin: Pin) {
  pin = dropPageLineOverlaps(pin); // no overlap badge between two verdicts about one page target (verdict/flow-line.ts)
  const loc = 'L' + pin.lo + '-L' + pin.hi,
    name =
      pin.name ||
      String(pin.file || '')
        .split('/')
        .pop(),
    tags: Html[] = []; // loc stays in the copy format
  if (pin.stale)
    tags.push(
      html`<span class="badge badge-warning" data-tip="${TIP_TEXT.stale}">${lucideIcon('triangle-alert')}위치 잃음</span>`,
    );
  // A figure pin whose element is where it was (el_sync ok) has no '줄 +N 이동': its code lines shifted, but the pin is
  // the element, whose mark and path have not moved. A moved or lost element, and a pin with no element (no el_sync),
  // show it.
  else {
    const moved = /^moved ([+-]\d+)$/.exec(pin.sync || '');
    if (moved && pin.el_sync !== ELEMENT_SYNC.OK)
      tags.push(
        html`<span class="badge" data-tip="${translateTemplate(
          '원고가 고쳐져 {n}줄 밀렸고, 핀을 찍을 때 떠 둔 첫·끝 문장으로 새 위치를 다시 찾았습니다',
          { n: moved[1].replace('+', '') },
        )}">${lucideIcon('move-vertical')}${translateTemplate('줄 {delta} 이동', { delta: moved[1] })}</span>`,
      );
  }
  const lostBadge = lostElementTag(pin);
  if (lostBadge) tags.push(lostBadge); // a figure pin whose element the re-rendered map does not have
  const claimed = claimActive(pin);
  if (claimed) tags.push(claimTag(pin));
  if (pin.edited_at)
    tags.push(
      html`<span class="badge" data-tip="${translateTemplate('저장한 뒤 메모나 범위를 고쳤습니다({when})', {
        when: pin.edited_at.slice(11, 16) + (pin.edited_by ? ' · ' + who(pin.edited_by) : ''),
      })}">${lucideIcon('pencil')}${translate('수정됨')}</span>`,
    );
  // overlap and location-confidence badges mean nothing on an awaiting-review or done card: line matching does not run
  const closedCard = pinState(pin) !== PIN_STATE.OPEN;
  const overlapBadge = closedCard ? null : relBadge(pin.rel, pin);
  if (overlapBadge)
    tags.push(
      html`<span class="badge" data-tip="${translateTemplate(
        overlapBadge.rel === RANGE_REL.PARTIAL
          ? '핀 #{id}{p} 줄 범위가 일부 겹칩니다. 참고만 하고 따로 고쳐도 됩니다'
          : '핀 #{id}{p} 같은 곳을 가리킵니다. 한 번에 고치고 함께 닫는 편이 낫습니다',
        { id: overlapBadge.id, p: josa(overlapBadge.id, '과', '와') },
      )}">${overlapBadge.label}</span>`,
    );
  const locationTag = closedCard ? null : viaTag(pin);
  if (locationTag)
    tags.push(
      html`<span class="badge${locationTag.low ? ' badge-warning' : ''}" data-tip="${locationTag.tip}">${locationTag.t}</span>`,
    );
  const editing = !!(EDITOR.current && EDITOR.current.id === pin.id),
    open = OPEN_CARDS.has(pin.id);
  // Header line: number/line-range/page on the left, reply count/collapse on the right. Badges (.tags) drop to one line
  // below the header. compact accordion: the collapsed header and note preview (.sum) retain the note-level metadata;
  // clicking expands badges/note/buttons (CSS). In wide, .sum and the collapse button are hidden and the card is always
  // expanded. Actions form an equal-width grid; only [완료] is emphasized, [삭제] is the destructive color.
  const first = String(pin.note || '')
      .split('\n')[0]
      .trim(),
    // a suggestion alone says what to do
    noNote = html`<span class="dim">${translate(pin.suggest ? '(제안 문안만)' : '(메모 없음)')}</span>`;
  // A verdict pin without a note spends no line on it: its '판정 채택' badge says what it asks. Folded (compact), its
  // preview is the badge.
  const isVerdictOnly = !pin.note && !pin.suggest && !!verdictOf(pin);
  // Collapsed card's (compact) note preview: up to two lines on its own line below the header, not the width left after
  // the number and location in the header's single line, which would clip it to '[C...' (and an awaiting-review card's
  // '내 확인 차례 · ' prefix would take more of it). Review status is conveyed by the dot color. A verdict pin's
  // preview always leads with what it is: its badge ('판정 채택') and the figure it is about - a reason in its note
  // would take the whole preview, and the folded card would not say which verdict or which figure. The reason follows
  // on a line of its own, cut to one line (.sum-note). A superseded verdict says so folded too: its badge, '이전 판정 ·
  // #4로 대체됨', then '메모 있음' when it has a note (shown when opened). A row that does not clip, so the '#4' link
  // answers its whole touch area (.sum-vd, responsive.css).
  const oldMarker = verdictOldMarker(pin),
    targetTag = verdictTarget(pin),
    isVerdict = !!verdictOf(pin),
    hasNote = oldMarker && pin.note ? html`<span class="sum-has">${translate('메모 있음')}</span>` : '';
  const why =
    isVerdict && !oldMarker && !isVerdictOnly && first
      ? html`<span class="sum-note">${fmtText(first, pin.mentions)}</span>`
      : '';
  // It starts with when the note was written, the short form: a folded card has no comment head to say so.
  const noteTime = pin.at ? stampSpan(pin.at, STAMP_FORM.SHORT, 'sum-t') : '';
  const sum = html`<div class="sum${isVerdict ? ' sum-vd' : ''}" translate="no" data-act="card-toggle">${noteTime}${isVerdict ? html`${verdictBadge(pin)}${oldMarker}${targetTag}${hasNote}${why}` : first ? fmtText(first, pin.mentions) : noNote}</div>`;
  if (isRegion(pin)) {
    // a figure region: element without code, or map unreadable
    const regionBadge = figureRegionBadge(pin.el, isFigureKind((docInfo(pdoc(pin)) || {}).kind));
    tags.unshift(
      regionBadge
        ? html`<span class="badge" data-tip="${regionBadge.tip}">${regionBadge.t}</span>`
        : html`<span class="badge" data-tip="보기 전용 PDF의 핀 — 줄 번호 없이 쪽·영역과 영역 글자로 가리킵니다">보기 전용</span>`,
    );
  }
  if (isQuestion(pin))
    tags.unshift(
      html`<span class="badge badge-question" data-tip="${TIP_TEXT.question}">${lucideIcon('circle-question-mark')}질문</span>`,
    );
  const verdictTag = verdictBadge(pin);
  if (targetTag) tags.unshift(targetTag);
  if (oldMarker) tags.unshift(oldMarker);
  // '판정 채택' in the question badge's place, then '이전 판정 · #4로 대체됨', then the figure it is about
  if (verdictTag) tags.unshift(verdictTag);
  const addressed = pin.assignee ? null : addressedTag(pin);
  if (addressed) tags.push(addressed); // a recorded assignee already appears in the note-level metadata
  const fyi = fyiTag(pin);
  if (fyi) tags.push(fyi); // a fix pin's FYI @-tags
  const suggestTag = suggestBadge(pin, closedCard);
  if (suggestTag) tags.push(suggestTag); // a suggested edit, and why not to apply it (composer/flow-suggest.ts)
  const inReview = pinState(pin) === PIN_STATE.REVIEW;
  const quote = cardQuote(pin); // the dragged PDF text, one line above the note
  if (inReview)
    tags.unshift(
      html`<span class="badge badge-review" data-tip="${translate(TIP_TEXT.review) + ' · ' + translateTemplate('닫은 쪽: {name}', { name: who(pin.closed_by) || '?' }) + ' · ' + (pin.done_at || '')}">${lucideIcon('eye')}${reviewerLabel(pin)}</span>`,
    );
  const reopened = !inReview && reopenedTurn(pin);
  if (reopened)
    tags.unshift(
      html`<span class="badge badge-reopen" data-tip="${translateTemplate('검토에서 되돌아온 핀 — {name} · {time}', { name: who(reopened.by) || '?', time: arcTime(reopened.at) }) + (reopened.text ? ' · ' + translateTemplate('이유: {text}', { text: reopened.text }) : '')}">${lucideIcon('rotate-ccw')}다시 열림</span>`,
    );
  // The one status word of the facts line: what the dot says, and '다시 열림' for an open pin back from review (the dot
  // is the open one's). The assignee is a button only under a mouse, whose 24px hit fits the line. On touch it is text,
  // folded and open alike, and is changed through [수정]: a 44px hit has no room there - in a folded card it would lie
  // over the note's preview, where a tap means "unfold", and open the editor and raise the keyboard instead; in an open
  // card the note right over it and [수정] right under it open the same editor. Never a button while the card is being
  // edited.
  const pressable = !editing && !COARSE_POINTER_QUERY.matches;
  const lost = !!(pin.stale || lostBadge),
    metadata = cardMetadata(
      pin,
      inReview ? '검토 대기' : lost ? '위치 잃음' : claimed ? '처리 중' : reopened ? '다시 열림' : '열림',
      pressable,
    );
  // compact's head link (CSS shows it in place of #N, the line range and N쪽): one 44px target that does what
  // [보기] does - the same data-act, so it also replaces the row's [보기] there.
  // A pin of a Markdown document has no page (ADR-0025 D2): its head says the lines alone.
  const at = pinPlace(pin).page,
    page = typeof at === 'number' && !isMarkdownPin(pin) ? translateTemplate('{page}쪽', { page: at }) : '';
  // Its words and the reply count are in .lbl: compact trims them to their cap height, so the head row's dot, words,
  // count and chevron share one centre in any font.
  const go = html`<span class="go-all" role="button" tabindex="0" data-act="view" data-tip="${TIP_TEXT.view}"><span class="lbl">#${pin.id} · ${locText(pin)}${page ? ' · ' + page : ''}</span></span>`;
  const replyTotal = replyCount(pin);
  const replyCountLink = replyTotal
    ? html`<span class="th-n" role="button" tabindex="0" data-act="reply-open" aria-label="${translateTemplate('답글 {n}건 — 답글 쓰기', { n: replyTotal })}" data-tip="${translateTemplate('이 핀의 답글 {n}건 — 누르면 카드를 펴고 답글 칸을 엽니다', { n: replyTotal })}">${lucideIcon('message-square')}<span class="lbl">${replyTotal}</span></span>`
    : '';
  const dot = stateDot(
      inReview
        ? CARD_DOT.REVIEW
        : pin.stale || isElementLost(pin)
          ? CARD_DOT.LOST
          : claimed
            ? CARD_DOT.CLAIMED
            : CARD_DOT.OPEN,
    ),
    unfold = open || (!inReview && editing);
  // Who wrote the note is said by the comment's head (noteHead). A folded compact card draws no such head, so its own
  // head keeps the avatar.
  const folded = LAYOUT !== LAYOUT_MODE.WIDE && !unfold;
  const authorAvatar =
    folded && who(pin.author)
      ? html`<span class="au" role="img" aria-label="${who(pin.author)}" data-tip="${authorTip(pin)}" translate="no">${avatar(pin.author)}</span>`
      : '';
  // The first comment (docs/handbook/viewer.md §패널 정리 핀 카드): a reply's shape, its head and then the note and
  // what belongs to the note beside the avatar's column. The thread follows it, and .tl-on draws the timeline through
  // them (cards.css). The edit card takes the note's place under the same head, with no thread: comment('') is the head
  // alone.
  const comment = (
    body: Html | string,
  ) => html`<div class="tl${body && !folded && threadOf(pin).length ? ' tl-on' : ''}"><div class="cmt">${nodeAvatar(pin.author)}\
<div class="cmt-b">${noteHead(pin)}${body}</div></div>${body ? threadHtml(pin, LAYOUT === LAYOUT_MODE.WIDE) : ''}</div>`;
  const head = html`<div class="row head">${dot}${go}<span class="n go" role="button" tabindex="0" data-act="view" data-tip="${TIP_TEXT.n}">#${pin.id}</span>${docChip(pin)}\
<span class="loc" tabindex="0" data-copy="${isRegion(pin) ? locCopy(pin) : name + ' ' + loc}" data-tip="${isRegion(pin) ? '영역이 있는 PDF 쪽. 클릭하면 복사' : TIP_TEXT.loc}">${locText(pin)}</span>\
${page ? html`<span class="pg-link" role="button" tabindex="0" data-act="view" data-tip="클릭하면 그 쪽으로 이동">${page}</span>` : ''}\
<span class="sp"></span><span class="h-meta">${replyCountLink}${authorAvatar}</span>\
<button class="btn-icon btn-sm btn-ghost cmp b-fold" data-act="card-toggle" aria-expanded="${unfold}" aria-label="${open ? '카드 접기' : '카드 펼치기'}">${lucideIcon(unfold ? 'chevron-down' : 'chevron-right')}</button></div>\
${sum}<div class="tags">${tags}</div>`;
  if (inReview)
    return html`<div class="pin card review${open ? ' open' : ''}" data-id="${pin.id}" data-doc="${pdoc(pin)}">${head}\
${quote}${comment(html`${isVerdictOnly ? '' : html`<div class="note" translate="no">${pin.note ? fmtText(pin.note, pin.mentions) : noNote}</div>`}${suggestView(pin)}${metadata}`)}\
<div class="acts"><button class="btn-sm b-change" data-act="change" data-tip="${TIP_TEXT.change}">변경 보기</button>\
<button class="btn-sm b-reply" data-act="reply-open" data-tip="${TIP_TEXT.reply}">답글</button>\
${canConfirmReview() ? html`<button class="btn-sm b-confirm${isMe(pin.author) ? ' btn-soft' : ''}" data-act="confirm" data-tip="${TIP_TEXT.confirm}">확인</button>` : ''}</div>\
${canConfirmReview() ? '' : html`<div class="dim review-access">${confirmAccessText()}</div>`}</div>`;
  const body = editing
    ? html`${comment('')}<div class="edit-slot"></div>${metadata}`
    : html`${quote}${comment(html`${isVerdictOnly ? '' : html`<div class="note" translate="no" data-act="edit" data-tip="${translate('클릭하면 메모와 범위를 고칩니다')}">${pin.note ? fmtText(pin.note, pin.mentions) : noNote}</div>`}\
${suggestView(pin)}${metadata}`)}<div class="acts">${cardActs(claimed, LAYOUT !== LAYOUT_MODE.WIDE, !(verdictOf(pin) && isAgentRole()), !!verdictOf(pin))}</div>`;
  return html`<div class="pin card${pin.stale || isElementLost(pin) ? ' st' : ''}${claimed ? ' claimed' : ''}${editing ? ' editing' : ''}${open ? ' open' : ''}" data-id="${pin.id}" data-doc="${pdoc(pin)}">${head}${body}</div>`;
}
// An open card's action row, in the order it is seen so that Tab follows it. wide: [보기] [수정] [답글] ([풀기]) [삭제]
// [완료], by name. compact (narrow and mid, any pointer): [삭제] [수정] ([풀기]) ...... [답글] [완료] - [보기] is the
// head's '#N · L… · N쪽' link, and [수정][풀기][삭제] show only their icon (the name stays in aria-label and the
// tooltip); CSS picks icon or name per layout. canDrop false (an agent's verdict card, D16) leaves [삭제] out. On a
// verdict pin's card it is [지우기] (verdict): a word file may name a verdict '삭제' (the figure goes), and the card's
// '판정 삭제' badge beside a [삭제] would read as that verdict. Two or three syllables like the row's other names, so
// it keeps one line in the row's equal cells ('핀 지우기' would break in two on a narrow row); its description says
// what taking a verdict back does.
function cardActs(claimed, compact, canDrop = true, verdict = false) {
  const dropLabel = verdict ? '지우기' : '삭제';
  const buttons = {
    view: html`<button class="btn-sm b-view" data-act="view" data-tip="${TIP_TEXT.view}">보기</button>`,
    edit: html`<button class="btn-sm b-edit" data-act="edit" aria-label="수정" data-tip="${TIP_TEXT.edit}">${lucideIcon('pencil')}<span class="lbl">수정</span></button>`,
    reply: html`<button class="btn-sm b-reply" data-act="reply-open" data-tip="${TIP_TEXT.reply}">답글</button>`,
    unclaim: claimed
      ? html`<button class="btn-sm b-unclaim" data-act="unclaim" aria-label="풀기" data-tip="처리 중 표시를 풉니다(에이전트가 멈췄거나 잘못 잡은 경우)">${lucideIcon('lock-open')}<span class="lbl">풀기</span></button>`
      : '',
    drop: canDrop
      ? html`<button class="btn-sm btn-destructive b-drop" data-act="drop" aria-label="${dropLabel}" data-tip="${verdict ? TIP_TEXT.dropVerdict : TIP_TEXT.drop}">${lucideIcon('trash-2')}<span class="lbl">${dropLabel}</span></button>`
      : '',
    close: html`<button class="btn-sm btn-soft b-close" data-act="close" data-tip="${TIP_TEXT.close}">완료</button>`,
  };
  return html`${(compact ? ['drop', 'edit', 'unclaim', 'reply', 'close'] : ['view', 'edit', 'reply', 'unclaim', 'drop', 'close']).map((name) => buttons[name])}`;
}
// Archive row (docs/handbook/viewer.md §보관함): a closed/dropped pin is a flat, borderless, backgroundless row with
// faded text, not a card. The first line is icon/#number/location/reference/time/[다시 열기|되살리기]; the second line
// is one line of the agent's answer (close_reply) - truncated on overflow, expandable on click. The original request
// note is only shown by pressing [원래 요청]. The expanded state is kept in ARC_OPEN ('r:'|'o:'|'d:' + id) so it
// survives a redraw.
const ARC_OPEN = new Set();
// Relative time (docs/handbook/viewer.md §뜻과 모양): '방금'/'N분 전'/'N시간 전'/'N일 전', 'M-D' past a week. Absolute
// time is in the description (hover). The original string is kept in data-at and re-computed every 60 seconds
// (tickRel). The archive and the verdict line say this; a comment says stampText.
function relTime(stamp, now?) {
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
function relSpan(stamp, className?, tip?) {
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
// The name of the day a stored time falls on, as a day line of the list says it: 오늘, 어제, '10월 31일', and '2025년
// 9월 25일' in another year; '' for a string that is no time. A time ahead of this device's clock counts as today. now
// is injected by tests.
function dayName(stamp: string | null | undefined, now?: number): string {
  const parts = timeParts(stamp);
  if (!parts) return '';
  const today = new Date(now == null ? Date.now() : now);
  const ago = Math.round(
    (Date.UTC(today.getFullYear(), today.getMonth(), today.getDate()) - Date.UTC(parts.y, parts.mo - 1, parts.d)) /
      86400000,
  ); // calendar days: a day of 23 or 25 hours counts as one
  if (ago <= 0) return translate('오늘');
  if (ago === 1) return translate('어제');
  const month =
    LANG === UI_LANG.EN
      ? ['Jan', 'Feb', 'Mar', 'Apr', 'May', 'Jun', 'Jul', 'Aug', 'Sep', 'Oct', 'Nov', 'Dec'][parts.mo - 1]
      : parts.mo;
  return parts.y === today.getFullYear()
    ? translateTemplate('{m}월 {d}일', { m: month, d: parts.d })
    : translateTemplate('{y}년 {m}월 {d}일', { y: parts.y, m: month, d: parts.d });
}
// Every 60 seconds the drawn times say what they say now: a comment's by its form, the rest by relTime.
function tickRel() {
  if (document.hidden) return;
  $$('.rt[data-at]').forEach((stampElement) => {
    const form = stampElement.dataset.form,
      text = form ? stampText(stampElement.dataset.at, form) : relTime(stampElement.dataset.at);
    if (stampElement.textContent !== text) stampElement.textContent = text;
  });
}
setInterval(tickRel, 60000);
function arcTime(stamp) {
  stamp = String(stamp || '');
  return /^\d{4}-\d\d-\d\d \d\d:\d\d/.test(stamp) ? stamp.slice(5, 16) : stamp;
}
// The location span of an archive row (done or trashed pin): 'L12-L18' for lines, '쪽 N 영역' for a region, N being the
// page its mark is on now (pinPlace); the copy text carries the same.
function arcLoc(pin: Pin) {
  const name =
    pin.name ||
    String(pin.file || pin.pdf || '')
      .split('/')
      .pop();
  return html`<span class="loc" tabindex="0" data-copy="${isRegion(pin) ? locCopy(pin) : name + ' L' + pin.lo + '-L' + pin.hi}" data-tip="${TIP_TEXT.loc}">${isRegion(pin) ? translateTemplate('{page}쪽 영역', { page: pinPlace(pin).page }) : lineRange(pin.lo, pin.hi)}</span>`;
}
// One expandable line of an archive row: text (a close reply or a deleted pin's note) is user text (translate="no"), so
// its Korean description tip is translated here.
function arcLine(key, text, tip, logins) {
  const open = ARC_OPEN.has(key);
  return html`<span class="arc-reply${open ? ' open' : ''}" translate="no" role="button" tabindex="0" data-act="arc-toggle" data-key="${key}" aria-expanded="${open}" data-tip="${translateMessage(tip)}">${fmtText(text, logins)}</span>`;
}
function allMentions(pin: Pin) {
  const out = (pin.mentions || []).slice();
  threadOf(pin).forEach((entry) =>
    (entry.mentions || []).forEach((login) => {
      if (!out.includes(login)) out.push(login);
    }),
  );
  return out;
}
// A done pin's archive row (docs/handbook/viewer.md §보관함): icon, #N, location, reference and time with [답글]; the
// close reply as one expandable line (user text) with [원래 요청], [변경 보기] and [스레드 N]; the original request and
// the thread when expanded (ARC_OPEN), the thread also while a reply box is open on it. A superseded verdict's row has
// two badges, so its first line is icon, #N, '판정 보류' and '이전 판정 · #12로 대체됨' (one block, .arc-head, that
// wraps inside itself on the narrowest widths) with [답글] at its end, and the location, reference and time go on a
// line of their own under it (.arc-l1b) - in every width, so one pin's facts never scatter.
function doneCard(pin: Pin) {
  const ref = hasRef(pin.close_ref)
    ? html`<span class="badge arc-ref" data-tip="닫을 때 남긴 참조 — 같은 값이면 같은 처리에 딸린 핀입니다">${pin.close_ref}</span>`
    : '';
  const reply = pin.close_reply
    ? arcLine('r:' + pin.id, pin.close_reply, '닫으며 남긴 설명 — 누르면 펼치고 접습니다', allMentions(pin))
    : html`<span class="arc-reply none">설명 없이 닫힘</span>`;
  const originalOpen = ARC_OPEN.has('o:' + pin.id);
  // If the thread is longer than a single close record (there was a reply/reopen), it expands via [스레드 N] - with
  // only one record, it's the same as the single answer line above. [답글] opens the same reply box as a card
  // (openReply): a person's reply on a done pin reopens it by the server rule, and the line under the box says so
  // before sending. The thread is kept expanded while replying so the box is visible.
  const replying = REPLY && REPLY.id === pin.id;
  const entries = threadOf(pin),
    hasThread = entries.length > 1 || (entries.length > 0 && !entries[0].ev),
    threadOpen = !!((hasThread && ARC_OPEN.has('t:' + pin.id)) || replying);
  const originalToggle =
    pin.note || pin.suggest
      ? html`<button class="arc-orig-t" data-act="arc-toggle" data-key="o:${pin.id}" aria-expanded="${originalOpen}" data-tip="핀을 남길 때 쓴 메모를 펼치고 접습니다">원래 요청</button>`
      : '';
  const threadToggle = hasThread
    ? html`<button class="arc-orig-t" data-act="arc-toggle" data-key="t:${pin.id}" aria-expanded="${threadOpen}" data-tip="답글과 닫기·다시 열기 이력을 펼치고 접습니다">${translateTemplate('스레드 {n}', { n: entries.length })}</button>`
    : '';
  const original =
    (pin.note || pin.suggest) && originalOpen
      ? html`<div class="arc-orig" translate="no"><b>${translate('원래 요청')}</b>${pin.note ? fmtText(pin.note, pin.mentions) : ''}${suggestView(pin)}</div>`
      : ''; // with its suggested edit, read-only
  const thread = threadOpen
    ? html`<div class="arc-thread"><div class="thread">${entries.map((entry, index) => messageHtml(entry, pin.id + ':' + index))}${replying ? html`<div class="reply-slot"></div>` : ''}</div></div>`
    : '';
  const oldMarker = verdictOldMarker(pin),
    targetTag = verdictTarget(pin),
    numberTag = html`${lucideIcon('check')}<span class="n" data-tip="완료한 핀 번호">#${pin.id}</span>`;
  const where = html`${docChip(pin)}${!oldMarker ? html`${verdictBadge(pin)}${targetTag}` : ''}${arcLoc(pin)}${ref}${relSpan(pin.done_at, 'arc-t', translateTemplate('닫은 사람 {name} · 닫은 시각', { name: who(pin.closed_by) || translate('기록 전') }))}`;
  const replyButton = html`<span class="sp"></span><button class="btn-sm btn-secondary arc-b b-reply" data-act="reply-open" data-tip="${TIP_TEXT.reply}">답글</button>`;
  return html`<div class="arc-row done" data-id="${pin.id}" data-doc="${pdoc(pin)}" data-tip="${authorTip(pin)}">\
${oldMarker ? html`<div class="arc-l1"><span class="arc-head">${numberTag}${verdictBadge(pin)}${oldMarker}${targetTag}</span>${replyButton}</div><div class="arc-l1b">${where}</div>` : html`<div class="arc-l1">${numberTag}${where}${replyButton}</div>`}\
<div class="arc-l2">${reply}${originalToggle}<button class="arc-orig-t b-change" data-act="change" data-tip="${TIP_TEXT.change}">변경 보기</button>${threadToggle}</div>${original}${thread}</div>`;
}
// A Trash row (docs/handbook/viewer.md §휴지통): who deleted it and when, how many days are left before it is purged,
// [되살리기], and - for the owner only - [영구 삭제] (sent after its undo row goes away, like a reply). The buttons
// follow the two lines in the markup; CSS sets them beside the meta line, or on a phone beside the note line (two
// lines, not three).
const TRASH_DAYS = 30;
function trashDaysLeft(at, now, expirySeconds) {
  if (typeof expirySeconds === 'number')
    return Math.max(0, Math.ceil((expirySeconds * 1000 - (now == null ? Date.now() : now)) / 86400000));
  const match = /^(\d{4})-(\d\d)-(\d\d)[ T](\d\d):(\d\d)/.exec(String(at || ''));
  if (!match) return null;
  const droppedAt = new Date(+match[1], +match[2] - 1, +match[3], +match[4], +match[5]).getTime();
  return Math.max(0, Math.ceil(TRASH_DAYS - ((now == null ? Date.now() : now) - droppedAt) / 86400000));
}
function isOwner() {
  return !!(typeof META !== 'undefined' && META && META.me && META.me.role === ROLE.OWNER);
}
// A Trash row: #N, location, when and by whom it was deleted and the days left, the note as one expandable line (user
// text), and [되살리기] (not for a viewer) and [영구 삭제] (the owner only) after the two lines.
function droppedCard(pin: Pin) {
  const line = pin.note
    ? arcLine('d:' + pin.id, pin.note, '삭제한 핀의 메모 — 누르면 펼치고 접습니다', pin.mentions)
    : html`<span class="arc-reply none">(메모 없음)</span>`;
  const left = trashDaysLeft(pin.dropped_at, null, pin.expires_ts),
    by = who(pin.dropped_by) || translate('기록 전');
  const daysLeftTag =
    left != null
      ? html`<span class="arc-sep" aria-hidden="true">·</span><span class="arc-t trash-left" data-tip="${translateTemplate('{n}일이 지나면 저절로 지워집니다', { n: TRASH_DAYS })}">${translateTemplate('{n}일 뒤 지워짐', { n: left })}</span>`
      : '';
  // a viewer reads the Trash but is offered no state change (the server answers 403 anyway) - not rendered, not only
  // hidden ...and an agent is not offered a verdict pin's (D16: 403 verdict_human)
  const restore =
    isViewer() || (verdictOf(pin) && isAgentRole())
      ? ''
      : html`<button class="btn-sm btn-secondary arc-b b-restore" data-act="restore" data-tip="${TIP_TEXT.restore}">되살리기</button>`;
  const purge = isOwner()
    ? html`<button class="btn-sm arc-b btn-destructive b-purge" data-act="purge" data-tip="${TIP_TEXT.purge}">영구 삭제</button>`
    : '';
  return html`<div class="arc-row dropped" data-id="${pin.id}" data-doc="${pdoc(pin)}" data-tip="${authorTip(pin)}">\
<div class="arc-l1">${lucideIcon('trash-2')}<span class="n" data-tip="삭제한 핀 번호">#${pin.id}</span>${docChip(pin)}${arcLoc(pin)}\
${relSpan(pin.dropped_at, 'arc-t', translateTemplate('삭제한 사람 {name} · 삭제한 시각', { name: by }))}\
<span class="arc-sep" aria-hidden="true">·</span><span class="arc-t trash-by">${translateTemplate('{name} 삭제', { name: by })}</span>${daysLeftTag}<span class="sp"></span>\
</div><div class="arc-l2">${line}</div><span class="arc-acts">${restore}${purge}</span></div>`;
}
// the Trash shows every document while open for another document's pin - the list's own filter (SHOW_ALL) is untouched
let TRASH_ALL = false;
// Draws the Trash's rows, newest first (all documents with TRASH_ALL), leaving out a row whose permanent delete waits,
// whose undo row (platform/notices.ts) goes in its place. A focus on a control in the list stays in it (trashRefocus).
function drawTrash() {
  const dropped = TRASH_ALL ? DROPPED : listDropped(),
    box = $('#trash-list');
  if (!box) return;
  const focused = document.activeElement as HTMLElement | null,
    spot = focused && focused !== box && box.contains(focused) ? trashSpot(box, focused) : null;
  $('#trash-note').textContent = translateTemplate(
    '삭제한 핀은 {n}일 동안 여기 있다가 저절로 지워집니다. 되살리면 같은 번호로 돌아옵니다',
    { n: TRASH_DAYS },
  );
  setHtml(
    box,
    dropped.length
      ? html`${dropped
          .slice()
          .reverse()
          .filter((pin) => !PURGING.has(pin.id))
          .map(droppedCard)}`
      : html`<div class="dim">${translate('휴지통이 비어 있습니다')}</div>`,
  );
  drawTrashOffers();
  if (focused && spot && !box.contains(document.activeElement)) trashRefocus(box, spot, focused);
  tipFollow();
} // a box over a row drawn anew stands over nothing
// Where the focused element stands in the Trash's list before a redraw: its row's pin (null in an undo row), its
// action, and the rows' pins in order with its row's place among them.
function trashSpot(
  box: HTMLElement,
  focused: HTMLElement,
): { id: number | null; act: string; ids: number[]; at: number } {
  const row = focused.closest('.arc-row[data-id]') as HTMLElement | null,
    id = row ? Number(row.dataset.id) : null;
  const ids = [...box.querySelectorAll('.arc-row[data-id]')].map((rowElement) =>
    Number((rowElement as HTMLElement).dataset.id),
  );
  return { id, act: focused.dataset.act || '', ids, at: id == null ? -1 : ids.indexOf(id) };
}
// A redraw took the focus out of the Trash's list (setHtml; restorePin's list reload after its answer): it comes back -
// to the element itself when it is drawn again (an undo row is moved, not made anew), to the same control of its row
// when the row is still there (a [되살리기] that failed), else, the row gone (restored, purged, gone elsewhere), to the
// undo row in its place, the next row's [되살리기], the one before's, and last the Trash's [닫기] - never to nothing,
// which would leave Tab and Esc to start from the page's top. A focus the person moved out of the list meanwhile is not
// here to come back (drawTrash).
function trashRefocus(
  box: HTMLElement,
  spot: { id: number | null; act: string; ids: number[]; at: number },
  focused: HTMLElement,
) {
  const findControl = (id: number, act: string) => {
    const row = box.querySelector('.arc-row[data-id="' + id + '"]');
    return (row &&
      (row.querySelector('[data-act="' + act + '"]') ||
        row.querySelector('[data-act="restore"]'))) as HTMLElement | null;
  };
  let target = focused.isConnected ? focused : null;
  if (!target && spot.id != null) {
    const id = spot.id;
    target = findControl(id, spot.act);
    if (!target) {
      const undoRow = [...NOTICES.values()].find(
        (notice) => notice.place === NOTICE_PLACE.TRASH && notice.pin === id && !!notice.el && box.contains(notice.el),
      );
      target = undoRow && undoRow.el ? undoRow.el.querySelector('[data-act="notice-act"]') : null;
    }
    for (const otherId of [...spot.ids.slice(spot.at + 1), ...spot.ids.slice(0, Math.max(0, spot.at)).reverse()]) {
      if (target) break;
      target = findControl(otherId, 'restore');
    }
  }
  if (!target) target = $('#trash').querySelector('[data-act="trash-close"]') as HTMLElement | null;
  if (target) target.focus();
}
function openTrash(flashId?) {
  const trash = $('#trash');
  if (flashId != null && !listDropped().some((pin) => pin.id === flashId) && DROPPED.some((pin) => pin.id === flashId))
    TRASH_ALL = true; // another document's pin
  drawTrash();
  if (!trash.open) {
    hideTip();
    showSheet(trash);
  }
  if (flashId != null)
    requestAnimationFrame(() => {
      const row = document.querySelector('#trash .arc-row[data-id="' + flashId + '"]') as HTMLElement;
      if (!row) return;
      row.scrollIntoView({ block: 'nearest' });
      row.classList.remove('flash');
      void row.offsetWidth;
      row.classList.add('flash');
    });
}
$('#trash').addEventListener('close', () => {
  TRASH_ALL = false;
});
// Tab stays in the open Trash, a modal dialog: from its last control it comes back to its first, and Shift+Tab from its
// first (or from the dialog itself) goes to its last. Left to the browser, Tab would leave it for the browser's own
// toolbar and the page's focus would fall to <body> while the Trash stays open (Tab from [닫기] once the last row is
// restored).
$('#trash').addEventListener('keydown', (event) => {
  if (event.key !== 'Tab' || event.ctrlKey || event.metaKey || event.altKey || event.defaultPrevented) return;
  const trash = $('#trash');
  const all = [...trash.querySelectorAll(TABBABLE)].filter(isTabStop) as HTMLElement[],
    focused = document.activeElement,
    index = all.indexOf(focused as HTMLElement);
  const to = !all.length
    ? null
    : event.shiftKey
      ? index === 0 || focused === trash
        ? all[all.length - 1]
        : null
      : index === all.length - 1
        ? all[0]
        : null;
  if (to) {
    event.preventDefault();
    to.focus();
  }
});
$('#trash').addEventListener('click', (event) => {
  const trash = $('#trash');
  if (event.target !== trash) return;
  const rect = trash.getBoundingClientRect();
  if (
    event.clientX < rect.left ||
    event.clientX > rect.right ||
    event.clientY < rect.top ||
    event.clientY > rect.bottom
  )
    trash.close();
});
export { ARC_OPEN, card, dayName, doneCard, drawTrash, openTrash, relSpan, stampSpan, timeParts };
