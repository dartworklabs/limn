// Shapes of the viewer's own screen state (docs/handbook/viewer.md §여러 문서 전환, 화면 상태의 소유자). Types only;
// none of this is stored or sent as it is.

// The open edit card (edit.js EDITOR.current): the pin it edits, its card element, the request's base revision, the
// range being edited with its ladder and snippet, the values it opened with (orig) to tell what changed.
interface EditCard {
  id: number;
  el: HTMLElement;
  base_rev: number;
  file?: string;
  name: string;
  lo?: number;
  hi?: number;
  scope: string | null;
  kind?: string;
  env: string | null;
  levels: Rung[];
  n_lines: number | null;
  snippet: string;
  orig: { lo?: number; hi?: number; scope: string | null; note: string; kind_req: string; assignee: string };
  assignee: string;
  doc: string;
  region: boolean;
  pinEl: PinElement | null;
  page: number;
  quote: string;
  kind_req: string;
}
