// -------------------------------------- Markup: html``, lucideIcon() and setHtml(), the one way the viewer writes HTML
// docs/handbook/viewer.md §마크업 만들기. A value put into html`` is text unless it is Html the viewer made itself, so
// a note, a name or a PDF heading never becomes markup because one esc() was forgotten. Html is made only here (html``
// and lucideIcon()), and setHtml() is the one sink; src/limn/viewer/tests/test_viewer_markup.py holds every part to
// both.
import { ICONS, esc } from '../app/state.ts';

// Markup the viewer built: html`` escaped every value in it, or lucideIcon() drew it from the bundled icon table.
// toString() gives the markup text (for tests and debugging); a string made from it is no Html, so setHtml() refuses
// it.
class Html {
  declare text: string;
  constructor(text: string) {
    this.text = text;
  }
  toString() {
    return this.text;
  }
}

// Tag for a template of markup. Returns Html whose literal parts are kept and whose values are escaped: an Html goes in
// as markup, an array as its items one after another (each by these rules), null and undefined as nothing, and
// anything else as escaped text (esc()), so false reads "false" (an aria-pressed value), not nothing. Write a
// condition as c?x:''. Values must sit in element content or a quoted attribute; esc() does not make an unquoted
// attribute or a URL attribute safe. Called as a function rather than a tag, it throws a TypeError.
function html(parts: TemplateStringsArray, ...values: unknown[]): Html {
  if (!Array.isArray(parts) || !Array.isArray(parts.raw)) throw new TypeError('html is a template tag: html`...`');
  let out = parts[0];
  for (let i = 0; i < values.length; i++) out += htmlValue(values[i]) + parts[i + 1];
  return new Html(out);
}

// The markup one html`` value stands for (see html()).
function htmlValue(value) {
  if (value instanceof Html) return value.text;
  if (Array.isArray(value)) return value.map(htmlValue).join('');
  if (value == null) return '';
  return esc(value);
}

// The Lucide icon `name` as an inline <svg> (same shape as the server's icon_svg(); CSS sets its size through .ic), or
// empty Html when the bundled table has no such icon. `name` comes from this code, never from user text.
function lucideIcon(name) {
  const shapes = ICONS[name];
  return new Html(
    shapes
      ? '<svg class="ic ic-' +
          name +
          '" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true" focusable="false">' +
          shapes +
          '</svg>'
      : '',
  );
}

// Replaces an element's children with markup. Throws a TypeError for anything but Html, so a string built by hand
// cannot reach the page through here. An empty element of the markup with data-cp (a code point in hex:
// markHiddenHtml's box) then gets that character as its text through the DOM, which keeps what the HTML parser would
// drop or change (a NUL, a CR).
function setHtml(element, markup) {
  if (!(markup instanceof Html)) throw new TypeError('setHtml takes Html from html`` or ic()');
  element.innerHTML = markup.text;
  if (!markup.text.includes(' data-cp="')) return; // most markup has no box: no query
  for (const box of element.querySelectorAll('[data-cp]')) {
    const codePoint = parseInt(box.getAttribute('data-cp') || '', 16);
    box.removeAttribute('data-cp');
    if (codePoint >= 0 && codePoint <= 0x10ffff && !(codePoint >= 0xd800 && codePoint <= 0xdfff))
      box.textContent = String.fromCodePoint(codePoint);
  }
}
export { Html, html, lucideIcon, setHtml };
