// ------------------------------------------------ A person's avatar
import { html, lucideIcon } from '../platform/markup.ts';
import { isAgent, who } from './state-people.ts';
// The avatar URLs that have failed: never requested again, so console errors do not pile up on every redraw.
const FAILED_AVATARS = new Set<string | null>();
function avatar(person: Person | null | undefined) {
  if (!person || !(person.name || person.login)) return html``;
  if (isAgent(person)) return html`<span class="av i agent" aria-hidden="true">${lucideIcon('bot')}</span>`;
  const initial = (who(person).trim()[0] || '?').toUpperCase();
  return person.pic && !FAILED_AVATARS.has(person.pic)
    ? html`<img class="av" src="${person.pic}" alt="" referrerpolicy="no-referrer" data-ini="${initial}">`
    : html`<span class="av i" aria-hidden="true"><span class="av-l">${initial}</span></span>`;
}
export { FAILED_AVATARS, avatar };
