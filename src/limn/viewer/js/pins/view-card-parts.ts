import { DOC, DROPPED, META, PEOPLE, PINS, REPLY, SHOW_ALL, THREAD_OPEN } from '../app/state.ts';
import { html, lucideIcon } from '../platform/markup.ts';
import { markHiddenPlain } from '../platform/hidden-chars.ts';
import { translateTemplate, translate, josa } from '../platform/i18n.ts';
import { multiDoc } from '../documents/view-tabs.ts';
import { findAnyPin } from '../revisions/flow.ts';
import { pinPlace } from '../pdf/view-figure.ts';
import { isMarkdownPin } from '../markdown/view.ts';
import { quoteInner, shownQuote } from '../composer/flow-pick.ts';
import { nameShared, personLabel, mentionAfterWord } from '../composer/input-mentions.ts';
import type { Html } from '../platform/markup.ts';
import {
  ASSIGNEE_AGENT,
  CARD_DOT,
  REQUEST_KIND,
  LOCAL_LOGIN,
  PIN_STATE,
  RANGE_REL,
  STAMP_FORM,
  THREAD_EVENT,
} from '../app/rules-tables.ts';
import { pinState, lineRange } from '../app/rules-pins.ts';
import { who, peopleName, meLogin, isMe } from '../app/state-people.ts';
import { FAILED_AVATARS, avatar } from '../app/view-people.ts';
import { docInfo, isRegion, pdoc, isViewer } from '../documents/state.ts';
import { QUOTE_OPEN } from '../composer/view-text.ts';
import { relSpan, stampSpan } from './view-time.ts';

/** Native pin-card markup, including participant text, state badges and threads.
 * User-provided names and notes enter markup only through the escaping Html template. */

document.addEventListener(
  'error',
  (event) => {
    const image = event.target;
    if (image instanceof HTMLImageElement && image.classList.contains('av')) {
      FAILED_AVATARS.add(image.getAttribute('src'));
      const circle = document.createElement('span');
      circle.className = 'av i';
      const letter = document.createElement('span');
      letter.className = 'av-l';
      letter.textContent = image.dataset.ini || '?';
      circle.append(letter);
      image.replaceWith(circle);
    }
  },
  true,
);
function authorTip(pin: Pin) {
  let tip = translateTemplate('작성: {name} · {at}', {
    name: pin.author ? who(pin.author) : translate('기록 전'),
    at: pin.at || '?',
  });
  if (pin.edited_at)
    tip +=
      ' / ' +
      translateTemplate('수정: {name} · {at}', { name: who(pin.edited_by) || translate('기록 전'), at: pin.edited_at });
  return tip;
}
function josaToward(number: number) {
  return '036'.includes(String(number).slice(-1)) ? '으로' : '로';
}
function relBadge(rel: PinRelation[] | undefined, pin: Pin) {
  if (!rel || !rel.length) return null;
  const byId = new Map(PINS.map((listed) => [listed.id, listed]));
  if (pin) {
    const same = rel.filter((entry) => {
      const other = byId.get(entry.id);
      return other && other.lo === pin.lo && other.hi === pin.hi;
    });
    if (same.length) {
      const lowestId = Math.min.apply(
        null,
        same.map((entry) => entry.id),
      );
      return {
        id: lowestId,
        rel: RANGE_REL.EQUAL,
        label: translateTemplate('#{id}{p} 같은 범위', { id: lowestId, p: josa(lowestId, '과', '와') }),
      };
    }
  }
  const insides = rel.filter((entry) => entry.rel === RANGE_REL.INSIDE);
  if (insides.length) {
    const span = (entry: PinRelation) => {
      const other = byId.get(entry.id);
      return other ? (other.hi as number) - (other.lo as number) : Number.MAX_SAFE_INTEGER;
    }; // rel names line pins
    const best = insides.reduce((best, candidate) => {
      const bestSpan = span(best),
        candidateSpan = span(candidate);
      return candidateSpan < bestSpan || (candidateSpan === bestSpan && candidate.id < best.id) ? candidate : best;
    });
    return { id: best.id, rel: RANGE_REL.INSIDE, label: translateTemplate('#{id} 범위 안', { id: best.id }) };
  }
  const partials = rel.filter((entry) => entry.rel === RANGE_REL.PARTIAL).sort((left, right) => left.id - right.id);
  if (partials.length) {
    const firstId = partials[0].id;
    return {
      id: firstId,
      rel: RANGE_REL.PARTIAL,
      label: translateTemplate('#{id}{p} 일부 겹침', { id: firstId, p: josa(firstId, '과', '와') }),
    };
  }
  return null;
}
// The in-progress marker (docs/handbook/api.md §처리 중 표시 (claim)). claim_until is epoch seconds, compared
// independent of the browser's timezone (numbers instead of a wall-clock string, for the same reason as
// docs/handbook/build-sync.md §위치 추정). The viewer never places a claim (agent-only) - it only offers [풀기].
function claimActive(pin: Pin) {
  return typeof pin.claim_until === 'number' && pin.claim_until > Date.now() / 1000;
}
// Estimated time to handle (docs/handbook/api.md §처리 중 표시): if an agent gives eta_min on a claim, the server sets
// eta_ts (epoch). The badge shows '처리 중 · 약 15분 · 20:40쯤' - both the remaining minutes and the time are rounded
// up to 5-minute steps (an estimate is approximate). Past it, '예상보다 늦어짐 (+5분)'. A legacy claim with no eta
// shows '처리 중 · 20:02부터 (23분째)'. The lock's auto-expiry (claim_until) would read as the estimated completion, so
// it is never shown on screen - only in the description. The time is the viewing device's local time. now is injected
// by tests.
function ceil5(minutes: number) {
  return Math.max(5, Math.ceil(minutes / 5 - 1e-9) * 5);
}
function clockTime(ms: number) {
  const date = new Date(ms);
  return String(date.getHours()).padStart(2, '0') + ':' + String(date.getMinutes()).padStart(2, '0');
}
function claimInfo(pin: Pin, now?: number) {
  now = now == null ? Date.now() : now;
  const claimer = who(pin.claimed_by) || '?',
    startMs = typeof pin.claim_ts === 'number' ? pin.claim_ts * 1000 : null;
  const tail =
    ' · ' +
    translateTemplate('잠금 자동 해제 {time}(그 뒤에는 다른 쪽이 잡을 수 있습니다). 에이전트가 멈췄으면 [풀기]', {
      time: clockTime((pin.claim_until as number) * 1000),
    }); // claimInfo runs for an active claim (claimActive)
  const head =
    translateTemplate('처리하는 쪽: {name}', { name: claimer }) +
    (startMs ? ' · ' + translateTemplate('시작 {time}', { time: clockTime(startMs) }) : '');
  if (typeof pin.eta_ts === 'number') {
    const eta = pin.eta_ts * 1000;
    if (now <= eta)
      return {
        t: translateTemplate('처리 중 · 약 {n}분 · {time}쯤', {
          n: ceil5((eta - now) / 60000),
          time: clockTime(Math.ceil(eta / 300000) * 300000),
        }),
        late: false,
        tip: head + ' · ' + translateTemplate('예상 완료 {time}', { time: clockTime(eta) }) + tail,
      };
    return {
      t: translateTemplate('예상보다 늦어짐 (+{n}분)', { n: ceil5((now - eta) / 60000) }),
      late: true,
      tip: head + ' · ' + translateTemplate('예상 완료 {time}였음', { time: clockTime(eta) }) + tail,
    };
  }
  if (startMs)
    return {
      t: translateTemplate('처리 중 · {time}부터 ({n}분째)', {
        time: clockTime(startMs),
        n: Math.max(1, Math.ceil((now - startMs) / 60000)),
      }),
      late: false,
      tip: head + ' · ' + translate('예상 시간 없음') + tail,
    };
  return { t: translate('처리 중'), late: false, tip: head + tail };
}
function claimLabel(pin: Pin, now?: number) {
  return claimInfo(pin, now).t;
}
function claimTag(pin: Pin) {
  const claim = claimInfo(pin);
  return html`<span class="badge badge-claimed${claim.late ? ' late' : ''}" data-claim="${pin.id}" data-tip="${claim.tip}">${lucideIcon('clock')}<span class="ct">${claim.t}</span></span>`;
}
// A card's location text: 'L12-L18' for a LaTeX pin, '영역' for a view-only PDF's pin (the page is a separate field).
// The copy format is 'file L12-L18' / 'x.pdf 쪽 3'; a region's page is the one its mark is on in the current build
// (pinPlace), which a figure pin's element can move.
function locText(pin: Pin) {
  return isRegion(pin) ? translate('영역') : lineRange(pin.lo, pin.hi);
}
function locCopy(pin: Pin) {
  const name =
    pin.name ||
    String(pin.file || pin.pdf || '')
      .split('/')
      .pop();
  return isRegion(pin) ? name + ' 쪽 ' + pinPlace(pin).page : name + ' L' + pin.lo + '-L' + pin.hi;
}
// The document chip attached to a card header when viewing all documents. Another document's is dashed-bordered -
// clicking it switches to that document. The name is user text (translate="no"); its description's UI words are
// translated here.
function docChip(pin: Pin) {
  if (!(SHOW_ALL && multiDoc())) return html``;
  const entry = docInfo(pdoc(pin)),
    other = pdoc(pin) !== DOC;
  const tip =
    (entry ? entry.name + ' · ' + entry.path : translateTemplate('{doc} (설정에 없는 문서)', { doc: pdoc(pin) })) +
    (other ? ' — ' + translate('#번호·[보기]를 누르면 이 문서로 바꿉니다') : '');
  return html`<span class="badge badge-secondary dchip${other ? ' other' : ''}" translate="no" data-tip="${tip}">${entry ? entry.name : pdoc(pin)}</span>`;
}
// Thread (docs/handbook/viewer.md §스레드와 검토): replies and state-transition records (close/reopen/confirm) form a
// single line of history, built with html``. wide shows the last 3, compact shows only the last 1, expanded via [이전
// N건] (THREAD_OPEN). The input field (REPLY) is inserted in place like EDITOR.current.
function isQuestion(pin: Pin) {
  return !!pin && pin.kind_req === REQUEST_KIND.QUESTION;
}
// The current assignee - the recorded value (pin.assignee); for a legacy pin without one, the person the server
// inferred (the first of pin.addressed); if neither, the agent.
function assigneeOf(pin: Pin) {
  if (!pin) return ASSIGNEE_AGENT;
  if (pin.assignee) return pin.assignee;
  const addressed = pin.addressed || [];
  return addressed.length ? addressed[0] : ASSIGNEE_AGENT;
}
// The words for an assignee: the agent, me, a person's name, and '미지정' for a record without one.
function assigneeWord(assignee: string | null | undefined): string {
  return !assignee
    ? translate('미지정')
    : assignee === ASSIGNEE_AGENT
      ? translate('에이전트')
      : assignee === meLogin()
        ? translate('나')
        : peopleName(assignee);
}
/** Render the recorded assignee once as plain metadata, without inferring a legacy default.
 * The agent - the default - is said to screen readers only (.sr-only); a person, me and a record without an assignee
 * are drawn. Only an open pin's author or identity-less local screen gets the existing edit action, and only where it
 * can be pressed (pressable: under a mouse); read-only viewers, other participants and every touch card retain
 * readable text. The pressable one ends in a pencil, so it does not look like the one that only reads. Names remain
 * escaped. The label and the name are elements of their own (.as-l, .as-n), so each
 * line can be trimmed to its cap height: a trim does not reach a bare text in the chip's flex row. */
function assignChip(pin: Pin, pressable: boolean): Html {
  if (pin.assignee === ASSIGNEE_AGENT)
    return html`<span class="cm-i as-chip sr-only">${translate('담당')} ${assigneeWord(pin.assignee)}</span>`;
  if (!pin.assignee)
    return html`<span class="cm-i as-chip"><span class="as-l">${translate('담당')} ${assigneeWord(null)}</span></span>`;
  const me = meLogin(),
    mine = pin.assignee === me,
    shared = !mine && nameShared(pin.assignee),
    name = assigneeWord(pin.assignee) + (shared ? ' ' + pin.assignee : '');
  const canEdit = pressable && !isViewer() && pinState(pin) === PIN_STATE.OPEN && (isMe(pin.author) || !me),
    tip =
      translateTemplate('담당: {name} — 에이전트는 이 핀을 건너뜁니다', { name: name }) +
      (canEdit ? translate('. 누르면 [수정]에서 담당을 바꿉니다') : '');
  // a name another known person shares carries the login, as the composer's
  const shown = shared ? personLabel(pin.assignee) : html`${name}`;
  return canEdit
    ? html`<button class="cm-i badge badge-assign as-chip${mine ? ' me' : ''}" data-act="edit" data-tip="${tip}"><span class="as-l">${translate('담당')} </span><span class="as-n" translate="no">${shown}</span>${lucideIcon('pencil')}</button>`
    : html`<span class="cm-i badge badge-assign as-chip${mine ? ' me' : ''}" data-tip="${tip}"><span class="as-l">${translate('담당')} </span><span class="as-n" translate="no">${shown}</span></span>`;
}
/** Return the card's facts line: kind, assignee and status, of which only what differs from the default is drawn.
 * The default - a fix request, for the agent, open - is in the line for screen readers (.sr-only) and takes no room,
 * so a pin with nothing to report shows no line at all (hide-folded). The line is one line of text with ' · ' between
 * the drawn facts (CSS keeps its spaces): the kind and the status are never shortened and a long assignee name ends
 * in an ellipsis. In an open card the question, review, claim, reopen and location badges already say the kind and
 * the status (a drawn card-meta-context is not shown there), so the line shows the assignee alone, or nothing
 * (hide-open). The caller supplies the same status word the native badges are built from, and whether the assignee
 * can be a button there (assignChip). */
function cardMetadata(pin: Pin, statusLabel: string, pressable: boolean): Html {
  const question = isQuestion(pin),
    open = statusLabel === '열림',
    agent = pin.assignee === ASSIGNEE_AGENT;
  const facts = [
    {
      drawn: question,
      part: html`<span class="cm-i card-meta-context${question ? '' : ' sr-only'}">${translate(question ? '질문' : '수정 요청')}</span>`,
    },
    { drawn: !agent, part: assignChip(pin, pressable) },
    {
      drawn: !open,
      part: html`<span class="cm-i card-meta-context${open ? ' sr-only' : ''}">${translate(statusLabel)}</span>`,
    },
  ];
  // Between two drawn facts ' · '; before any other fact a space only a screen reader meets, so the words never run
  // together.
  let drawnCount = 0;
  const parts = facts.map((fact, index) =>
    fact.drawn && drawnCount++
      ? html`<span class="cm-sep card-meta-context"> · </span>${fact.part}`
      : index
        ? html`<span class="sr-only"> </span>${fact.part}`
        : fact.part,
  );
  return html`<div class="card-meta${agent ? ' hide-open' : ''}${drawnCount ? '' : ' hide-folded'}">${parts}</div>`;
}
// Status dot (docs/handbook/viewer.md §상태 표현): color + a readable name (aria-label/description). A badge states the
// same meaning in text once more.
const CARD_STATE_NAME = { open: '열림', claimed: '처리 중', review: '검토 대기', lost: '위치 잃음' };
function stateDot(state: keyof typeof CARD_STATE_NAME) {
  const label = translateTemplate('상태: {name}', { name: translate(CARD_STATE_NAME[state]) });
  return html`<span class="st-dot${state === CARD_DOT.OPEN ? '' : ' ' + state}" role="img" aria-label="${label}" data-tip="${label}"></span>`;
}
// Did the current round start with a reopen (a pin that returned from review)? True if the thread's last close/reopen
// record is a reopen.
function reopenedTurn(pin: Pin) {
  const thread = threadOf(pin);
  for (let i = thread.length - 1; i >= 0; i--) {
    const kind = thread[i].ev;
    if (kind === THREAD_EVENT.CLOSE || kind === THREAD_EVENT.REOPEN)
      return kind === THREAD_EVENT.REOPEN ? thread[i] : null;
  }
  return null;
}
function threadOf(pin: Pin) {
  const thread = pin && pin.thread;
  return Array.isArray(thread) ? thread : [];
}
function replyCount(pin: Pin) {
  return threadOf(pin).filter((entry) => !entry.ev).length;
}
function entryText(entry: ThreadEntry) {
  return fmtText(entry.text, entry.mentions);
}
function mentionTokensOf(logins: readonly string[] | undefined) {
  const out: { t: string; lg: string; k: number }[] = [];
  (logins || []).forEach((login) => {
    const known = PEOPLE.find((person) => person.login === login),
      name = String((known && known.name) || '');
    const words = name.split(/\s+/).filter(Boolean);
    [name, login, String(login).split('@')[0]].concat(words.length > 1 ? [words[0]] : []).forEach((candidate, rank) => {
      if ([...candidate].length >= 2) out.push({ t: candidate, lg: login, k: rank });
    });
  });
  return out.sort((left, right) => right.t.length - left.t.length || left.k - right.k);
} // for a tie in text length, full name > login > first word
function escapeRegExp(text: string) {
  return text.replace(/[.*+?^${}()|[\]\\]/g, '\\$&');
}
// text as Html with its resolved @-tags (logins) and existing #refs as tokens. A match the rules turn down is consumed
// and stays text, and the text between two tags is searched for #refs only, so a name never holds a link.
function fmtText(text: string | undefined, logins: readonly string[] | undefined) {
  const plain = String(text == null ? '' : text),
    tokens = mentionTokensOf(logins),
    me = meLogin(),
    out: ((string | Html)[] | Html)[] = [];
  let at = 0;
  if (tokens.length) {
    const pattern = new RegExp('@(' + tokens.map((token) => escapeRegExp(token.t)).join('|') + ')', 'gi');
    for (const match of plain.matchAll(pattern)) {
      const name = match[1],
        offset = match.index;
      if (mentionAfterWord(plain, offset)) continue;
      const after = plain.charAt(offset + match[0].length);
      if (/[A-Za-z0-9]$/.test(name) && /[A-Za-z0-9_]/.test(after)) continue;
      const token = tokens.find((token) => token.t.toLowerCase() === name.toLowerCase());
      if (!token) continue;
      const mine = !!me && token.lg === me,
        tip = mine
          ? translate('나를 부름 — 이 핀 알림이 나에게 옵니다')
          : translateTemplate('@태그 — {name}에게 알림이 갑니다', { name: peopleName(token.lg) });
      out.push(
        pinRefs(plain.slice(at, offset)),
        html`<span class="mention${mine ? ' me' : ''}" data-tip="${tip}">${match[0]}</span>`,
      );
      at = offset + match[0].length;
    }
  }
  out.push(pinRefs(plain.slice(at)));
  return html`${out}`;
}
// text with each '#12' whose pin exists as a link, as html`` values. '#12;' and a number glued to a word, digit or '#'
// stay text. A '#12' whose pin is in the Trash renders as '#12 deleted pin' (faded) and opens the Trash at that row.
function pinRefs(text: string) {
  const out: (string | Html)[] = [];
  let at = 0;
  for (const match of text.matchAll(/(^|[^0-9A-Za-z#])#(\d{1,6})(?![\d;])/g)) {
    const id = +match[2],
      start = match.index + match[1].length;
    const ref = pinRefExists(id)
      ? html`<span class="pin-ref" role="link" tabindex="0" data-act="pin-ref" data-ref="${id}" data-tip="${translateTemplate('핀 #{id} 로 갑니다', { id })}">#${id}</span>`
      : pinRefGone(id)
        ? html`<span class="pin-ref gone" role="link" tabindex="0" data-act="pin-ref" data-ref="${id}" data-tip="${translateTemplate('핀 #{id} 은 삭제되었습니다 — 누르면 휴지통에서 봅니다', { id })}">#${id} <small>${translate('삭제된 핀')}</small></span>`
        : null;
    if (!ref) continue;
    out.push(text.slice(at, start), ref);
    at = match.index + match[0].length;
  }
  out.push(text.slice(at));
  return out;
}
function pinRefExists(id: number) {
  return typeof findAnyPin === 'function' && !!findAnyPin(id);
}
function pinRefGone(id: number) {
  return typeof DROPPED !== 'undefined' && Array.isArray(DROPPED) && DROPPED.some((pin) => pin.id === id);
}
// The [나를 부른 핀] filter (docs/handbook/viewer.md §@태그): uses the same material as the badge/pins.md's '→ @name'
// (pin.addressed, which the server counts only for the current round via thread_round), not a scan of the whole thread
// (threadOf(pin).some(...)): that would keep a pin marked "called me" after a reopen for an @-tag of an earlier round.
// addressed_to() only has a value on question pins.
function mentionsMe(pin: Pin) {
  const me = META && META.me;
  if (!me || !me.login || me.login === LOCAL_LOGIN) return false;
  return (pin.addressed || []).includes(me.login);
}
// The badges of a question pin that calls people: '나를 부름', and the others' names (user text, translate="no").
function addressedTag(pin: Pin) {
  const to = pin.addressed || [];
  if (!to.length) return null;
  const me = META && META.me && META.me.login,
    mine = to.includes(me),
    others = to.filter((login) => login !== me);
  const self = mine
    ? html`<span class="badge badge-mention" data-tip="이 핀이 나를 @태그했습니다 — 에이전트는 이 핀을 건너뜁니다(사용자가 시키면 예외)">${lucideIcon('at-sign')}나를 부름</span>`
    : '';
  const rest = others.length
    ? html`<span class="badge badge-mention" data-tip="사람을 부른 핀입니다 — 에이전트는 사용자가 따로 시키지 않으면 건너뜁니다">${lucideIcon('at-sign')}<span translate="no">${others.map(peopleName).join(', ')}</span></span>`
    : '';
  return html`${self}${rest}`;
}
// A fix pin's FYI @-tags (never skipped) - kept separate from pin.addressed (question-pin only) and sent in pin.fyi
// instead.
function fyiTag(pin: Pin) {
  const to = pin.fyi || [];
  if (!to.length) return null;
  return html`<span class="badge badge-mention" data-tip="참고로 부른 사람입니다 — 질문이 아니라 수정 요청이라 건너뛰지 않습니다">${lucideIcon('at-sign')}${translateTemplate('참고 {names}', { names: to.map(peopleName).join(', ') })}</span>`;
}
// Is the reference (ref) a meaningful value? '-' is a placeholder some callers use for "no reference" - shown as-is
// it would produce meaningless text like '닫음 · -'. An empty or whitespace-only value is filtered out the same way.
function hasRef(value: string | undefined) {
  return !!value && String(value).trim() !== '' && String(value).trim() !== '-';
}
const EVENT_LABEL: Record<string, string> = { close: '닫음', reopen: '다시 엶', confirm: '확인', assign: '담당 바꿈' };
// A card's quote line, right above its note: the composer's line for the pin's saved quote (shownQuote, quoteInner),
// folded to one line with the whole text as its tooltip until it is pressed. null when the pin shows no quote.
function cardQuote(pin: Pin): Html | null {
  const quote = shownQuote(pin, (docInfo(pdoc(pin)) || {}).kind);
  if (!quote) return null;
  const key = pdoc(pin) + ':' + pin.id,
    open = QUOTE_OPEN.has(key);
  return html`<div class="quote hit${open ? ' open' : ''}" role="button" tabindex="0" data-act="quote" data-key="${key}" aria-expanded="${String(open)}"\
 data-tip="${open ? null : markHiddenPlain(quote)}" translate="no">${quoteInner(quote, isMarkdownPin(pin))}</div>`;
}
// A long post collapses at 6 lines with [더 보기] (keyed 'id:index' in MESSAGE_OPEN). If the author is me, '(나)'. The
// post and its author's name are user text (translate="no"); '(나)' is translated here.
const MESSAGE_OPEN = new Set<string>();
// A thread entry's text (user text, translate="no") clamped at 6 lines with [더 보기]/[접기] when long; key
// ('id:index') keeps it open across redraws (MESSAGE_OPEN), and without a key it is drawn whole with no button.
function messageBody(entry: ThreadEntry, key: string) {
  const long = String(entry.text || '').length > 280 || String(entry.text || '').split('\n').length > 6,
    open = !key || MESSAGE_OPEN.has(key);
  const more =
    long && key
      ? html`<button class="btn-sm btn-ghost msg-more" data-act="msg-more" data-key="${key}" aria-expanded="${open}">${open ? '접기' : '더 보기'}</button>`
      : '';
  return html`<div class="msg-t${long && !open ? ' clamp' : ''}" translate="no">${entryText(entry)}</div>${more}`;
}
// One entry of an archive row's thread: a post (avatar, author, time, text) or a state record (who, what, reference,
// time, optional text).
function messageHtml(entry: ThreadEntry, key: string) {
  const by = entry.by || {},
    name = who(by) || '?',
    mine = isMe(by) ? html`<span class="me-tag"> ${translate('(나)')}</span>` : '';
  if (entry.ev)
    return html`<div class="msg ev ev-${entry.ev}"><div class="msg-h"><b translate="no">${name}${mine}</b><span>${translate(EVENT_LABEL[entry.ev] || entry.ev)}${hasRef(entry.ref) ? ' · ' + entry.ref : ''}</span>${relSpan(entry.at)}</div>${entry.text ? messageBody(entry, key) : ''}</div>`;
  return html`<div class="msg">${avatar(by)}<div class="msg-b"><div class="msg-h"><b translate="no">${name}${mine}</b>${relSpan(entry.at)}</div>${messageBody(entry, key)}</div></div>`;
}
// A node of a card's timeline: the person's avatar, or for no recorded person an empty circle in its place, so the
// column, the line and the indent of the text hold.
function nodeAvatar(person: Person | null | undefined): Html {
  return who(person) ? avatar(person) : html`<span class="av none" aria-hidden="true"></span>`;
}
// Who and when at the start of a card's comment or entry head, kept on one line (.who): the name ends in an ellipsis
// where the line is short, its whole text staying the element's text and its description (tip), and '(나)' and the time
// are never cut. The name and its tip are user text: the element holding both is translate="no", so a person named
// '완료' is not 'Done' in either; '(나)' and the tip's own words are translated here. className marks a name with no
// recorded person.
function whoWhen(name: string, mine: boolean, tip: string, time: Html | string, className?: string): Html {
  // the space is the text's; drawn, the margin is
  const me = mine ? html`<span class="me-tag"> ${translate('(나)')}</span>` : '';
  return html`<span class="who"><b class="${className || ''}" translate="no" data-tip="${tip}"><span class="nm">${name}</span>${me}</b>${time}</span>`;
}
// The head of a card's first comment, a reply's: who wrote the note ('기록 전' for a pin with no recorded author),
// when, and when it was last edited, which takes the next line where the first has no room. The name's description also
// says who edited it.
function noteHead(pin: Pin): Html {
  const name = who(pin.author);
  return html`<div class="msg-h note-h">${whoWhen(name || translate('기록 전'), isMe(pin.author), authorTip(pin), pin.at ? stampSpan(pin.at, STAMP_FORM.BOTH) : '', name ? '' : 'old')}\
${pin.edited_at ? stampSpan(pin.edited_at, STAMP_FORM.EDITED) : ''}</div>`;
}
// One entry of a card's timeline: a post (avatar, then name and time over its text) or a state record (a dot in the
// avatar's place, then name and time, what happened and its reference on the next line, any text under them).
/** @param key - keeps a long post open across redraws (messageBody) */
function timelineEntry(entry: ThreadEntry, key: string): Html {
  const by = entry.by || {},
    name = who(by) || '?';
  const head = html`<div class="msg-h">${whoWhen(name, isMe(by), name, stampSpan(entry.at, STAMP_FORM.BOTH))}</div>`;
  if (entry.ev)
    return html`<div class="msg ev ev-${entry.ev}"><span class="ev-dot" aria-hidden="true"></span><div class="msg-b">${head}\
<div class="ev-l">${translate(EVENT_LABEL[entry.ev] || entry.ev)}${hasRef(entry.ref) ? html` · <span translate="no">${entry.ref}</span>` : ''}</div>${entry.text ? messageBody(entry, key) : ''}</div></div>`;
  return html`<div class="msg">${nodeAvatar(by)}<div class="msg-b">${head}${messageBody(entry, key)}</div></div>`;
}
// The thread of a pin as Html (empty without entries): the last 3 entries in wide, the last 1 elsewhere, unless
// THREAD_OPEN holds the pin; the button that shows the rest or folds them, in a row the timeline passes (.th-row); and
// the reply slot when the pin's reply box is open.
function threadHtml(pin: Pin, wide: boolean) {
  const thread = threadOf(pin),
    keep = wide ? 3 : 1,
    all = THREAD_OPEN.has(pin.id),
    hide = all ? 0 : Math.max(0, thread.length - keep);
  const more = hide
    ? html`<div class="th-row"><button class="btn-sm btn-ghost th-more" data-act="thread-more" aria-expanded="false">${translateTemplate('이전 {n}건 보기', { n: hide })}</button></div>`
    : all && thread.length > keep
      ? html`<div class="th-row"><button class="btn-sm btn-ghost th-more" data-act="thread-more" aria-expanded="true">스레드 접기</button></div>`
      : '';
  const entries = thread.slice(hide).map((entry, index) => timelineEntry(entry, pin.id + ':' + (index + hide))),
    slot = REPLY && REPLY.id === pin.id ? html`<div class="reply-slot"></div>` : '';
  return more || entries.length || slot ? html`<div class="thread">${more}${entries}${slot}</div>` : html``;
}
function reviewerLabel(pin: Pin) {
  if (!pin.author || !(pin.author.name || pin.author.login)) return translate('확인 필요');
  return isMe(pin.author)
    ? translate('내 확인 차례')
    : translateTemplate('{name}님 확인 필요', { name: who(pin.author) });
}

export {
  MESSAGE_OPEN,
  addressedTag,
  assigneeOf,
  authorTip,
  cardMetadata,
  cardQuote,
  claimActive,
  claimLabel,
  claimTag,
  docChip,
  fmtText,
  fyiTag,
  hasRef,
  isQuestion,
  josaToward,
  locCopy,
  locText,
  mentionsMe,
  messageBody,
  messageHtml,
  nodeAvatar,
  noteHead,
  relBadge,
  reopenedTurn,
  replyCount,
  stateDot,
  threadHtml,
  threadOf,
  reviewerLabel,
  claimInfo,
};
