import {
  $$,
  ASSIGNEE_AGENT,
  CARD_DOT,
  DOC,
  DROPPED,
  KIND_REQ,
  LOCAL_LOGIN,
  META,
  OPEN_ALL,
  PEOPLE,
  PINS,
  PIN_STATE,
  RANGE_REL,
  REPLY,
  SHOW_ALL,
  STAMP_FORM,
  THREAD_EV,
  THREAD_OPEN,
} from './core.ts';
import { html, ic } from './markup.ts';
import { ccPlain } from './hidden-chars.ts';
import { tl, tr } from './i18n.ts';
import { docInfo, isRegion, multiDoc, pdoc } from './doc-tabs.ts';
import { findAnyPin } from './revisions.ts';
import { isViewer } from './boot.ts';
import { pinState } from './polling.ts';
import { rng } from './levels.ts';
import { pinPlace } from './figure.ts';
import { isMdPin } from './md-surface.ts';
import { quoteInner, shownQuote } from './composer.ts';
import { relSpan, stampSpan } from './cards.ts';
import { drawPins, isMe } from './list.ts';
import { nameShared, personLabel } from './mentions.ts';
import type { Html } from './markup.ts';

/** Native pin-card markup, including participant text, state badges and threads.
 * User-provided names and notes enter markup only through the escaping Html template. */
function who(person) {
  if (person && person.login === LOCAL_LOGIN) return tr(person.name || '로컬/에이전트');
  return (person && (person.name || person.login)) || '';
} // the stored local name is Korean ('로컬/에이전트'); shown in the UI language
const BADPIC = new Set(); // an avatar URL that has already failed is never requested again (otherwise console errors would pile up on every re-render)
// A person = a photo or an initial circle (primary color); local/agent = a faded circle with a robot icon - distinguishes people from agents at a glance.
// The initial is in a box of its own (.av-l): trimmed to its cap height, so the circle centres the letter and not its line box.
function isAgent(person) {
  return !!person && (person.login === LOCAL_LOGIN || String(person.login).startsWith('agent:'));
}
function avatar(person) {
  if (!person || !(person.name || person.login)) return html``;
  if (isAgent(person)) return html`<span class="av i agent" aria-hidden="true">${ic('bot')}</span>`;
  const initial = (who(person).trim()[0] || '?').toUpperCase();
  return person.pic && !BADPIC.has(person.pic)
    ? html`<img class="av" src="${person.pic}" alt="" referrerpolicy="no-referrer" data-ini="${initial}">`
    : html`<span class="av i" aria-hidden="true"><span class="av-l">${initial}</span></span>`;
}
document.addEventListener(
  'error',
  (event) => {
    const image = event.target as HTMLImageElement;
    if (image && image.tagName === 'IMG' && image.classList.contains('av')) {
      BADPIC.add(image.getAttribute('src'));
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
  let tip = tl('작성: {name} · {at}', { name: pin.author ? who(pin.author) : tr('기록 전'), at: pin.at || '?' });
  if (pin.edited_at)
    tip += ' / ' + tl('수정: {name} · {at}', { name: who(pin.edited_by) || tr('기록 전'), at: pin.edited_at });
  return tip;
}
// docs/handbook/api.md §겹친 핀과 덧붙이기: one representative among the rel entries - if there's an inside (the outer pin with the smallest range),
// otherwise the smallest-id partial. Must follow the same rule as the server's rel_badge() (pins.md) so card tags and
// pins.md rows never disagree - since a rel entry is only {id,rel}, the range is looked up by id from PINS (all currently loaded open pins).
// The badge wording is phrased to be self-explanatory: '#20과 같은 범위' > '#20 범위 안' > '#20과 일부 겹침'. Same-range is distinguished using p's (this pin's) lo/hi.
function josa(number, afterConsonant, afterVowel) {
  const lastDigit = String(number).slice(-1);
  return lastDigit === '0' || '13678'.includes(lastDigit) ? afterConsonant : afterVowel;
}
// '로' or '으로' after a number read in Korean: '으로' after a final consonant other than ㄹ (영/십·백·천, 삼, 육), else '로'.
// The particle after a name: c after a final consonant, v after a vowel. A Hangul name by its last syllable's final; a Latin
// one by how its end is read - a vowel letter (and a silent e) reads as a vowel, a consonant as one ('Bob이', 'Alice가'),
// a lone capital as its letter's Korean name ('Agent B가', 'Team L이'); a digit as its Korean reading (josa). Pure.
function josaName(name: string, afterConsonant: string, afterVowel: string) {
  const trimmed = String(name || '').trim(),
    last = trimmed.slice(-1);
  if (!last) return afterVowel;
  const code = last.charCodeAt(0);
  if (code >= 0xac00 && code <= 0xd7a3) return (code - 0xac00) % 28 ? afterConsonant : afterVowel;
  if (/[0-9]/.test(last)) return josa(last, afterConsonant, afterVowel);
  if (/[A-Z]/.test(last) && !/[A-Za-z]/.test(trimmed.slice(-2, -1)))
    return 'LMNR'.includes(last) ? afterConsonant : afterVowel;
  if (/[a-zA-Z]/.test(last)) return /[aeiouyAEIOUY]/.test(last) ? afterVowel : afterConsonant;
  return afterVowel;
}
function josaRo(number) {
  return '036'.includes(String(number).slice(-1)) ? '으로' : '로';
}
function relBadge(rel, pin) {
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
        label: tl('#{id}{p} 같은 범위', { id: lowestId, p: josa(lowestId, '과', '와') }),
      };
    }
  }
  const insides = rel.filter((entry) => entry.rel === RANGE_REL.INSIDE);
  if (insides.length) {
    const span = (entry) => {
      const other = byId.get(entry.id);
      return other ? (other.hi as number) - (other.lo as number) : Number.MAX_SAFE_INTEGER;
    }; // rel names line pins
    const best = insides.reduce((best, candidate) => {
      const bestSpan = span(best),
        candidateSpan = span(candidate);
      return candidateSpan < bestSpan || (candidateSpan === bestSpan && candidate.id < best.id) ? candidate : best;
    });
    return { id: best.id, rel: RANGE_REL.INSIDE, label: tl('#{id} 범위 안', { id: best.id }) };
  }
  const partials = rel.filter((entry) => entry.rel === RANGE_REL.PARTIAL).sort((left, right) => left.id - right.id);
  if (partials.length) {
    const firstId = partials[0].id;
    return {
      id: firstId,
      rel: RANGE_REL.PARTIAL,
      label: tl('#{id}{p} 일부 겹침', { id: firstId, p: josa(firstId, '과', '와') }),
    };
  }
  return null;
}
// The in-progress marker (docs/handbook/api.md §처리 중 표시 (claim)). claim_until is epoch seconds, compared independent of the browser's timezone (numbers
// instead of a wall-clock string, for the same reason as docs/handbook/build-sync.md §위치 추정). The viewer never places a claim (agent-only) - it only offers [풀기].
function claimActive(pin: Pin) {
  return typeof pin.claim_until === 'number' && pin.claim_until > Date.now() / 1000;
}
// Estimated time to handle (docs/handbook/api.md §처리 중 표시): if an agent gives eta_min on a claim, the server sets eta_ts
// (epoch). The badge shows '처리 중 · 약 15분 · 20:40쯤' - both the remaining minutes and the time are rounded up to
// 5-minute steps (an estimate is approximate). Past it, '예상보다 늦어짐 (+5분)'. A legacy claim with no eta shows
// '처리 중 · 20:02부터 (23분째)'. The lock's auto-expiry (claim_until) was misread as the estimated completion (observed:
// '~04:02'), so it's never shown on screen - only in the description. The time is the viewing device's local time. now is injected by tests.
function ceil5(minutes) {
  return Math.max(5, Math.ceil(minutes / 5 - 1e-9) * 5);
}
function clockTime(ms) {
  const date = new Date(ms);
  return String(date.getHours()).padStart(2, '0') + ':' + String(date.getMinutes()).padStart(2, '0');
}
function claimInfo(pin: Pin, now?: number) {
  now = now == null ? Date.now() : now;
  const claimer = who(pin.claimed_by) || '?',
    startMs = typeof pin.claim_ts === 'number' ? pin.claim_ts * 1000 : null;
  const tail =
    ' · ' +
    tl('잠금 자동 해제 {time}(그 뒤에는 다른 쪽이 잡을 수 있습니다). 에이전트가 멈췄으면 [풀기]', {
      time: clockTime((pin.claim_until as number) * 1000),
    }); // claimInfo runs for an active claim (claimActive)
  const head =
    tl('처리하는 쪽: {name}', { name: claimer }) +
    (startMs ? ' · ' + tl('시작 {time}', { time: clockTime(startMs) }) : '');
  if (typeof pin.eta_ts === 'number') {
    const eta = pin.eta_ts * 1000;
    if (now <= eta)
      return {
        t: tl('처리 중 · 약 {n}분 · {time}쯤', {
          n: ceil5((eta - now) / 60000),
          time: clockTime(Math.ceil(eta / 300000) * 300000),
        }),
        late: false,
        tip: head + ' · ' + tl('예상 완료 {time}', { time: clockTime(eta) }) + tail,
      };
    return {
      t: tl('예상보다 늦어짐 (+{n}분)', { n: ceil5((now - eta) / 60000) }),
      late: true,
      tip: head + ' · ' + tl('예상 완료 {time}였음', { time: clockTime(eta) }) + tail,
    };
  }
  if (startMs)
    return {
      t: tl('처리 중 · {time}부터 ({n}분째)', {
        time: clockTime(startMs),
        n: Math.max(1, Math.ceil((now - startMs) / 60000)),
      }),
      late: false,
      tip: head + ' · ' + tr('예상 시간 없음') + tail,
    };
  return { t: tr('처리 중'), late: false, tip: head + tail };
}
function claimLabel(pin: Pin, now?: number) {
  return claimInfo(pin, now).t;
}
function claimTag(pin: Pin) {
  const claim = claimInfo(pin);
  return html`<span class="badge badge-claimed${claim.late ? ' late' : ''}" data-claim="${pin.id}" data-tip="${claim.tip}">${ic('clock')}<span class="ct">${claim.t}</span></span>`;
}
// The remaining/elapsed minutes change with time - only the badge text is updated every 30 seconds (the card isn't redrawn). The list is redrawn if any pin's lock has expired.
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
// A card's location text: 'L12-L18' for a LaTeX pin, '영역' for a view-only PDF's pin (the page is a separate field). The copy format is 'file L12-L18' / 'x.pdf 쪽 3'; a
// region's page is the one its mark is on in the current build (pinPlace), which a figure pin's element can move.
function locText(pin: Pin) {
  return isRegion(pin) ? tr('영역') : rng(pin.lo, pin.hi);
}
function locCopy(pin: Pin) {
  const name =
    pin.name ||
    String(pin.file || pin.pdf || '')
      .split('/')
      .pop();
  return isRegion(pin) ? name + ' 쪽 ' + pinPlace(pin).page : name + ' L' + pin.lo + '-L' + pin.hi;
}
// The document chip attached to a card header when viewing all documents. Another document's is dashed-bordered - clicking it switches to that document.
// The name is user text (translate="no"); its description's UI words are translated here.
function docChip(pin: Pin) {
  if (!(SHOW_ALL && multiDoc())) return html``;
  const entry = docInfo(pdoc(pin)),
    other = pdoc(pin) !== DOC;
  const tip =
    (entry ? entry.name + ' · ' + entry.path : tl('{doc} (설정에 없는 문서)', { doc: pdoc(pin) })) +
    (other ? ' — ' + tr('#번호·[보기]를 누르면 이 문서로 바꿉니다') : '');
  return html`<span class="badge badge-secondary dchip${other ? ' other' : ''}" translate="no" data-tip="${tip}">${entry ? entry.name : pdoc(pin)}</span>`;
}
// Thread (docs/handbook/viewer.md §스레드와 검토): replies and state-transition records (close/reopen/confirm) form a single line of history, built with html``.
// wide shows the last 3, compact shows only the last 1, expanded via [이전 N건] (THREAD_OPEN). The input field (REPLY) is inserted in place like EDITOR.current.
function isQuestion(pin: Pin) {
  return !!pin && pin.kind_req === KIND_REQ.QUESTION;
}
// The current assignee - the recorded value (p.assignee); for a legacy pin without one, the person the server inferred (the first of p.addressed); if neither, the agent.
function assigneeOf(pin: Pin) {
  if (!pin) return ASSIGNEE_AGENT;
  if (pin.assignee) return pin.assignee;
  const addressed = pin.addressed || [];
  return addressed.length ? addressed[0] : ASSIGNEE_AGENT;
}
// The words for an assignee: the agent, me, a person's name, and '미지정' for a record without one.
function assigneeWord(assignee: string | null | undefined): string {
  return !assignee
    ? tr('미지정')
    : assignee === ASSIGNEE_AGENT
      ? tr('에이전트')
      : assignee === meLogin()
        ? tr('나')
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
    return html`<span class="cm-i as-chip sr-only">${tr('담당')} ${assigneeWord(pin.assignee)}</span>`;
  if (!pin.assignee)
    return html`<span class="cm-i as-chip"><span class="as-l">${tr('담당')} ${assigneeWord(null)}</span></span>`;
  const me = meLogin(),
    mine = pin.assignee === me,
    shared = !mine && nameShared(pin.assignee),
    name = assigneeWord(pin.assignee) + (shared ? ' ' + pin.assignee : '');
  const canEdit = pressable && !isViewer() && pinState(pin) === PIN_STATE.OPEN && (isMe(pin.author) || !me),
    tip =
      tl('담당: {name} — 에이전트는 이 핀을 건너뜁니다', { name: name }) +
      (canEdit ? tr('. 누르면 [수정]에서 담당을 바꿉니다') : '');
  const shown = shared ? personLabel(pin.assignee) : html`${name}`; // a name another known person shares carries the login, as the composer's
  return canEdit
    ? html`<button class="cm-i badge badge-assign as-chip${mine ? ' me' : ''}" data-act="edit" data-tip="${tip}"><span class="as-l">${tr('담당')} </span><span class="as-n" translate="no">${shown}</span>${ic('pencil')}</button>`
    : html`<span class="cm-i badge badge-assign as-chip${mine ? ' me' : ''}" data-tip="${tip}"><span class="as-l">${tr('담당')} </span><span class="as-n" translate="no">${shown}</span></span>`;
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
      part: html`<span class="cm-i card-meta-context${question ? '' : ' sr-only'}">${tr(question ? '질문' : '수정 요청')}</span>`,
    },
    { drawn: !agent, part: assignChip(pin, pressable) },
    {
      drawn: !open,
      part: html`<span class="cm-i card-meta-context${open ? ' sr-only' : ''}">${tr(statusLabel)}</span>`,
    },
  ];
  // Between two drawn facts ' · '; before any other fact a space only a screen reader meets, so the words never run together.
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
// Status dot (docs/handbook/viewer.md §상태 표현): color + a readable name (aria-label/description). A badge states the same meaning in text once more.
const CARD_STATE_NAME = { open: '열림', claimed: '처리 중', review: '검토 대기', lost: '위치 잃음' };
function stDot(state) {
  const label = tl('상태: {name}', { name: tr(CARD_STATE_NAME[state]) });
  return html`<span class="st-dot${state === CARD_DOT.OPEN ? '' : ' ' + state}" role="img" aria-label="${label}" data-tip="${label}"></span>`;
}
// Did the current round start with a reopen (a pin that returned from review)? True if the thread's last close/reopen record is a reopen.
function reopenedTurn(pin: Pin) {
  const thread = threadOf(pin);
  for (let i = thread.length - 1; i >= 0; i--) {
    const kind = thread[i].ev;
    if (kind === THREAD_EV.CLOSE || kind === THREAD_EV.REOPEN) return kind === THREAD_EV.REOPEN ? thread[i] : null;
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
// Turns '@name' (only resolved mentions) and '#number' (an existing pin) in text into tokens (docs/handbook/viewer.md §@태그).
// Names and numbers are found in the text as written and the result is built with html``, so the text between and
// inside the tokens stays text - what a person wrote never leaks as HTML. Names are matched with the same candidates as the server's resolve_mentions() (full
// name/login/the part of the login before @/the first word of the name), longest first, case-insensitive. Skipped when
// '@' follows a word (mentionAfterWord - an email address); a name ending in an ASCII letter followed by an ASCII letter
// (@Alicex) is a different word. An unresolved '@word' stays plain text - it must never look like it called someone.
function peopleName(login) {
  const known = PEOPLE.find((person) => person.login === login);
  return known ? known.name : login;
}
function mentionTokensOf(logins) {
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
// Whether the '@' at text[i] continues a word, so it is no tag - the server's rule: the character before it is a letter or
// digit of any script (Python's str.isalnum(): Unicode L*/N*, so 'é@' and '김@' too) or one of '._-'. That character
// is a whole code point, as Python reads it: an astral letter before '@' is two UTF-16 units.
function mentionAfterWord(text, index) {
  if (index <= 0) return false;
  const lowUnit = text.charCodeAt(index - 1),
    highUnit = index > 1 ? text.charCodeAt(index - 2) : 0;
  const before =
    lowUnit >= 0xdc00 && lowUnit <= 0xdfff && highUnit >= 0xd800 && highUnit <= 0xdbff
      ? text.slice(index - 2, index)
      : text[index - 1];
  return /^[\p{L}\p{N}._-]$/u.test(before);
}
function escapeRegExp(text) {
  return text.replace(/[.*+?^${}()|[\]\\]/g, '\\$&');
}
function meLogin() {
  const me = typeof META !== 'undefined' && META && META.me;
  return me && me.login && me.login !== LOCAL_LOGIN ? me.login : null;
}
// text as Html with its resolved @-tags (logins) and existing #refs as tokens. A match the rules turn down is consumed and
// stays text, and the text between two tags is searched for #refs only, so a name never holds a link.
function fmtText(text, logins) {
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
          ? tr('나를 부름 — 이 핀 알림이 나에게 옵니다')
          : tl('@태그 — {name}에게 알림이 갑니다', { name: peopleName(token.lg) });
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
// s with each '#12' whose pin exists as a link, as html`` values. '#12;' and a number glued to a word, digit or '#' stay
// text. A '#12' whose pin is in the Trash renders as '#12 deleted pin' (faded) and opens the Trash at that row.
function pinRefs(text: string) {
  const out: (string | Html)[] = [];
  let at = 0;
  for (const match of text.matchAll(/(^|[^0-9A-Za-z#])#(\d{1,6})(?![\d;])/g)) {
    const id = +match[2],
      start = match.index + match[1].length;
    const ref = pinRefExists(id)
      ? html`<span class="pin-ref" role="link" tabindex="0" data-act="pin-ref" data-ref="${id}" data-tip="${tl('핀 #{id} 로 갑니다', { id })}">#${id}</span>`
      : pinRefGone(id)
        ? html`<span class="pin-ref gone" role="link" tabindex="0" data-act="pin-ref" data-ref="${id}" data-tip="${tl('핀 #{id} 은 삭제되었습니다 — 누르면 휴지통에서 봅니다', { id })}">#${id} <small>${tr('삭제된 핀')}</small></span>`
        : null;
    if (!ref) continue;
    out.push(text.slice(at, start), ref);
    at = match.index + match[0].length;
  }
  out.push(text.slice(at));
  return out;
}
function pinRefExists(id) {
  return typeof findAnyPin === 'function' && !!findAnyPin(id);
}
function pinRefGone(id) {
  return typeof DROPPED !== 'undefined' && Array.isArray(DROPPED) && DROPPED.some((pin) => pin.id === id);
}
// The [나를 부른 핀] filter (docs/handbook/viewer.md §@태그): uses the same material as the badge/pins.md's '→ @name'
// (p.addressed, which the server counts only for the current round via thread_round) - the old version scanned the
// entire thread (threadOf(p).some(...)) and had a defect where an @-tag from an old round kept a pin marked "called me"
// even after reopening (observed). addressed_to() only has a value on question pins.
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
    ? html`<span class="badge badge-mention" data-tip="이 핀이 나를 @태그했습니다 — 에이전트는 이 핀을 건너뜁니다(사용자가 시키면 예외)">${ic('at-sign')}나를 부름</span>`
    : '';
  const rest = others.length
    ? html`<span class="badge badge-mention" data-tip="사람을 부른 핀입니다 — 에이전트는 사용자가 따로 시키지 않으면 건너뜁니다">${ic('at-sign')}<span translate="no">${others.map(peopleName).join(', ')}</span></span>`
    : '';
  return html`${self}${rest}`;
}
// A fix pin's FYI @-tags (never skipped) - kept separate from p.addressed (question-pin only) and sent in p.fyi instead.
function fyiTag(pin: Pin) {
  const to = pin.fyi || [];
  if (!to.length) return null;
  return html`<span class="badge badge-mention" data-tip="참고로 부른 사람입니다 — 질문이 아니라 수정 요청이라 건너뛰지 않습니다">${ic('at-sign')}${tl('참고 {names}', { names: to.map(peopleName).join(', ') })}</span>`;
}
// Is the reference (ref) a meaningful value? '-' is a placeholder QA scripts/legacy callers use for "no reference" - shown as-is
// it would produce meaningless text like '닫음 · -' (observed defect). An empty or whitespace-only value is filtered out the same way.
function hasRef(value) {
  return !!value && String(value).trim() !== '' && String(value).trim() !== '-';
}
const EVENT_LABEL = { close: '닫음', reopen: '다시 엶', confirm: '확인', assign: '담당 바꿈' };
// The cards whose quote line is open ('<doc>:<id>', toggleQuote), kept across redraws.
const QUOTE_OPEN = new Set();
// A card's quote line, right above its note: the composer's line for the pin's saved quote (shownQuote, quoteInner), folded to
// one line with the whole text as its tooltip until it is pressed. null when the pin shows no quote.
function cardQuote(pin: Pin): Html | null {
  const quote = shownQuote(pin, (docInfo(pdoc(pin)) || {}).kind);
  if (!quote) return null;
  const key = pdoc(pin) + ':' + pin.id,
    open = QUOTE_OPEN.has(key);
  return html`<div class="quote hit${open ? ' open' : ''}" role="button" tabindex="0" data-act="quote" data-key="${key}" aria-expanded="${String(open)}"\
 data-tip="${open ? null : ccPlain(quote)}" translate="no">${quoteInner(quote, isMdPin(pin))}</div>`;
}
// A long post collapses at 6 lines with [더 보기] (keyed 'id:index' in MSG_OPEN). If the author is me, '(나)'. The post and its
// author's name are user text (translate="no"); '(나)' is translated here.
const MSG_OPEN = new Set();
// A thread entry's text (user text, translate="no") clamped at 6 lines with [더 보기]/[접기] when long; key ('id:index') keeps
// it open across redraws (MSG_OPEN), and without a key it is drawn whole with no button.
function msgBody(entry: ThreadEntry, key) {
  const long = String(entry.text || '').length > 280 || String(entry.text || '').split('\n').length > 6,
    open = !key || MSG_OPEN.has(key);
  const more =
    long && key
      ? html`<button class="btn-sm btn-ghost msg-more" data-act="msg-more" data-key="${key}" aria-expanded="${open}">${open ? '접기' : '더 보기'}</button>`
      : '';
  return html`<div class="msg-t${long && !open ? ' clamp' : ''}" translate="no">${entryText(entry)}</div>${more}`;
}
// One entry of an archive row's thread: a post (avatar, author, time, text) or a state record (who, what, reference, time, optional text).
function msgHtml(entry: ThreadEntry, key) {
  const by = entry.by || {},
    name = who(by) || '?',
    mine = isMe(by) ? html`<span class="me-tag"> ${tr('(나)')}</span>` : '';
  if (entry.ev)
    return html`<div class="msg ev ev-${entry.ev}"><div class="msg-h"><b translate="no">${name}${mine}</b><span>${tr(EVENT_LABEL[entry.ev] || entry.ev)}${hasRef(entry.ref) ? ' · ' + entry.ref : ''}</span>${relSpan(entry.at)}</div>${entry.text ? msgBody(entry, key) : ''}</div>`;
  return html`<div class="msg">${avatar(by)}<div class="msg-b"><div class="msg-h"><b translate="no">${name}${mine}</b>${relSpan(entry.at)}</div>${msgBody(entry, key)}</div></div>`;
}
// A node of a card's timeline: the person's avatar, or for no recorded person an empty circle in its place, so the column, the
// line and the indent of the text hold.
function nodeAvatar(person: Person | null | undefined): Html {
  return who(person) ? avatar(person) : html`<span class="av none" aria-hidden="true"></span>`;
}
// Who and when at the start of a card's comment or entry head, kept on one line (.who): the name ends in an ellipsis where the
// line is short, its whole text staying the element's text and its description (tip), and '(나)' and the time are never cut.
// The name and its tip are user text: the element holding both is translate="no", so a person named '완료' is not 'Done' in
// either; '(나)' and the tip's own words are translated here. cls marks a name with no recorded person.
function whoWhen(name: string, mine: boolean, tip: string, time: Html | string, className?: string): Html {
  const me = mine ? html`<span class="me-tag"> ${tr('(나)')}</span>` : ''; // the space is the text's; drawn, the margin is
  return html`<span class="who"><b class="${className || ''}" translate="no" data-tip="${tip}"><span class="nm">${name}</span>${me}</b>${time}</span>`;
}
// The head of a card's first comment, a reply's: who wrote the note ('기록 전' for a pin from before authors were recorded), when,
// and when it was last edited, which takes the next line where the first has no room. The name's description also says who
// edited it.
function noteHead(pin: Pin): Html {
  const name = who(pin.author);
  return html`<div class="msg-h note-h">${whoWhen(name || tr('기록 전'), isMe(pin.author), authorTip(pin), pin.at ? stampSpan(pin.at, STAMP_FORM.BOTH) : '', name ? '' : 'old')}\
${pin.edited_at ? stampSpan(pin.edited_at, STAMP_FORM.EDITED) : ''}</div>`;
}
// One entry of a card's timeline: a post (avatar, then name and time over its text) or a state record (a dot in the avatar's
// place, then name and time, what happened and its reference on the next line, any text under them).
/** @param key - keeps a long post open across redraws (msgBody) */
function timelineEntry(entry: ThreadEntry, key: string): Html {
  const by = entry.by || {},
    name = who(by) || '?';
  const head = html`<div class="msg-h">${whoWhen(name, isMe(by), name, stampSpan(entry.at, STAMP_FORM.BOTH))}</div>`;
  if (entry.ev)
    return html`<div class="msg ev ev-${entry.ev}"><span class="ev-dot" aria-hidden="true"></span><div class="msg-b">${head}\
<div class="ev-l">${tr(EVENT_LABEL[entry.ev] || entry.ev)}${hasRef(entry.ref) ? html` · <span translate="no">${entry.ref}</span>` : ''}</div>${entry.text ? msgBody(entry, key) : ''}</div></div>`;
  return html`<div class="msg">${nodeAvatar(by)}<div class="msg-b">${head}${msgBody(entry, key)}</div></div>`;
}
// The thread of p as Html (empty without entries): the last 3 entries in wide, the last 1 elsewhere, unless THREAD_OPEN
// holds p; the button that shows the rest or folds them, in a row the timeline passes (.th-row); and the reply slot when p's
// reply box is open.
function threadHtml(pin: Pin, wide) {
  const thread = threadOf(pin),
    keep = wide ? 3 : 1,
    all = THREAD_OPEN.has(pin.id),
    hide = all ? 0 : Math.max(0, thread.length - keep);
  const more = hide
    ? html`<div class="th-row"><button class="btn-sm btn-ghost th-more" data-act="thread-more" aria-expanded="false">${tl('이전 {n}건 보기', { n: hide })}</button></div>`
    : all && thread.length > keep
      ? html`<div class="th-row"><button class="btn-sm btn-ghost th-more" data-act="thread-more" aria-expanded="true">스레드 접기</button></div>`
      : '';
  const entries = thread.slice(hide).map((entry, index) => timelineEntry(entry, pin.id + ':' + (index + hide))),
    slot = REPLY && REPLY.id === pin.id ? html`<div class="reply-slot"></div>` : '';
  return more || entries.length || slot ? html`<div class="thread">${more}${entries}${slot}</div>` : html``;
}
export {
  MSG_OPEN,
  QUOTE_OPEN,
  addressedTag,
  assigneeOf,
  authorTip,
  avatar,
  cardMetadata,
  cardQuote,
  claimActive,
  claimLabel,
  claimTag,
  docChip,
  fmtText,
  fyiTag,
  hasRef,
  isAgent,
  isQuestion,
  josa,
  josaName,
  josaRo,
  locCopy,
  locText,
  meLogin,
  mentionAfterWord,
  mentionsMe,
  msgBody,
  msgHtml,
  nodeAvatar,
  noteHead,
  peopleName,
  relBadge,
  reopenedTurn,
  replyCount,
  stDot,
  threadHtml,
  threadOf,
  who,
};
