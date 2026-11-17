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
import ts from 'typescript';
import { importGraph, main, placeOf, tableErrors, violations } from '../check_viewer_boundaries.mjs';
import { UNCHECKED_QUERIES, limnRules } from '../../eslint.config.mjs';

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

/**
 * A viewer of its own in a temporary folder: parts.txt lists `modules` ({path: source}) under __APP_JS__ in order.
 * Returns the check's exit code and what it said, on stdout and on stderr.
 */
function checkOf(modules, argv = []) {
  const viewer = mkdtempSync(join(tmpdir(), 'limn-check-'));
  writeFileSync(join(viewer, 'parts.txt'), '__APP_JS__\n' + Object.keys(modules).join('\n') + '\n');
  for (const [path, source] of Object.entries(modules)) {
    mkdirSync(join(viewer, path, '..'), { recursive: true });
    writeFileSync(join(viewer, path), source);
  }
  const out = [],
    err = [];
  const [log, error, write] = [console.log, console.error, process.stdout.write];
  console.log = (line) => out.push(String(line));
  console.error = (line) => err.push(String(line));
  process.stdout.write = (text) => out.push(String(text)) > 0;
  try {
    return { code: main(argv, viewer), out: out.join('\n'), err: err.join('\n') };
  } finally {
    [console.log, console.error, process.stdout.write] = [log, error, write];
  }
}

test('a feature dependency ALLOWED does not list fails the check outright, naming the rule and both modules', () => {
  const got = checkOf({
    'js/pins/view-cards.ts': 'export const card = 1;\n',
    'js/pdf/view-pages.ts': "import { card } from '../pins/view-cards.ts';\nexport const page = card;\n",
  });
  assert.equal(got.code, 2);
  assert.match(
    got.err,
    /^feature-dependency: js\/pdf\/view-pages\.ts \(pdf\) imports js\/pins\/view-cards\.ts \(pins\)/m,
  );
  for (const argv of [[], ['--json']])
    assert.equal(
      checkOf({ 'js/pins/view-cards.ts': '', 'js/pdf/view-pages.ts': "import '../pins/view-cards.ts';\n" }, argv).code,
      2,
    );
});

test('a platform module reaching a feature fails the check outright, naming the rule and both modules', () => {
  const got = checkOf({
    'js/pins/state.ts': 'export const x = 1;\n',
    'js/platform/dom.ts': "import { x } from '../pins/state.ts';\nexport const y = x;\n",
  });
  assert.equal(got.code, 2);
  assert.match(
    got.err,
    /^platform-isolation: js\/platform\/dom\.ts \(platform\) reaches js\/pins\/state\.ts \(pins\)/m,
  );
});

test('a role rule broken fails the check outright, naming the rule and both modules', () => {
  const got = checkOf({
    'js/pins/view-cards.ts': 'export const card = 1;\n',
    'js/pins/rules-order.ts': "import { card } from './view-cards.ts';\nexport const order = card;\n",
  });
  assert.equal(got.code, 2);
  assert.match(got.err, /^role: js\/pins\/rules-order\.ts \(rules\) imports js\/pins\/view-cards\.ts \(pins view\)/m);
});

test('a cycle is counted for the ratchet, not failed: the check passes and its counts hold only cycle', () => {
  const modules = {
    'js/pins/view-cards.ts': "import { list } from './flow-list.ts';\nexport const card = () => list;\n",
    'js/pins/flow-list.ts': "import { card } from './view-cards.ts';\nexport const list = () => card;\n",
  };
  assert.equal(checkOf(modules).code, 0);
  const got = checkOf(modules, ['--json']);
  assert.equal(got.code, 0);
  assert.deepEqual(JSON.parse(got.out), {
    cycle: { 'src/limn/viewer/js/pins/flow-list.ts': 1, 'src/limn/viewer/js/pins/view-cards.ts': 1 },
  });
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

/** The messages ESLint's no-restricted-syntax gives code, a TypeScript module, with the viewer's UNCHECKED_QUERIES. */
function lintQueries(code) {
  const linter = new Linter({ configType: 'flat' });
  return linter
    .verify(
      code,
      [
        {
          files: ['**/*.ts'],
          languageOptions: { ecmaVersion: 2024, sourceType: 'module', parser: tseslint.parser },
          rules: { 'no-restricted-syntax': ['error', ...UNCHECKED_QUERIES] },
        },
      ],
      'module.ts',
    )
    .map((m) => m.ruleId || `fatal: ${m.message}`);
}

test('a type argument on a DOM query is refused, called plainly or optionally; the query without one and other calls pass', () => {
  for (const call of [
    "document.querySelector<HTMLInputElement>('#q');",
    "root.querySelectorAll<HTMLElement>('.row');",
    "target.closest<HTMLElement>('.card');",
    "maybe?.querySelector<HTMLDivElement>('.x');",
  ])
    assert.deepEqual(lintQueries(call), ['no-restricted-syntax'], call);
  assert.deepEqual(
    lintQueries(
      "document.querySelector('#q');\nroot.querySelectorAll('.row');\ntarget.closest('.card');\nnew Map<string, number>();\npick<number>(1);\n",
    ),
    [],
  );
});

/**
 * The limn/no-inferred-query-class messages ESLint gives code, a TypeScript module checked with the DOM types and the
 * strict set: the rule needs the type checker, so the module is written to a scratch folder and read as a program.
 */
function lintInferred(code) {
  const dir = mkdtempSync(join(tmpdir(), 'limn-inferred-'));
  const file = join(dir, 'module.ts');
  writeFileSync(file, code);
  const program = ts.createProgram([file], {
    strict: true,
    noEmit: true,
    target: ts.ScriptTarget.ES2022,
    lib: ['lib.es2022.d.ts', 'lib.dom.d.ts', 'lib.dom.iterable.d.ts'],
  });
  const linter = new Linter({ configType: 'flat', cwd: dir });
  return linter
    .verify(
      code,
      [
        {
          files: ['**/*.ts'],
          languageOptions: {
            ecmaVersion: 2024,
            sourceType: 'module',
            parser: tseslint.parser,
            parserOptions: { programs: [program] },
          },
          plugins: { limn: { rules: limnRules } },
          rules: { 'limn/no-inferred-query-class': 'error' },
        },
      ],
      file,
    )
    .map((m) => m.ruleId || `fatal: ${m.message}`);
}

test('a DOM query whose class is inferred from where its answer goes is refused; Element, a tag name and a checked find pass', () => {
  const take = 'function take(element: HTMLElement | null) { return element; }\n';
  for (const call of [
    "take(document.querySelector('.hint'));",
    "take(document.body.closest('.card'));",
    "const rows: NodeListOf<HTMLElement> = document.querySelectorAll('.row');\nrows.forEach(take);",
    "const box: HTMLDivElement | null = document.querySelector('.box');\ntake(box);",
  ])
    assert.deepEqual(lintInferred(take + call + '\n'), ['limn/no-inferred-query-class'], call);
  assert.deepEqual(
    lintInferred(
      take +
        "const found = document.querySelector('.hint');\n" +
        'take(found instanceof HTMLElement ? found : null);\n' +
        "take(document.querySelector('a'));\n" +
        "const near = document.body?.closest('.card');\n" +
        "document.querySelectorAll('.row').forEach((row) => row.remove());\n" +
        'export { near };\n',
    ),
    [],
  );
});
