import { DOC } from '../app/state.ts';

let KEYED_PAGE = 0; // the page whose line the keys 1-5 act on (keyedPageFor), 0 for none

let READING_LINE_PAGE = 0; // the reading page with a line: its line floats and names its figure

// A page line's pending state is keyed by its document and page (pageLineSlot): a save held on one document's page must
// not hold, queue or end the same page number's line of another document.
/** @param [doc] - default: the document on screen */
function pageLineSlot(page: number, doc?: string | null) {
  return (doc === undefined ? DOC || '' : doc || '') + '\u0001' + page;
}
// the page lines whose verdict is being saved (pageLineSlot), with the word it saves
const SAVING_LINES: Map<string, string> = new Map();

// The lines whose save out was a digit key's (pageLineSlot): Enter on any control of that line then means the reason,
// one intent with the key (openReasonOnEnter). On the word the focus rests on it pressed that word: a second verdict,
// over the one being saved.
const KEY_SAVE_OUT: Set<string> = new Set();

// The page shown as reading and the one accepting verdict keys change together.
function setReadingLinePages(readingPage: number, keyedPage: number) {
  READING_LINE_PAGE = readingPage;
  KEYED_PAGE = keyedPage;
}

export { KEYED_PAGE, READING_LINE_PAGE, SAVING_LINES, KEY_SAVE_OUT, pageLineSlot, setReadingLinePages };
