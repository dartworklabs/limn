// ------------------------------------------------ What the composer asks the features above it
// The composer makes a pin from a selection; the verdict row it shows and the verdict a save may carry, the pin list a
// save is followed by, the queue a save goes into while cut off, and the edit card and reply that share its text tools
// are the features above (verdict, pins, offline). The composer may not import them (docs/handbook/viewer.md §모듈
// 경계), so each need is a seam here: an interface for what the composer asks, a registration function and an
// accessor. js/main.ts registers every seam once, at its top level before boot() runs (no code that runs while the
// script loads reaches one), and the composer calls the registered function at the point, with the arguments and in
// the order it called the feature function directly. An accessor called before its registration throws, naming the
// seam.

// The verdict's part of the composer (verdict/flow-line.ts): the row of verdict words under the note, and what a save
// that carries a verdict does differently.
interface ComposerVerdict {
  /** Draws the composer's verdict row for the selection and the kind as they are now. */
  drawRow(): void;
  /** The pin body of a verdict saved on a figure document (the figure's, whatever element is picked), or null. */
  figureBody(selection: ComposerSelection): Record<string, unknown> | null;
  /** The figure a selection on a figure document is about, or null. */
  figureRoot(selection: ComposerSelection | null): string | null;
  /** A figure's short name while its page still shows it. */
  figureShort(page: number, root: string): string;
  /** The [되돌리기] of a saved verdict pin. */
  undo(id: number): () => Promise<boolean>;
  /** Says on the composer's failed-save banner that the verdict it was for is not asked for any more. */
  dropped(): void;
}
let COMPOSER_VERDICT: ComposerVerdict | null = null;
// Registers the verdict's part of the composer; js/main.ts calls it once.
function setComposerVerdict(verdict: ComposerVerdict) {
  COMPOSER_VERDICT = verdict;
}
// The registered verdict part; throws before setComposerVerdict() has run.
function composerVerdict(): ComposerVerdict {
  if (!COMPOSER_VERDICT) throw new Error('setComposerVerdict() has not run: the composer has no verdict row');
  return COMPOSER_VERDICT;
}

// The pin list a save changes (pins/flow-list.ts, pins/flow-actions.ts): read again after a save, an append or a move,
// and a saved pin taken back by its [되돌리기].
interface ComposerPins {
  /** Reads the pin lists again and draws them; whether this read's answer was the one drawn. */
  load(): Promise<boolean>;
  /** Takes a pin this person just saved back (undoSave), with what [다시 시도] runs. */
  drop(id: number | null, undoSave: boolean, again?: () => unknown): Promise<boolean>;
}
let COMPOSER_PINS: ComposerPins | null = null;
// Registers the pin list a save changes; js/main.ts calls it once.
function setComposerPins(pins: ComposerPins) {
  COMPOSER_PINS = pins;
}
// The registered pin list; throws before setComposerPins() has run.
function composerPins(): ComposerPins {
  if (!COMPOSER_PINS) throw new Error('setComposerPins() has not run: the composer has no pin list to save into');
  return COMPOSER_PINS;
}

/** A drag on the pages, in PDF points, as /api/pick takes it. */
interface PickDrag {
  page: number;
  x0: number;
  y0: number;
  x1: number;
  y1: number;
  frac: number[];
  pdf_build?: string;
  doc?: string;
}

// The queue a pin is kept in while cut off (offline/flow.ts): a selection made without the server, a save kept for
// later, and the key a plain save goes with.
interface ComposerQueue {
  /** Opens the composer on a selection the server could not be reached for. */
  pick(drag: PickDrag): Promise<void>;
  /** Keeps a pin in the queue; whether it was kept. */
  save(
    selection: ComposerSelection,
    note: string,
    out: { kind: string | null; assignee: string | null },
    mentions: string[],
    tried?: { idem?: string; top: number },
  ): Promise<boolean>;
  /** Whether the server knows a write by its key, so a plain save goes with one. */
  keyed(): boolean;
  /** A new key for a write. */
  key(): string;
}
let COMPOSER_QUEUE: ComposerQueue | null = null;
// Registers the queue; js/main.ts calls it once.
function setComposerQueue(queue: ComposerQueue) {
  COMPOSER_QUEUE = queue;
}
// The registered queue; throws before setComposerQueue() has run.
function composerQueue(): ComposerQueue {
  if (!COMPOSER_QUEUE) throw new Error('setComposerQueue() has not run: the composer has no queue for a pin cut off');
  return COMPOSER_QUEUE;
}

// A pin's own fields that use the composer's text tools (pins/flow-edit.ts, pins/flow-reply.ts): the open edit card,
// whose excerpt, place and @-tags the composer's code changes, and the reply box's outcome line.
interface PinFields {
  /** Draws the open edit card again. */
  drawEdit(): void;
  /** Reads the open edit card's snippet again (with its range ladder when withLevels). */
  snipEdit(withLevels: boolean): Promise<void>;
  /** Draws the reply box's outcome line again. */
  drawReplyOutcome(): void;
}
let PIN_FIELDS: PinFields | null = null;
// Registers the edit card and the reply box; js/main.ts calls it once.
function setPinFields(fields: PinFields) {
  PIN_FIELDS = fields;
}
// The registered edit card and reply box; throws before setPinFields() has run.
function pinFields(): PinFields {
  if (!PIN_FIELDS) throw new Error('setPinFields() has not run: the composer has no edit card or reply to draw');
  return PIN_FIELDS;
}

export type { PickDrag };
export {
  composerPins,
  composerQueue,
  composerVerdict,
  pinFields,
  setComposerPins,
  setComposerQueue,
  setComposerVerdict,
  setPinFields,
};
