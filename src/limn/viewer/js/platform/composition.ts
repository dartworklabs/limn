// ------------------------------------------------ Input method composition
// Whether an input method's composition is open (imeOpen): the element it is open in, kept by three listeners.
// The element an input method's composition is open in (compositionstart, not ended since), else null. A composition is
// over once its element ends it, loses the focus (blur), leaves the document - a field drawn away with no
// compositionend (a switch of documents, a rebuild) - or a new one starts elsewhere; imeOpen() reads the last two at
// the moment it is asked.
let COMPOSITION_ELEMENT: Element | null = null;
addEventListener(
  'compositionstart',
  (event) => {
    COMPOSITION_ELEMENT = event.target instanceof Element ? event.target : null;
  },
  true,
);
addEventListener(
  'compositionend',
  (event) => {
    if (event.target === COMPOSITION_ELEMENT) COMPOSITION_ELEMENT = null;
  },
  true,
);
addEventListener(
  'focusout',
  (event) => {
    if (event.target === COMPOSITION_ELEMENT) COMPOSITION_ELEMENT = null;
  },
  true,
);
function imeOpen() {
  const composing = COMPOSITION_ELEMENT,
    focused = document.activeElement;
  if (composing && (!composing.isConnected || !(focused === composing || (focused && composing.contains(focused)))))
    COMPOSITION_ELEMENT = null;
  return !!COMPOSITION_ELEMENT;
}

export { imeOpen };
