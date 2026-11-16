// ------------------------------------------------ People
// Who a login is (a name, an agent or a human) and whether it is the viewer themself, read from the page's shared
// state.
import { LOCAL_LOGIN, ROLE } from './rules-tables.ts';
import { translate } from '../platform/i18n.ts';
import { PEOPLE, META } from './state.ts';
function who(person) {
  if (person && person.login === LOCAL_LOGIN) return translate(person.name || '로컬/에이전트');
  return (person && (person.name || person.login)) || '';
} // the stored local name is Korean ('로컬/에이전트'); shown in the UI language
// A person = a photo or an initial circle (primary color); local/agent = a faded circle with a robot icon -
// distinguishes people from agents at a glance. The initial is in a box of its own (.av-l): trimmed to its cap height,
// so the circle centres the letter and not its line box.
function isAgent(person) {
  return !!person && (person.login === LOCAL_LOGIN || String(person.login).startsWith('agent:'));
}
// Turns '@name' (only resolved mentions) and '#number' (an existing pin) in text into tokens (docs/handbook/viewer.md
// §@태그). Names and numbers are found in the text as written and the result is built with html``, so the text between
// and inside the tokens stays text - what a person wrote never leaks as HTML. Names are matched with the same
// candidates as the server's resolve_mentions() (full name/login/the part of the login before @/the first word of the
// name), longest first, case-insensitive. Skipped when '@' follows a word (mentionAfterWord - an email address); a name
// ending in an ASCII letter followed by an ASCII letter (@Alicex) is a different word. An unresolved '@word' stays
// plain text - it must never look like it called someone.
function peopleName(login) {
  const known = PEOPLE.find((person) => person.login === login);
  return known ? known.name : login;
}
function meLogin() {
  const me = typeof META !== 'undefined' && META && META.me;
  return me && me.login && me.login !== LOCAL_LOGIN ? me.login : null;
}
function isHuman() {
  const me = typeof META !== 'undefined' && META && META.me;
  return !!(
    me &&
    me.login &&
    me.login !== LOCAL_LOGIN &&
    !String(me.login).startsWith('agent:') &&
    me.role !== ROLE.AGENT
  );
}
// The reviewer shown on an awaiting-review card: the author is suggested (anyone can confirm - a trust model). If I'm
// the author, '내 확인 차례'.
function isMe(person) {
  const me = META && META.me;
  return !!(person && me && me.login && me.login !== LOCAL_LOGIN && person.login === me.login);
}

export { who, isAgent, peopleName, meLogin, isHuman, isMe };
