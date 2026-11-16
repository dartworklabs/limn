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
import tseslint from 'typescript-eslint';
import { importGraph, placeOf, tableErrors, violations } from '../check_viewer_boundaries.mjs';
import { limnRules } from '../../eslint.config.mjs';

/** The rules found for a graph given as {module: [imports]}, with these tables. */
const rulesOf = (graph, allowed = []) =>
  violations(new Map(Object.entries(graph)), { allowed }).map(([rule, path]) => `${rule} ${path}`);

test('an import inside one feature passes', () => {
  assert.deepEqual(rulesOf({ 'js/pins/view-cards.ts': ['js/pins/state.ts'], 'js/pins/state.ts': [] }), []);
});

test('a cycle of modules is refused, even inside one feature', () => {
  assert.deepEqual(rulesOf({ 'js/pins/view.ts': ['js/pins/flow.ts'], 'js/pins/flow.ts': ['js/pins/view.ts'] }).sort(), [
    'cycle js/pins/flow.ts',
    'cycle js/pins/view.ts',
  ]);
});

test('a dependency between features that ALLOWED does not list is refused, and a listed one passes', () => {
  const graph = { 'js/pins/view.ts': ['js/pdf/view.ts'], 'js/pdf/view.ts': [] };
  assert.deepEqual(rulesOf(graph), ['feature-dependency js/pins/view.ts']);
  assert.deepEqual(rulesOf(graph, [['pins', 'pdf', 'a pin is marked on its page']]), []);
  assert.deepEqual(rulesOf({ 'js/pdf/view.ts': ['js/pins/view.ts'], 'js/pins/view.ts': [] }, [['pins', 'pdf', 'r']]), [
    'feature-dependency js/pdf/view.ts',
  ]);
});

test('a platform module importing a feature is refused, directly or through another platform module', () => {
  const graph = {
    'js/platform/a.ts': ['js/platform/b.ts'],
    'js/platform/b.ts': ['js/pins/state.ts'],
    'js/pins/state.ts': [],
  };
  assert.deepEqual(rulesOf(graph, [['*', 'pins', 'any']]).sort(), [
    'platform-isolation js/platform/a.ts',
    'platform-isolation js/platform/b.ts',
  ]);
});

test("a rules module importing another feature's code is refused, its surface included, even where ALLOWED lets the feature", () => {
  const graph = { 'js/pins/rules.ts': ['js/pdf/rules.ts'], 'js/pdf/rules.ts': [] };
  assert.deepEqual(rulesOf(graph, [['pins', 'pdf', 'r']]), ['role js/pins/rules.ts']);
  assert.deepEqual(rulesOf({ 'js/pins/rules.ts': ['js/pins/view.ts'], 'js/pins/view.ts': [] }), [
    'role js/pins/rules.ts',
  ]);
  assert.deepEqual(
    rulesOf({
      'js/pins/rules.ts': ['js/pins/rules-order.ts', 'js/platform/m.ts'],
      'js/pins/rules-order.ts': [],
      'js/platform/m.ts': [],
    }),
    [],
  );
});

test('nothing imports the entry point', () => {
  assert.deepEqual(rulesOf({ 'js/pins/flow.ts': ['js/main.ts'], 'js/main.ts': [] }, []).sort(), [
    'feature-dependency js/pins/flow.ts',
    'role js/pins/flow.ts',
  ]);
});

test('the path says feature and role; a path that is no place says nothing', () => {
  assert.deepEqual(placeOf('js/pins/view-cards.ts'), { feature: 'pins', role: 'view' });
  assert.deepEqual(placeOf('js/platform/markup.ts'), { feature: 'platform', role: 'lib' });
  assert.deepEqual(placeOf('js/main.ts'), { feature: 'entry', role: 'main' });
  assert.equal(placeOf('js/new.ts'), null);
  assert.equal(placeOf('js/pins/deeper/view.ts'), null);
  assert.equal(placeOf('js/pins/view.js'), null);
});

test('a mistake in the tables fails the check itself', () => {
  const base = { allowed: [], modules: ['js/pins/view.ts'] };
  assert.deepEqual(tableErrors(base), []);
  const errors = tableErrors({
    ...base,
    allowed: [
      ['pins', 'pdf', 'r'],
      ['pdf', 'pins', 'r'],
      ['pdf', 'layout', ''],
      ['layout', 'pins', 'r'],
      ['nope', 'pdf', 'r'],
    ],
    modules: ['js/pins/view.ts', 'js/new.ts', 'js/pins/deeper/view.ts', 'js/pins/painter.ts', 'js/pins/lib.ts'],
  });
  for (const expected of [
    'ALLOWED lists both pdf -> pins and pins -> pdf',
    'ALLOWED pdf -> layout has no reason',
    'ALLOWED has a cycle through',
    'ALLOWED names an unknown feature: nope -> pdf',
    'js/new.ts: no place',
    'js/pins/deeper/view.ts: no place',
    'js/pins/painter.ts: unknown role painter',
    'js/pins/lib.ts: role lib does not belong in pins',
  ]) {
    assert.ok(
      errors.some((e) => e.includes(expected)),
      `${expected}\n${errors.join('\n')}`,
    );
  }
});

test('the import graph reads named and bare imports, not type-only ones, and refuses one from outside the viewer', () => {
  const viewer = mkdtempSync(join(tmpdir(), 'limn-graph-'));
  mkdirSync(join(viewer, 'js', 'pins'), { recursive: true });
  writeFileSync(
    join(viewer, 'js', 'pins', 'view.ts'),
    "import type { T } from './types.ts';\nimport { a } from './state.ts';\nimport '../main.ts';\nexport { a };\n",
  );
  writeFileSync(join(viewer, 'js', 'pins', 'state.ts'), 'const a = 1;\nexport { a };\n');
  writeFileSync(join(viewer, 'js', 'main.ts'), '');
  const graph = importGraph(['js/pins/view.ts', 'js/pins/state.ts', 'js/main.ts'], viewer);
  assert.deepEqual(graph.get('js/pins/view.ts'), ['js/pins/state.ts', 'js/main.ts']);
  writeFileSync(join(viewer, 'js', 'main.ts'), "import x from 'lodash';\n");
  assert.throws(() => importGraph(['js/main.ts'], viewer), /not a module of the viewer/);
});

/** The local rule messages ESLint gives code, a TypeScript module, by rule id. */
function lintTs(code) {
  const linter = new Linter({ configType: 'flat' });
  return linter
    .verify(
      code,
      [
        {
          files: ['**/*.ts'],
          languageOptions: { ecmaVersion: 2024, sourceType: 'module', parser: tseslint.parser },
          plugins: { limn: { rules: limnRules } },
          rules: { 'limn/no-jsdoc-type': 'error', 'limn/no-imported-state-write': 'error' },
        },
      ],
      'module.ts',
    )
    .map((m) => m.ruleId || `fatal: ${m.message}`);
}

test('a JSDoc type in a .ts file is refused; the words of a JSDoc comment pass', () => {
  for (const comment of [
    '/** @param {number} x */',
    '/** @returns {string} */',
    '/** @type {HTMLElement} */',
    '/** @typedef Pair */',
    '/** @template T */',
  ]) {
    assert.deepEqual(lintTs(`${comment}\nfunction f(x: number): number {\n  return x;\n}\nf(1);\n`), [
      'limn/no-jsdoc-type',
    ]);
  }
  assert.deepEqual(
    lintTs('/** The width. @param x in pixels */\nfunction f(x: number) {\n  return x;\n}\nf(1);\n'),
    [],
  );
});

test("a write through another module's binding is refused; a local of the same name and a read pass", () => {
  assert.deepEqual(lintTs("import { OFF } from './state.ts';\nOFF.n=1;\nOFF.n++;\ndelete OFF.k;\n"), [
    'limn/no-imported-state-write',
    'limn/no-imported-state-write',
    'limn/no-imported-state-write',
  ]);
  assert.deepEqual(
    lintTs(
      "import { OFF } from './state.ts';\nfunction f(OFF: { n: number }){OFF.n=1;}\nf({ n: 0 });\nconst n=OFF.n;\nexport { n };\n",
    ),
    [],
  );
});

test("a write through another module's binding is refused through a type assertion too", () => {
  assert.deepEqual(
    lintTs("import { OFF } from './state.ts';\n(OFF as { n: number }).n = 1;\nOFF!.n++;\n(<any>OFF).k = 2;\n"),
    ['limn/no-imported-state-write', 'limn/no-imported-state-write', 'limn/no-imported-state-write'],
  );
});
