// ------------------------------------------------ UI language (Korean source, English table)
// UI language (window.LIMN_LANG from the head script). Korean strings in this file are the source; in English mode
// translate()/translateMessage() look them up in I18N_EN (src/limn/viewer/ui_en.json) and a MutationObserver translates
// text nodes and UI attributes as they are rendered. Strings missing from the table stay Korean.
import { $, UI_LANG } from './core.ts';
import { roveSegment } from './events.ts';
const LANG = window.LIMN_LANG === UI_LANG.EN ? UI_LANG.EN : UI_LANG.KO,
  I18N_EN = __UI_EN_JSON__,
  I18N_ATTRS = ['data-tip', 'aria-label', 'title', 'placeholder'];
function translate(text) {
  if (LANG !== UI_LANG.EN || typeof text !== 'string') return text;
  const trimmed = text.trim();
  if (!trimmed || !Object.prototype.hasOwnProperty.call(I18N_EN, trimmed) || typeof I18N_EN[trimmed] !== 'string')
    return text;
  return text.replace(trimmed, I18N_EN[trimmed]);
}
// Composed UI strings: translateTemplate('{n}쪽',{n:3}). The Korean key is the template and the Korean output; in
// English the table value is the template - a string, or plural forms {"one":...,"other":...} picked by values.n. {x}
// placeholders are filled from `values` (inserted as given - escape them first if the result goes into HTML).
function translateTemplate(key, values) {
  let pattern = key;
  if (LANG === UI_LANG.EN && Object.prototype.hasOwnProperty.call(I18N_EN, key)) {
    const entry = I18N_EN[key];
    pattern =
      typeof entry === 'string'
        ? entry
        : (entry && (Number(values && values.n) === 1 && entry.one ? entry.one : entry.other)) || key;
  }
  return pattern.replace(/\{(\w+)\}/g, (placeholder, field) =>
    values && values[field] != null ? String(values[field]) : placeholder,
  );
}
function translateMessage(message) {
  if (LANG !== UI_LANG.EN || typeof message !== 'string') return message;
  const english = translate(message);
  if (english !== message) return english;
  for (const separator of [' — ', ' · ']) {
    if (message.indexOf(separator) > 0) return message.split(separator).map(translate).join(separator);
  }
  return message;
}
// An API error body {error, reason} as the UI shows it (docs/handbook/viewer.md §뷰어 규칙을 바꿀 때). Korean shows the
// server's `error` text as is - it is the agent contract (api.md §오류 응답). English looks up the stable reason code
// ('reason:<code>' in the table) and falls back to the server text through the table. '' when there is no body.
function errText(body) {
  if (!body) return '';
  const serverText = body.error == null ? '' : String(body.error);
  if (LANG === UI_LANG.EN && typeof body.reason === 'string') {
    const english = I18N_EN['reason:' + body.reason];
    if (typeof english === 'string') return english;
  }
  return translateMessage(serverText);
}
// The pick's `warn` (a Korean UI hint, not an error body) is up to three sentences the server joins with a space, some
// with numbers. Each Korean template here matches one server sentence ({x} = the number); English fills the table's
// template through translateTemplate(). Korean shows the server text as is; a sentence no template matches stays as it
// is.
const PICK_WARNS = [
  '이 영역은 원문 대조가 약합니다({pct}%). 줄 범위를 눈으로 확인하세요.',
  '두 경로가 다른 곳을 가리킵니다(L{a} / L{b}). 확인이 필요합니다.',
  '화면의 PDF 가 지금 원고보다 낡았습니다 — [PDF 재빌드] 뒤에 다시 고르세요.',
  '빌드 중이라 결과가 흔들릴 수 있습니다.',
  '이 영역에는 글자가 없습니다(그림·스캔본). 메모에 무엇을 가리키는지 적어 주세요.',
  'PDF 가 바뀌어 쪽을 다시 그리는 중입니다 — 끝나면 다시 고르세요.',
  '이 그림의 요소 지도를 읽지 못해 영역으로 찍습니다 — 그림 저장소가 지도를 다시 쓰면 다시 고르세요.',
  '이 요소를 그린 코드 줄을 찾지 못해 영역으로 찍습니다 — 스크립트를 고친 뒤라면 그림을 다시 렌더하고 다시 고르세요.',
];
function warnText(text) {
  text = text == null ? '' : String(text);
  if (LANG !== UI_LANG.EN || !text) return text;
  for (const template of PICK_WARNS) {
    const names: string[] = [],
      lit = template.split(/\{(\w+)\}/).filter((part, index) => index % 2 === 0 || !names.push(part));
    const pattern = new RegExp(
      lit.map((literal) => literal.replace(/[.*+?^$()|[\]\\{}]/g, '\\$&')).join('(\\d+)'),
      'g',
    );
    text = text.replace(pattern, (...match) =>
      translateTemplate(template, Object.fromEntries(names.map((name, index) => [name, match[index + 1]]))),
    );
  }
  return text;
}
// What people wrote is never translated (docs/handbook/viewer.md §뷰어 규칙을 바꿀 때): document names, notes, authors
// and thread posts are drawn under translate="no", and the translator leaves that subtree - its text and its UI
// attributes - alone, so a document named '그림' or a note that reads '완료' stays as written. The UI words drawn
// inside it are translate()'d by the code that draws them. Asked of an element (an SVG one has no translate and counts
// as translatable).
function i18nUser(element) {
  return !!element && element.translate === false;
}
// Translates an element's UI attributes in place, unless it is user text.
function translateAttributes(element) {
  if (i18nUser(element)) return;
  for (const attribute of I18N_ATTRS) {
    const value = element.getAttribute(attribute);
    if (value) {
      const english = translateMessage(value);
      if (english !== value) element.setAttribute(attribute, english);
    }
  }
}
// Translates a text node in place, unless it sits in a text field, a script or style, or user text.
function i18nText(node) {
  const parent = node.parentNode;
  if (!parent || /^(TEXTAREA|SCRIPT|STYLE)$/.test(parent.nodeName) || i18nUser(parent)) return;
  const english = translateMessage(node.nodeValue);
  if (english !== node.nodeValue) node.nodeValue = english;
}
// Translates root and everything under it in English mode, skipping whole user-text subtrees.
function i18nTree(root) {
  if (LANG !== UI_LANG.EN || !root) return;
  if (root.nodeType === 3) return i18nText(root);
  if (root.nodeType !== 1 || i18nUser(root)) return;
  translateAttributes(root);
  const walker = document.createTreeWalker(root, NodeFilter.SHOW_ELEMENT | NodeFilter.SHOW_TEXT, {
    acceptNode: (node) => (node.nodeType === 1 && i18nUser(node) ? NodeFilter.FILTER_REJECT : NodeFilter.FILTER_ACCEPT),
  });
  let node;
  while ((node = walker.nextNode())) {
    if (node.nodeType === 3) i18nText(node);
    else translateAttributes(node);
  }
}
// Checks the current language in [더보기]'s language segment, then in English translates the page once and everything
// drawn or changed after it (text nodes and UI attributes), leaving user text alone (i18nUser).
function i18nStart() {
  for (const radio of document.querySelectorAll('#m-lang [role=radio]') as NodeListOf<HTMLElement>) {
    const on = radio.dataset.lang === LANG;
    radio.setAttribute('aria-checked', String(on));
    radio.classList.toggle('on', on);
  }
  roveSegment($('#m-lang')); // the group's one Tab stop is the language now chosen (events.ts)
  if (LANG !== UI_LANG.EN) return;
  i18nTree(document.body);
  new MutationObserver((mutations) => {
    for (const mutation of mutations) {
      if (mutation.type === 'childList') mutation.addedNodes.forEach(i18nTree);
      else if (mutation.type === 'characterData') i18nText(mutation.target);
      else if (mutation.type === 'attributes' && mutation.target.nodeType === 1 && !i18nUser(mutation.target)) {
        const element = mutation.target as Element,
          name = mutation.attributeName || '',
          value = element.getAttribute(name);
        if (value) {
          const english = translateMessage(value);
          if (english !== value) element.setAttribute(name, english);
        }
      }
    }
  }).observe(document.body, {
    childList: true,
    subtree: true,
    characterData: true,
    attributes: true,
    attributeFilter: I18N_ATTRS,
  });
}
// [더보기]'s language segment: saves lang (ko or en) as this device's choice and reloads in it - the tab's draft is
// kept (sessionStorage). The language on screen does nothing; nothing asks first. A ?lang= would beat the saved choice,
// so the reload drops it and keeps the hash (document and place). Without one the address is unchanged, and replacing
// an address that has a hash with itself only jumps to that hash inside the page, loading nothing - so that case
// reloads.
function switchLang(lang) {
  if ((lang !== UI_LANG.KO && lang !== UI_LANG.EN) || lang === LANG) return;
  try {
    localStorage.setItem('limnLang', lang);
  } catch (error) {}
  const address = new URL(location.href);
  address.searchParams.delete('lang');
  if (address.href === location.href) location.reload();
  else location.replace(address.href);
}
export { LANG, errText, i18nStart, switchLang, translateTemplate, translate, translateMessage, warnText };
