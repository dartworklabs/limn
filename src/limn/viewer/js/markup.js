// ------------------------------------------------ Markup: html``, ic() and setHtml(), the one way the viewer writes HTML
// docs/handbook/viewer.md §마크업 만들기. A value put into html`` is text unless it is Html the viewer made itself, so a
// note, a name or a PDF heading never becomes markup because one esc() was forgotten. Html is made only here (html``
// and ic()), and setHtml() is the one sink; src/limn/viewer/tests/test_viewer_markup.py holds every part to both.

// Markup the viewer built: html`` escaped every value in it, or ic() drew it from the bundled icon table. toString()
// gives the markup text (for tests and debugging); a string made from it is no Html, so setHtml() refuses it.
class Html{
  constructor(text){this.text=text;}
  toString(){return this.text;}
}

// Tag for a template of markup. Returns Html whose literal parts are kept and whose values are escaped: an Html goes in
// as markup, an array as its items one after another (each by these rules), null and undefined as nothing, and
// anything else as escaped text (esc()), so false reads "false" (an aria-pressed value), not nothing. Write a
// condition as c?x:''. Values must sit in element content or a quoted attribute; esc() does not make an unquoted
// attribute or a URL attribute safe. Called as a function rather than a tag, it throws a TypeError.
function html(parts,...values){
  if(!Array.isArray(parts)||!Array.isArray(parts.raw))throw new TypeError('html is a template tag: html`...`');
  let out=parts[0];
  for(let i=0;i<values.length;i++)out+=htmlValue(values[i])+parts[i+1];
  return new Html(out);
}

// The markup one html`` value stands for (see html()).
function htmlValue(v){
  if(v instanceof Html)return v.text;
  if(Array.isArray(v))return v.map(htmlValue).join('');
  if(v==null)return '';
  return esc(v);
}

// The Lucide icon n as an inline <svg> (same shape as the server's icon_svg(); CSS sets its size through .ic), or
// empty Html when the bundled table has no such icon. n is a name from this code, never user text.
function ic(n){const b=ICONS[n];
  return new Html(b?'<svg class="ic ic-'+n+'" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true" focusable="false">'+b+'</svg>':'');}

// Replaces el's children with markup. Throws a TypeError for anything but Html, so a string built by hand cannot
// reach the page through here.
function setHtml(el,markup){
  if(!(markup instanceof Html))throw new TypeError('setHtml takes Html from html`` or ic()');
  el.innerHTML=markup.text;
}
