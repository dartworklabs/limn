// ------------------------------------------------ Preferences (merged save): per-device pinPrefs, list-section state, theme
import { $, $$, LIST_ORDER, MQ } from './core.ts';
import { tl, tr } from './i18n.ts';
import { segRove } from './events.ts';
function prefs() {
  try {
    const stored = JSON.parse(localStorage.getItem('pinPrefs') || '{}');
    return stored && typeof stored === 'object' ? stored : {};
  } catch (error) {
    return {};
  }
}
function savePrefs(patch) {
  try {
    localStorage.setItem('pinPrefs', JSON.stringify(Object.assign(prefs(), patch)));
  } catch (error) {}
}
// The saved panel width, and the keys of the [줄바꿈] toggles an older release stored (wrap, diffWrap) dropped: the source and
// the diff always wrap now. The saved page scale is read per document when its pages are built (savedK).
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
// List sections (docs/handbook/viewer.md §목록 구획): expanded/collapsed per section, remembered in pinPrefs.sec. Defaults: open pins and
// awaiting review expanded, done collapsed. SEC_SEEN holds, per section, the ids known at the first load plus everything the section
// held while expanded - while collapsed, a listed id not in it is counted as 'new N' on the header.
const SEC_DEFAULT = { open: true, review: true, done: false };
function readSectionsExpanded(saved) {
  const expanded = Object.assign({}, SEC_DEFAULT);
  if (saved && typeof saved === 'object')
    for (const section in SEC_DEFAULT) if (typeof saved[section] === 'boolean') expanded[section] = saved[section];
  return expanded;
}
function secNewCount(seen, ids) {
  if (!seen) return 0;
  return ids.filter((id) => !seen.has(id)).length;
}
let SEC = readSectionsExpanded(prefs().sec);
const SEC_SEEN = {
  open: null as Set<number> | null,
  review: null as Set<number> | null,
  done: null as Set<number> | null,
};
// The pin list's order (docs/handbook/viewer.md §목록 순서): one choice for this browser across documents, remembered in
// pinPrefs.order. Returns the saved value when it names an order, else the default: newest first.
function listOrderOf(saved: unknown): string {
  return Object.values(LIST_ORDER).includes(saved as any) ? (saved as string) : LIST_ORDER.NEW;
}
let ORDER = listOrderOf(prefs().order);

const THEMES = ['system', 'light', 'dark'],
  THEME_NAME = { system: '시스템', light: '밝게', dark: '어둡게' };
// Applies the saved theme (system, light or dark; light by default): the page's data-theme and [더보기]'s theme segments - the
// saved one checked, and under 시스템 what the system gives now ('지금 밝게'). The segments are the one theme control on every
// layout: the desktop's cycle button went with its [⋯] (3b of the cross-resolution pass).
function applyTheme() {
  let theme = prefs().theme || 'light';
  if (!THEMES.includes(theme)) theme = 'light';
  const shownTheme = theme === 'system' ? (MQ.matches ? 'light' : 'dark') : theme === 'light' ? 'light' : 'dark';
  document.documentElement.setAttribute('data-theme', shownTheme);
  for (const radio of $$('#m-theme [role=radio]')) {
    const on = radio.dataset.theme === theme;
    radio.setAttribute('aria-checked', String(on));
    radio.classList.toggle('on', on);
  }
  segRove($('#m-theme')); // the group's one Tab stop is the word now chosen (events.js)
  const now = $('#m-theme-now');
  if (now) {
    now.hidden = theme !== 'system';
    now.textContent = tl('지금 {name}', { name: tr(THEME_NAME[shownTheme]) });
  }
}
MQ.addEventListener('change', applyTheme);
// [더보기]'s theme segment: saves theme t (one of THEMES) and applies it at once - the change is its own preview, another
// segment its undo.
function setTheme(theme) {
  if (!THEMES.includes(theme)) return;
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
  SEC,
  SEC_DEFAULT,
  SEC_SEEN,
  applyTheme,
  listOrderOf,
  prefs,
  savePrefs,
  secNewCount,
  setOrder,
  setTheme,
};
