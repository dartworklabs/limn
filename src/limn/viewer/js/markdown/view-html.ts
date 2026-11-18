/** Represent raw HTML with inert placeholders whose source ranges remain selectable. */
import type { MarkdownToken } from './flow-parse.ts';
import type { RenderContext } from './state.ts';
import { countedElement, mapLines, tokenLines, drawTextNow } from './view-elements.ts';
import { translateTemplate } from '../platform/i18n.ts';
import { setHtml, html, lucideIcon } from '../platform/markup.ts';
import { findClosest, findMaybe, findAll } from '../platform/dom.ts';
import { drawPinMarks, markChosenLines, shownChoice } from './view-marks.ts';
import { updateMarkdownStrip } from './view-outline.ts';

// A raw HTML block's placeholder: its lines (it takes a pin), their count and its first line as code, never the HTML
// itself.
function htmlPlaceholder(token: MarkdownToken, context: RenderContext): HTMLElement {
  const box = countedElement('div', context);
  mapLines(box, token, 'html', context);
  box.className = 'md-html';
  const lines = tokenLines(token, context),
    count = lines ? lines.hi - lines.lo + 1 : 0,
    first =
      String(token.content || '')
        .split('\n')
        .find((line) => line.trim()) || '';
  const label = countedElement('span', context);
  label.className = 'md-html-l';
  label.textContent = translateTemplate('HTML {lines}줄 · 그리지 않습니다', { lines: count });
  let head = '';
  let taken = 0;
  for (const character of first.trim()) {
    if (++taken > 120) break;
    head += character;
  } // 120 characters at most, never half of one
  const code = countedElement('code', context);
  drawTextNow(code, head, context);
  box.append(label, code);
  return box;
}
// Two or more raw HTML blocks in a row (a README's head of badges and pictures) are one placeholder, closed: a button
// naming the blocks and their lines (HTML 블록 N개 · M줄) that opens it (toggleHtmlRun), each block then its own
// placeholder that takes a pin. Only what is on screen carries lines (data-lo/hi): closed, the run stands for all its
// lines as one HTML block; open, each block for its own (holdHtmlLines keeps the other's in data-r-lo/hi). So the
// marks, the picks, the ladder and the reading line read whatever is shown and nothing hidden.
function htmlRunElement(count: number, first: number, last: number, context: RenderContext): HTMLElement {
  const run = countedElement('div', context);
  run.className = 'md-html-run';
  run.dataset.rLo = String(first);
  run.dataset.rHi = String(last);
  run.dataset.kind = 'html';
  holdHtmlLines(run, true);
  const button = countedElement('button', context);
  button.type = 'button';
  button.className = 'md-html-sum';
  button.dataset.act = 'md-html-run';
  button.setAttribute('aria-expanded', 'false');
  setHtml(
    button,
    html`${lucideIcon('chevron-right')}<span>${translateTemplate('HTML 블록 {n}개 · {lines}줄 · 그리지 않습니다', { n: count, lines: last - first + 1 })}</span>`,
  ); // the chevron turns down when open (CSS)
  const body = countedElement('div', context);
  body.className = 'md-html-body';
  body.hidden = true;
  run.append(button, body);
  return run;
}
// Shows (on) or hides (off) the element's lines: data-lo/hi from its kept data-r-lo/hi, or none.
function holdHtmlLines(element: HTMLElement, on: boolean) {
  if (!element.dataset.rLo) {
    element.dataset.rLo = element.dataset.lo || '';
    element.dataset.rHi = element.dataset.hi || '';
  }
  if (on) {
    element.dataset.lo = element.dataset.rLo;
    element.dataset.hi = element.dataset.rHi || '';
  } else {
    delete element.dataset.lo;
    delete element.dataset.hi;
  }
}
// Opens or closes the run of raw HTML blocks whose button is button (data-act md-html-run), then draws the marks, the
// chosen lines and the strip again over what is shown.
function toggleHtmlRun(button: HTMLElement) {
  const run = findClosest(button, '.md-html-run', HTMLElement),
    body = run && findMaybe(run, '.md-html-body', HTMLElement);
  if (!run || !body) return;
  const open = button.getAttribute('aria-expanded') !== 'true';
  holdHtmlLines(run, !open);
  findAll(body, '.md-html', HTMLElement).forEach((placeholder) => holdHtmlLines(placeholder, open));
  body.hidden = !open;
  button.setAttribute('aria-expanded', String(open));
  drawPinMarks();
  markChosenLines(shownChoice());
  updateMarkdownStrip();
}

export { htmlPlaceholder, htmlRunElement, holdHtmlLines, toggleHtmlRun };
