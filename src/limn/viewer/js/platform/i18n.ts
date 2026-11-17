// ------------------------------------------------ UI language (Korean source, English table)
// UI language (window.LIMN_LANG from the head script). Korean strings in this file are the source; in English mode
// translate()/translateMessage() look them up in I18N_EN (src/limn/viewer/ui_en.json) and a MutationObserver translates
// text nodes and UI attributes as they are rendered. Strings missing from the table stay Korean.
import { UI_LANG } from './tables.ts';
import { $ } from './dom.ts';
import { roveSegment } from './segments.ts';
const LANG = window.LIMN_LANG === UI_LANG.EN ? UI_LANG.EN : UI_LANG.KO,
  I18N_EN = __UI_EN_JSON__,
  I18N_ATTRS = ['data-tip', 'aria-label', 'title', 'placeholder'];
function translate(text: string) {
  if (LANG !== UI_LANG.EN || typeof text !== 'string') return text;
  const trimmed = text.trim();
  if (!trimmed || !Object.prototype.hasOwnProperty.call(I18N_EN, trimmed) || typeof I18N_EN[trimmed] !== 'string')
    return text;
  return text.replace(trimmed, I18N_EN[trimmed]);
}
// Composed UI strings: translateTemplate('{n}쪽',{n:3}). The Korean key is the template and the Korean output; in
// English the table value is the template - a string, or plural forms {"one":...,"other":...} picked by values.n. {x}
// placeholders are filled from `values` (inserted as given - escape them first if the result goes into HTML).
function translateTemplate(key: string, values: Record<string, unknown>) {
  let pattern = key;
  if (LANG === UI_LANG.EN && Object.prototype.hasOwnProperty.call(I18N_EN, key)) {
    const entry = I18N_EN[key];
    pattern =
      typeof entry === 'string'
        ? entry
        : (entry && (Number(values && values.n) === 1 && entry.one ? entry.one : entry.other)) || key;
  }
  return pattern.replace(/\{(\w+)\}/g, (placeholder: string, field: string) =>
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
function warnText(text: string | null | undefined) {
  text = text == null ? '' : String(text);
  if (LANG !== UI_LANG.EN || !text) return text;
  for (const template of PICK_WARNS) {
    const names: string[] = [],
      lit = template.split(/\{(\w+)\}/).filter((part, index) => index % 2 === 0 || !names.push(part));
    const pattern = new RegExp(
      lit.map((literal) => literal.replace(/[.*+?^$()|[\]\\{}]/g, '\\$&')).join('(\\d+)'),
      'g',
    );
    text = text.replace(pattern, (...match: (string | number)[]) =>
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
function i18nText(node: Node) {
  const parent = node.parentNode;
  if (!parent || /^(TEXTAREA|SCRIPT|STYLE)$/.test(parent.nodeName) || i18nUser(parent)) return;
  const english = translateMessage(node.nodeValue);
  if (english !== node.nodeValue) node.nodeValue = english;
}
// Translates root and everything under it in English mode, skipping whole user-text subtrees.
function i18nTree(root: Node) {
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
  roveSegment($('#m-lang')); // the group's one Tab stop is the language now chosen (platform/segments.ts)
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
function switchLang(lang: string | undefined) {
  if ((lang !== UI_LANG.KO && lang !== UI_LANG.EN) || lang === LANG) return;
  try {
    localStorage.setItem('limnLang', lang);
  } catch (error) {}
  const address = new URL(location.href);
  address.searchParams.delete('lang');
  if (address.href === location.href) location.reload();
  else location.replace(address.href);
}
const TIP_TEXT: Record<string, string> = {
  stale:
    '핀을 찍은 첫 문장이 바뀌거나 지워져 위치를 되찾지 못했습니다. 이미 고쳐졌을 수 있으니 확인한 뒤 완료하거나 [수정] → 위치 다시 잡기를 하세요',
  ellost:
    '그림을 다시 그린 뒤 지도에서 이 요소를 찾지 못했습니다(요소 id가 바뀌었거나 지워짐). 표시는 핀을 찍은 때 자리에 그립니다. 이미 고쳐졌을 수 있으니 확인한 뒤 완료하거나 [수정] → 위치 다시 잡기를 하세요',
  n: "누르면 문서에서 이 핀 자리로 갑니다. 에이전트에게는 '#2 처리해줘'처럼 번호로 부르세요. 번호는 다시 쓰이지 않습니다",
  loc: '핀이 가리키는 원문 줄. 클릭하면 복사',
  view: '문서에서 이 핀 자리로 가서 깜빡입니다',
  edit: '메모와 범위를 고칩니다. 번호는 그대로입니다',
  close: "처리됨으로 표시해 목록과 pins.md에서 뺍니다. 아래 '닫힌 핀'에서 되돌릴 수 있습니다",
  drop: '핀을 휴지통으로 보냅니다. 카드 자리에 남는 [되돌리기]나 휴지통에서 같은 번호 그대로 되살릴 수 있습니다(30일 보관)',
  dropVerdict:
    '이 판정 핀을 휴지통으로 보냅니다(판정을 거둡니다). 같은 대상에 앞선 판정이 있으면 그 판정이 다시 지금 판정이 됩니다. 카드 자리에 남는 [되돌리기]나 휴지통에서 같은 번호 그대로 되살릴 수 있습니다(30일 보관)',
  repick: '번호와 메모는 그대로 두고 PDF에서 새 위치를 드래그해 바꿉니다 (Esc 취소)',
  esave: '수정한 내용을 저장합니다 (⌘ Enter / Ctrl+Enter)',
  ecancel: '수정을 버립니다 (Esc)',
  restore: '삭제한 핀을 같은 번호로 되살려 열린 핀에 올립니다',
  purge:
    '휴지통에서 영구 삭제합니다(소유자만). 그 자리에 6초 동안 남는 [되돌리기]로 취소할 수 있고, 그 줄이 사라지면 지웁니다',
  synctex: 'PDF 좌표(SyncTeX)로 찾은 위치입니다.',
  text: '드래그한 글자를 원문에서 직접 찾아 정한 위치입니다. 표나 기호표처럼 좌표로 찾기 어려운 곳에 쓰는 방법입니다.',
  map: '그림 지도에서 드래그와 가장 많이 겹치는 요소를 골랐습니다.',
  raw: '넓히기 전에 드래그 영역이 직접 가리킨 줄만 잡습니다',
  mdraw: '넓히기 전에 끌어 고르거나 누른 줄만 잡습니다',
  block: '고른 자리를 감싸는 블록 전체입니다(문단·목록 항목·표·코드 블록·인용·HTML 블록·머리 정보·수식)',
  blocks: '고른 줄이 걸친 블록들 전체입니다',
  section: '이 제목부터 같거나 높은 수준의 다음 제목 앞까지입니다',
  para: '드래그한 자리를 감싸는 문단 전체입니다(앞뒤 % 주석 줄은 뺍니다)',
  txpara: '고른 줄을 감싸는, 빈 줄 사이의 문단 전체입니다',
  txparas: '고른 줄이 걸친 문단들 전체입니다',
  indent:
    '고른 줄이 머리인 들여쓰기 블록, 아니면 고른 줄을 감싼 들여쓰기 블록입니다(머리 줄부터, 닫는 괄호나 end·fi·done·esac 만 있는 줄까지)',
  env: '감싸는 \\begin{…}…\\end{…} 블록 전체입니다. (바깥)은 한 단계 더 바깥 블록입니다',
  el: '이 요소를 그린 코드 줄입니다. 대기 상자가 그림의 이 요소에 맞춰집니다',
  fig: '그림 전체를 그린 코드 줄입니다',
  elregion: '이 요소를 그린 코드 줄을 찾지 못했습니다 — 쪽·영역과 요소로 핀을 남깁니다',
  figregion: '그림 지도를 읽지 못해 쪽·영역과 영역 글자로 핀을 남깁니다',
  shape: '이 자리는 지금 핀과 모양(줄/영역)이 달라 옮길 수 없습니다 — 다른 자리를 고르거나 새 핀을 남기세요',
  cur: '지금 핀이 가리키는 범위 그대로입니다',
  undo: '방금 한 저장·완료·삭제를 되돌립니다',
  question: '고칠 곳이 아니라 묻는 핀입니다. 답은 아래 스레드에 달리고, 원고는 질문이 수정을 뜻할 때만 고칩니다',
  review:
    '에이전트가 닫은 핀입니다. 사람이 결과를 보고 [확인]하면 완료로 가고, [답글]에 틀린 점을 쓰면 다시 열려 에이전트가 고칩니다',
  confirm:
    '결과를 확인했다고 기록하고 완료로 옮깁니다. 작성자에게 권하지만 누구나 누를 수 있고, 누른 사람이 기록됩니다',
  change:
    '변경사항 탭을 열어 이 핀을 고친 커밋(닫을 때 남긴 참조, 없으면 이 줄을 바꾼 최근 커밋)의 diff 에서 핀 자리를 강조합니다',
  reply:
    '이 핀에 답글을 답니다. 닫힌 핀이면 보내기 전에 칸 아래 한 줄이 결과(다시 열림·알림·그대로)를 알려 줍니다 (⌘ Enter / Ctrl+Enter 보내기)',
  nochange: '변경 없음',
  buildanyway: '그래도 빌드',
  buildanywaytip:
    '남겨 둔 LaTeX 부산물을 지우고 처음부터 다시 빌드합니다. 빌드가 비교하지 않는 것(셸 탈출로 도는 프로그램이 읽는 파일 등)을 바꿨을 때 씁니다',
  reloadtip:
    '이 탭을 새로 읽어 서버의 새 Limn 화면을 씁니다. 작성 패널의 글과 읽던 자리는 남고, 쓰던 답글·수정이 있으면 먼저 알립니다',
};
// docs/handbook/api.md §겹친 핀과 덧붙이기: one representative among the rel entries - if there's an inside (the outer
// pin with the smallest range), otherwise the smallest-id partial. Must follow the same rule as the server's
// rel_badge() (pins.md) so card tags and pins.md rows never disagree - since a rel entry is only {id,rel}, the range is
// looked up by id from PINS (all currently loaded open pins). The badge wording is phrased to be self-explanatory:
// '#20과 같은 범위' > '#20 범위 안' > '#20과 일부 겹침'. Same-range is told by this pin's own lo/hi.
function josa(number: string | number, afterConsonant: string, afterVowel: string) {
  const lastDigit = String(number).slice(-1);
  return lastDigit === '0' || '13678'.includes(lastDigit) ? afterConsonant : afterVowel;
}
// '로' or '으로' after a number read in Korean: '으로' after a final consonant other than ㄹ (영/십·백·천, 삼, 육),
// else '로'. The particle after a name: afterConsonant after a final consonant, afterVowel after a vowel. A Hangul name
// by its last syllable's final; a Latin one by how its end is read - a vowel letter (and a silent e) reads as a vowel,
// a consonant as one ('Bob이', 'Alice가'), a lone capital as its letter's Korean name ('Agent B가', 'Team L이'); a
// digit as its Korean reading (josa). Pure.
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

export {
  LANG,
  errText,
  i18nStart,
  switchLang,
  translateTemplate,
  translate,
  translateMessage,
  warnText,
  TIP_TEXT,
  josa,
  josaName,
};
