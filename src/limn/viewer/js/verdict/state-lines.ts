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

// The press made on a line while its save was out, by line (pageLineSlot) - the last one: applied when that save is
// done (pressPageVerdict).
const NEXT_PRESS: Map<string, { key: string; how: string }> = new Map();

// A line whose word was just taken back by pressing it again (pageLineSlot): that word waits until then (a double press
// takes back one).
const TAKEN_BACK_HOLD: Map<string, { key: string; until: number }> = new Map();

// A page line's last failed save, by page: said on the line that was pressed (pageLineHtml) as well as on the status
// line, until the next press on that line or another document or build. The document and build it was for come with it.
const LINE_SAVE_ERROR: Map<number, { text: string; doc: string | null; build: string }> = new Map();

const CANCEL_HOLD: Map<string, number> = new Map(); // line (pageLineSlot) -> until when its [판정 취소] waits

// The lines whose take-back is out: Enter and Space on them do nothing until it answers (stopOffPageKey). What the
// focus rests on is what the line shows meanwhile, the verdict before it: Enter there would open a reason for it, or
// take that one back too. An answer that does not come must not leave the line deaf: past CANCEL_ANSWER_WAIT the keys
// are back and the status line says so; the late answer is still taken (its message, its [되돌리기]), but the focus has
// moved on by then and stays. The value says whose wait it is.
const CANCEL_OUT: Map<string, number> = new Map();

// The take-backs whose [되돌리기] the line offers too, by line (pageLineSlot): the pin and its status-line message -
// the offer lasts as long as that message (its window, or its action).
const LINE_UNDO_OFFERS: Map<string, { id: number; n: number }> = new Map();

export {
  CANCEL_HOLD,
  CANCEL_OUT,
  KEYED_PAGE,
  KEY_SAVE_OUT,
  LINE_SAVE_ERROR,
  LINE_UNDO_OFFERS,
  NEXT_PRESS,
  READING_LINE_PAGE,
  SAVING_LINES,
  TAKEN_BACK_HOLD,
  pageLineSlot,
  setReadingLinePages,
};
