// The import boundaries of the viewer's ES modules (docs/adr/0042-viewer-es-modules.md D8, docs/handbook/viewer.md
// §모듈 경계), in the spirit of tools/check_boundaries.py for the server.
//
// Each module has a feature (the capability it serves) and a role (what it does within it). The path says both:
//   js/<feature>/<role>.js or js/<feature>/<role>-<topic>.js   a module of a feature
//   js/platform/<name>.js                                      a shared mechanism (feature platform, role lib)
//   js/main.js                                                 the entry point (feature entry, role main)
// The 57 modules the conversion left flat (js/<name>.js) are not in place yet: LEGACY below says their feature and
// role instead, and each counts once as `unplaced` until it moves. A flat module LEGACY does not name is an error.
//
// The rules, over every import of every module listed in parts.txt (__APP_JS__):
//   cycle               the import closes a cycle of modules (its target reaches the importer again)
//   feature-dependency  a module imports another feature's module, and ALLOWED does not list that direction
//   platform-isolation  a platform module imports a feature's module, or reaches one through other platform modules
//                       (shared code knows no feature)
//   role                a rules module imports anything but rules of its feature or platform; a state or api module
//                       anything but rules or state of its feature, app's shared state or platform; any module
//                       imports the entry point
//   unplaced            the module is a LEGACY flat file, not in its feature folder
// These count per importing module (per imported module for the import rules). tools/strict_ratchet.py holds every
// count to tools/strict-baseline.json, which only goes down: a new violation fails, and so does a count that fell
// without the baseline being lowered. A mistake in the tables here (an unknown feature or role, an ALLOWED direction
// without a reason, two directions between one pair, a cycle among the ALLOWED directions, a LEGACY entry for a file
// that is gone) fails the check outright.
//
// Run: node tools/check_viewer_boundaries.mjs          (the violations, by rule and module)
//      node tools/check_viewer_boundaries.mjs --json   ({rule: {module path: count}} for the ratchet)
import { existsSync, readFileSync } from 'node:fs';
import { dirname, join, relative, resolve, sep } from 'node:path';
import { fileURLToPath } from 'node:url';
import { parseAst } from 'rollup/parseAst';
import { stripTypes } from './strip_types.mjs';

const ROOT = resolve(dirname(fileURLToPath(import.meta.url)), '..');
const VIEWER = join(ROOT, 'src', 'limn', 'viewer');

/** The roles, and what each module of that role does. */
export const ROLES = {
  rules: 'pure decisions: values in, values out; no DOM, no request, no state of its own',
  state: 'module state and the functions that change it',
  api: 'requests to the server and the reading of their answers',
  view: 'drawing values into the DOM',
  input: 'pointer, keyboard and gesture handling',
  flow: "a feature's sequence of steps across its other roles",
  lib: 'a business-agnostic mechanism (platform only)',
  main: 'the entry point: wiring only (entry only)',
};

/** The features, bottom to top, and what each owns. Platform and entry are not features but the two ends. */
export const FEATURES = {
  platform: 'business-agnostic mechanisms: DOM markup, messages and language, requests, preferences, notices, tooltips',
  app: "the page's shared state and the closed value tables (core.js), until each value moves to the feature that owns it",
  layout: 'the frame: widths, the panel and sheet, their gestures',
  documents: 'which document is open, its meta and builds, the status line, switching and refreshing',
  pdf: "a PDF document's pages: opening, drawing, zoom, outline, page list, search, selection",
  markdown: 'a Markdown document drawn from its source',
  text: 'a text document drawn as its lines',
  revisions: 'the changes view: source diff, comparison PDF, rendered compare',
  composer: 'making a pin from a selection: the range ladder, the note, suggested edits, saving',
  pins: 'the pin list and cards, their thread, actions, replies and edits',
  verdict: 'verdict pins and the page verdict panel',
  offline: 'reading and pinning while cut off: the copies and the queue',
  entry: 'the page entry point: the click and key dispatch, boot()',
};

// The directions one feature may import another in, each with its business reason. Every feature may import platform
// (shared mechanisms) and app (the shared state and closed value tables). Together they must be acyclic.
const ANY = '*';
export const ALLOWED = [
  [ANY, 'app', 'every feature reads the shared state and compares with the closed value tables until they move'],
  ['documents', 'layout', 'the status line and the document links take their place from the frame'],
  ['pdf', 'layout', 'the pages are sized to the room the frame leaves'],
  ['pdf', 'documents', 'the pages draw the open document and its current build'],
  ['markdown', 'layout', 'the Markdown column is sized to the room the frame leaves'],
  ['markdown', 'documents', 'the Markdown surface draws the open document'],
  ['markdown', 'pdf', 'a Markdown document shares the reading position, outline and search of the page surface'],
  ['text', 'markdown', "a text document is drawn with the Markdown surface's line machinery"],
  ['revisions', 'layout', 'the changes view is sized to the room the frame leaves'],
  ['revisions', 'documents', "the changes view compares the open document's commits"],
  ['revisions', 'pdf', 'the comparison PDF is drawn with the page surface'],
  ['revisions', 'markdown', 'the rendered compare draws both sides as Markdown'],
  ['revisions', 'text', "a text document's changes are shown as its lines"],
  ['composer', 'layout', 'the composer opens in the panel or sheet the frame shows'],
  ['composer', 'documents', 'a pin is made on the open document and its build'],
  ['composer', 'pdf', "a selection on a PDF page becomes the composer's place"],
  ['composer', 'markdown', "a selection on a Markdown document becomes the composer's place"],
  ['composer', 'revisions', 'a suggested edit is shown as a diff'],
  ['pins', 'layout', 'the pin list sits in the panel or sheet the frame shows'],
  ['pins', 'documents', 'pins belong to a document and follow its builds'],
  ['pins', 'pdf', 'a pin is marked on its page and jumped to'],
  ['pins', 'markdown', 'a pin of a Markdown document is marked on its lines'],
  ['pins', 'revisions', "a pin's [변경 보기] opens the changes view"],
  ['pins', 'composer', 'editing or re-placing a pin reopens the composer'],
  ['verdict', 'layout', 'the verdict panel stands beside the pages when the frame has room'],
  ['verdict', 'documents', 'verdict words come from the open document'],
  ['verdict', 'pdf', 'a page verdict belongs to the page being read'],
  ['verdict', 'markdown', 'a verdict reads the Markdown reading position'],
  ['verdict', 'composer', "a verdict is saved from the composer's verdict row"],
  ['verdict', 'pins', 'a verdict is a pin and is drawn as one'],
  ['verdict', 'revisions', "a verdict's card can open the changes view"],
  ['offline', 'layout', 'the queued pins are listed in the panel'],
  ['offline', 'documents', 'the copies kept are per document and build'],
  ['offline', 'pdf', 'a queued pin is drawn on its page'],
  ['offline', 'markdown', 'a queued line pin is placed in its Markdown source again'],
  ['offline', 'composer', 'a pin saved while cut off is queued instead'],
  ['offline', 'pins', 'a sent queued pin becomes a pin of the list'],
  ['offline', 'verdict', 'the queue holds verdicts back and says why'],
  ['entry', ANY, 'the entry point wires every feature: the click and key dispatch call each feature'],
];

// The flat modules not yet in their feature folder: [feature, role], from what each does (parts.txt says it in a line).
export const LEGACY = {
  'js/core.ts': ['app', 'state'],
  'js/markup.ts': ['platform', 'lib'],
  'js/hidden-chars.ts': ['platform', 'lib'],
  'js/i18n.ts': ['platform', 'lib'],
  'js/prefs.ts': ['platform', 'lib'],
  'js/api.ts': ['platform', 'lib'],
  'js/notices.ts': ['platform', 'lib'],
  'js/tooltip.ts': ['platform', 'lib'],
  'js/doc-tabs.ts': ['documents', 'view'],
  'js/revisions.ts': ['revisions', 'flow'],
  'js/doc-switch.ts': ['documents', 'flow'],
  'js/boot.ts': ['documents', 'flow'],
  'js/polling.ts': ['documents', 'api'],
  'js/notify.ts': ['documents', 'flow'],
  'js/build-chip.ts': ['documents', 'view'],
  'js/updates.ts': ['documents', 'flow'],
  'js/status.ts': ['documents', 'view'],
  'js/panel-size.ts': ['layout', 'state'],
  'js/pages.ts': ['pdf', 'view'],
  'js/pdf-open.ts': ['pdf', 'api'],
  'js/outline.ts': ['pdf', 'view'],
  'js/page-list.ts': ['pdf', 'view'],
  'js/pdf-draw.ts': ['pdf', 'view'],
  'js/search.ts': ['pdf', 'flow'],
  'js/revision-zoom.ts': ['revisions', 'input'],
  'js/zoom.ts': ['pdf', 'input'],
  'js/layout.ts': ['layout', 'flow'],
  'js/gestures.ts': ['layout', 'input'],
  'js/selection.ts': ['pdf', 'input'],
  'js/levels.ts': ['composer', 'view'],
  'js/excerpt.ts': ['composer', 'view'],
  'js/figure.ts': ['pdf', 'view'],
  'js/md-surface.ts': ['markdown', 'view'],
  'js/text-surface.ts': ['text', 'view'],
  'js/md-compare.ts': ['revisions', 'view'],
  'js/suggest.ts': ['composer', 'flow'],
  'js/composer.ts': ['composer', 'flow'],
  'js/draft.ts': ['composer', 'state'],
  'js/save.ts': ['composer', 'api'],
  'js/offline.ts': ['offline', 'api'],
  'js/offline-ui.ts': ['offline', 'view'],
  'js/verdict.ts': ['verdict', 'flow'],
  'js/verdict-reason.ts': ['verdict', 'flow'],
  'js/verdict-panel.ts': ['verdict', 'view'],
  'js/sel-popover.ts': ['composer', 'view'],
  'js/card-parts.ts': ['pins', 'view'],
  'js/cards.ts': ['pins', 'view'],
  'js/review-pick.ts': ['pins', 'flow'],
  'js/list.ts': ['pins', 'flow'],
  'js/marks-hide.ts': ['pins', 'input'],
  'js/actions.ts': ['pins', 'api'],
  'js/mentions.ts': ['pins', 'input'],
  'js/reply.ts': ['pins', 'flow'],
  'js/edit.ts': ['pins', 'flow'],
  'js/repick.ts': ['composer', 'flow'],
  'js/rebuild.ts': ['documents', 'flow'],
  'js/events.ts': ['entry', 'main'],
};

export const RULES = ['cycle', 'feature-dependency', 'platform-isolation', 'role', 'unplaced'];

/** The modules parts.txt lists under __APP_JS__, as viewer-relative paths, in order. */
export function listedModules(viewer = VIEWER) {
  const out = [];
  let inJs = false;
  for (const raw of readFileSync(join(viewer, 'parts.txt'), 'utf8').split('\n')) {
    const line = raw.split('#')[0].trim();
    if (!line) continue;
    if (/^__[A-Z_]+__$/.test(line)) {
      inJs = line === '__APP_JS__';
      continue;
    }
    if (inJs) out.push(line);
  }
  return out;
}

/**
 * The feature and role of a module path, from its place or, for a flat module, from legacy; null for a flat module
 * legacy does not name.
 * @param {string} path a viewer-relative path such as js/pins/view-cards.js
 * @param {Record<string, string[]>} legacy
 * @returns {{feature: string, role: string, placed: boolean} | null}
 */
export function placeOf(path, legacy = LEGACY) {
  const parts = path.split('/');
  if (parts.length === 2 && /^main\.[jt]s$/.test(parts[1])) return { feature: 'entry', role: 'main', placed: true };
  if (parts.length === 3 && parts[1] === 'platform') return { feature: 'platform', role: 'lib', placed: true };
  if (parts.length === 3) {
    const role = parts[2].replace(/\.[jt]s$/, '').split('-')[0];
    return { feature: parts[1], role, placed: true };
  }
  const known = legacy[path];
  return known ? { feature: known[0], role: known[1], placed: false } : null;
}

/**
 * The tables' own mistakes, as messages ([] when they are sound).
 * @param {{allowed: string[][], legacy: Record<string, string[]>, modules: string[], viewer: string}} t
 */
export function tableErrors({ allowed, legacy, modules, viewer }) {
  const errors = [];
  const features = new Set(Object.keys(FEATURES));
  const pairs = new Set();
  for (const [from, to, why] of allowed) {
    if ((from !== ANY && !features.has(from)) || (to !== ANY && !features.has(to)))
      errors.push(`ALLOWED names an unknown feature: ${from} -> ${to}`);
    if (!why || !why.trim()) errors.push(`ALLOWED ${from} -> ${to} has no reason`);
    if (pairs.has(`${to} ${from}`)) errors.push(`ALLOWED lists both ${from} -> ${to} and ${to} -> ${from}`);
    pairs.add(`${from} ${to}`);
  }
  // The listed directions between named features must be acyclic.
  const next = new Map();
  for (const [from, to] of allowed) if (from !== ANY && to !== ANY) next.set(from, [...(next.get(from) || []), to]);
  const seen = new Set(),
    stack = new Set();
  const visit = (f) => {
    if (stack.has(f)) {
      errors.push(`ALLOWED has a cycle through ${f}`);
      return;
    }
    if (seen.has(f)) return;
    seen.add(f);
    stack.add(f);
    for (const t of next.get(f) || []) visit(t);
    stack.delete(f);
  };
  for (const f of next.keys()) visit(f);
  for (const [path, [feature, role]] of Object.entries(legacy)) {
    if (!features.has(feature) || !(role in ROLES))
      errors.push(`LEGACY ${path}: unknown feature or role ${feature}/${role}`);
    if (!existsSync(join(viewer, path))) errors.push(`LEGACY ${path}: no such file - take its line out`);
  }
  for (const path of modules) {
    const place = placeOf(path, legacy);
    if (!place) {
      errors.push(`${path}: a flat module LEGACY does not name - put it in js/<feature>/<role>.js`);
      continue;
    }
    if (!features.has(place.feature)) errors.push(`${path}: unknown feature ${place.feature}`);
    else if (!(place.role in ROLES))
      errors.push(`${path}: unknown role ${place.role} (one of ${Object.keys(ROLES).join(', ')})`);
    else if (
      (place.role === 'lib') !== (place.feature === 'platform') ||
      (place.role === 'main') !== (place.feature === 'entry')
    ) {
      errors.push(`${path}: role ${place.role} does not belong in ${place.feature}`);
    }
  }
  return errors;
}

/**
 * The modules each module imports, as viewer-relative paths (named and bare imports of relative paths). An import of
 * types only (`import type`) is no import: the built script never runs it.
 * @param {string[]} modules
 * @param {string} viewer
 * @returns {Map<string, string[]>}
 */
export function importGraph(modules, viewer = VIEWER) {
  const graph = new Map();
  for (const path of modules) {
    const file = join(viewer, path);
    const ast = parseAst(stripTypes(readFileSync(file, 'utf8'), path));
    const targets = [];
    for (const node of ast.body) {
      if (
        node.type !== 'ImportDeclaration' &&
        !(node.type === 'ExportNamedDeclaration' && node.source) &&
        node.type !== 'ExportAllDeclaration'
      )
        continue;
      const spec = String(node.source.value);
      if (!spec.startsWith('.')) throw new Error(`${path}: imports ${spec}, which is not a module of the viewer`);
      const target = relative(viewer, resolve(dirname(file), spec))
        .split(sep)
        .join('/');
      if (!targets.includes(target)) targets.push(target);
    }
    graph.set(path, targets);
  }
  return graph;
}

/**
 * The modules of each strongly connected component of graph, as a map from module to its component's index.
 * @param {Map<string, string[]>} graph
 */
function components(graph) {
  let index = 0;
  const order = new Map(),
    low = new Map(),
    onStack = new Set(),
    stack = [],
    comp = new Map();
  let n = 0;
  const strong = (v) => {
    order.set(v, index);
    low.set(v, index);
    index++;
    stack.push(v);
    onStack.add(v);
    for (const w of graph.get(v) || []) {
      if (!order.has(w)) {
        strong(w);
        low.set(v, Math.min(low.get(v), low.get(w)));
      } else if (onStack.has(w)) low.set(v, Math.min(low.get(v), order.get(w)));
    }
    if (low.get(v) === order.get(v)) {
      let w;
      do {
        w = stack.pop();
        onStack.delete(w);
        comp.set(w, n);
      } while (w !== v);
      n++;
    }
  };
  for (const v of graph.keys()) if (!order.has(v)) strong(v);
  return comp;
}

/**
 * The feature modules start leads to without leaving platform: start itself when it is one, else those its platform
 * modules import, each with the platform modules on the way.
 * @param {Map<string, string[]>} graph
 * @param {string} start
 * @param {Record<string, string[]>} legacy
 * @returns {Array<[string, string[]]>}
 */
function reachedThroughPlatform(graph, start, legacy) {
  const out = [],
    seen = new Set([start]),
    queue = [[start, []]];
  while (queue.length) {
    const [module, via] = queue.shift();
    const place = placeOf(module, legacy);
    if (!place) continue;
    if (place.feature !== 'platform') {
      out.push([module, via]);
      continue;
    }
    for (const next of graph.get(module) || []) {
      if (!seen.has(next)) {
        seen.add(next);
        queue.push([next, [...via, module]]);
      }
    }
  }
  return out;
}

/**
 * Every violation of graph, as [rule, importing module, message].
 * @param {Map<string, string[]>} graph
 * @param {{allowed?: string[][], legacy?: Record<string, string[]>}} [tables]
 * @returns {Array<[string, string, string]>}
 */
export function violations(graph, { allowed = ALLOWED, legacy = LEGACY } = {}) {
  const out = [];
  const comp = components(graph);
  const may = (from, to) =>
    from === to || to === 'platform' || allowed.some(([a, b]) => (a === ANY || a === from) && (b === ANY || b === to));
  for (const [path, targets] of graph) {
    const place = placeOf(path, legacy);
    if (!place) continue;
    if (!place.placed) out.push(['unplaced', path, `${path} belongs in js/${place.feature}/${place.role}.js (LEGACY)`]);
    for (const target of targets) {
      const to = placeOf(target, legacy);
      if (!to) continue;
      if (comp.get(target) === comp.get(path)) out.push(['cycle', path, `${path} -> ${target} closes a cycle`]);
      if (place.feature === 'platform') {
        // Paths count, not only direct imports: a platform module that reaches a feature through other platform
        // modules depends on it as much as the one that imports it.
        for (const [reached, via] of reachedThroughPlatform(graph, target, legacy)) {
          out.push([
            'platform-isolation',
            path,
            `${path} (platform) reaches ${reached} (${placeOf(reached, legacy).feature})${via.length ? ' through ' + via.join(' -> ') : ''}`,
          ]);
        }
      } else if (!may(place.feature, to.feature)) {
        out.push([
          'feature-dependency',
          path,
          `${path} (${place.feature}) imports ${target} (${to.feature}): ALLOWED has no ${place.feature} -> ${to.feature}`,
        ]);
      }
      const sameOrShared = to.feature === place.feature || to.feature === 'platform';
      if (to.role === 'main') out.push(['role', path, `${path} imports the entry point ${target}`]);
      else if (place.role === 'rules' && !(sameOrShared && (to.role === 'rules' || to.role === 'lib'))) {
        out.push([
          'role',
          path,
          `${path} (rules) imports ${target} (${to.feature} ${to.role}): rules import only rules of their feature and platform`,
        ]);
      } else if (
        (place.role === 'state' || place.role === 'api') &&
        !((sameOrShared || to.feature === 'app') && ['rules', 'state', 'lib'].includes(to.role))
      ) {
        out.push([
          'role',
          path,
          `${path} (${place.role}) imports ${target} (${to.feature} ${to.role}): ${place.role} imports only rules and state of its feature, app and platform`,
        ]);
      }
    }
  }
  return out;
}

/**
 * The counts the ratchet compares: {rule: {src/limn/viewer/<module>: n}}, every rule present.
 * @param {Array<[string, string, string]>} found
 */
export function counts(found) {
  const out = Object.fromEntries(RULES.map((r) => [r, {}]));
  for (const [rule, path] of found) {
    const key = `src/limn/viewer/${path}`;
    out[rule][key] = (out[rule][key] || 0) + 1;
  }
  for (const rule of RULES) out[rule] = Object.fromEntries(Object.entries(out[rule]).sort());
  return out;
}

function main(argv) {
  const modules = listedModules();
  const errors = tableErrors({ allowed: ALLOWED, legacy: LEGACY, modules, viewer: VIEWER });
  if (errors.length) {
    for (const e of errors) console.error(e);
    return 2;
  }
  const found = violations(importGraph(modules));
  if (argv.includes('--json')) {
    process.stdout.write(JSON.stringify(counts(found), null, 2) + '\n');
    return 0;
  }
  for (const [rule, , message] of found) console.log(`${rule}: ${message}`);
  const c = counts(found);
  console.log(
    RULES.map((r) => `${r} ${Object.values(c[r]).reduce((a, b) => a + b, 0)}`).join(', ') +
      ` - tools/strict_ratchet.py holds these to tools/strict-baseline.json`,
  );
  return 0;
}

if (process.argv[1] && resolve(process.argv[1]) === fileURLToPath(import.meta.url)) {
  process.exitCode = main(process.argv.slice(2));
}
