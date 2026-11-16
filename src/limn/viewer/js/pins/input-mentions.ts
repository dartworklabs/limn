// ------------------------------------------------ @-tag autocomplete (docs/handbook/viewer.md §@태그)
// Typing '@' in the note/edit/reply field shows known people (PEOPLE, excluding me). Picking one inserts '@name ' and
// remembers that login on the field (field._mentions) with the place of its '@name' in the text (field._tags), carried
// as a hint (mentions) when sending - the server re-resolves it from the text. A hint belongs to its one '@name': an
// edit that touches that tag drops it, so of two people with one name, deleting one's tag leaves only the other's hint.
// A field that mirrors another's text (the note popover's field mirrors the composer's note, sel-popover.ts) offers the
// same list, and its tags are kept on the field it mirrors, which sends them (mentionModel). There is no external
// notification. The open @-list: its field, the '@word' it was drawn for (where its '@' is, q the letters after it),
// its people and the highlighted row.
import {
  $,
  ASSIGNEE_AGENT,
  KIND_NEW,
  META,
  PEOPLE,
  PEOPLE_KNOWN,
  PINS,
  SAVE_MODE,
  imeKey,
  imeTail,
} from '../app/state.ts';
import { html, lucideIcon, setHtml } from '../platform/markup.ts';
import { translateTemplate, translate } from '../platform/i18n.ts';
import { revealSegment } from '../composer/view-levels.ts';
import { appendTarget, syncQuestionHint } from '../composer/flow-pick.ts';
import { saveDraftSoon } from '../composer/flow-draft.ts';
import { avatar, meLogin, mentionAfterWord, peopleName } from './view-card-parts.ts';
import { renderReplyOutcome } from './flow-reply.ts';
import { EDITOR, autoGrow, editNote } from './flow-edit.ts';
import { segmentFocusAt, keepSegmentFocus, roveSegment } from '../main.ts';
import type { Html } from '../platform/markup.ts';

const MENTION = {
  ta: null as HTMLTextAreaElement | null,
  start: 0,
  q: '',
  items: [] as PersonSeen[],
  sel: 0,
};
function mentionQuery(field) {
  const pos = field.selectionStart;
  if (pos == null || pos !== field.selectionEnd) return null;
  const match = /(^|[^\p{L}\p{N}._@-])@([^\s@]{0,30})$/u.exec(field.value.slice(0, pos));
  return match ? { start: pos - match[2].length - 1, q: match[2] } : null;
}
function mentionMatches(query, people, meLogin) {
  query = String(query || '').toLowerCase();
  const rows = people
    .filter((person) => person.login !== meLogin)
    .map((person) => {
      const name = String(person.name || '').toLowerCase(),
        login = person.login.toLowerCase();
      const at = Math.min(
        ...[name.indexOf(query), login.indexOf(query)].filter((position) => position >= 0).concat([99]),
      );
      const word = name.split(/\s+/).some((part) => part.startsWith(query));
      return { p: person, rank: !query ? 0 : at === 0 ? 0 : word ? 1 : at < 99 ? 2 : 9 };
    });
  return rows
    .filter((row) => row.rank < 9)
    .sort((left, right) => left.rank - right.rank || String(left.p.name).localeCompare(String(right.p.name)))
    .slice(0, 6)
    .map((row) => row.p);
}
// The hints a send carries: the logins of the field's tags that are tags in its text now (an '@name' right after a
// letter is none, as for the server; typing a new tag right before an old one makes one for a moment), in text order.
function mentionHints(field: HTMLTextAreaElement | null): string[] {
  if (!field) return [];
  const text = field.value;
  return [
    ...new Set(
      mentionTags(field)
        .filter((tag) => !mentionAfterWord(text, tag.at))
        .map((tag) => tag.login),
    ),
  ];
}
// The field's tags for the text it holds. When its text or its logins were set from outside (a draft, a stored pin, a
// reply's draft) the tags are worked out again from the logins, which are in text order: each takes the next '@name' of
// its name that no earlier one took.
function mentionTags(field: HTMLTextAreaElement): MentionTag[] {
  if (field._tags && field._tagsFor === field.value && field._tagsFrom === field._mentions) return field._tags;
  field._tags = mentionBind(
    Array.from(field._mentions || []).map((login) => ({ login: login, tok: '@' + peopleName(login) })),
    field.value,
  );
  field._tagsFor = field.value;
  field._tagsFrom = field._mentions;
  return field._tags;
}
// Each of picks ({login, tok}) bound to the first '@name' (tok) in text that a tag can start at and no earlier pick
// took; a pick whose name is not there is dropped. Pure.
function mentionBind(picks: { login: string; tok: string }[], text: string): MentionTag[] {
  const taken = new Set(),
    out = [] as MentionTag[];
  for (const pick of picks) {
    let position = text.indexOf(pick.tok);
    while (position >= 0 && (taken.has(position) || mentionAfterWord(text, position)))
      position = text.indexOf(pick.tok, position + 1);
    if (position >= 0) {
      taken.add(position);
      out.push({ login: pick.login, at: position, tok: pick.tok });
    }
  }
  return out.sort((left, right) => left.at - right.at);
}
// The tags of old after an edit made it now, with the caret at caret afterwards: the edit is the one span where the two
// differ. Typing, pasting and deleting leave the caret at its end, so of two equal '@name's the one at the caret is the
// one edited; when the caret says otherwise (a script set the text) the smallest span is taken. A tag the edit
// overlapped, or typed into, is dropped - its person is not named there - and a tag after it moves by what the edit
// added or took away. A tag whose '@name' is not where it moved to is dropped too; one that a letter now precedes stays
// (it is no tag until that letter goes: mentionHints). Pure.
function mentionShift(tags: MentionTag[], old: string, now: string, caret: number): MentionTag[] {
  const minLength = Math.min(old.length, now.length);
  const span = (tail: number) => {
    let prefix = 0,
      suffix = 0;
    while (suffix < minLength && suffix < tail && old[old.length - 1 - suffix] === now[now.length - 1 - suffix])
      suffix++;
    while (prefix < minLength - suffix && old[prefix] === now[prefix]) prefix++;
    return { p: prefix, s: suffix, size: old.length + now.length - 2 * (prefix + suffix) };
  };
  const at = span(Math.max(0, now.length - caret)),
    free = span(Math.max(0, minLength - mentionCommonStart(old, now))),
    { p: prefix, s: suffix } = free.size < at.size ? free : at;
  const end = old.length - suffix,
    delta = now.length - old.length;
  return tags
    .filter((tag) =>
      end > prefix
        ? !(tag.at < end && prefix < tag.at + tag.tok.length)
        : !(tag.at < prefix && prefix < tag.at + tag.tok.length),
    )
    .map((tag) => (tag.at >= end ? { login: tag.login, at: tag.at + delta, tok: tag.tok } : tag))
    .filter((tag) => now.startsWith(tag.tok, tag.at));
}
// How many characters old and now share from their start. Pure.
function mentionCommonStart(old: string, now: string): number {
  let shared = 0;
  const minLength = Math.min(old.length, now.length);
  while (shared < minLength && old[shared] === now[shared]) shared++;
  return shared;
}
// Follows an edit of the field's text (an input event, or the note popover's text copied in): its tags move with the
// edit or drop out, and its logins become theirs. caret is where the edit left the caret.
function mentionEdited(field: HTMLTextAreaElement, caret?: number) {
  const known = field._tags && field._tagsFrom === field._mentions && field._tagsFor != null;
  const tags = known
    ? mentionShift(
        field._tags as MentionTag[],
        field._tagsFor as string,
        field.value,
        caret == null ? field.selectionStart : caret,
      )
    : mentionTags(field);
  mentionKeep(field, tags);
}
// Stores tags as the field's own for its present text, with the logins they name (in text order) as field._mentions.
function mentionKeep(field: HTMLTextAreaElement, tags: MentionTag[]) {
  field._tags = tags;
  field._tagsFor = field.value;
  field._mentions = field._tagsFrom = tags.length ? new Set(tags.map((tag) => tag.login)) : null;
}
// The field that keeps a field's tags and sends them: the field it mirrors (field._mirrorOf, whose text the field's own
// listener keeps equal to its own), else the field itself.
function mentionModel(field: HTMLTextAreaElement): HTMLTextAreaElement {
  return field._mirrorOf || field;
}
// Shows the model's text in each field that mirrors it. A mirror's own listeners copy only what is typed in the model
// (an input event), and a pick writes the model's text from code.
function mentionMirror(model: HTMLTextAreaElement) {
  document.querySelectorAll('textarea').forEach((mirror) => {
    if (mirror._mirrorOf === model && mirror.value !== model.value) mirror.value = model.value;
  });
}
// Whether the caret of the open list's field still ends the '@word' the list was drawn for.
function mentionCurrent() {
  const field = MENTION.ta,
    query = field && mentionQuery(field);
  return !!query && query.start === MENTION.start && query.q === MENTION.q;
}
// An '@word' still being typed (the cursor sits at its end) is never flagged as '등록된 사람이 아님' yet - the warning
// would show while the person is still picking. It is flagged once the cursor leaves it or the field. If the same word
// appears earlier too (an '@word' already finished), it is flagged as usual.
function mentionBadSettled(bad, text, typing) {
  if (!typing) return bad;
  const typed = typing.q,
    before = String(text || '').slice(0, typing.start);
  return bad.filter((badWord) => badWord !== typed || before.includes('@' + typed));
}
function mentionClose() {
  MENTION.ta = null;
  $('#mention-pop').hidden = true;
}
// The line below the input field: who will be notified on save (resolved @names) and any '@word' that won't resolve
// ('not a registered person'). Since text can't be colored inside a textarea, this is previewed here instead - so it's
// known before saving whether a tag will actually become a notification. It is the server's resolve_mentions() step for
// step (src/limn/viewer/tests/test_mentions_parity.py runs one corpus through both): hit is what the server records, in
// first-seen order.
function mentionScan(text: string, hints?: Iterable<string>): { hit: string[]; bad: string[] } {
  return mentionResolve(text, hints || [], PEOPLE, false);
}
// mentionScan's reading over an explicit list of people. A name several people share tags those of them the hints name:
// in the server's order (by login), or with byHint in the hints' own order - the order the text names them
// (mentionKeep), which is what decides who was tagged first (assignOutcome). Pure.
function mentionResolve(
  text: string,
  hints: Iterable<string>,
  people: PersonSeen[],
  byHint: boolean,
): { hit: string[]; bad: string[] } {
  text = String(text || '');
  const tokens = mentionTokens(people),
    order = [...hints],
    hinted = new Set(order);
  const hit = [] as string[],
    bad = [] as string[],
    low = text.toLowerCase();
  for (let i = 0; i < text.length; i++) {
    if (text[i] !== '@' || mentionAfterWord(text, i)) continue;
    const rest = low.slice(i + 1);
    let got = null as string[] | null;
    for (const token of tokens) {
      if (!rest.startsWith(token.t)) continue;
      const after = rest.charAt(token.t.length);
      if (/[a-z0-9]$/.test(token.t) && /[a-z0-9_]/.test(after)) continue;
      const pick =
        token.lg.length === 1
          ? token.lg
          : byHint
            ? order.filter((login) => token.lg.includes(login))
            : token.lg.filter((login) => hinted.has(login));
      if (pick.length) {
        got = pick;
        break;
      }
    }
    if (got)
      got.forEach((login) => {
        if (!hit.includes(login)) hit.push(login);
      });
    else {
      const word = /^[^\s@]{1,30}/.exec(text.slice(i + 1));
      if (word && !bad.includes(word[0])) bad.push(word[0]);
    }
  }
  return { hit, bad };
}
// The server's mention_tokens(): [{t, lg:[login...]}], longest first. The candidates of a person are the full name, the
// login, the login before '@' and the name's first word (when it has several), lower-cased; a candidate shorter than
// two characters (code points, as Python counts) is none. The same candidate twice for one person is one entry ('Bob'
// for bob@example.com), and a candidate several people share lists them all (sorted) - it then needs a hint.
function mentionTokens(people) {
  const by = new Map();
  (people || []).forEach((person) => {
    const login = String(person.login),
      name = String(person.name || ''),
      words = name.split(/\s+/).filter(Boolean);
    [name, login, login.split('@')[0]].concat(words.length > 1 ? [words[0]] : []).forEach((candidate) => {
      if ([...candidate].length < 2) return;
      const key = candidate.toLowerCase();
      if (!by.has(key)) by.set(key, new Set());
      by.get(key).add(login);
    });
  });
  return [...by]
    .map(([candidate, logins]) => ({ t: candidate, lg: [...logins].sort() }))
    .sort((left, right) => [...right.t].length - [...left.t].length);
}
// The colleagues a note tags, in the order it first names them - whom an assignee row offers. A colleague is a resolved
// @-tag that is not me (the server drops a tag of its author too), so an unresolved word, a tag taken out of the text
// and a tag of myself are nobody. keep (an edit card's stored assignee) stays offered after its tag left the note.
// Pure.
function assignPeople(
  text: string,
  hints: Iterable<string>,
  people: PersonSeen[],
  me: string | null,
  keep?: string,
): string[] {
  const out = mentionResolve(text, hints, people, true).hit.filter((login) => login !== me);
  if (keep && keep !== ASSIGNEE_AGENT && !out.includes(keep)) out.push(keep);
  return out;
}
// Assignee (docs/handbook/viewer.md §담당): what a save of the composer's note does. Every input is an argument - text,
// kind (the request kind), hints (the logins picked from the @-list, in the order the text names them), people (the
// known people), me (the author's login, null on the identity-less screen), mode and pick (the assignee row's state) -
// so the preview line, the assignee row and the request all read one answer, worked out when each needs it.
// - SAVE_MODE.NEW, a new pin: its assignee is the author's pick while that stands (kept: the agent, or a colleague the
//   note still tags), else the first colleague the note tags, wherever the tag sits and whatever the kind, else the
//   agent. told are the colleagues who are only notified - the assignee is told through the assignment.
// - SAVE_MODE.APPEND, the note joins an existing pin: that pin's assignee (stored) and kind stay as they are, there is
//   nobody to choose (people is empty), and every colleague the note tags is told.
// Pure.
function assignOutcome(inputs: {
  text: string;
  kind: string;
  hints: string[];
  people: PersonSeen[];
  me: string | null;
  mode: string;
  pick: { v: string; touched: boolean };
  stored?: string | null;
}): { mode: string; kind: string | null; people: string[]; assignee: string | null; told: string[]; kept: boolean } {
  const tagged = assignPeople(inputs.text, inputs.hints, inputs.people, inputs.me);
  if (inputs.mode === SAVE_MODE.APPEND)
    return { mode: inputs.mode, kind: null, people: [], assignee: inputs.stored || null, told: tagged, kept: false };
  const kept = inputs.pick.touched && (inputs.pick.v === ASSIGNEE_AGENT || tagged.includes(inputs.pick.v)),
    assignee = kept ? inputs.pick.v : tagged.length ? tagged[0] : ASSIGNEE_AGENT;
  return {
    mode: inputs.mode,
    kind: inputs.kind,
    people: tagged,
    assignee,
    told: tagged.filter((login) => login !== assignee),
    kept,
  };
}
// assignOutcome's inputs as the composer holds them at this moment, for a save in mode; an append reads the pin it
// joins.
function composeAsk(mode: string): Parameters<typeof assignOutcome>[0] {
  const noteField = $('#note') as HTMLTextAreaElement,
    overlap = mode === SAVE_MODE.APPEND ? appendTarget() : null,
    pin = overlap ? PINS.find((listed) => listed.id === overlap.id) : null;
  return {
    text: noteField.value,
    kind: KIND_NEW,
    hints: mentionHints(noteField),
    people: PEOPLE,
    me: meLogin(),
    mode,
    pick: { v: ASSIGN_NEW.v, touched: ASSIGN_NEW.touched },
    stored: pin ? pin.assignee || null : null,
  };
}
// A person's name where the reader must tell people apart (an assignee row, the composer's preview line): the name,
// with the login beside it for a name another known person shares - as the @-list shows every person (.ml).
function personLabel(login: string): Html {
  return nameShared(login) ? html`${peopleName(login)} <span class="ml">${login}</span>` : html`${peopleName(login)}`;
}
// Whether another known person has login's displayed name.
function nameShared(login: string): boolean {
  const name = peopleName(login);
  return PEOPLE.some((person) => person.login !== login && person.name === name);
}
// The assignee row (Html) for people, value pressed; empty Html without people. Each option carries act as its
// data-act. The track scrolls sideways inside the row when it is longer (.lad, the range ladder's rule), so every name
// reads in full; its scroll box is out of the Tab order as the ladder's is (levels.ts drawLadder). A segment's words
// are in .as-t, trimmed to their cap height like the row's label, so the two share one centre in any font.
function assigneeRowHtml(people: string[], value: string, act: string): Html {
  if (!people.length) return html``;
  const opt = (text, label, tip) =>
    html`<button type="button" role="radio" data-act="${act}" data-v="${text}" aria-checked="${text === value}"${text === value ? html` class="on"` : ''} data-tip="${tip}"><span class="as-t">${label}</span></button>`;
  const agent = opt(
    ASSIGNEE_AGENT,
    translate('에이전트'),
    translate('에이전트가 이 핀을 처리합니다 — @태그한 사람에게는 알림만 갑니다'),
  );
  const others = people.map((login) =>
    opt(
      login,
      html`@${personLabel(login)}`,
      translateTemplate('{name}에게 맡깁니다 — 에이전트는 이 핀을 건너뜁니다', {
        name: peopleName(login) + (nameShared(login) ? ' (' + login + ')' : ''),
      }),
    ),
  );
  return html`<span class="as-lab">${translate('담당')}</span><div class="seg lad as-seg" data-reveal="whole" tabindex="-1"><div class="lad-t">${agent}${others}</div></div>`;
}
// The composer panel's assignee: the author's pick (touched) or, until there is one, the default re-chosen every time
// the note changes. A pick whose person left the note is dropped. Both assignee rows read the note with the hints the
// save carries (mentionHints), so they offer exactly whom the server tags.
const ASSIGN_NEW = { v: ASSIGNEE_AGENT, touched: false };
// Draws the composer's assignee row and the preview line from the note as it is now (assignOutcome), and drops a pick
// whose person left the note. No row without a tagged colleague - the agent has the pin - and none while the note would
// join an existing pin (appendTarget): an append keeps that pin's assignee, so the row would choose nothing. Before the
// people list has arrived (PEOPLE_KNOWN) no pick is dropped: a draft restored at boot keeps its pick until its person
// can be looked up (loadPeople draws the row again). savePin() does not read what is settled here: it asks
// assignOutcome itself.
function renderAssignNew() {
  const noteField = $('#note'),
    box = $('#c-assign');
  if (!noteField || !box) return;
  const outcome = assignOutcome(composeAsk(SAVE_MODE.NEW));
  if (PEOPLE_KNOWN) {
    ASSIGN_NEW.v = outcome.assignee as string;
    ASSIGN_NEW.touched = outcome.kept;
  }
  if (outcome.people.length && !appendTarget()) {
    const at = segmentFocusAt(box);
    setHtml(box, assigneeRowHtml(outcome.people, outcome.assignee as string, 'assign-new'));
    box.hidden = false;
    roveSegment(box);
    keepSegmentFocus(box, at);
    revealSegment(box.querySelector('.as-seg'));
  } // one Tab stop, and the focus kept (events.ts)
  else {
    box.hidden = true;
    box.replaceChildren();
  }
  mentionPreview(noteField);
}
// The edit card's assignee row: the stored assignee stays pressed until the author changes it - a stored pin never
// takes the new pin's default.
function renderAssignEdit() {
  const card = EDITOR.current;
  if (!card) return;
  const noteField = editNote(card),
    box = card.el.querySelector('.e-assign') as HTMLElement;
  if (!noteField || !box) return;
  const people = assignPeople(noteField.value, mentionHints(noteField), PEOPLE, meLogin(), card.assignee);
  if (!people.length) {
    box.hidden = true;
    box.replaceChildren();
    return;
  }
  const at = segmentFocusAt(box);
  setHtml(box, assigneeRowHtml(people, card.assignee, 'assign-edit'));
  box.hidden = false;
  roveSegment(box);
  keepSegmentFocus(box, at);
  revealSegment(box.querySelector('.as-seg'));
} // one Tab stop, and the focus kept (events.ts)
// The preview line under a mention field: what sending the text does. The composer's note says who handles the pin
// first - '담당' and the assignee the save sends (assignOutcome, SAVE_MODE.NEW) - then '알림' and the people who are
// only notified: the assignee is told through the assignment and is not listed again. While the note may also join an
// existing pin (appendTarget - the overlap notice's [덧붙이기]) the line says only what each action changes: '알림' and
// everyone the note tags, whom appending tells, then - once a colleague is tagged - ' · 따로 저장하면 담당' and the
// assignee a separate save sends. Appending leaves that pin's assignee as it is, so the line says nothing of it. The
// two are groups (.m-grp) that never break inside: the line breaks only after the separator, which ends the first, and
// a group wider than the line cuts its names with an ellipsis (their whole text stays). An edit or a reply assigns
// nobody and lists whom it notifies. Hidden while the text has no '@' word to report.
function mentionPreview(field) {
  if (!field) return;
  const box = field.nextElementSibling;
  if (!box || !box.classList.contains('m-preview')) return;
  const scan = mentionScan(field.value, mentionHints(field)),
    me = meLogin(); // the same hints the save/send carries
  // the field, or a field that mirrors it, being typed in
  const focused = document.activeElement as HTMLTextAreaElement | null;
  scan.bad = mentionBadSettled(
    scan.bad,
    field.value,
    focused && mentionModel(focused) === field ? mentionQuery(focused) : null,
  );
  if (!scan.hit.length && !scan.bad.length) {
    box.hidden = true;
    box.replaceChildren();
    return;
  }
  const outcome = field.id === 'note' ? assignOutcome(composeAsk(SAVE_MODE.NEW)) : null,
    join = outcome && appendTarget() ? assignOutcome(composeAsk(SAVE_MODE.APPEND)) : null;
  const told = outcome && !join ? scan.hit.filter((login) => login !== outcome.assignee) : scan.hit;
  const name = (login) =>
    login === ASSIGNEE_AGENT
      ? html`<span class="m-who">${translate('에이전트')}</span>`
      : html`<span class="mention">${personLabel(login)}</span>`;
  const hits = told.length
    ? html`<span class="m-lab">${lucideIcon('at-sign')}알림</span>${told.map((login) => html`<span class="mention${login === me ? ' me' : ''}">${personLabel(login)}${login === me ? ' ' + translate('(나 — 알림 없음)') : ''}</span>`)}`
    : '';
  const assigns = outcome
    ? html`<span class="m-lab">${translate(join ? '따로 저장하면 담당' : '담당')}</span>${name(outcome.assignee as string)}`
    : html``;
  const head = !outcome
    ? hits
    : !join
      ? html`${assigns}${hits}`
      : join.told.length
        ? html`<span class="m-grp">${hits}<span class="m-sep">·</span></span><span class="m-grp">${assigns}</span>`
        : hits;
  const bad = scan.bad.map(
    (word) =>
      html`<span class="mention-bad" data-tip="등록된 사람이 아님 — 이 이름으로는 알림이 가지 않습니다. 핀이나 답글을 남긴 적 있는 사람과 멤버로 등록된 사람만 부를 수 있습니다">@${word}</span>`,
  );
  setHtml(box, html`${head}${bad}${scan.bad.length ? html`<span class="m-note">등록된 사람이 아님</span>` : ''}`);
  box.hidden = false;
}
function mentionUpdate(field) {
  const query = mentionQuery(field);
  if (!query) {
    if (MENTION.ta === field) mentionClose();
    return;
  }
  const me = META && META.me && META.me.login;
  MENTION.ta = field;
  MENTION.start = query.start;
  MENTION.q = query.q;
  MENTION.items = mentionMatches(query.q, PEOPLE, me);
  MENTION.sel = Math.min(MENTION.sel, Math.max(0, MENTION.items.length - 1));
  const pop = $('#mention-pop');
  const none =
    (query.q
      ? translateTemplate("'{q}' 와 맞는 사람이 없습니다", { q: query.q })
      : translate('부를 수 있는 사람이 없습니다')) +
    ' — ' +
    translate('핀이나 답글을 남긴 적 있는 사람과 멤버로 등록된 사람만 부를 수 있습니다');
  setHtml(
    pop,
    MENTION.items.length
      ? html`${MENTION.items.map(
          (
            person,
            index,
          ) => html`<button type="button" role="option" aria-selected="${index === MENTION.sel}" data-act="mention-pick" data-i="${index}">\
${avatar(person)}<span>${person.name}</span><span class="ml">${person.login}</span></button>`,
        )}`
      : html`<div class="dim">${none}</div>`,
  );
  pop.hidden = false;
  mentionPlace();
}
// Puts the open @-list by its field (mentionTop; the note popover's field: mentionRoom, which may cut the list, keeping
// its highlighted row in view), inside the window's width. Also run when the field moves under the list (the note
// popover follows its box: placeSelectionPopover).
function mentionPlace() {
  const field = MENTION.ta,
    pop = $('#mention-pop');
  if (!field || pop.hidden) return;
  const was = pop.scrollTop;
  pop.style.maxHeight = '';
  const fieldRect = field.getBoundingClientRect(),
    listHeight = pop.offsetHeight,
    listWidth = pop.offsetWidth,
    viewport = window.visualViewport,
    guard = mentionGuard(field);
  const guardRect = guard ? guard.getBoundingClientRect() : null,
    top = viewport ? viewport.offsetTop : 0,
    bottom = viewport ? viewport.offsetTop + viewport.height : innerHeight;
  const at = field.closest('#sel-pop')
    ? mentionRoom(fieldRect, guardRect, listHeight, top, bottom)
    : { top: mentionTop(fieldRect, guardRect, listHeight, top, bottom), max: null };
  pop.style.top = at.top + 'px';
  pop.style.left = Math.max(4, Math.min(fieldRect.left, innerWidth - listWidth - 4)) + 'px';
  if (at.max == null) return;
  pop.style.maxHeight = at.max + 'px';
  const selected = pop.querySelector('[aria-selected=true]') as HTMLElement | null;
  pop.scrollTop = selected
    ? Math.min(selected.offsetTop, Math.max(was, selected.offsetTop + selected.offsetHeight - pop.clientHeight))
    : was;
}
// The action row of that input field that the @-list must never cover: reply/reopen [취소][보내기], edit [저장], the
// note popover by the box [자세히 →][저장], composer panel [취소][핀 저장].
function mentionGuard(field) {
  const box = field.closest('.reply-box,.edit,#sel-pop');
  return box ? box.querySelector('.r-acts,.e-acts,.sp-acts') : field.id === 'note' ? $('#c-actions') : null;
}
// The @-list's top (docs/handbook/viewer.md §@태그). A spot that never covers the action row (guard) is chosen in this
// order - (1) right below the input field (if it fits above the action row) (2) above the input field (3) below the
// action row (4) if nothing fits, below the input field (the note popover's field takes mentionRoom instead). A reply
// field has [취소][보내기] right below it, so (1) never fits there and (2) keeps the list off both buttons.
function mentionTop(fieldRect, guardRect, listHeight, top, bottom) {
  const gap = 4,
    limit = guardRect && guardRect.top >= fieldRect.bottom ? Math.min(bottom, guardRect.top) : bottom;
  if (fieldRect.bottom + gap + listHeight <= limit) return fieldRect.bottom + gap;
  if (fieldRect.top - gap - listHeight >= top + gap) return fieldRect.top - gap - listHeight;
  if (guardRect && guardRect.bottom + gap + listHeight <= bottom) return guardRect.bottom + gap;
  return Math.max(top + gap, Math.min(fieldRect.bottom + gap, bottom - listHeight - gap));
}
// The @-list's spot by the note popover's field, whose action row ([자세히 →][저장]) it never covers: mentionTop's spot
// when one of (1)-(3) holds all listHeight px of the list (max null). Otherwise (a short window) not mentionTop's (4),
// which covers the field and that row, but the roomiest of (1)-(3), the list cut to its room (max px; the list
// scrolls). Pure.
function mentionRoom(
  fieldRect: { top: number; bottom: number },
  guardRect: { top: number; bottom: number } | null,
  listHeight: number,
  top: number,
  bottom: number,
): { top: number; max: number | null } {
  const gap = 4,
    limit = guardRect && guardRect.top >= fieldRect.bottom ? Math.min(bottom, guardRect.top) : bottom;
  // Each spot's room, and its edge: the list's top there, or (up) its bottom.
  const spots = [
    { room: limit - fieldRect.bottom - gap, edge: fieldRect.bottom + gap, up: false },
    { room: fieldRect.top - gap - (top + gap), edge: fieldRect.top - gap, up: true },
  ];
  if (guardRect) spots.push({ room: bottom - guardRect.bottom - gap, edge: guardRect.bottom + gap, up: false });
  const whole = spots.find((spot) => spot.room >= listHeight);
  if (whole) return { top: whole.up ? whole.edge - listHeight : whole.edge, max: null };
  const roomiest = spots.reduce((best, spot) => (spot.room > best.room ? spot : best)),
    fitted = Math.max(0, Math.floor(roomiest.room));
  return { top: roomiest.up ? roomiest.edge - fitted : roomiest.edge, max: fitted };
}
// Inserts the picked person as '@name ' at the cursor, remembers the login as a hint with the place of its tag (the
// tags after it move along) on the field's model (mentionModel: a mirror field's text goes to the field it mirrors,
// which keeps the tags), shows the text in the fields that mirror the model, and refreshes what depends on the model
// (the preview, the assignee, the reply outcome; the note's draft). When the caret has left the end of the '@word' the
// list was drawn for (it moved, and no keyup or click has redrawn the list yet), nothing is inserted - the name would
// land where the caret went, spliced into the text - and the list follows the caret instead.
function mentionApply(index) {
  const field = MENTION.ta,
    person = MENTION.items[index];
  if (!field || !person) return;
  if (!mentionCurrent()) {
    mentionUpdate(field);
    return;
  }
  const model = mentionModel(field),
    pos = field.selectionStart,
    inserted = '@' + person.name + ' ';
  const old = field.value,
    before = mentionTags(model);
  field.value = old.slice(0, MENTION.start) + inserted + old.slice(pos);
  const caret = MENTION.start + inserted.length;
  field.setSelectionRange(caret, caret);
  if (model !== field) model.value = field.value;
  mentionMirror(model);
  const tags = mentionShift(before, old, field.value, caret)
    .concat([{ login: person.login, at: MENTION.start, tok: '@' + person.name }])
    .sort((left, right) => left.at - right.at);
  mentionKeep(model, tags);
  mentionClose();
  field.focus();
  autoGrow(model);
  if (model.id === 'note') {
    renderAssignNew();
    saveDraftSoon();
    return;
  } // the composer's row draws its preview line too
  mentionPreview(model);
  if (model.classList.contains('e-note')) renderAssignEdit();
  else if (model.classList.contains('r-text')) renderReplyOutcome();
}
const isMentionField = (target) =>
  !!target &&
  target.tagName === 'TEXTAREA' &&
  (target.id === 'note' ||
    target.classList.contains('e-note') ||
    target.classList.contains('r-text') ||
    !!target._mirrorOf);
// A mirror field's own listener has copied its text and the edit into its model (sel-popover.ts); here it only gets the
// list.
document.addEventListener('input', (event) => {
  const field = event.target as HTMLTextAreaElement;
  if (!isMentionField(field)) return;
  if (mentionModel(field) !== field) {
    mentionUpdate(field);
    return;
  }
  mentionEdited(field);
  mentionUpdate(field);
  if (field.id === 'note') {
    renderAssignNew();
    syncQuestionHint($('#c-qhint'), field.value, KIND_NEW);
    saveDraftSoon();
    return;
  } // the row draws the preview line too
  mentionPreview(field);
  if (field.classList.contains('e-note')) {
    renderAssignEdit();
    if (EDITOR.current)
      syncQuestionHint(EDITOR.current.el.querySelector('.e-qhint'), field.value, EDITOR.current.kind_req);
  } else if (field.classList.contains('r-text')) renderReplyOutcome();
});
window.addEventListener(
  'keydown',
  (event) => {
    if (!MENTION.ta || event.target !== MENTION.ta || $('#mention-pop').hidden) return;
    if (imeKey(event)) {
      if (imeTail(event)) event.preventDefault();
      return;
    } // the Enter that ended a composition neither picks nor breaks the line (core.ts)
    const count = MENTION.items.length;
    if (event.key === 'ArrowDown' || event.key === 'ArrowUp') {
      if (!count) return;
      event.preventDefault();
      event.stopImmediatePropagation();
      MENTION.sel = (MENTION.sel + (event.key === 'ArrowDown' ? 1 : count - 1)) % count;
      mentionUpdate(MENTION.ta);
    } else if ((event.key === 'Enter' && !event.metaKey && !event.ctrlKey) || event.key === 'Tab') {
      if (!count) return;
      event.preventDefault();
      event.stopImmediatePropagation();
      mentionApply(MENTION.sel);
    } else if (event.key === 'Escape') {
      event.preventDefault();
      event.stopImmediatePropagation();
      mentionClose();
    }
  },
  true,
);
// When the cursor leaves the '@word' being typed (arrow key/click/leaving the field), the preview redraws and warns at
// that point (a mirror field's: its model's preview), and an open list follows the caret: it is drawn again for the
// '@word' the caret now ends, or closes when there is none.
['keyup', 'click', 'focusout'].forEach((eventType) =>
  document.addEventListener(eventType, (event) => {
    const field = event.target as HTMLTextAreaElement;
    if (!isMentionField(field)) return;
    if (eventType !== 'focusout' && MENTION.ta === field && !mentionCurrent()) mentionUpdate(field);
    setTimeout(() => mentionPreview(mentionModel(field)), 0);
  }),
);
document.addEventListener('focusout', (event) => {
  if (event.target === MENTION.ta)
    setTimeout(() => {
      if (document.activeElement !== MENTION.ta) mentionClose();
    }, 150);
});
$('#mention-pop').addEventListener('pointerdown', (event) => event.preventDefault());

export {
  ASSIGN_NEW,
  MENTION,
  assignOutcome,
  composeAsk,
  mentionApply,
  mentionClose,
  mentionEdited,
  mentionHints,
  mentionPlace,
  mentionPreview,
  mentionScan,
  nameShared,
  personLabel,
  renderAssignEdit,
  renderAssignNew,
};
