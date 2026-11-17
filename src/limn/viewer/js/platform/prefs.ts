// ------------------------------------------- Preferences (merged save): per-device pinPrefs, list-section state, theme
import { translateTemplate, translate } from './i18n.ts';
import { LIST_ORDER } from './tables.ts';
import { $, findAll } from './dom.ts';
import { roveSegment } from './segments.ts';
const LIGHT_SCHEME_QUERY = matchMedia('(prefers-color-scheme: light)');

function prefs() {
  try {
    const stored = JSON.parse(localStorage.getItem('pinPrefs') || '{}');
    return stored && typeof stored === 'object' ? stored : {};
  } catch (error) {
    return {};
  }
}
function savePrefs(patch: Record<string, unknown>) {
  try {
    localStorage.setItem('pinPrefs', JSON.stringify(Object.assign(prefs(), patch)));
  } catch (error) {}
}
// Applies the saved panel width, and drops the keys of the [줄바꿈] toggles (wrap, diffWrap) a stored pinPrefs may
// still carry: the source and the diff always wrap. The saved page scale is read per document when its pages are built
// (savedScale).
(function () {
  const stored = prefs();
  if (stored.side) $('#right').style.width = stored.side + 'px';
  if ('wrap' in stored || 'diffWrap' in stored) {
    delete stored.wrap;
    delete stored.diffWrap;
    try {
      localStorage.setItem('pinPrefs', JSON.stringify(stored));
    } catch (error) {}
  }
})();
// List sections (docs/handbook/viewer.md §목록 구획): expanded/collapsed per section, remembered in pinPrefs.sec.
// Defaults: open pins and awaiting review expanded, done collapsed. SECTION_SEEN holds, per section, the ids known at
// the first load plus everything the section held while expanded - while collapsed, a listed id not in it is counted as
// 'new N' on the header.
const SECTION_OPEN_DEFAULT = { open: true, review: true, done: false };
function readSectionsExpanded(saved?: Record<string, unknown> | null) {
  const expanded: Record<string, boolean> = Object.assign({}, SECTION_OPEN_DEFAULT);
  if (saved && typeof saved === 'object')
    for (const section in SECTION_OPEN_DEFAULT)
      if (typeof saved[section] === 'boolean') expanded[section] = saved[section];
  return expanded;
}
function countNewInSection(seen: Set<number> | null, ids: number[]) {
  if (!seen) return 0;
  return ids.filter((id: number) => !seen.has(id)).length;
}
let SECTION_OPEN = readSectionsExpanded(prefs().sec);
const SECTION_SEEN = {
  open: null as Set<number> | null,
  review: null as Set<number> | null,
  done: null as Set<number> | null,
};
// The pin list's order (docs/handbook/viewer.md §목록 순서): one choice for this browser across documents, remembered
// in pinPrefs.order. Returns the saved value when it names an order, else the default: newest first.
function listOrderOf(saved: unknown): string {
  return Object.values(LIST_ORDER).includes(saved as any) ? (saved as string) : LIST_ORDER.NEW;
}
let ORDER = listOrderOf(prefs().order);

const THEMES = ['system', 'light', 'dark'],
  THEME_NAME = { system: '시스템', light: '밝게', dark: '어둡게' };
// Applies the saved theme (system, light or dark; light by default): the page's data-theme and [더보기]'s theme
// segments - the saved one checked, and under 시스템 what the system gives now ('지금 밝게'). The segments are the one
// theme control on every layout.
function applyTheme() {
  let theme = prefs().theme || 'light';
  if (!THEMES.includes(theme)) theme = 'light';
  const shownTheme =
    theme === 'system' ? (LIGHT_SCHEME_QUERY.matches ? 'light' : 'dark') : theme === 'light' ? 'light' : 'dark';
  document.documentElement.setAttribute('data-theme', shownTheme);
  for (const radio of findAll(document, '#m-theme [role=radio]', HTMLElement)) {
    const on = radio.dataset.theme === theme;
    radio.setAttribute('aria-checked', String(on));
    radio.classList.toggle('on', on);
  }
  roveSegment($('#m-theme')); // the group's one Tab stop is the word now chosen (platform/segments.ts)
  const now = $('#m-theme-now');
  if (now) {
    now.hidden = theme !== 'system';
    now.textContent = translateTemplate('지금 {name}', { name: translate(THEME_NAME[shownTheme]) });
  }
}
LIGHT_SCHEME_QUERY.addEventListener('change', applyTheme);
// [더보기]'s theme segment: saves `theme` (one of THEMES) and applies it at once - the change is its own preview,
// another segment its undo.
function setTheme(theme: string | undefined) {
  if (theme === undefined || !THEMES.includes(theme)) return;
  savePrefs({ theme: theme });
  applyTheme();
}

// Sets ORDER, which this module declares, for another module that changes it (ADR-0042 D1); answers the value.
function setOrder<Value extends typeof ORDER>(value: Value): Value {
  ORDER = value;
  return value;
}
export {
  ORDER,
  SECTION_OPEN,
  SECTION_OPEN_DEFAULT,
  SECTION_SEEN,
  applyTheme,
  listOrderOf,
  prefs,
  savePrefs,
  countNewInSection,
  setOrder,
  setTheme,
  LIGHT_SCHEME_QUERY,
};
