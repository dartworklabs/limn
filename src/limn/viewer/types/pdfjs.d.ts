// The part of PDF.js the viewer calls, as the vendored build exposes it (src/limn/vendor/pdfjs/README.md: pdfjs-dist
// 6.3.289, `legacy/build`; viewer.md §타입 검사). Types only: no dependency, and only the members the viewer's modules
// use, so a member added here is one a module calls. Each is held to the build by
// src/limn/viewer/tests/test_vendor_pdfjs_types.py, which loads the vendored module under node, opens a small PDF and
// checks every declared member against the real objects: a name that is missing or a member of another kind fails
// there until this file follows the build.
// Where the build's own declarations (`types/src/display/api.d.ts` in the npm package) and its behaviour differ, this file
// says what the build does: getOutline() answers null for a PDF without bookmarks, an outline item always carries its
// title and children, and render() reads canvasContext.canvas, so a null context throws.

// The module the viewer imports from /vendor/pdfjs/pdf.min.mjs (pdf/flow-open.ts importPdfLibrary).
interface PdfLibrary {
  getDocument(source: PdfDocumentSource): PdfLoadingTask;
  GlobalWorkerOptions: PdfWorkerOptions;
}

// Where the library finds its worker (a class with static accessors in the build).
interface PdfWorkerOptions {
  workerSrc: string;
}

// What getDocument is given: the bytes of the PDF, with the three features the viewer turns off (eval for fonts, the
// WebAssembly decoders, XFA forms).
interface PdfDocumentSource {
  data: Uint8Array;
  isEvalSupported: boolean;
  useWasm: boolean;
  enableXfa: boolean;
}

// The load of a document (PDFDocumentLoadingTask): its promise, and destroy(), which also frees the worker's side of an
// opened document.
interface PdfLoadingTask {
  promise: Promise<PdfDocument>;
  destroy(): Promise<void>;
}

// An opened PDF document (PDFDocumentProxy). It has no destroy of its own: its loadingTask has.
interface PdfDocument {
  numPages: number;
  loadingTask: PdfLoadingTask;
  getPage(pageNumber: number): Promise<PdfPage>;
  getOutline(): Promise<PdfOutlineItem[] | null>;
  getDestination(name: string): Promise<PdfDestination | null>;
  getPageIndex(reference: PdfPageReference): Promise<number>;
}

// A page's reference in a PDF's object table, which an outline destination may name instead of a page number.
interface PdfPageReference {
  num: number;
  gen: number;
}

// An outline destination: the page (its reference, or a page index), the kind of view ({ name: 'XYZ' } carries the left,
// top and zoom that follow, each a number or null) and the view's numbers. A view with fewer numbers (Fit) has fewer
// elements, so an element past the view's name is read by its type.
type PdfDestination = [PdfPageReference | number | null, { name: string } | null, ...(number | null)[]];

// One item of a PDF's outline (a bookmark): its title, where it goes (a destination, or the name of one) and its children.
interface PdfOutlineItem {
  title: string;
  dest: string | PdfDestination | null;
  items: PdfOutlineItem[];
}

// A page of a PDF document (PDFPageProxy).
interface PdfPage {
  getViewport(options: { scale: number }): PdfViewport;
  render(options: PdfRenderOptions): PdfRenderTask;
  getTextContent(): Promise<PdfTextContent>;
}

// A page's viewport at a scale: its size, and the matrix from PDF units to the canvas.
interface PdfViewport {
  width: number;
  height: number;
  transform: number[];
}

// What render() is given: the canvas's 2D context, the viewport, and the matrix that puts the viewport on the canvas.
interface PdfRenderOptions {
  canvasContext: CanvasRenderingContext2D;
  viewport: PdfViewport;
  transform: number[];
}

// A render of a page onto a canvas: it settles when the page is drawn, and cancel() ends it early (its promise then
// rejects with a RenderingCancelledException).
interface PdfRenderTask {
  promise: Promise<void>;
  cancel(): void;
}

// A page's text (getTextContent without marked content): its items in reading order, and the styles of the fonts they
// name.
interface PdfTextContent {
  items: PdfTextItem[];
  styles: Record<string, PdfTextStyle>;
}

// One text item of a PDF page: its text, its transform matrix [a, b, c, d, e, f] (e and f: where its baseline starts),
// its width and height in PDF units, its font's name (a key of the styles) and whether a line ends after it.
interface PdfTextItem {
  str: string;
  transform: number[];
  width: number;
  height: number;
  fontName: string;
  hasEOL: boolean;
}

// A font's metrics as PDF.js gives them with the text: its family and its ascent and descent in em.
interface PdfTextStyle {
  fontFamily: string;
  ascent: number;
  descent: number;
}
