// The viewer's own checks, on cases of their own (docs/adr/0042-viewer-es-modules.md D7, D8): the boundary check's rules
// and tables (tools/check_viewer_boundaries.mjs) and the local ESLint rules (eslint.config.mjs). The CI lint job runs
// them (npm test) before the ratchet, so a check that stopped catching its violation fails there.
//
// Run: npm ci --ignore-scripts && npm test
import assert from 'node:assert/strict';
import { mkdtempSync, mkdirSync, writeFileSync } from 'node:fs';
import { tmpdir } from 'node:os';
import { join } from 'node:path';
import { test } from 'node:test';
import { Linter } from 'eslint';
import { importGraph, placeOf, tableErrors, violations } from '../check_viewer_boundaries.mjs';
import { limnRules } from '../../eslint.config.mjs';

const NONE = {};
/** The rules found for a graph given as {module: [imports]}, with these tables. */
const rulesOf = (graph, allowed = [], legacy = NONE) =>
  violations(new Map(Object.entries(graph)), { allowed, legacy }).map(([rule, path]) => `${rule} ${path}`);

test('an import inside one feature passes', () => {
  assert.deepEqual(rulesOf({ 'js/pins/view-cards.js': ['js/pins/state.js'], 'js/pins/state.js': [] }), []);
});

test('a cycle of modules is refused, even inside one feature', () => {
  assert.deepEqual(rulesOf({ 'js/pins/view.js': ['js/pins/flow.js'], 'js/pins/flow.js': ['js/pins/view.js'] }).sort(), [
    'cycle js/pins/flow.js',
    'cycle js/pins/view.js',
  ]);
});

test('a dependency between features that ALLOWED does not list is refused, and a listed one passes', () => {
  const graph = { 'js/pins/view.js': ['js/pdf/view.js'], 'js/pdf/view.js': [] };
  assert.deepEqual(rulesOf(graph), ['feature-dependency js/pins/view.js']);
  assert.deepEqual(rulesOf(graph, [['pins', 'pdf', 'a pin is marked on its page']]), []);
  assert.deepEqual(rulesOf({ 'js/pdf/view.js': ['js/pins/view.js'], 'js/pins/view.js': [] }, [['pins', 'pdf', 'r']]), [
    'feature-dependency js/pdf/view.js',
  ]);
});

test('a platform module importing a feature is refused, directly or through another platform module', () => {
  const graph = {
    'js/platform/a.js': ['js/platform/b.js'],
    'js/platform/b.js': ['js/pins/state.js'],
    'js/pins/state.js': [],
  };
  assert.deepEqual(rulesOf(graph, [['*', 'pins', 'any']]).sort(), ['platform-isolation js/platform/a.js', 'platform-isolation js/platform/b.js']);
});

test("a rules module importing another feature's code is refused, its surface included, even where ALLOWED lets the feature", () => {
  const graph = { 'js/pins/rules.js': ['js/pdf/rules.js'], 'js/pdf/rules.js': [] };
  assert.deepEqual(rulesOf(graph, [['pins', 'pdf', 'r']]), ['role js/pins/rules.js']);
  assert.deepEqual(rulesOf({ 'js/pins/rules.js': ['js/pins/view.js'], 'js/pins/view.js': [] }), ['role js/pins/rules.js']);
  assert.deepEqual(rulesOf({ 'js/pins/rules.js': ['js/pins/rules-order.js', 'js/platform/m.js'], 'js/pins/rules-order.js': [], 'js/platform/m.js': [] }), []);
});

test('nothing imports the entry point, and a flat module counts as unplaced', () => {
  const legacy = { 'js/old.js': ['pins', 'flow'] };
  assert.deepEqual(rulesOf({ 'js/old.js': ['js/main.js'], 'js/main.js': [] }, [], legacy).sort(), [
    'feature-dependency js/old.js',
    'role js/old.js',
    'unplaced js/old.js',
  ]);
});

test('the path says feature and role; a flat file says them only through LEGACY', () => {
  assert.deepEqual(placeOf('js/pins/view-cards.js', NONE), { feature: 'pins', role: 'view', placed: true });
  assert.deepEqual(placeOf('js/platform/markup.js', NONE), { feature: 'platform', role: 'lib', placed: true });
  assert.deepEqual(placeOf('js/main.js', NONE), { feature: 'entry', role: 'main', placed: true });
  assert.equal(placeOf('js/new.js', NONE), null);
});

test('a mistake in the tables fails the check itself', () => {
  const viewer = mkdtempSync(join(tmpdir(), 'limn-boundaries-'));
  mkdirSync(join(viewer, 'js'));
  writeFileSync(join(viewer, 'js', 'kept.js'), '');
  const base = { allowed: [], legacy: { 'js/kept.js': ['pins', 'view'] }, modules: ['js/kept.js'], viewer };
  assert.deepEqual(tableErrors(base), []);
  const errors = tableErrors({
    ...base,
    allowed: [['pins', 'pdf', 'r'], ['pdf', 'pins', 'r'], ['pdf', 'layout', ''], ['layout', 'pins', 'r'], ['nope', 'pdf', 'r']],
    legacy: { ...base.legacy, 'js/gone.js': ['pins', 'view'], 'js/odd.js': ['pins', 'lib'] },
    modules: ['js/kept.js', 'js/new.js', 'js/pins/painter.js', 'js/pins/lib.js'],
  });
  for (const expected of [
    'ALLOWED lists both pdf -> pins and pins -> pdf',
    'ALLOWED pdf -> layout has no reason',
    'ALLOWED has a cycle through',
    'ALLOWED names an unknown feature: nope -> pdf',
    'LEGACY js/gone.js: no such file',
    'js/new.js: a flat module LEGACY does not name',
    'js/pins/painter.js: unknown role painter',
    'js/pins/lib.js: role lib does not belong in pins',
  ]) {
    assert.ok(errors.some(e => e.includes(expected)), `${expected}\n${errors.join('\n')}`);
  }
});

test('the import graph reads named and bare imports and refuses one from outside the viewer', () => {
  const viewer = mkdtempSync(join(tmpdir(), 'limn-graph-'));
  mkdirSync(join(viewer, 'js', 'pins'), { recursive: true });
  writeFileSync(join(viewer, 'js', 'pins', 'view.js'), "import { a } from './state.js';\nimport '../main.js';\nexport { a };\n");
  writeFileSync(join(viewer, 'js', 'pins', 'state.js'), 'const a = 1;\nexport { a };\n');
  writeFileSync(join(viewer, 'js', 'main.js'), '');
  const graph = importGraph(['js/pins/view.js', 'js/pins/state.js', 'js/main.js'], viewer);
  assert.deepEqual(graph.get('js/pins/view.js'), ['js/pins/state.js', 'js/main.js']);
  writeFileSync(join(viewer, 'js', 'main.js'), "import x from 'lodash';\n");
  assert.throws(() => importGraph(['js/main.js'], viewer), /not a module of the viewer/);
});

/** The local rule messages ESLint gives code (a module), by rule id. */
function lint(code) {
  const linter = new Linter({ configType: 'flat' });
  return linter
    .verify(code, [
      {
        languageOptions: { ecmaVersion: 2024, sourceType: 'module' },
        plugins: { limn: { rules: limnRules } },
        rules: { 'limn/no-jsdoc-any': 'error', 'limn/no-jsdoc-cast': 'error', 'limn/no-imported-state-write': 'error' },
      },
    ])
    .map(m => m.ruleId || `fatal: ${m.message}`);
}

test('an any or * in a JSDoc type is refused; a named type passes', () => {
  assert.deepEqual(lint('/** @param {any} x */\nfunction f(x){return x;}\nf(1);\n'), ['limn/no-jsdoc-any']);
  assert.deepEqual(lint('/** @type {Array<*>} */\nconst a=[];\nexport { a };\n'), ['limn/no-jsdoc-any']);
  assert.deepEqual(lint('/** @param {{many: number, anyway: string}} x */\nfunction f(x){return x;}\nf({many:1,anyway:""});\n'), []);
});

test('a JSDoc cast is refused; a typed declaration is not a cast', () => {
  assert.deepEqual(lint('const e=document.body;\nconst t=/** @type {HTMLElement} */(e);\nexport { t };\n'), ['limn/no-jsdoc-cast']);
  assert.deepEqual(lint('/** @type {HTMLElement|null} */\nlet t=null;\nexport { t };\n'), []);
});

test("a write through another module's binding is refused; a local of the same name and a read pass", () => {
  assert.deepEqual(lint("import { OFF } from './offline.js';\nOFF.n=1;\nOFF.n++;\ndelete OFF.k;\n"), [
    'limn/no-imported-state-write',
    'limn/no-imported-state-write',
    'limn/no-imported-state-write',
  ]);
  assert.deepEqual(lint("import { OFF } from './offline.js';\nfunction f(OFF){OFF.n=1;}\nf({});\nconst n=OFF.n;\nexport { n };\n"), []);
});
