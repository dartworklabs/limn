// The part of KaTeX the viewer calls, as the vendored build exposes it (src/limn/vendor/katex/README.md: katex 0.19.1,
// `dist/katex.mjs`; viewer.md §타입 검사). Types only: no dependency, and only what markdown/view.ts uses, so a member
// added here is one it calls. src/limn/viewer/tests/test_vendor_katex_types.py holds it to the build: it loads the
// vendored module under node, draws a formula and a refused one with it, and checks each declared member and option
// against the real module and its SETTINGS_SCHEMA.

// The library the viewer draws math with: the module's default export, which /vendor/katex/katex.mjs gives
// (markdown/view.ts loadTexRenderer, texLibraryOf). render() draws tex into element, in place of what it held, and
// returns nothing; with throwOnError it throws a ParseError for TeX it refuses.
interface KatexLibrary {
  render(tex: string, element: HTMLElement, options: KatexRenderOptions): void;
}

// The options the viewer draws every formula with (drawTexBox), each of a type the build's SETTINGS_SCHEMA gives it.
interface KatexRenderOptions {
  displayMode: boolean;
  throwOnError: boolean;
  strict: boolean;
  trust: boolean;
}
