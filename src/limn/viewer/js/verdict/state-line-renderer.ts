// Panel and reason changes redraw the affected line or update its reading position.
interface VerdictLineRenderer {
  /** Watch the chip on a newly created line so its controls update when the chip changes. */
  watchLineChips(line: HTMLElement): void;
  drawPageVerdicts(): void;
  fillPageLine(line: HTMLElement, page: number, list: Pin[] | undefined, verdicts: DocVerdicts): void;
  stickReadingLine(): void;
}
let VERDICT_LINE_RENDERER: VerdictLineRenderer | null = null;

/** Connect the line renderer before the first draw or input event. */
function setVerdictLineRenderer(renderer: VerdictLineRenderer) {
  VERDICT_LINE_RENDERER = renderer;
}

/** Return the renderer registered by main, or fail immediately if it has not been wired. */
function verdictLineRenderer(): VerdictLineRenderer {
  if (!VERDICT_LINE_RENDERER) throw new Error('setVerdictLineRenderer() has not run');
  return VERDICT_LINE_RENDERER;
}

let STICK_FRAME = 0;

/** Coalesce reading-line updates from scroll and layout into the next animation frame. */
function stickSoon() {
  if (!STICK_FRAME)
    STICK_FRAME = requestAnimationFrame(() => {
      STICK_FRAME = 0;
      verdictLineRenderer().stickReadingLine();
    });
}

export { verdictLineRenderer, setVerdictLineRenderer, stickSoon };
